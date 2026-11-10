"""
Baixa a geometria real do rio na area do corredor e grava um cache local.

Este script e o ponto do projeto que precisa de rede para a **geometria**. Ele
consulta a API Overpass do OpenStreetMap, costura os trechos de
`waterway=river` em cadeias e salva o resultado em `dados_osm/eixo_rio.json`.
Depois disso o simulador roda off-line, e `flora_osm.py` le so o arquivo.

Os tiles do mapa de fundo sao a excecao opcional: `flora_tiles.py` so acessa a
rede quando o item *Mapa online* esta ligado, um tile visivel por vez, e guarda
o resultado em `mapa_tiles_satelite/` ou `mapa_tiles/`. Desligado, nada e
baixado e o simulador usa apenas os arquivos locais.

    python baixar_osm.py            # constroi ou atualiza o cache
    python baixar_osm.py --forcar   # ignora o cache e refaz a consulta

Por que Overpass e nao tiles. Tile de mapa e uma imagem de tela: serve para
mostrar, nao para medir, e o termo de uso do tile server do OSM proibe baixa em
lote, justamente porque cada tile e uma pessegada. A Overpass entrega dado
vetorial, que e o que o modelo precisa, e uma consulta de area pequena e um uso
normal da API. Google Maps exigiria chave e termo que proibe cache, o que
derruba a exigencia de rodar sem rede. O download dos tiles do fundo, feito por
`flora_tiles.py`, nao e um lote: e um pedido por tile visivel, apenas quando o
mapa online esta ligado, e o resultado fica em cache para as proximas visitas.

O dado e do OpenStreetMap, sob ODbL. A atribuicao esta em `ATRIBUICAO` e precisa
acompanhar a carta exportada: ver `flora_osm.credito_carta`.
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

#: Onde o cache mora. Relativo ao script, para funcionar de qualquer diretorio.
PASTA_DADOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados_osm")
ARQUIVO_CACHE = os.path.join(PASTA_DADOS, "eixo_rio.json")

#: Endpoints Overpass, na ordem de tentativa. Os tres sao publicos e um deles
#: sempre esta fora do ar.
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

#: User-Agent honesto, como pede a politica da Overpass. Identificar o projeto
#: e o contato e o que separa consulta de pesquisa de trafego anonimizado.
USER_AGENT = (
    "FLoRA-DTN-simulador/1.0 (tese de doutorado, cache offline de geometria fluvial)"
)

#: Area consultada, em graus. Cortada rente ao corredor porque a consulta com
#: area grande estoura o tempo do servidor: o primeiro tile unico de 1,8 x 0,6
#: graus ja deu HTTP 504, e o mesmo recorte em 14 tiles de 0,3 grau passou.
LATS = ((-3.45, -3.15), (-3.15, -2.85))
LONS = ((-60.30, -60.00), (-60.00, -59.70), (-59.70, -59.40), (-59.40, -59.10),
        (-59.10, -58.80), (-58.80, -58.50), (-58.50, -58.20))

#: Cidades e marcos, em graus, copiados de `flora_geometria`. Sao as mesmas
#: coordenadas, e nao valores parecidos: o percurso real do OSM so serve se
#: passar pelos mesmos lugares que o modelo declara. Uma constante divergente
#: aqui e um criterio de busca errado, e nao um detalhe.
MANAUS = (-3.1190, -60.0217)
ITA_COATIARA = (-3.1338, -58.4386)
BIFURCACAO_CAREIRO = (-3.1300, -59.9900)
BOCA_PRETO_EVA = (-3.1450, -58.5200)

#: Marcos do leito principal, na ordem em que o rio corre, com a mesma lista de
#: `flora_geometria.COORDENADAS_ROTA_NAVEGACAO`.
MARCAS_PRINCIPAL = (
    ("Manaus", MANAUS),
    ("Bifurcacao do Careiro", BIFURCACAO_CAREIRO),
    ("Boca do Preto da Eva", BOCA_PRETO_EVA),
    ("Itacoatiara", ITA_COATIARA),
)

#: Raio, em km, dentro do qual um ponto do percurso conta como "a cidade".
RAIO_CIDADE_KM = 12.0

#: Vao entre trechos maior que isto conta como geometria inventada. As
#: coordenadas do OSM nao tem o que dizer sobre o trecho que falta, e o recurso
#: e explicito: o vao e uma reta entre dois pontos e nada mais.
VAO_MAX_KM = 4.0

#: Quanto um vao grande pesa contra o comprimento total. Serve para o percurso
#: mais curto sair do corredor e voltar por fora, cortando pela mata: um vao de
#: 10 km custa 500 km de comprimento, mais que o desvio inteiro.
PESO_VAO = 50.0

RAIO_TERRA_KM = 6371.0088


# ---------------------------------------------------------------------------
# GEOIDESA
# ---------------------------------------------------------------------------
def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia em km entre dois pontos (lat, lon) em graus."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * RAIO_TERRA_KM * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# CONSULTA
# ---------------------------------------------------------------------------
def _consultar(consulta: str, tentativas: int = 2) -> dict:
    """Roda uma consulta Overpass, trocando de endpoint quando um falha."""
    for endpoint in ENDPOINTS:
        for tentativa in range(tentativas):
            try:
                req = urllib.request.Request(
                    endpoint, data=consulta.encode("utf-8"),
                    headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=180) as resp:
                    return json.loads(resp.read())
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    json.JSONDecodeError, OSError) as exc:
                print(f"    {endpoint.split('/')[2]} tentativa {tentativa + 1}: {exc}",
                      file=sys.stderr, flush=True)
                time.sleep(3.0 + 2.0 * tentativa)
    return {}


def _cache_tile(nome: str) -> str:
    return os.path.join(PASTA_DADOS, "tiles_osm", nome)


def baixar_tiles(forcar: bool = False) -> dict[str, list]:
    """
    Consulta a grade de tiles e devolve `way_id -> [(lat, lon), ...]`.

    O bruto vai para `dados_osm/tiles_osm/` antes de qualquer processamento. Se a
    costura ou a selecao de cadeia precisarem ser refeitas, o script roda sem
    rede: e o bruto que custa, nao a analise.
    """
    os.makedirs(_cache_tile("."), exist_ok=True)
    trechos: dict[str, list] = {}
    for (sul, norte) in LATS:
        for (oeste, leste) in LONS:
            nome = f"rio_{sul:.2f}_{oeste:.2f}.json"
            caminho = _cache_tile(nome)
            if os.path.exists(caminho) and not forcar:
                with open(caminho, encoding="utf-8") as fh:
                    dados = json.load(fh)
            else:
                consulta = (f'[out:json][timeout:120];('
                            f'way["waterway"="river"]({sul},{oeste},{norte},{leste});'
                            f'way["natural"="water"]({sul},{oeste},{norte},{leste});'
                            f');out geom;')
                print(f"  consultando {sul:+.2f},{oeste:+.2f}", flush=True)
                dados = _consultar(consulta)
                if not dados:
                    print(f"  AVISO: tile {nome} falhou, seguindo", file=sys.stderr)
                    continue
                with open(caminho, "w", encoding="utf-8") as fh:
                    json.dump(dados, fh)
                time.sleep(1.2)
            for el in dados.get("elements", []):
                if el.get("tags", {}).get("waterway") != "river":
                    continue
                geom = el.get("geometry")
                if geom:
                    trechos[str(el["id"])] = [(p["lat"], p["lon"]) for p in geom]
    return trechos


# ---------------------------------------------------------------------------
# GRAFO DE TRECHOS
# ---------------------------------------------------------------------------
#: Distancia maxima, em km, entre dois extremos de trechos para eles serem
#: considerados o mesmo ponto do rio.
#:
#: O valor nao e chutado: medindo as 66 430 distancias entre extremos de trechos
#: diferentes na area, ha 24 pares que batem em 0,000 km, e opercentil 50 dos
#: 364 pares mais proximos fica em 1,06 km, com o 800o em 3,06 km. Dois
#: quilometros junta a cadeia sem criar atalho: a distancia tipica entre trechos
#: vizinhos e de poucos quilometros, entao 2 km nao atravessa margem nem lago.
TOLERANCIA_KM = 2.0


def _comprimento_trecho(pontos: list) -> float:
    return sum(haversine(pontos[i], pontos[i + 1]) for i in range(len(pontos) - 1))


def montar_grafo(trechos: dict[str, list], tolerancia_km: float = TOLERANCIA_KM):
    """
    Monta o grafo em que um no e um trecho de rio e uma aresta e a ponte entre
    dois trechos que chegam no mesmo lugar.

    Diferente da costura por encadeamento, que depende de os extremos baterem
    exato, aqui a ponte e tolerante. O motivo e a medicao: nesta regiao o OSM
    deixa buracos no mapeamento do leito, com trechos separados por gaps de ate
    poucos quilometros, e o encadeamento exato achava so 27 juncoes em 365
    trechos, deixando o rio em 338 cacos. Com a tolerancia, o caminho passa a
    existir e o percurso sai unico.

    O peso da aresta e o comprimento do trecho mais o gap ate o vizinho, e o
    vizinho em que a ponte e criada, de modo que Dijkstra minimize o percurso
    real e nao a quantidade de trechos.
    """
    validos = {w: p for w, p in trechos.items() if len(p) >= 2}
    # extremos: (ponto, trecho, lado)
    extremos = [(p[0], w, 0) for w, p in validos.items()]
    extremos += [(p[-1], w, 1) for w, p in validos.items()]

    # uma malha em graus resolve o par mais proximo sem O(n^2) em Python
    passo = 0.25
    cubos: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    for i, (p, _w, _l) in enumerate(extremos):
        cubos[(int(p[0] // passo), int(p[1] // passo))].append(i)

    grafo: dict[str, list[tuple[str, float]]] = {w: [] for w in validos}
    vistos: set[tuple[str, int, str, int]] = set()
    for i, (pi, wi, li) in enumerate(extremos):
        ci, cj = int(pi[0] // passo), int(pi[1] // passo)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for j in cubos.get((ci + di, cj + dj), ()):
                    if i == j:
                        continue
                    pj, wj, lj = extremos[j]
                    if wj == wi:
                        continue
                    chave = (wi, li, wj, lj)
                    if chave in vistos:
                        continue
                    gap = haversine(pi, pj)
                    if gap > tolerancia_km:
                        continue
                    vistos.add(chave)
                    custo = _comprimento_trecho(validos[wj]) + gap
                    grafo[wi].append((wj, custo))
    return grafo, validos


def menor_caminho(grafo, origem: str, destino: str) -> list[str] | None:
    """Dijkstra de `origem` a `destino`, devolvendo a sequencia de trechos."""
    import heapq

    if origem not in grafo or destino not in grafo:
        return None
    dist = {origem: 0.0}
    anterior: dict[str, str] = {}
    fila = [(0.0, origem)]
    visitados: set[str] = set()
    while fila:
        d, no = heapq.heappop(fila)
        if no in visitados:
            continue
        visitados.add(no)
        if no == destino:
            break
        for vizinho, custo in grafo[no]:
            nd = d + custo
            if nd < dist.get(vizinho, float("inf")):
                dist[vizinho] = nd
                anterior[vizinho] = no
                heapq.heappush(fila, (nd, vizinho))
    if destino not in dist:
        return None
    caminho = [destino]
    while caminho[-1] in anterior:
        caminho.append(anterior[caminho[-1]])
    return list(reversed(caminho))


def costurar(caminho: list[str], trechos: dict[str, list]) -> list:
    """
    Achata um caminho de trechos em uma unica polilinha de (lat, lon).

    Os vãos entre trechos entram como um segmento reto, porque o OSM nao diz onde
    o rio passa no buraco. Sao lacunas de ate 2 km numa linha de 180 km, e o
    recurso e explicito: o polyline resultante tem os vãos como dois pontos, e
    nao como um spline inventado atravessando a mata.
    """
    pontos: list = []
    for wid in caminho:
        pts = trechos[wid]
        if not pontos:
            pontos.extend(pts)
        else:
            if haversine(pontos[-1], pts[0]) > 1e-6:
                pontos.append(pts[0])
            pontos.extend(pts[1:])
    return pontos


# ---------------------------------------------------------------------------
# SELECAO
# ---------------------------------------------------------------------------
def _componentes(grafo) -> list[int]:
    """Rotulo de componente conexa de cada no. Serve para medir a fragmentacao."""
    rot: dict[str, int] = {}
    cid = 0
    for s in grafo:
        if s in rot:
            continue
        pilha = [s]
        rot[s] = cid
        while pilha:
            u = pilha.pop()
            for v, _custo in grafo[u]:
                if v not in rot:
                    rot[v] = cid
                    pilha.append(v)
        cid += 1
    return list(rot.values())


def _melhores_origens(validos: dict[str, list], alvo: tuple[float, float],
                      excluir: set[str], n: int) -> list[str]:
    """Os `n` trechos cujo ponto mais proximo do alvo e o mais proximo de todos."""
    d = [(min(haversine(p, alvo) for p in pts), wid)
         for wid, pts in validos.items() if wid not in excluir]
    d.sort()
    return [wid for _dist, wid in d[:n]]


def _rota_por_marcas(validos, grafo, marcas, excluir: set[str], n: int = 8) -> dict | None:
    """
    Acha a polilinha que passa por uma sequencia de marcos.

    Para cada par de marcos procura-se o trecho mais proximo de cada um e
    liga-se os dois por Dijkstra. O percurso aceito e o de menor comprimento
    calculado, e so passa se chegar perto de todos os marcos, porque um caminho
    longo que ignora um marco e o rio errado, nao o canal modelado.

    O par de extremos mais proximos de Manaus e o de Itacoatiara precisa entrar
    como candidato, e nao so os pares consecutivos. O tronco do Amazonas e um
    unico `way` de 764 km que passa pelos quatro marcos, e o caco isolado mais
    proximo de Manaus nao se liga a nada dentro da tolerancia, entao um percurso
    que va de Manaus direto a Itacoatiara so aparece se esse par for testado.
    """
    cands = [_melhores_origens(validos, alvo, excluir, n)
             for _nome, alvo in marcas]
    primeiro, ultimo = marcas[0][1], marcas[-1][1]
    melhor = None

    def avaliar(caminho: list[str] | None):
        nonlocal melhor
        if not caminho:
            return
        pontos = costurar(caminho, validos)
        if len(pontos) < 4:
            return
        # a janela e o trecho do percurso entre o primeiro e o ultimo marco. E
        # ela que e conferida contra todos os marcos, e nao o percurso inteiro:
        # o OSM continua o rio muito alem da ultima cidade, e o que nao entra no
        # modelo nao tem por que satisfazer ninguem.
        janela = _recortar_entre(pontos, primeiro, ultimo)
        if len(janela) < 2:
            return
        if any(_distancia_a_cidade(janela, alvo) > RAIO_CIDADE_KM
               for _nome, alvo in marcas):
            return
        vaos = [haversine(validos[caminho[k]][-1], validos[caminho[k + 1]][0])
                for k in range(len(caminho) - 1)]
        km = _comprimento_pontos(janela)
        # o comprimento sozinho premia o caminho que sai do corredor e volta por
        # fora; o desvio longo penaliza os vaos grandes, que sao justamente onde
        # a geometria foi inventada
        penal = km + PESO_VAO * sum(v for v in vaos if v > VAO_MAX_KM)
        if melhor is None or penal < melhor["custo"]:
            melhor = {"caminho": list(caminho), "pontos": janela, "custo": penal,
                      "km": km, "vao_max": max(vaos) if vaos else 0.0,
                      "d_inicio": _distancia_a_cidade(janela, primeiro),
                      "d_fim": _distancia_a_cidade(janela, ultimo)}

    # um trecho so pode ser o percurso inteiro: o tronco do Amazonas e um unico
    # `way` de 764 km que passa por Manaus, Boca do Preto da Eva e Itacoatiara,
    # e ele nao esta ligado a nenhum outro trecho dentro da tolerancia
    for wid in itertools.chain.from_iterable(cands):
        avaliar([wid])
    # e todos os pares de marcos, nao so os consecutivos: o percurso que liga
    # Manaus direto a Itacoatiara e o mesmo, e ele e servido por um caminho cujo
    # ponto de partida e um caco isolado perto da cidade que nao se liga a nada
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            for o in cands[i]:
                for f in cands[j]:
                    avaliar(menor_caminho(grafo, o, f))
    return melhor


def selecionar_eixo(trechos: dict[str, list]) -> dict:
    """
    Acha o percurso do leito principal do Amazonas.

    O canal e definido pelos marcos do proprio modelo, na ordem em que o rio
    corre, e nao por nome de rua no OSM: nesta regiao quase nenhum trecho de rio
    tem `name` consultavel, com 145 trechos sem nome e so 1 nomeado no bruto. O
    criterio e geografico e auditavel.

    Antes havia um segundo canal, o do Careiro, e ele foi retirado do modelo por
    decisao do experimento. O motivo pratico esta em `dados_osm/eixo_rio.json`:
    o percurso do Careiro nao existe no OSM com fidelidade util. O trecho real
    que passaria pelos quatro marcos do canal so aparece com tolerancia de juncao
    de 6 km, e vem com nove vaos de mais de 5 km entre trechos, o maior de
    13,6 km. Um vao e uma reta que o OSM nao mediu: e invencao atravessando a
    mata, que e o oposto do que a geometria real veio resolver.
    """
    grafo, validos = montar_grafo(trechos)
    principal = _rota_por_marcas(validos, grafo, MARCAS_PRINCIPAL, set())
    return {"principal": principal, "n_trechos": len(validos)}


def _distancia_a_cidade(pontos: list, cidade: tuple[float, float]) -> float:
    return min(haversine(p, cidade) for p in pontos)


def _indice_mais_perto(pontos: list, alvo: tuple[float, float]) -> int:
    return min(range(len(pontos)), key=lambda i: haversine(pontos[i], alvo))


def _recortar_entre(pontos: list, inicio, fim) -> list:
    """
    Recorta a polilinha entre dois alvos, na ordem em que a cadeia corre.

    Se o trecho veio do OSM invertido, a ordem e corrigida: o modelo sempre
    desce o rio, de Manaus para Itacoatiara, e o comprimento por km so pode ser
    comparado se o sentido for o mesmo nos dois casos.
    """
    i, j = _indice_mais_perto(pontos, inicio), _indice_mais_perto(pontos, fim)
    if i > j:
        return list(reversed(pontos[j:i + 1]))
    return pontos[i:j + 1]


def _comprimento_pontos(pontos: list) -> float:
    return sum(haversine(pontos[i], pontos[i + 1]) for i in range(len(pontos) - 1))


# ---------------------------------------------------------------------------
# GRAVACAO
# ---------------------------------------------------------------------------
def _propriedades(canal: str, nome: str, pontos: list, inicio: str, fim: str) -> dict:
    """Metadados que acompanham cada linha, inclusive o comprimento em km."""
    return {
        "canal": canal,
        "nome": nome,
        "cidade_inicio": inicio,
        "cidade_fim": fim,
        "origem": "OpenStreetMap contributors, ODbL 1.0, via Overpass API",
        "comprimento_km": round(_comprimento_pontos(pontos), 2),
        "n_pontos": len(pontos),
    }


def _ancorar(pontos: list, inicio: tuple[float, float],
             fim: tuple[float, float]) -> list:
    """
    Puxa as duas pontas do percurso para as coordenadas exatas das cidades.

    O ponto do OSM mais proximo de Manaus esta 3,9 km dela, e o de Itacoatiara
    3,8 km. Sao sessenta metros de carta em 200 km, entao nao muda o desenho, mas
    muda onde o modelo ancorar: o gateway precisa nascer sobre a cidade, e a
    posicao do rio e onde o OSM diz que o rio esta, nao onde a cidade esta.

    Por isso so as pontas sao trocadas. O meio do percurso fica intacto, que e
    onde esta a geometria que o OSM realmente mediu.
    """
    if len(pontos) < 2:
        return pontos
    saida = [tuple(p) for p in pontos]
    if haversine(saida[0], inicio) < haversine(saida[-1], inicio):
        saida[0] = inicio
        saida[-1] = fim
    else:
        saida[-1] = inicio
        saida[0] = fim
    return saida


def gravar_cache(selecao: dict) -> str:
    """Escreve o GeoJSON de saida, no formato que `flora_osm.py` le."""
    feats = []
    principal = selecao["principal"]
    if principal is not None:
        pts = _ancorar(principal["pontos"], MANAUS, ITA_COATIARA)
        feats.append({"type": "Feature",
                      "properties": _propriedades("principal", "Rio Amazonas", pts,
                                                  "Manaus", "Itacoatiara"),
                      "geometry": {"type": "LineString",
                                   "coordinates": [[p[1], p[0]] for p in pts]}})

    doc = {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors, ODbL 1.0. Geometria via "
                       "Overpass API. Derivado de waterway=river.",
        "gerado_por": "baixar_osm.py",
        "tolerancia_junta_km": TOLERANCIA_KM,
        "features": feats,
    }
    os.makedirs(PASTA_DADOS, exist_ok=True)
    with open(ARQUIVO_CACHE, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    return ARQUIVO_CACHE


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--forcar", action="store_true",
                    help="ignora o cache de tiles e consulta a Overpass de novo")
    args = ap.parse_args(argv)

    tiles = baixar_tiles(forcar=args.forcar)
    print(f"tiles em {LATS} x {LONS}")
    print(f"trechos de rio: {len(tiles)}")
    grafo, validos = montar_grafo(tiles)
    arestas = sum(len(v) for v in grafo.values())
    componentes = _componentes(grafo)
    print(f"grafo: {len(validos)} nos, {arestas} arestas, "
          f"{len(set(componentes))} componentes, tolerancia {TOLERANCIA_KM} km")
    selecao = selecionar_eixo(tiles)

    achado = selecao["principal"]
    if achado is None:
        print("AVISO: nenhum percurso do OSM passa pelos marcos do leito "
              f"principal dentro da tolerancia de {TOLERANCIA_KM} km",
              file=sys.stderr)
    else:
        pts = _ancorar(achado["pontos"], MANAUS, ITA_COATIARA)
        km = _comprimento_pontos(pts)
        reta = haversine(pts[0], pts[-1])
        print(f"  principal {km:7.1f} km  {len(pts):5d} pontos  "
              f"{len(achado['caminho']):3d} trechos do OSM  "
              f"vao maior {achado['vao_max']:4.1f} km")
        print(f"            ponta a ponta {reta:7.1f} km | "
              f"razao reta/percurso {reta / km:.3f}")

    caminho = gravar_cache(selecao)
    print(f"cache gravado em {caminho}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
