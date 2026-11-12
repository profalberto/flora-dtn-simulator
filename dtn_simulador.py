#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
dtn_simulador.py
================

Ponto de entrada unico do simulador FLoRA-DTN (DTN-LoRa / UFAM).

Cinco modos
-----------
``gui``      abre a interface pygame (padrao quando nenhum subcomando e dado);
``rodar``    executa a simulacao sem tela e grava os CSV de metricas e frota
             (mais um JSON unico com a simulacao completa, salvo se
             ``--sem-completo``);
``carta``    gera a carta nautica do cenario, opcionalmente depois de rodar a
             simulacao ate um instante;
``comparar`` roda os cinco protocolos no mesmo cenario e imprime a tabela
             comparativa das metricas (sequencial ou em paralelo);
``analisar`` agrega os ``*_metricas.csv`` e aplica IC95%, Shapiro-Wilk,
             ANOVA/Friedman e correcao de Holm.

Toda execucao imprime a versao e o commit no inicio, e grava um log em
``logs/``. Use ``--sem-log`` para desligar e ``--log-arquivo`` para escolher o
destino.

Exemplos
--------
    python dtn_simulador.py --version
    python dtn_simulador.py
    python dtn_simulador.py rodar --cenario C3 --protocolo flora --horizonte 168
    python dtn_simulador.py carta --cenario C2 --saida cartas/vazante.png
    python dtn_simulador.py comparar --cenario C3 --horizonte 168 --paralelo
    python dtn_simulador.py analisar --entrada resultados

O modo headless nao inicializa o pygame, de modo que roda em servidor.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time

RAIZ = os.path.dirname(os.path.abspath(__file__))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import flora_log
import flora_versao

PROTOCOLOS = ("epidemico", "spray", "flora", "slp", "sc")
PROTOCOLOS_V13 = ("sc", "oficial", "slp", "slp_moveis", "satelite", "epidemico",
                  "spray", "flora", "flora_perigo")
CENARIOS = ("C1", "C2", "C3")


# ---------------------------------------------------------------------------
# 1. CONFIGURACAO
# ---------------------------------------------------------------------------
def construir_cfg(args) -> "ConfiguracaoDTN":
    from flora_dtn import ConfiguracaoDTN

    if getattr(args, "dry_run", False):
        args.horizonte = 0.1
        args.semente = 20260826

    campos = {
        "cenario": args.cenario,
        "protocolo": args.protocolo,
        "horizonte_h": args.horizonte,
        "semente": args.semente,
        "passo_s": args.passo,
    }
    # Somente os ajustes efetivamente informados na linha de comando sao
    # repassados; caso contrario sobrescreveriam com ``None`` os padroes
    # calibrados de `ConfiguracaoDTN`.
    opcionais = {
        "fator_alcance": args.fator_alcance,
        "limiar_utilidade": args.limiar_utilidade,
        "fator_retencao": args.fator_retencao,
        "utilidade_sigma_d_km": args.sigma_d,
        "copias_spray": args.copias_spray,
    }
    campos.update({k: v for k, v in opcionais.items() if v is not None})
    if args.sem_sombreamento:
        campos["perda_sombreamento"] = 0.0
    if getattr(args, "utilidade_legada", False):
        campos["utilidade_legada"] = True
    return ConfiguracaoDTN(**campos)


def argumentos_comuns(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--version", "-V", action="version",
                        version=flora_versao.versao_completa(),
                        help="mostra a versao e o commit e sai")
    parser.add_argument("--cenario", "-c", choices=CENARIOS, default="C1",
                        help="cenario hidrologico (padrao: C1)")
    parser.add_argument("--protocolo", "-p", choices=PROTOCOLOS, default="flora",
                        help="protocolo de roteamento (padrao: flora)")
    parser.add_argument("--horizonte", "-H", type=float, default=168.0,
                        help="horizonte simulado em horas (padrao: 168)")
    parser.add_argument("--semente", "-s", type=int, default=20260826,
                        help="semente do gerador aleatorio (padrao: 20260826)")
    parser.add_argument("--passo", type=float, default=10.0,
                        help="duracao do passo de tempo em segundos (padrao: 10)")
    parser.add_argument("--fator-alcance", type=float, default=None,
                        help="multiplicador do alcance LoRa modelado")
    parser.add_argument("--limiar-utilidade", type=float, default=None,
                        help="utilidade minima para retransmitir (FLoRA)")
    parser.add_argument("--fator-retencao", type=float, default=None,
                        help="ganho relativo exigido do vizinho (FLoRA)")
    parser.add_argument("--sigma-d", type=float, default=None,
                        help="abertura da gaussiana de distancia (FLoRA)")
    parser.add_argument("--copias-spray", type=int, default=None,
                        help="copias por origem no spray-and-wait")
    parser.add_argument("--sem-sombreamento", action="store_true",
                        help="desliga a perda por sombreamento do enlace")
    parser.add_argument("--utilidade-legada", action="store_true",
                        help="preserva o comportamento anterior da utilidade (prioridade cancela)")
    parser.add_argument("--dry-run", action="store_true",
                        help="validacao rapida: 0.1 h, semente 20260826, sem gravar arquivos")


def argumentos_log(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--log-arquivo", default=None, metavar="CAMINHO",
                        help="arquivo de log (padrao: logs/flora_<data>_<pid>.log)")
    parser.add_argument("--sem-log", action="store_true",
                        help="nao grava log em arquivo")
    parser.add_argument("--log-console", action="store_true",
                        help="tambem mostra avisos do log no terminal")
    parser.add_argument("--verboso", "-v", action="store_true",
                        help="grava o log em nivel DEBUG")


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dtn_simulador.py",
        description="Simulador FLoRA-DTN: DTN-LoRa na calha do Amazonas (UFAM).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Exemplos")[-1],
    )
    p.add_argument("--version", "-V", action="version",
                   version=flora_versao.versao_completa(),
                   help="mostra a versao e o commit e sai")
    sub = p.add_subparsers(dest="comando")

    g = sub.add_parser("gui", help="abre a interface grafica (padrao)")
    argumentos_comuns(g)
    argumentos_log(g)

    r = sub.add_parser("rodar", help="executa sem tela e grava CSV")
    argumentos_comuns(r)
    argumentos_log(r)
    r.add_argument("--saida", "-o", default=os.path.join(RAIZ, "resultados"),
                   help="pasta de saida dos CSV (padrao: ./resultados)")
    r.add_argument("--sem-completo", action="store_true",
                   help="nao grava o JSON unico com a simulacao completa")

    c = sub.add_parser("carta", help="gera a carta nautica em PNG")
    c.add_argument("--version", "-V", action="version",
                   version=flora_versao.versao_completa())
    c.add_argument("--cenario", "-c", choices=CENARIOS, default="C1")
    c.add_argument("--instante", "-t", type=float, default=0.0,
                   help="instante da carta em horas (padrao: 0)")
    c.add_argument("--rodar", type=float, default=None, metavar="HORAS",
                   help="simula ate HORAS antes de gerar a carta")
    c.add_argument("--protocolo", "-p", choices=PROTOCOLOS, default="flora")
    c.add_argument("--semente", "-s", type=int, default=20260826)
    c.add_argument("--passo", type=float, default=10.0)
    c.add_argument("--escala", type=float, default=1.6,
                   help="fator de escala da carta (padrao: 1.6)")
    c.add_argument("--saida", "-o", default=os.path.join(RAIZ, "cartas", "carta.png"),
                   help="arquivo PNG de saida")
    c.add_argument("--sem-legenda", action="store_true", help="omite a legenda")
    c.add_argument("--sem-metadados", action="store_true", help="omite o quadro de metricas")
    c.add_argument("--base-satelite", action="store_true",
                   help="usa o mosaico de satelite no lugar da folha de carta")
    c.add_argument("--sem-curvas", action="store_true", help="omite as curvas de cote")
    c.add_argument("--sem-sondagens", action="store_true", help="omite as sondagens")
    c.add_argument("--sem-relevo", action="store_true",
                   help="omite o sombreado ilustrativo do terreno")
    c.add_argument("--sem-limites", action="store_true",
                   help="omite os limites de largura navegavel")
    c.add_argument("--tinta-profundidade", action="store_true",
                   help="pinta a profundidade por cima do fundo, como a rampa "
                        "de risco de encalhe sobre o satelite")
    c.add_argument("--dry-run", action="store_true",
                   help="validacao rapida: 0.1 h, semente 20260826, sem gravar arquivos")
    argumentos_log(c)

    m = sub.add_parser("comparar", help="compara os cinco protocolos")
    argumentos_comuns(m)
    argumentos_log(m)
    m.add_argument("--saida", "-o", default=None,
                   help="pasta opcional para gravar os CSV de cada protocolo")
    m.add_argument("--paralelo", action="store_true",
                   help="executa os protocolos em processos simultaneos")
    m.add_argument("--trabalhadores", type=int, default=None, metavar="N",
                   help="numero de processos no modo paralelo (padrao: ate 5)")

    a = sub.add_parser("analisar", help="estatistica agregada dos CSV de metricas")
    a.add_argument("--version", "-V", action="version",
                   version=flora_versao.versao_completa())
    a.add_argument("--entrada", "-e", nargs="+",
                   default=[os.path.join(RAIZ, "resultados")],
                   metavar="CAMINHO",
                   help="pastas, arquivos CSV/JSON ou globs (padrao: resultados/)")
    a.add_argument("--saida", "-o", default=None,
                   help="pasta de saida (padrao: resultados/analise)")
    a.add_argument("--metricas", default=None,
                   help="lista de metricas separadas por virgula")
    a.add_argument("--cenario", "-c", choices=CENARIOS, default=None,
                   help="considera apenas este cenario")
    a.add_argument("--horizonte", "-H", type=float, default=None,
                   help="considera apenas execucoes com este horizonte (horas)")
    a.add_argument("--confianca", type=float, default=0.95,
                   help="nivel do intervalo de confianca (padrao: 0.95)")
    a.add_argument("--dry-run", action="store_true",
                   help="validacao rapida: nao grava arquivos de saida")
    argumentos_log(a)

    art = sub.add_parser("artigo", help="gera as tabelas 5, 6 e 7 do artigo")
    argumentos_comuns(art)
    argumentos_log(art)
    art.add_argument("--sementes", type=int, default=30,
                     help="numero de sementes (padrao: 30)")
    art.add_argument("--saida", "-o",
                     default=os.path.join(RAIZ, "resultados", "artigo"),
                     help="pasta de saida (padrao: resultados/artigo)")
    art.add_argument("--trabalhadores", type=int, default=None, metavar="N",
                     help="numero de processos (padrao: ate 8)")
    art.add_argument("--densidades", default="media",
                     help="densidades de frota separadas por virgula (padrao: media)")
    return p


# ---------------------------------------------------------------------------
# 2. SAIDA NO TERMINAL
# ---------------------------------------------------------------------------
def _num(v, casas=1, sufixo=""):
    return "n/a" if v is None else f"{v:.{casas}f}{sufixo}"


#: Larguras fixas das colunas do resumo comparativo, compartilhadas pelo
#: cabecalho e pelas linhas para que fiquem alinhadas no terminal.
COLUNAS_RESUMO = (("<22s", "protocolo"), ("<10s", "TED"), ("<10s", "TED 6 h"),
                  ("<11s", "LPA"), ("<10s", "CAR"), ("<10s", "TCI"),
                  ("<9s", "overhead"), ("<9s", "tx"))


def linha_resumo(r: dict) -> str:
    valores = (
        r.get("protocolo_rotulo", r.get("protocolo", "?")),
        _num(r.get("ted_percentual"), 1, "%"),
        _num(r.get("ted_no_horizonte_percentual"), 1, "%"),
        _num(r.get("lpa_minutos"), 1, "min"),
        _num(r.get("car_percentual"), 1, "%"),
        _num(r.get("tci_horas"), 1, "h"),
        _num(r.get("overhead_copias"), 2, "x"),
        str(r.get("transmissoes", 0)),
    )
    return "".join(f"{v:{fmt}}" for (fmt, _), v in zip(COLUNAS_RESUMO, valores)).rstrip()


def cabecalho_resumo() -> str:
    return "".join(f"{rot:{fmt}}" for fmt, rot in COLUNAS_RESUMO)


# ---------------------------------------------------------------------------
# 3. MODO: RODAR
# ---------------------------------------------------------------------------
def modo_rodar(args) -> int:
    from flora_dtn import MotorDTN

    log = flora_log.obter_logger("rodar")
    if getattr(args, "dry_run", False):
        args.sem_log = True
    cfg = construir_cfg(args)
    cfg.validar()
    motor = MotorDTN(cfg)
    print(f"Cenario {cfg.cenario} - {motor.cenario.nome} | "
          f"protocolo {motor.protocolo.nome} | horizonte {cfg.horizonte_h:g} h | "
          f"semente {cfg.semente}")
    log.info("rodar: cenario=%s protocolo=%s horizonte=%g semente=%d passo=%g",
             cfg.cenario, cfg.protocolo, cfg.horizonte_h, cfg.semente, cfg.passo_s)
    inicio = time.perf_counter()
    passos_totais = max(1, int(cfg.horizonte_h * 3600.0 / cfg.passo_s))
    estado = {"ultimo": -1.0}

    def progresso(frac: float) -> None:
        pct = int(frac * 100)
        if pct >= estado["ultimo"] + 5:
            estado["ultimo"] = pct
            tempo = time.perf_counter() - inicio
            eta = tempo / max(frac, 1e-9) * (1.0 - frac)
            print(f"  {pct:3d}%  {tempo:6.1f}s decorridos, ~{eta:5.1f}s restantes",
                  end="\r", flush=True)
            log.debug("progresso: %d%% em %.1fs", pct, tempo)

    motor.executar(progresso=progresso)
    duracao = time.perf_counter() - inicio
    print(f"  100%  concluido em {duracao:6.1f}s "
          f"({passos_totais} passos)              ")

    r = motor.resumo()
    print("\n" + cabecalho_resumo())
    print(linha_resumo(r))

    base = os.path.join(args.saida, f"{cfg.cenario}_{motor.protocolo.nome}_"
                                   f"{cfg.horizonte_h:g}h_s{cfg.semente}")
    if not getattr(args, "dry_run", False):
        os.makedirs(args.saida, exist_ok=True)
        for caminho in motor.exportar_tudo(base):
            print(f"  gravado: {caminho}")
            log.info("gravado: %s", caminho)
        if not getattr(args, "sem_completo", False):
            completo = f"{base}_simulacao.json"
            motor.exportar_simulacao(completo)
            print(f"  gravado: {completo}")
            log.info("gravado: %s", completo)
    log.info("rodar concluido em %.1fs: ted=%.2f%% lpa=%s min transmissoes=%s",
             duracao, r.get("ted_percentual") or 0.0, r.get("lpa_minutos"),
             r.get("transmissoes"))
    return 0


# ---------------------------------------------------------------------------
# 4. MODO: COMPARAR
# ---------------------------------------------------------------------------
def _base_saida(cfg, pasta: str | None) -> str | None:
    if not pasta:
        return None
    return os.path.join(pasta, f"{cfg.cenario}_{cfg.protocolo}_"
                               f"{cfg.horizonte_h:g}h_s{cfg.semente}")


def _executar_um(cfg, pasta_saida: str | None):
    """Executa um protocolo e devolve ``(resumo, duracao, arquivos)``."""
    from flora_dtn import MotorDTN

    inicio = time.perf_counter()
    motor = MotorDTN(cfg).executar()
    duracao = time.perf_counter() - inicio
    arquivos = []
    base = _base_saida(cfg, pasta_saida)
    if base:
        os.makedirs(pasta_saida, exist_ok=True)
        arquivos = motor.exportar_tudo(base)
    return motor.resumo(), duracao, arquivos


def _executar_um_artigo(cfg, pasta_saida: str, config_label: str):
    """Executa uma configuracao do artigo e grava CSV + JSON completos."""
    from flora_dtn import MotorDTN

    motor = MotorDTN(cfg).executar()
    base = os.path.join(
        pasta_saida,
        f"{cfg.cenario}_{cfg.protocolo}_{config_label}_"
        f"{cfg.horizonte_h:g}h_s{cfg.semente}",
    )
    os.makedirs(pasta_saida, exist_ok=True)
    motor.exportar_metricas(f"{base}_metricas.csv")
    motor.exportar_simulacao(f"{base}_simulacao.json")
    return (cfg.cenario, cfg.protocolo, cfg.semente, config_label, motor.resumo())


def _tarefa_protocolo(tarefa):
    """
    Funcao de topo, picklavel, usada pelo `ProcessPoolExecutor`.

    Recebe a configuracao pronta porque o objeto `ConfiguracaoDTN` e um
    dataclass simples (floats, ints, strings, tuplas e dicts), sem referencias
    a pygame ou a recursos abertos.
    """
    cfg, pasta_saida = tarefa
    resumo, duracao, arquivos = _executar_um(cfg, pasta_saida)
    return cfg.protocolo, resumo, duracao, arquivos


def _comparar_sequencial(cfgs, pasta_saida: str | None):
    resultados = {}
    for cfg in cfgs:
        resumo, duracao, arquivos = _executar_um(cfg, pasta_saida)
        resultados[cfg.protocolo] = (resumo, duracao, arquivos)
        print(linha_resumo(resumo) + f"  ({duracao:5.1f}s)", flush=True)
    return resultados


def _comparar_paralelo(cfgs, pasta_saida: str | None, trabalhadores: int | None):
    from concurrent.futures import ProcessPoolExecutor, as_completed

    log = flora_log.obter_logger("comparar")
    total = trabalhadores or min(len(cfgs), os.cpu_count() or 1)
    total = max(1, min(total, len(cfgs)))
    print(f"  executando {len(cfgs)} protocolos em {total} processo(s)", flush=True)

    resultados = {}
    try:
        with ProcessPoolExecutor(max_workers=total) as pool:
            futuros = {
                pool.submit(_tarefa_protocolo, (cfg, pasta_saida)): cfg.protocolo
                for cfg in cfgs
            }
            for futuro in as_completed(futuros):
                nome, resumo, duracao, arquivos = futuro.result()
                resultados[nome] = (resumo, duracao, arquivos)
                log.info("paralelo: %s concluido em %.1fs", nome, duracao)
                print(f"  concluido: {nome} ({duracao:5.1f}s)", flush=True)
    except Exception as exc:  # pragma: no cover - depende do ambiente
        # Ambiente sem suporte a processos (sandbox, politica do sistema):
        # termina o que faltou no processo principal em vez de perder a rodada.
        log.warning("paralelo indisponivel (%s); caindo para sequencial", exc)
        print(f"  aviso: paralelismo indisponivel ({exc}); seguindo em sequencia",
              flush=True)
        for cfg in cfgs:
            if cfg.protocolo in resultados:
                continue
            resumo, duracao, arquivos = _executar_um(cfg, pasta_saida)
            resultados[cfg.protocolo] = (resumo, duracao, arquivos)
    return resultados


def modo_comparar(args) -> int:
    log = flora_log.obter_logger("comparar")
    print(f"Comparacao dos {len(PROTOCOLOS)} protocolos | cenario {args.cenario} | "
          f"horizonte {args.horizonte:g} h | semente {args.semente}"
          f"{' | paralelo' if args.paralelo else ''}\n")

    cfgs = []
    for nome in PROTOCOLOS:
        cfg = construir_cfg(args)
        cfg.protocolo = nome
        cfg.validar()
        cfgs.append(cfg)

    if args.saida:
        os.makedirs(args.saida, exist_ok=True)

    if args.paralelo:
        resultados = _comparar_paralelo(cfgs, args.saida, args.trabalhadores)
        # A tabela final respeita a ordem de PROTOCOLOS, mesmo quando os
        # processos terminam fora de ordem.
        print("\n" + cabecalho_resumo())
        for nome in PROTOCOLOS:
            if nome not in resultados:
                continue
            resumo, duracao, _ = resultados[nome]
            print(linha_resumo(resumo) + f"  ({duracao:5.1f}s)")
    else:
        print(cabecalho_resumo())
        resultados = _comparar_sequencial(cfgs, args.saida)

    for nome in PROTOCOLOS:
        if nome not in resultados:
            continue
        resumo, duracao, _ = resultados[nome]
        log.info("comparar: %s ted=%.2f%% lpa=%s transmissoes=%s tempo=%.1fs",
                 nome, resumo.get("ted_percentual") or 0.0,
                 resumo.get("lpa_minutos"), resumo.get("transmissoes"), duracao)
    if args.saida:
        print(f"\n  CSV gravados em {args.saida}")
    return 0


# ---------------------------------------------------------------------------
# 5. MODO: ANALISAR
# ---------------------------------------------------------------------------
def _horizonte_igual(texto: str, alvo: float) -> bool:
    """Compara o horizonte gravado no CSV com o filtro de linha de comando."""
    try:
        valor = float(texto)
    except (TypeError, ValueError):
        return False
    return abs(valor - alvo) <= 1e-6 * max(1.0, abs(alvo))


def modo_analisar(args) -> int:
    from flora_analise import (METRICAS_PADRAO, analisar, carregar_registros,
                               expandir_caminhos, gerar_diferencas, salvar, tabela_texto,
                               validar_consistencia)

    log = flora_log.obter_logger("analisar")
    metricas = None
    if args.metricas:
        metricas = [m.strip() for m in args.metricas.split(",") if m.strip()]
    else:
        metricas = list(METRICAS_PADRAO)

    caminhos = expandir_caminhos(args.entrada)
    for caminho in caminhos:
        if caminho.lower().endswith("_metricas.csv"):
            json_cand = caminho[:-len("_metricas.csv")] + "_simulacao.json"
            if os.path.isfile(json_cand):
                ok, diffs = validar_consistencia(caminho, json_cand)
                if not ok:
                    nomes = ", ".join(d[0] for d in diffs)
                    print(f"  aviso: inconsistencia entre "
                          f"{os.path.basename(caminho)} e "
                          f"{os.path.basename(json_cand)}: {nomes}")
                    log.warning("inconsistencia %s vs %s: %s", caminho, json_cand, diffs)
    registros = carregar_registros(caminhos)
    if args.cenario:
        registros = [r for r in registros if r.cenario == args.cenario]
    if args.horizonte is not None:
        registros = [r for r in registros
                     if _horizonte_igual(r.horizonte, args.horizonte)]

    resultado = analisar(registros, metricas=metricas, confianca=args.confianca)
    resultado["arquivos"] = caminhos
    if not resultado["n_registros"]:
        print("Nenhum arquivo de metricas encontrado em: " + ", ".join(args.entrada))
        log.warning("analisar: nenhum registro em %s", args.entrada)
        return 1

    combos = sorted({(r.cenario, r.horizonte) for r in registros})
    if len(combos) > 1:
        resumo_combos = ", ".join(f"{c}/{h}h" for c, h in combos[:6])
        print(f"  aviso: {len(combos)} combinacoes cenario/horizonte "
              f"({resumo_combos}{'...' if len(combos) > 6 else ''}); "
              f"use --cenario e --horizonte para comparar um unico regime.")
        log.warning("analisar: regimes misturados: %s", combos)

    print(f"Analise de {resultado['n_registros']} "
          f"{'execucao' if resultado['n_registros'] == 1 else 'execucoes'} | "
          f"protocolos: {', '.join(resultado['protocolos']) or 'nenhum'} | "
          f"IC {resultado['confianca'] * 100:g}% | "
          f"familia de {resultado['familia_testes']} teste(s) com Holm")
    print(tabela_texto(resultado))

    pasta = args.saida or os.path.join(RAIZ, "resultados", "analise")
    if getattr(args, "dry_run", False):
        print("  (dry-run: nenhum arquivo gravado)")
        return 0
    # IC95% da diferenca pareada entre protocolos
    difs = gerar_diferencas(registros, metricas or METRICAS_PADRAO, args.confianca)
    if difs:
        caminho_dif = os.path.join(pasta, "analise_estatistica_diferencas.csv")
        os.makedirs(pasta, exist_ok=True)
        with open(caminho_dif, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(difs[0].keys()))
            w.writeheader()
            w.writerows(difs)
        print(f"  gravado: {caminho_dif}")
    for caminho in salvar(resultado, pasta):
        print(f"  gravado: {caminho}")
        log.info("gravado: %s", caminho)
    if not resultado["familia_testes"]:
        print("\n  aviso: sem dados suficientes para teste de hipotese "
              "(precisa de 2+ protocolos e 2+ execucoes por protocolo).")
    return 0


def modo_artigo(args) -> int:
    import importlib.util

    log = flora_log.obter_logger("artigo")
    if getattr(args, "dry_run", False):
        args.sementes = 1
        args.horizonte = 0.1
        args.sem_log = True
    spec = importlib.util.spec_from_file_location(
        "gerar_tabelas_artigo",
        os.path.join(RAIZ, "scripts", "gerar_tabelas_artigo.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    argv = ["--sementes", str(args.sementes),
            "--horizonte", str(args.horizonte),
            "--saida", args.saida]
    if getattr(args, "trabalhadores", None):
        argv += ["--trabalhadores", str(args.trabalhadores)]
    if getattr(args, "densidades", None):
        argv += ["--densidades", str(args.densidades)]
    if getattr(args, "dry_run", False):
        argv.append("--dry-run")
    print(f"Gerando tabelas do artigo | sementes={args.sementes} | "
          f"horizonte={args.horizonte:g} h | saida={args.saida}")
    log.info("artigo: sementes=%d horizonte=%g saida=%s", args.sementes,
             args.horizonte, args.saida)
    return int(mod.main(argv) or 0)


# ---------------------------------------------------------------------------
# 6. MODO: CARTA
# ---------------------------------------------------------------------------
def modo_carta(args) -> int:
    from flora_cenario import obter_cenario
    from flora_mapa import CartaNautica, OpcoesCarta

    log = flora_log.obter_logger("carta")
    cenario = obter_cenario(args.cenario)
    t_h = args.instante
    motor = None
    if args.rodar is not None:
        from flora_dtn import ConfiguracaoDTN, MotorDTN

        cfg = ConfiguracaoDTN(cenario=args.cenario, protocolo=args.protocolo,
                              semente=args.semente, passo_s=args.passo)
        print(f"Simulando {args.rodar:g} h do cenario {args.cenario} "
              f"({args.protocolo}) antes de gerar a carta...")
        inicio = time.perf_counter()
        motor = MotorDTN(cfg).executar(args.rodar)
        print(f"  concluido em {time.perf_counter() - inicio:.1f}s; "
              f"t = {motor.t_s / 3600.0:.1f} h")
        t_h = motor.t_s / 3600.0

    opcoes = OpcoesCarta(
        escala=args.escala, legenda=not args.sem_legenda,
        quadro_metadados=not args.sem_metadados,
        base_carta=not args.base_satelite, base_satelite=args.base_satelite,
        curvas_batimetricas=not args.sem_curvas,
        sondagens=not args.sem_sondagens,
        relevo_sombreado=not args.sem_relevo,
        limites_canal=not args.sem_limites,
        batimetria=args.tinta_profundidade,
    )
    inicio = time.perf_counter()
    carta = CartaNautica(opcoes)
    img = carta.render(cenario, t_h, motor=motor)
    if getattr(args, "dry_run", False):
        print("dry-run: carta nao gravada")
        return 0
    caminho = carta.salvar(img, args.saida)
    print(f"Carta salva em {caminho} ({img.width}x{img.height} px, "
          f"{time.perf_counter() - inicio:.1f}s)")
    log.info("carta: cenario=%s t=%.2fh escala=%g saida=%s",
             args.cenario, t_h, args.escala, caminho)
    return 0


# ---------------------------------------------------------------------------
# 7. MODO: GUI
# ---------------------------------------------------------------------------
def modo_gui(args) -> int:
    if getattr(args, "dry_run", False):
        from flora_dtn import MotorDTN
        cfg = construir_cfg(args)
        motor = MotorDTN(cfg).executar()
        r = motor.resumo()
        print(f"dry-run: cenario {cfg.cenario} | protocolo {cfg.protocolo} | "
              f"horizonte {cfg.horizonte_h:g} h | TED {r.get('ted_percentual')}%")
        return 0
    from flora_ui import Aplicacao

    cfg = construir_cfg(args)
    flora_log.obter_logger("gui").info(
        "gui: cenario=%s protocolo=%s horizonte=%g semente=%d",
        cfg.cenario, cfg.protocolo, cfg.horizonte_h, cfg.semente)
    Aplicacao(cfg).executar()
    return 0


# ---------------------------------------------------------------------------
# 8. DESPACHANTE
# ---------------------------------------------------------------------------
def _configurar_log(args) -> str | None:
    if getattr(args, "sem_log", False):
        flora_log.desligar()
        return None
    nivel = logging.DEBUG if getattr(args, "verboso", False) else logging.INFO
    return flora_log.configurar(
        getattr(args, "log_arquivo", None),
        nivel=nivel,
        console=getattr(args, "log_console", False),
    )


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Sem subcomando a interface grafica e o padrao. As opcoes de ajuda e de
    # versao sao deixadas intactas para que `--help` e `--version` funcionem
    # antes de qualquer subcomando.
    if not argv or (argv[0].startswith("-")
                    and argv[0] not in ("-h", "--help", "-V", "--version")):
        argv = ["gui"] + argv
    args = parser.parse_args(argv)
    comando = args.comando or "gui"

    if getattr(args, "dry_run", False):
        args.sem_log = True
        if comando in ("rodar", "comparar", "gui", "carta", "artigo"):
            if hasattr(args, "horizonte"):
                args.horizonte = 0.1
            if hasattr(args, "semente"):
                args.semente = 20260826
            if hasattr(args, "sementes"):
                args.sementes = 1

    # O banner e o log valem para todos os modos, inclusive a GUI.
    print(flora_versao.banner())
    caminho_log = _configurar_log(args)
    log = flora_log.obter_logger()
    log.info("inicio: %s", flora_versao.versao_completa())
    log.info("comando=%s args=%s", comando, vars(args))
    if caminho_log:
        log.debug("log em %s", caminho_log)

    codigo = 1
    try:
        codigo = {
            "gui": modo_gui,
            "rodar": modo_rodar,
            "carta": modo_carta,
            "comparar": modo_comparar,
            "analisar": modo_analisar,
            "artigo": modo_artigo,
        }[comando](args)
    except Exception:
        log.exception("falha no comando %s", comando)
        raise
    finally:
        log.info("fim: comando=%s codigo=%s", comando, codigo)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
