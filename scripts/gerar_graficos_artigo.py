#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
gerar_graficos_artigo.py
========================

Gera os gráficos complementares do artigo FLoRA:

Figura 7 — Níveis de rio nos cenários C1, C2 e C3 ao longo de 168 h.
Figura 8 — Tempo de viagem Manaus–Itacoatiara em cheia, vazante e seca,
           comparando operação reativa (sem informação) com operação
           informada (FLoRA).
Figura 9 — Custo logístico agregado e impacto do transbordo.

Os gráficos são complementares aos resultados experimentais das Tabelas 5–7.

Uso:
    python scripts/gerar_graficos_artigo.py
    python scripts/gerar_graficos_artigo.py --saida artigo/figuras
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from flora_cenario import obter_cenario

DPI = 300

COR_C1 = "#2e7d32"
COR_C2 = "#e67e22"
COR_C3 = "#c0392b"
COR_INFORMADO = "#1f4e79"
COR_REATIVO = "#95a5a6"
COR_FLORA = "#27ae60"
COR_FUNDO = "#ffffff"
COR_GRADE = "#e0e0e0"
COR_TEXTO = "#1a1a1a"


def figura7_niveis_rio(caminho: str) -> str:
    fig, ax = plt.subplots(figsize=(10, 5), dpi=DPI)
    fig.patch.set_facecolor(COR_FUNDO)
    ax.set_facecolor(COR_FUNDO)

    t = np.linspace(0, 168, 1000)

    for codigo, cor, rotulo in [("C1", COR_C1, "C1 — Operação normal"),
                                 ("C2", COR_C2, "C2 — Vazante severa"),
                                 ("C3", COR_C3, "C3 — Terra caída")]:
        cenario = obter_cenario(codigo)
        niveis = [cenario.nivel_rio_m(float(ti)) for ti in t]
        ax.plot(t, niveis, color=cor, linewidth=2, label=rotulo)

    ax.axvline(72, color=COR_C3, linestyle="--", linewidth=1.5, alpha=0.7)
    ax.text(74, 0.5, "C3: terra caída ativada\n(km 170, dia 3)",
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


def figura8_tempo_viagem(caminho: str) -> str:
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=DPI)
    fig.patch.set_facecolor(COR_FUNDO)
    ax.set_facecolor(COR_FUNDO)

    tempo_base = 11.6
    regimes = ["Cheia", "Vazante", "Seca"]
    x = np.arange(len(regimes))
    largura = 0.35

    reativo = [tempo_base, tempo_base + 28, tempo_base + 72]
    informado = [tempo_base, tempo_base + 12, tempo_base + 24]

    barras_r = ax.bar(x - largura/2, reativo, largura, label="Operação reativa (sem informação)",
                      color=COR_REATIVO, edgecolor=COR_TEXTO, linewidth=0.8)
    barras_i = ax.bar(x + largura/2, informado, largura, label="Operação informada (FLoRA)",
                      color=COR_FLORA, edgecolor=COR_TEXTO, linewidth=0.8)

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
                        ha="center", fontsize=9, color=COR_FLORA, fontweight="bold",
                        arrowprops=dict(arrowstyle="->", color=COR_FLORA, lw=1.2))

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


def figura9_custo_transbordo(caminho: str) -> str:
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


def capturar_simulacao(caminho: str, cenario: str, t_h: float = 168.0) -> str:
    """Captura a carta náutica do simulador em 300 dpi."""
    from flora_dtn import ConfiguracaoDTN, MotorDTN
    from flora_mapa import CartaNautica, OpcoesCarta

    cfg = ConfiguracaoDTN(cenario=cenario, protocolo="flora",
                          horizonte_h=t_h, semente=20260826)
    motor = MotorDTN(cfg).executar(t_h)
    opcoes = OpcoesCarta(escala=2.0, nx=520, ny=312)
    carta = CartaNautica(opcoes)
    img = carta.render(motor.cenario, t_h, motor=motor)
    carta.salvar(img, caminho, dpi=300)
    return caminho


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gera os gráficos 7, 8 e 9 do artigo FLoRA.")
    ap.add_argument("--saida", "-o", default=os.path.join(RAIZ, "artigo", "figuras"),
                    help="pasta de saída (padrão: artigo/figuras)")
    args = ap.parse_args(argv)

    os.makedirs(args.saida, exist_ok=True)
    geradas = []
    geradas.append(figura7_niveis_rio(os.path.join(args.saida, "figura7_niveis_rio.png")))
    geradas.append(figura8_tempo_viagem(os.path.join(args.saida, "figura8_tempo_viagem.png")))
    geradas.append(figura9_custo_transbordo(os.path.join(args.saida, "figura9_custo_transbordo.png")))
    for codigo in ("C1", "C2", "C3"):
        geradas.append(capturar_simulacao(
            os.path.join(args.saida, f"simulacao_{codigo}.png"), codigo))

    for caminho in geradas:
        tamanho = os.path.getsize(caminho) / 1024
        print(f"  gerada: {caminho} ({tamanho:.0f} KB, {DPI} dpi)")
    print(f"\n{len(geradas)} gráficos gerados em {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY