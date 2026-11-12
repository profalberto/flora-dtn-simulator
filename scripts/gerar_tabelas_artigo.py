# -*- coding: utf-8 -*-
"""Gera as Tabelas 5, 6 e 7 do artigo FLoRA-DTN.

Uso:
    python scripts/gerar_tabelas_artigo.py --sementes 30 --horizonte 168
    python dtn_simulador.py artigo --sementes 3 --horizonte 2
"""

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import flora_analise
import dtn_simulador
from flora_dtn import ConfiguracaoDTN, MotorDTN

PROTOCOLOS = ("epidemico", "spray", "flora", "slp", "sc")
CENARIOS = ("C1", "C2", "C3")


def _escrita_csv(caminho, cabecalho, linhas):
    with open(caminho, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cabecalho)
        for linha in linhas:
            w.writerow(linha)


def _latex_tabela(caminho, caption, colunas, linhas, alinhamento=None):
    if alinhamento is None:
        alinhamento = "l" + "r" * (len(colunas) - 1)
    partes = [
        r"\documentclass{article}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[T1]{fontenc}",
        r"\begin{document}",
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{" + caption + "}",
        r"\begin{tabular}{" + alinhamento + "}",
        r"\hline",
        " & ".join(colunas) + r" \\",
        r"\hline",
    ]
    for linha in linhas:
        partes.append(" & ".join(str(x) for x in linha) + r" \\")
    partes += [
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
        r"\end{document}",
    ]
    with open(caminho, "w", encoding="utf-8") as fh:
        fh.write("\n".join(partes) + "\n")


def _media(vals):
    import statistics
    return statistics.fmean(vals) if vals else 0.0


def _ic95(vals):
    import statistics
    if len(vals) < 2:
        m = vals[0] if vals else 0.0
        return m, m
    m = statistics.fmean(vals)
    sd = statistics.stdev(vals)
    # t aproximado para n pequeno (usa 1.96 para n>=30, t para n<30)
    try:
        from scipy import stats as st
        tc = st.t.ppf(0.975, len(vals) - 1)
    except Exception:
        tc = 1.96
    margem = tc * sd / (len(vals) ** 0.5)
    return m - margem, m + margem


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera as tabelas 5, 6 e 7 do artigo.")
    parser.add_argument("--sementes", type=int, default=30)
    parser.add_argument("--horizonte", type=float, default=168.0)
    parser.add_argument("--saida", default=os.path.join(RAIZ, "resultados", "artigo"))
    parser.add_argument("--trabalhadores", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--densidades", default="media",
                        help="densidades de frota separadas por virgula")
    args = parser.parse_args(argv)

    sementes = [20260826 + i for i in range(args.sementes)]
    os.makedirs(args.saida, exist_ok=True)
    tabela5_dir = os.path.join(args.saida, "tabela5")
    tabela6_dir = os.path.join(args.saida, "tabela6")
    tabela9_dir = os.path.join(args.saida, "tabela9")
    densidades = [d.strip() for d in args.densidades.split(",") if d.strip()]

    tarefas = []
    for cenario in CENARIOS:
        for protocolo in PROTOCOLOS:
            for semente in sementes:
                cfg = ConfiguracaoDTN(cenario=cenario, protocolo=protocolo,
                                     horizonte_h=args.horizonte, semente=semente)
                tarefas.append((cfg, tabela6_dir, "movel"))
    for semente in sementes:
        for fixo in (False, True):
            cfg = ConfiguracaoDTN(cenario="C3", protocolo="flora",
                                 horizonte_h=args.horizonte, semente=semente)
            label = "fixo" if fixo else "movel"
            if fixo:
                cfg.bundles_por_hora_gateway_movel = 0.0
                cfg.tipos_gateway_movel = ()
            tarefas.append((cfg, tabela5_dir, label))

    # Tabela 9: densidade de frota (C2)
    for densidade in densidades:
        for protocolo in PROTOCOLOS:
            for semente in sementes:
                cfg = ConfiguracaoDTN(cenario="C2", protocolo=protocolo,
                                     horizonte_h=args.horizonte, semente=semente,
                                     densidade_frota=densidade)
                tarefas.append((cfg, tabela9_dir, densidade))

    if args.dry_run:
        print(f"dry-run: {len(tarefas)} execucoes planejadas, horizonte={args.horizonte}h")
        return 0

    os.makedirs(tabela5_dir, exist_ok=True)
    os.makedirs(tabela6_dir, exist_ok=True)
    os.makedirs(tabela9_dir, exist_ok=True)
    os.makedirs(args.saida, exist_ok=True)

    inicio = time.perf_counter()
    resultados = []
    total = len(tarefas)
    workers = args.trabalhadores or min(8, (os.cpu_count() or 4))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futuros = [pool.submit(dtn_simulador._executar_um_artigo, cfg, pasta, label)
                   for cfg, pasta, label in tarefas]
        for i, futuro in enumerate(futuros, 1):
            r = futuro.result()
            resultados.append(r)
            print(f"  [{i}/{total}] {r[0]} {r[1]} {r[3]} s={r[2]} "
                  f"TED {r[4].get('ted_percentual')}%", flush=True)
    print(f"execucoes concluidas em {time.perf_counter() - inicio:.1f}s")

    # --- Tabela 5 ---
    por_config = {"movel": [], "fixo": []}
    for cenario, protocolo, semente, config, resumo in resultados:
        if cenario == "C3" and protocolo == "flora":
            por_config[config].append(resumo)
    linhas5 = []
    for config in ("movel", "fixo"):
        rs = por_config[config]
        teds = [r["ted_percentual"] for r in rs]
        lpas = [r["lpa_minutos"] for r in rs if r["lpa_minutos"] is not None]
        covs = [r["cobertura_instantanea_media"] for r in rs]
        txs = [r["transmissoes"] for r in rs]
        inf, sup = _ic95(teds)
        linhas5.append([
            "C3",
            config,
            round(_media(teds), 1),
            round(_media(lpas), 1) if lpas else None,
            round(_media(covs), 1),
            round(_media(txs), 0),
            round(inf, 1),
            round(sup, 1),
        ])
    _escrita_csv(
        os.path.join(args.saida, "tabela5_gateways.csv"),
        ["cenario", "config_gateway", "TED%", "LPA_min",
         "cobertura_instantanea%", "transmissoes", "IC95_TED_inf", "IC95_TED_sup"],
        linhas5,
    )
    _latex_tabela(
        os.path.join(args.saida, "tabela5.tex"),
        "Gateways moveis vs. fixos (C3, %gh, %d sementes)" % (args.horizonte, args.sementes),
        ["Cenario", "Config.", "TED (\\%)", "LPA (min)", "Cob. (\\%)",
         "Tx", "IC95 inf", "IC95 sup"],
        linhas5,
    )

    # --- Tabela 6 ---
    grupos = {}
    for cenario, protocolo, semente, config, resumo in resultados:
        if config != "movel":
            continue
        grupos.setdefault((cenario, protocolo), []).append(resumo)
    linhas6 = []
    for cenario in CENARIOS:
        for protocolo in PROTOCOLOS:
            rs = grupos.get((cenario, protocolo), [])
            if not rs:
                continue
            linhas6.append([
                cenario,
                protocolo,
                round(_media([r["ted_percentual"] for r in rs]), 1),
                round(_media([r["lpa_minutos"] for r in rs if r["lpa_minutos"] is not None]), 1) if any(r["lpa_minutos"] is not None for r in rs) else None,
                round(_media([r["car_percentual"] for r in rs if r["car_percentual"] is not None]), 1) if any(r["car_percentual"] is not None for r in rs) else None,
                round(_media([r["tci_horas"] for r in rs if r["tci_horas"] is not None]), 2) if any(r["tci_horas"] is not None for r in rs) else None,
                round(_media([r["overhead_copias"] for r in rs if r["overhead_copias"] is not None]), 2) if any(r["overhead_copias"] is not None for r in rs) else None,
                round(_media([r["transmissoes"] for r in rs]), 0),
                round(_media([r["energia_total_j"] for r in rs]), 3),
            ])
    _escrita_csv(
        os.path.join(args.saida, "tabela6_protocolos.csv"),
        ["cenario", "protocolo", "TED%", "LPA_min", "CAR%", "TCI_h",
         "overhead", "transmissoes", "energia_J"],
        linhas6,
    )
    _latex_tabela(
        os.path.join(args.saida, "tabela6.tex"),
        "Comparacao dos protocolos (%gh, %d sementes)" % (args.horizonte, args.sementes),
        ["Cenario", "Protocolo", "TED (\\%)", "LPA (min)", "CAR (\\%)",
         "TCI (h)", "Overhead", "Tx", "Energia (J)"],
        linhas6,
    )

    # --- Tabela 8 (IDTU) ---
    grupos8 = {}
    for cenario, protocolo, semente, config, resumo in resultados:
        if config != "movel":
            continue
        grupos8.setdefault((cenario, protocolo), []).append(resumo)
    linhas8 = []
    for cenario in CENARIOS:
        for protocolo in PROTOCOLOS:
            rs = grupos8.get((cenario, protocolo), [])
            if not rs:
                continue
            vals = [r.get("idtu_media") for r in rs if r.get("idtu_media") is not None]
            idtu_n = round(_media([r.get("idtu_n", 0) for r in rs]), 0)
            if vals:
                inf, sup = _ic95(vals)
            else:
                inf, sup = None, None
            linhas8.append([
                cenario,
                protocolo,
                round(_media(vals), 4) if vals else None,
                round(__import__("statistics").stdev(vals), 4) if len(vals) >= 2 else 0.0,
                (round(inf, 4) if inf is not None else None),
                (round(sup, 4) if sup is not None else None),
                int(idtu_n),
            ])
    _escrita_csv(
        os.path.join(args.saida, "tabela8_idtu.csv"),
        ["cenario", "protocolo", "idtu_media", "idtu_desvio",
         "idtu_ic95_inf", "idtu_ic95_sup", "idtu_n"],
        linhas8,
    )
    _latex_tabela(
        os.path.join(args.saida, "tabela8_idtu.tex"),
        "IDTU por cenario e protocolo (%gh, %d sementes)" % (args.horizonte, args.sementes),
        ["Cenario", "Protocolo", "IDTU med.", "Desvio", "IC95 inf", "IC95 sup", "n"],
        linhas8,
    )
    registros = [r for r in flora_analise.carregar_registros([tabela6_dir])
                 if _horizonte_igual(r.horizonte, args.horizonte)]
    resultado = flora_analise.analisar(registros, metricas=list(flora_analise.METRICAS_PADRAO),
                                       confianca=0.95)
    linhas7 = []
    for metrica, info in resultado["metricas"].items():
        teste = info["teste"]
        linhas7.append([
            metrica,
            teste.get("nome") or "n/a",
            (round(teste["estatistica"], 4) if teste.get("estatistica") is not None else None),
            (round(teste["p"], 6) if teste.get("p") is not None else None),
            (round(teste["p_holm"], 6) if teste.get("p_holm") is not None else None),
            (round(teste["tamanho_efeito"], 4) if teste.get("tamanho_efeito") is not None else None),
            teste.get("n_blocos", 0),
        ])
    _escrita_csv(
        os.path.join(args.saida, "tabela7_estatistica.csv"),
        ["metrica", "teste", "estatistica", "p_valor",
         "p_ajustado_Holm", "tamanho_efeito", "n_blocos"],
        linhas7,
    )
    _latex_tabela(
        os.path.join(args.saida, "tabela7.tex"),
        "Analise estatistica (%gh, %d sementes)" % (args.horizonte, args.sementes),
        ["Metrica", "Teste", "Estat.", "p", "p Holm", "Tam. efeito", "Blocos"],
        linhas7,
    )

    # --- Tabela 9 (densidade) ---
    grupos9 = {}
    for cenario, protocolo, semente, config, resumo in resultados:
        if cenario != "C2":
            continue
        grupos9.setdefault((config, protocolo), []).append(resumo)
    linhas9 = []
    for densidade in densidades:
        for protocolo in PROTOCOLOS:
            rs = grupos9.get((densidade, protocolo), [])
            if not rs:
                continue
            linhas9.append([
                densidade,
                protocolo,
                round(_media([r["ted_percentual"] for r in rs]), 1),
                round(_media([r["idtu_media"] for r in rs if r.get("idtu_media") is not None]), 4) if any(r.get("idtu_media") is not None for r in rs) else None,
                round(_media([r["overhead_copias"] for r in rs if r.get("overhead_copias") is not None]), 2) if any(r.get("overhead_copias") is not None for r in rs) else None,
                round(_media([r["transmissoes"] for r in rs]), 0),
            ])
    _escrita_csv(
        os.path.join(args.saida, "tabela9_densidade.csv"),
        ["densidade", "protocolo", "TED%", "IDTU", "overhead", "transmissoes"],
        linhas9,
    )
    _latex_tabela(
        os.path.join(args.saida, "tabela9_densidade.tex"),
        "Sensibilidade a densidade de frota (C2, %gh, %d sementes)" % (args.horizonte, args.sementes),
        ["Densidade", "Protocolo", "TED (\\%)", "IDTU", "Overhead", "Tx"],
        linhas9,
    )

    print("arquivos gerados em", args.saida)
    for nome in ("tabela5_gateways.csv", "tabela5.tex", "tabela6_protocolos.csv",
                 "tabela6.tex", "tabela7_estatistica.csv", "tabela7.tex",
                 "tabela8_idtu.csv", "tabela8_idtu.tex",
                 "tabela9_densidade.csv", "tabela9_densidade.tex"):
        print("  ", nome)


def _horizonte_igual(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a) == str(b)


if __name__ == "__main__":
    main()
