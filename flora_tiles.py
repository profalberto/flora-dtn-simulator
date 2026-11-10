"""
flora_tiles.py
==============

Camada de tiles XYZ para o mapa de fundo do simulador (estilo *slippy map*).

O mapa de um aplicativo como o Google Maps ou o OpenStreetMap e uma grade de
imagens de 256 x 256 px, servidas por nivel de zoom (esquema XYZ). Este modulo
implementa a parte que importa para o simulador:

* a projecao Web Mercator entre ``(lat, lon)`` e o pixel global de um zoom;
* a leitura dos tiles ja guardados em disco (``mapa_tiles_satelite`` e
  ``mapa_tiles``), que e o caminho **offline** e o unico que o simulador usa
  quando a rede nao esta disponivel;
* o download **sob demanda** de um tile que falte, em uma thread propria, para
  o quadro da interface nunca esperar pela rede;
* o cache dos tiles em memoria e a costura apenas da faixa visivel.

Por que nao "importar o Google Maps". A API do Google Maps e uma biblioteca
JavaScript que roda dentro de um navegador; uma janela pygame nao tem DOM para
ela desenhar. O que da para reaproveitar e o modelo de tiles, que e o mesmo do
OpenStreetMap e do Esri, e e o que este modulo faz. As imagens continuam sendo
buscadas dos servidores publicos, com atribuicao no mapa.

Atribuicao
----------
* Esri World Imagery: "Esri, Maxar, Earthstar Geographics e a comunidade GIS".
* OpenStreetMap: "© OpenStreetMap contributors", sob ODbL 1.0.

Os dois provedores exigem que o credito acompanhe a imagem. A interface desenha
esse credito no canto inferior esquerdo do mapa; a carta exportada continua com
o credito da geometria em ``flora_osm.credito_carta``.
"""

from __future__ import annotations

import io
import math
import os
import queue
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from PIL import Image

#: Lado de um tile, em pixels. O esquema XYZ inteiro assume 256.
LADO_TILE = 256

#: Cor de preenchimento de um tile que ainda nao chegou (ou que nao existe no
#: recorte offline). E o verde escuro da mata amazônica, para a espera nao
#: abrir um buraco branco no meio do mapa.
COR_FALTA = (28, 48, 34)

#: User-Agent honesto, como pedem as politicas de uso dos servidores de tiles.
#: Identificar o projeto e o contato e o que separa uso normal de trafego
#: anonimizado; os dois provedores recusam clientes sem identificacao.
USER_AGENT = (
    "FLoRA-DTN-simulador/1.0 (tese de doutorado, mapa de fundo do corredor "
    "Manaus-Itacoatiara)"
)

PASTA_RAIZ = os.path.dirname(os.path.abspath(__file__))
PASTA_SATELITE = os.path.join(PASTA_RAIZ, "mapa_tiles_satelite")
PASTA_RUAS = os.path.join(PASTA_RAIZ, "mapa_tiles")


@dataclass(frozen=True)
class Provedor:
    """Descricao de um servidor de tiles XYZ e da pasta de cache local."""

    nome: str
    url: str
    atribuicao: str
    extensao: str
    pasta: str
    zoom_min: int = 3
    zoom_max: int = 19


#: Esri World Imagery: a mesma foto que ja esta nos tiles de satelite em disco.
PROVEDOR_SATELITE = Provedor(
    nome="Esri World Imagery",
    url=("https://server.arcgisonline.com/ArcGIS/rest/services/"
         "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
    atribuicao=("Imagens: Esri, Maxar, Earthstar Geographics e a "
                "comunidade de usuarios GIS"),
    extensao="jpg",
    pasta=PASTA_SATELITE,
    zoom_min=3,
    zoom_max=19,
)

#: OpenStreetMap padrao: mapa de ruas, com nomes de lugares.
PROVEDOR_RUAS = Provedor(
    nome="OpenStreetMap",
    url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    atribuicao="© OpenStreetMap contributors (ODbL 1.0)",
    extensao="png",
    pasta=PASTA_RUAS,
    zoom_min=3,
    zoom_max=19,
)


# ---------------------------------------------------------------------------
# PROJECAO WEB MERCATOR
# ---------------------------------------------------------------------------
def geo_para_px(lat: float, lon: float, z: int) -> tuple[float, float]:
    """Lat/lon -> pixel global do esquema XYZ, em px (256 por tile)."""
    n = 2 ** z
    gx = (lon + 180.0) / 360.0 * n * LADO_TILE
    lat = max(-85.05112878, min(85.05112878, lat))
    lat_r = math.radians(lat)
    gy = ((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
          / 2.0 * n * LADO_TILE)
    return gx, gy


def px_para_geo(gx: float, gy: float, z: int) -> tuple[float, float]:
    """Pixel global do esquema XYZ -> (lat, lon). Inverso de `geo_para_px`."""
    n = 2 ** z
    lon = gx / (n * LADO_TILE) * 360.0 - 180.0
    y = gy / (n * LADO_TILE)
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y))))
    return lat, lon


def zoom_para_escala(zoom: float, largura_mundo_px: float,
                     graus_lon: float) -> int:
    """
    Escolhe o nivel de tile que deixa o mapa em ~1 px de tela por px de tile.

    `zoom` e o multiplicador da visao do simulador (1 = mundo inteiro na
    largura). O nivel cresce um degrau a cada dobra da visao: e o mesmo
    comportamento de um mapa real, em que aproximar troca de conjunto de tiles.
    """
    alvo = (largura_mundo_px * zoom * 360.0
            / (LADO_TILE * max(1e-9, graus_lon)))
    return int(round(math.log2(max(1.0, alvo))))


# ---------------------------------------------------------------------------
# CAMADA DE TILES
# ---------------------------------------------------------------------------
class CamadaTiles:
    """
    Tiles de um provedor, com cache de memoria, disco e download em segundo plano.

    O acesso e sempre nao bloqueante: `tile()` devolve o que ja esta em memoria
    ou em disco e, se faltar e a rede estiver liberada, enfileira o download e
    devolve ``None``. O quadro seguinte encontra o tile pronto. Assim a
    interface nunca congela esperando um servidor lento.
    """

    def __init__(self, provedor: Provedor, permitir_rede: bool = False) -> None:
        self.provedor = provedor
        self.permitir_rede = permitir_rede
        #: (z, x, y) -> PIL.Image ja carregada
        self._memoria: dict[tuple[int, int, int], Image.Image] = {}
        #: (z, x, y) que ja se sabe nao existirem em disco
        self._sem_disco: set[tuple[int, int, int]] = set()
        #: (z, x, y) que falharam de vez (404, rede fora, formato invalido)
        self._ausente: set[tuple[int, int, int]] = set()
        #: (z, x, y) enfileirados ou em download agora
        self._pendente: set[tuple[int, int, int]] = set()
        #: (z, tx0, ty0, tx1, ty1) -> PIL.Image costurada
        self._mosaicos: dict[tuple[int, int, int, int, int], Image.Image] = {}
        self._z_local: int | None = None
        self._fila: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        #: Cresce a cada tile novo; a interface usa como chave de cache.
        self.versao = 0

    # -- disponibilidade -------------------------------------------------
    def zoom_local_max(self) -> int:
        """Maior nivel de zoom que existe em disco para este provedor."""
        if self._z_local is None:
            zmax = -1
            pasta = self.provedor.pasta
            if os.path.isdir(pasta):
                for nome in os.listdir(pasta):
                    raiz, ext = os.path.splitext(nome)
                    if ext.lower().lstrip(".") != self.provedor.extensao:
                        continue
                    partes = raiz.split("_")
                    if len(partes) != 3:
                        continue
                    try:
                        z = int(partes[0])
                    except ValueError:
                        continue
                    if z > zmax:
                        zmax = z
            self._z_local = max(0, zmax)
        return self._z_local

    def tem_tiles(self) -> bool:
        """Se ha alguma imagem utilizavel: em disco ou na rede liberada."""
        return self.zoom_local_max() > 0 or self.permitir_rede

    def zoom_max_efetivo(self) -> int:
        """Maior zoom que pode ser usado agora (local, ou do provedor com rede)."""
        if self.permitir_rede:
            return self.provedor.zoom_max
        return max(self.provedor.zoom_min, self.zoom_local_max())

    # -- arquivos --------------------------------------------------------
    def caminho(self, z: int, x: int, y: int) -> str:
        return os.path.join(
            self.provedor.pasta,
            f"{z}_{x}_{y}.{self.provedor.extensao}",
        )

    def _ler_disco(self, z: int, x: int, y: int) -> Image.Image | None:
        caminho = self.caminho(z, x, y)
        try:
            with Image.open(caminho) as im:
                return im.convert("RGB")
        except (OSError, ValueError):
            return None

    def _baixar(self, z: int, x: int, y: int) -> Image.Image | None:
        url = self.provedor.url.format(z=z, x=x, y=y)
        pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(pedido, timeout=12) as resposta:
            dados = resposta.read()
        if not dados:
            return None
        caminho = self.caminho(z, x, y)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        temporario = caminho + ".tmp"
        with open(temporario, "wb") as fh:
            fh.write(dados)
        os.replace(temporario, caminho)
        with Image.open(io.BytesIO(dados)) as im:
            return im.convert("RGB")

    # -- download em segundo plano --------------------------------------
    def _iniciar_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._trabalhar, daemon=True,
            name=f"tiles-{self.provedor.nome}",
        )
        self._worker.start()

    def _trabalhar(self) -> None:
        while True:
            try:
                pedido = self._fila.get(timeout=1.0)
            except queue.Empty:
                continue
            if pedido is None:
                break
            z, x, y = pedido
            chave = (z, x, y)
            try:
                img = self._baixar(z, x, y)
                if img is None:
                    self._ausente.add(chave)
                else:
                    self._memoria[chave] = img
                    # o mosaico antigo nao tem este tile: joga fora para a
                    # proxima composicao incluir a imagem recem-chegada
                    self._mosaicos.clear()
                    self.versao += 1
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, OSError, ValueError):
                self._ausente.add(chave)
            finally:
                self._pendente.discard(chave)

    # -- leitura ---------------------------------------------------------
    def tile(self, z: int, x: int, y: int) -> Image.Image | None:
        """Imagem do tile, ou ``None`` enquanto ele nao estiver disponivel."""
        chave = (z, x, y)
        img = self._memoria.get(chave)
        if img is not None:
            return img
        if chave in self._ausente:
            return None
        if chave not in self._sem_disco:
            img = self._ler_disco(z, x, y)
            if img is not None:
                self._memoria[chave] = img
                return img
            self._sem_disco.add(chave)
        # teto na fila: um arrasto rapido por uma area grande nao pode abrir
        # centenas de conexoes; o que ficar de fora entra no quadro seguinte
        if (self.permitir_rede and chave not in self._pendente
                and len(self._pendente) < 128):
            self._pendente.add(chave)
            self._iniciar_worker()
            self._fila.put(chave)
        return None

    def mosaico(self, z: int, tx0: int, ty0: int, tx1: int, ty1: int):
        """Costura os tiles ``tx0..tx1`` x ``ty0..ty1`` numa unica imagem."""
        chave = (z, tx0, ty0, tx1, ty1)
        pronto = self._mosaicos.get(chave)
        if pronto is not None:
            return pronto
        larg = (tx1 - tx0 + 1) * LADO_TILE
        alt = (ty1 - ty0 + 1) * LADO_TILE
        if larg <= 0 or alt <= 0 or larg > 8192 or alt > 8192:
            return None
        mosaico = Image.new("RGB", (larg, alt), COR_FALTA)
        algum = False
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                img = self.tile(z, tx, ty)
                if img is not None:
                    mosaico.paste(
                        img, ((tx - tx0) * LADO_TILE, (ty - ty0) * LADO_TILE))
                    algum = True
        if not algum:
            return None
        self._mosaicos[chave] = mosaico
        if len(self._mosaicos) > 12:
            self._mosaicos.pop(next(iter(self._mosaicos)))
        return mosaico

    def recorte(self, bbox, tamanho: tuple[int, int], z: int):
        """
        Recorta o bbox (lat_topo, lat_base, lon_esq, lon_dir) no zoom `z`.

        Devolve uma imagem PIL ja no tamanho pedido, ou ``None`` se nao houver
        nenhum tile na area (fora do recorte offline, por exemplo).
        """
        lat_topo, lat_base, lon_esq, lon_dir = bbox
        gx0, gy0 = geo_para_px(lat_topo, lon_esq, z)
        gx1, gy1 = geo_para_px(lat_base, lon_dir, z)
        tx0 = int(math.floor(gx0 / LADO_TILE))
        tx1 = int(math.floor((gx1 - 1e-9) / LADO_TILE))
        ty0 = int(math.floor(gy0 / LADO_TILE))
        ty1 = int(math.floor((gy1 - 1e-9) / LADO_TILE))
        mosaico = self.mosaico(z, tx0, ty0, tx1, ty1)
        if mosaico is None:
            return None
        caixa = (
            gx0 - tx0 * LADO_TILE,
            gy0 - ty0 * LADO_TILE,
            gx1 - tx0 * LADO_TILE,
            gy1 - ty0 * LADO_TILE,
        )
        caixa = (
            max(0, int(round(caixa[0]))),
            max(0, int(round(caixa[1]))),
            min(mosaico.width, int(round(caixa[2]))),
            min(mosaico.height, int(round(caixa[3]))),
        )
        if caixa[2] - caixa[0] < 2 or caixa[3] - caixa[1] < 2:
            return None
        recorte = mosaico.crop(caixa)
        if recorte.size != tuple(tamanho):
            recorte = recorte.resize(tuple(tamanho), Image.LANCZOS)
        return recorte

    def limpar_memoria(self) -> None:
        """Descarta os caches de memoria (o disco e a rede continuam valendo)."""
        self._memoria.clear()
        self._mosaicos.clear()
        self._sem_disco.clear()
        self._ausente.clear()
        self.versao += 1
