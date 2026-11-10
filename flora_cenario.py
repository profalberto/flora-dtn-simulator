"""
flora_cenario.py
================

Cenarios hidrogeograficos do corredor Manaus-Itacoatiara.

O simulador legado modelava profundidade como funcao da distancia ao eixo do
canal, o que tornava o alerta de "profundidade critica" inalcancaivel para
qualquer embarcacao dentro da faixa navegavel. Aqui a batimetria e um campo
dependente de tres fatores explicitos:

    profundidade(pos, t) = perfil_transversal(distancia_ao_eixo)
                           - (nivel_rio(t) - nivel_referencia)
                           - soma_de_terras_caidas(perto, t)

e a margem de seguranca e medida contra o *calado* de cada embarcacao:

    margem_sob-keel (MSK) = profundidade - calado

Classificacao de risco (MSK, em metros):
    <  0.5 m  -> CRITICO  (encalhe iminente)
    <  1.5 m  -> ATENCAO
    >= 1.5 m  -> SEGURO

Cenarios implementados (artigo FLoRA, secao 5.2):
    C1 Normal    - nivel de referencia, sem obstrucoes
    C2 Vazante   - nivel 8 m abaixo da referencia, 12 baixios sazonais
    C3 Terra Caiada - desmoronamento no km 170, ativado no dia 3, 15 m -> 2.5 m
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from flora_geometria import (
    CANAIS,
    CANAL_PRINCIPAL,
    Canal,
    KM_POR_PX,
    geo_para_mundo,
    km_para_px,
)

SEGUNDOS_POR_HORA = 3600.0
HORAS_POR_DIA = 24.0
DIAS_POR_SEMANA = 7.0

# Limiares de margem sob quilha (metros).
MSK_CRITICO = 0.5
MSK_ATENCAO = 1.5


# ---------------------------------------------------------------------------
# 1. TERRAS CAIDAS / BAIXIOS
# ---------------------------------------------------------------------------
@dataclass
class Obstaculo:
    """
    Depressao batimetrica local: desmoronamento de margem (terra caida) ou
    baixio sazonal exposto durante a vazante.
    """

    identificacao: str
    canal: str
    km: float
    raio_km: float
    profundidade_residual_m: float
    t_inicio_h: float = 0.0
    t_fim_h: float = math.inf
    borda_km: float | None = None
    rotulo: str = ""

    def __post_init__(self) -> None:
        if self.borda_km is None:
            self.borda_km = max(0.15, 0.25 * self.raio_km)
        self.borda_km = min(float(self.borda_km), 0.9 * self.raio_km)

    @property
    def posicao_px(self) -> np.ndarray:
        canal = CANAIS[self.canal]
        pos, _, _ = canal.posicao_em(min(self.km, canal.comprimento_km))
        return pos

    def ativo_em(self, t_h: float) -> bool:
        return self.t_inicio_h <= t_h <= self.t_fim_h

    def peso_depressao(self, pos) -> float:
        """
        Fração da profundidade nominal que resta dentro da depressao, em [0, 1].

        O nucleo (dx <= borda_km) tem a profundidade residual integral; a
        transicao ate a borda externa e linear. O nucleo plano reproduz o
        degrau de uma terra caida, que nao e um suave e sim um paredao.
        """
        dx = _distancia_canvas_km(pos, self.posicao_px)
        if dx >= self.raio_km:
            return 1.0
        if dx <= self.borda_km:
            return 0.0
        return (dx - self.borda_km) / (self.raio_km - self.borda_km)

    def peso_depressao_lote(self, posicoes) -> np.ndarray:
        """Versao em lote de `peso_depressao`, para a frota inteira."""
        arr = np.asarray(posicoes, dtype=float).reshape(-1, 2)
        if len(arr) == 0:
            return np.ones(0, dtype=float)
        dx = np.linalg.norm(arr - self.posicao_px[None, :], axis=1) * KM_POR_PX
        # dentro do nucleo: 0 (nenhuma profundidade nominal sobrevive)
        # fora do raio: 1 (a depressao nao age)
        return np.clip((dx - self.borda_km) / (self.raio_km - self.borda_km), 0.0, 1.0)


def _distancia_canvas_km(a, b) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))) * KM_POR_PX


# ---------------------------------------------------------------------------
# 2. PERFIL TRANSVERSAL DE CADA CANAL
# ---------------------------------------------------------------------------
# (distancia_ao_eixo_km, profundidade_m) por canal. Interpolacao linear.
PERFIS_TRANSVERSAIS: dict[str, list[tuple[float, float]]] = {
    CANAL_PRINCIPAL.nome: [
        (0.00, 32.5),   # eixo do canal
        (2.20, 15.0),   # borda da depressao central navegavel
        (5.40, 3.5),    # talude
        (9.00, 0.4),    # banco / margem
    ],
}


def _perfil_profundidade(nome_canal: str, dist_eixo_km: float) -> float:
    perfil = PERFIS_TRANSVERSAIS[nome_canal]
    if dist_eixo_km <= perfil[0][0]:
        return perfil[0][1]
    for (d0, p0), (d1, p1) in zip(perfil, perfil[1:]):
        if dist_eixo_km <= d1:
            span = d1 - d0
            frac = 0.0 if span <= 0 else (dist_eixo_km - d0) / span
            return p0 + (p1 - p0) * frac
    return perfil[-1][1]


#: Vistas de (distancias, profundidades) por canal, prontas para `np.interp`.
#: `np.interp` reproduz exatamente o perfil: interpolacao linear entre marcos e
#: achatamento nos extremos, o mesmo comportamento de `_perfil_profundidade`.
_PERFIS_VETOR: dict[str, tuple[list[float], list[float]]] = {
    nome: ([d for d, _ in perfil], [p for _, p in perfil])
    for nome, perfil in PERFIS_TRANSVERSAIS.items()
}


def _perfil_profundidade_lote(nome_canal: str, dists_km) -> np.ndarray:
    """Versao vetorizada de `_perfil_profundidade` para uma colecao de distancias."""
    marcos, profundidades = _PERFIS_VETOR[nome_canal]
    return np.interp(np.asarray(dists_km, dtype=float), marcos, profundidades)


#: Semi-eixo do perfil transversal de cada canal, em km: a distancia ate onde o
#: modelo descreve o leito e a margem. Alem disso nao ha informacao, porque o
#: restante do quadro e o plano da floresta de varzea. Serve para dizer, sem
#: ambiguidade de cota, onde a secao transversal acaba e a carta deve mostrar
#: terra.
#:
#: E a ultima coluna do perfil, e nao a primeira: o perfil comeca em `d = 0`, no
#: eixo do canal, e vai ate a margem. Pegar `perfil[0][0]` devolveria zero e
#: apagaria a agua inteira da carta.
SEMI_EIXO_CANAL_KM: dict[str, float] = {
    nome: perfil[-1][0] for nome, perfil in PERFIS_TRANSVERSAIS.items()
}

#: Folga, em quilometros, sobre o semi-eixo para a margem caber na faixa de agua.
_MARGEM_COSTA_KM = 0.15


def mascara_agua(indice_canal: np.ndarray, dists_km: np.ndarray) -> np.ndarray:
    """
    Diz quais celulas da grade estao dentro do leito, a partir da geometria.

    A primeira versao da carta separava terra e agua por limiar de
    profundidade, do jeito que se faz num levantamento batimetrico de verdade.
    Aqui isso nao funciona, e a razao vale registro.

    O modelo nao tem topografia. O perfil transversal de cada canal termina em
    0,4 m no leito principal e 0,3 m no canal de varzea, e esse valor se repete
    identico por todo o resto do quadro: a floresta de varzea e um plano. Como a
    profundidade e `perfil + nivel do rio` e o nivel oscila 0,35 m por dia, um
    limiar de 0,6 m classificava a varzea inteira como agua rasante no pico da
    mare e como terra na vazante. Medido no cenario C3, a fracao de agua no
    quadro saltava de 19% para 100% conforme a hora, e a carta piscava.

    Por isso a agua vem do canal, e nao da altura: uma celula e agua quando esta
    dentro da secao transversal que o modelo descreve, e terra quando esta fora
    dela. A faixa e uma propriedade da geometria, identica em todos os instantes
    e nos tres cenarios, e o nivel do rio passa a entrar so na cor, que e o que
    ele de fato informa.

    `indice_canal` e o indice do canal mais proximo e `dists_km` a distancia ate
    o eixo, ambos como `grade_distancias` devolve, achatados.
    """
    semi = np.array([SEMI_EIXO_CANAL_KM[nome] for nome in CANAIS], dtype=float)
    return np.asarray(dists_km, dtype=float) <= semi[indice_canal] + _MARGEM_COSTA_KM


# ---------------------------------------------------------------------------
# 3. CLASSIFICACAO DE RISCO
# ---------------------------------------------------------------------------
RISCO_CRITICO = "CRITICO"
RISCO_ATENCAO = "ATENCAO"
RISCO_SEGURO = "SEGURO"

CORES_RISCO = {
    RISCO_CRITICO: (225, 45, 45),
    RISCO_ATENCAO: (240, 190, 40),
    RISCO_SEGURO: (55, 205, 120),
}


def classificar_margem(margem_m: float) -> str:
    if margem_m < MSK_CRITICO:
        return RISCO_CRITICO
    if margem_m < MSK_ATENCAO:
        return RISCO_ATENCAO
    return RISCO_SEGURO


def cor_risco(margem_m: float) -> tuple[int, int, int]:
    return CORES_RISCO[classificar_margem(margem_m)]


# ---------------------------------------------------------------------------
# 4. CENARIOS
# ---------------------------------------------------------------------------
@dataclass
class CenarioHidrologico:
    """
    Cenario hidrogeografico parametrizado.

    nivel(t) = nivel_referencia_m
             + variacao_sazonal_m * sin(2*pi*t/T_sazonal)
             + variacao_diurna_m * sin(2*pi*t/24)
             + rebaixamento_programado_m(t)
    """

    codigo: str
    nome: str
    descricao: str
    nivel_referencia_m: float = 0.0
    rebaixamento_m: float = 0.0
    variacao_diurna_m: float = 0.35
    variacao_sazonal_m: float = 0.0
    obstaculos: list[Obstaculo] = field(default_factory=list)

    def nivel_rio_m(self, t_h: float) -> float:
        diario = self.variacao_diurna_m * math.sin(2.0 * math.pi * t_h / HORAS_POR_DIA)
        sazonal = 0.0
        if self.variacao_sazonal_m:
            sazonal = self.variacao_sazonal_m * math.sin(2.0 * math.pi * t_h / (365.25 * HORAS_POR_DIA))
        return self.nivel_referencia_m + diario + sazonal + self.rebaixamento_m

    def obstaculos_ativos(self, t_h: float) -> list[Obstaculo]:
        return [o for o in self.obstaculos if o.ativo_em(t_h)]

    def canal_mais_proximo(self, pos) -> tuple[str, float]:
        """(nome do canal, distancia ao eixo em km) para a posicao dada."""
        melhor = None
        for nome, canal in CANAIS.items():
            d = canal.distancia_ao_eixo_km(pos)
            if melhor is None or d < melhor[1]:
                melhor = (nome, d)
        return melhor

    def distancias_ao_canal_mais_proximo_km(self, posicoes) -> np.ndarray:
        """Versao em lote de `canal_mais_proximo`, so com a distancia minima."""
        arr = np.asarray(posicoes, dtype=float).reshape(-1, 2)
        if len(arr) == 0:
            return np.zeros(0, dtype=float)
        return np.min(np.stack([canal.distancias_ao_eixo_km(arr) for canal in CANAIS.values()]), axis=0)

    def canal_da_posicao(self, pos) -> str:
        """Nome do canal mais proximo da posicao dada."""
        return self.canal_mais_proximo(pos)[0]

    def profundidades_m(self, posicoes, t_h: float, d_eixo: dict | None = None) -> np.ndarray:
        """
        Profundidade em varios pontos, para o mesmo instante.

        Equivalente ponto a ponto a `profundidade_m`, porem resolve toda a frota
        com uma unica chamada vetorizada. O motor de simulacao usa esta versao
        porque recalcular a batimetria da frota inteira, uma embarcacao por
        vez, era o custo dominante do passo de tempo.

        `d_eixo` permite reaproveitar as distancias ja calculadas no passo
        corrente em vez de resolve-las outra vez.
        """
        arr = np.asarray(posicoes, dtype=float).reshape(-1, 2)
        if len(arr) == 0:
            return np.zeros(0, dtype=float)
        if d_eixo:
            dists = np.stack([d_eixo[id(canal)] for canal in CANAIS.values()])
        else:
            dists = np.stack([canal.distancias_ao_eixo_km(arr) for canal in CANAIS.values()])
        # menor distancia vence; empate desfeito pelo primeiro canal
        indice = np.argmin(dists, axis=0)
        melhor = np.take_along_axis(dists, indice[None, :], axis=0)[0]
        return self.profundidades_de_distancias(indice, melhor, t_h, arr)

    def profundidades_de_distancias(
        self,
        indice: np.ndarray,
        dists_km: np.ndarray,
        t_h: float,
        posicoes: np.ndarray | None = None,
    ) -> np.ndarray:
        """
        Profundidades a partir da distancia ja resolvida ao canal mais proximo.

        Isola a parte que **nao** depende do tempo do calculo de batimetria. A
        distancia ao eixo do canal depende apenas da posicao, o que permite
        cachear a malha de distancias: reavaliar so o perfil transversal, o
        nivel do rio e os obstaculos. Sem essa separacao, cada regeracao da
        carta repetia 2,9 milhoes de distancias ponto-a-segmento e levava
        cerca de 215 ms, mesmo sem nenhuma mudanca no cenario.
        """
        arr = (np.asarray(posicoes, dtype=float).reshape(-1, 2)
               if posicoes is not None else np.zeros((len(indice), 2)))
        prof = np.empty(len(indice), dtype=float)
        for canal_ind, (nome, _canal) in enumerate(CANAIS.items()):
            sel = indice == canal_ind
            if not sel.any():
                continue
            prof[sel] = _perfil_profundidade_lote(nome, dists_km[sel])

        prof += self.nivel_rio_m(t_h)
        for obst in self.obstaculos_ativos(t_h):
            perda = 1.0 - obst.peso_depressao_lote(arr)
            prof = prof * (1.0 - perda) + obst.profundidade_residual_m * perda
        return np.maximum(0.0, prof)

    def margens_sob_quilha_m(self, posicoes, calados, t_h: float) -> np.ndarray:
        return self.profundidades_m(posicoes, t_h) - np.asarray(calados, dtype=float)

    def profundidade_m(self, pos, t_h: float) -> float:
        nome, dist = self.canal_mais_proximo(pos)
        prof = _perfil_profundidade(nome, dist)
        # `nivel_rio_m` e a cota da agua relativa ao nivel de referencia da
        # sondagem. Um rebaixamento (valor negativo, como os -8 m da vazante)
        # afunda menos o canal: some-se do que se subtrai. Um nivel positivo
        # (cheia) aumenta a lamina d'agua.
        prof += self.nivel_rio_m(t_h)
        for obst in self.obstaculos_ativos(t_h):
            perda = 1.0 - obst.peso_depressao(pos)
            if perda <= 0.0:
                continue
            prof = prof * (1.0 - perda) + obst.profundidade_residual_m * perda
        return max(0.0, prof)

    def margem_sob_quilha_m(self, pos, t_h: float, calado_m: float) -> float:
        return self.profundidade_m(pos, t_h) - calado_m

    def resumo(self, t_h: float) -> dict:
        ativos = self.obstaculos_ativos(t_h)
        return {
            "codigo": self.codigo,
            "nome": self.nome,
            "nivel_rio_m": round(self.nivel_rio_m(t_h), 2),
            "obstaculos_ativos": len(ativos),
            "obstaculos_total": len(self.obstaculos),
            "descricao": self.descricao,
        }


# ---------------------------------------------------------------------------
# 5. Definicao dos tres cenarios do artigo
# ---------------------------------------------------------------------------
def _baixios_vazante() -> list[Obstaculo]:
    """Doze baixios sazonais distributes ao longo do trecho (artigo, secao 5.2)."""
    baixios: list[Obstaculo] = []
    posicoes_km = [12.0, 26.0, 39.0, 51.0, 63.0, 74.0,
                   86.0, 99.0, 111.0, 124.0, 138.0, 155.0]
    for i, km in enumerate(posicoes_km, start=1):
        baixios.append(
            Obstaculo(
                identificacao=f"BAIXIO_VAZ_{i:02d}",
                canal=CANAL_PRINCIPAL.nome,
                km=km,
                raio_km=1.9,
                borda_km=0.5,
                # rebaixamento residual tipico de um baixio de varzea exposto
                profundidade_residual_m=3.1 + 0.35 * ((i % 4) - 1.5),
                rotulo=f"Baixio sazonal {i}",
            )
        )
    return baixios


def _terra_caida() -> Obstaculo:
    return Obstaculo(
        identificacao="TERRA_CAIDA_KM170",
        canal=CANAL_PRINCIPAL.nome,
        km=170.0,
        raio_km=4.5,
        borda_km=0.6,
        profundidade_residual_m=2.5,
        t_inicio_h=72.0,   # dia 3 do experimento de 7 dias
        t_fim_h=math.inf,
        rotulo="Terra caida (desmoronamento de margem)",
    )


CENARIOS: dict[str, CenarioHidrologico] = {
    "C1": CenarioHidrologico(
        codigo="C1",
        nome="Normal",
        descricao="Nivel hidrologico de referencia; sem obstaculos mapeados.",
    ),
    "C2": CenarioHidrologico(
        codigo="C2",
        nome="Vazante",
        descricao="Nivel 8 m abaixo da referencia; 12 baixios sazonais expostos.",
        rebaixamento_m=-8.0,
        obstaculos=_baixios_vazante(),
    ),
    "C3": CenarioHidrologico(
        codigo="C3",
        nome="Terra Caida",
        descricao="Desmoronamento no km 170 no dia 3; leito passa de 15 m a 2,5 m.",
        variacao_diurna_m=0.5,
        obstaculos=[_terra_caida()],
    ),
}

CODIGOS_CENARIO: list[str] = list(CENARIOS)


def obter_cenario(codigo: str) -> CenarioHidrologico:
    if codigo not in CENARIOS:
        raise KeyError(f"cenario desconhecido: {codigo!r} (use um de {CODIGOS_CENARIO})")
    return CENARIOS[codigo]


# ---------------------------------------------------------------------------
# 6. VARREDURA RAPIDA PARA A CARTA NAUTICA
# ---------------------------------------------------------------------------
def grade_profundidade(cenario: CenarioHidrologico, t_h: float, nx: int, ny: int):
    """
    Amostra a batimetria numa grade regular do bbox geodesico.

    Devolve (prof_m, lats, lons) com `prof_m` de forma (ny, nx). Usado para
    colorir a carta nautica e para a estatistica descritiva de risco.

    A malha inteira e resolvida numa unica chamada vetorizada. A versao
    anterior percorria nx*ny celulas em Python, cada uma refazendo a distancia
    ponto-a-ponto ate a polilinha do canal, o que tornava a geracao da carta
    lenta a ponto de nao poder ser refeita a cada atualizacao do cenario na
    interface.
    """
    from flora_geometria import (
        ALTURA_MENU_SUP,
        ALTURA_TELA_BASE,
        LARGURA_SIMULACAO_BASE,
        LAT_BOTTOM,
        LAT_TOP,
        LONG_LEFT,
        LONG_RIGHT,
    )

    lons = np.linspace(LONG_LEFT, LONG_RIGHT, nx)
    lats = np.linspace(LAT_TOP, LAT_BOTTOM, ny)
    posicoes, indice, dists = grade_distancias(nx, ny)
    prof = cenario.profundidades_de_distancias(
        indice, dists, t_h, posicoes
    ).reshape(ny, nx)
    return prof, lats, lons


def grade_leito(cenario: CenarioHidrologico, t_h: float, nx: int, ny: int):
    """
    Como `grade_profundidade`, mas devolve tambem a faixa de agua.

    Devolve (prof_m, agua, lats, lons), com `agua` um arranho booleano de forma
    (ny, nx) que marca as celulas dentro da secao transversal do canal mais
    proximo. A carta precisa dos dois: a profundidade sozinha nao separa terra de
    agua, porque o modelo nao tem topografia fora do leito. Ver `mascara_agua` em
    `flora_mapa.py`.
    """
    from flora_geometria import (
        LAT_BOTTOM,
        LAT_TOP,
        LONG_LEFT,
        LONG_RIGHT,
    )

    lons = np.linspace(LONG_LEFT, LONG_RIGHT, nx)
    lats = np.linspace(LAT_TOP, LAT_BOTTOM, ny)
    posicoes, indice, dists = grade_distancias(nx, ny)
    prof = cenario.profundidades_de_distancias(indice, dists, t_h, posicoes)
    agua = mascara_agua(indice, dists).reshape(ny, nx)
    return prof.reshape(ny, nx), agua, lats, lons


# Malhas de distancia por resolucao. A distancia ao eixo do canal nao muda com
# o tempo nem com o cenario hidrologico, apenas com a geometria fixa do
# rio; portanto ela e resolvida uma unica vez por (nx, ny) e reaproveitada a cada
# atualizacao. E o que permite refazer a batimetria em ~1 ms em vez de ~215 ms.
_CACHE_DISTANCIAS: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}


def grade_distancias(nx: int, ny: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Malha (posicoes, indice_do_canal, distancia_em_km) para a grade (nx, ny).

    Devolve tres arrays achatados, com ny*nx elementos, na ordem usada por
    `grade_profundidade`. As posicoes viajam junto porque a depressao dos
    obstaculos depende delas: sem elas os baixios seriam avaliados na origem.
    O resultado e somente leitura.
    """
    chave = (int(nx), int(ny))
    if chave not in _CACHE_DISTANCIAS:
        from flora_geometria import (
            ALTURA_MENU_SUP,
            ALTURA_TELA_BASE,
            LARGURA_SIMULACAO_BASE,
            LAT_BOTTOM,
            LAT_TOP,
            LONG_LEFT,
            LONG_RIGHT,
        )

        lons = np.linspace(LONG_LEFT, LONG_RIGHT, nx)
        lats = np.linspace(LAT_TOP, LAT_BOTTOM, ny)
        malha_lon, malha_lat = np.meshgrid(lons, lats)
        # `geo_para_mundo` e afim, entao a malha geografica pode ser convertida em
        # bloco, com os mesmos coeficientes da conversao ponto a ponto.
        x = (malha_lon - LONG_LEFT) / (LONG_RIGHT - LONG_LEFT) * LARGURA_SIMULACAO_BASE
        y = ALTURA_MENU_SUP + (malha_lat - LAT_TOP) / (LAT_BOTTOM - LAT_TOP) * ALTURA_TELA_BASE
        posicoes = np.ascontiguousarray(np.column_stack([x.ravel(), y.ravel()]))
        dists = np.stack(
            [canal.distancias_ao_eixo_km(posicoes) for canal in CANAIS.values()]
        )
        indice = np.argmin(dists, axis=0)
        melhor = np.take_along_axis(dists, indice[None, :], axis=0)[0]
        for arr in (posicoes, indice, melhor):
            arr.flags.writeable = False
        _CACHE_DISTANCIAS[chave] = (posicoes, indice, melhor)
    return _CACHE_DISTANCIAS[chave]
