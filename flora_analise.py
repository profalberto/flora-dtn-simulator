# -*- coding: utf-8 -*-
"""
flora_analise.py
================

Analise estatistica agregada das execucoes do simulador FLoRA-DTN.

Le os ``*_metricas.csv`` (ou ``.json``, inclusive o JSON unico gerado por
``MotorDTN.exportar_simulacao``) gravados pelos modos ``rodar`` e ``comparar``
e, para cada metrica, devolve:

* tamanho da amostra, media, desvio padrao e intervalo de confianca de 95%
  (distribuicao t de Student, adequada a amostras pequenas);
* normalidade por Shapiro-Wilk;
* comparacao entre protocolos por ANOVA de um fator, quando as amostras sao
  independentes, ou por Friedman, quando o mesmo bloco
  (cenario, semente e horizonte) foi medido em todos os protocolos;
* correcao de Holm sobre todos os p-valores da familia de metricas, porque
  testar oito metricas sem correcao infla o erro tipo I.

O modulo nao depende de pandas: usa a biblioteca padrao para ler os CSV e
``scipy.stats`` apenas para os testes. As funcoes de teste carregam o scipy
sob demanda, de modo que importar `flora_analise` continua barato.
"""

from __future__ import annotations

import csv
import glob
import json
import math
import os
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

#: Metricas comparadas por padrao. Sao as que respondem a pergunta do
#: experimento: entrega, latencia, cobertura, convergencia, custo e energia.
METRICAS_PADRAO = (
    "ted_percentual",
    "ted_no_horizonte_percentual",
    "lpa_minutos",
    "car_percentual",
    "tci_horas",
    "overhead_copias",
    "transmissoes",
    "energia_total_j",
)

#: Colunas obrigatorias para reconhecer um CSV de metricas.
COLUNAS_OBRIGATORIAS = ("protocolo", "cenario", "semente")

#: Coluna de horizonte usada para casar os blocos entre protocolos.
COLUNA_HORIZONTE = "tempo_simulado_h"


@dataclass
class Registro:
    """Uma linha de metrica de uma execucao."""

    protocolo: str
    cenario: str
    semente: str
    horizonte: str
    valores: dict[str, float]


# ---------------------------------------------------------------------------
# 1. LEITURA
# ---------------------------------------------------------------------------
def expandir_caminhos(entradas: Iterable[str]) -> list[str]:
    """Expande pastas, globs e arquivos para uma lista unica de caminhos."""
    achados: list[str] = []
    for entrada in entradas:
        if os.path.isdir(entrada):
            csvs = sorted(glob.glob(os.path.join(entrada, "*.csv")))
            jsons = sorted(glob.glob(os.path.join(entrada, "*.json")))
            # Uma execucao gravada com `rodar` gera tanto o CSV de metricas
            # quanto o JSON completo. Na leitura de uma pasta, o JSON so entra
            # quando nao ha o CSV correspondente, para nao contar a mesma
            # execucao duas vezes.
            bases_csv = {
                os.path.basename(c)[:-len("_metricas.csv")]
                for c in csvs if c.endswith("_metricas.csv")
            }
            candidatos = list(csvs)
            for caminho in jsons:
                nome = os.path.basename(caminho)
                if (nome.endswith("_simulacao.json")
                        and nome[:-len("_simulacao.json")] in bases_csv):
                    continue
                candidatos.append(caminho)
        elif any(ch in entrada for ch in "*?["):
            candidatos = sorted(glob.glob(entrada))
        else:
            candidatos = [entrada]
        for caminho in candidatos:
            if caminho not in achados:
                achados.append(caminho)
    return achados


def carregar_registros(caminhos: Iterable[str]) -> list[Registro]:
    """
    Le metricas de CSV e JSON, ignorando arquivos que nao sejam de metricas.

    A codificacao ``utf-8-sig`` cobre os CSV gravados pelo proprio simulador,
    que usa BOM para abrir corretamente no Excel.
    """
    registros: list[Registro] = []
    for caminho in expandir_caminhos(caminhos):
        if not os.path.isfile(caminho):
            continue
        if caminho.lower().endswith(".json"):
            registros.extend(_ler_json(caminho))
        elif caminho.lower().endswith(".csv"):
            registros.extend(_ler_csv(caminho))
    return registros


def _converter(valor) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        numero = float(valor)
    else:
        texto = str(valor).strip()
        if not texto:
            return None
        try:
            numero = float(texto)
        except ValueError:
            return None
    if math.isnan(numero) or math.isinf(numero):
        return None
    return numero


def validar_consistencia(caminho_csv: str, caminho_json: str,
                        tolerancia: float = 0.001) -> tuple[bool, list[tuple]]:
    """
    Compara um ``_metricas.csv`` com o ``_simulacao.json`` da mesma execucao.

    Devolve ``(True, [])`` se tudo estiver dentro da tolerancia relativa e
    ``(False, divergencias)`` caso contrario. Cada divergencia e uma tupla
    ``(campo, valor_csv, valor_json)``.
    """
    divergencias: list[tuple] = []
    with open(caminho_csv, newline="", encoding="utf-8-sig") as fh:
        linhas = list(csv.DictReader(fh))
    with open(caminho_json, encoding="utf-8") as fh:
        dados = json.load(fh)
    resumo = dados.get("resumo", dados)

    if len(linhas) != 1:
        divergencias.append(("linhas", len(linhas), 1))
        return False, divergencias
    linha = linhas[0]

    def comparar_campo(campo_csv: str, campo_json: str) -> None:
        valor_csv = linha.get(campo_csv)
        if valor_csv == "":
            valor_csv = None
        valor_json = resumo.get(campo_json, resumo.get(campo_csv))
        if valor_csv is None or valor_json is None:
            if valor_csv != valor_json and not (valor_csv is None and valor_json is None):
                # empty string vs None are equivalent
                if not (valor_csv in (None, "") and valor_json in (None, "")):
                    divergencias.append((campo_csv, valor_csv, valor_json))
            return
        try:
            a = float(valor_csv)
            b = float(valor_json)
        except (TypeError, ValueError):
            if str(valor_csv) != str(valor_json):
                divergencias.append((campo_csv, valor_csv, valor_json))
            return
        if b == 0:
            if abs(a - b) > tolerancia:
                divergencias.append((campo_csv, a, b))
        else:
            if abs(a - b) / max(abs(b), 1e-12) > tolerancia:
                divergencias.append((campo_csv, a, b))

    for campo in ("protocolo", "cenario", "semente"):
        if str(linha.get(campo)) != str(resumo.get(campo)):
            divergencias.append((campo, linha.get(campo), resumo.get(campo)))

    csv_horizonte = linha.get(COLUNA_HORIZONTE)
    json_horizonte = resumo.get(COLUNA_HORIZONTE, resumo.get("horizonte_h"))
    if csv_horizonte is not None and json_horizonte is not None:
        comparar_campo(COLUNA_HORIZONTE, COLUNA_HORIZONTE)
        if COLUNA_HORIZONTE not in resumo and "horizonte_h" in resumo:
            comparar_campo(COLUNA_HORIZONTE, "horizonte_h")

    for campo in ("ted_percentual", "lpa_minutos", "car_percentual",
                  "tci_horas", "transmissoes"):
        comparar_campo(campo, campo)

    return (len(divergencias) == 0, divergencias)


def _registro_de_linha(linha: dict) -> Registro | None:
    # O JSON completo do modo `exportar_simulacao` guarda as metricas em
    # ``resumo``; achatar aqui deixa o mesmo leitor servir aos CSV e ao JSON.
    resumo = linha.get("resumo")
    if isinstance(resumo, dict):
        linha = {**linha, **resumo}
    if not all(coluna in linha for coluna in COLUNAS_OBRIGATORIAS):
        return None
    # O `_config.json` de cada execucao tambem tem protocolo, cenario, semente
    # e `horizonte_h`; so o CSV de metricas (e o JSON completo, que achata o
    # resumo) traz `tempo_simulado_h`. Exigir essa coluna separa metadados de
    # metricas de verdade.
    if COLUNA_HORIZONTE not in linha:
        return None
    protocolo = str(linha.get("protocolo") or "").strip()
    if not protocolo:
        return None
    horizonte = str(linha.get(COLUNA_HORIZONTE) or linha.get("horizonte_h") or "").strip()
    valores: dict[str, float] = {}
    for chave, bruto in linha.items():
        numero = _converter(bruto)
        if numero is not None:
            valores[str(chave)] = numero
    return Registro(
        protocolo=protocolo,
        cenario=str(linha.get("cenario") or "").strip(),
        semente=str(linha.get("semente") or "").strip(),
        horizonte=horizonte,
        valores=valores,
    )


def _ler_csv(caminho: str) -> list[Registro]:
    try:
        with open(caminho, newline="", encoding="utf-8-sig") as fh:
            linhas = list(csv.DictReader(fh))
    except OSError:
        return []
    registros = []
    for linha in linhas:
        registro = _registro_de_linha(linha)
        if registro is not None:
            registros.append(registro)
    return registros


def _ler_json(caminho: str) -> list[Registro]:
    try:
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
    except (OSError, ValueError):
        return []
    if isinstance(dados, dict):
        dados = [dados]
    if not isinstance(dados, list):
        return []
    registros = []
    for linha in dados:
        if isinstance(linha, dict):
            registro = _registro_de_linha(linha)
            if registro is not None:
                registros.append(registro)
    return registros


# ---------------------------------------------------------------------------
# 2. ESTATISTICA DESCRITIVA
# ---------------------------------------------------------------------------
def intervalo_confianca(
    valores: Sequence[float], confianca: float = 0.95
) -> tuple[float | None, float | None]:
    """IC pela t de Student; devolve ``(None, None)`` com menos de dois dados."""
    if len(valores) < 2:
        return (None, None)
    from scipy import stats

    media = statistics.fmean(valores)
    erro = statistics.stdev(valores) / math.sqrt(len(valores))
    t_critico = stats.t.ppf(0.5 + confianca / 2.0, len(valores) - 1)
    return (media - t_critico * erro, media + t_critico * erro)


def resumo_descritivo(valores: Sequence[float], confianca: float = 0.95) -> dict:
    """Media, desvio, minimo, maximo e IC95% de uma amostra."""
    if not valores:
        return {"n": 0, "media": None, "desvio": None, "minimo": None,
                "maximo": None, "ic95_inf": None, "ic95_sup": None}
    media = statistics.fmean(valores)
    desvio = statistics.stdev(valores) if len(valores) >= 2 else 0.0
    inferior, superior = intervalo_confianca(valores, confianca)
    return {
        "n": len(valores),
        "media": media,
        "desvio": desvio,
        "minimo": min(valores),
        "maximo": max(valores),
        "ic95_inf": inferior,
        "ic95_sup": superior,
    }


def shapiro(valores: Sequence[float]) -> dict:
    """Shapiro-Wilk; exige ao menos tres observacoes distintas."""
    if len(valores) < 3 or len(set(valores)) < 2:
        return {"w": None, "p": None}
    from scipy import stats

    resultado = stats.shapiro(list(valores))
    return {"w": float(resultado.statistic), "p": float(resultado.pvalue)}


# ---------------------------------------------------------------------------
# 3. TESTES ENTRE PROTOCOLOS
# ---------------------------------------------------------------------------
def _blocos(registros: Sequence[Registro], metrica: str) -> tuple[dict[str, dict[str, float]], set[str]]:
    """
    Mapa protocolo -> chave do bloco -> valor, e o conjunto de protocolos
    que repetiram um bloco (e portanto nao sao emparelhavel).

    A chave e o par (cenario, semente, horizonte): o mesmo experimento rodado
    em protocolos diferentes. Quando um protocolo repete a mesma chave, o
    ultimo valor prevalece, mas o protocolo e marcado como nao emparelhavel.
    """
    dados: dict[str, dict[str, float]] = {}
    duplicados: set[str] = set()
    for registro in registros:
        valor = registro.valores.get(metrica)
        if valor is None:
            continue
        chave = f"{registro.cenario}|{registro.semente}|{registro.horizonte}"
        protocolo = registro.protocolo
        alvo = dados.setdefault(protocolo, {})
        if chave in alvo:
            duplicados.add(protocolo)
        alvo[chave] = valor
    return dados, duplicados


def comparar_protocolos(
    registros: Sequence[Registro], metrica: str
) -> dict:
    """
    Escolhe e executa o teste adequado para uma metrica.

    Friedman quando ha tres ou mais protocolos com os mesmos blocos completos;
    ANOVA de um fator caso contrario, desde que haja dois grupos com ao menos
    duas observacoes. Sem condicoes, devolve ``teste=None``.
    """
    por_protocolo, duplicados = _blocos(registros, metrica)
    protocolos = list(por_protocolo)
    grupos = {
        protocolo: [v for k, v in valores.items() if k != "__duplicado__"]
        for protocolo, valores in por_protocolo.items()
    }

    emparelhado = (
        len(protocolos) >= 3
        and not duplicados
    )
    if emparelhado:
        chaves = set.intersection(*[set(por_protocolo[p]) for p in protocolos])
        if len(chaves) >= 2:
            listas = [[por_protocolo[p][chave] for chave in sorted(chaves)]
                      for p in protocolos]
            # Friedman divide pela variancia dos postos e devolve NaN quando
            # todos os valores sao iguais (por exemplo, CAR saturado em 100%).
            # Nesse caso nao ha efeito a testar, e o scipy ainda emitiria um
            # aviso de divisao por zero no stderr.
            valores = [v for lista in listas for v in lista]
            if max(valores) == min(valores):
                return {"nome": None, "estatistica": None, "p": None,
                        "n_blocos": len(chaves), "protocolos": protocolos,
                        "tamanho_efeito": None}
            try:
                from scipy import stats

                estat, p = stats.friedmanchisquare(*listas)
                k = len(protocolos)
                n_blocos = len(chaves)
                tamanho_efeito = (float(estat) / (n_blocos * (k - 1))
                                  if n_blocos > 0 and k > 1 else None)
                return {
                    "nome": "friedman",
                    "estatistica": float(estat),
                    "p": float(p),
                    "n_blocos": n_blocos,
                    "protocolos": protocolos,
                    "tamanho_efeito": tamanho_efeito,
                }
            except ValueError:
                pass

    usaveis = [p for p in protocolos if len(grupos[p]) >= 2]
    if len(usaveis) >= 2:
        try:
            from scipy import stats

            estat, p = stats.f_oneway(*[grupos[p] for p in usaveis])
            k = len(usaveis)
            n = max(len(grupos[p]) for p in usaveis)
            df_between = k - 1
            df_within = n * k - k
            tamanho_efeito = ((float(estat) * df_between)
                              / (float(estat) * df_between + df_within)
                              if df_within > 0 else None)
            return {
                "nome": "anova",
                "estatistica": float(estat),
                "p": float(p),
                "n_blocos": n,
                "protocolos": usaveis,
                "tamanho_efeito": tamanho_efeito,
            }
        except ValueError:
            pass

    return {"nome": None, "estatistica": None, "p": None, "n_blocos": 0,
            "protocolos": protocolos, "tamanho_efeito": None}


# ---------------------------------------------------------------------------
# 4. HOLM
# ---------------------------------------------------------------------------
def holm(pvalores: Sequence[float | None]) -> list[float | None]:
    """
    Correcao de Holm-Bonferroni, preservando a ordem original.

    Os ``None`` sao ignorados no calculo e devolvidos como ``None``. A familia
    de testes e, por decisao do modo ``analisar``, o conjunto de metricas de
    uma mesma chamada.
    """
    indices = [i for i, p in enumerate(pvalores) if p is not None]
    if not indices:
        return [None] * len(pvalores)
    ordenados = sorted(indices, key=lambda i: pvalores[i])  # type: ignore[arg-type]
    total = len(ordenados)
    ajustados: list[float | None] = [None] * len(pvalores)
    anterior = 0.0
    for posicao, indice in enumerate(ordenados):
        bruto = float(pvalores[indice])  # type: ignore[arg-type]
        ajustado = min(1.0, (total - posicao) * bruto)
        anterior = max(anterior, ajustado)
        ajustados[indice] = anterior
    return ajustados


# ---------------------------------------------------------------------------
# 5. AGREGADO
# ---------------------------------------------------------------------------
def analisar(
    registros: Sequence[Registro],
    metricas: Sequence[str] | None = None,
    confianca: float = 0.95,
) -> dict:
    """Monta o resultado completo, com Holm aplicado sobre todas as metricas."""
    pedidas = list(metricas or METRICAS_PADRAO)
    presentes = {chave for r in registros for chave in r.valores}
    metricas_efetivas = [m for m in pedidas if m in presentes]

    resultado: dict = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "n_registros": len(registros),
        "protocolos": sorted({r.protocolo for r in registros}),
        "metricas": {},
    }

    pvalores: list[float] = []
    for metrica in metricas_efetivas:
        por_protocolo: dict[str, list[float]] = {}
        for registro in registros:
            valor = registro.valores.get(metrica)
            if valor is not None:
                por_protocolo.setdefault(registro.protocolo, []).append(valor)
        grupos = {
            protocolo: {**resumo_descritivo(valores, confianca), **shapiro(valores)}
            for protocolo, valores in sorted(por_protocolo.items())
        }
        teste = comparar_protocolos(registros, metrica)
        resultado["metricas"][metrica] = {"grupos": grupos, "teste": teste}
        if teste["p"] is not None and not math.isnan(teste["p"]):
            pvalores.append({"metrica": metrica, "p": teste["p"]})

    ajustados = holm([item["p"] for item in pvalores])
    for item, ajustado in zip(pvalores, ajustados):
        resultado["metricas"][item["metrica"]]["teste"]["p_holm"] = ajustado
    for metrica in metricas_efetivas:
        resultado["metricas"][metrica]["teste"].setdefault("p_holm", None)

    resultado["familia_testes"] = len(pvalores)
    resultado["confianca"] = confianca
    return resultado


def analisar_caminhos(
    entradas: Iterable[str],
    metricas: Sequence[str] | None = None,
    confianca: float = 0.95,
) -> dict:
    """Atalho: expande, le e analisa em uma chamada."""
    caminhos = expandir_caminhos(entradas)
    registros = carregar_registros(caminhos)
    resultado = analisar(registros, metricas=metricas, confianca=confianca)
    resultado["arquivos"] = caminhos
    return resultado


# ---------------------------------------------------------------------------
# 6. SAIDA
# ---------------------------------------------------------------------------
def _num(valor, casas: int = 3) -> str:
    if valor is None:
        return "n/a"
    if isinstance(valor, float) and math.isnan(valor):
        return "n/a"
    return f"{valor:.{casas}f}"


def tabela_texto(resultado: dict) -> str:
    """Tabela de largura fixa para o terminal."""
    linhas: list[str] = []
    for metrica, dados in resultado["metricas"].items():
        linhas.append(f"\n{metrica}")
        linhas.append(
            f"{'protocolo':<14}{'n':>4}{'media':>11}{'desvio':>11}"
            f"{'IC95%':>22}{'Shapiro p':>12}"
        )
        for protocolo, grupo in dados["grupos"].items():
            ic = (f"[{_num(grupo['ic95_inf'], 2)}, {_num(grupo['ic95_sup'], 2)}]"
                  if grupo["ic95_inf"] is not None else "n/a")
            linhas.append(
                f"{protocolo:<14}{grupo['n']:>4}{_num(grupo['media'], 2):>11}"
                f"{_num(grupo['desvio'], 2):>11}{ic:>22}"
                f"{_num(grupo['p'], 4):>12}"
            )
        teste = dados["teste"]
        if teste["nome"]:
            linhas.append(
                f"  {teste['nome']}: estatistica={_num(teste['estatistica'], 4)}"
                f"  p={_num(teste['p'], 6)}  p_Holm={_num(teste['p_holm'], 6)}"
                f"  blocos={teste['n_blocos']}"
            )
        else:
            linhas.append("  teste: dados insuficientes (n<2 por protocolo ou <2 protocolos)")
    return "\n".join(linhas)


def linhas_csv(resultado: dict) -> list[dict]:
    """Formato longo, uma linha por (metrica, protocolo)."""
    linhas = []
    for metrica, dados in resultado["metricas"].items():
        teste = dados["teste"]
        for protocolo, grupo in dados["grupos"].items():
            linhas.append({
                "metrica": metrica,
                "protocolo": protocolo,
                "n": grupo["n"],
                "media": grupo["media"],
                "desvio": grupo["desvio"],
                "minimo": grupo["minimo"],
                "maximo": grupo["maximo"],
                "ic95_inf": grupo["ic95_inf"],
                "ic95_sup": grupo["ic95_sup"],
                "shapiro_w": grupo["w"],
                "shapiro_p": grupo["p"],
                "teste": teste["nome"],
                "teste_estatistica": teste["estatistica"],
                "teste_p": teste["p"],
                "teste_p_holm": teste.get("p_holm"),
                "n_blocos": teste["n_blocos"],
            })
    return linhas


def salvar(resultado: dict, pasta: str, prefixo: str = "analise_estatistica") -> list[str]:
    """Grava ``<prefixo>.csv`` e ``<prefixo>.json`` na pasta indicada."""
    os.makedirs(pasta, exist_ok=True)
    caminho_csv = os.path.join(pasta, f"{prefixo}.csv")
    caminho_json = os.path.join(pasta, f"{prefixo}.json")

    linhas = linhas_csv(resultado)
    campos = list(linhas[0]) if linhas else ["metrica", "protocolo"]
    with open(caminho_csv, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=campos)
        writer.writeheader()
        writer.writerows(linhas)

    with open(caminho_json, "w", encoding="utf-8") as fh:
        json.dump(resultado, fh, indent=2, ensure_ascii=False)
    return [caminho_csv, caminho_json]
