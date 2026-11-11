#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
exportar_figuras_artigo.py
==========================

Gera as figuras 4, 5 e 6 do artigo FLoRA em 300 dpi.

Figura 4 — Arquitetura em três camadas (diagrama esquemático).
Figura 5 — Fluxo de bundles na rede (diagrama de sequência).
Figura 6 — Ciclo operacional da arquitetura-alvo (fluxo em quatro etapas).

As figuras são diagramas conceituais, não capturas de tela. Foram desenhadas
com matplotlib puro, em vetor, e exportadas em PNG a 300 dpi. Isso garante
que sejam legíveis em qualquer tamanho de impressão e que possam ser editadas
sem perda de qualidade.

Uso:
    python scripts/exportar_figuras_artigo.py
    python scripts/exportar_figuras_artigo.py --saida artigo/figuras
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
import matplotlib.patheffects as pe

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

#: Cores alinhadas com a paleta do simulador (flora_ui.py).
COR_APLICACAO = "#1f3a5f"
COR_DISSEMINACAO = "#2e6b9e"
COR_SENSORIAMENTO = "#4a9bc7"
COR_TERRA = "#d9c9a3"
COR_AGUA = "#a8d4e6"
COR_TEXTO = "#1a1a1a"
COR_DESTAQUE = "#c0392b"
COR_VERDE = "#27ae60"

DPI = 300


def figura4_arquitetura(caminho: str) -> str:
    fig, ax = plt.subplots(figsize=(12, 8), dpi=DPI)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis("off")

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
        ax.add_patch(FancyBboxPatch(
            (0.3, y0), 11.4, y1 - y0,
            boxstyle="round,pad=0.05,rounding_size=0.15",
            facecolor=cor, edgecolor="white", linewidth=2, alpha=0.92))
        ax.text(6.0, y1 - 0.25, titulo, ha="center", va="top",
                fontsize=13, fontweight="bold", color="white")
        ax.text(6.0, y1 - 0.55, subtitulo, ha="center", va="top",
                fontsize=9.5, color="white", alpha=0.92, style="italic")

    ax.add_patch(mpatches.Ellipse((6.0, 6.5), 2.4, 1.0,
                                   facecolor="white", edgecolor=COR_APLICACAO,
                                   linewidth=2, alpha=0.95))
    ax.text(6.0, 6.5, "Nuvem FLoRA\n(agregação, IA/ML)", ha="center", va="center",
            fontsize=9, color=COR_APLICACAO, fontweight="bold")
    ax.add_patch(FancyBboxPatch((1.0, 6.0), 2.4, 1.0,
                                 boxstyle="round,pad=0.04,rounding_size=0.1",
                                 facecolor="white", edgecolor=COR_APLICACAO,
                                 linewidth=1.5))
    ax.text(2.2, 6.5, "Decisão logística\n(rota, ETA, alívio)", ha="center", va="center",
            fontsize=8.5, color=COR_APLICACAO)
    ax.add_patch(FancyBboxPatch((8.6, 6.0), 2.4, 1.0,
                                 boxstyle="round,pad=0.04,rounding_size=0.1",
                                 facecolor="white", edgecolor=COR_APLICACAO,
                                 linewidth=1.5))
    ax.text(9.8, 6.5, "Mapas de risco\n(atualização)", ha="center", va="center",
            fontsize=8.5, color=COR_APLICACAO)
    for x0, x1 in [(2.6, 4.6), (7.4, 8.4)]:
        ax.annotate("", xy=(x1, 6.5), xytext=(x0, 6.5),
                    arrowprops=dict(arrowstyle="<->", color="white", lw=1.8))

    for x, label in [(2.0, "Barco A"), (6.0, "Barco B"), (10.0, "Barco C")]:
        ax.add_patch(mpatches.Circle((x, 4.2), 0.32,
                                      facecolor="white", edgecolor=COR_DISSEMINACAO,
                                      linewidth=2))
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

    for x in (1.0, 4.5, 8.0):
        ax.add_patch(FancyBboxPatch((x, 1.4), 3.0, 0.85,
                                     boxstyle="round,pad=0.04,rounding_size=0.1",
                                     facecolor="white", edgecolor=COR_SENSORIAMENTO,
                                     linewidth=1.5))
    ax.text(2.5, 1.85, "NS-Embarcado\nGNSS, calado, velocidade", ha="center", va="center",
            fontsize=8.5, color=COR_SENSORIAMENTO)
    ax.text(6.0, 1.85, "NS-Boia\nsonar, profundidade", ha="center", va="center",
            fontsize=8.5, color=COR_SENSORIAMENTO)
    ax.text(9.5, 1.85, "NS-Margem\ninclinômetro, nível", ha="center", va="center",
            fontsize=8.5, color=COR_SENSORIAMENTO)
    ax.text(6.0, 0.85, "enlace LoRa/LoRaWAN  ·  915 MHz  ·  baixo consumo",
            ha="center", fontsize=9, color="white", alpha=0.9, style="italic")

    ax.annotate("", xy=(6.0, 3.0), xytext=(6.0, 2.8),
                arrowprops=dict(arrowstyle="-|>", color=COR_TEXTO, lw=2.5))
    ax.text(6.3, 2.9, "coleta local", fontsize=8.5, color=COR_TEXTO, va="center")
    ax.annotate("", xy=(6.0, 5.6), xytext=(6.0, 5.4),
                arrowprops=dict(arrowstyle="-|>", color=COR_TEXTO, lw=2.5))
    ax.text(6.3, 5.5, "sincronização assíncrona", fontsize=8.5, color=COR_TEXTO, va="center")

    ax.text(6.0, 7.85, "Figura 4 — Arquitetura FLoRA em três camadas",
            ha="center", fontsize=14, fontweight="bold", color=COR_TEXTO)

    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return caminho


def figura5_fluxo_bundles(caminho: str) -> str:
    fig, ax = plt.subplots(figsize=(14, 7), dpi=DPI)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.axis("off")

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
                                     facecolor="white", edgecolor=cor, linewidth=1.5,
                                     alpha=0.95))
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
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return caminho


def figura6_ciclo_operacional(caminho: str) -> str:
    fig, ax = plt.subplots(figsize=(14, 5), dpi=DPI)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 5)
    ax.axis("off")

    etapas = [
        (1.8, "1. Coleta\ne qualificação",
         "GNSS, profundidade,\nnível, instante,\norigem e incerteza",
         COR_SENSORIAMENTO),
        (5.0, "2. Armazenamento",
         "Mensagem identificada,\nprioridade, validade\ne buffer local",
         COR_DISSEMINACAO),
        (8.2, "3. Troca oportunística",
         "Contato entre nós,\ninventário, seleção\ne encaminhamento",
         COR_DISSEMINACAO),
        (11.4, "4. Entrega e uso",
         "Gateway, aplicação,\natualização e retorno\nde alertas",
         COR_APLICACAO),
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
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return caminho


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gera as figuras 4, 5 e 6 do artigo FLoRA.")
    ap.add_argument("--saida", "-o", default=os.path.join(RAIZ, "artigo", "figuras"),
                    help="pasta de saida (padrao: artigo/figuras)")
    args = ap.parse_args(argv)

    os.makedirs(args.saida, exist_ok=True)
    geradas = []
    geradas.append(figura4_arquitetura(os.path.join(args.saida, "figura4_arquitetura.png")))
    geradas.append(figura5_fluxo_bundles(os.path.join(args.saida, "figura5_fluxo_bundles.png")))
    geradas.append(figura6_ciclo_operacional(os.path.join(args.saida, "figura6_ciclo_operacional.png")))

    for caminho in geradas:
        tamanho = os.path.getsize(caminho) / 1024
        print(f"  gerada: {caminho} ({tamanho:.0f} KB, {DPI} dpi)")
    print(f"\n{len(geradas)} figuras geradas em {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY