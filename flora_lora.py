"""
flora_lora.py
=============

Camada fisica LoRa (SX1262 / SX1301) para o simulador FLoRA.

O simulador legado era acustico: a comunicacao entre embarcacoes era um
`if distancia <= raio` sem custo, sem tempo de ocupacao do canal e sem
energia. Aqui o custo de cada entrega e cobrado em airtime e joules, o que
permite comparar protocolos por overhead real e nao apenas por contagem de
mensagens.

A equacao de airtime segue a formulacao de Semtech para CSS (chirp spread
spectrum) com taxa de codificacao:

    T_sym      = 32 * 2^SF / BW
    T_preamble = (n_preamble + 4.25) * T_sym
    n_sym_carga = 8 + max(ceil((8*P - 4*SF + 28 + 16*CRC - 20*IH)
                                / (4*(SF - 2*DE))) * (CRC + 4), 0)
    T_carga    = n_sym_carga * T_sym
    T_pacote   = T_preamble + T_carga

com P o tamanho da carga util em bytes, CRC=1 quando o CRC esta habilitado,
IH=1 para a optimizacao de taxa lenta (obrigatoria abaixo de SF11 a 125 kHz)
e DE=1 no modo de taxa baixa de dados.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Codigos de taxa de dados usuais para 125 kHz, indexados por spreading factor.
SPREADING_FACTORS: dict[int, int] = {7: 125, 8: 125, 9: 125, 10: 125, 11: 125, 12: 125}


@dataclass(frozen=True)
class ParametrosLora:
    """Parametros de radio de um no LoRa da frota."""

    sf: int = 7
    banda_hz: int = 125_000
    preamble: int = 8
    cr_crc: bool = True
    codificacao: str = "4/5"
    cabecalho_explicito: bool = True
    otimizacao_baixa_taxa: bool = True
    potencia_tx_w: float = 0.100          # 100 mW, faixa usual do SX1262
    consumo_rx_w: float = 0.019           # SX1262 em recepcao
    consumo_sleep_w: float = 0.0000022    # SX1262 em repouso profundo
    limite_duty_cycle: float = 0.01       # 1% em banda ISM (ETSI EN 300 220)
    taxa_bits_s: int = 0

    def __post_init__(self) -> None:
        if self.sf not in SPREADING_FACTORS:
            raise ValueError(f"spreading factor fora da tabela: {self.sf}")
        if not self.taxa_bits_s:
            # taxa nominal do CSS (Semtech): Rb = SF * BW / 2^SF * 4/(4+CR),
            # com CR o numero extra de bits de paridade (1 para 4/5).
            cr_extra = int(self.codificacao.split("/")[1]) - 4
            object.__setattr__(
                self, "taxa_bits_s",
                int(self.sf * self.banda_hz / (2 ** self.sf) * 4.0 / (4 + cr_extra)),
            )

    @property
    def alcance_referencia_km(self) -> float:
        """Alcance nominal de enlace em km para este perfil."""
        return ALCANCE_NOMINAL_KM.get(self.sf, 10.0)

    def airtime_ms(self, payload_bytes: int) -> float:
        """
        Tempo de ocupacao do canal, em milissegundos.

        `H = 0` quando o cabecalho e explicito (caso do LoRaWAN) e `DE = 1`
        apenas para SF11/SF12 em 125 kHz, que sao as unicas combinacoes em
        que a otimizacao de taxa baixa de dados e permitida.
        """
        sf = self.sf
        t_sym_ms = (2 ** sf) / self.banda_hz * 1000.0
        t_preamble_ms = (self.preamble + 4.25) * t_sym_ms
        cr = 1 if self.cr_crc else 0
        h = 0 if self.cabecalho_explicito else 1
        de = 1 if (self.otimizacao_baixa_taxa and self.banda_hz == 125_000 and sf >= 11) else 0
        cr_denominador = int(self.codificacao.split("/")[1]) - 4
        numerador = 8 * payload_bytes - 4 * sf + 28 + 16 * cr - 20 * h
        denominador = 4 * (sf - 2 * de)
        passos = math.ceil(numerador / denominador) * (cr_denominador + 4)
        n_simbolos_carga = 8 + max(passos, 0)
        return t_preamble_ms + n_simbolos_carga * t_sym_ms

    def airtime_por_segundo(self, payload_bytes: int) -> float:
        """Airtime em segundos, para contabilizacao de duty cycle."""
        return self.airtime_ms(payload_bytes) / 1000.0

    def energia_tx_joule(self, airtime_ms: float) -> float:
        return self.potencia_tx_w * (airtime_ms / 1000.0)

    def energia_rx_joule(self, airtime_ms: float) -> float:
        return self.consumo_rx_w * (airtime_ms / 1000.0)

    def frames_por_hora(self, payload_bytes: int) -> float:
        """Numero maximo de Quadros por hora respeitando o duty cycle."""
        janela_s = 3600.0
        orcamento_s = janela_s * self.limite_duty_cycle
        airtime_s = self.airtime_por_segundo(payload_bytes)
        return orcamento_s / airtime_s if airtime_s > 0 else 0.0


#: Tamanho da carga util de um bundle hidrográfico serializado.
#: 48 B cobrem: marca de tempo (8) + coordenada (8) + profundidade (4) +
#: nivel do rio (4) + identificacao do sensor (4) + classe/prioridade (2)
#: + cabecalho de bundle compactado do BP (18 B).
TAMANHO_CARGA_UTIL_B = 48
TAMANHO_CABECALHO_BP_B = 18
TAMANHO_PACOTE_LORA_B = TAMANHO_CABECALHO_BP_B + TAMANHO_CARGA_UTIL_B


#: Tabela de alcances nominais por spreading factor, em linha de visada
#: sobre agua aberta, usada para calibrar o alcance do protocolo.
ALCANCE_NOMINAL_KM: dict[int, float] = {7: 15.0, 8: 12.0, 9: 9.0, 10: 6.0, 11: 3.5, 12: 2.0}

#: Perfil por classe de embarcacao. Bargas e navios de recreio precisam de
#: alcance longo (SF7) porque a calha e aberta; as lanchas e os ribeirinhos
#: operam junto a margem, onde a vegetacao atenua e o alcance e menor.
PERFIS_POR_TIPO: dict[str, ParametrosLora] = {
    "PRINCIPAL": ParametrosLora(sf=7, potencia_tx_w=0.100),
    "LANCHA": ParametrosLora(sf=9, potencia_tx_w=0.062),
    "RIBEIRINHO": ParametrosLora(sf=10, potencia_tx_w=0.025),
}


def resumo_phy() -> str:
    linhas = [
        f"pacote LoRa = {TAMANHO_CABECALHO_BP_B} B (BP compactado) + "
        f"{TAMANHO_CARGA_UTIL_B} B (carga hidro) = {TAMANHO_PACOTE_LORA_B} B",
        "",
        "perfil      SF  taxa(bps)  alcance(km)  airtime     energia/tx   quadros/h (1%)",
    ]
    for tipo, p in PERFIS_POR_TIPO.items():
        at = p.airtime_ms(TAMANHO_PACOTE_LORA_B)
        linhas.append(
            f"{tipo:11s} {p.sf:2d}  {p.taxa_bits_s:9d}  {p.alcance_referencia_km:11.1f}  "
            f"{at:7.1f} ms  {p.energia_tx_joule(at) * 1000:7.2f} mJ  "
            f"{p.frames_por_hora(TAMANHO_PACOTE_LORA_B):12.1f}"
        )
    return "\n".join(linhas)
