"""
flora_osm.py
============

Leitor da geometria real do rio, gravada por `baixar_osm.py`.

O canal modelado nao e um desenho: antes era um spline que passava pelos
marcos, e o resultado era uma linha quase reta de Manaus a Itacoatiara, com
razao reta/percurso de 0,998. A causa e matematica, nao artistica: quatro ou
cinco marcos com distancia de dezenas de kilometros entre si, e uma spline
suave por cima, tem o que fazer e ir em linha. O resultado era bonito e falso.

Este modulo le o cache vetorial do OpenStreetMap e devolve o eixo real. A
separacao de responsabilidade fica assim:

* `baixar_osm.py` e o unico ponto do projeto que precisa de rede. Consulta a
  Overpass, costura os trechos e grava `dados_osm/eixo_rio.json`.
* este modulo so le o arquivo. Nao abre socket, nao pede token e nao falha se o
  cache faltar.

Se o cache nao existir ou vier invalido, `carregar_eixo` devolve `None` e o
simulador cai no spline antigo. O fallback e deliberado: e melhor um rio
sintetico do que um programa que nao abre.

Atribuicao
----------
O dado e do OpenStreetMap, sob ODbL 1.0. A ODbL exige credito aoDerivado, e
`ATRIBUICAO` precisa acompanhar qualquer imagem exportada. Ver
`credito_carta()`.
"""

from __future__ import annotations

import json
import os

import numpy as np

#: Caminho do cache, relativo a este arquivo, para funcionar de qualquer
#: diretorio de trabalho.
PASTA_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados_osm")
ARQUIVO_EIXO = os.path.join(PASTA_DADOS, "eixo_rio.json")

#: Credito que a ODbL 1.0 exige em obra derivada. Aparece no rodape da carta
#: exportada e no CSV.
ATRIBUICAO = ("Geometria do rio: © OpenStreetMap contributors, "
              "ODbL 1.0, via Overpass API")

#: Quantos pontos a polilinha pode ter antes de ser considerada invalida. Um
#: arquivo com dois pontos e um trecho, nao um eixo de rio.
_MIN_PONTOS = 8


class CacheInvalido(Exception):
    """O cache existe mas nao tem um eixo utilizavel."""


def credito_carta() -> str:
    """Linha de credito para a carta exportada, ou vazio se nao ha cache."""
    if not os.path.exists(ARQUIVO_EIXO):
        return ""
    return ATRIBUICAO


def tem_cache() -> bool:
    """Se existe cache na leitura, sem abrir o arquivo."""
    return os.path.exists(ARQUIVO_EIXO)


def _linha_por_canal(doc: dict, canal: str) -> dict:
    for feat in doc.get("features", ()):
        props = feat.get("properties", {})
        if props.get("canal") != canal:
            continue
        geom = feat.get("geometry", {})
        if geom.get("type") != "LineString":
            raise CacheInvalido(
                f"canal {canal!r} tem geometria {geom.get('type')!r}, "
                "esperado 'LineString'")
        return feat
    raise CacheInvalido(f"o cache nao tem linha para o canal {canal!r}")


def carregar_eixo(canal: str = "principal", caminho: str | None = None):
    """
    Le o eixo de um canal do cache e devolve `(lat, lon)` em array numpy.

    Devolve `None` quando nao ha cache. Devolve `None` tambem quando o cache
    existe mas esta invalido, e avisa no `stderr`: um cache corrompido que passa
    em silencio seria pior do que um cache ausente, porque o programa rodaria
    com a geometria antiga sem ninguem saber.

    O que nao volta: interpolar, suavizar ou estender. O eixo e o que o OSM
    mediu, e qualquer ponto acrescentado aqui seria invencao com aparencia de
    dado. A unica manipulacao feita e a orientacao da polilinha, para o percurso
    correr sempre de Manaus para Itacoatiara.
    """
    if caminho is None:
        caminho = ARQUIVO_EIXO
    if not os.path.exists(caminho):
        return None

    try:
        with open(caminho, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        _avisar(f"cache do OSM ilegivel em {caminho}: {exc}")
        return None

    try:
        feat = _linha_por_canal(doc, canal)
    except CacheInvalido as exc:
        _avisar(f"cache do OSM sem eixo utilizavel: {exc}")
        return None

    coords = feat["geometry"]["coordinates"]
    if len(coords) < _MIN_PONTOS:
        _avisar(f"eixo {canal!r} tem so {len(coords)} pontos; "
                f"minimo e {_MIN_PONTOS}")
        return None

    # GeoJSON e (lon, lat); o resto do projeto e (lat, lon). A inversao e feita
    # uma vez aqui para ninguem no simulador precisar saber disso.
    arr = np.asarray(coords, dtype=float)
    if not np.isfinite(arr).all():
        _avisar(f"eixo {canal!r} tem coordenada nao finita")
        return None
    lat = arr[:, 1]
    lon = arr[:, 0]
    return np.column_stack((lat, lon))


def _avisar(mensagem: str) -> None:
    import sys
    print(f"AVISO: {mensagem}", file=sys.stderr)


def metadados(caminho: str | None = None) -> dict:
    """Propriedades do cache, para relatorio e teste. Vazio se nao houver cache."""
    if caminho is None:
        caminho = ARQUIVO_EIXO
    if not os.path.exists(caminho):
        return {}
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}
