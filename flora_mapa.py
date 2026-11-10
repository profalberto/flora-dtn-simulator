"""
flora_mapa.py
=============

Base cartografica, carta nautica e exportacao de imagens.

O modulo reune tres responsabilidades:

* montar a base de satelite a partir dos tiles XYZ guardados off-line em
  ``mapa_tiles_satelite`` (imagens World Imagery, zoom 10);
* colorir a batimetria do cenario e sobrepor a hidrovia, os supernos de
  gateway, os obstaculos e a frota;
* compor a mobilia cartografica (titulo, legenda, escala, rosa dos ventos,
  graticula e quadro de metadados) e salvar a carta em PNG.

Nao depende de pygame nem de tela: usa apenas Pillow e numpy, de modo que a
mesma carta pode ser gerada no modo headless. A interface grafica reaproveita
``desenhar_carta`` convertendo a imagem resultante para superficie do pygame.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import flora_osm

from flora_geometria import (
    ALTURA_MENU_SUP,
    ALTURA_TELA_BASE,
    CANAIS,
    KM_POR_PX,
    LARGURA_SIMULACAO_BASE,
    LAT_BOTTOM,
    LAT_TOP,
    LONG_LEFT,
    LONG_RIGHT,
    geo_para_mundo,
)
from flora_cenario import (
    CORES_RISCO,
    PERFIS_TRANSVERSAIS,
    RISCO_ATENCAO,
    RISCO_CRITICO,
    RISCO_SEGURO,
    obter_cenario,
)

# ---------------------------------------------------------------------------
# 1. CONSTANTES DE APRESENTACAO
# ---------------------------------------------------------------------------
TILE_PX = 256
ZOOM_TILES = 10
PASTA_TILES_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapa_tiles_satelite")

#: Paleta de profundidade (m -> RGB). Do perigo (raso) ao azul profundo. Os
#: valores coincidem com os limiares de risco da navegacao: 0,5 m e o limite
#: critico de margem sob quilha e 2,5 m o calado das embarcacoes principais.
PALETA_BATIMETRIA: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (150, 20, 20)),
    (0.5, (200, 45, 35)),
    (1.5, (228, 120, 45)),
    (2.5, (235, 190, 55)),
    (5.0, (120, 200, 150)),
    (10.0, (45, 150, 190)),
    (18.0, (25, 95, 155)),
    (32.5, (10, 45, 105)),
]

COR_MATA = (30, 52, 32)
COR_BORDA = (232, 226, 210)
COR_FUNDO_CARTA = (18, 26, 36)
COR_GRADE = (70, 90, 110)

COR_TITULO_FUNDO = (12, 22, 34)
COR_TEXTO = (236, 240, 245)


# ---------------------------------------------------------------------------
# 2. FONTES
# ---------------------------------------------------------------------------
_FONTES_CANDIDATAS = (
    "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf",
    "calibrib.ttf", "calibri.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf",
)
_cache_fontes: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def fonte(tamanho: int, negrito: bool = False):
    """Carrega uma fonte TrueType do sistema, com recuo para a fonte padrao."""
    chave = (tamanho, negrito)
    if chave in _cache_fontes:
        return _cache_fontes[chave]
    escolhidas = _FONTES_CANDIDATAS[0::2] if negrito else _FONTES_CANDIDATAS[1::2]
    f = None
    for nome in escolhidas:
        try:
            f = ImageFont.truetype(nome, tamanho)
            break
        except OSError:
            continue
    if f is None:
        f = ImageFont.load_default()
    _cache_fontes[chave] = f
    return f


# ---------------------------------------------------------------------------
# 3. BATIMETRIA -> CORES
# ---------------------------------------------------------------------------
def cor_batimetria(prof_m: np.ndarray) -> np.ndarray:
    """
    Converte uma malha de profundidades em RGBA (uint8), com alfa crescente.

    O alfa cresce com a profundidade: o canal aparece saturado e a transicao
    para o banco desvanece ate deixar visivel a imagem de satelite por baixo.
    Onde a lamina d'agua e menor que ~0,5 m a celula e tratada como terra e
    fica totalmente transparente.
    """
    prof = np.asarray(prof_m, dtype=float)
    marcos = np.array([p for p, _ in PALETA_BATIMETRIA], dtype=float)
    cores = np.array([c for _, c in PALETA_BATIMETRIA], dtype=float)
    h, w = prof.shape
    rgb = np.empty((h, w, 3), dtype=float)
    for canal in range(3):
        rgb[..., canal] = np.interp(prof, marcos, cores[:, canal])
    # alfa: 0 em terra rasa, satura a partir de ~4 m
    alfa = np.clip((prof - 0.4) / (4.0 - 0.4), 0.0, 1.0) * 205.0
    rgba = np.empty((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    rgba[..., 3] = alfa.astype(np.uint8)
    return rgba


# ---------------------------------------------------------------------------
# 4. MOSAICO DE TILES (BASE DE SATELITE)
# ---------------------------------------------------------------------------
def _geo_para_tile_px(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Lat/lon -> pixel absoluto do esquema XYZ (256 px por tile)."""
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x * TILE_PX, y * TILE_PX


def _tile_y_para_lat(y: float, zoom: int) -> float:
    n = 2 ** zoom
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))


@dataclass
class MosaicoTiles:
    """Costura os tiles de satelite guardados em disco numa unica imagem."""

    pasta: str = PASTA_TILES_PADRAO
    zoom: int = ZOOM_TILES
    _imagem: Image.Image | None = field(default=None, init=False, repr=False)
    _origem: tuple[int, int] | None = field(default=None, init=False, repr=False)
    _disponivel: bool | None = field(default=None, init=False, repr=False)

    def _scan(self) -> list[tuple[int, int]]:
        achados: list[tuple[int, int]] = []
        if not os.path.isdir(self.pasta):
            return achados
        for nome in os.listdir(self.pasta):
            raiz, ext = os.path.splitext(nome)
            if ext.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            partes = raiz.split("_")
            if len(partes) != 3:
                continue
            try:
                z, x, y = int(partes[0]), int(partes[1]), int(partes[2])
            except ValueError:
                continue
            if z == self.zoom:
                achados.append((x, y))
        return achados

    def disponivel(self) -> bool:
        if self._disponivel is None:
            self._disponivel = len(self._scan()) > 0
        return self._disponivel

    def _montar(self) -> None:
        tiles = self._scan()
        if not tiles:
            self._imagem = None
            return
        xs = [x for x, _ in tiles]
        ys = [y for _, y in tiles]
        x0, y0 = min(xs), min(ys)
        x1, y1 = max(xs), max(ys)
        larg = (x1 - x0 + 1) * TILE_PX
        alt = (y1 - y0 + 1) * TILE_PX
        mosaico = Image.new("RGB", (larg, alt), COR_MATA)
        for x, y in tiles:
            cam = os.path.join(self.pasta, f"{self.zoom}_{x}_{y}")
            for ext in (".jpg", ".jpeg", ".png"):
                if os.path.exists(cam + ext):
                    cam = cam + ext
                    break
            else:
                continue
            try:
                tijolo = Image.open(cam).convert("RGB")
            except OSError:
                continue
            mosaico.paste(tijolo, ((x - x0) * TILE_PX, (y - y0) * TILE_PX))
        self._imagem = mosaico
        self._origem = (x0, y0)

    def base(self) -> Image.Image | None:
        """Imagem costurada completa (ou ``None`` se nao houver tiles)."""
        if self._imagem is None and self._disponivel is not False:
            self._montar()
        return self._imagem

    def recorte(
        self,
        tamanho: tuple[int, int],
        bbox: tuple[float, float, float, float] | None = None,
    ) -> Image.Image:
        """
        Recorta o bbox geografico (lat_topo, lat_base, lon_esq, lon_dir) e
        redimensiona para ``tamanho`` (largura, altura). Sem tiles, devolve um
        fundo procedural neutro.
        """
        if bbox is None:
            bbox = (LAT_TOP, LAT_BOTTOM, LONG_LEFT, LONG_RIGHT)
        larg, alt = tamanho
        base = self.base()
        if base is None or self._origem is None:
            return self._fundo_procedural(tamanho)
        lat_topo, lat_base, lon_esq, lon_dir = bbox
        px_esq, py_topo = _geo_para_tile_px(lat_topo, lon_esq, self.zoom)
        px_dir, py_base = _geo_para_tile_px(lat_base, lon_dir, self.zoom)
        ox, oy = self._origem
        px_esq -= ox * TILE_PX
        px_dir -= ox * TILE_PX
        py_topo -= oy * TILE_PX
        py_base -= oy * TILE_PX
        caixa = (int(round(px_esq)), int(round(py_topo)),
                 int(round(px_dir)), int(round(py_base)))
        caixa = (max(0, caixa[0]), max(0, caixa[1]),
                 min(base.width, caixa[2]), min(base.height, caixa[3]))
        if caixa[2] <= caixa[0] or caixa[3] <= caixa[1]:
            return self._fundo_procedural(tamanho)
        return base.crop(caixa).resize((larg, alt), Image.LANCZOS)

    def _fundo_procedural(self, tamanho: tuple[int, int]) -> Image.Image:
        """Fundo de emergencia quando os tiles nao estao disponiveis."""
        larg, alt = tamanho
        img = Image.new("RGB", (larg, alt), COR_MATA)
        dr = ImageDraw.Draw(img)
        passo = max(12, larg // 60)
        for i in range(-alt, larg, passo * 2):
            dr.line([(i, 0), (i + alt, alt)], fill=(38, 62, 40), width=1)
        return img


# ---------------------------------------------------------------------------
# 5. BASE NO ESTILO CARTA NAUTICA
# ---------------------------------------------------------------------------
#: Paleta de agua da carta (m -> RGB): claro no raso, escuro no fundo, como em
#: carta nautica impressa. E separada de `PALETA_BATIMETRIA` de proposito: aquela
#: codifica risco de encalhe e por isso usa tons quentes no raso, enquanto a
#: carta mostra a profundidade, e nao o perigo.
PALETA_AGUA_CARTA: list[tuple[float, tuple[int, int, int]]] = [
    # Muito raso / banco: azul-acinzentado claríssimo (estilo H19: branco-azulado)
    (0.0,  (208, 232, 240)),
    (0.5,  (190, 222, 234)),
    (1.0,  (170, 210, 228)),
    (2.0,  (145, 196, 220)),
    (3.0,  (122, 181, 213)),
    (5.0,  ( 96, 162, 204)),
    (8.0,  ( 72, 140, 192)),
    (12.0, ( 52, 115, 178)),
    (18.0, ( 36,  88, 158)),
    (25.0, ( 22,  65, 135)),
    (32.5, ( 12,  44, 108)),
]

#: Terra em ocre, com tres tons para o relevo sombreado oscilar em torno deles.
COR_TERRA_OCRE = (222, 205, 166)
COR_TERRA_OCRE_SOMBRA = (173, 152, 111)
COR_TERRA_OCRE_CLARO = (240, 228, 199)
COR_COSTA = (96, 76, 40)
COR_CURVA = (32, 86, 134)
COR_CURVA_MESTRA = (16, 52, 92)
COR_SONDA_ESCURA = (14, 42, 70)
COR_SONDA_CLARA = (224, 240, 247)
COR_LIMITE_CANAL = (250, 234, 132)
COR_EIXO_MAGENTA = (180, 40, 120)      # eixo do canal / thalweg no padrão H19
COR_PERIGO_TRACEJADO = (210, 50, 30)   # curvas de perigo (< 1 m)
COR_AVISO_SIMULACAO = (210, 55, 35)    # aviso "não apto para navegação"
COR_ESCALA_KM = (220, 228, 238)
MILHAS_POR_KM = 0.539957              # fator de conversão

#: Curvas de cote ao estilo carta fluvial H19 (Marinha do Brasil).
#: 1 m e 3 m: curvas de segurança críticas (encalhe / margem mínima de calado).
#: 5, 10, 20, 30 m: hierarquia padrão para hidrovias amazónicas.
#: Mestras a 10 m e 30 m, com traço mais espesso.
CURVAS_BATIMETRICAS_M: tuple[float, ...] = (1.0, 3.0, 5.0, 10.0, 20.0, 30.0)

#: Cor de cada curva de cote (RGB).
#: 1 m -> vermelho-alaranjado (perigo crítico), 3 m -> âmbar (atenção),
#: restantes -> azul convencional, mestras -> azul escuro.
_COR_CURVA_POR_M: dict[float, tuple[int, int, int]] = {
    1.0:  (210,  50,  30),
    3.0:  (200, 130,  20),
    5.0:  COR_CURVA,
    10.0: COR_CURVA_MESTRA,
    20.0: COR_CURVA,
    30.0: COR_CURVA_MESTRA,
}



#: A faixa de agua e a secao transversal dos canais, e a curva de cote e a
#: isolinha de `CURVAS_BATIMETRICAS_M`. A distincao terra/agua vem da geometria,
#: e nao de um limiar de altura: ver `flora_cenario.mascara_agua`, que explica
#: por que o modelo sem topografia nao permitiria esse outro caminho.



def _interpolar_paleta(valores: np.ndarray, paleta) -> np.ndarray:
    """Mapeia numeros para RGB usando uma paleta (marcador, cor) ja ordenada."""
    v = np.asarray(valores, dtype=float)
    marcos = np.array([p for p, _ in paleta], dtype=float)
    cores = np.array([c for _, c in paleta], dtype=float)
    saida = np.empty(v.shape + (3,), dtype=float)
    for k in range(3):
        saida[..., k] = np.interp(v, marcos, cores[:, k])
    return saida


def _relevo_ilustrativo(w: int, h: int) -> np.ndarray:
    """
    Campo de altura ilustrativo, em [0, 1], para sombrear a terra.

    O cenario hidrologico nao tem topografia, entao a terra fora d'agua viraria
    um preenchimento chapado, e uma carta chapada nao da para ler. Sao varias
    oitavas de ruido de valor, com amplitude decrescente, geradas por um LCG de
    semente fixa: a carta sai sempre igual, sem tocar no estado global do numpy
    e sem inventar uma altura com aparencia de dado medido. Como nao ha relevo
    verdadeiro, a legenda chama a camada de relevo ilustrativo.

    As oitavas sao somadas num quartero da resolucao e o resultado e ampliado
    uma vez. O campo e de baixa frequencia por construcao, entao o custo cai de
    ~170 ms para ~15 ms sem mudar o que se ve.
    """
    oitavas = (4, 8, 16, 32, 64)
    # `PIL.resize` recebe (largura, altura) e o arranjo de imagem e (altura,
    # largura), entao os dois pares sao mantidos separados aqui
    rh, rw = max(8, h // 4), max(8, w // 4)
    campo = np.zeros((rh, rw), dtype=np.float32)
    amplitude = 1.0
    total = 0.0
    semente = 20240917
    for ni, n in enumerate(oitavas):
        germe = np.random.default_rng(semente + ni * 7919)
        nq = max(2, int(round(n * rw / rh)))
        bruto = germe.random((n, nq)).astype(np.float32)
        alto = Image.fromarray((bruto * 255).astype(np.uint8), "L")
        amostra = np.asarray(alto.resize((rw, rh), Image.BILINEAR), dtype=np.float32) / 255.0
        campo += amplitude * amostra
        total += amplitude
        amplitude *= 0.55
    campo /= total
    # realce o contraste para o sombreamento ter presenca sem virar ruido
    campo = np.clip((campo - 0.5) * 1.7 + 0.5, 0.0, 1.0)
    return np.asarray(
        Image.fromarray((campo * 255).astype(np.uint8), "L").resize((w, h), Image.BICUBIC),
        dtype=np.float32,
    ) / 255.0


def _borda_binaria(mascara: np.ndarray) -> np.ndarray:
    """
    Contorno de 1 px de uma mascara booleana.

    E a intersecao da mascara com a negacao da sua erosao por 4 vizinhos, o que
    dispensa filtro de morfologia e devolve o resultado em numpy puro. Sai com
    2 px a menos em cada dimensao, entao quem chama precisa recolocar a borda.
    """
    m = mascara
    dentro = m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]
    return m[1:-1, 1:-1] & ~dentro


def _bordas_em(alvo: np.ndarray, mascara: np.ndarray, cor: tuple[int, int, int]) -> None:
    """Pinta o contorno de `mascara` sobre `alvo` in-place, com 1 px de borda."""
    borda = _borda_binaria(mascara)
    if not borda.any():
        return
    janela = alvo[1:-1, 1:-1]
    janela[borda] = cor


def _curvas_cote(rgb: np.ndarray, prof: np.ndarray, agua: np.ndarray) -> None:
    """
    Desenha as isolinhas de profundidade em uma passada so.

    Cada pixel recebe o indice da faixa em que a profundidade cai, e a curva
    de cote e o lugar onde esse indice muda de valor para o vizinho. Detectar a
    fronteira de cada nivel separadamente custaria sete erosoes da imagem
    inteira, ~130 ms; comparar o indice com os quatro vizinhos resolve as sete
    curvas de uma vez, com uma unica varredura.

    A cor vem do indice que o pixel alcanca, entao uma curva e sempre pintada
    com a cor do nivel que ela representa.
    """
    niveis = np.array([n for n in CURVAS_BATIMETRICAS_M if n <= float(prof.max())],
                      dtype=np.float32)
    if len(niveis) == 0:
        return
    # faixa de cada pixel: quantos niveis ele alcanca. O acumulo vai para um
    # arranho uint8, e nao int16, porque o valor cabe em um byte e a imagem
    # inteira cabe melhor na cache.
    banda = np.zeros(prof.shape, dtype=np.uint8)
    for nivel in niveis:
        banda += prof >= nivel

    centro = banda[1:-1, 1:-1]
    mudou = (centro != banda[:-2, 1:-1]) | (centro != banda[2:, 1:-1]) \
        | (centro != banda[1:-1, :-2]) | (centro != banda[1:-1, 2:])
    # so conta como curva quem esta em agua de um lado e terra do outro, ou
    # entre duas faixas de agua: em terra o indice ja e zero e nao ha o que cotar
    mudou &= (agua[1:-1, 1:-1] | (banda[1:-1, 1:-1] > 0))
    if not mudou.any():
        return

    cores = np.array(
        [_COR_CURVA_POR_M.get(float(n), COR_CURVA) for n in niveis],
        dtype=np.uint8,
    )
    janela = rgb[1:-1, 1:-1]
    # indice da curva e o nivel alcancado, com o zero significando a mais rasa
    indice = np.clip(banda[1:-1, 1:-1] - 1, 0, len(niveis) - 1)
    janela[mudou] = cores[indice[mudou]]





def _pontos_sondagem(w: int, h: int, escala: float, agua: np.ndarray) -> list[tuple[int, int]]:
    """
    Pontos de sondagem: grade com jitter deterministico, so dentro d'agua.

    O jitter vem de um LCG de semente fixa, de modo que o conjunto de numeros
    impressos e reprodutivel entre exportacoes. O passo cresce com a escala da
    carta para a densidade de numeros impressos ficar parecida em qualquer
    resolucao, e naoAmountar com a area em pixels.
    """
    passo = max(34, int(round(46 * escala)))
    cols = np.arange(passo // 2, w, passo)
    linhas = np.arange(passo // 2, h, passo)
    if len(cols) == 0 or len(linhas) == 0:
        return []
    malha_l, malha_c = np.meshgrid(linhas, cols, indexing="ij")
    limite = passo * 0.22
    sorteio = np.random.default_rng(917)
    malha_l = malha_l + (sorteio.random(malha_l.shape) - 0.5) * 2.0 * limite
    malha_c = malha_c + (sorteio.random(malha_c.shape) - 0.5) * 2.0 * limite
    yi = np.clip(malha_l.astype(int), 0, h - 1)
    xi = np.clip(malha_c.astype(int), 0, w - 1)
    dentro = agua[yi, xi]
    return [(int(x), int(y)) for y, x in zip(yi[dentro], xi[dentro])]


def _polilinha_borda_canal(canal, escala: float, lado: int) -> list[tuple[float, float]]:
    """Borda de largura navegavel de um canal, em pixels do raster."""
    n = max(2, len(canal.pontos_mundo))
    meios = np.linspace(0.0, canal.comprimento_km, n)
    meia = canal.largura_navegavel_km * 0.5 * lado
    saida = []
    for km in meios:
        pos, _t, _p = canal.posicao_em(float(km), meia)
        saida.append((float(pos[0]) * escala, (float(pos[1]) - ALTURA_MENU_SUP) * escala))
    return saida


def desenhar_folha_carta(
    cenario,
    t_h: float,
    tamanho: tuple[int, int],
    *,
    nx: int = 260,
    ny: int = 156,
    curvas: bool = True,
    sondagens: bool = True,
    relevo: bool = True,
    limites_canal: bool = True,
) -> Image.Image:
    """
    Base cartografica no estilo carta nautica, num raster de `tamanho` px.

    Tudo o que aparece aqui vem da batimetria do cenario: a cor da agua e a
    profundidade interpolada, as curvas sao as isolinhas da mesma malha, o
    sombreado da terra e apenas um ruido ilustrativo (nao ha topografia no
    modelo) e a faixa de agua vem da secao transversal dos canais. A carta fica
    coerente com a fisica porque e a mesma funcao que diz a profundidade sob a
    quilha.

    `escala` aqui e px de raster por px logico do canvas, e serve para dar
    espessura de traco e corpo de texto compativeis com a resolucao pedida.
    """
    from flora_cenario import grade_leito

    w, h = tamanho
    escala = w / float(LARGURA_SIMULACAO_BASE)
    prof_grade, agua_grade, _lats, _lons = grade_leito(cenario, t_h, nx, ny)
    # a grade vem em (ny, nx) com a linha 0 no norte, que e a ordem de cima para
    # baixo de uma imagem; a reamostragem preserva o alinhamento geografico.
    # `np.array` e nao `np.asarray` porque o buffer do PIL e somente leitura e a
    # linha seguinte escreve no arranjo.
    prof = np.array(
        Image.fromarray(prof_grade.astype(np.float32), "F").resize((w, h), Image.BICUBIC),
        dtype=np.float32,
    )
    # o reamostrador bicubico pode ringing nas bordas dos canais, o que daria
    # profundidade negativa e cores fora da paleta
    np.clip(prof, 0.0, None, out=prof)
    # A faixa de agua vem da geometria, interpolada no mesmo espaco do raster.
    # Reamostrar o booleano e o que mantem a linha de costa com um pixel de
    # espessura: nearest mantem o degrau, e a borda sai da diferenca entre
    # vizinhos, nao de um limiar de cor.
    agua = np.array(
        Image.fromarray((agua_grade * 255).astype(np.uint8), "L").resize(
            (w, h), Image.BILINEAR),
        dtype=np.float32,
    ) >= 128.0
    rgb = np.empty((h, w, 3), dtype=np.float32)

    # terra: ocre modulado pelo relevo ilustrativo
    if relevo:
        sombra = _relevo_ilustrativo(w, h)
        baixo = np.array(COR_TERRA_OCRE_SOMBRA, dtype=np.float32)
        alto = np.array(COR_TERRA_OCRE_CLARO, dtype=np.float32)
        # interpola baixo->alto com o campo como parametro, o que evita um laco
        # por pixel e mantem a transicao continua no meio da rampa
        rgb[:] = baixo + (alto - baixo) * sombra[..., None]
    else:
        rgb[:] = np.array(COR_TERRA_OCRE, dtype=np.float32)

    # agua: gradiente de profundidade. A paleta e aplicada so aos valores que
    # sao agua: passar o arranjo inteiro por `np.interp` custa ~137 ms para tres
    # canais, contra ~31 ms para a fração que e agua, porque o rio ocupa uma
    # faixa estreita do quadro. A atribuicao mascarada devolve entao a faixa ao
    # seu lugar, que e o mesmo que `rgb[agua] = ...` faria.
    rgb[agua] = _interpolar_paleta(prof[agua], PALETA_AGUA_CARTA)

    # linha de costa e curvas de cote, so na agua
    _bordas_em(rgb, agua, COR_COSTA)
    if curvas:
        _curvas_cote(rgb, prof, agua)

    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(img, "RGBA")

    if limites_canal:
        for canal in CANAIS.values():
            for lado in (-1.0, 1.0):
                pts = _polilinha_borda_canal(canal, escala, lado)
                dr.line(pts, fill=COR_LIMITE_CANAL + (215,),
                        width=max(1, int(round(escala))))

    if sondagens:
        corpo = max(7, int(round(9 * escala)))
        f_norm   = fonte(corpo, False)
        f_critica = fonte(max(7, int(round(10 * escala))), True)   # negrito para zona crítica
        for x, y in _pontos_sondagem(w, h, escala, agua):
            v = float(prof[y, x])
            # H19: dois decimais < 2 m, um decimal < 5 m, inteiro acima
            if v < 2.0:
                rot = f"{v:.2f}"
                cor = (200, 40, 20)    # vermelho: perigo crítico
                f_s = f_critica
            elif v < 5.0:
                rot = f"{v:.1f}"
                cor = (190, 110, 10)   # âmbar: zona de atenção
                f_s = f_critica
            elif v >= 10.0:
                rot = f"{v:.0f}"
                cor = COR_SONDA_CLARA
                f_s = f_norm
            else:
                rot = f"{v:.1f}"
                cor = COR_SONDA_CLARA
                f_s = f_norm
            dr.text((x, y), rot, font=f_s, fill=cor + (220,), anchor="mm")

    return img


# ---------------------------------------------------------------------------
# 6. PROJECAO DA CARTA
# ---------------------------------------------------------------------------
@dataclass
class ProjecaoCarta:
    """Mundo logico (px do canvas) -> pixel da carta."""

    escala: float
    origem: tuple[int, int]

    def de_mundo(self, x: float, y_mundo: float) -> tuple[float, float]:
        ox, oy = self.origem
        return (ox + x * self.escala, oy + (y_mundo - ALTURA_MENU_SUP) * self.escala)

    def de_geo(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = geo_para_mundo(lat, lon)
        return self.de_mundo(float(x), float(y))

    def de_ponto(self, ponto) -> tuple[float, float]:
        return self.de_mundo(float(ponto[0]), float(ponto[1]))

    def tamanho_mapa(self) -> tuple[int, int]:
        return (int(round(LARGURA_SIMULACAO_BASE * self.escala)),
                int(round(ALTURA_TELA_BASE * self.escala)))


@dataclass
class OpcoesCarta:
    """Liga/desliga camadas e define o acabamento da carta."""

    escala: float = 1.6
    nx: int = 260
    ny: int = 156
    base_carta: bool = True
    base_satelite: bool = False
    curvas_batimetricas: bool = True
    sondagens: bool = True
    relevo_sombreado: bool = True
    limites_canal: bool = True
    #: Tinta de profundidade por cima do fundo, a mesma de `cor_batimetria`.
    #: Desligada por padrao porque com a folha de carta ligada ela e redundante:
    #: a propria folha ja pinta a agua pela rampa de profundidade, e a segunda
    #: rampa, com alfa ate 205, acaba lavando o gradiente e as curvas de cote.
    #: Ligada, ela volta a ter sentido sobre o mosaico de satelite, que e o caso
    #: em que a cor de fundo nao diz nada sobre o leito.
    batimetria: bool = False
    grade_geografica: bool = True
    escala_grafica: bool = True
    rosa_dos_ventos: bool = True
    rastro_frota: bool = True
    circulos_alcance: bool = True
    rotas: bool = True
    marcos_km: bool = True
    waypoints_rota: bool = True
    legenda: bool = True
    quadro_metadados: bool = True
    rodape: str = "CARTA DE SIMULACAO - NAO APTA PARA NAVEGACAO"


# ---------------------------------------------------------------------------
# 6. COMPOSICAO DA CARTA
# ---------------------------------------------------------------------------
class CartaNautica:
    """Desenha a carta nautica de um cenario num dado instante."""

    MARGEM = 24
    ALTURA_TITULO = 58
    ALTURA_RODAPE = 30
    LARGURA_LEGENDA = 248
    #: Altura da caixa da legenda para comportar batimetria, rota, estacas, riscos e escala.
    ALTURA_LEGENDA = 560

    def __init__(self, opcoes: OpcoesCarta | None = None) -> None:
        self.op = opcoes or OpcoesCarta()
        self.mosaico = MosaicoTiles()

    # -- dimensoes -------------------------------------------------------
    def _dimensoes(self) -> tuple[int, int, int, int]:
        larg_mapa = int(round(LARGURA_SIMULACAO_BASE * self.op.escala))
        alt_mapa = int(round(ALTURA_TELA_BASE * self.op.escala))
        extra = self.LARGURA_LEGENDA if self.op.legenda else 0
        # a legenda e uma coluna ao lado do mapa, entao a folha precisa ser alta o
        # bastante para ela, e nao apenas para o mapa
        altura_util = max(alt_mapa, self.ALTURA_LEGENDA if self.op.legenda else 0)
        larg = self.MARGEM * 2 + larg_mapa + extra
        alt = self.MARGEM * 2 + self.ALTURA_TITULO + altura_util + self.ALTURA_RODAPE
        return larg, alt, larg_mapa, alt_mapa

    def _projecao(self) -> ProjecaoCarta:
        origem = (self.MARGEM, self.MARGEM + self.ALTURA_TITULO)
        return ProjecaoCarta(self.op.escala, origem)

    # -- render ----------------------------------------------------------
    def render(self, cenario, t_h: float, motor=None, titulo: str | None = None) -> Image.Image:
        larg, alt, larg_mapa, alt_mapa = self._dimensoes()
        img = Image.new("RGB", (larg, alt), COR_FUNDO_CARTA)
        dr = ImageDraw.Draw(img, "RGBA")
        proj = self._projecao()

        self._desenhar_base(img, proj, larg_mapa, alt_mapa, cenario, t_h)
        if self.op.grade_geografica:
            self._desenhar_graticula(dr, proj, larg_mapa, alt_mapa)
        self._desenhar_canais(dr, proj)
        self._desenhar_obstaculos(dr, proj, cenario, t_h)
        self._desenhar_supernos(dr, proj, motor)
        self._desenhar_frota(dr, proj, motor)
        self._desenhar_titulo(dr, titulo, cenario, t_h, larg)
        self._desenhar_rodape(dr, larg, alt)
        if self.op.legenda:
            self._desenhar_legenda(dr, proj, larg_mapa, alt_mapa, cenario)
        if self.op.quadro_metadados and motor is not None:
            self._desenhar_metadados(img, motor)
        self._desenhar_moldura(dr, larg, alt, larg_mapa, alt_mapa)
        return img

    # -- base ------------------------------------------------------------
    def _desenhar_base(self, img, proj, larg_mapa, alt_mapa, cenario, t_h) -> None:
        """
        Escolhe o fundo do mapa: folha de carta nautica ou imagem de satelite.

        A folha e o padrao. O mosaico de satelite continua disponivel como
        alternativa, porque ele mostra a geografia real e serve de conferencia
        visual para a geometria do modelo.
        """
        t_amostra = t_h if cenario is not None else 0.0
        if self.op.base_carta:
            fundo = desenhar_folha_carta(
                cenario, t_amostra, (larg_mapa, alt_mapa),
                nx=self.op.nx, ny=self.op.ny,
                curvas=self.op.curvas_batimetricas,
                sondagens=self.op.sondagens,
                relevo=self.op.relevo_sombreado,
                limites_canal=self.op.limites_canal,
            )
        elif self.op.base_satelite and self.mosaico.disponivel():
            # O mosaico em disco tem 1536 px de largura para a janela, quase o
            # dobro do que a carta desenha. Recortar direto no tamanho da carta
            # jogava fora metade dos pixels e o satelite saia lavado; o recorte
            # vai na resolucao do arquivo e e reamostrado para a carta.
            fundo = self.mosaico.recorte(
                (larg_mapa, alt_mapa), (LAT_TOP, LAT_BOTTOM, LONG_LEFT, LONG_RIGHT))
            if fundo.size != (larg_mapa, alt_mapa):
                fundo = fundo.resize((larg_mapa, alt_mapa), Image.LANCZOS)
        else:
            fundo = MosaicoTiles()._fundo_procedural((larg_mapa, alt_mapa))
        img.paste(fundo, proj.origem)
        if not self.op.batimetria:
            return
        from flora_cenario import grade_profundidade

        prof, _lats, _lons = grade_profundidade(cenario, t_amostra, self.op.nx, self.op.ny)
        rgba = cor_batimetria(prof)
        sobrepor = Image.fromarray(rgba, "RGBA").resize((larg_mapa, alt_mapa), Image.BILINEAR)
        base = img.crop((proj.origem[0], proj.origem[1],
                         proj.origem[0] + larg_mapa, proj.origem[1] + alt_mapa)).convert("RGBA")
        base.alpha_composite(sobrepor)
        img.paste(base.convert("RGB"), proj.origem)

    # -- camadas ---------------------------------------------------------
    def _desenhar_graticula(self, dr, proj, larg_mapa, alt_mapa) -> None:
        lons = []
        lon = math.ceil(LONG_LEFT * 4) / 4.0
        while lon <= LONG_RIGHT:
            lons.append(lon)
            x0 = proj.de_geo(LAT_TOP, lon)[0]
            x1 = proj.de_geo(LAT_BOTTOM, lon)[0]
            dr.line([(x0, proj.origem[1]), (x1, proj.origem[1] + alt_mapa)],
                    fill=(*COR_GRADE, 120), width=1)
            lon_hemi = "W" if lon < 0 else "E"
            a_lon = round(abs(lon), 4)
            rot_lon = f"{int(a_lon)}°{int(round(a_lon * 60)) % 60}'{lon_hemi}"
            dr.text((x0 + 3, proj.origem[1] + alt_mapa - 16), rot_lon,
                    font=fonte(11), fill=(*COR_GRADE, 220))
            lon += 0.25
        lats = []
        lat = math.ceil(LAT_BOTTOM * 4) / 4.0
        while lat <= LAT_TOP:
            lats.append(lat)
            y0 = proj.de_geo(lat, LONG_LEFT)[1]
            y1 = proj.de_geo(lat, LONG_RIGHT)[1]
            dr.line([(proj.origem[0], y0), (proj.origem[0] + larg_mapa, y1)],
                    fill=(*COR_GRADE, 120), width=1)
            lat_hemi = "S" if lat < 0 else "N"
            a_lat = round(abs(lat), 4)
            rot_lat = f"{int(a_lat)}°{int(round(a_lat * 60)) % 60}'{lat_hemi}"
            dr.text((proj.origem[0] + 4, y0 - 14), rot_lat,
                    font=fonte(11), fill=(*COR_GRADE, 220))
            lat += 0.25
        for glat in lats:
            for glon in lons:
                cx, cy = proj.de_geo(glat, glon)
                dr.line([(cx - 4, cy), (cx + 4, cy)], fill=(*COR_GRADE, 200), width=1)
                dr.line([(cx, cy - 4), (cx, cy + 4)], fill=(*COR_GRADE, 200), width=1)

    def _desenhar_canais(self, dr, proj) -> None:
        for canal in CANAIS.values():
            pts = [proj.de_ponto(p) for p in canal.pontos_mundo]
            if len(pts) < 2:
                continue
            esc = proj.escala
            larg = max(3, int(round(canal.largura_navegavel_km * 2 / KM_POR_PX * esc)))

            # 1. Faixa navegavel (Fairway do canal comercial)
            dr.line(pts, fill=(18, 52, 90, 100), width=larg + 4)
            dr.line(pts, fill=(30, 85, 145, 65), width=larg)

            # 2. Bordas laterais do canal navegavel (margens de bombordo e boreste)
            meia_km = canal.largura_navegavel_km * 0.5
            n_amostras = max(35, int(canal.comprimento_km * 0.5))
            kms = np.linspace(0.0, canal.comprimento_km, n_amostras)
            for lado in (-1, 1):
                pts_borda = [
                    proj.de_ponto(canal.posicao_em(float(k), meia_km * lado)[0])
                    for k in kms
                ]
                dr.line(pts_borda, fill=(65, 135, 195, 160), width=max(1, int(round(1.0 * esc))))

            # 3. Eixo central recomendado de navegacao (Recommended Track / Thalweg)
            dr.line(pts, fill=(8, 22, 38, 235), width=max(3, int(round(3.8 * esc))), joint="curve")
            dr.line(pts, fill=(240, 248, 255, 250), width=max(1, int(round(1.8 * esc))), joint="curve")

            # 4. Setas de orientacao e fluxo (sentido montante -> jusante / Manaus -> Itacoatiara)
            self._desenhar_setas_rota(dr, proj, canal)

            # 5. Estacas quilometricas ao longo da rota
            if self.op.marcos_km:
                self._desenhar_marcas_km(dr, proj, canal)

            # 6. Waypoints notaveis da rota
            if self.op.waypoints_rota:
                self._desenhar_waypoints_rota(dr, proj, canal)

    def _desenhar_setas_rota(self, dr, proj, canal) -> None:
        total = canal.comprimento_km
        passo_km = 30.0
        s = max(5, int(round(7.0 * proj.escala)))
        for km in np.arange(15.0, total - 10.0, passo_km):
            p, t_vec, n_vec = canal.posicao_em(float(km), 0.0)
            x, y = proj.de_ponto(p)
            tx, ty = float(t_vec[0]), float(t_vec[1])
            nx, ny = float(n_vec[0]), float(n_vec[1])
            tip = (x + tx * s, y + ty * s)
            left = (x - tx * s * 0.7 + nx * s * 0.6, y - ty * s * 0.7 + ny * s * 0.6)
            right = (x - tx * s * 0.7 - nx * s * 0.6, y - ty * s * 0.7 - ny * s * 0.6)
            inner = (x - tx * s * 0.3, y - ty * s * 0.3)
            dr.polygon([tip, left, inner, right], fill=(255, 255, 255, 230), outline=(10, 25, 45, 255))

    def _desenhar_marcas_km(self, dr, proj, canal) -> None:
        total = canal.comprimento_km
        f_km = fonte(max(8, int(round(9 * proj.escala))), negrito=True)
        dist_offset = max(14, int(round(16 * proj.escala)))
        for km in range(0, int(total) + 1, 25):
            p, _t, n_vec = canal.posicao_em(float(km), 0.0)
            x, y = proj.de_ponto(p)
            nx, ny = float(n_vec[0]), float(n_vec[1])

            # Ponto de estaca no eixo
            r_pt = max(2, int(round(3 * proj.escala)))
            dr.ellipse([x - r_pt, y - r_pt, x + r_pt, y + r_pt],
                       fill=(255, 255, 255, 240), outline=(12, 28, 48, 255), width=1)

            # Offset alternado
            lado = -1.0 if (km // 25) % 2 == 0 else 1.0
            bx = x + nx * dist_offset * lado
            by = y + ny * dist_offset * lado

            texto = f"km {km}"
            bbox = dr.textbbox((bx, by), texto, font=f_km, anchor="mm")
            pad_x, pad_y = 4, 2
            rect = [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y]

            dr.line([(x, y), (bx, by)], fill=(80, 150, 220, 180), width=1)
            dr.rounded_rectangle(rect, radius=3, fill=(12, 24, 40, 230),
                                 outline=(90, 160, 230, 240), width=1)
            dr.text((bx, by), texto, font=f_km, fill=(230, 242, 255, 255), anchor="mm")

    def _desenhar_waypoints_rota(self, dr, proj, canal) -> None:
        from flora_geometria import COORDENADAS_ROTA_NAVEGACAO

        rotulos_marcos = {
            "Manaus": "Porto de Manaus (km 0.0)",
            "Bifurcacao_Careiro_Entrada": "Bifurcação Careiro (km 24.8)",
            "Boca_do_Preto_da_Eva": "Foz Rio Preto da Eva (km 145.2)",
            "Itacoatiara": "Terminal Itacoatiara (km 208.4)",
        }

        f_wp = fonte(max(9, int(round(10 * proj.escala))), negrito=True)
        r_wp = max(5, int(round(6 * proj.escala)))

        for chave, (lat, lon) in COORDENADAS_ROTA_NAVEGACAO.items():
            x, y = proj.de_geo(lat, lon)
            rotulo = rotulos_marcos.get(chave, chave)

            dr.ellipse([x - r_wp - 2, y - r_wp - 2, x + r_wp + 2, y + r_wp + 2],
                       outline=(255, 214, 92, 240), width=2)
            dr.ellipse([x - r_wp, y - r_wp, x + r_wp, y + r_wp],
                       fill=(20, 35, 55, 240), outline=(15, 25, 40, 255), width=1)
            dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 214, 92, 255))

            # Posiciona o rotulo: para pontos intermediarios ou extremos
            y_texto = y + r_wp + 8 if chave in ("Manaus", "Itacoatiara") else y - r_wp - 8
            anchor_pos = "mt" if chave in ("Manaus", "Itacoatiara") else "ms"

            bbox = dr.textbbox((x, y_texto), rotulo, font=f_wp, anchor=anchor_pos)
            pad_x, pad_y = 5, 3
            rect = [bbox[0] - pad_x, bbox[1] - pad_y, bbox[2] + pad_x, bbox[3] + pad_y]

            dr.rounded_rectangle(rect, radius=4, fill=(10, 20, 32, 240),
                                 outline=(255, 214, 92, 220), width=1)
            dr.text((x, y_texto), rotulo, font=f_wp,
                    fill=(255, 245, 220, 255), anchor=anchor_pos)

    def _desenhar_obstaculos(self, dr, proj, cenario, t_h) -> None:
        if cenario is None:
            return
        for obst in cenario.obstaculos_ativos(t_h):
            x, y = proj.de_ponto(obst.posicao_px)
            r = max(6, int(round(obst.raio_km / KM_POR_PX * proj.escala)))
            # zona de perigo: círculo tracejado vermelho (IHO S-57 estilo)
            dr.ellipse([x - r, y - r, x + r, y + r],
                       outline=(210, 50, 30, 200), width=2)
            # círculo interno sólido menor
            ri = max(3, r // 3)
            dr.ellipse([x - ri, y - ri, x + ri, y + ri],
                       fill=(225, 60, 40, 130), outline=(255, 180, 80, 255), width=1)
            # símbolo + (baixio/shoal IHO)
            arm = max(4, r // 2)
            dr.line([(x - arm, y), (x + arm, y)], fill=(210, 50, 30, 230), width=2)
            dr.line([(x, y - arm), (x, y + arm)], fill=(210, 50, 30, 230), width=2)
            dr.text((x + r + 3, y - 10), obst.rotulo, font=fonte(11, True), fill=(255, 210, 160, 255))
            if obst.profundidade_residual_m is not None:
                dr.text((x + r + 3, y + 2), f"{obst.profundidade_residual_m:.1f} m",
                        font=fonte(9), fill=(255, 180, 100, 220))

    def _desenhar_supernos(self, dr, proj, motor) -> None:
        if motor is None:
            return
        for sn in motor.supernos:
            x, y = proj.de_ponto(sn.pos)
            if self.op.circulos_alcance:
                r = sn.alcance_km / KM_POR_PX * proj.escala
                dr.ellipse([x - r, y - r, x + r, y + r], outline=(70, 240, 120, 130), width=1)
            # símbolo de rádio-baliza IHO (círculo + raios em leque)
            s = 7
            dr.ellipse([x - s, y - s, x + s, y + s], fill=(40, 220, 110, 255),
                       outline=(10, 60, 30, 255), width=2)
            # 3 raios superiores (arco de 120°)
            import math as _m
            for ang_deg in (-60, 0, 60):
                a = _m.radians(ang_deg - 90)
                x2 = x + _m.cos(a) * (s + 10)
                y2 = y + _m.sin(a) * (s + 10)
                dr.line([(x, y), (x2, y2)], fill=(40, 220, 110, 200), width=1)
            dr.text((x + s + 4, y - 18), sn.nome, font=fonte(11, True), fill=(180, 255, 200, 255))
            dr.text((x + s + 4, y - 5), f"km {sn.km_canal:.0f}", font=fonte(9),
                    fill=(200, 240, 210, 255))
            if sn.movel:
                dr.text((x + s + 4, y + 6), "(móvel)", font=fonte(8), fill=(255, 210, 100, 200))

    def _desenhar_frota(self, dr, proj, motor) -> None:
        if motor is None:
            return
        if self.op.rastro_frota:
            for no in motor.frota:
                if len(no.historico) < 2:
                    continue
                pts = [proj.de_ponto(p) for p in no.historico]
                dr.line(pts, fill=(*no.cor_base, 70), width=2)
        for no in motor.frota:
            x, y = proj.de_ponto(no.pos)
            cor = no.cor_risco if no.classe_risco != RISCO_SEGURO else no.cor_base
            s = max(4, int(round(no.tamanho * 0.5 * proj.escala)))
            if no.classe_risco != RISCO_SEGURO:
                dr.ellipse([x - s - 4, y - s - 4, x + s + 4, y + s + 4],
                           outline=(*cor, 230), width=2)
            dr.ellipse([x - s, y - s, x + s, y + s], fill=(*cor, 255),
                       outline=(15, 25, 35, 255), width=1)

    # -- mobilia ---------------------------------------------------------
    def _desenhar_titulo(self, dr, titulo, cenario, t_h, larg) -> None:
        dr.rectangle([0, 0, larg, self.MARGEM + self.ALTURA_TITULO - 4], fill=COR_TITULO_FUNDO)
        # borda interna do bloco de título (estilo DHN)
        dr.rectangle([self.MARGEM - 4, 2, larg - self.MARGEM + 4, self.MARGEM + self.ALTURA_TITULO - 6],
                     outline=(80, 100, 130, 180), width=1)
        nome = titulo or "CARTA NÁUTICA DE SIMULAÇÃO — CALHA DO AMAZONAS (MANAUS–ITACOATIARA)"
        dr.text((self.MARGEM, 10), nome, font=fonte(20, True), fill=COR_TEXTO)
        if cenario is not None:
            sub = (f"Cenário {cenario.codigo} — {cenario.nome}   |   t = {t_h:.1f} h"
                   f"   |   nível do rio = {cenario.nivel_rio_m(t_h):+.2f} m"
                   f"   |   Datum: WGS-84   |   Projeção: Mercator")
            dr.text((self.MARGEM, 36), sub, font=fonte(12), fill=(175, 200, 225))
        # aviso de simulação (canto direito do bloco, em vermelho)
        aviso = "NÃO APTA PARA NAVEGAÇÃO"
        bbox = dr.textbbox((0, 0), aviso, font=fonte(11, True))
        aw = bbox[2] - bbox[0]
        dr.text((larg - self.MARGEM - aw, 10), aviso, font=fonte(11, True),
                fill=(210, 55, 35))
        dr.text((larg - self.MARGEM - aw, 28), "CARTA DE SIMULAÇÃO / FLoRA-UFAM",
                font=fonte(9), fill=(140, 160, 185))

    def _desenhar_rodape(self, dr, larg, alt) -> None:
        y = alt - self.ALTURA_RODAPE + 4
        # fundo vermelho escuro para o aviso
        dr.rectangle([self.MARGEM - 4, y - 2, self.MARGEM + 300, y + 20],
                     fill=(80, 18, 18, 230), outline=(160, 40, 30, 200), width=1)
        dr.text((self.MARGEM, y), self.op.rodape, font=fonte(11, True), fill=(240, 100, 80))
        dr.text((larg // 2 - 80, y), "FLoRA-DTN / UFAM — Simulador DTN-LoRa   |   WGS-84 / Mercator",
                font=fonte(10), fill=(150, 175, 195))
        credito = flora_osm.credito_carta()
        if credito:
            dr.text((larg - self.MARGEM, y), credito, font=fonte(10),
                    fill=(140, 160, 180), anchor="ra")

    def _desenhar_legenda(self, dr, proj, larg_mapa, alt_mapa, cenario) -> None:
        x0 = proj.origem[0] + larg_mapa + 12
        y0 = proj.origem[1]
        larg = self.LARGURA_LEGENDA - 16
        dr.rectangle([x0, y0, x0 + larg, y0 + self.ALTURA_LEGENDA],
                     fill=(14, 24, 38, 230), outline=(90, 120, 150, 255), width=1)
        dr.text((x0 + 8, y0 + 6), "LEGENDA", font=fonte(13, True), fill=COR_TEXTO)
        y = y0 + 30
        # escala de profundidade
        for i, (prof, cor) in enumerate(PALETA_BATIMETRIA):
            yy = y + i * 14
            dr.rectangle([x0 + 8, yy, x0 + 34, yy + 12], fill=(*cor, 255))
            rot = f"< {PALETA_BATIMETRIA[i + 1][0]:.1f} m" if i + 1 < len(PALETA_BATIMETRIA) else f"> {prof:.1f} m"
            if i == 0:
                rot = f"< {PALETA_BATIMETRIA[1][0]:.1f} m"
            dr.text((x0 + 40, yy - 1), rot, font=fonte(10), fill=(210, 220, 230))
        y += len(PALETA_BATIMETRIA) * 14 + 10
        itens = [
            ("rota", (240, 248, 255), "Eixo da rota (rumo recomendado)"),
            ("fairway", (65, 135, 195), "Faixa navegavel / Fairway (3 km)"),
            ("estaca", (90, 160, 230), "Estacas quilometricas (km)"),
            ("waypoint", (255, 214, 92), "Marco / porto da rota"),
            ("superno", (40, 220, 110), "Superno de gateway (LoRaWAN)"),
            ("obstaculo", (225, 60, 40), "Obstaculo / baixio"),
        ]
        for estilo, cor, rot in itens:
            if estilo == "rota":
                dr.line([(x0 + 8, y + 5), (x0 + 34, y + 5)], fill=(8, 22, 38, 255), width=4)
                dr.line([(x0 + 8, y + 5), (x0 + 34, y + 5)], fill=(*cor, 255), width=2)
            elif estilo == "fairway":
                dr.rectangle([x0 + 8, y + 1, x0 + 34, y + 9], fill=(20, 65, 115, 120),
                             outline=(*cor, 255), width=1)
            elif estilo == "estaca":
                dr.rounded_rectangle([x0 + 10, y + 1, x0 + 32, y + 11], radius=2,
                                     fill=(12, 24, 40, 255), outline=(*cor, 255), width=1)
            elif estilo == "waypoint":
                dr.ellipse([x0 + 17, y + 1, x0 + 25, y + 9], fill=(20, 35, 55, 255),
                           outline=(*cor, 255), width=2)
                dr.ellipse([x0 + 20, y + 4, x0 + 22, y + 6], fill=(*cor, 255))
            else:
                dr.rectangle([x0 + 8, y, x0 + 34, y + 10], fill=(*cor, 255))
            dr.text((x0 + 40, y - 2), rot, font=fonte(10), fill=(210, 220, 230))
            y += 16
        for classe in (RISCO_SEGURO, RISCO_ATENCAO, RISCO_CRITICO):
            cor = CORES_RISCO[classe]
            dr.ellipse([x0 + 12, y, x0 + 30, y + 14], fill=(*cor, 255),
                       outline=(15, 25, 35, 255))
            dr.text((x0 + 40, y - 1), f"Embarcacao - risco {classe.lower()}",
                    font=fonte(10), fill=(210, 220, 230))
            y += 16
        # camadas proprias da folha de carta nautica
        if self.op.base_carta:
            y += 2
            dr.text((x0 + 8, y), "FOLHA DE CARTA", font=fonte(10, True),
                    fill=(210, 220, 230))
            y += 14
            amostras = (
                (COR_CURVA_MESTRA, "Curva de cote (mestra)"),
                (COR_CURVA, "Curva de cote (normal)"),
                (COR_COSTA, "Linha de costa"),
                (COR_LIMITE_CANAL, "Limite navegavel"),
            )
            for cor, rot in amostras:
                dr.line([(x0 + 8, y + 5), (x0 + 34, y + 5)], fill=(*cor, 255), width=2)
                dr.text((x0 + 40, y - 1), rot, font=fonte(10), fill=(210, 220, 230))
                y += 14
            dr.text((x0 + 40, y - 1), "Sondagem (profundidade em m)",
                    font=fonte(10), fill=(210, 220, 230))
            y += 14
            dr.rectangle([x0 + 8, y, x0 + 34, y + 10], fill=(*COR_TERRA_OCRE, 255),
                         outline=COR_TERRA_OCRE_SOMBRA)
            dr.text((x0 + 40, y - 2), "Terra (relevo ilustrativo)",
                    font=fonte(10), fill=(210, 220, 230))
            y += 18
        if self.op.escala_grafica:
            self._desenhar_escala(dr, x0 + 8, y + 6, larg - 16)
        if self.op.rosa_dos_ventos:
            self._desenhar_rosa(dr, x0 + larg // 2, y + 78, 13)

    def _desenhar_escala(self, dr, x, y, larg_max) -> None:
        km_total = larg_max * KM_POR_PX / self.op.escala
        alvo = next((v for v in (10, 20, 25, 50, 100, 200) if v >= km_total * 0.6), 200)
        px = alvo / KM_POR_PX * self.op.escala
        # linha de título
        dr.text((x, y - 14), f"ESCALA  0 — {alvo} km  /  0 — {alvo * 0.539957:.0f} Mn",
                font=fonte(9, True), fill=(220, 228, 238))
        n = 4
        passo = px / n
        # barra km
        for i in range(n):
            cor = (230, 230, 230) if i % 2 == 0 else (40, 40, 40)
            dr.rectangle([x + i * passo, y, x + (i + 1) * passo, y + 7], fill=cor,
                         outline=(180, 180, 180))
        dr.text((x, y + 8), "0", font=fonte(8), fill=(210, 220, 230))
        dr.text((x + px / 2 - 8, y + 8), f"{alvo // 2}", font=fonte(8), fill=(210, 220, 230))
        dr.text((x + px - 14, y + 8), f"{alvo}", font=fonte(8), fill=(210, 220, 230))
        dr.text((x + px + 3, y + 1), "km", font=fonte(7), fill=(170, 180, 195))
        # barra milhas náuticas (menor, abaixo)
        alvo_mn = alvo * 0.539957
        passo_mn = px / n  # mesma escala física
        for i in range(n):
            cor = (180, 190, 210) if i % 2 == 0 else (60, 65, 80)
            dr.rectangle([x + i * passo_mn, y + 18, x + (i + 1) * passo_mn, y + 23],
                         fill=cor, outline=(140, 150, 170))
        dr.text((x, y + 24), "0", font=fonte(8), fill=(180, 195, 215))
        dr.text((x + px - 24, y + 24), f"{alvo_mn:.0f}", font=fonte(8), fill=(180, 195, 215))
        dr.text((x + px + 3, y + 18), "Mn", font=fonte(7), fill=(150, 165, 190))

    def _desenhar_rosa(self, dr, x, y, r) -> None:
        """Rosa dos ventos de 16 pontas, estilo carta náutica DHN."""
        import math as _m
        # 16 pontas: N S L O e intermediárias
        pontos_principais = [0, 90, 180, -90]    # N L S O
        pontos_inter = [45, 135, 225, 315]        # NL NR SL SR -> NE SE SW NW
        pontos_terciarios = [22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5]
        # desenhar em 3 tamanhos
        for ang in pontos_terciarios:
            a = _m.radians(ang - 90)
            r2 = r * 0.5
            px1, py1 = x + _m.cos(a) * r2 * 0.3, y + _m.sin(a) * r2 * 0.3
            px2, py2 = x + _m.cos(a) * r2, y + _m.sin(a) * r2
            dr.line([(px1, py1), (px2, py2)], fill=(180, 192, 210, 200), width=1)
        for ang in pontos_inter:
            a = _m.radians(ang - 90)
            r3 = r * 0.72
            # losango pequeno
            pts = [
                (x + _m.cos(a) * r3, y + _m.sin(a) * r3),
                (x + _m.cos(a + _m.pi/2) * r3 * 0.15, y + _m.sin(a + _m.pi/2) * r3 * 0.15),
                (x + _m.cos(a + _m.pi) * r3 * 0.3, y + _m.sin(a + _m.pi) * r3 * 0.3),
                (x + _m.cos(a - _m.pi/2) * r3 * 0.15, y + _m.sin(a - _m.pi/2) * r3 * 0.15),
            ]
            dr.polygon(pts, fill=(195, 205, 220, 210))
        # 4 pontas principais (N S L O): losangos brancos grandes
        for ang in pontos_principais:
            a = _m.radians(ang - 90)
            rm = r
            pts = [
                (x + _m.cos(a) * rm, y + _m.sin(a) * rm),
                (x + _m.cos(a + _m.pi/2) * rm * 0.2, y + _m.sin(a + _m.pi/2) * rm * 0.2),
                (x + _m.cos(a + _m.pi) * rm * 0.35, y + _m.sin(a + _m.pi) * rm * 0.35),
                (x + _m.cos(a - _m.pi/2) * rm * 0.2, y + _m.sin(a - _m.pi/2) * rm * 0.2),
            ]
            # metade N = cor, metade contrária = branco
            fill = (210, 50, 30) if ang == 0 else (235, 235, 235)
            dr.polygon(pts, fill=fill, outline=(40, 40, 40, 200), width=1)
        # círculo central
        rc = max(3, int(r * 0.18))
        dr.ellipse([x - rc, y - rc, x + rc, y + rc], fill=(235, 235, 235), outline=(40, 40, 40))
        # rótulo N
        dr.text((x - 5, y - r - 18), "N", font=fonte(max(11, int(r * 0.9)), True), fill=(210, 50, 30))

    def _desenhar_metadados(self, img, motor) -> None:
        r = motor.resumo()

        def num(chave: str, casas: int = 1, sufixo: str = "") -> str:
            v = r.get(chave)
            return "n/a" if v is None else f"{v:.{casas}f}{sufixo}"

        tci = r.get("tci_horas")
        linhas = [
            f"Protocolo: {r.get('protocolo_rotulo', r.get('protocolo', '?'))}",
            f"TED: {num('ted_percentual')}%   (horizonte 6 h: {num('ted_no_horizonte_percentual')}%)",
            f"LPA: {num('lpa_minutos')} min   CAR: {num('car_percentual')}%",
            f"Overhead: {num('overhead_copias', 2)}x   saltos: {num('saltos_medios', 2)}",
            f"Transmissoes: {r.get('transmissoes', 0)}   airtime: {num('airtime_total_s', 0)} s",
            f"TCI: {'n/a' if tci is None else f'{tci:.1f} h'}   zonas a tempo: {r.get('nos_informados_a_tempo', 0)}",
        ]
        x0 = self.MARGEM + 6
        y0 = self.MARGEM + self.ALTURA_TITULO + 10
        larg = 300
        alt = 22 + len(linhas) * 16
        bloco = Image.new("RGBA", (larg, alt), (10, 20, 32, 215))
        bdr = ImageDraw.Draw(bloco)
        bdr.rectangle([0, 0, larg - 1, alt - 1], outline=(90, 120, 150, 255), width=1)
        bdr.text((8, 5), "QUADRO DE METRICAS DA SIMULACAO", font=fonte(11, True), fill=COR_TEXTO)
        for i, ln in enumerate(linhas):
            bdr.text((8, 24 + i * 16), ln, font=fonte(11), fill=(205, 218, 230))
        img.paste(bloco, (x0, y0), bloco)

    def _desenhar_moldura(self, dr, larg, alt, larg_mapa, alt_mapa) -> None:
        dr.rectangle([self.MARGEM - 2, self.MARGEM + self.ALTURA_TITULO - 2,
                      self.MARGEM + larg_mapa + 2, self.MARGEM + self.ALTURA_TITULO + alt_mapa + 2],
                     outline=COR_BORDA, width=2)
        dr.rectangle([0, 0, larg - 1, alt - 1], outline=COR_BORDA, width=2)

    # -- exportacao ------------------------------------------------------
    def salvar(self, imagem: Image.Image, caminho: str, dpi: int = 200) -> str:
        pasta = os.path.dirname(os.path.abspath(caminho))
        os.makedirs(pasta, exist_ok=True)
        imagem.save(caminho, dpi=(dpi, dpi))
        return caminho


# ---------------------------------------------------------------------------
# 7. FUNCOES DE CONVENIENCIA
# ---------------------------------------------------------------------------
def desenhar_carta(
    cenario,
    t_h: float = 0.0,
    motor=None,
    titulo: str | None = None,
    opcoes: OpcoesCarta | None = None,
) -> Image.Image:
    """Gera a carta nautica do cenario no instante ``t_h``."""
    return CartaNautica(opcoes).render(cenario, t_h, motor=motor, titulo=titulo)


def salvar_carta(
    caminho: str,
    cenario,
    t_h: float = 0.0,
    motor=None,
    titulo: str | None = None,
    opcoes: OpcoesCarta | None = None,
) -> str:
    """Gera e grava a carta nautica em disco, devolvendo o caminho final."""
    carta = CartaNautica(opcoes)
    return carta.salvar(carta.render(cenario, t_h, motor=motor, titulo=titulo), caminho)
