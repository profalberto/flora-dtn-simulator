"""
flora_geometria.py
=================

Geometria georreferenciada e escala fisica do corredor fluvial
Manaus-Itacoatiara, bacia do Rio Amazonas (UFAM / FLoRA).

Este modulo nao importa pygame: e usado tanto pela interface grafica quanto
pelo motor headless de linha de comando, o que garante que a geometria
avaliada no experimento e a mesma exibida na tela.

Convencoes
----------
* "Mundo" sao pixels logicos do canvas de simulacao (1000 x 600).
* `y_mundo` cresce para baixo e ja inclui o deslocamento do menu superior,
  de modo que a faixa geografica util ocupa de 40 a 640.
* Toda a fisica (movimentacao, alcance de radio, obstaculos) e expressa em
  quilometros. Pixels servem apenas para desenho.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

import flora_osm

# ---------------------------------------------------------------------------
# 1. CANVAS
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 1. EXTENSAO GEOGRAFICA
# ---------------------------------------------------------------------------
# Web Mercator nao e necessaria: a area tem 1,75 grau de longitude por 1,10 de
# latitude, onde a diferenca de escala entre as duas direcoes e pequena e
# mensuravel. O que importa mesmo e o aspecto.
LAT_TOP, LAT_BOTTOM = -2.60, -3.70
LONG_LEFT, LONG_RIGHT = -60.10, -58.35

RAIO_TERRA_KM = 6371.0088
_LAT_MEDIO = (LAT_TOP + LAT_BOTTOM) * 0.5

EXTENSAO_LON_KM = abs(LONG_RIGHT - LONG_LEFT) * 111.320 * math.cos(math.radians(_LAT_MEDIO))
EXTENSAO_LAT_KM = abs(LAT_BOTTOM - LAT_TOP) * 110.574

# ---------------------------------------------------------------------------
# 2. CANVAS
# ---------------------------------------------------------------------------
LARGURA_SIMULACAO_BASE = 1000

# A altura e DERIVADA da janela geografica, e nao escolhida a mao. Com 1000 x 600
# fixos as escalas por pixel ficavam diferentes (194,5 m/px em X contra 202,7 em
# Y, 4,2% de diferença), e toda distancia medida em pixels errava nessa
# proporcao: o canal dava 211,2 km contra os 209,0 km do GeoJSON, a cobertura dos
# gateways e os raios de obstaculo tambem. Um km por pixel em tela nao e um
# detalhe estetico, e a unidade em que o modelo fala de velocidade e alcance.
ALTURA_TELA_BASE = int(round(LARGURA_SIMULACAO_BASE * EXTENSAO_LAT_KM / EXTENSAO_LON_KM))
ALTURA_MENU_SUP = 40
LARGURA_PAINEL = 280
ALTURA_TELA = ALTURA_TELA_BASE + ALTURA_MENU_SUP

#: Escala unica da carta. As duas direcoes batem porque a altura do canvas foi
#: derivada do aspecto da janela; estas duas medidas ficam para conferencia.
KM_POR_PX_X = EXTENSAO_LON_KM / LARGURA_SIMULACAO_BASE
KM_POR_PX_Y = EXTENSAO_LAT_KM / ALTURA_TELA_BASE
KM_POR_PX = (KM_POR_PX_X + KM_POR_PX_Y) * 0.5
PX_POR_KM = 1.0 / KM_POR_PX

#: Semilargura da faixa de navegacao de cada sentido. Em agua navegavel o
#: trafego de subida e de descida se mantem em pistas separadas; 0,45 km evita
#: a sobreposicao de cascos e e compativel com a largura da calha modelada.
OFFSETO_FAIXA_KM = 0.45

#: Numero de pontos resolvidos por bloco nas consultas vetorizadas de
#: distancia. Limita o pico de memoria sem prejudicar o rendimento.
_BLOCO_DISTANCIA = 1024


# ---------------------------------------------------------------------------
# 3. CONVERSOES
# ---------------------------------------------------------------------------
def geo_para_mundo(latitude: float, longitude: float) -> np.ndarray:
    """Latitude/longitude -> pixel logico do canvas."""
    x = (longitude - LONG_LEFT) / (LONG_RIGHT - LONG_LEFT) * LARGURA_SIMULACAO_BASE
    y = ALTURA_MENU_SUP + (latitude - LAT_TOP) / (LAT_BOTTOM - LAT_TOP) * ALTURA_TELA_BASE
    return np.array([x, y], dtype=float)


def mundo_para_geo(x_mundo: float, y_mundo: float) -> tuple[float, float]:
    """Pixel logico do canvas -> (latitude, longitude)."""
    lat = LAT_TOP + (y_mundo - ALTURA_MENU_SUP) / ALTURA_TELA_BASE * (LAT_BOTTOM - LAT_TOP)
    lon = LONG_LEFT + x_mundo / LARGURA_SIMULACAO_BASE * (LONG_RIGHT - LONG_LEFT)
    return lat, lon


def distancia_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia de grande circulo entre dois pontos, em quilometros."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * RAIO_TERRA_KM * math.asin(math.sqrt(a))


def distancia_mundo_km(a, b) -> float:
    """Distancia euclidiana em pixels convertida para quilometros."""
    return float(np.linalg.norm(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))) * KM_POR_PX


def px_para_km(valor_px: float) -> float:
    return float(valor_px) * KM_POR_PX


def km_para_px(valor_km: float) -> float:
    return float(valor_km) * PX_POR_KM


#: Expoente da parametrizacao centripeta de Catmull-Rom. 0,5 e o valor padrao
#: de Yuksel/Bourke: com 1,0 (uniforme) ou menos a spline cria lacos e bicos
#: quando dois marcos consecutivos ficam perto um do outro, que e exatamente o
#: caso dos confluentes, e a curva sai do corredor.
_CATMULL_ALPHA = 0.5

#: Margem para os nos coincidentes. Nas pontas da polilinha o primeiro e o
#: ultimo marco sao repetidos, e entao dois nos caem no mesmo instante; sem esta
#: folga a divisao por zero devolveria NaN em todo o primeiro trecho.
_CATMULL_EPS = 1e-9


def catmull_rom(p0, p1, p2, p3, t):
    """
    Trecho de spline de Catmull-Rom centripeta entre `p1` e `p2`.

    `t` vai de 0 a 1 e mede o avanco de `p1` ate `p2`. A diferenca para a
    versao uniforme e a distribuicao dos nos ao longo do trecho, governada pelo
    expoente `_CATMULL_ALPHA` sobre a distancia entre marcos. Isso remove os
    lacos e bicos da versao uniforme sem mudar os pontos por onde a curva passa.
    """
    a = _CATMULL_ALPHA
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    p3 = np.asarray(p3, dtype=float)

    def _no(p, q, base):
        return base + max(float(np.linalg.norm(q - p)) ** a, _CATMULL_EPS)

    t0 = 0.0
    t1 = _no(p0, p1, t0)
    t2 = _no(p1, p2, t1)
    t3 = _no(p2, p3, t2)

    u = t1 + float(t) * (t2 - t1)
    a1 = (t1 - u) / (t1 - t0) * p0 + (u - t0) / (t1 - t0) * p1
    a2 = (t2 - u) / (t2 - t1) * p1 + (u - t1) / (t2 - t1) * p2
    a3 = (t3 - u) / (t3 - t2) * p2 + (u - t2) / (t3 - t2) * p3
    b1 = (t2 - u) / (t2 - t0) * a1 + (u - t0) / (t2 - t0) * a2
    b2 = (t3 - u) / (t3 - t1) * a2 + (u - t1) / (t3 - t1) * a3
    return (t2 - u) / (t2 - t1) * b1 + (u - t1) / (t2 - t1) * b2


# ---------------------------------------------------------------------------
# 4. MARCOS GEOGRAFICOS
# ---------------------------------------------------------------------------
#: Marcos da rota comercial principal (leito do Amazonas), em graus.
#:
#: As coordenadas de cidade sao reais, do IBGE. Os dois pontos intermediarios
#: nao sao cidades: sao a bifurcação do canal de várzea e a Boca do Preto da Eva,
#: e existem porque sao os marcos de checagem de `baixar_osm.py`, que exige que o
#: eixo real do OSM passe por eles. O eixo que o simulador usa nao passa por eles
#: a nocao: ele vem do arquivo `dados_osm/eixo_rio.json`, e so precisa terminar
#: nas cidades. Ver `CIDADES_FORA_DO_CORREDOR` para o criterio de inclusao.
COORDENADAS_ROTA_NAVEGACAO: dict[str, tuple[float, float]] = {
    "Manaus": (-3.1190, -60.0217),                 # IBGE
    "Bifurcacao_Careiro_Entrada": (-3.1300, -59.9900),
    "Boca_do_Preto_da_Eva": (-3.1450, -58.5200),
    "Itacoatiara": (-3.1338, -58.4386),            # IBGE
}

#: Rotas nomeadas usadas nos paineis e no CSV.
ROTAS: dict[str, list[str]] = {
    "Manaus-Itacoatiara": list(COORDENADAS_ROTA_NAVEGACAO),
}

#: Cidades do corredor que recebem um gateway fixo, na ordem em que aparecem ao
#: longo do trajeto. A chave e o nome do marco em `WAYPOINTS`, de modo que a
#: posicao do gateway e sempre a posicao geografica real da cidade: nao ha km
#: digitado a mao para divergir do mapa.
SUPERNOS_CIDADE: list[tuple[str, str]] = [
    ("Manaus", "Porto de Manaus"),
    ("Itacoatiara", "Terminal Itacoatiara"),
]

#: Municipios com telecomunicacao citados na tese que NAO recebem gateway, com a
#: coordenada real e o motivo em cada caso. E um registro explicito, e nao uma
#: omissao: o criterio para entrar no corredor e ter posicao real sobre o canal
#: modelado, e nao ter o nome numa lista de cidades preferidas.
#:
#: Careiro da Varzea e Autazes entraram aqui junto com a retirada do canal de
#: várzea do Careiro: as duas cidades continuam sendo reais e continuam sendo
#: citadas, mas nao ha mais um segundo rio modelado para elas ficarem em cima.
#: O motivo do canal esta em `baixar_osm.selecionar_eixo`.
#:
#: O tipo e `dict` e nao tupla de tres posicoes porque os motivos contem virgula,
#: e o comentario ficaria ambíguo se a posicao fosse lida a mao.
CIDADES_FORA_DO_CORREDOR: list[dict[str, object]] = [
    {
        "cidade": "Urucurituba",
        "lat": -3.1308,
        "lon": -58.1550,
        "motivo": "a 31 km a jusante de Itacoatiara, fora do trecho Manaus-Itacoatiara",
    },
    {
        "cidade": "Careiro da Varzea",
        "lat": -3.2208,
        "lon": -59.8258,
        "motivo": "no canal de varzea do Careiro, retirado do modelo por decisao do experimento",
    },
    {
        "cidade": "Autazes",
        "lat": -3.5801,
        "lon": -59.1306,
        "motivo": "no canal de varzea do Careiro, retirado do modelo por decisao do experimento",
    },
    {
        "cidade": "Silves",
        "lat": -2.8389,
        "lon": -58.2092,
        "motivo": "no rio Itacoatiara, a montante do corredor modelado",
    },
    {
        "cidade": "Itapiranga",
        "lat": -2.7489,
        "lon": -58.0220,
        "motivo": "no rio Madeira, cerca de 340 km de Manaus",
    },
]


# ---------------------------------------------------------------------------
# 5. CANAIS
# ---------------------------------------------------------------------------
# eq=False: um canal e identificado pela instancia, nao pelo conteudo. Isso
# permite usa-lo como chave de dicionario e evita comparar dois arrays de 287
# pontos sempre que dois canais sao posto lado a lado.
@dataclass(eq=False)
class Canal:
    """
    Polilinha hidrográfica com parametrizacao acumulativa em quilometros.

    O deslocamento das embarcações é descrito por `km_atual` ao longo do canal,
    e nao por indice de pixel; isso torna o modelo independente da resolucao
    do canvas e permite expresses velocidades em km/h.
    """

    nome: str
    tipo: str
    profundidade_nominal_m: float
    largura_navegavel_km: float
    pontos_geo: np.ndarray
    pontos_mundo: np.ndarray
    km_acumulado: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        seg = np.linalg.norm(np.diff(self.pontos_mundo, axis=0), axis=1)
        self.km_acumulado = np.concatenate(([0.0], np.cumsum(seg) * KM_POR_PX))
        # canal em quilometros, para consultas de batimetria
        self.pontos_km = self.pontos_mundo * KM_POR_PX
        # segmentos pré-computados para a distância ponto-a-segmento em lote
        self._seg_a = self.pontos_mundo[:-1]
        ab = self.pontos_mundo[1:] - self._seg_a
        self._seg_ab = ab
        self._seg_len2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12)
        # listas de Python para os acessos ponto a ponto, que rodam uma vez por
        # no e por passo de tempo e nao justificam o custo fixo do numpy
        self._km_lista = [float(v) for v in self.km_acumulado]
        self._pts_lista = [(float(p[0]), float(p[1])) for p in self.pontos_mundo]

    @classmethod
    def a_partir_de_pontos(cls, nome, tipo, profundidade_nominal_m,
                           largura_navegavel_km, pontos_geo: np.ndarray) -> "Canal":
        """
        Constroi o canal a partir de uma polilinha ja medida, sem interpolar.

        E o caminho usado pelo eixo do OpenStreetMap. Os pontos chegam como
        vieram do dado e sao usados como estao: o OSM mediu onde o rio esta, e
        qualquer ponto acrescentado aqui seria uma invencao com cara de medicao.
        """
        arr_geo = np.asarray(pontos_geo, dtype=float)
        arr_mundo = np.array([geo_para_mundo(p[0], p[1]) for p in arr_geo],
                             dtype=float)
        return cls(nome, tipo, profundidade_nominal_m, largura_navegavel_km,
                   arr_geo, arr_mundo)

    @classmethod
    def a_partir_de_marcas(cls, nome, tipo, profundidade_nominal_m, largura_navegavel_km,
                           marcas: list[str], coordenadas: dict, amostras_por_trecho: int = 22) -> "Canal":
        """Suaviza os marcos geograficos com Catmull-Rom e devolve um canal denso."""
        ancora = [np.array(coordenadas[n], dtype=float) for n in marcas]
        pontos_geo: list[np.ndarray] = []
        for i in range(len(ancora) - 1):
            p0 = ancora[max(0, i - 1)]
            p1 = ancora[i]
            p2 = ancora[i + 1]
            p3 = ancora[min(len(ancora) - 1, i + 2)]
            for j in range(amostras_por_trecho):
                pontos_geo.append(catmull_rom(p0, p1, p2, p3, j / float(amostras_por_trecho)))
        pontos_geo.append(ancora[-1])
        arr_geo = np.array(pontos_geo, dtype=float)
        arr_mundo = np.array([geo_para_mundo(p[0], p[1]) for p in pontos_geo], dtype=float)
        return cls(nome, tipo, profundidade_nominal_m, largura_navegavel_km, arr_geo, arr_mundo)

    @property
    def comprimento_km(self) -> float:
        return float(self.km_acumulado[-1])

    def indice_no_km(self, km: float) -> int:
        """Indice do ultimo vertice no km ou antes dele."""
        i = int(np.searchsorted(self.km_acumulado, km, side="right")) - 1
        return int(np.clip(i, 0, len(self.km_acumulado) - 1))

    def posicao_em(self, km: float, offset_km: float = 0.0):
        """
        Devolve (posicao_px, tangente_unitaria, perpendicular_unitaria) no ponto
        `km` do canal, deslocado `offset_km` para um dos lados da faixa.

        Esta funcao e chamada uma vez por embarcacao e por passo de tempo, com
        arrays de apenas dois elementos. O numpy tem custo fixo por chamada
        que, nesse tamanho, domina o calculo; por isso as interpolacoes de uma
        dimensao sao feitas em Python puro sobre listas pre-computadas.
        """
        kma = self._km_lista
        pts = self._pts_lista
        # `searchsorted` com o lado esquerdo devolve o vertice *seguinte*, e nao
        # o inicial do trecho que contem `km`. Nos trechos densos a diferenca e
        # de um ponto vizinho, mas o eixo do OSM tem trechos retos de quilometros
        # (a malha e esparsa de proposito): com o indice errado a posicao ficava
        # presa no vertice seguinte e saltava de uma vez ao cruza-lo. E o salto
        # que aparecia como tremor no casco. O lado direito menos um devolve o
        # vertice inicial do trecho, e a interpolacao fica continua.
        i = int(np.searchsorted(self.km_acumulado, km, side="right")) - 1
        if i < 0:
            i = 0
        elif i > len(kma) - 1:
            i = len(kma) - 1
        j = i + 1 if i + 1 < len(kma) else i

        km_i, km_j = kma[i], kma[j]
        span = km_j - km_i
        frac = 0.0 if span <= 0.0 else min(1.0, max(0.0, (km - km_i) / span))

        x0, y0 = pts[i]
        x1, y1 = pts[j]
        bx, by = x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac
        tx, ty = x1 - x0, y1 - y0
        norma = math.hypot(tx, ty)
        if norma == 0.0:
            tx, ty, norma = 1.0, 0.0, 1.0
        tx, ty = tx / norma, ty / norma

        px = -ty
        py = tx
        d = km_para_px(offset_km)
        return np.array([bx + px * d, by + py * d]), np.array([tx, ty]), np.array([px, py])

    def distancias_ao_eixo_km(self, pontos) -> np.ndarray:
        """
        Distancia perpendicular ao eixo do canal para varios pontos, em km.

        Formula de ponto-a-segmento resolvida com produtos internos:

            |p - q|^2 = |p|^2 - 2 p.q + |q|^2,  com q = a + t (b - a)

        em que `t` e a projecao de `p` no segmento, truncada em [0, 1]. Dessa
        forma a dimensao dos segmentos aparece apenas em arrays (n x m), nunca
        em tensores (n x m x 2), e as projecoes saem de produtos matriz-matriz
        acelerados pela BLAS em vez de `einsum` com broadcasting. E o mesmo
        resultado da busca ponto a ponto, apenas com menos trafego de memoria.
        """
        arr = np.asarray(pontos, dtype=float).reshape(-1, 2)
        if len(arr) == 0:
            return np.zeros(0, dtype=float)
        seg_a = self._seg_a          # (m, 2)
        seg_ab = self._seg_ab        # (m, 2)
        len2 = self._seg_len2        # (m,)
        aa = np.einsum("mj,mj->m", seg_a, seg_a)                       # |a|^2
        da = np.einsum("mj,mj->m", seg_a, seg_ab)                      # a . (b-a)
        pp = np.einsum("nj,nj->n", arr, arr)                          # |p|^2
        saida = np.empty(len(arr), dtype=float)
        for ini in range(0, len(arr), _BLOCO_DISTANCIA):
            bloco = arr[ini:ini + _BLOCO_DISTANCIA]
            pa = bloco @ seg_a.T          # (n, m)  p . a
            pb = bloco @ seg_ab.T         # (n, m)  p . (b-a)
            t = np.clip((pb - da[None, :]) / len2[None, :], 0.0, 1.0)
            dist2 = (
                pp[ini:ini + _BLOCO_DISTANCIA, None]
                - 2.0 * (pa + t * pb)
                + (aa[None, :] + 2.0 * t * da[None, :] + t * t * len2[None, :])
            )
            np.maximum(dist2, 0.0, out=dist2)
            saida[ini:ini + _BLOCO_DISTANCIA] = np.sqrt(dist2).min(axis=1)
        return saida * KM_POR_PX

    def distancia_ao_eixo_km(self, pos) -> float:
        """Distancia perpendicular do ponto ate o eixo do canal, em km."""
        return float(self.distancias_ao_eixo_km([pos])[0])

    def indice_mais_proximo(self, pos) -> int:
        d = np.linalg.norm(self.pontos_mundo - np.asarray(pos, dtype=float), axis=1)
        return int(np.argmin(d))

    def ponto_faixa(self, km: float, sentido: int, offset_km: float) -> np.ndarray:
        pos, _, _ = self.posicao_em(km, offset_km * (1 if sentido >= 0 else -1))
        return pos

    def projetar_ponto(self, pos) -> tuple[float, float]:
        """
        Projeta um ponto arbitrario no eixo do canal.

        Retorna (km_ao_longo_do_canal, offset_perpendicular_km com sinal).
        Util para inserir novos nos ou ancorar elementos a partir de cliques do usuario.
        """
        pos_arr = np.asarray(pos, dtype=float)
        pa = pos_arr - self._seg_a
        t = np.clip(np.einsum("ij,ij->i", pa, self._seg_ab) / self._seg_len2, 0.0, 1.0)
        proj = self._seg_a + t[:, None] * self._seg_ab
        dif = pos_arr - proj
        d2 = np.einsum("ij,ij->i", dif, dif)
        idx = int(np.argmin(d2))

        km_base = self.km_acumulado[idx]
        km_seg = self.km_acumulado[idx + 1] - km_base
        km_proj = float(km_base + t[idx] * km_seg)

        tx, ty = self._seg_ab[idx]
        norm = math.hypot(tx, ty)
        if norm > 0.0:
            nx, ny = -ty / norm, tx / norm
            offset_px = dif[idx, 0] * nx + dif[idx, 1] * ny
            offset_km = float(offset_px * KM_POR_PX)
        else:
            offset_km = 0.0

        return km_proj, offset_km


#: Nome do canal principal, e a profundidade e a largura que o modelo assume
#: para a calha comercial. Sao parametros do modelo, nao medidas do OSM: o dado
#: do OpenStreetMap quase nao traz `width` para o Amazonas, com um unico trecho
#: mapeado no corredor, entao a largura continua sendo uma hipotese declarada.
CANAL_PRINCIPAL_NOME = "Leito Principal do Rio Amazonas"
PROFUNDIDADE_NOMINAL_M = 32.5
LARGURA_NAVEGAVEL_KM = 3.0


#: Polilinha (lat, lon) do leito principal vinda do cache do OpenStreetMap, ou
#: `None` se nao houver cache utilizavel.
#:
#: Le uma vez no import, porque o resultado decide a geometria do canal e a
#: legenda da carta ao mesmo tempo. Ler duas vezes abriria duas situacoes em que
#: o arquivo mudou no meio, e a carta creditaria uma fonte diferente da que o
#: rio foi desenhado.
#:
#: O motivo de o fallback existir: sem o arquivo, o programa precisa abrir do
#: mesmo jeito. O motivo de o fallback nao ser o padrao: o spline produz uma
#: linha quase reta, com razao reta/percurso de 0,998, que e o defeito que a
#: geometria real veio corrigir.
_EIXO_OSM: np.ndarray | None = flora_osm.carregar_eixo("principal")


def _construir_canais() -> dict[str, Canal]:
    if _EIXO_OSM is not None:
        return {CANAL_PRINCIPAL_NOME: Canal.a_partir_de_pontos(
            CANAL_PRINCIPAL_NOME,
            "Calha comercial estavel",
            PROFUNDIDADE_NOMINAL_M,
            LARGURA_NAVEGAVEL_KM,
            _EIXO_OSM)}
    return {CANAL_PRINCIPAL_NOME: Canal.a_partir_de_marcas(
        CANAL_PRINCIPAL_NOME,
        "Calha comercial estavel",
        PROFUNDIDADE_NOMINAL_M,
        LARGURA_NAVEGAVEL_KM,
        ROTAS["Manaus-Itacoatiara"],
        COORDENADAS_ROTA_NAVEGACAO,
    )}


CANAIS: dict[str, Canal] = _construir_canais()
CANAL_PRINCIPAL: Canal = CANAIS[CANAL_PRINCIPAL_NOME]

#: Se o eixo veio do OpenStreetMap ou do spline dos marcos. A carta e o rodape
#: consultam isso para creditar a fonte certa e nao mentir sobre a origem.
GEOMETRIA_DO_OSM: bool = _EIXO_OSM is not None

#: Nomes dos canais, na ordem em que aparecem nos menus.
ROTAS_DISPONIVEIS: list[str] = [CANAL_PRINCIPAL.nome]

#: Todos os marcos geograficos indexados pelo nome original do simulador legado.
WAYPOINTS: dict[str, np.ndarray] = {
    nome: geo_para_mundo(*coord)
    for nome, coord in COORDENADAS_ROTA_NAVEGACAO.items()
}
for _c in CIDADES_FORA_DO_CORREDOR:
    WAYPOINTS[_c["cidade"]] = geo_para_mundo(_c["lat"], _c["lon"])


def ancorar_cidades() -> list[tuple[str, str, Canal, float, float]]:
    """
    Ancora cada cidade de `SUPERNOS_CIDADE` no canal e no quilometro que lhe
    correspondem.

    Devolve (chave, nome, canal, km, desvio_km). O canal e o de menor distancia
    ao marco, e o km vem da polilinha desse canal, entao o gateway nasce
    exatamente sobre a cidade, sem nenhum valor digitado a mao.

    Cidades sem marco no dicionario sao ignoradas e nao param a ancoragem: a
    lista de cidades e um cadastro, nao uma garantia de cobertura.
    """
    saida = []
    for chave, nome in SUPERNOS_CIDADE:
        pos = WAYPOINTS.get(chave)
        if pos is None:
            continue
        melhor_canal, melhor = min(
            ((c, float(np.linalg.norm(c.pontos_mundo - pos, axis=1).min()))
             for c in CANAIS.values()),
            key=lambda par: par[1],
        )
        indice = melhor_canal.indice_mais_proximo(pos)
        saida.append((chave, nome, melhor_canal,
                      float(melhor_canal.km_acumulado[indice]), melhor * KM_POR_PX))
    return saida


def cobertura_gateways(alcance_km: float, supernos) -> tuple[float, float]:
    """
    (fracao coberta, maior vao em km) do canal principal por um conjunto de
    gateways de alcance `alcance_km`.

    O canal principal e onde a frota opera em quase toda a trajetoria, entao e
    ele que define se ha regiao sem acesso a internet. O resultado vai para o
    painel e para o CSV porque e a grandeza que decide se o transporte
    store-carry-forward e mesmo necessario: com a rota inteira coberta, qualquer
    protocolo se comporta como LoRaWAN comum e a comparacao perde sentido.

    So gateways fixos entram na conta. Um gateway movel cobre onde esta, que
    muda a cada passo; somar a posicao de um instante daria um numero que
    parece estatico e nao e. Para o que os moveis acrescentam, veja
    `cobertura_instantanea`.
    """
    comp = CANAL_PRINCIPAL.comprimento_km
    intervalos = []
    for sn in supernos:
        if sn.movel or sn.canal is not CANAL_PRINCIPAL:
            continue
        centro = sn.km_canal
        intervalos.append((max(0.0, centro - alcance_km),
                           min(comp, centro + alcance_km)))
    intervalos.sort()
    coberto = 0.0
    fim_atual = 0.0
    for ini, fim in intervalos:
        if ini > fim_atual:
            coberto += fim - ini
        else:
            coberto += max(0.0, fim - max(ini, fim_atual))
        fim_atual = max(fim_atual, fim)
    maior_vao = 0.0
    pos = 0.0
    for ini, fim in intervalos:
        if ini - pos > maior_vao:
            maior_vao = ini - pos
        pos = max(pos, fim)
    maior_vao = max(maior_vao, comp - pos)
    return coberto / comp if comp else 0.0, maior_vao


def descricao_escala() -> str:
    """Texto de rodape com a escala real do mapa, util para cartografia e CSV."""
    fonte = "eixo OSM" if GEOMETRIA_DO_OSM else "eixo spline"
    return (
        f"escala {KM_POR_PX * 1000:.1f} m/px | "
        f"{CANAL_PRINCIPAL.comprimento_km:.1f} km Manaus-Itacoatiara | {fonte}"
    )
