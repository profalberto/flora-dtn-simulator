"""
flora_dtn.py
============

Motor de simulacao DTN-LoRa do projeto FLoRA.

Diferencas estruturais em relacao ao simulador legado
-----------------------------------------------------
1. Passo de tempo fixo. Toda a fisica e integrada em `passo_s` segundos de
   tempo de simulacao e as velocidades sao expressas em km/h. O tempo
   simulado deixa de depender da taxa de quadros da maquina.
2. Roteamento explicito. Cinco protocolos comparaveis (epidemico,
   spray-and-wait, FLoRA por utilidade, LoRaWAN puro, sistema convencional)
   em vez do "union completo" unico do legado.
3. Custos fisicos. Cada entrega custa airtime, energia e orcamento de duty
   cycle, e bundles disputam espaco finito no buffer store-and-carry.
4. Metricas do artigo. TED, LPA, CAR, TCI, overhead de copias, saltos e
   energia sao calculadas durante a execucao e exportadas.

Unidades: tempo em segundos, distancia em quilometros, posicao de estado em
pixels do canvas (ver flora_geometria).
"""

from __future__ import annotations

import csv as _csv
import json
import math
import random
from dataclasses import asdict, dataclass, field

import numpy as np

from flora_cenario import (
    CenarioHidrologico,
    classificar_margem,
    cor_risco,
    obter_cenario,
)
from flora_geometria import (
    CANAIS,
    CANAL_PRINCIPAL,
    KM_POR_PX,
    OFFSETO_FAIXA_KM,
    Canal,
    cobertura_gateways,
    mundo_para_geo,
)
from flora_lora import PERFIS_POR_TIPO, TAMANHO_PACOTE_LORA_B, ParametrosLora

#: Quilometros por hora em um no nautico. O modelo integra em km/h porque a
#: escala do rio e dada em km; a interface mostra o valor em nos, que e a
#: unidade de quem navega.
KM_POR_NO = 1.852

# ===========================================================================
# 1. CATEGORIAS DE BUNDLE
# ===========================================================================
CAT_SEGURANCA = "seguranca"
CAT_ROTINA = "rotina"
CATEGORIAS = (CAT_SEGURANCA, CAT_ROTINA)

#: Pesos de prioridade do protocolo FLoRA (artigo, secao 4.2).
PRIORIDADE = {CAT_SEGURANCA: 10, CAT_ROTINA: 1}

#: Vida maxima de um bundle, em segundos.
#:
#: Definem o prazo em que uma leitura ainda serve para alguma coisa. Uma
#: atualizacao de rota com um dia de vida ja esta vencida para efeito de CAR
#: (que exige 6 h); mantê-la nao melhora nenhuma metrica e apenas infla o
#: store, multiplicando o custo de varrer o buffer a cada passo.
TTL_PADRAO_S = {CAT_SEGURANCA: 24 * 3600.0, CAT_ROTINA: 6 * 3600.0}

#: Tempo de validade de um bundle de rota para efeito da metrica CAR.
VALIDIDADE_ROTA_H = 6.0

#: Colunas do CSV de frota, na ordem em que sao gravadas e documentadas.
_CAMPOS_FROTA = (
    "ID", "Tipo", "Nome", "Canal", "Km_Rota", "Progresso_pct", "Sentido",
    "Latitude", "Longitude", "Profundidade_m", "Calado_m", "Margem_Sob_Quilha_m",
    "Classe_Risco", "Velocidade_km_h", "Viagens_Completas", "Distancia_Percorrida_km",
    "Buffer_Bundles", "Pacotes_Buffer", "Bundles_Criados", "Transmitidos",
    "Recebidos", "Saltos", "Contatos", "Gateways_Visitados", "Frames_TX",
    "Frames_RX", "Transmissoes_Adiadas", "Airtime_s", "Energia_mJ",
)


# ===========================================================================
# 2. CONFIGURACAO
# ===========================================================================
@dataclass
class ConfiguracaoDTN:
    """Parametros de um experimento. Tudo que afeta o resultado esta aqui."""

    semente: int = 2026
    cenario: str = "C1"
    protocolo: str = "flora"

    passo_s: float = 10.0
    horizonte_h: float = 24.0 * 7.0

    composicao_frota: dict[str, int] = field(
        default_factory=lambda: {"PRINCIPAL": 4, "LANCHA": 6, "RIBEIRINHO": 5}
    )
    densidade_frota: str | None = None

    #: Multiplicador do alcance nominal de cada perfil LoRa. O legado usava
    #: 95 px == 18,5 km, acima dos 15 km declarados no artigo.
    fator_alcance: float = 1.0
    #: Fracao do alcance perdida por sombreamento (vegetacao de margem e
    #: curvatura do canal), aplicada de forma reproduzivel por par de nos.
    perda_sombreamento: float = 0.25

    taxa_rotina_h: float = 0.50
    taxa_seguranca_h: float = 0.08
    taxa_alerta_zona_critica_h: float = 3.00

    limite_buffer: int = 120
    horizonte_ted_h: float = 6.0
    limiar_cobertura_tci: float = 0.90

    # -- parametros do protocolo FLoRA (Algoritmo 1 do artigo) --
    # sigma_d precisa ser da ordem da distancia entre pontos de drenagem. Com
    # 40 km, todo o corredor estava a menos de 24 km de algum gateway e o termo
    # espacial ficava praticamente constante: o FLoRA degenerava em inundacao.
    utilidade_alpha: float = 1.0
    utilidade_sigma_d_km: float = 30.0
    utilidade_sigma_t_h: float = 12.0
    limiar_utilidade: float = 0.50
    #: O vizinho tem de ser pelo menos 20% mais util que quem detem o bundle.
    #: Com 1.0 (melhoria estritamente positiva), qualquer ganho marginal gera
    #: uma copia nova e o protocolo volta a se aproximar da inundacao; 1.2 e a
    #: histerese usual para conter a proliferacao de copias.
    fator_retencao: float = 1.20

    # -- parametros do spray-and-wait --
    copias_spray: int = 2

    # -- pontos de drenagem (gateways) --
    #: Alcance, em km, de um gateway fixo de cidade. Eh o alcance efetivo com
    #: que a embarcacao completa o uplink, e nao o alcance nominal de LoRa: a
    #: margem de sombreamento, a curvatura da meandrada e a obstrucao por
    #: vegetacao de margem ja estao embutidas nesse numero.
    alcance_gateway_fixo_km: float = 8.0
    #: Tipos de embarcacao que carregam terminal de backhaul e portanto drenam
    #: a internet para quem esta em alcance. Vazio desliga os gateways moveis.
    tipos_gateway_movel: tuple[str, ...] = ("PRINCIPAL",)
    #: Alcance de radio do gateway movel: o mesmo enlace LoRa entre vessels.
    alcance_gateway_movel_km: float = 15.0
    #: Gargalo do terminal de backhaul, em bundles por hora de simulacao.
    #:
    #: Este e o parametro que decide se o experimento diz alguma coisa. Com as
    #: cidades do corridor todas servidas por gateway fixo, o corredor inteiro
    #: fica com cobertura de radio, e o que passa a ser escasso e a subida para
    #: a internet, nao a comunicacao entre as embarcoacoes. E assim que o
    #: enlace de um barge com VSAT se comporta na pratica, e e o regime em que
    #: escolher o que subir primeiro - que e o que o FLoRA faz - importa.
    bundles_por_hora_gateway_movel: float = 20.0

    def validar(self) -> None:
        obter_cenario(self.cenario)
        if self.protocolo not in NOMES_PROTOCOLO:
            raise ValueError(
                f"protocolo desconhecido: {self.protocolo!r} (use um de {sorted(NOMES_PROTOCOLO)})"
            )
        if self.passo_s <= 0:
            raise ValueError("passo_s deve ser positivo")
        if self.horizonte_ted_h <= 0:
            raise ValueError("horizonte_ted_h deve ser positivo")
        if self.fator_alcance <= 0:
            raise ValueError("fator_alcance deve ser positivo")
        if self.alcance_gateway_fixo_km <= 0:
            raise ValueError("alcance_gateway_fixo_km deve ser positivo")
        if self.bundles_por_hora_gateway_movel < 0:
            raise ValueError("bundles_por_hora_gateway_movel nao pode ser negativo")
        desconhecidos = set(self.tipos_gateway_movel) - set(PERFIS_EMBARCACAO)
        if desconhecidos:
            raise ValueError(
                f"tipos_gateway_movel desconhecidos: {sorted(desconhecidos)}"
            )


# ===========================================================================
# 3. BUNDLE
# ===========================================================================
@dataclass
class Bundle:
    """Unidade de informacao hidrográfica em transito (store-carry-forward)."""

    bid: str
    categoria: str
    origem: int
    t_criacao_s: float
    carga: dict
    saltos: int = 0
    copias: int = 1
    t_primeira_entrega_s: float | None = None

    @property
    def prioridade(self) -> int:
        return PRIORIDADE[self.categoria]

    @property
    def eh_rota(self) -> bool:
        return self.carga.get("classe") == "rota"

    def idade_h(self, t_s: float) -> float:
        return max(0.0, (t_s - self.t_criacao_s) / 3600.0)

    def expirado(self, t_s: float) -> bool:
        return (t_s - self.t_criacao_s) > TTL_PADRAO_S[self.categoria]

    def descricao(self) -> str:
        c = self.carga
        return (
            f"{self.categoria}|msk={c.get('margem_sob_quilha_m', 0.0):5.2f}m|"
            f"km={c.get('km', 0.0):6.1f}"
        )

    def copia(self, saltos: int, copias: int = 1) -> "Bundle":
        return Bundle(
            bid=self.bid,
            categoria=self.categoria,
            origem=self.origem,
            t_criacao_s=self.t_criacao_s,
            carga=dict(self.carga),
            saltos=saltos,
            copias=copias,
            t_primeira_entrega_s=self.t_primeira_entrega_s,
        )


# ===========================================================================
# 4. UTILIDADE (equacao do protocolo FLoRA)
# ===========================================================================
class ContextoRoteamento:
    """Dados compartilhados que um protocolo precisa para decidir um repasse."""

    __slots__ = ("supernos", "t_s", "_d_eixo")

    def __init__(self, supernos: list["SuperNo"], t_s: float, frota=None, d_eixo=None) -> None:
        self.supernos = supernos
        self.t_s = t_s
        #: Distancia de cada no da frota ao eixo de cada canal, resolvida uma
        #: unica vez por passo. Rotear consulta essa distancia uma vez por
        #: superno candidato; recalcular por chamada multiplicava o custo do
        #: passo pelo numero de supernos.
        self._d_eixo: dict[int, np.ndarray] = dict(d_eixo) if d_eixo else {}
        if frota and not self._d_eixo:
            posicoes = [no.pos for no in frota]
            for canal in {sn.canal for sn in supernos}:
                self._d_eixo[id(canal)] = canal.distancias_ao_eixo_km(posicoes)

    def d_eixo_km(self, no) -> float:
        arr = self._d_eixo.get(id(no.canal))
        return float(arr[no.indice_frota]) if arr is not None else no.canal.distancia_ao_eixo_km(no.pos)

    def distancia_ate_roteiro_km(self, no) -> float:
        """
        Distancia do no ate o superno de internet mais proximo, medida ao
        longo do canal.

        Esta e a instancia concreta da "proximidade espacial a rota planejada"
        da funcao de utilidade do artigo: um bundle e mais util para um no
        que ainda esta longe de qualquer saida para a internet.
        """
        melhor = math.inf
        for sn in self.supernos:
            arr = self._d_eixo.get(id(sn.canal))
            d = float(arr[no.indice_frota]) if arr is not None else no.canal.distancia_ao_eixo_km(sn.pos)
            d += abs(sn.km_canal - no.km_atual)
            if d < melhor:
                melhor = d
        return melhor if melhor < math.inf else no.canal.comprimento_km


def utilidade_bundle(
    bundle: Bundle, t_s: float, no, ctx: ContextoRoteamento, cfg: ConfiguracaoDTN
) -> float:
    """
    u = alpha * exp(-d/sigma_d) * exp(-t/sigma_t) * peso_prioridade

    `d` e a distancia do no ate o superno mais proximo, em km; `t` e a idade do
    bundle, em horas. Um bundle de seguranca vale 10x um rotineiro, na proporcao
    definida no artigo.
    """
    return (
        cfg.utilidade_alpha
        * math.exp(-ctx.distancia_ate_roteiro_km(no) / cfg.utilidade_sigma_d_km)
        * math.exp(-bundle.idade_h(t_s) / cfg.utilidade_sigma_t_h)
        * bundle.prioridade
    )


def ganho_relativo_bundle(
    bundle: Bundle, t_s: float, no, ctx: ContextoRoteamento, cfg: ConfiguracaoDTN
) -> float:
    """
    Termo espaco-temporal da utilidade, SEM o peso de prioridade.

    O limiar de decisao tem de ser aplicado a este termo. Aplica-lo a `u` faria
    o peso de seguranca (10) transformar o corte em decorativo: um bundle de
    seguranca atravessaria qualquer limiar por mais longe que estivesse da
    saida para a internet, e o FLoRA passaria a se comportar como inundacao com
    alguns saltos a mais, sem seletividade alguma.
    """
    return (
        cfg.utilidade_alpha
        * math.exp(-ctx.distancia_ate_roteiro_km(no) / cfg.utilidade_sigma_d_km)
        * math.exp(-bundle.idade_h(t_s) / cfg.utilidade_sigma_t_h)
    )


# ===========================================================================
# 5. PROTOCOLOS
# ===========================================================================
class ProtocoloDTN:
    nome = "base"
    descricao = ""
    navega_entre_embarcacoes = True

    def __init__(self, cfg: ConfiguracaoDTN) -> None:
        self.cfg = cfg

    def decidir(
        self,
        frota: list["Embarcacao"],
        vizinhos: dict[int, list[int]],
        t_s: float,
        ctx: "ContextoRoteamento",
    ) -> dict[tuple[int, int], list["Bundle"]]:
        """
        Escolhe, para cada par em encounter, quais bundles serao enviados.

        A decisao e tomada por NÓ, com a lista completa de seus vizinhos
        disponiveis, e nao par a par. E o que permite a um protocolo seletivo
        distinguir "este vizinho e o melhor caminho" de "todos estes vizinhos
        servem": consultados um par por vez, todos os protocolos se comportam
        igual a inundacao, porque nao ha como comparar candidatos.
        """
        return self._padrao(frota, vizinhos, t_s)

    def _padrao(self, frota, vizinhos, t_s) -> dict[tuple[int, int], list["Bundle"]]:
        """Entrega a cada vizinho tudo o que ainda estiver valido."""
        decisoes: dict[tuple[int, int], list[Bundle]] = {}
        for i, no in enumerate(frota):
            vivos = [bd for bd in no.buffer.values() if not bd.expirado(t_s)]
            if not vivos:
                continue
            for j in vizinhos.get(i, ()):
                decisoes[(i, j)] = list(vivos)
        return decisoes

    def ajustar_no(self, no) -> None:
        """Ajuste opcional do estado do no quando o protocolo e instalado."""


class ProtocoloEpidemico(ProtocoloDTN):
    """Inundacao: toda copia e entregue a toda vizinha. Upper bound de entrega."""

    nome = "epidemico"
    descricao = "Inundacao total (flooding): entrega maxima, overhead maximo."


class ProtocoloSprayWait(ProtocoloDTN):
    """
    Spray-and-wait: distribui L copias por encounter e depois espera.

    Cada bundle recebe `copias_spray` oportunidades de envio, uma por vizinho
    distinto.
    Ao esgotar as copias, a embarcacao retem o bundle e so o entrega a um
    superno: nao ha conhecimento de rota para escolher a quem enviar.
    """

    nome = "spray"
    descricao = "Spray-and-wait com L copias; sem conhecimento de rota."

    def decidir(self, frota, vizinhos, t_s, ctx):
        decisoes: dict[tuple[int, int], list[Bundle]] = {}
        for i, no in enumerate(frota):
            alvos = vizinhos.get(i, ())
            if not alvos:
                continue
            for bd in list(no.buffer.values()):
                if bd.expirado(t_s):
                    continue
                # bundles com uma unica copia entram na fase de espera e nao
                # sao mais pulverizados; ainda podem ser entregues a gateways
                if bd.copias <= 1:
                    continue
                restantes = bd.copias
                for j in alvos:
                    if restantes <= 1:
                        break
                    decisoes.setdefault((i, j), []).append(bd)
                    restantes -= 1
        return decisoes

    def ajustar_no(self, no) -> None:
        no.copias_iniciais = self.cfg.copias_spray
        for bd in no.buffer.values():
            bd.copias = max(1, min(bd.copias, no.copias_iniciais))


class ProtocoloFLoRA(ProtocoloDTN):
    """
    Protocolo FLoRA (Algoritmo 1): encaminhamento seletivo por utilidade.

    Para cada bundle que uma embarcacao detem, o protocolo olha todos os
    vizinhos disponiveis e encaminha para UM deles: o de maior utilidade, desde
    que ela supere o limiar e supere com folga a utilidade de quem detem a
    informacao. E esse "um unico melhor caminho" que distingue o FLoRA da
    inundacao: a copia caminha em direcao a saida para a internet em vez de se
    multiplicar por todo o grafo de encounter.
    """

    nome = "flora"
    descricao = "Seletivo por utilidade u = a*e^(-d/sd)*e^(-t/st)*w, um melhor caminho por bundle."

    def decidir(self, frota, vizinhos, t_s, ctx):
        cfg = self.cfg
        decisoes: dict[tuple[int, int], list[Bundle]] = {}
        for i, no in enumerate(frota):
            alvos = vizinhos.get(i, ())
            if not alvos:
                continue
            u_origem_no = [ctx.distancia_ate_roteiro_km(frota[j]) for j in alvos]
            for bd in no.buffer.values():
                if bd.expirado(t_s):
                    continue
                idade = math.exp(-bd.idade_h(t_s) / cfg.utilidade_sigma_t_h)
                base_origem = cfg.utilidade_alpha * math.exp(
                    -ctx.distancia_ate_roteiro_km(no) / cfg.utilidade_sigma_d_km
                ) * idade
                u_origem = base_origem * bd.prioridade
                melhor_j = -1
                melhor_ganho = cfg.limiar_utilidade
                for k, j in enumerate(alvos):
                    ganho = (cfg.utilidade_alpha
                             * math.exp(-u_origem_no[k] / cfg.utilidade_sigma_d_km)
                             * idade * bd.prioridade)
                    if ganho > melhor_ganho and ganho > cfg.fator_retencao * base_origem:
                        melhor_ganho = ganho
                        melhor_j = j
                if melhor_j >= 0:
                    decisoes.setdefault((i, melhor_j), []).append(bd)
        return decisoes


class ProtocoloLoRaWanPuro(ProtocoloDTN):
    """
    Linha de base SLP: LoRaWAN puro, sem fase de transporte DTN entre
    embarcacoes. Um bundle so chega a internet se a embarcacao passar perto de
    um superno; caso contrario a latencia permanece indefinida.
    """

    nome = "slp"
    descricao = "LoRaWAN puro: coleta apenas por cobertura de gateway, sem relay DTN."
    navega_entre_embarcacoes = False

    def decidir(self, frota, vizinhos, t_s, ctx):
        return {}


class ProtocoloConvencional(ProtocoloDTN):
    """
    Linha de base SC: sem coleta e sem compartilhamento entre embarcacoes.
    Representa o status quo, em que cada operador mantem sua propria carta
    nautica desatualizada.
    """

    nome = "sc"
    descricao = "Sistema convencional: sem coleta e sem compartilhamento entre embarcacoes."
    navega_entre_embarcacoes = False

    def decidir(self, frota, vizinhos, t_s, ctx):
        return {}


PROTOCOLOS: dict[str, type[ProtocoloDTN]] = {
    ProtocoloEpidemico.nome: ProtocoloEpidemico,
    ProtocoloSprayWait.nome: ProtocoloSprayWait,
    ProtocoloFLoRA.nome: ProtocoloFLoRA,
    ProtocoloLoRaWanPuro.nome: ProtocoloLoRaWanPuro,
    ProtocoloConvencional.nome: ProtocoloConvencional,
}
NOMES_PROTOCOLO = list(PROTOCOLOS)

#: Rotulos amigaveis para menus e relatorios.
ROTULOS_PROTOCOLO: dict[str, str] = {
    "flora": "FLoRA (utilidade)",
    "epidemico": "Epidemico (flooding)",
    "spray": "Spray-and-wait",
    "slp": "SLP (LoRaWAN puro)",
    "sc": "SC (convencional)",
}


def criar_protocolo(cfg: ConfiguracaoDTN) -> ProtocoloDTN:
    return PROTOCOLOS[cfg.protocolo](cfg)


# ===========================================================================
# 6. SUPER NO DE CIDADE
# ===========================================================================
class SuperNo:
    """
    Ponto de drenagem para a internet, por fibra optica, satelite ou rede celular.

    Ha dois tipos, com o mesmo comportamento de drenagem e diferindo no que os
    torna distintos:

    * **fixo**, ancorado numa cidade do corredor, com rede de terra e sem limite
      de vazao;
    * **movel**, embarcado numa embarcacao grande que carrega terminal de
      backhaul. Ele se move com a embarcacao e tem a subida limitada por
      `bundles_por_h`, porque o gargalo de um terminal a bordo e a taxa do
      enlace de retorno, nao o radio LoRa.
    """

    def __init__(
        self,
        chave: str,
        nome: str,
        canal: Canal,
        km: float | None = None,
        alcance_km: float = 15.0,
        anfitriao=None,
        bundles_por_h: float = 0.0,
        km_canal: float | None = None,
        pos: np.ndarray | None = None,
        movel: bool | None = None,
    ) -> None:
        self.chave = chave
        self.nome = nome
        self.canal = canal
        km_val = km if km is not None else (km_canal if km_canal is not None else 0.0)
        self.km_canal = float(km_val)
        self.alcance_km = alcance_km
        if pos is not None:
            self.pos = np.asarray(pos, dtype=float).copy()
        else:
            self.pos, _, _ = canal.posicao_em(self.km_canal)
        self.drenados: dict[str, float] = {}
        self.embarcoes_atendidas: set[int] = set()
        self.pacotes_drenados = 0
        #: Embarcacao que carrega o terminal, ou None num gateway fixo.
        self.anfitriao = anfitriao
        self.bundles_por_h = bundles_por_h
        #: Cota de subida do passo corrente, em bundles. E fracionaria: um
        #: terminal de 20 bundles/h gasta a cota em 18 s, nao de uma vez.
        self._cota = 0.0
        #: Bundles que chegaram ao terminal e ficaram esperando cota. Serve para
        #: mostrar na ficha que o gargalo e subida, e nao falta de cobertura.
        self.aguardando_cota = 0
        self.sincronizar()

    @property
    def movel(self) -> bool:
        return self.anfitriao is not None

    def sincronizar(self) -> None:
        """Reposiciona o gateway movel junto da embarcacao que o carrega."""
        if self.anfitriao is not None:
            self.canal = self.anfitriao.canal
            self.km_canal = self.anfitriao.km_atual
            self.pos = self.anfitriao.pos

    def acumular_cota(self, passo_s: float) -> None:
        """Converte tempo decorrido em cota de subida."""
        if self.movel:
            self._cota += self.bundles_por_h * passo_s / 3600.0

    def em_alcance(self, no, d_eixo_km: float | None = None) -> bool:
        """
        O no esta em alcance deste superno?

        `d_eixo_km` permite reaproveitar a distancia ao eixo ja calculada para a
        frota inteira no passo corrente, evitando uma varredura da polilinha
        por no e por superno.
        """
        d = d_eixo_km if d_eixo_km is not None else no.canal.distancia_ao_eixo_km(self.pos)
        return d + abs(self.km_canal - no.km_atual) <= self.alcance_km

    def drenar(self, no, t_s: float) -> list[Bundle]:
        """
        Coleta os bundles que a embarcacao tem a oferecer neste instante.

        Enviar para a internet NAO apaga a copia local. Um dispositivo IoT que
        faz upload de uma leitura continua com ela a bordo, e e justamente essa
        copia que permite repassar a informacao adiante para um vizinho que
        ainda nao a tem. Tratar o envio como consumo destruiria a informacao
        compartilhada: depois do primeiro upload nao restaria nada para
        dissemination, e a metrica de atualizacao de rotas (CAR) seria sempre
            zero por construcao, para qualquer protocolo.
        """
        self.embarcoes_atendidas.add(no.id)
        no.gateways_em_contato.add(self.chave)
        if self.chave not in no.gateways_visitados:
            no.gateways_visitados.append(self.chave)
        return list(no.buffer.values())


#: (chave, nome, canal, km ao longo do canal, alcance em km)
#:
#: O desenho dos pontos de drenagem e o que decide se a camada DTN tem alguma
#: funcao no experimento. Ver `cobertura_gateways` em `flora_geometria`: o que
#: importa e a fracao da rota sem acesso a internet e o tamanho do maior vao.
#:
#: Com as cidades do corridor servidas por gateway fixo, o vao entre Itapiranga
#: (km 70) e Urucurituba (km 96) e o maior, e ele e o que ainda separa os
#: protocolos. Ver o painel e o CSV antes de comparar: se a cobertura chegar a
#: 100%, nenhum protocolo se distingue, porque a informacao sobe direto por
#: LoRaWAN e o repasse deixa de existir.
#:
#: As posicoes nao sao digitadas: `construir_supernos` ancora cada cidade na
#: polilinha do canal, de modo que o gateway fica na cidade de verdade.
def construir_supernos(alcance_km: float) -> list[SuperNo]:
    from flora_geometria import ancorar_cidades

    return [
        SuperNo(chave, nome, canal, km, alcance_km)
        for chave, nome, canal, km, _desvio in ancorar_cidades()
    ]


def construir_frota(cfg: "ConfiguracaoDTN") -> list["Embarcacao"]:
    """Monta a frota padrao a partir da composicao/densidade, com a semente de cfg."""
    composicao = cfg.composicao_frota
    if getattr(cfg, "densidade_frota", None):
        composicao = composicao_por_densidade(cfg.densidade_frota, composicao)
    rng = random.Random(cfg.semente)
    frota: list["Embarcacao"] = []
    id_no = 0
    for tipo, quantidade in composicao.items():
        for _ in range(quantidade):
            frota.append(Embarcacao(id_no, tipo, CANAL_PRINCIPAL, rng))
            id_no += 1
    return frota
    from flora_geometria import ancorar_cidades

    return [
        SuperNo(chave, nome, canal, km, alcance_km)
        for chave, nome, canal, km, _desvio in ancorar_cidades()
    ]


def construir_supernos_moveis(frota, cfg: "ConfiguracaoDTN") -> list[SuperNo]:
    """
    Um gateway movel por embarcacao do tipo configurado em `tipos_gateway_movel`.

    A ordenacao por tipo importa: os grupos do protocolo decidem o que fazer com
    o que o superno drena, e o superno movel entra na lista com as demais
    embarcacoes, sem tratamento especial.
    """
    if not cfg.tipos_gateway_movel or cfg.bundles_por_hora_gateway_movel <= 0:
        return []
    return [
        SuperNo(f"movel_{no.id}", f"Backhaul {no.tipo} {no.id}", no.canal,
                no.km_atual, cfg.alcance_gateway_movel_km, anfitriao=no,
                bundles_por_h=cfg.bundles_por_hora_gateway_movel)
        for no in frota
        if no.tipo in cfg.tipos_gateway_movel
    ]


DENSIDADES_FROTA: dict[str, int] = {
    "muito_baixa": 3, "baixa": 7, "media": 14, "alta": 28, "muito_alta": 42,
}


def composicao_por_densidade(densidade: str,
                            base: dict[str, int] | None = None) -> dict[str, int]:
    base = base or {"PRINCIPAL": 4, "LANCHA": 6, "RIBEIRINHO": 5}
    alvo = DENSIDADES_FROTA.get(densidade, sum(base.values()))
    total_base = sum(base.values()) or 1
    fator = alvo / total_base
    resultado = {t: max(1, round(q * fator)) for t, q in base.items()}
    # ajusta para bater o alvo
    while sum(resultado.values()) < alvo:
        resultado[max(resultado, key=lambda t: base[t])] += 1
    while sum(resultado.values()) > alvo and len(resultado) > 1:
        t = max(resultado, key=lambda t: resultado[t])
        if resultado[t] > 1:
            resultado[t] -= 1
        else:
            break
    return resultado
    """Monta a frota padrao a partir da composicao, com a semente de ``cfg``."""
    rng = random.Random(cfg.semente)
    frota: list["Embarcacao"] = []
    id_no = 0
    for tipo, quantidade in cfg.composicao_frota.items():
        for _ in range(quantidade):
            frota.append(Embarcacao(id_no, tipo, CANAL_PRINCIPAL, rng))
            id_no += 1
    return frota


def listar_gateways(cfg: "ConfiguracaoDTN | None" = None,
                    frota: list["Embarcacao"] | None = None,
                    supernos: list["SuperNo"] | None = None,
                    moveis: list["SuperNo"] | None = None) -> dict:
    """
    Fonte unica de verdade sobre os gateways do modelo.

    Devolve um dicionario com ``fixos`` (Manaus e Itacoatiara), ``moveis``
    (um por embarcacao PRINCIPAL) e ``municipios_excluidos`` (os cinco
    municipios citados na tese que nao recebem gateway, com motivo).
    """
    from flora_geometria import CIDADES_FORA_DO_CORREDOR, mundo_para_geo

    if cfg is None:
        cfg = ConfiguracaoDTN()
    if supernos is None:
        supernos = construir_supernos(cfg.alcance_gateway_fixo_km)
    if moveis is None:
        if frota is None:
            frota = construir_frota(cfg)
        moveis = construir_supernos_moveis(frota, cfg)

    fixos = []
    for sn in supernos:
        lat, lon = mundo_para_geo(float(sn.pos[0]), float(sn.pos[1]))
        fixos.append({
            "nome": sn.nome,
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
            "km": round(float(sn.km_canal), 3),
            "raio_km": sn.alcance_km,
        })

    moveis_list = []
    for sn in moveis:
        host = getattr(sn, "anfitriao", None)
        moveis_list.append({
            "id_embarcacao": getattr(host, "id", None),
            "raio_km": sn.alcance_km,
            "cota_por_hora": sn.bundles_por_h,
        })

    excluidos = [
        {
            "nome": c["cidade"],
            "lat": c["lat"],
            "lon": c["lon"],
            "motivo": c["motivo"],
        }
        for c in CIDADES_FORA_DO_CORREDOR
    ]

    return {
        "fixos": fixos,
        "moveis": moveis_list,
        "municipios_excluidos": excluidos,
    }


# ===========================================================================
# 7. EMBARCACAO
# ===========================================================================
@dataclass
class PerfilEmbarcacao:
    tipo: str
    nome: str
    cor: tuple[int, int, int]
    tamanho_px: int
    calado_m: float
    vel_km_h: tuple[float, float]

    @property
    def velocidade_min_kmh(self) -> float:
        return self.vel_km_h[0]

    @property
    def velocidade_max_kmh(self) -> float:
        return self.vel_km_h[1]

    @property
    def velocidade_min_nos(self) -> float:
        """Velocidade minima na escala de nos nauticos (1 no = 1,852 km/h)."""
        return self.vel_km_h[0] / KM_POR_NO

    @property
    def velocidade_max_nos(self) -> float:
        """Velocidade maxima na escala de nos nauticos (1 no = 1,852 km/h)."""
        return self.vel_km_h[1] / KM_POR_NO

    @property
    def vel_nos(self) -> tuple[float, float]:
        """Faixa de velocidade (min, max) em nos nauticos."""
        return (self.velocidade_min_nos, self.velocidade_max_nos)

    @property
    def lora(self) -> ParametrosLora:
        return PERFIS_POR_TIPO[self.tipo]


PERFIS_EMBARCACAO: dict[str, PerfilEmbarcacao] = {
    "PRINCIPAL": PerfilEmbarcacao("PRINCIPAL", "Navio/balsa de recreio", (70, 130, 180), 11, 2.5, (9.0, 15.0)),
    "LANCHA": PerfilEmbarcacao("LANCHA", "Lancha rapida", (218, 112, 214), 8, 0.8, (25.0, 40.0)),
    "RIBEIRINHO": PerfilEmbarcacao("RIBEIRINHO", "Barco ribeirinho", (140, 150, 155), 6, 0.5, (5.0, 9.0)),
}

CORES_EMBARCACAO: dict[str, tuple[int, int, int]] = {
    "PRINCIPAL": (70, 130, 180),
    "LANCHA": (218, 112, 214),
    "RIBEIRINHO": (140, 150, 155),
}

#: Carga inicial herdada do simulador legado: as embarcacoes principais sao
#: as unicas que entram em rota com informacao hidrográfica a bordo.
CARGA_INICIAL = {"PRINCIPAL": (1, 2), "LANCHA": (0, 2), "RIBEIRINHO": (0, 1)}


class Embarcacao:
    """No movel da rede: sensor, transportador de dados e plataforma de decisao."""

    def __init__(
        self,
        id_no: int | None = None,
        tipo: str = "PRINCIPAL",
        canal: Canal | None = None,
        rng: random.Random | None = None,
        km_atual: float | None = None,
        sentido: int | None = None,
        offset_faixa_km: float | None = None,
        velocidade_km_h: float | None = None,
        pos: np.ndarray | None = None,
        id: int | None = None,
        calado_m: float | None = None,
        lora: ParametrosLora | None = None,
        cor_base: tuple[int, int, int] | None = None,
        indice_frota: int | None = None,
    ) -> None:
        perfil = PERFIS_EMBARCACAO[tipo]
        final_id = id if id is not None else (id_no if id_no is not None else 0)
        self.id = final_id
        self.indice_frota = indice_frota if indice_frota is not None else final_id
        self.tipo = tipo
        self.nome_tipo = perfil.nome
        self.cor_base = cor_base if cor_base is not None else perfil.cor
        self.tamanho = perfil.tamanho_px
        self.calado_m = calado_m if calado_m is not None else perfil.calado_m
        self.lora: ParametrosLora = lora if lora is not None else PERFIS_POR_TIPO[tipo]
        self.canal = canal if canal is not None else CANAL_PRINCIPAL
        self.copias_iniciais = 2

        _rng = rng if rng is not None else random.Random()

        if km_atual is not None:
            self.km_atual = float(km_atual)
        else:
            self.km_atual = _rng.uniform(0.0, self.canal.comprimento_km)

        if sentido is not None:
            self.sentido = 1 if sentido >= 0 else -1
        else:
            self.sentido = 1 if _rng.random() < 0.5 else -1

        if offset_faixa_km is not None:
            self.offset_faixa_km = float(offset_faixa_km)
        else:
            self.offset_faixa_km = OFFSETO_FAIXA_KM * self.sentido * _rng.uniform(0.72, 1.0)

        if velocidade_km_h is not None:
            self.velocidade_km_h = float(velocidade_km_h)
        else:
            self.velocidade_km_h = _rng.uniform(*perfil.vel_km_h)

        if pos is not None:
            self._pos = np.asarray(pos, dtype=float).copy()
        else:
            self._pos = self.canal.posicao_em(self.km_atual, self.offset_faixa_km)[0]

        self.lat, self.lon = mundo_para_geo(*self._pos)
        self.t_s = 0.0

        self.buffer: dict[str, Bundle] = {}
        #: Bundle ids que esta embarcacao ja enviou a um superno, para nao
        #: reenviar a mesma leitura a cada passo enquanto ela estiver a bordo.
        self.bids_enviados: set[str] = set()
        #: Bundle ids que esta embarcacao ja recebeu em algum momento, mesmo que
        #: ja os tenha repassado adiante. E o que impede a retransmissao de uma
        #: informacao que o vizinho ja possui: sem isso, protocolos de
        #: inundacao reenviam o mesmo quadro a cada passo de tempo e o custo de
        #: enlace deixa de ter relacao com a quantidade de informacao nova.
        self.bids_recebidos: set[str] = set()
        self.historico: list[np.ndarray] = [self.pos.copy()]
        self.limite_historico = 45

        self.profundidade_m = 0.0
        self.nivel_rio_m = 0.0
        self.margem_sob_quilha_m = 99.0
        self.classe_risco = "SEGURO"
        self.cor_risco = cor_risco(99.0)

        self.vizinhos_ativos: set[int] = set()
        self.contatos_ativos: set[int] = set()
        self.contatos_total = 0
        self.contatos_por_no: dict[int, int] = {}
        self.gateways_em_contato: set[str] = set()
        self.gateways_visitados: list[str] = []
        self.distancia_percorrida_km = 0.0
        self.viagens_completas = 0
        self.bundles_criados = 0
        self.bundles_expulsos = 0
        self.bundles_descartados = 0
        self.transmitidos = 0
        self.t_chegada_km_critico: float | None = None
        self.recebidos = 0
        self.saltos_totais = 0
        self.transmitiu_ao_gateway = 0
        self.janela_duty_t_s = 0.0
        self.airtime_janela_s = 0.0
        self.orcamento_duty_s = 3600.0 * self.lora.limite_duty_cycle
        self.frames_tx = 0
        self.frames_rx = 0
        self.transmissoes_adiaadas = 0
        self.airtime_s = 0.0
        self.energia_j = 0.0

        self.em_transmissao = False
        self.raio_onda = 0.0
        self.entrou_em_zona_critica = False
        self.informacao_a_tempo = False

    @property
    def velocidade_nos(self) -> float:
        """Velocidade da embarcacao em nos nauticos (1 no = 1,852 km/h)."""
        return self.velocidade_km_h / KM_POR_NO

    @property
    def pos(self) -> np.ndarray:
        return self._pos

    @pos.setter
    def pos(self, novo_pos: np.ndarray) -> None:
        self._pos = np.asarray(novo_pos, dtype=float).copy()
        self.lat, self.lon = mundo_para_geo(*self._pos)

    @property
    def progresso(self) -> float:
        return self.km_atual / max(1e-9, self.canal.comprimento_km)

    @property
    def em_zona_de_risco(self) -> bool:
        return self.margem_sob_quilha_m < 1.5

    def mover(self, dt_s: float, cenario: CenarioHidrologico) -> None:
        """
        Integra o deslocamento ao longo do canal em `dt_s` segundos.

        Este e o unico lugar onde a posicao muda, o que garante que o resultado
        dependa apenas de (semente, passo_s, horizonte) e nunca da taxa de
        quadros da maquina. Ao chegar a uma extremidade a embarcacao inverte o
        sentido e transborda a cada `comprimento_km` percorrido.

        A hidrologia nao e calculada aqui: o motor a resolve para a frota
        inteira de uma vez por passo e a atribui depois.
        """
        comprimento = self.canal.comprimento_km
        self.km_atual += self.velocidade_km_h * self.sentido * (dt_s / 3600.0)
        if self.km_atual >= comprimento:
            self.km_atual = comprimento
            self.sentido = -1
            self.viagens_completas += 1
            self.offset_faixa_km = -self.offset_faixa_km
        elif self.km_atual <= 0.0:
            self.km_atual = 0.0
            self.sentido = 1
            self.viagens_completas += 1
            self.offset_faixa_km = -self.offset_faixa_km
        self.distancia_percorrida_km += self.velocidade_km_h * (dt_s / 3600.0)

        self.pos = self.canal.posicao_em(self.km_atual, self.offset_faixa_km)[0]
        self.lat, self.lon = mundo_para_geo(*self.pos)

    def registrar_historico(self) -> None:
        self.historico.append(self.pos.copy())
        if len(self.historico) > self.limite_historico:
            del self.historico[0]

    def rotulo(self) -> str:
        return f"ID {self.id} - {self.nome_tipo}"

    def abrir_janela_duty(self, t_s: float) -> None:
        if t_s - self.janela_duty_t_s >= 3600.0:
            self.janela_duty_t_s = t_s
            self.airtime_janela_s = 0.0

    def pode_transmitir(self, airtime_s: float) -> bool:
        return self.airtime_janela_s + airtime_s <= self.orcamento_duty_s

    def registrar_tx(self, t_s: float, airtime_s: float) -> None:
        self.abrir_janela_duty(t_s)
        self.airtime_janela_s += airtime_s
        self.airtime_s += airtime_s
        self.frames_tx += 1
        self.energia_j += self.lora.energia_tx_joule(airtime_s * 1000.0)
        self.em_transmissao = True
        self.raio_onda = self.tamanho

    def registrar_rx(self, airtime_s: float) -> None:
        self.frames_rx += 1
        self.energia_j += self.lora.energia_rx_joule(airtime_s * 1000.0)

    def inserir(self, bd: Bundle, t_s: float, limite: int) -> bool:
        """
        Insere um bundle no store honoring o limite de ocupacao.

        Com o store cheio, a admissao depende de prioridade e idade: um bundle
        de seguranca novo expulsa o bundle rotineiro mais antigo; se nao houver
        o que expulsar, o bundle e descartado. Esse limite e o que diferencia
        protocolos com duplicacao (epidemico) dos protocolos seletivos (FLoRA).
        """
        if bd.bid in self.buffer:
            return False
        if len(self.buffer) >= limite:
            antes = len(self.buffer)
            self._expulsar(limite, t_s, bd)
            if len(self.buffer) >= limite:
                self.bundles_descartados += 1
                return False
        self.buffer[bd.bid] = bd
        return True

    def conhece(self, bid: str) -> bool:
        """True se a embarcacao ja detem ou ja deteve este bundle."""
        return bid in self.buffer or bid in self.bids_recebidos

    def marcar_recebido(self, bid: str) -> None:
        self.bids_recebidos.add(bid)

    def _expulsar(self, limite: int, t_s: float, novo: "Bundle | None" = None) -> None:
        if not self.buffer:
            return
        pior_bid = min(self.buffer, key=lambda k: (self.buffer[k].prioridade, self.buffer[k].idade_h(t_s), k))
        if novo is None or novo.prioridade > self.buffer[pior_bid].prioridade:
            del self.buffer[pior_bid]
            self.bundles_expulsos += 1

    def expirar(self, t_s: float) -> int:
        mortos = [bid for bid, bd in self.buffer.items() if bd.expirado(t_s)]
        for bid in mortos:
            del self.buffer[bid]
        return len(mortos)

    def pacotes(self) -> str:
        return "|".join(sorted(self.buffer))

    def tem_rota_valida(self, t_s: float) -> bool:
        return any(bd.eh_rota and bd.idade_h(t_s) <= VALIDIDADE_ROTA_H for bd in self.buffer.values())

    def resumo_painel(self) -> dict:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "velocidade_km_h": self.velocidade_km_h,
            "calado_m": self.calado_m,
            "profundidade_m": self.profundidade_m,
            "margem_sob_quilha_m": self.margem_sob_quilha_m,
            "buffer": len(self.buffer),
            "transmitidos": self.transmitidos,
            "recebidos": self.recebidos,
            "contatos": self.contatos_total,
            "frame_tx": self.frames_tx,
            "frame_rx": self.frames_rx,
            "airtime_s": self.airtime_s,
            "energia_mj": self.energia_j * 1000.0,
        }


# ===========================================================================
# 8. METRICAS
# ===========================================================================
class Metricas:
    """Acumula as metricas do artigo durante a execucao."""

    def __init__(self, cfg: ConfiguracaoDTN) -> None:
        self.cfg = cfg
        #: Preenchidos pelo motor logo apos a construcao da frota.
        self.nos = 0
        self.super_nos = 0
        self.gateways_moveis = 0
        #: Fracao do canal principal com cobertura de gateway fixo, e maior
        #: trecho sem cobertura. Sao as duas grandezas que dizem se ainda ha
        #: regiao obrigada a transportar por store-carry-forward.
        self.cobertura_gateway_percentual = 0.0
        self.maior_vao_gateway_km = 0.0
        #: Fracao da frota com ao menos um gateway em alcance, em cada passo.
        #: E a medida do que os gateways moveis acrescentam sobre a cobertura
        #: fixa, que nao muda: sem eles a frota sai das cidades por conta propria.
        self.cobertura_instantanea_percentual = 0.0
        self.cobertura_instantanea_media = 0.0
        self._soma_cobertura = 0.0
        self._amostras_cobertura = 0
        self.alcance_referencia_km: float | None = None
        self.t_s = 0.0
        self.bundles_criados = 0
        self.bundles_gerados = 0
        self.bundles_admitidos = 0
        self.bundles_descartados = 0
        self.bundles_expulsos = 0
        self.bundles_por_categoria: dict[str, int] = {c: 0 for c in CATEGORIAS}
        self.entregues_total = 0
        self.entregues_no_horizonte = 0
        self.latencias_s: list[float] = []
        self.latencias_seguranca_s: list[float] = []
        self.transmissoes = 0
        self.saltos = 0
        self.adiaadas = 0
        self.energia_j = 0.0
        self.airtime_s = 0.0
        self.frames_tx = 0
        self.encontros = 0
        self.uploads_redundantes = 0
        self.retransmissoes_suprimidas = 0
        self.cobertura_por_bid: dict[str, set[int]] = {}
        self.tci_por_bid: dict[str, float | None] = {}
        self.tci_criacao_por_bid: dict[str, float] = {}
        #: Numero minimo de nos com copia para dar um bundle por convergente.
        #: Definido pelo motor apos conhecer o tamanho da frota.
        self.limiar_cobertura = 1
        self.nos_em_zona_critica = 0
        self.nos_informados_a_tempo = 0
        self.nos_expirados = 0
        self.serie_ted: list[tuple[float, float]] = []
        self.serie_lpa: list[tuple[float, float]] = []
        self.serie_idtu: list[tuple[float, float]] = []
        self.idtu_soma: float = 0.0
        self.idtu_n: int = 0

    def registrar_criacao(self, bd: Bundle, no_id: int) -> None:
        self.bundles_criados += 1
        self.bundles_admitidos += 1
        self.bundles_por_categoria[bd.categoria] += 1
        if bd.categoria == CAT_SEGURANCA:
            self.cobertura_por_bid[bd.bid] = {no_id}
            self.tci_por_bid[bd.bid] = None
            self.tci_criacao_por_bid[bd.bid] = bd.t_criacao_s

    def registrar_cobertura(self, bid: str, no_id: int, t_s: float) -> None:
        """
        Registra a posse de um bundle por parte de um no e, no mesmo instante,
        verifica se a cobertura crossings o limiar do TCI.

        A verificacao e feita aqui, e nao numa varredura periodica de todos os
        bundles: com 7 dias de simulacao e geracao continua de informação, uma
        varredura por passo custaria trilhoes de comparacoes.
        """
        conjunto = self.cobertura_por_bid.get(bid)
        if conjunto is None:
            return
        if bid in conjunto:
            return
        conjunto.add(no_id)
    def registrar_cobertura(self, bid: str, no_id: int, t_s: float) -> None:
        conjunto = self.cobertura_por_bid.get(bid)
        if conjunto is None:
            return
        if bid in conjunto:
            return
        conjunto.add(no_id)
        if self.tci_por_bid.get(bid) is None and len(conjunto) >= self.limiar_cobertura:
            criacao = self.tci_criacao_por_bid.get(bid, t_s)
            self.tci_por_bid[bid] = max(0.0, (t_s - criacao) / 3600.0)

    def registrar_entrega(self, bd: Bundle, t_s: float) -> None:
        self.entregues_total += 1
        if bd.t_primeira_entrega_s is None:
            lat = t_s - bd.t_criacao_s
            self.latencias_s.append(lat)
            if bd.categoria == CAT_SEGURANCA:
                self.latencias_seguranca_s.append(lat)
            if bd.idade_h(t_s) <= self.cfg.horizonte_ted_h:
                self.entregues_no_horizonte += 1

    def registrar_transmissao(self, saltos: int = 1) -> None:
        self.transmissoes += 1
        self.saltos += saltos

    @property
    def ted(self) -> float:
        return 100.0 * self.entregues_total / self.bundles_gerados if self.bundles_gerados else 0.0

    @property
    def ted_no_horizonte(self) -> float:
        return 100.0 * self.entregues_no_horizonte / self.bundles_gerados if self.bundles_gerados else 0.0

    @property
    def lpa_min(self) -> float:
        if not self.latencias_seguranca_s:
            return float("nan")
        return sum(self.latencias_seguranca_s) / len(self.latencias_seguranca_s) / 60.0

    @property
    def lpa_mediana_min(self) -> float:
        if not self.latencias_s:
            return float("nan")
        ordenadas = sorted(self.latencias_s)
        return ordenadas[len(ordenadas) // 2] / 60.0

    @property
    def overhead(self) -> float:
        """
        Quadros LoRa transmitidos por bundle entregue.

        O minimo e 1.0: um bundle entregue consome pelo menos o uplink da
        embarcacao que o carregava. Acima de 1.0, o excedente e retransmissao
        entre embarcacoes e reenvio de copias ja entregues.
        """
        return self.transmissoes / self.entregues_total if self.entregues_total else float("nan")

    @property
    def saltos_medios(self) -> float:
        return self.saltos / self.entregues_total if self.entregues_total else float("nan")

    @property
    def car(self) -> float:
        """
        Cobertura de atualizacao de rotas: percentual de nos que, ao entrar em
        zona de risco, ja detinham um bundle de rota com menos de 6 h.
        """
        if not self.nos_em_zona_critica:
            return float("nan")
        return 100.0 * self.nos_informados_a_tempo / self.nos_em_zona_critica

    @property
    def tci_h(self) -> float:
        """Tempo ate 90% da frota possuir copia; media dos bundles rastreados."""
        valores = [v for v in self.tci_por_bid.values() if v is not None]
        if not valores:
            return float("inf")
        return sum(valores) / len(valores)

    @property
    def tci_mediana_h(self) -> float:
        valores = sorted(v for v in self.tci_por_bid.values() if v is not None)
        if not valores:
            return float("nan")
        n = len(valores)
        if n % 2:
            return valores[n // 2]
        return (valores[n // 2 - 1] + valores[n // 2]) / 2.0

    @property
    def tci_desvio_h(self) -> float:
        valores = [v for v in self.tci_por_bid.values() if v is not None]
        if len(valores) < 2:
            return 0.0
        import statistics
        return statistics.stdev(valores)

    def dict(self) -> dict:
        return {
            "cenario": self.cfg.cenario,
            "protocolo": self.cfg.protocolo,
            "semente": self.cfg.semente,
            "passo_s": self.cfg.passo_s,
            "tempo_simulado_h": round(self.t_s / 3600.0, 3),
            "frota": self.nos,
            "super_nos": self.super_nos,
            "gateways_moveis": self.gateways_moveis,
            "cobertura_gateway_percentual": self.cobertura_gateway_percentual,
            "maior_vao_gateway_km": self.maior_vao_gateway_km,
            "cobertura_instantanea_media": round(self.cobertura_instantanea_media, 1),
            "alcance_referencia_km": self.alcance_referencia_km,
            "bundles_criados": self.bundles_criados,
        "bundles_gerados": self.bundles_gerados,
        "bundles_admitidos": self.bundles_admitidos,
        "bundles_descartados": self.bundles_descartados,
        "bundles_expulsos": self.bundles_expulsos,
            "bundles_seguranca": self.bundles_por_categoria[CAT_SEGURANCA],
            "bundles_rotina": self.bundles_por_categoria[CAT_ROTINA],
            "entregues_total": self.entregues_total,
            "entregues_no_horizonte": self.entregues_no_horizonte,
            "ted_percentual": round(self.ted, 3),
            "ted_no_horizonte_percentual": round(self.ted_no_horizonte, 3),
            "lpa_minutos": round(self.lpa_min, 2) if self.latencias_seguranca_s else None,
            "lpa_mediana_minutos": round(self.lpa_mediana_min, 2) if self.latencias_s else None,
            "car_percentual": round(self.car, 2) if self.nos_em_zona_critica else None,
            "tci_horas": round(self.tci_h, 3) if math.isfinite(self.tci_h) else None,
            "tci_mediana_horas": round(self.tci_mediana_h, 3) if math.isfinite(self.tci_mediana_h) else None,
            "tci_desvio_horas": round(self.tci_desvio_h, 3),
            "tci_bundles_convergidos": sum(1 for v in self.tci_por_bid.values() if v is not None),
            "tci_bundles_nao_convergidos": sum(1 for v in self.tci_por_bid.values() if v is None),
            "overhead_copias": round(self.overhead, 3) if self.entregues_total else None,
            "saltos_medios": round(self.saltos_medios, 3) if self.entregues_total else None,
            "transmissoes": self.transmissoes,
            "transmissoes_adiaadas": self.adiaadas,
            "encontros": self.encontros,
            "uploads_redundantes": self.uploads_redundantes,
            "retransmissoes_suprimidas": self.retransmissoes_suprimidas,
            "cobertura_maxima_bundles": max(
                (len(v) for v in self.cobertura_por_bid.values()), default=0
            ),
            "airtime_total_s": round(self.airtime_s, 1),
            "energia_total_j": round(self.energia_j, 4),
            "frames_tx": self.frames_tx,
            "nos_em_zona_critica": self.nos_em_zona_critica,
            "nos_informados_a_tempo": self.nos_informados_a_tempo,
            "bundles_expirados_ttl": self.nos_expirados,
        }


# ===========================================================================
# 9. MOTOR
# ===========================================================================
class MotorDTN:
    """Executa o experimento completo com passo de tempo fixo."""

    def __init__(self, cfg: ConfiguracaoDTN) -> None:
        cfg.validar()
        self.cfg = cfg
        self.rng = random.Random(cfg.semente)
        self._rng = self.rng
        self.cenario: CenarioHidrologico = obter_cenario(cfg.cenario)
        self.protocolo: ProtocoloDTN = criar_protocolo(cfg)
        self.t_s = 0.0
        self.km_trecho_critico: float | None = {"C1": None, "C2": 155.0, "C3": 170.0}.get(cfg.cenario)
        self._seq_bundle = 0
        #: Bundle ids que ja chegaram a internet. Uma copia duplicada que
        #: chega depois conta como upload redundante (custo de overhead), nunca
        #: como uma segunda entrega: e o que mantem TED em [0, 100].
        self._entregues: set[str] = set()
        self._t_podagem = 0.0
        self.metricas = Metricas(cfg)
        self.frota: list[Embarcacao] = self._construir_frota()
        self.supernos: list[SuperNo] = construir_supernos(cfg.alcance_gateway_fixo_km)
        self.supernos_moveis: list[SuperNo] = construir_supernos_moveis(self.frota, cfg)
        self.gateways_info: dict = listar_gateways(cfg, self.frota, self.supernos, self.supernos_moveis)
        # os moveis entram na mesma lista de drenagem: nenhum grupo do
        # protocolo distingue um terminal de terra de um terminal a bordo
        self.supernos = self.supernos + self.supernos_moveis
        self.metricas.nos = len(self.frota)
        self.metricas.super_nos = len(self.supernos)
        self.metricas.gateways_moveis = len(self.supernos_moveis)
        cov, vao = cobertura_gateways(cfg.alcance_gateway_fixo_km, self.supernos)
        self.metricas.cobertura_gateway_percentual = round(cov * 100.0, 1)
        self.metricas.maior_vao_gateway_km = round(vao, 1)
        self.metricas.alcance_referencia_km = (
            round(min(no.lora.alcance_referencia_km for no in self.frota), 1) if self.frota else None
        )
        self.metricas.limiar_cobertura = max(
            1, int(math.ceil(cfg.limiar_cobertura_tci * len(self.frota)))
        )
        self._iniciar_carga_inicial()

    # -- construcao ----------------------------------------------------
    def _construir_frota(self) -> list[Embarcacao]:
        from flora_dtn import composicao_por_densidade
        composicao = self.cfg.composicao_frota
        if getattr(self.cfg, "densidade_frota", None):
            composicao = composicao_por_densidade(
                self.cfg.densidade_frota, composicao)
        frota: list[Embarcacao] = []
        id_no = 0
        for tipo, quantidade in composicao.items():
            for _ in range(quantidade):
                frota.append(Embarcacao(id_no, tipo, CANAL_PRINCIPAL, self.rng))
                id_no += 1
        return frota

    def adicionar_no(
        self,
        tipo: str = "PRINCIPAL",
        canal: Canal | None = None,
        km_atual: float | None = None,
        sentido: int | None = None,
        pos_mundo: np.ndarray | None = None,
        offset_faixa_km: float | None = None,
    ) -> Embarcacao:
        """
        Insere uma nova embarcacao (no movel) no cenario.

        Permite posicionamento por quilometro no canal ou por coordenadas do mundo
        (projetadas automaticamente sobre a calha navegavel).
        """
        if canal is None:
            canal = CANAL_PRINCIPAL
        if pos_mundo is not None:
            km_proj, off_proj = canal.projetar_ponto(pos_mundo)
            if km_atual is None:
                km_atual = km_proj
            if offset_faixa_km is None:
                offset_faixa_km = off_proj

        proximo_id = max((no.id for no in self.frota), default=-1) + 1
        no = Embarcacao(
            proximo_id,
            tipo,
            canal,
            self.rng,
            km_atual=km_atual,
            sentido=sentido,
            offset_faixa_km=offset_faixa_km,
        )
        no.t_s = self.t_s
        self.frota.append(no)

        if tipo in self.cfg.tipos_gateway_movel and self.cfg.bundles_por_hora_gateway_movel > 0:
            sn = SuperNo(
                f"movel_{no.id}",
                f"Backhaul {no.tipo} {no.id}",
                no.canal,
                no.km_atual,
                self.cfg.alcance_gateway_movel_km,
                anfitriao=no,
                bundles_por_h=self.cfg.bundles_por_hora_gateway_movel,
            )
            self.supernos_moveis.append(sn)
            self.supernos.append(sn)

        self.metricas.nos = len(self.frota)
        self.metricas.super_nos = len(self.supernos)
        self.metricas.gateways_moveis = len(self.supernos_moveis)
        self.metricas.limiar_cobertura = max(
            1, int(math.ceil(self.cfg.limiar_cobertura_tci * len(self.frota)))
        )

        self._atualizar_hidrologia()
        self.protocolo.ajustar_no(no)

        n_seg, n_rot = CARGA_INICIAL.get(no.tipo, (0, 0))
        for _ in range(n_seg):
            bd = self._novo_bundle(no, CAT_SEGURANCA, {"alerta": False})
            self.metricas.bundles_gerados += 1
            if no.inserir(bd, self.t_s, self.cfg.limite_buffer):
                no.bundles_criados += 1
                self.metricas.registrar_criacao(bd, no.id)
        for _ in range(n_rot):
            bd = self._novo_bundle(no, CAT_ROTINA)
            self.metricas.bundles_gerados += 1
            if no.inserir(bd, self.t_s, self.cfg.limite_buffer):
                no.bundles_criados += 1
                self.metricas.registrar_criacao(bd, no.id)

        return no

    def remover_no(self, id_no: int) -> Embarcacao | None:
        """
        Remove a embarcacao indicada da frota e desfaz vinculos de supernos e contatos.
        """
        no = self.obter_no(id_no)
        if no is None:
            return None

        self.frota.remove(no)

        # Remove gateway movel associado se houver
        self.supernos_moveis = [
            sn for sn in self.supernos_moveis
            if sn.anfitriao != no and getattr(sn, "id", None) != f"movel_{id_no}" and sn.chave != f"movel_{id_no}"
        ]
        self.supernos = [
            sn for sn in self.supernos
            if sn.anfitriao != no and getattr(sn, "id", None) != f"movel_{id_no}" and sn.chave != f"movel_{id_no}"
        ]

        self.metricas.nos = len(self.frota)
        self.metricas.super_nos = len(self.supernos)
        self.metricas.gateways_moveis = len(self.supernos_moveis)
        self.metricas.limiar_cobertura = max(
            1, int(math.ceil(self.cfg.limiar_cobertura_tci * max(1, len(self.frota))))
        )

        for rem in self.frota:
            rem.vizinhos_ativos.discard(id_no)
            rem.contatos_ativos.discard(id_no)

        return no

    def obter_no(self, id_no: int) -> Embarcacao | None:
        """Busca uma embarcacao pelo ID numerico."""
        for no in self.frota:
            if no.id == id_no:
                return no
        return None

    obter_embarcacao = obter_no

    def _iniciar_carga_inicial(self) -> None:
        # a carga inicial precisa de profundidade valida, entao a hidrologia e
        # resolvida uma vez antes de qualquer bundle ser criado
        self._atualizar_hidrologia()
        for no in self.frota:
            n_seg, n_rot = CARGA_INICIAL.get(no.tipo, (0, 0))
            for _ in range(n_seg):
                bd = self._novo_bundle(no, CAT_SEGURANCA, {"alerta": False})
                self.metricas.bundles_gerados += 1
                if no.inserir(bd, 0.0, self.cfg.limite_buffer):
                    no.bundles_criados += 1
                    self.metricas.registrar_criacao(bd, no.id)
            for _ in range(n_rot):
                bd = self._novo_bundle(no, CAT_ROTINA)
                self.metricas.bundles_gerados += 1
                if no.inserir(bd, 0.0, self.cfg.limite_buffer):
                    no.bundles_criados += 1
                    self.metricas.registrar_criacao(bd, no.id)
        for no in self.frota:
            self.protocolo.ajustar_no(no)

    def _novo_bundle(self, no: Embarcacao, categoria: str, extra: dict | None = None) -> Bundle:
        self._seq_bundle += 1
        carga = {
            "classe": "rota" if categoria == CAT_SEGURANCA else "sensor",
            "profundidade_m": round(no.profundidade_m, 2),
            "nivel_rio_m": round(no.nivel_rio_m, 2),
            "margem_sob_quilha_m": round(no.margem_sob_quilha_m, 2),
            "km": round(no.km_atual, 2),
            "id_origem": no.id,
        }
        if extra:
            carga.update(extra)
        return Bundle(
            bid=f"B{self._seq_bundle:07d}",
            categoria=categoria,
            origem=no.id,
            t_criacao_s=self.t_s,
            carga=carga,
            copias=2 if categoria == CAT_SEGURANCA else 1,
        )

    # -- passo de simulacao -------------------------------------------
    def passo(self) -> None:
        cfg = self.cfg
        dt = cfg.passo_s
        self.t_s += dt
        t_h = self.t_s / 3600.0

        # -- hidrologia da frota inteira em uma unica chamada vetorizada --
        nivel = self.cenario.nivel_rio_m(t_h)
        for no in self.frota:
            no.t_s = self.t_s
            no.abrir_janela_duty(self.t_s)
            no.mover(self._dt(), self.cenario)
            if (self.km_trecho_critico is not None
                    and no.t_chegada_km_critico is None
                    and no.km_atual >= self.km_trecho_critico):
                no.t_chegada_km_critico = self.t_s
        d_eixo = self._distancias_ao_eixo()
        self._atualizar_hidrologia(d_eixo)
        for no in self.frota:
            no.contatos_ativos.clear()
        # os gateways moveis andam com a embarcacao que os carrega: reposicionar
        # antes de qualquer teste de alcance, senao o passo inteiro usaria a
        # posicao do passo anterior
        for sn in self.supernos_moveis:
            sn.sincronizar()
            sn.acumular_cota(dt)

        ctx = ContextoRoteamento(self.supernos, self.t_s, d_eixo=d_eixo)
        self._gerar_carga()
        self._drenar_supernos(ctx)
        self._processar_encontros(ctx)
        self._avaliar_car()
        self._amostrar_series()
        if self.t_s - self._t_podagem >= 3600.0:
            self._t_podagem = self.t_s
            self._podar_cobertura()
        for no in self.frota:
            if self.rng.random() < 0.12:
                no.registrar_historico()

    def _atualizar_hidrologia(self, d_eixo: dict[int, np.ndarray] | None = None) -> None:
        """Resolve profundidade e margem sob quilha da frota inteira."""
        t_h = self.t_s / 3600.0
        posicoes = [no.pos for no in self.frota]
        calados = np.array([no.calado_m for no in self.frota], dtype=float)
        nivel = self.cenario.nivel_rio_m(t_h)
        profs = self.cenario.profundidades_m(posicoes, t_h, d_eixo)
        for no, prof, margem in zip(self.frota, profs, profs - calados):
            no.nivel_rio_m = nivel
            no.profundidade_m = float(prof)
            no.margem_sob_quilha_m = float(margem)
            no.classe_risco = classificar_margem(float(margem))
            no.cor_risco = cor_risco(float(margem))

    def _distancias_ao_eixo(self) -> dict[int, np.ndarray]:
        """
        Distancia ao eixo de todos os canais relevantes, indexada por `id()`.

        Uma unica chamada por passo alimenta a batimetria, a checagem de
        cobertura de gateway e a funcao de utilidade do FLoRA, que de outro modo
        resolveriam a mesma distancia quatro vezes.
        """
        posicoes = [no.pos for no in self.frota]
        canais = set(CANAIS.values()) | {no.canal for no in self.frota} | {sn.canal for sn in self.supernos}
        return {id(c): c.distancias_ao_eixo_km(posicoes) for c in canais}

    def _dt(self) -> float:
        return self.cfg.passo_s

    def _gerar_carga(self) -> None:
        cfg = self.cfg
        fracao_h = cfg.passo_s / 3600.0
        p_alerta = min(1.0, cfg.taxa_alerta_zona_critica_h * fracao_h)
        p_seg = min(1.0, cfg.taxa_seguranca_h * fracao_h)
        p_rot = min(1.0, cfg.taxa_rotina_h * fracao_h)
        for no in self.frota:
            categoria = None
            extra = None
            if no.em_zona_de_risco and self.rng.random() < p_alerta:
                categoria, extra = CAT_SEGURANCA, {"alerta": True, "msk": round(no.margem_sob_quilha_m, 2)}
            elif self.rng.random() < p_seg:
                categoria, extra = CAT_SEGURANCA, {"alerta": False}
            elif self.rng.random() < p_rot:
                categoria, extra = CAT_ROTINA, None
            if categoria is None:
                continue
            bd = self._novo_bundle(no, categoria, extra)
            self.metricas.bundles_gerados += 1
            if no.inserir(bd, self.t_s, cfg.limite_buffer):
                no.bundles_criados += 1
                self.metricas.registrar_criacao(bd, no.id)

    def _drenar_supernos(self, ctx: ContextoRoteamento) -> None:
        """
        Coleta por cobertura de gateway.

        Toda entrega ao superno custa um uplink LoRa completo (airtime, energia
        e duty cycle da embarcacao), igual a um repasse entre embarcacoes. E o
        que torna TED e overhead compativeis com a fisica do enlace.

        Num gateway movel ha ainda a cota do terminal de backhaul. O que nao
        couber nela permanece a bordo da embarcacao e pode ser servido no
        proximo passo, ou mais adiante por outro terminal: e a fila de subida,
        e nao perda de leitura.
        """
        com_cobertura = 0
        for no in self.frota:
            self.metricas.nos_expirados += no.expirar(self.t_s)
            # a distancia ao eixo nao depende do superno: calcula-se uma vez
            d_eixo = ctx.d_eixo_km(no)
            alcancado = False
            for sn in self.supernos:
                if not sn.em_alcance(no, d_eixo):
                    no.gateways_em_contato.discard(sn.chave)
                    continue
                alcancado = True
                candidatos = sn.drenar(no, self.t_s)
                if sn.movel:
                    if not candidatos:
                        sn.aguardando_cota = 0
                        continue
                    sn.aguardando_cota = max(0, len(candidatos) - int(sn._cota))
                    if sn._cota < 1.0:
                        # terminal sem cota livre neste passo: nada sobe
                        continue
                    # primeiro os bundles ja entregues, para nao gastar taxa com
                    # upload que so contaria como redundante
                    candidatos.sort(key=lambda b: b.bid in self._entregues)
                    quota = min(len(candidatos), int(sn._cota))
                    candidatos = candidatos[:quota]
                    # a cota so e descontada quando a transmissao efetivamente
                    # ocorrer, em _uplicar_ao_gateway
                for bd in candidatos:
                    self._uplicar_ao_gateway(no, bd, sn)
            com_cobertura += 1 if alcancado else 0
        if self.frota:
            pct = 100.0 * com_cobertura / len(self.frota)
            self.metricas.cobertura_instantanea_percentual = pct
            self.metricas._soma_cobertura += pct
            self.metricas._amostras_cobertura += 1
            self.metricas.cobertura_instantanea_media = (
                self.metricas._soma_cobertura / self.metricas._amostras_cobertura
            )

    def _uplicar_ao_gateway(self, no: Embarcacao, bd: Bundle, sn: SuperNo) -> None:
        # cada embarcacao envia um bundle a cada superno uma unica vez
        if bd.bid in no.bids_enviados:
            return
        airtime_s = no.lora.airtime_por_segundo(TAMANHO_PACOTE_LORA_B)
        if not no.pode_transmitir(airtime_s):
            no.transmissoes_adiaadas += 1
            self.metricas.adiaadas += 1
            # transmissao bloqueada: bundle permanece pendente para reenvio
            return
        # transmissao efetiva: so agora marca como enviado
        no.bids_enviados.add(bd.bid)
        no.transmitiu_ao_gateway += 1
        sn.pacotes_drenados += 1
        sn.drenados.setdefault(bd.bid, self.t_s)
        if sn.movel:
            sn._cota = max(0.0, sn._cota - 1.0)

        no.registrar_tx(self.t_s, airtime_s)
        self.metricas.airtime_s += airtime_s
        self.metricas.energia_j += no.lora.energia_tx_joule(airtime_s * 1000.0)
        self.metricas.frames_tx += 1
        self.metricas.registrar_transmissao()

        if bd.bid in self._entregues:
            self.metricas.uploads_redundantes += 1
            return
        # IDTU: informacao disponivel em tempo util
        t_rec = self.t_s
        km_crit = self.km_trecho_critico
        if km_crit is None:
            idtu = 1.0
        else:
            t_arr = no.t_chegada_km_critico
            if t_arr is None:
                idtu = 0.0
            else:
                idtu = 1.0 if (t_rec + 0.5 * 3600.0 < t_arr
                               and (t_rec - bd.t_criacao_s) <= 6.0 * 3600.0) else 0.0
        self.metricas.idtu_soma += idtu
        self.metricas.idtu_n += 1
        self._entregues.add(bd.bid)
        self.metricas.registrar_entrega(bd, self.t_s)

    def _processar_encontros(self, ctx: ContextoRoteamento) -> None:
        """
        Deteccao vetorizada de vizinhos e aplicacao do protocolo.

        Sao tres etapas deliberadamente separadas: descobrir quem ve quem, decidir
        o que cada no envia, e so entao transmitir. Se a transmissao fosse
        resolvida no meio da deteccao, o estado de uma embarcacao mudaria
        enquanto os pares ainda estavam sendo percorridos, e o resultado
        passaria a depender da ordem de iteracao.
        """
        cfg = self.cfg
        n = len(self.frota)
        if n < 2:
            return
        pos_km = np.array([no.pos for no in self.frota], dtype=float) * KM_POR_PX
        alcance = np.array([no.lora.alcance_referencia_km for no in self.frota], dtype=float) * cfg.fator_alcance

        i_idx, j_idx = np.triu_indices(n, 1)
        dif = pos_km[i_idx] - pos_km[j_idx]
        dist = np.sqrt(np.einsum("ij,ij->i", dif, dif))
        alcance_par = np.minimum(alcance[i_idx], alcance[j_idx])
        candidatos = np.nonzero(dist <= alcance_par)[0].tolist()
        if not candidatos:
            return

        # -- etapa 1: grafo de encounter --
        sombra = np.array(
            [self._fator_sombreamento(int(i_idx[k]), int(j_idx[k])) for k in candidatos],
            dtype=float,
        )
        alcance_efetivo = alcance_par[candidatos] * sombra
        vivos = np.nonzero(dist[candidatos] <= alcance_efetivo)[0]
        if len(vivos) == 0:
            return
        pares: list[tuple[int, int]] = []
        vizinhos: dict[int, list[int]] = {}
        for pos in vivos.tolist():
            k = candidatos[pos]
            i, j = int(i_idx[k]), int(j_idx[k])
            a, b = self.frota[i], self.frota[j]
            a.vizinhos_ativos.add(b.id)
            b.vizinhos_ativos.add(a.id)
            vizinhos.setdefault(i, []).append(j)
            vizinhos.setdefault(j, []).append(i)
            pares.append((i, j))
        self.metricas.encontros += len(pares)

        for i, no in enumerate(self.frota):
            for j in vizinhos.get(i, ()):
                id_alvo = self.frota[j].id
                if id_alvo not in no.contatos_ativos:
                    no.contatos_total += 1
                    no.contatos_por_no[id_alvo] = no.contatos_por_no.get(id_alvo, 0) + 1
                no.contatos_ativos.add(id_alvo)

        if not self.protocolo.navega_entre_embarcacoes:
            return

        # -- etapa 2: decisao de roteamento, por no --
        decisoes = self.protocolo.decidir(self.frota, vizinhos, self.t_s, ctx)

        # -- etapa 3: transmissao --
        for (i, j), bundles in decisoes.items():
            origem, destino = self.frota[i], self.frota[j]
            for bd in bundles:
                self._entregar(origem, destino, bd)

    def _fator_sombreamento(self, i: int, j: int) -> float:
        """Perda de alcance por par, reproduzivel a partir dos identificadores."""
        h = ((i + 1) * 73856093) ^ ((j + 1) * 19349663)
        fracao = (h & 0xFFFF) / 65535.0
        return 1.0 - self.cfg.perda_sombreamento * fracao

    def _entregar(self, origem: Embarcacao, destino: Embarcacao, bd: Bundle) -> None:
        """
        Repasse de um bundle entre duas embarcacoes em encounter.

        A ordem das operacoes e essencial: primeiro descobre-se se ha
        informacao nova a transmitir, e so entao se gasta airtime. Transferir
        uma copia que o destino ja possui custaria um quadro LoRa inteiro sem
        agregar nada, e em protocolos de inundacao isso consumiria todo o
        orcamento de duty cycle em retransmissoes.
        """
        if destino.conhece(bd.bid):
            self.metricas.retransmissoes_suprimidas += 1
            return
        airtime_s = origem.lora.airtime_por_segundo(TAMANHO_PACOTE_LORA_B)
        if not origem.pode_transmitir(airtime_s):
            origem.transmissoes_adiaadas += 1
            self.metricas.adiaadas += 1
            return
        origem.registrar_tx(self.t_s, airtime_s)
        destino.registrar_rx(airtime_s)
        self.metricas.airtime_s += airtime_s
        self.metricas.energia_j += origem.lora.energia_tx_joule(airtime_s * 1000.0)
        self.metricas.frames_tx += 1
        self.metricas.registrar_transmissao()

        novo = bd.copia(bd.saltos + 1)
        decrementou_copia = False
        if self.protocolo.nome == "spray" and bd.copias > 1:
            bd.copias -= 1
            decrementou_copia = True
        if destino.inserir(novo, self.t_s, self.cfg.limite_buffer):
            destino.marcar_recebido(novo.bid)
            destino.recebidos += 1
            destino.saltos_totais += 1
            origem.transmitidos += 1
            self.metricas.registrar_cobertura(bd.bid, destino.id, self.t_s)
        else:
            if decrementou_copia:
                bd.copias += 1
            # store cheio e sem o que expulsar: o bundle foi conhecido mas
            # descartado. Ja conta como "conhecido" para nao repetir a tentativa.
            destino.marcar_recebido(novo.bid)

    def _avaliar_car(self) -> None:
        for no in self.frota:
            if not no.entrou_em_zona_critica and no.em_zona_de_risco:
                no.entrou_em_zona_critica = True
                self.metricas.nos_em_zona_critica += 1
                if no.tem_rota_valida(self.t_s):
                    no.informacao_a_tempo = True
                    self.metricas.nos_informados_a_tempo += 1

    def _podar_cobertura(self) -> None:
        """
        Libera a memoria dos bundles ja convergentes ou ainda sem qualquer
        copia alem do no de origem. Roda no maximo uma vez por hora simulada.
        """
        m = self.metricas
        for bid in list(m.cobertura_por_bid):
            if len(m.cobertura_por_bid) <= 5000:
                break
            if m.tci_por_bid.get(bid) is not None or len(m.cobertura_por_bid[bid]) <= 1:
                del m.cobertura_por_bid[bid]
                # preserva o TCI ja calculado

    def _amostrar_series(self) -> None:
        t_h = self.t_s / 3600.0
        if abs(t_h - round(t_h)) > 1e-9:
            return
        m = self.metricas
        m.serie_ted.append((t_h, m.ted))
        if m.latencias_s:
            m.serie_lpa.append((t_h, sum(m.latencias_s) / len(m.latencias_s) / 60.0))
        if m.idtu_n:
            m.serie_idtu.append((t_h, (m.idtu_soma / m.idtu_n) * 100.0))

    # -- execucao ------------------------------------------------------
    def executar(self, horizonte_h: float | None = None, progresso=None) -> "MotorDTN":
        horizonte = (self.cfg.horizonte_h if horizonte_h is None else horizonte_h) * 3600.0
        alvo = self.t_s + horizonte
        passos = max(1, int(math.ceil(horizonte / self.cfg.passo_s)))
        for k in range(passos):
            if self.t_s >= alvo:
                break
            self.passo()
            if progresso is not None:
                progresso(k / passos)
        return self

    def registrar_historico(self) -> None:  # pragma: no cover - compatibilidade
        for no in self.frota:
            no.registrar_historico()

    # -- exportacao ----------------------------------------------------
    def resumo(self) -> dict:
        m = self.metricas
        m.t_s = self.t_s
        m.bundles_descartados = sum(no.bundles_descartados for no in self.frota)
        m.bundles_expulsos = sum(no.bundles_expulsos for no in self.frota)
        dados = m.dict()
        dados.update({
            "cenario_nome": self.cenario.nome,
            "protocolo_rotulo": ROTULOS_PROTOCOLO.get(self.cfg.protocolo, self.cfg.protocolo),
            "nivel_rio_final_m": round(self.cenario.nivel_rio_m(self.t_s / 3600.0), 2),
            "obstaculos_ativos": len(self.cenario.obstaculos_ativos(self.t_s / 3600.0)),
            "energia_media_mJ": round(m.energia_j / max(1, len(self.frota)) * 1000.0, 2),
            "energia_media_por_no_mJ": round(
                sum(no.energia_j for no in self.frota) / max(1, len(self.frota)) * 1000.0, 2
            ),
            "idtu_media": round(m.idtu_soma / m.idtu_n, 4) if m.idtu_n else None,
            "idtu_n": m.idtu_n,
        })
        return dados

    def exportar_metricas(self, caminho: str) -> None:
        dados = self.resumo()
        if caminho.lower().endswith(".json"):
            with open(caminho, "w", encoding="utf-8") as fh:
                json.dump(dados, fh, indent=2, ensure_ascii=False)
            return
        with open(caminho, "w", newline="", encoding="utf-8-sig") as fh:
            writer = _csv.DictWriter(fh, fieldnames=list(dados))
            writer.writeheader()
            writer.writerow(dados)

    def exportar_frota(self, caminho: str) -> None:
        """Estado por no, com tudo que o simulador legado nao persistia."""
        with open(caminho, "w", newline="", encoding="utf-8-sig") as fh:
            writer = _csv.DictWriter(fh, fieldnames=list(_CAMPOS_FROTA))
            writer.writeheader()
            for no in sorted(self.frota, key=lambda x: x.id):
                writer.writerow(self._linha_frota(no))

    def _linha_frota(self, no: "Embarcacao") -> dict:
        """Uma linha do CSV de frota; tambem usada no JSON completo."""
        return {
            "ID": no.id,
            "Tipo": no.tipo,
            "Nome": no.nome_tipo,
            "Canal": no.canal.nome,
            "Km_Rota": round(no.km_atual, 3),
            "Progresso_pct": round(100.0 * no.progresso, 2),
            "Sentido": "subida" if no.sentido > 0 else "descida",
            "Latitude": round(no.lat, 6),
            "Longitude": round(no.lon, 6),
            "Profundidade_m": round(no.profundidade_m, 2),
            "Calado_m": no.calado_m,
            "Margem_Sob_Quilha_m": round(no.margem_sob_quilha_m, 2),
            "Classe_Risco": no.classe_risco,
            "Velocidade_km_h": round(no.velocidade_km_h, 2),
            "Viagens_Completas": no.viagens_completas,
            "Distancia_Percorrida_km": round(no.distancia_percorrida_km, 2),
            "Buffer_Bundles": len(no.buffer),
            "Pacotes_Buffer": no.pacotes(),
            "Bundles_Criados": no.bundles_criados,
            "Transmitidos": no.transmitidos,
            "Recebidos": no.recebidos,
            "Saltos": no.saltos_totais,
            "Contatos": no.contatos_total,
            "Gateways_Visitados": "|".join(no.gateways_visitados),
            "Frames_TX": no.frames_tx,
            "Frames_RX": no.frames_rx,
            "Transmissoes_Adiadas": no.transmissoes_adiaadas,
            "Airtime_s": round(no.airtime_s, 2),
            "Energia_mJ": round(no.energia_j * 1000.0, 2),
        }

    def _superno_dict(self, no: "SuperNo") -> dict:
        """Descricao de um ponto de drenagem para o JSON completo."""
        lat, lon = mundo_para_geo(float(no.pos[0]), float(no.pos[1]))
        return {
            "chave": no.chave,
            "nome": no.nome,
            "movel": no.movel,
            "km_canal": round(no.km_canal, 3),
            "alcance_km": no.alcance_km,
            "bundles_por_h": no.bundles_por_h,
            "pacotes_drenados": no.pacotes_drenados,
            "embarcoes_atendidas": sorted(no.embarcoes_atendidas),
            "latitude": round(float(lat), 6),
            "longitude": round(float(lon), 6),
        }

    def exportar_simulacao(self, caminho: str) -> str:
        """
        Grava **um unico JSON** com tudo que descreve a execucao.

        E o formato pensado para analise fora do simulador: traz o resumo das
        metricas, a configuracao completa, o estado final da frota, os
        supernos, as series horarias e as amostras brutas de latencia. O
        arquivo e autossuficiente e pode ser lido pelo modo ``analisar`` sem
        os CSV auxiliares.

        Returns
        -------
        str
            O caminho gravado.
        """
        from datetime import datetime

        from flora_versao import NOME as SOFTWARE, VERSAO, resolver_commit

        m = self.metricas
        dados = {
            "formato": "flora-dtn-simulacao",
            "formato_versao": 1,
            "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
            "software": {
                "nome": SOFTWARE,
                "versao": VERSAO,
                "commit": resolver_commit(),
            },
            "resumo": self.resumo(),
            "resultados_simulados": {
                "proveniencia": "simulado",
                "ted_percentual": self.resumo().get("ted_percentual"),
                "lpa_minutos": self.resumo().get("lpa_minutos"),
                "car_percentual": self.resumo().get("car_percentual"),
                "tci_horas": self.resumo().get("tci_horas"),
                "overhead_copias": self.resumo().get("overhead_copias"),
                "transmissoes": self.resumo().get("transmissoes"),
                "energia_total_j": self.resumo().get("energia_total_j"),
                "idtu_media": self.resumo().get("idtu_media"),
                "idtu_n": self.resumo().get("idtu_n"),
            },
            "cenarios_ilustrativos": {
                "proveniencia": "estimado",
                "nota": "Valores ilustrativos (nao simulados): tempo de viagem, custo e transbordo por regime hidrologico.",
            },
            "configuracao": asdict(self.cfg),
            "cenario": {
                "codigo": self.cenario.codigo,
                "nome": self.cenario.nome,
                "fonte": self.cenario.fonte,
                "nivel_rio_final_m": round(
                    self.cenario.nivel_rio_m(self.t_s / 3600.0), 3),
                "obstaculos_ativos": len(
                    self.cenario.obstaculos_ativos(self.t_s / 3600.0)),
            },
            "frota": [self._linha_frota(no)
                      for no in sorted(self.frota, key=lambda x: x.id)],
            "supernos": [self._superno_dict(no) for no in self.supernos],
            "gateways": self.gateways_info,
            "series": {
                "ted": [[round(h, 3), round(v, 3)] for h, v in m.serie_ted],
                "lpa_minutos": [[round(h, 3), round(v, 3)]
                                for h, v in m.serie_lpa],
                "idtu": [[round(h, 3), round(v, 3)] for h, v in m.serie_idtu],
            },
            "amostras": {
                "latencias_s": [round(v, 2) for v in m.latencias_s],
                "latencias_seguranca_s": [round(v, 2)
                                          for v in m.latencias_seguranca_s],
                "bundles_por_categoria": dict(m.bundles_por_categoria),
                "tci_por_bid": {
                    bid: (None if t is None else round(t, 3))
                    for bid, t in m.tci_por_bid.items()
                },
                "cobertura_por_bid": {
                    bid: sorted(nos) for bid, nos in m.cobertura_por_bid.items()
                },
            },
        }
        with open(caminho, "w", encoding="utf-8") as fh:
            json.dump(dados, fh, indent=2, ensure_ascii=False, allow_nan=False)
        return caminho

    def exportar_config(self, caminho: str) -> None:
        with open(caminho, "w", encoding="utf-8") as fh:
            json.dump(asdict(self.cfg), fh, indent=2, ensure_ascii=False)

    def exportar_tudo(self, base: str) -> list[str]:
        """Grava <base>_metricas.csv, <base>_frota.csv e <base>_config.json."""
        criados = []
        for sufixo, metodo in (
            ("_metricas.csv", self.exportar_metricas),
            ("_frota.csv", self.exportar_frota),
            ("_config.json", self.exportar_config),
        ):
            caminho = f"{base}{sufixo}"
            metodo(caminho)
            criados.append(caminho)
        return criados

    def adicionar_embarcacao(
        self, tipo: str, km_inicial: float, sentido: int = 1
    ) -> "Embarcacao":
        """
        Adiciona uma embarcacao nova a frota em tempo de execucao.

        O novo no recebe o proximo ID livre, e inserido na lista da frota e
        e indexado pelos supernos moveis existentes. O ContextoRoteamento
        do proximo passo e recriado automaticamente porque e calculado a cada
        chamada a `passo()`.

        Returns
        -------
        Embarcacao
            O objeto recem criado, ja inserido na frota.
        """
        if tipo not in PERFIS_EMBARCACAO:
            raise ValueError(
                f"tipo desconhecido: {tipo!r} (use um de {sorted(PERFIS_EMBARCACAO)})"
            )
        novo_id = max((no.id for no in self.frota), default=0) + 1
        perfil = PERFIS_EMBARCACAO[tipo]
        canal = CANAL_PRINCIPAL
        km_inicial = max(0.0, min(float(km_inicial), canal.comprimento_km))
        offset = self._rng.uniform(-OFFSETO_FAIXA_KM, OFFSETO_FAIXA_KM)
        velocidade = self._rng.uniform(perfil.velocidade_min_kmh, perfil.velocidade_max_kmh)
        no = Embarcacao(
            id=novo_id,
            tipo=tipo,
            canal=canal,
            km_atual=km_inicial,
            sentido=int(sentido),
            offset_faixa_km=offset,
            velocidade_km_h=velocidade,
            calado_m=perfil.calado_m,
            lora=perfil.lora,
            cor_base=CORES_EMBARCACAO.get(tipo, (70, 130, 180)),
            indice_frota=len(self.frota),
        )
        no.pos = canal.posicao_em(km_inicial, offset)[0]
        self.frota.append(no)
        # cria gateway movel se o tipo for configurado para isso
        if tipo in self.cfg.tipos_gateway_movel:
            sn = SuperNo(
                chave=f"gw_movel_{novo_id}",
                nome=f"GW-{no.tipo[:3]}{novo_id}",
                canal=canal,
                km_canal=km_inicial,
                alcance_km=self.cfg.alcance_gateway_movel_km,
                pos=no.pos,
                movel=True,
                anfitriao=no,
                bundles_por_h=self.cfg.bundles_por_hora_gateway_movel,
            )
            self.supernos.append(sn)
            if hasattr(self, "supernos_moveis") and sn not in self.supernos_moveis:
                self.supernos_moveis.append(sn)
        self.metricas.nos = len(self.frota)
        self.metricas.super_nos = len(self.supernos)
        self.metricas.gateways_moveis = len(getattr(self, "supernos_moveis", []))
        self._atualizar_hidrologia()
        return no

    def remover_embarcacao(self, id_no: int) -> bool:
        """
        Remove uma embarcacao da frota pelo seu ID.

        Bundles a bordo sao descartados. Supernos moveis associados a esta
        embarcacao sao removidos. O indice_frota de todos os nos remanescentes
        e recalculado para manter a consistencia com o ContextoRoteamento.

        Returns
        -------
        bool
            True se o no foi encontrado e removido, False se o ID nao existe.
        """
        alvo = next((no for no in self.frota if no.id == id_no), None)
        if alvo is None:
            return False
        self.frota.remove(alvo)
        # remove supernos moveis cujo anfitriao era este no
        self.supernos = [
            sn for sn in self.supernos
            if not (sn.movel and sn.anfitriao is alvo)
        ]
        if hasattr(self, "supernos_moveis"):
            self.supernos_moveis = [
                sn for sn in self.supernos_moveis
                if not (sn.movel and sn.anfitriao is alvo)
            ]
        # recalcula os indices para manter consistencia
        for i, no in enumerate(self.frota):
            no.indice_frota = i
        self.metricas.nos = len(self.frota)
        self.metricas.super_nos = len(self.supernos)
        self.metricas.gateways_moveis = len(getattr(self, "supernos_moveis", []))
        for rem in self.frota:
            rem.vizinhos_ativos.discard(id_no)
            rem.contatos_ativos.discard(id_no)
        return True
