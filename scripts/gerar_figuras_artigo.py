#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
gerar_figuras_artigo.py
=======================

Gera as 6 figuras do artigo FLoRA em 300 dpi:

Figura 4 — Arquitetura em três camadas (diagrama).
Figura 5 — Fluxo de bundles na rede (diagrama de sequência).
Figura 6 — Ciclo operacional da arquitetura-alvo (fluxo em 4 etapas).
Figura 7 — Níveis de rio nos cenários C1, C2 e C3 ao longo de 168 h.
Figura 8 — Tempo de viagem Manaus–Itacoatiara por regime hidrológico.
Figura 9 — Custo logístico e impacto do transbordo.

As figuras 4, 5 e 6 são diagramas conceituais desenhados com matplotlib puro.
As figuras 7, 8 e 9 são gráficos de dados gerados a partir dos modelos de
`flora_cenario.py` e das estimativas da Seção 6.5 do artigo.

Uso:
    python scripts/gerar_figuras_artigo.py
    python scripts/gerar_figuras_artigo.py --saida artigo/figuras
"""

from __future__ import annotations

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# Tenta importar o cenário (opcional, para as figuras 7, 8, 9)
try:
    from flora_cenario import obter_cenario
    TEM_CENARIO = True
except ImportError:
    TEM_CENARIO = False

DPI = 300

# Paleta alinhada com o simulador
COR_APLICACAO = "#1f3a5f"
COR_DISSEMINACAO = "#2e6b9e"
COR_SENSORIAMENTO = "#4a9bc7"
COR_TEXTO = "#1a1a1a"
COR_DESTAQUE = "#c0392b"
COR_VERDE = "#27ae60"
COR_C1 = "#2e7d32"
COR_C2 = "#e67e22"
COR_C3 = "#c0392b"
COR_INFORMADO = "#1f4e79"
COR_REATIVO = "#95a5a6"
COR_FUNDO = "#ffffff"
COR_GRADE = "#e0e0e0"


# ============================================================================
# FIGURA 4 — Arquitetura em três camadas
# ============================================================================
def figura4_arquitetura(caminho: str) -> str:
    """Diagrama em três camadas horizontais com os componentes de cada camada."""
    fig, ax = plt.subplots(figsize=(12, 8), dpi=DPI)
    ax.set_xlim(0, 12); ax.set_ylim(0, 8); ax.axis("off")

    faixas = [
        (5.6, 7.4, COR_APLICACAO,
         "CAMADA DE APLICAÇÃO E INTELIGÊNCIA (CAI)",
         "Nuvem FLoRA  ·  Decisão logística  ·  Mapas de risco"),
        (3.0, 5.4, COR_DISSEMINACAO,
         "CAMADA DE DISSEMINAÇÃO OPORTUNÍSTICA (CDO)",
         "Bundle Protocol v7  ·  Store-carry-forward  ·  Encontros oportunísticos"),
        (0.6, 2.8, COR_SENSORIAMENTO,
         "CAMADA DE SENSORIAMENTO DISTRIBUÍDO (CSD)",
         "NS-Embarcado  ·  NS-Boia  ·  NS-Margem"),
    ]
    for y0, y1, cor, titulo, subtitulo in faixas:
        ax.add_patch(FancyBboxPatch((0.3, y0), 11.4, y1 - y0,
                     boxstyle="round,pad=0.05,rounding_size=0.15",
                     facecolor=cor, edgecolor="white", linewidth=2, alpha=0.92))
        ax.text(6.0, y1 - 0.25, titulo, ha="center", va="top",
                fontsize=13, fontweight="bold", color="white")
        ax.text(6.0, y1 - 0.55, subtitulo, ha="center", va="top",
                fontsize=9.5, color="white", alpha=0.92, style="italic")

    # Aplicação
    ax.add_patch(mpatches.Ellipse((6.0, 6.5), 2.4, 1.0,
                 facecolor="white", edgecolor=COR_APLICACAO, linewidth=2, alpha=0.95))
    ax.text(6.0, 6.5, "Nuvem FLoRA\n(agregação, IA/ML)",
            ha="center", va="center", fontsize=9, color=COR_APLICACAO, fontweight="bold")
    ax.add_patch(FancyBboxPatch((1.0, 6.0), 2.4, 1.0,
                 boxstyle="round,pad=0.04,rounding_size=0.1",
                 facecolor="white", edgecolor=COR_APLICACAO, linewidth=1.5))
    ax.text(2.2, 6.5, "Decisão logística\n(rota, ETA, alívio)",
            ha="center", va="center", fontsize=8.5, color=COR_APLICACAO)
    ax.add_patch(FancyBboxPatch((8.6, 6.0), 2.4, 1.0,
                 boxstyle="round,pad=0.04,rounding_size=0.1",
                 facecolor="white", edgecolor=COR_APLICACAO, linewidth=1.5))
    ax.text(9.8, 6.5, "Mapas de risco\n(atualização)",
            ha="center", va="center", fontsize=8.5, color=COR_APLICACAO)
    for x0, x1 in [(2.6, 4.6), (7.4, 8.4)]:
        ax.annotate("", xy=(x1, 6.5), xytext=(x0, 6.5),
                    arrowprops=dict(arrowstyle="<->", color="white", lw=1.8))

    # Disseminação
    for x, label in [(2.0, "Barco A"), (6.0, "Barco B"), (10.0, "Barco C")]:
        ax.add_patch(mpatches.Circle((x, 4.2), 0.32,
                     facecolor="white", edgecolor=COR_DISSEMINACAO, linewidth=2))
        ax.text(x, 4.2, label, ha="center", va="center",
                fontsize=8, color=COR_DISSEMINACAO, fontweight="bold")
    for x0, x1 in [(2.35, 5.65), (6.35, 9.65)]:
        ax.annotate("", xy=(x1, 4.2), xytext=(x0, 4.2),
                    arrowprops=dict(arrowstyle="->", color="white", lw=2,
                                    linestyle="--", connectionstyle="arc3,rad=0.15"))
    ax.text(4.0, 4.75, "encontro oportunístico", ha="center", fontsize=8,
            color="white", style="italic")
    ax.text(8.0, 4.75, "encontro oportunístico", ha="center", fontsize=8,
            color="white", style="italic")
    ax.text(6.0, 3.35, "store-carry-forward: armazenar, transportar, encaminhar",
            ha="center", fontsize=9, color="white", alpha=0.9, style="italic")

    # Sensoriamento
    ax.add_patch(FancyBboxPatch((1.0, 1.4), 3.0, 0.85,
                 boxstyle="round,pad=0.04,rounding_size=0.1",
                 facecolor="white", edgecolor=COR_SENSORIAMENTO, linewidth=1.5))
    ax.text(2.5, 1.85, "NS-Embarcado\nGNSS, calado, velocidade",
            ha="center", va="center", fontsize=8.5, color=COR_SENSORIAMENTO)
    ax.add_patch(FancyBboxPatch((4.5, 1.4), 3.0, 0.85,
                 boxstyle="round,pad=0.04,rounding_size=0.1",
                 facecolor="white", edgecolor=COR_SENSORIAMENTO, linewidth=1.5))
    ax.text(6.0, 1.85, "NS-Boia\nsonar, profundidade",
            ha="center", va="center", fontsize=8.5, color=COR_SENSORIAMENTO)
    ax.add_patch(FancyBboxPatch((8.0, 1.4), 3.0, 0.85,
                 boxstyle="round,pad=0.04,rounding_size=0.1",
                 facecolor="white", edgecolor=COR_SENSORIAMENTO, linewidth=1.5))
    ax.text(9.5, 1.85, "NS-Margem\ninclinômetro, nível",
            ha="center", va="center", fontsize=8.5, color=COR_SENSORIAMENTO)
    ax.text(6.0, 0.85, "enlace LoRa/LoRaWAN  ·  915 MHz  ·  baixo consumo",
            ha="center", fontsize=9, color="white", alpha=0.9, style="italic")

    # Setas entre camadas
    ax.annotate("", xy=(6.0, 3.0), xytext=(6.0, 2.8),
                arrowprops=dict(arrowstyle="-|>", color=COR_TEXTO, lw=2.5))
    ax.text(6.3, 2.9, "coleta local", fontsize=8.5, color=COR_TEXTO, va="center")
    ax.annotate("", xy=(6.0, 5.6), xytext=(6.0, 5.4),
                arrowprops=dict(arrowstyle="-|>", color=COR_TEXTO, lw=2.5))
    ax.text(6.3, 5.5, "sincronização assíncrona", fontsize=8.5, color=COR_TEXTO, va="center")

    ax.text(6.0, 7.85, "Figura 4 — Arquitetura FLoRA em três camadas",
            ha="center", fontsize=14, fontweight="bold", color=COR_TEXTO)

    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor=COR_FUNDO)
    plt.close(fig)
    return caminho


# ============================================================================
# FIGURA 5 — Fluxo de bundles
# ============================================================================
def figura5_fluxo_bundles(caminho: str) -> str:
    """Diagrama de sequência do ciclo de vida de um bundle."""
    fig, ax = plt.subplots(figsize=(14, 7), dpi=DPI)
    ax.set_xlim(0, 14); ax.set_ylim(0, 7); ax.axis("off")

    ax.annotate("", xy=(13.5, 3.5), xytext=(0.5, 3.5),
                arrowprops=dict(arrowstyle="-|>", color=COR_TEXTO, lw=2))
    ax.text(13.5, 3.2, "tempo", ha="right", fontsize=9, color=COR_TEXTO, style="italic")

    marcos = [
        (1.5, "1. Sensoriamento", "NS-Boia, NS-Embarcado, NS-Margem\ncoletam profundidade, nível, posição", COR_SENSORIAMENTO),
        (4.0, "2. Coleta", "Bundle #247 é formado\ne armazenado a bordo", COR_DISSEMINACAO),
        (7.0, "3. Armazenamento", "Buffer local persistente\n(store-carry-forward)", COR_DISSEMINACAO),
        (10.0, "4. Troca DTN", "Encontro oportunístico entre\nembarcações; bundle é replicado", COR_DISSEMINACAO),
        (12.5, "5. Sincronização", "Gateway entrega à nuvem;\nbundle é consumido", COR_APLICACAO),
    ]
    for x, titulo, descricao, cor in marcos:
        ax.add_patch(mpatches.Circle((x, 3.5), 0.18,
                     facecolor=cor, edgecolor="white", linewidth=2, zorder=3))
        ax.add_patch(FancyBboxPatch((x - 1.05, 5.0), 2.1, 1.3,
                     boxstyle="round,pad=0.04,rounding_size=0.1",
                     facecolor="white", edgecolor=cor, linewidth=1.5, alpha=0.95))
        ax.text(x, 6.1, titulo, ha="center", va="center",
                fontsize=10, fontweight="bold", color=cor)
        ax.text(x, 5.5, descricao, ha="center", va="center",
                fontsize=7.5, color=COR_TEXTO)
        ax.plot([x, x], [3.68, 5.0], color=cor, lw=1, linestyle=":")

    ax.annotate("", xy=(12.5, 2.8), xytext=(4.0, 2.8),
                arrowprops=dict(arrowstyle="<->", color=COR_DESTAQUE, lw=2.5))
    ax.add_patch(FancyBboxPatch((6.5, 1.8), 3.5, 0.7,
                 boxstyle="round,pad=0.04,rounding_size=0.1",
                 facecolor=COR_DESTAQUE, edgecolor="white", linewidth=1.5, alpha=0.92))
    ax.text(8.25, 2.15, "IDTU — Informação Disponível em Tempo Útil",
            ha="center", va="center", fontsize=9, color="white", fontweight="bold")
    ax.text(8.25, 1.55, "tempo entre a coleta e a chegada ao gateway",
            ha="center", va="center", fontsize=8, color=COR_TEXTO, style="italic")

    ax.annotate("", xy=(12.5, 4.1), xytext=(4.0, 4.1),
                arrowprops=dict(arrowstyle="<->", color=COR_VERDE, lw=2))
    ax.text(8.25, 4.25, "vida útil do bundle (TTL)",
            ha="center", fontsize=8.5, color=COR_VERDE, style="italic")

    ax.text(7.0, 6.85, "Figura 5 — Fluxo de um bundle na arquitetura FLoRA",
            ha="center", fontsize=14, fontweight="bold", color=COR_TEXTO)
    ax.text(7.0, 0.6, "O bundle nasce na coleta, é transportado por encontros sucessivos\ne é consumido na sincronização. A IDTU mede o tempo útil dessa jornada.",
            ha="center", fontsize=9, color=COR_TEXTO, style="italic")

    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor=COR_FUNDO)
    plt.close(fig)
    return caminho


# ============================================================================
# FIGURA 6 — Ciclo operacional
# ============================================================================
def figura6_ciclo_operacional(caminho: str) -> str:
    """Fluxo em quatro etapas do ciclo operacional da arquitetura-alvo."""
    fig, ax = plt.subplots(figsize=(14, 5), dpi=DPI)
    ax.set_xlim(0, 14); ax.set_ylim(0, 5); ax.axis("off")

    etapas = [
        (1.8, "1. Coleta\ne qualificação", "GNSS, profundidade,\nnível, instante,\norigem e incerteza", COR_SENSORIAMENTO),
        (5.0, "2. Armazenamento", "Mensagem identificada,\nprioridade, validade\ne buffer local", COR_DISSEMINACAO),
        (8.2, "3. Troca oportunística", "Contato entre nós,\ninventário, seleção\ne encaminhamento", COR_DISSEMINACAO),
        (11.4, "4. Entrega e uso", "Gateway, aplicação,\natualização e retorno\nde alertas", COR_APLICACAO),
    ]
    for x, titulo, descricao, cor in etapas:
        ax.add_patch(FancyBboxPatch((x - 1.3, 1.8), 2.6, 2.2,
                     boxstyle="round,pad=0.08,rounding_size=0.15",
                     facecolor=cor, edgecolor="white", linewidth=2, alpha=0.92))
        ax.text(x, 3.6, titulo, ha="center", va="center",
                fontsize=11, fontweight="bold", color="white")
        ax.text(x, 2.6, descricao, ha="center", va="center",
                fontsize=8.5, color="white")

    for x0, x1 in [(3.15, 3.65), (6.35, 6.85), (9.55, 10.05)]:
        ax.annotate("", xy=(x1, 2.9), xytext=(x0, 2.9),
                    arrowprops=dict(arrowstyle="-|>", color=COR_TEXTO, lw=2.5))

    ax.annotate("", xy=(1.8, 1.4), xytext=(11.4, 1.4),
                arrowprops=dict(arrowstyle="-|>", color=COR_DESTAQUE, lw=2,
                                connectionstyle="arc3,rad=0.3"))
    ax.text(6.6, 0.65, "ciclo contínuo enquanto a embarcação navega",
            ha="center", fontsize=9, color=COR_DESTAQUE, style="italic")

    ax.add_patch(FancyBboxPatch((4.0, 0.15), 6.0, 0.5,
                 boxstyle="round,pad=0.03,rounding_size=0.1",
                 facecolor="white", edgecolor=COR_APLICACAO, linewidth=1.5))
    ax.text(7.0, 0.4, "→ decisão logística: rota, ETA, alívio, transbordo, segurança",
            ha="center", va="center", fontsize=9, color=COR_APLICACAO, fontweight="bold")

    ax.text(7.0, 4.6, "Figura 6 — Ciclo operacional da arquitetura-alvo FLoRA",
            ha="center", fontsize=14, fontweight="bold", color=COR_TEXTO)

    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor=COR_FUNDO)
    plt.close(fig)
    return caminho


# ============================================================================
# FIGURA 7 — Níveis de rio
# ============================================================================
def figura7_niveis_rio(caminho: str) -> str:
    """Níveis de rio nos três cenários ao longo de 168 h."""
    fig, ax = plt.subplots(figsize=(10, 5), dpi=DPI)
    fig.patch.set_facecolor(COR_FUNDO)
    ax.set_facecolor(COR_FUNDO)

    t = np.linspace(0, 168, 1000)

    for codigo, cor, rotulo in [("C1", COR_C1, "C1 — Operação normal"),
                                 ("C2", COR_C2, "C2 — Vazante severa"),
                                 ("C3", COR_C3, "C3 — Terra caída")]:
        if TEM_CENARIO:
            cenario = obter_cenario(codigo)
            niveis = [cenario.nivel_rio_m(float(ti)) for ti in t]
        else:
            niveis = {"C1": 0.0, "C2": -8.0, "C3": 0.0}[codigo]
        ax.plot(t, niveis, color=cor, linewidth=2, label=rotulo)

    ax.axvline(72, color=COR_C3, linestyle="--", linewidth=1.5, alpha=0.7)
    y_min = ax.get_ylim()[0]
    ax.text(74, y_min + 0.5, "C3: terra caída ativada\n(km 170, dia 3)",
            color=COR_C3, fontsize=9, va="bottom")

    ax.set_xlabel("Tempo simulado (h)", fontsize=11, color=COR_TEXTO)
    ax.set_ylabel("Nível do rio (m)", fontsize=11, color=COR_TEXTO)
    ax.set_title("Figura 7 — Níveis de rio nos três cenários hidrológicos (168 h)",
                 fontsize=13, fontweight="bold", color=COR_TEXTO, pad=12)
    ax.grid(True, color=COR_GRADE, linestyle="--", linewidth=0.6, alpha=0.8)
    ax.legend(loc="upper right", fontsize=10, framealpha=0.95)
    ax.tick_params(colors=COR_TEXTO, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(COR_TEXTO)

    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor=COR_FUNDO)
    plt.close(fig)
    return caminho


# ============================================================================
# FIGURA 8 — Tempo de viagem
# ============================================================================
def figura8_tempo_viagem(caminho: str) -> str:
    """Tempo de viagem Manaus–Itacoatiara por regime hidrológico."""
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=DPI)
    fig.patch.set_facecolor(COR_FUNDO)
    ax.set_facecolor(COR_FUNDO)

    tempo_base = 11.6
    regimes = ["Cheia", "Vazante", "Seca"]
    x = np.arange(len(regimes))
    largura = 0.35

    reativo = [tempo_base, tempo_base + 28, tempo_base + 72]
    informado = [tempo_base, tempo_base + 12, tempo_base + 24]

    barras_r = ax.bar(x - largura/2, reativo, largura,
                      label="Operação reativa (sem informação)",
                      color=COR_REATIVO, edgecolor=COR_TEXTO, linewidth=0.8)
    barras_i = ax.bar(x + largura/2, informado, largura,
                      label="Operação informada (FLoRA)",
                      color=COR_VERDE, edgecolor=COR_TEXTO, linewidth=0.8)

    for b in barras_r:
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 1.5,
                f"{b.get_height():.1f} h", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=COR_TEXTO)
    for b in barras_i:
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 1.5,
                f"{b.get_height():.1f} h", ha="center", va="bottom",
                fontsize=9, fontweight="bold", color=COR_TEXTO)

    for i, (r, inf) in enumerate(zip(reativo, informado)):
        if r > inf:
            ax.annotate(f"−{r - inf:.1f} h",
                        xy=(x[i] + largura/2, inf + 3),
                        xytext=(x[i] + largura/2, r - 4),
                        ha="center", fontsize=9, color=COR_VERDE, fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color=COR_VERDE, lw=1.2))

    ax.set_xticks(x)
    ax.set_xticklabels(regimes, fontsize=11, color=COR_TEXTO)
    ax.set_ylabel("Tempo de viagem (h)", fontsize=11, color=COR_TEXTO)
    ax.set_title("Figura 8 — Tempo de viagem Manaus–Itacoatiara por regime hidrológico",
                 fontsize=13, fontweight="bold", color=COR_TEXTO, pad=12)
    ax.grid(True, axis="y", color=COR_GRADE, linestyle="--", linewidth=0.6, alpha=0.8)
    ax.legend(loc="upper left", fontsize=10, framealpha=0.95)
    ax.tick_params(colors=COR_TEXTO, labelsize=10)
    for spine in ax.spines.values():
        spine.set_color(COR_TEXTO)
    ax.set_ylim(0, max(reativo) * 1.15)

    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor=COR_FUNDO)
    plt.close(fig)
    return caminho


# ============================================================================
# FIGURA 9 — Custo logístico e transbordo
# ============================================================================
def figura9_custo_transbordo(caminho: str) -> str:
    """Custo logístico por regime hidrológico e impacto do transbordo."""
    fig, ax = plt.subplots(figsize=(10, 6), dpi=DPI)
    fig.patch.set_facecolor(COR_FUNDO)
    ax.set_facecolor(COR_FUNDO)

    regimes = ["Cheia", "Vazante", "Seca"]
    x = np.arange(len(regimes))

    custo_base = [420, 420, 420]
    custo_espera = [0, 180, 420]
    custo_transbordo = [0, 120, 380]

    largura = 0.5
    ax.bar(x, custo_base, largura, label="Custo base (frete + combustível)",
           color="#3498db", edgecolor=COR_TEXTO, linewidth=0.8)
    ax.bar(x, custo_espera, largura, bottom=custo_base,
           label="Custo de espera (demurrage)", color="#f39c12",
           edgecolor=COR_TEXTO, linewidth=0.8)
    ax.bar(x, custo_transbordo, largura,
           bottom=np.array(custo_base) + np.array(custo_espera),
           label="Custo de transbordo / alívio", color="#e74c3c",
           edgecolor=COR_TEXTO, linewidth=0.8)

    totais = np.array(custo_base) + np.array(custo_espera) + np.array(custo_transbordo)
    for i, total in enumerate(totais):
        ax.text(i, total + 15, f"R$ {total} mil", ha="center", va="bottom",
                fontsize=10, fontweight="bold", color=COR_TEXTO)

    for i, (base, trans) in enumerate(zip(custo_base, custo_transbordo)):
        if trans > 0:
            pct = 100 * trans / base
            ax.text(i, custo_base[i] + custo_espera[i] + trans/2,
                    f"+{pct:.0f}%\nno custo base",
                    ha="center", va="center", fontsize=8,
                    color="white", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(regimes, fontsize=11, color=COR_TEXTO)
    ax.set_ylabel("Custo logístico (R$ mil)", fontsize=11, color=COR_TEXTO)
    ax.set_title("Figura 9 — Custo logístico por regime hidrológico e impacto do transbordo",
                 fontsize=13, fontweight="bold", color=COR_TEXTO, pad=12)
    ax.grid(True, axis="y", color=COR_GRADE, linestyle="--", linewidth=0.6, alpha=0.8)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.95)
    ax.tick_params(colors=COR_TEXTO, labelsize=10)
    for spine in ax.spines.values():
        spine.set_color(COR_TEXTO)
    ax.set_ylim(0, max(totais) * 1.15)

    fig.text(0.5, 0.01,
             "Em seca, o transbordo responde por ~90% do custo base. "
             "A informação em tempo útil permite antecipar o alívio em terminal intermediário,\n"
             "reduzindo o custo de espera e evitando o transbordo emergencial no trecho crítico.",
             ha="center", fontsize=8.5, color=COR_TEXTO, style="italic")

    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor=COR_FUNDO)
    plt.close(fig)
    return caminho


# ============================================================================
# MAIN
# ============================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--saida", "-o", default=os.path.join(RAIZ, "artigo", "figuras"),
                    help="pasta de saída (padrão: artigo/figuras)")
    args = ap.parse_args(argv)

    os.makedirs(args.saida, exist_ok=True)
    geradas = [
        figura4_arquitetura(os.path.join(args.saida, "figura4_arquitetura.png")),
        figura5_fluxo_bundles(os.path.join(args.saida, "figura5_fluxo_bundles.png")),
        figura6_ciclo_operacional(os.path.join(args.saida, "figura6_ciclo_operacional.png")),
        figura7_niveis_rio(os.path.join(args.saida, "figura7_niveis_rio.png")),
        figura8_tempo_viagem(os.path.join(args.saida, "figura8_tempo_viagem.png")),
        figura9_custo_transbordo(os.path.join(args.saida, "figura9_custo_transbordo.png")),
    ]

    for caminho in geradas:
        tamanho = os.path.getsize(caminho) / 1024
        print(f"  ✓ {caminho} ({tamanho:.0f} KB, {DPI} dpi)")
    print(f"\n{len(geradas)} figuras geradas em {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())