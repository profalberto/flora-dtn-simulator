#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
sensibilidade_radio.py
======================

Varredura de fator_alcance para raios de 1, 2, 5 e 12 km (literatura
amazonica), com CDF das duracoes de contato.

Uso:
    python scripts/sensibilidade_radio.py --sementes 10 --horizonte 24
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import numpy as np
from flora_dtn import ConfiguracaoDTN, MotorDTN

#: Raios de alcance efetivo (km) e fatores aproximados.
RAIOS = {1.0: 0.067, 2.0: 0.133, 5.0: 0.333, 12.0: 0.8}

DPI = 300


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sementes", type=int, default=10)
    ap.add_argument("--horizonte", type=float, default=24.0)
    ap.add_argument("--saida", default=os.path.join(RAIZ, "resultados", "sensibilidade"))
    args = ap.parse_args(argv)

    os.makedirs(args.saida, exist_ok=True)
    linhas = []
    for raio, fator in RAIOS.items():
        for semente in range(args.sementes):
            cfg = ConfiguracaoDTN(cenario="C3", protocolo="flora",
                                 horizonte_h=args.horizonte, semente=20260826 + semente,
                                 fator_alcance=fator)
            motor = MotorDTN(cfg).executar()
            r = motor.resumo()
            linhas.append({
                "raio_km": raio,
                "fator_alcance": fator,
                "semente": cfg.semente,
                "TED%": r.get("ted_percentual"),
                "IDTU": r.get("idtu_media"),
                "overhead": r.get("overhead_copias"),
                "transmissoes": r.get("transmissoes"),
                "contatos_total": r.get("contatos_total", 0),
            })
            print(f"  raio={raio}km s={cfg.semente} TED={r.get('ted_percentual')}", flush=True)

    with open(os.path.join(args.saida, "sensibilidade_radio.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
    print(f"\n{len(linhas)} execucoes salvas em {args.saida}/sensibilidade_radio.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY