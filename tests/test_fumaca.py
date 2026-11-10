# -*- coding: utf-8 -*-
"""
Testes de fumaca do FLoRA-DTN.

Objetivo: em poucos segundos, provar que os caminhos de entrada continuam de
pe funcionando, sem validar o modelo fisico (isso e papel da suite principal em
``test_simulador.py``):

* ``--version`` responde com versao e commit;
* ``rodar`` grava CSV e log;
* ``comparar --paralelo`` roda os cinco protocolos e grava um conjunto por
  protocolo;
* ``analisar`` le os CSV, aplica os testes e grava o resultado;
* o resolvedor de commit aceita ``FLORA_COMMIT`` e degrada sem git.

Rodar com:

    python -m pytest tests/test_fumaca.py
"""

from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import dtn_simulador as cli
import flora_analise
import flora_log
import flora_versao

PROTOCOLOS_SINTETICOS = ("epidemico", "spray", "flora", "slp", "sc")


# ---------------------------------------------------------------------------
# 1. VERSAO
# ---------------------------------------------------------------------------
def test_version_mostra_versao_e_commit(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    saida = capsys.readouterr().out
    assert flora_versao.VERSAO in saida
    assert "commit" in saida


def test_version_pelo_executavel():
    resultado = subprocess.run(
        [sys.executable, os.path.join(RAIZ, "dtn_simulador.py"), "--version"],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert resultado.returncode == 0
    assert flora_versao.VERSAO in resultado.stdout
    assert "commit" in resultado.stdout


def test_commit_por_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("FLORA_COMMIT", "abc123def456789")
    assert flora_versao.resolver_commit() == "abc123def456"


def test_commit_degrada_sem_git_e_sem_arquivo(monkeypatch, tmp_path):
    monkeypatch.delenv("FLORA_COMMIT", raising=False)
    assert (flora_versao.resolver_commit(raiz=str(tmp_path))
            == flora_versao.COMMIT_DESCONHECIDO)
    assert flora_versao.versao_completa().startswith(flora_versao.NOME)


# ---------------------------------------------------------------------------
# 2. RODAR E LOG
# ---------------------------------------------------------------------------
def test_rodar_grava_csv_e_log(tmp_path):
    log = tmp_path / "execucao.log"
    codigo = cli.main([
        "rodar", "-c", "C1", "-p", "slp", "-H", "0.2", "-s", "7",
        "-o", str(tmp_path), "--log-arquivo", str(log),
    ])
    assert codigo == 0

    metricas = sorted(tmp_path.glob("*_metricas.csv"))
    assert len(metricas) == 1
    with open(metricas[0], newline="", encoding="utf-8-sig") as fh:
        linhas = list(csv.DictReader(fh))
    assert linhas and linhas[0]["protocolo"] == "slp"

    assert log.exists()
    texto = log.read_text(encoding="utf-8")
    assert "FLoRA-DTN" in texto
    assert "rodar concluido" in texto

    completos = sorted(tmp_path.glob("*_simulacao.json"))
    assert len(completos) == 1
    with open(completos[0], encoding="utf-8") as fh:
        dados = json.load(fh)
    assert dados["formato"] == "flora-dtn-simulacao"
    assert dados["resumo"]["protocolo"] == "slp"
    assert dados["configuracao"]["semente"] == 7
    assert dados["frota"]
    # Series horarias so existem a partir de 1 h; o teste de 1 h cobre o
    # conteudo, aqui basta garantir que a secao esta presente.
    assert "ted" in dados["series"]


def test_rodar_sem_completo_nao_gera_json(tmp_path):
    codigo = cli.main([
        "rodar", "-c", "C1", "-p", "slp", "-H", "0.2", "-s", "7",
        "-o", str(tmp_path), "--sem-completo", "--sem-log",
    ])
    assert codigo == 0
    assert not list(tmp_path.glob("*_simulacao.json"))


def test_log_padrao_cria_arquivo(tmp_path):
    caminho = flora_log.configurar(pasta=str(tmp_path))
    assert caminho is not None
    assert os.path.exists(caminho)
    flora_log.obter_logger("teste").info("mensagem de fumaca")
    with open(caminho, encoding="utf-8") as fh:
        assert "mensagem de fumaca" in fh.read()


# ---------------------------------------------------------------------------
# 3. COMPARAR EM PARALELO
# ---------------------------------------------------------------------------
def test_comparar_paralelo_gera_os_cinco_protocolos(tmp_path):
    codigo = cli.main([
        "comparar", "-c", "C1", "-H", "0.2", "--paralelo",
        "--trabalhadores", "2", "-o", str(tmp_path), "--sem-log",
    ])
    assert codigo == 0

    encontrados = {
        caminho.name.split("_")[1]
        for caminho in tmp_path.glob("*_metricas.csv")
    }
    assert encontrados == set(cli.PROTOCOLOS)
    assert len(list(tmp_path.glob("*.csv"))) == 10  # metricas + frota por protocolo


# ---------------------------------------------------------------------------
# 4. ANALISAR
# ---------------------------------------------------------------------------
def _gerar_metricas(pasta, sementes=(1, 2, 3, 4, 5), protocolos=PROTOCOLOS_SINTETICOS):
    """CSV sinteticos com diferenca clara entre protocolos e blocos pareados."""
    rng = random.Random(11)
    base = {"epidemico": 70.0, "spray": 78.0, "flora": 92.0, "slp": 74.0, "sc": 72.0}
    campos = ["cenario", "protocolo", "semente", "tempo_simulado_h",
              "ted_percentual", "lpa_minutos", "overhead_copias", "transmissoes"]
    for semente in sementes:
        for protocolo in protocolos:
            ted = base[protocolo] + rng.gauss(0, 2.0)
            caminho = os.path.join(
                pasta, f"C3_{protocolo}_168h_s{semente}_metricas.csv"
            )
            with open(caminho, "w", newline="", encoding="utf-8-sig") as fh:
                escritor = csv.DictWriter(fh, fieldnames=campos)
                escritor.writeheader()
                escritor.writerow({
                    "cenario": "C3", "protocolo": protocolo, "semente": semente,
                    "tempo_simulado_h": 168.0,
                    "ted_percentual": round(ted, 3),
                    "lpa_minutos": round(60.0 - (ted - 70.0) * 1.2, 3),
                    "overhead_copias": round(1.0 + rng.random(), 3),
                    "transmissoes": int(2000 + ted * 20),
                })
    return pasta


def test_analisar_escolhe_friedman_e_aplica_holm(tmp_path):
    _gerar_metricas(tmp_path)
    resultado = flora_analise.analisar_caminhos([str(tmp_path)])

    assert resultado["n_registros"] == 25
    ted = resultado["metricas"]["ted_percentual"]
    assert ted["teste"]["nome"] == "friedman"
    assert ted["teste"]["p"] < 0.01
    assert ted["teste"]["p_holm"] is not None
    assert ted["teste"]["p_holm"] >= ted["teste"]["p"]
    for protocolo in PROTOCOLOS_SINTETICOS:
        grupo = ted["grupos"][protocolo]
        assert grupo["n"] == 5
        assert grupo["ic95_inf"] < grupo["media"] < grupo["ic95_sup"]


def test_analisar_pela_linha_de_comando(tmp_path, capsys):
    _gerar_metricas(tmp_path)
    destino = tmp_path / "analise"
    codigo = cli.main([
        "analisar", "-e", str(tmp_path), "-o", str(destino), "--sem-log",
    ])
    assert codigo == 0
    assert (destino / "analise_estatistica.csv").exists()
    assert (destino / "analise_estatistica.json").exists()
    assert "friedman" in capsys.readouterr().out


def test_analisar_usa_anova_quando_nao_ha_blocos_pareados():
    registros = []
    for protocolo, base in (("flora", 90.0), ("sc", 70.0)):
        for semente in range(4):
            # Sementes disjuntas entre protocolos: nao ha bloco comum, entao
            # o teste correto e a ANOVA de um fator, nao Friedman.
            registros.append(flora_analise.Registro(
                protocolo=protocolo, cenario="C1",
                semente=str(semente + (0 if protocolo == "flora" else 100)),
                horizonte="168.0",
                valores={"ted_percentual": base + semente},
            ))
    resultado = flora_analise.analisar(registros, metricas=["ted_percentual"])
    teste = resultado["metricas"]["ted_percentual"]["teste"]
    assert teste["nome"] == "anova"
    assert teste["p"] < 0.01
    assert teste["p_holm"] is not None


def test_analisar_le_o_json_completo_e_nao_duplica_a_execucao(tmp_path):
    codigo = cli.main([
        "rodar", "-c", "C1", "-p", "slp", "-H", "0.2", "-s", "9",
        "-o", str(tmp_path), "--sem-log",
    ])
    assert codigo == 0
    completo = next(tmp_path.glob("*_simulacao.json"))

    # O JSON sozinho e um registro valido de metricas.
    resultado = flora_analise.analisar_caminhos([str(completo)])
    assert resultado["n_registros"] == 1
    assert resultado["protocolos"] == ["slp"]
    assert resultado["metricas"]["ted_percentual"]["grupos"]["slp"]["n"] == 1

    # Na pasta, CSV e JSON sao a mesma execucao: conta uma vez.
    resultado_pasta = flora_analise.analisar_caminhos([str(tmp_path)])
    assert resultado_pasta["n_registros"] == 1


def test_holm_preserva_ordem_e_limita_a_um():
    brutos = [0.04, None, 0.01, 0.2]
    ajustados = flora_analise.holm(brutos)
    assert ajustados[1] is None
    assert ajustados[2] <= ajustados[0] <= ajustados[3]
    assert all(a is None or 0.0 <= a <= 1.0 for a in ajustados)


# ---------------------------------------------------------------------------
# 5. IMPORTACOES E CLI
# ---------------------------------------------------------------------------
def test_modulos_importam_sem_pygame():
    import flora_analise
    import flora_cenario
    import flora_dtn
    import flora_geometria
    import flora_log
    import flora_lora
    import flora_versao

    for modulo in (flora_analise, flora_cenario, flora_dtn, flora_geometria,
                   flora_log, flora_lora, flora_versao):
        assert modulo.__name__.startswith("flora_")


def test_ajuda_geral_lista_os_cinco_modos(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    texto = capsys.readouterr().out
    for modo in ("gui", "rodar", "carta", "comparar", "analisar"):
        assert modo in texto
