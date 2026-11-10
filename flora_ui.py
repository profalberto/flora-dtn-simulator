"""
flora_ui.py
===========

Interface grafica (pygame) do simulador FLoRA-DTN.

Telas
-----
* janela principal: barra de menus, area do mapa com zoom e painel de controle;
* vista de carta nautica: sobreposicao com a carta completa gerada a partir
  do estado corrente da simulacao, salvavel em PNG.

Desempenho
----------
O mapa e composto em tres niveis para que a interface responda sempre a 60 fps:

1. **base cartografica** em dois caminhos. O fundo de satelite/ruas vem de
   tiles XYZ (`flora_tiles`): a faixa visivel e costurada e cacheada por nivel de
   zoom, e o recorte escalado so e refeito quando a vista ou os tiles mudam. A
   folha de carta (batimetria) continua sendo montada em 2x de resolucao, apenas
   quando o cenario troca ou a cada faixa de seis horas simuladas;
2. **camadas vetoriais** (rotas, obstaculos, supernos, frota) redesenhadas a
   cada quadro a partir de uma transformacao de visao, que e a unica coisa que
   o zoom altera;
3. **textos** memorizados por (fonte, conteudo, cor), evitando rasterizar as
   mesmas strings 74 vezes por quadro.

A simulacao avanca em passos de duracao fixa com um orcamento de tempo por
quadro, de modo que aumentar a velocidade nunca congela a interface.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pygame
from PIL import Image

from flora_cenario import (
    CORES_RISCO,
    RISCO_CRITICO,
    RISCO_SEGURO,
    grade_profundidade,
    obter_cenario,
)
from flora_dtn import CAT_SEGURANCA, ConfiguracaoDTN, MotorDTN
from flora_geometria import (
    ALTURA_MENU_SUP,
    ALTURA_TELA_BASE,
    CANAIS,
    CANAL_PRINCIPAL,
    KM_POR_PX,
    LARGURA_PAINEL,
    LARGURA_SIMULACAO_BASE,
    LAT_BOTTOM,
    LAT_TOP,
    LONG_LEFT,
    LONG_RIGHT,
    WAYPOINTS,
    mundo_para_geo,
)
from flora_mapa import (
    CartaNautica,
    MosaicoTiles,
    OpcoesCarta,
    cor_batimetria,
    desenhar_folha_carta,
)
from flora_tiles import (
    LADO_TILE,
    PROVEDOR_RUAS,
    PROVEDOR_SATELITE,
    CamadaTiles,
    geo_para_px,
    zoom_para_escala,
)

# ---------------------------------------------------------------------------
# 1. PALETA E DIMENSOES
# ---------------------------------------------------------------------------
COR_FUNDO = (14, 18, 24)
COR_PAINEL = (24, 30, 40)
BORDA = (58, 70, 88)
TEXTO = (226, 232, 240)
TEXTO_FRACO = (150, 164, 182)
DESTAQUE = (255, 176, 64)
VERDE = (60, 220, 130)
AZUL = (120, 180, 245)

ALTURA_MENU = ALTURA_MENU_SUP
LARGURA_TOTAL = LARGURA_SIMULACAO_BASE + LARGURA_PAINEL
ALTURA_TOTAL = ALTURA_TELA_BASE + ALTURA_MENU

#: Multiplicador de resolucao da base cartografica. Acima de 1 o fundo continua
#: nitido quando o mapa e ampliado, que e o que torna o zoom util.
RES_BASE = 2

#: Resolucao do mosaico de satelite por quilometro, medida do proprio arquivo.
#: Os tiles em disco cobrem a janela com 7,9 px/km, quase o dobro do que a base
#: desenha (5,1 px/km). Pedir o recorte no tamanho da base, e o que `_imagem_satelite`
#: fazia, jogava fora mais da metade dos pixels: o zoom mostrava a foto


#: Faixa de tempo simulado que dispara a regeracao da base cartografica.
FAIXA_BASE_H = 6.0

#: Resolucao da malha de batimetria da base (em celulas, nao em pixels).
NX_BATI = 260
NY_BATI = 156

#: Area do mapa dentro da janela. Os desenhos translucidos sao limitados a ela,
#: o que evita tocar no painel a cada quadro e reduz em 54% o trabalho de alpha.
MAPA_RECT = pygame.Rect(0, ALTURA_MENU, LARGURA_SIMULACAO_BASE, ALTURA_TELA_BASE)

#: Orcamento de tempo, em segundos, para os passos de simulacao de um quadro.
#: Um passo de FLoRA custa cerca de 4,5 ms e o desenho cerca de 7 ms: 5 ms de
#: orcamento mantem a interface perto de 60 fps mesmo com a simulacao rodando.
ORCAMENTO_PASSOS = 0.005

#: Raio, em pixels de tela, dentro do qual um clique no mapa vale como
#: selecao da embarcacao mais proxima.
RAIO_SELECAO_PX = 22.0

#: Andamento do cursor, em pixels, que distingue um arrasto de um clique no mapa.
LIMITE_ARRASTO_PX = 4

#: Altura de uma linha da lista de frota do painel.
ALTURA_LINHA_FROTA = 14

#: Velocidades oferecidas, em passos de simulacao por segundo real.
VELOCIDADES = (10, 30, 60, 120, 240, 480, 960, 1920)

FAMILIA_FONTE = "segoeui, arial, liberation sans, sans-serif"

# Cores da hidrovia.
#
# A paleta precisa funcionar sobre dois fundos muito diferentes: a foto de
# satelite, escura e verde, e a folha de carta, clara e azulada. O rio e um
# bloco alfanumerico de 12 a 40% de alpha, e o que separa a faixa navegavel do
# resto e a borda, nao o brilho: um halo luminoso de 4 passes virava uma fita
# neon por cima da imagem. A borda escura e o eixo em creme sao os unicos
# elementos opacos, e por isso as duas bases leem igual.
COR_MARGEM = (18, 46, 40)
COR_LEITO = (26, 74, 122)
COR_FUNDO = (16, 52, 92)
COR_HALO = (46, 108, 158)
COR_EIXO = (245, 232, 196)
COR_FLUXO = (255, 250, 235)


def _fonte(tamanho: int, negrito: bool = False):
    return pygame.font.SysFont(FAMILIA_FONTE, tamanho, bold=negrito)


def _n(valor, casas: int = 1) -> str:
    """Formata um numero que pode ser `None` (metrica ainda indefinida)."""
    return "n/a" if valor is None else f"{valor:.{casas}f}"


# ---------------------------------------------------------------------------
# 2. VISAO: ZOOM E DESLOCAMENTO
# ---------------------------------------------------------------------------
@dataclass
class Visao:
    """
    Transformacao entre o mundo do simulador e a tela.

    O mundo usa as coordenadas de `flora_geometria`, com a origem em
    (0, ALTURA_MENU_SUP). A base cartografica cobre o bloco
    [0, LARGURA_SIMULACAO_BASE] x [0, ALTURA_TELA_BASE] com resolucao
    `RES_BASE`; o zoom apenas recorta e reescala esse bloco. Como as camadas
    vetoriais passam pela mesma transformacao, zoom e pan nao exigem reconstruir
    nada alem da propria projecao dos pontos.
    """

    zoom: float = 1.0
    centro_u: float = LARGURA_SIMULACAO_BASE / 2.0
    centro_v: float = ALTURA_TELA_BASE / 2.0

    ZOOM_MIN = 1.0
    ZOOM_MAX = 6.0
    #: Fator de zoom por entalhe da roda do mouse.
    FATO_RODA = 1.25

    # -- projecao --------------------------------------------------------
    def para_base(self, pos_mundo) -> tuple[float, float]:
        """Coordenadas do mundo para o bloco da base (sem o deslocamento do menu)."""
        return float(pos_mundo[0]), float(pos_mundo[1]) - ALTURA_MENU

    def para_tela(self, pos_mundo) -> tuple[int, int]:
        u, v = self.para_base(pos_mundo)
        sx = (u - self.centro_u) * self.zoom + LARGURA_SIMULACAO_BASE / 2.0
        sy = ((v - self.centro_v) * self.zoom + ALTURA_TELA_BASE / 2.0
              + ALTURA_MENU)
        return int(sx), int(sy)

    def para_base_local(self, sx: float, sy: float) -> tuple[float, float]:
        """Ponto da tela para o bloco da base; inverso de `para_tela`."""
        u = (sx - LARGURA_SIMULACAO_BASE / 2.0) / self.zoom + self.centro_u
        v = ((sy - ALTURA_MENU - ALTURA_TELA_BASE / 2.0) / self.zoom
             + self.centro_v)
        return u, v

    def projetar(self, u, v):
        """Projecao vetorizada de arrays do bloco da base para a tela."""
        return (
            (np.asarray(u) - self.centro_u) * self.zoom + LARGURA_SIMULACAO_BASE / 2.0,
            (np.asarray(v) - self.centro_v) * self.zoom
            + ALTURA_TELA_BASE / 2.0 + ALTURA_MENU,
        )

    def largura_px(self, px_mundo: float) -> int:
        """Converte uma espessura em pixels do mundo para pixels de tela."""
        return max(1, int(round(px_mundo * self.zoom)))

    def recorte_base(self) -> pygame.Rect:
        """Retangulo da base que preenche a area do mapa."""
        z = self.zoom
        w = LARGURA_SIMULACAO_BASE / z
        h = ALTURA_TELA_BASE / z
        return pygame.Rect(
            int(round((self.centro_u - w / 2.0) * RES_BASE)),
            int(round((self.centro_v - h / 2.0) * RES_BASE)),
            max(1, int(round(w * RES_BASE))),
            max(1, int(round(h * RES_BASE))),
        )

    def visivel(self, u: float, v: float, margem: float = 0.0) -> bool:
        w = LARGURA_SIMULACAO_BASE / (2.0 * self.zoom) + margem
        h = ALTURA_TELA_BASE / (2.0 * self.zoom) + margem
        return (abs(u - self.centro_u) <= w
                and abs(v - self.centro_v) <= h)

    # -- manuseio --------------------------------------------------------
    #: Quanto da janela pode sair do mundo ao arrastar, como fracao do que esta
    #: visivel. Sem essa folga, no zoom 1 o mundo ocupa a janela inteira e nao
    #: sobra nada para arrastar: o mapa parecia travado. Com 0,5 a vista sai
    #: meia tela para cada lado, como num mapa de verdade.
    MARGEM_PAN = 0.5

    def limitar(self) -> None:
        """Limita o arrasto a uma folga em volta do mundo."""
        w = LARGURA_SIMULACAO_BASE / (2.0 * self.zoom)
        h = ALTURA_TELA_BASE / (2.0 * self.zoom)
        mu = w * self.MARGEM_PAN
        mv = h * self.MARGEM_PAN
        self.centro_u = min(max(self.centro_u, w - mu),
                            LARGURA_SIMULACAO_BASE - w + mu)
        self.centro_v = min(max(self.centro_v, h - mv),
                            ALTURA_TELA_BASE - h + mv)

    def aproximar(self, fator: float = 1.25, tela_pos=None) -> None:
        """Amplia mantendo fixo o ponto do mundo sob o cursor, se fornecido."""
        antes = self.para_base_local(*tela_pos) if tela_pos else None
        novo = min(self.ZOOM_MAX, max(self.ZOOM_MIN, self.zoom * fator))
        if abs(novo - self.zoom) < 1e-6:
            return
        self.zoom = novo
        self.limitar()
        if antes is not None:
            depois = self.para_base_local(*tela_pos)
            self.centro_u += antes[0] - depois[0]
            self.centro_v += antes[1] - depois[1]
            self.limitar()

    def afastar(self, fator: float = 1.25, tela_pos=None) -> None:
        self.aproximar(1.0 / fator, tela_pos)

    def deslocar(self, dx: float, dy: float) -> None:
        """Arrasta a visao junto com o mouse, em pixels de tela."""
        self.centro_u -= dx / self.zoom
        self.centro_v -= dy / self.zoom
        self.limitar()

    def reenquadrar(self) -> None:
        self.zoom = 1.0
        self.centro_u = LARGURA_SIMULACAO_BASE / 2.0
        self.centro_v = ALTURA_TELA_BASE / 2.0


# ---------------------------------------------------------------------------
# 3. ICONES DAS EMBARCACOES
# ---------------------------------------------------------------------------
# Silhuetas em coordenadas normalizadas: origem no centro do casco, proa
# apontando para +x, comprimento 1.0. Sao desenhadas uma unica vez por tipo e
# depois apenas rotacionadas.
ICONES: dict[str, dict] = {
    "PRINCIPAL": {
        # casco largo com porao, passarela e cabine de comando a rÃ©
        "casco": [(-0.50, -0.30), (0.30, -0.30), (0.50, -0.13),
                  (0.50, 0.13), (0.30, 0.30), (-0.50, 0.30)],
        "poroes": [(-0.20, -0.16), (0.14, -0.16), (0.14, 0.16), (-0.20, 0.16)],
        "conteineres": [
            [(-0.18, -0.14), (-0.02, -0.14), (-0.02, -0.02), (-0.18, -0.02)],
            [(-0.18, 0.02), (-0.02, 0.02), (-0.02, 0.14), (-0.18, 0.14)],
            [(0.00, -0.14), (0.12, -0.14), (0.12, -0.02), (0.00, -0.02)],
            [(0.00, 0.02), (0.12, 0.02), (0.12, 0.14), (0.00, 0.14)],
        ],
        "cabine": [(-0.46, -0.17), (-0.30, -0.17), (-0.30, 0.17), (-0.46, 0.17)],
        "mastro": ((-0.38, 0.0), (-0.38, -0.34)),
    },
    "LANCHA": {
        # casco estreito e pontudo, com para-brisa
        "casco": [(-0.50, -0.22), (0.24, -0.20), (0.50, 0.0),
                  (0.24, 0.20), (-0.50, 0.22)],
        "poroes": [(0.00, -0.12), (0.24, -0.07), (0.24, 0.07), (0.00, 0.12)],
        "cabine": [(-0.30, -0.09), (-0.16, -0.09), (-0.16, 0.09), (-0.30, 0.09)],
        "mastro": None,
    },
    "RIBEIRINHO": {
        # balsao chato de fundo, cabine central e mastro de antena
        "casco": [(-0.50, -0.34), (0.50, -0.34), (0.50, 0.34), (-0.50, 0.34)],
        "poroes": [(-0.44, -0.22), (0.44, -0.22), (0.44, 0.22), (-0.44, 0.22)],
        "cabine": [(-0.14, -0.20), (0.12, -0.20), (0.12, 0.20), (-0.14, 0.20)],
        "mastro": ((-0.01, -0.20), (-0.01, -0.46)),
    },
}

ICONES_PADRAO = {
    "casco": [(-0.5, -0.28), (0.5, -0.28), (0.5, 0.28), (-0.5, 0.28)],
    "poroes": [(-0.2, -0.12), (0.2, -0.12), (0.2, 0.12), (-0.2, 0.12)],
    "cabine": [(-0.3, -0.12), (-0.1, -0.12), (-0.1, 0.12), (-0.3, 0.12)],
    "mastro": None,
}

#: Comprimento do casco em pixels, por tipo de embarcacao.
COMPRIMENTO_ICONE = {"PRINCIPAL": 26.0, "LANCHA": 19.0, "RIBEIRINHO": 15.0}
LARGURA_ICONE = {"PRINCIPAL": 15.0, "LANCHA": 11.0, "RIBEIRINHO": 13.0}


# ---------------------------------------------------------------------------
# 3b. DIALOGO INLINE — ADICIONAR EMBARCACAO
# ---------------------------------------------------------------------------
class DialogoAdicionarEmbarcacao:
    """
    Painel flutuante modal (pygame puro) para configurar e adicionar uma nova
    embarcacao a frota durante a simulacao.

    A Aplicacao deve verificar `self._dialogo_frota` a cada quadro e, se nao
    for None, chamar `dialogo.desenhar(tela)` e `dialogo.evento(ev)`. Quando
    `dialogo.concluido` for True, `dialogo.resultado` contem os parametros
    escolhidos (ou None se o utilizador cancelou).
    """

    TIPOS = ("PRINCIPAL", "LANCHA", "RIBEIRINHO")
    LARGURA = 320
    ALTURA = 210

    def __init__(self, app: "Aplicacao") -> None:
        self.app = app
        self.concluido = False
        self.resultado: dict | None = None
        self._tipo_idx = 0          # indice em TIPOS
        self._km = 50.0             # km inicial
        self._sentido = 1           # 1=jusante, -1=montante
        self._arrastando_slider = False
        # posicao centrada na janela
        self._x = (LARGURA_TOTAL - self.LARGURA) // 2
        self._y = (ALTURA_TOTAL - self.ALTURA) // 2

    # -- geometria interna -----------------------------------------------
    def _rect(self) -> pygame.Rect:
        return pygame.Rect(self._x, self._y, self.LARGURA, self.ALTURA)

    def _btn(self, nome: str) -> pygame.Rect:
        """Retangulos dos botoes de acao na parte inferior."""
        if nome == "ok":
            return pygame.Rect(self._x + self.LARGURA - 160, self._y + self.ALTURA - 38, 68, 28)
        if nome == "cancelar":
            return pygame.Rect(self._x + self.LARGURA - 84, self._y + self.ALTURA - 38, 74, 28)
        if nome == "tipo_ant":
            return pygame.Rect(self._x + 16, self._y + 58, 24, 24)
        if nome == "tipo_prox":
            return pygame.Rect(self._x + self.LARGURA - 40, self._y + 58, 24, 24)
        if nome == "sentido":
            return pygame.Rect(self._x + 16, self._y + 98, self.LARGURA - 32, 24)
        return pygame.Rect(0, 0, 0, 0)

    def _slider_rect(self) -> pygame.Rect:
        """Faixa do slider de km."""
        return pygame.Rect(self._x + 16, self._y + 138, self.LARGURA - 32, 16)

    # -- eventos ---------------------------------------------------------
    def evento(self, ev: pygame.event.Event) -> None:
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = ev.pos
            if self._btn("ok").collidepoint(pos):
                self.resultado = {
                    "tipo": self.TIPOS[self._tipo_idx],
                    "km": self._km,
                    "sentido": self._sentido,
                }
                self.concluido = True
            elif self._btn("cancelar").collidepoint(pos):
                self.resultado = None
                self.concluido = True
            elif self._btn("tipo_ant").collidepoint(pos):
                self._tipo_idx = (self._tipo_idx - 1) % len(self.TIPOS)
            elif self._btn("tipo_prox").collidepoint(pos):
                self._tipo_idx = (self._tipo_idx + 1) % len(self.TIPOS)
            elif self._btn("sentido").collidepoint(pos):
                self._sentido = -self._sentido
            elif self._slider_rect().collidepoint(pos):
                self._arrastando_slider = True
                self._atualizar_km(pos[0])
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self._arrastando_slider = False
        elif ev.type == pygame.MOUSEMOTION and self._arrastando_slider:
            self._atualizar_km(ev.pos[0])
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.resultado = None
                self.concluido = True
            elif ev.key == pygame.K_RETURN:
                self.resultado = {
                    "tipo": self.TIPOS[self._tipo_idx],
                    "km": self._km,
                    "sentido": self._sentido,
                }
                self.concluido = True

    def _atualizar_km(self, mouse_x: int) -> None:
        sr = self._slider_rect()
        frac = max(0.0, min(1.0, (mouse_x - sr.x) / sr.width))
        self._km = frac * CANAL_PRINCIPAL.comprimento_km

    # -- desenho ---------------------------------------------------------
    def desenhar(self, tela: pygame.Surface) -> None:
        f_tit = pygame.font.SysFont(FAMILIA_FONTE, 14, bold=True)
        f_txt = pygame.font.SysFont(FAMILIA_FONTE, 12)
        f_btn = pygame.font.SysFont(FAMILIA_FONTE, 13, bold=True)

        # fundo com sombra
        sombra = pygame.Surface((self.LARGURA + 6, self.ALTURA + 6), pygame.SRCALPHA)
        sombra.fill((0, 0, 0, 90))
        tela.blit(sombra, (self._x + 4, self._y + 4))

        # painel principal
        pygame.draw.rect(tela, (22, 30, 44), self._rect(), border_radius=8)
        pygame.draw.rect(tela, (255, 214, 92), self._rect(), 2, border_radius=8)

        # título
        tela.blit(f_tit.render("Adicionar Embarcação", True, (255, 240, 200)),
                  (self._x + 16, self._y + 12))

        # selector de tipo
        tela.blit(f_txt.render("Tipo:", True, (170, 185, 210)),
                  (self._x + 16, self._y + 40))
        tipo_str = self.TIPOS[self._tipo_idx]
        pygame.draw.rect(tela, (38, 50, 68),
                         pygame.Rect(self._x + 44, self._y + 58, self.LARGURA - 88, 24),
                         border_radius=4)
        tela.blit(f_tit.render(tipo_str, True, (255, 200, 100)),
                  (self._x + self.LARGURA // 2 - f_tit.size(tipo_str)[0] // 2, self._y + 61))
        for nome, seta in (("tipo_ant", "◄"), ("tipo_prox", "►")):
            b = self._btn(nome)
            pygame.draw.rect(tela, (50, 65, 88), b, border_radius=3)
            pygame.draw.rect(tela, (120, 140, 170), b, 1, border_radius=3)
            tela.blit(f_btn.render(seta, True, (220, 235, 255)), (b.x + 4, b.y + 3))

        # selector de sentido
        sb = self._btn("sentido")
        pygame.draw.rect(tela, (38, 50, 68), sb, border_radius=4)
        pygame.draw.rect(tela, (90, 110, 140), sb, 1, border_radius=4)
        sent_str = "Sentido: Jusante (→ Itacoatiara)" if self._sentido > 0 else "Sentido: Montante (← Manaus)"
        tela.blit(f_txt.render(sent_str, True, (200, 220, 245)), (sb.x + 8, sb.y + 5))

        # slider de km
        tela.blit(f_txt.render(f"Posição inicial: km {self._km:.0f}", True, (170, 185, 210)),
                  (self._x + 16, self._y + 124))
        sr = self._slider_rect()
        pygame.draw.rect(tela, (38, 48, 64), sr, border_radius=4)
        pygame.draw.rect(tela, (80, 100, 130), sr, 1, border_radius=4)
        frac = self._km / max(1.0, CANAL_PRINCIPAL.comprimento_km)
        thumb_x = int(sr.x + frac * sr.width)
        pygame.draw.rect(tela, (255, 214, 92),
                         pygame.Rect(thumb_x - 5, sr.y - 2, 10, sr.height + 4),
                         border_radius=3)

        # botões OK / Cancelar
        for nome, txt, cor_f, cor_b in [
            ("ok", "Adicionar", (34, 96, 74), (60, 220, 130)),
            ("cancelar", "Cancelar", (80, 28, 28), (220, 100, 80)),
        ]:
            b = self._btn(nome)
            pygame.draw.rect(tela, cor_f, b, border_radius=4)
            pygame.draw.rect(tela, cor_b, b, 1, border_radius=4)
            s = f_btn.render(txt, True, cor_b)
            tela.blit(s, (b.centerx - s.get_width() // 2, b.centery - s.get_height() // 2))


def _mistura(cor, fator: float) -> tuple[int, int, int]:
    """Clareia (fator > 1) ou escurece (fator < 1) uma cor."""
    return tuple(max(0, min(255, int(round(c * fator)))) for c in cor)


# ---------------------------------------------------------------------------
# 4. CAMADAS
# ---------------------------------------------------------------------------
NOMES_CAMADAS = (
    "base_carta", "curvas_batimetricas", "sondagens", "relevo_sombreado",
    "limites_canal", "base_satelite", "batimetria", "rotas", "supernos",
    "obstaculos", "frota", "rastros", "circulos_alcance", "contatos",
    "grade_geografica", "legenda", "metadados",
    "efeitos_rota", "fluxo_rota", "marcos_km", "minimapa",
)

ROTULOS_CAMADAS = {
    "base_carta": "Folha de carta nautica",
    "curvas_batimetricas": "Curvas de cote",
    "sondagens": "Sondagens",
    "relevo_sombreado": "Relevo sombreado (ilustrativo)",
    "limites_canal": "Limites navegaveis",
    "base_satelite": "Base de satelite",
    "batimetria": "Tinta de profundidade (para o satelite)",
    "rotas": "Rotas / hidrovia",
    "supernos": "Supernos de gateway",
    "obstaculos": "Obstaculos e baixios",
    "frota": "Frota",
    "rastros": "Rastro das embarcacoes",
    "circulos_alcance": "Circulos de alcance",
    "contatos": "Contatos ativos",
    "grade_geografica": "Grade geografica",
    "legenda": "Legenda",
    "metadados": "Quadro de metricas",
    "efeitos_rota": "Efeitos de rota (brilho)",
    "fluxo_rota": "Fluxo animado na rota",
    "marcos_km": "Marcos de quilometragem",
    "minimapa": "Minimapa",
}


@dataclass
class Camadas:
    """Liga e desliga as camadas desenhaveis da carta e do mapa."""

    base_carta: bool = False
    curvas_batimetricas: bool = True
    sondagens: bool = True
    relevo_sombreado: bool = True
    limites_canal: bool = True
    base_satelite: bool = True
    batimetria: bool = False
    rotas: bool = True
    supernos: bool = True
    obstaculos: bool = True
    frota: bool = True
    rastros: bool = True
    circulos_alcance: bool = True
    contatos: bool = True
    legenda: bool = True
    metadados: bool = True
    grade_geografica: bool = True
    efeitos_rota: bool = True
    fluxo_rota: bool = True
    marcos_km: bool = True
    minimapa: bool = True

    def para_opcoes(self, escala: float) -> OpcoesCarta:
        return OpcoesCarta(
            escala=escala,
            base_carta=self.base_carta,
            base_satelite=self.base_satelite,
            curvas_batimetricas=self.curvas_batimetricas,
            sondagens=self.sondagens,
            relevo_sombreado=self.relevo_sombreado,
            limites_canal=self.limites_canal,
            batimetria=self.batimetria,
            grade_geografica=self.grade_geografica,
            rastro_frota=self.rastros,
            circulos_alcance=self.circulos_alcance,
            legenda=self.legenda,
            quadro_metadados=self.metadados,
        )


# ---------------------------------------------------------------------------
# 5. MENUS
# ---------------------------------------------------------------------------
@dataclass
class ItemMenu:
    rotulo: str
    acao: Callable[[], None] | None = None
    marcado: Callable[[], bool] | None = None
    separador: bool = False
    checkbox: bool = False


@dataclass
class Menu:
    titulo: str
    itens: list[ItemMenu] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 6. APLICACAO
# ---------------------------------------------------------------------------
class Aplicacao:
    """Janela principal do simulador."""

    def __init__(self, cfg: ConfiguracaoDTN) -> None:
        self.cfg = cfg
        self.camadas = Camadas()
        self.motor = MotorDTN(cfg)
        self.mosaico = MosaicoTiles()
        self.visao = Visao()
        #: Camadas de tiles do mapa de fundo (slippy map). O satelite e o
        #: padrao; `mapa_estilo` troca para o mapa de ruas do OpenStreetMap.
        #: `mapa_online` libera o download dos niveis de zoom que ainda nao
        #: estao em disco; desligado, o simulador usa so o que ja esta na pasta
        #: e continua rodando sem rede.
        self.camada_satelite = CamadaTiles(PROVEDOR_SATELITE, permitir_rede=True)
        self.camada_ruas = CamadaTiles(PROVEDOR_RUAS, permitir_rede=True)
        self.mapa_online = True
        self.mapa_estilo = "satelite"

        self.rodando = False
        self.indice_velocidade = 2   # indice em VELOCIDADES
        self.velocidade_efetiva = 0.0  # passos/s medidos, para o painel
        self.mensagem = ""
        self.mensagem_ate = 0
        self._acumulado = 0.0

        # superficies de trabalho
        self._base: pygame.Surface | None = None
        self._base_chave: tuple | None = None
        self._base_1x: pygame.Surface | None = None
        self._base_recorte_cache: tuple | None = None
        self._tile_recorte_cache: tuple | None = None
        self._minimapa: pygame.Surface | None = None
        self._sat_cache: Image.Image | None = None
        self._scratch: pygame.Surface | None = None
        self._caminhos: dict[int, tuple] = {}
        #: Mosaicos de tiles ja convertidos para superficie do pygame, por
        #: (id da camada, versao, z, faixa de tiles).
        self._cache_mosaico: dict[tuple, pygame.Surface] = {}
        #: Credito do provedor de tiles do fundo, ou vazio quando o fundo nao
        #: vem de tiles (carta, por exemplo).
        self._credito_mapa = ""
        self._credito_cache: tuple[str, pygame.Surface] | None = None

        # caches de rasterizacao
        self._cache_texto: dict[tuple, pygame.Surface] = {}
        self._cache_icones: dict[tuple, pygame.Surface] = {}
        self._cache_proa: dict[tuple, float] = {}

        self._menu_aberto: int | None = None
        self._carta: pygame.Surface | None = None
        self._carta_cheia: pygame.Surface | None = None
        self._arrastando = False
        self._arrastou = False
        self._pressao = (0, 0)
        self._arrastar_ultimo = (0, 0)

        #: Embarcacao cujo status de coleta esta aberto na ficha sobre o mapa.
        #: Guarda o id, e nao o objeto, porque reiniciar recria a frota.
        self.selecionado_id: int | None = None
        self._linhas_frota: list[tuple[pygame.Rect, int]] = []
        self._frota_scroll = 0
        self._ficha: pygame.Surface | None = None
        self._ficha_chave: tuple | None = None
        self._dialogo_frota: DialogoAdicionarEmbarcacao | None = None

        #: Posicao corrente do cursor (x, y), usada para tooltips de hover.
        self._pos_mouse: tuple[int, int] = (0, 0)
        #: Tooltip de hover do superno (Surface, pos), ou None.
        self._tooltip_sn: tuple[pygame.Surface, tuple[int, int]] | None = None

        pygame.init()
        pygame.display.set_caption("FLoRA-DTN  |  Simulador DTN-LoRa - Calha do Amazonas (UFAM)")
        self.tela = pygame.display.set_mode((LARGURA_TOTAL, ALTURA_TOTAL))
        self.relogio = pygame.time.Clock()
        self.f_titulo = _fonte(17, True)
        self.f_menu = _fonte(15)
        self.f_painel = _fonte(13)
        self.f_painel_t = _fonte(13, True)
        self.f_pequena = _fonte(12)
        self.menus = self._montar_menus()
        self._larguras_menu = [self.f_menu.size(m.titulo)[0] + 30 for m in self.menus]
        self._hint = self.f_pequena.render(
            "Carta nautica  |  S: salvar PNG   ESC: voltar", True, DESTAQUE)
        # aquece a malha de distancias, que nao muda durante a sessao
        grade_profundidade(self.motor.cenario, 0.0, NX_BATI, NY_BATI)

    # -- ciclo principal -------------------------------------------------
    def executar(self) -> None:
        try:
            while self._quadro():
                pass
        finally:
            pygame.quit()

    def _quadro(self) -> bool:
        """Um quadro do laco principal. Retorna False para encerrar."""
        dt = min(0.1, self.relogio.tick(60) / 1000.0)
        if not self._processar_eventos():
            return False
        if self.rodando:
            self._avancar(dt)
        self._desenhar()
        pygame.display.flip()
        return True

    @property
    def velocidade(self) -> int:
        """Vazao pedida, em passos de simulacao por segundo real."""
        return VELOCIDADES[self.indice_velocidade]

    @property
    def passos_por_segundo(self) -> int:
        return VELOCIDADES[self.indice_velocidade]

    @property
    def horas_por_segundo(self) -> float:
        return self.velocidade * self.cfg.passo_s / 3600.0

    def _avancar(self, dt: float) -> None:
        """
        Executa passos de duracao fixa com orcamento de tempo por quadro.

        `velocidade` e a vazao pedida em passos por segundo real. O orcamento
        impede que a interface trave: quando a maquina nao da conta da vazao
        pedida, a interface continua a 60 fps e o painel informa a vazao
        efetivamente alcancada. A suavizacao do desenho nao entra aqui: este
        metodo so move o modelo, e a posicao extrapolada e calculada no quadro.
        """
        self._acumulado += dt * self.passos_por_segundo
        pedidos = int(self._acumulado)
        if pedidos <= 0:
            return
        limite = self.cfg.horizonte_h * 3600.0
        inicio = time.perf_counter()
        feitos = 0
        for _ in range(pedidos):
            self.motor.passo()
            feitos += 1
            if self.motor.t_s >= limite:
                self.rodando = False
                self._acumulado = 0.0
                self._avisar("Simulacao concluida.")
                break
            if time.perf_counter() - inicio > ORCAMENTO_PASSOS:
                break
        # o acumulador conta passos, nao segundos de simulacao
        self._acumulado -= feitos
        # nao acumula divida: o que nao coube no quadro e descartado
        self._acumulado = min(self._acumulado, float(self.passos_por_segundo))
        self.velocidade_efetiva = (
            feitos / dt if dt > 0 else 0.0
        )

    def _suavizar_frota(self) -> None:
        """
        Posiciona o casco no ponto do eixo correspondente ao instante atual.

        A simulacao avanca em passos de `passo_s` e a tela corre a 60 quadros por
        segundo: quando o ritmo pedido fica abaixo de 60 passos/s, ha quadros sem
        nenhum passo do modelo e o casco dava um salto e ficava parado. O filtro
        exponencial anterior resolvia o tremor, mas pagava com atraso: o casco
        desenhado perseguia o modelo e ficava alguns quadros para tras, o que se
        via como uma embarcacao "pesada".

        A suavizacao agora e uma extrapolacao pela velocidade, e nao um filtro:
        dentro de um passo, o tempo real decorrido desde o ultimo avanco do modelo
        vira uma fracao do passo (0 a 1), e o casco anda
        `velocidade * passo_s * fracao`. Quando o modelo avanca, a fracao volta a
        zero e a posicao do modelo ja incluiu o passo inteiro, de modo que a
        trajetoria desenhada e continua e nao ha atraso medio. A fracao e
        limitada a um passo para uma maquina lenta nao projetar o casco adiante
        demais, e o km e preso as pontas do canal para a extrapolacao nao cruzar
        a volta.

        A posicao continua sendo reconstruida por `posicao_em` a partir de um km,
        e nao interpolada em pixels: e isso que mantem o casco sobre o eixo do
        rio, inclusive nas curvas.
        """
        agora = time.perf_counter()
        # um passo do modelo e um avanco de `passo_s` segundos simulados; a taxa
        # nominal (passos/s) da o intervalo real entre dois avancos
        intervalo = 1.0 / max(1.0, float(self.passos_por_segundo))
        passo_km = self.cfg.passo_s / 3600.0
        for no in self.motor.frota:
            km_modelo = getattr(no, "_km_modelo", None)
            if km_modelo is None or no.km_atual != km_modelo:
                # a volta no fim do canal cai aqui como qualquer outro avanco:
                # nao ha filtro acumulado para arrastar na direcao antiga
                no._km_modelo = no.km_atual
                no._km_modelo_ts = agora
                km_modelo = no.km_atual
            if not self.rodando:
                # parado, o desenho fica exatamente no modelo; zerar o relogio
                # evita um salto de um passo quando a simulacao voltar
                no._km_modelo_ts = agora
                km = km_modelo
            else:
                fracao = (agora - getattr(no, "_km_modelo_ts", agora)) / intervalo
                fracao = min(1.0, max(0.0, fracao))
                km = km_modelo + no.velocidade_km_h * no.sentido * passo_km * fracao
            km = min(no.canal.comprimento_km, max(0.0, km))
            no._km_desenho = km
            no._pos_desenho_cache = no.canal.posicao_em(
                km, no.offset_faixa_km)[0]

    def _pos_desenho(self, no) -> np.ndarray:
        """Posicao suavizada da embarcacao, ou a do modelo se ainda nao houve quadro."""
        return getattr(no, "_pos_desenho_cache", None) if \
            getattr(no, "_pos_desenho_cache", None) is not None else no.pos

    # -- eventos ---------------------------------------------------------
    def _processar_eventos(self) -> bool:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return False
            # dialogo modal de frota tem prioridade sobre todos os outros eventos
            if self._dialogo_frota is not None:
                self._dialogo_frota.evento(ev)
                if self._dialogo_frota.concluido:
                    res = self._dialogo_frota.resultado
                    self._dialogo_frota = None
                    if res is not None:
                        no = self.motor.adicionar_embarcacao(
                            res["tipo"], res["km"], res["sentido"])
                        self.selecionado_id = no.id
                        self._avisar(
                            f"{no.nome_tipo} ID {no.id} adicionada em km {res['km']:.0f}.")
                continue
            if ev.type == pygame.KEYDOWN:
                if not self._tecla(ev):
                    return False
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                if ev.button == 4:
                    if self._roda_sobre_painel(ev.pos):
                        self._rolar_frota(-1)
                    else:
                        self._zoom_roda(ev.pos, 1.0)
                elif ev.button == 5:
                    if self._roda_sobre_painel(ev.pos):
                        self._rolar_frota(1)
                    else:
                        self._zoom_roda(ev.pos, -1.0)
                elif ev.button == 1:
                    if self._iniciar_arrasto(ev.pos):
                        # o mapa aceita arrasto e clique: so se decide no
                        # MOUSEBUTTONUP, com base em quanto o cursor andou
                        self._arrastando = True
                        self._arrastou = False
                        self._arrastar_ultimo = ev.pos
                        self._pressao = ev.pos
                    else:
                        self._clique(ev.pos)
                elif ev.button == 3:
                    self._zoom_roda(ev.pos, -1.0)
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if self._arrastando:
                    self._arrastando = False
                    if not self._arrastou:
                        # clique de verdade: seleciona a embarcacao
                        self._clique(self._pressao)
            elif ev.type == pygame.MOUSEMOTION:
                self._pos_mouse = ev.pos
                if self._arrastando:
                    dx = ev.pos[0] - self._arrastar_ultimo[0]
                    dy = ev.pos[1] - self._arrastar_ultimo[1]
                    if not self._arrastou and abs(dx) + abs(dy) > LIMITE_ARRASTO_PX:
                        self._arrastou = True
                    if self._arrastou:
                        self.visao.deslocar(dx, dy)
                    self._arrastar_ultimo = ev.pos
        return True

    def _iniciar_arrasto(self, pos) -> bool:
        """So a area do mapa aceita arrasto; a barra de menus usa clique."""
        return (self._carta is None and pos[1] >= ALTURA_MENU
                and pos[0] < LARGURA_SIMULACAO_BASE)

    def _roda_sobre_painel(self, pos) -> bool:
        return self._carta is None and pos[0] >= LARGURA_SIMULACAO_BASE

    def _rolar_frota(self, delta: int) -> None:
        self._frota_scroll = max(0, self._frota_scroll + delta)

    def _zoom_roda(self, pos, direcao: float) -> None:
        if self._carta is not None or pos[1] < ALTURA_MENU:
            return
        if pos[0] >= LARGURA_SIMULACAO_BASE:
            return
        if direcao > 0:
            self.visao.aproximar(Visao.FATO_RODA, pos)
        else:
            self.visao.afastar(Visao.FATO_RODA, pos)

    def _tecla(self, ev) -> bool:
        if self._carta is not None:
            if ev.key in (pygame.K_ESCAPE, pygame.K_c):
                self._carta = None
                self._restaurar_titulo()
            elif ev.key == pygame.K_s:
                caminho = self._salvar_carta_dialogo()
                if caminho:
                    self._salvar_em(caminho)
            return True
        if ev.key == pygame.K_s and pygame.key.get_mods() & pygame.KMOD_CTRL:
            self._gerar_e_salvar()
            return True
        acoes = {
            pygame.K_SPACE: self._alternar_execucao,
            pygame.K_RIGHT: self._passo,
            pygame.K_r: self._reiniciar,
            pygame.K_c: self._alternar_carta,
            pygame.K_ESCAPE: self._fechar_menu_ou_limpar,
            pygame.K_EQUALS: lambda: self._zoom_tecla(1),
            pygame.K_PLUS: lambda: self._zoom_tecla(1),
            pygame.K_MINUS: lambda: self._zoom_tecla(-1),
            pygame.K_KP_PLUS: lambda: self._zoom_tecla(1),
            pygame.K_KP_MINUS: lambda: self._zoom_tecla(-1),
            pygame.K_0: self._reenquadrar,
            pygame.K_KP0: self._reenquadrar,
            pygame.K_1: lambda: self._trocar_protocolo("epidemico"),
            pygame.K_2: lambda: self._trocar_protocolo("spray"),
            pygame.K_3: lambda: self._trocar_protocolo("flora"),
            pygame.K_4: lambda: self._trocar_protocolo("slp"),
            pygame.K_5: lambda: self._trocar_protocolo("sc"),
        }
        acao = acoes.get(ev.key)
        if acao is not None:
            acao()
        return True

    def _zoom_tecla(self, direcao: int) -> None:
        if direcao > 0:
            self.visao.aproximar(1.5)
        else:
            self.visao.afastar(1.5)
        self._avisar(f"Zoom {self.visao.zoom:.2f}x")

    def _fechar_menu_ou_limpar(self) -> None:
        """Esc fecha o dropdown; se ja estiver fechado, limpa a selecao."""
        if self._menu_aberto is not None:
            self._menu_aberto = None
        elif self.selecionado_id is not None:
            self.selecionado_id = None
            self._avisar("Selecao limpa.")

    def _reenquadrar(self) -> None:
        self._menu_aberto = None
        self.visao.reenquadrar()
        self._avisar("Visao reenquadrada.")

    def _clique(self, pos) -> None:
        if self._carta is not None:
            self._carta = None
            self._restaurar_titulo()
            return
        # 1. botoes da barra de acoes: prioridade maxima, nao ha menu envolvido
        acao = self._botao_em(pos)
        if acao is not None:
            acao()
            return
        # 2. titulo de menu: alterna. Sem esta checagem antes do dropdown, um
        #    clique no titulo caia no caso "fora do dropdown", fechava o menu e
        #    exigia um segundo clique para reabrir: era o que parecia travado.
        if pos[1] < ALTURA_MENU:
            x = 8
            for i, larg in enumerate(self._larguras_menu):
                if x - 6 <= pos[0] <= x + larg:
                    self._menu_aberto = None if self._menu_aberto == i else i
                    return
                x += larg
            self._menu_aberto = None
            return
        # 3. item do dropdown aberto
        if self._menu_aberto is not None:
            menu = self.menus[self._menu_aberto]
            item = self._item_em(menu, self._menu_aberto, pos)
            if item is not None and not item.separador and item.acao is not None:
                item.acao()
                if not item.checkbox:
                    self._menu_aberto = None
            elif item is not None and item.separador:
                pass
            else:
                self._menu_aberto = None
            return
        # 4. linha da frota no painel
        for caixa, id_no in self._linhas_frota:
            if caixa.collidepoint(pos):
                self.selecionado_id = id_no
                self._ficha_chave = None
                self._avisar(f"Embarcacao {id_no} selecionada.")
                return
        # 5. embarcacao no mapa
        self._selecionar_em(pos)

    # -- barra de acoes ---------------------------------------------------
    def _botoes_acao(self) -> list[tuple[pygame.Rect, str, bool]]:
        """
        Botoes da barra superior, como (caixa, chave, eh_principal).

        O layout e derivado so de constantes, entao a deteccao de clique e o
        desenho sempre concordam, mesmo antes do primeiro quadro.
        """
        alt = ALTURA_MENU - 12
        y = 6
        rotulo = "Iniciar" if not self.rodando else "Parar"
        larg_principal = self.f_menu.size(rotulo)[0] + 40
        larg_menor = 30
        larg_veloc = self.f_menu.size(str(self.velocidade))[0] + 30
        caixas = []
        x = LARGURA_TOTAL - 12
        # medidos de traz para frente, para que cada botao reserve a propria largura
        specs = [
            ("reiniciar", "Reiniciar", False, self.f_menu.size("Reiniciar")[0] + 26),
            ("passo", "Passo", False, self.f_menu.size("Passo")[0] + 26),
            ("executar", rotulo, True, larg_principal),
            ("mais_rapido", "+", False, larg_menor),
            ("velocidade", str(self.velocidade), False, larg_veloc),
            ("mais_devagar", "-", False, larg_menor),
        ]
        for chave, _txt, principal, larg in specs:
            x -= larg
            caixas.append((pygame.Rect(x, y, larg, alt), chave, principal))
            x -= 6
        return list(reversed(caixas))

    def _botao_em(self, pos):
        for caixa, chave, _ in self._botoes_acao():
            if not caixa.collidepoint(pos):
                continue
            if chave == "velocidade":
                return None      # e so um indicador, nao um comando
            return {
                "executar": self._alternar_execucao,
                "passo": self._passo,
                "reiniciar": self._reiniciar,
                "mais_rapido": lambda: self._mudar_velocidade(1),
                "mais_devagar": lambda: self._mudar_velocidade(-1),
            }[chave]
        return None

    # -- selecao de embarcacao -------------------------------------------
    def _selecionar_em(self, pos) -> None:
        """Seleciona a embarcacao mais proxima do clique, dentro do mapa."""
        melhor = None
        melhor_d2 = RAIO_SELECAO_PX ** 2
        for no in self.motor.frota:
            u, v = self.visao.para_base(no.pos)
            if not self.visao.visivel(u, v, 12):
                continue
            x, y = self.visao.para_tela(no.pos)
            d2 = (x - pos[0]) ** 2 + (y - pos[1]) ** 2
            if d2 < melhor_d2:
                melhor, melhor_d2 = no, d2
        if melhor is None:
            if self.selecionado_id is not None:
                self.selecionado_id = None
                self._avisar("Selecao limpa.")
            return
        self.selecionado_id = melhor.id
        self._ficha_chave = None
        self._avisar(f"Embarcacao {melhor.id} - {melhor.nome_tipo}.")

    def _embarcacao_selecionada(self):
        if self.selecionado_id is None:
            return None
        for no in self.motor.frota:
            if no.id == self.selecionado_id:
                return no
        return None

    def _item_em(self, menu: Menu, indice: int, pos) -> ItemMenu | None:
        """Retorna o item do menu aberto sob o cursor, se houver."""
        for caixa, item in self._caixas_dropdown(menu, indice):
            if caixa.collidepoint(pos):
                return item
        return None

    def _caixas_dropdown(self, menu: Menu, indice: int) -> list[tuple[pygame.Rect, ItemMenu]]:
        x = 8
        for k, larg in enumerate(self._larguras_menu):
            if k == indice:
                break
            x += larg
        caixas = []
        y = ALTURA_MENU + 4
        larg = self._largura_dropdown(menu)
        for item in menu.itens:
            alt = (20 if item.rotulo else 9) if item.separador else 26
            caixas.append((pygame.Rect(x, y, larg, alt), item))
            y += alt
        return caixas

    def _largura_dropdown(self, menu: Menu) -> int:
        maior = max((self.f_menu.size(i.rotulo)[0] for i in menu.itens), default=140)
        return max(200, maior + 56)

    # -- acoes dos menus -------------------------------------------------
    def _montar_menus(self) -> list[Menu]:
        def cam(nome): return ItemMenu(
            ROTULOS_CAMADAS[nome],
            (lambda nn=nome: self._alternar_camada(nn)),
            marcado=(lambda nn=nome: getattr(self.camadas, nn)),
            checkbox=True)

        return [
            Menu("Simulação", [
                ItemMenu("Iniciar / Pausar   [Espaço]", self._alternar_execucao),
                ItemMenu("Passo único   [→]", self._passo),
                ItemMenu("", separador=True),
                ItemMenu("Mais rápido   [+]", lambda: self._mudar_velocidade(1)),
                ItemMenu("Mais devagar   [-]", lambda: self._mudar_velocidade(-1)),
                ItemMenu("", separador=True),
                ItemMenu("Reiniciar (mesma semente)   [R]", self._reiniciar),
                ItemMenu("Nova semente", self._nova_semente),
            ]),
            Menu("Cenário", [
                ItemMenu(f"{c} — {obter_cenario(c).nome}",
                         (lambda cc=c: self._trocar_cenario(cc)),
                         marcado=(lambda cc=c: self.motor.cenario.codigo == cc))
                for c in ("C1", "C2", "C3")
            ]),
            Menu("Protocolo", [
                ItemMenu(p, (lambda pp=p: self._trocar_protocolo(pp)),
                         marcado=(lambda pp=p: self.motor.protocolo.nome == pp))
                for p in ("epidemico", "spray", "flora", "slp", "sc")
            ]),
            Menu("Visão", [
                ItemMenu("Aproximar   [+ / roda]", self._zoom_tecla_mais),
                ItemMenu("Afastar   [- / roda]", self._zoom_tecla_menos),
                ItemMenu("Reenquadrar   [0]", self._reenquadrar),
                ItemMenu("", separador=True),
                ItemMenu("Minimapa", self._alternar_minimapa,
                         marcado=lambda: self.camadas.minimapa, checkbox=True),
            ]),
            Menu("Camadas", [
                # --- Base ---
                ItemMenu("— BASE —", separador=True),
                cam("base_carta"),
                cam("base_satelite"),
                ItemMenu("Mapa online (tiles detalhados)",
                         self._alternar_mapa_online,
                         marcado=lambda: self.mapa_online, checkbox=True),
                ItemMenu("Mapa de ruas (OSM)",
                         self._alternar_mapa_estilo,
                         marcado=lambda: self.mapa_estilo == "ruas",
                         checkbox=True),
                cam("batimetria"),
                # --- Hidrografia ---
                ItemMenu("— HIDROGRAFIA —", separador=True),
                cam("curvas_batimetricas"),
                cam("sondagens"),
                cam("relevo_sombreado"),
                cam("limites_canal"),
                # --- DTN / LoRa ---
                ItemMenu("— DTN / LoRa —", separador=True),
                cam("supernos"),
                cam("frota"),
                cam("rastros"),
                cam("circulos_alcance"),
                cam("contatos"),
                # --- Cartografia ---
                ItemMenu("— CARTOGRAFIA —", separador=True),
                cam("grade_geografica"),
                cam("marcos_km"),
                cam("efeitos_rota"),
                cam("fluxo_rota"),
                cam("legenda"),
                cam("metadados"),
                cam("minimapa"),
            ]),
            Menu("Exportar", [
                ItemMenu("Gerar carta náutica   [C]", self._alternar_carta),
                ItemMenu("Salvar carta como PNG...", self._gerar_e_salvar),
                ItemMenu("Salvar no diretório padrão", self._salvar_padrao),
                ItemMenu("", separador=True),
                ItemMenu("Exportar simulação completa (1 JSON)",
                         self._exportar_simulacao),
                ItemMenu("Exportar métricas CSV", self._exportar_metricas),
                ItemMenu("Exportar frota CSV", self._exportar_frota),
                ItemMenu("Exportar config JSON", self._exportar_config),
                ItemMenu("Exportar tudo", self._exportar_tudo),
            ]),
            Menu("Frota", [
                ItemMenu("Adicionar embarcação...", self._abrir_dialogo_adicionar),
                ItemMenu("Remover embarcação selecionada", self._remover_selecionada),
                ItemMenu("", separador=True),
                ItemMenu("Limpar seleção   [Esc]", self._limpar_selecao),
            ]),
            Menu("Ajuda", [
                ItemMenu("Atalhos de teclado", self._mostrar_atalhos),
                ItemMenu("Sobre", self._mostrar_sobre),
            ]),
        ]

    # -- acoes -----------------------------------------------------------
    def _zoom_tecla_mais(self) -> None:
        self._menu_aberto = None
        self._zoom_tecla(1)

    def _zoom_tecla_menos(self) -> None:
        self._menu_aberto = None
        self._zoom_tecla(-1)

    def _alternar_minimapa(self) -> None:
        self._menu_aberto = None
        self.camadas.minimapa = not self.camadas.minimapa

    def _limpar_selecao(self) -> None:
        self._menu_aberto = None
        self.selecionado_id = None
        self._avisar("Selecao limpa.")

    def _alternar_execucao(self) -> None:
        self._menu_aberto = None
        self.rodando = not self.rodando
        self._acumulado = 0.0
        self._avisar("Em execucao." if self.rodando else "Pausado.")

    def _passo(self) -> None:
        self._menu_aberto = None
        self.motor.passo()
        self._avisar(f"Passo executado. t = {self.motor.t_s / 3600.0:.1f} h")

    def _mudar_velocidade(self, delta: int) -> None:
        antes = self.indice_velocidade
        self.indice_velocidade = max(
            0, min(len(VELOCIDADES) - 1, self.indice_velocidade + delta))
        if self.indice_velocidade != antes:
            # o intervalo real de um passo mudou: reiniciar a fase evita que a
            # extrapolacao antiga projete o casco um passo adiante na troca
            agora = time.perf_counter()
            for no in self.motor.frota:
                no._km_modelo_ts = agora
        # o aviso em segundos simulados por segundo real e legivel em toda a
        # faixa: em horas, os 10 passos/s do piso dabordavam para "0,0 h/s"
        self._avisar(f"Velocidade: {self.velocidade} passos/s "
                     f"({self.velocidade * self.cfg.passo_s:.2f} s simuladas/s)."
                     if self.indice_velocidade != antes else
                     f"Velocidade ja esta no limite: {self.velocidade} passos/s.")

    def _reiniciar(self) -> None:
        self._menu_aberto = None
        self.motor = MotorDTN(self.cfg)
        self.rodando = False
        self._base_chave = None
        self.selecionado_id = None
        self._ficha_chave = None
        self._dialogo_frota = None
        self._avisar("Simulacao reiniciada com a mesma semente.")

    def _nova_semente(self) -> None:
        self.cfg.semente = int(self.cfg.semente) + 1
        self._reiniciar()
        self._avisar(f"Nova semente: {self.cfg.semente}.")

    def _trocar_cenario(self, codigo: str) -> None:
        self.cfg.cenario = codigo
        self._reiniciar()
        self._avisar(f"Cenario {codigo} - {obter_cenario(codigo).nome}.")

    def _trocar_protocolo(self, nome: str) -> None:
        self.cfg.protocolo = nome
        self._reiniciar()
        self._avisar(f"Protocolo: {self.motor.protocolo.nome}.")

    #: Camadas que sao desenhadas dentro da base, entao mudan-las invalida o
    #: cache do raster em vez de so trocar a flag da proxima pintura.
    _CAMADAS_DA_BASE = frozenset({
        "base_carta", "base_satelite", "batimetria", "curvas_batimetricas",
        "sondagens", "relevo_sombreado", "limites_canal",
    })

    def _alternar_camada(self, nome: str) -> None:
        setattr(self.camadas, nome, not getattr(self.camadas, nome))
        if nome in self._CAMADAS_DA_BASE:
            self._base_chave = None
        if nome == "base_carta" and self.camadas.base_carta:
            # folha de carta e satelite sao fundos alternativos, e nao camadas
            # empilhadas: ligar um desliga o outro para nao pagar duas bases
            self.camadas.base_satelite = False
        elif nome == "base_satelite" and self.camadas.base_satelite:
            self.camadas.base_carta = False
        self._avisar(f"{ROTULOS_CAMADAS[nome]}: "
                     f"{'ligado' if getattr(self.camadas, nome) else 'desligado'}")

    def _alternar_mapa_online(self) -> None:
        """Liga/desliga o download dos tiles que faltam (o disco continua)."""
        self.mapa_online = not self.mapa_online
        self.camada_satelite.permitir_rede = self.mapa_online
        self.camada_ruas.permitir_rede = self.mapa_online
        self._cache_mosaico.clear()
        self._avisar("Mapa online: " + (
            "ligado (baixa tiles que faltam)" if self.mapa_online
            else "desligado (usa so os tiles em disco)"))

    def _alternar_mapa_estilo(self) -> None:
        """Troca o fundo entre satelite (Esri) e mapa de ruas (OSM)."""
        self.mapa_estilo = ("ruas" if self.mapa_estilo == "satelite"
                            else "satelite")
        self._cache_mosaico.clear()
        self._credito_mapa = ""
        # escolher um estilo de tiles implica um fundo de tiles: desliga a
        # folha de carta, que e o outro fundo alternativo
        self.camadas.base_satelite = True
        self.camadas.base_carta = False
        self._base_chave = None
        self._avisar("Fundo do mapa: " + (
            "mapa de ruas (OpenStreetMap)" if self.mapa_estilo == "ruas"
            else "satelite (Esri World Imagery)"))

    # -- base cartografica ----------------------------------------------
    def _imagem_satelite(self, w: int, h: int) -> Image.Image | None:
        """
        Recorte do mosaico de satelite, na resolucao nativa dos tiles.

        Depende so do tamanho pedido, entao e cacheado. O recorte e feito na
        resolucao que os arquivos em disco tem, e nao na resolucao da base: os
        tiles cobrem a janela com 7,9 px/km, e pedir 5,1 px/km jogava fora mais da
        metade dos pixels antes de qualquer desenho. Era o satelite que aparecia
        lavado assim que o zoom passava de 1.
        """
        if not self.mosaico.disponivel():
            return None
        if self._sat_cache is None or self._sat_cache.size != (w, h):
            self._sat_cache = self.mosaico.recorte(
                (w, h), (LAT_TOP, LAT_BOTTOM, LONG_LEFT, LONG_RIGHT))
        return self._sat_cache

    def _tamanho_satelite(self, w: int, h: int) -> tuple[int, int]:
        """
        Tamanho do recorte de satelite para uma base de `w` x `h`.

        O mosaico em disco cobre a janela com cerca de 7,9 px/km, e a base e
        desenhada com 5,1 px/km. O recorte e pedido na resolucao do arquivo, e nao
        na da base: pedir 2000 px de largura para um arquivo que so tem 1536
        inventaria detalhe por interpolacao. Aqui a largura e a do proprio
        mosaico, e a altura segue o aspecto da janela para nao distorcer.
        """
        base = self.mosaico.base()
        if base is None:
            return max(1, w), max(1, h)
        alvo = max(1, min(w, base.width))
        return alvo, max(1, min(int(round(h * alvo / max(1, w))), base.height))

    def _construir_base(self) -> pygame.Surface:
        """
        Monta a base do mapa na resolucao `RES_BASE`.

        A folha de carta nautica e o fundo padrao. Ela ja traz a cor da agua
        por profundidade, as curvas de cote, as sondagens e a linha de costa,
        entao a camada `batimetria` continua sendo a paleta de risco, que e
        outra informacao: Onde ha risco de encalhe, e nao Onde ha agua.
        """
        cenario = self.motor.cenario
        t_h = self.motor.t_s / 3600.0
        w = LARGURA_SIMULACAO_BASE * RES_BASE
        h = ALTURA_TELA_BASE * RES_BASE
        # sem tiles em disco o fundo de satelite viraria um retangulo verde
        # vazio; nesse caso a folha de carta e o plano B, e nao uma tela preta
        usar_carta = self.camadas.base_carta or (
            self.camadas.base_satelite and not self.mosaico.disponivel())
        if usar_carta:
            img = desenhar_folha_carta(
                cenario, t_h, (w, h), nx=NX_BATI, ny=NY_BATI,
                curvas=self.camadas.curvas_batimetricas,
                sondagens=self.camadas.sondagens,
                relevo=self.camadas.relevo_sombreado,
                limites_canal=self.camadas.limites_canal,
            )
        else:
            # o satelite entra na resolucao nativa dos tiles e e reamostrado
            # para a base; pedir o recorte no tamanho da base perdia metade dos
            # pixels do arquivo
            img = Image.new("RGB", (w, h), (30, 52, 32))
            sw, sh = self._tamanho_satelite(w, h)
            sat = self._imagem_satelite(sw, sh)
            if sat is not None:
                if sat.size != (w, h):
                    sat = sat.resize((w, h), Image.LANCZOS)
                img.paste(sat, (0, 0))
        if self.camadas.batimetria:
            prof, _la, _lo = grade_profundidade(cenario, t_h, NX_BATI, NY_BATI)
            rgba = Image.fromarray(cor_batimetria(prof), "RGBA").resize(
                (w, h), Image.BILINEAR)
            img = Image.alpha_composite(img.convert("RGBA"), rgba).convert("RGB")
        return pygame.image.frombytes(img.tobytes(), img.size, "RGB")

    def _garantir_base(self) -> pygame.Surface:
        t_h = self.motor.t_s / 3600.0
        # so a folha de carta depende do nivel do rio; o mosaico de satelite e
        # estatico, entao ele nao entra no balde de tempo
        faixa_t = int(t_h // FAIXA_BASE_H) if self.camadas.base_carta else 0
        chave = (self.motor.cenario.codigo, faixa_t,
                 self.camadas.base_carta, self.camadas.base_satelite,
                 self.camadas.batimetria, self.camadas.curvas_batimetricas,
                 self.camadas.sondagens, self.camadas.relevo_sombreado,
                 self.camadas.limites_canal)
        if self._base is None or self._base_chave != chave:
            self._base = self._construir_base()
            self._base_chave = chave
            self._base_1x = None
            self._minimapa = None
            self._base_recorte_cache = None
        return self._base

    def _garantir_base_1x(self) -> pygame.Surface:
        """Versao da base na resolucao da janela, usada sem zoom e no minimapa."""
        if self._base_1x is None:
            self._base_1x = pygame.transform.smoothscale(
                self._garantir_base(),
                (LARGURA_SIMULACAO_BASE, ALTURA_TELA_BASE))
        return self._base_1x

    def _tela_transparente(self) -> pygame.Surface:
        """
        Superficie alpha reaproveitada para os desenhos translucidos.

        Apenas a area do mapa e limpa: o painel e a barra de menus ficam de
        fora, o que corta cerca de metade do trabalho de preenchimento por
        quadro sem alterar o resultado visivel.
        """
        if self._scratch is None:
            self._scratch = pygame.Surface((LARGURA_TOTAL, ALTURA_TOTAL),
                                           pygame.SRCALPHA)
        self._scratch.fill((0, 0, 0, 0), MAPA_RECT)
        return self._scratch

    def _compor_mapa(self, camada: pygame.Surface) -> None:
        """Acrescenta uma camada alpha do mapa sobre a tela."""
        self.tela.blit(camada, (0, ALTURA_MENU), MAPA_RECT)

    # -- geometria das rotas --------------------------------------------
    def _caminho(self, canal) -> tuple[np.ndarray, np.ndarray]:
        """
        Polilinha do canal em coordenadas da base, com comprimentos acumulados.

        Calculado uma vez por canal: o fluxo animado e os marcos de
        quilometragem precisam interpolar ao longo da curva a cada quadro.
        """
        chave = id(canal)
        if chave not in self._caminhos:
            pts = np.asarray(canal.pontos_mundo, dtype=float)
            base = np.column_stack([pts[:, 0], pts[:, 1] - ALTURA_MENU])
            passos = np.hypot(np.diff(base[:, 0]), np.diff(base[:, 1]))
            cum = np.concatenate([[0.0], np.cumsum(passos)])
            self._caminhos[chave] = (cum, base)
        return self._caminhos[chave]

    def _polilinha_tela(self, pts: np.ndarray) -> list[tuple[int, int]]:
        sx, sy = self.visao.projetar(pts[:, 0], pts[:, 1])
        return list(zip(sx.astype(int), sy.astype(int)))

    # -- desenho ---------------------------------------------------------
    def _desenhar(self) -> None:
        if self._carta is not None:
            self.tela.fill(COR_FUNDO)
            self.tela.blit(self._carta, (0, 0))
            return
        # a base cobre o mapa inteiro e o painel cobre a coluna lateral; assim
        # basta limpar a area do mapa, e a barra de menus e desenhada por cima
        self.tela.fill(COR_FUNDO, MAPA_RECT)
        self._suavizar_frota()
        self._desenhar_base()
        self._desenhar_rotas()
        self._desenhar_marcos()
        self._desenhar_obstaculos()
        self._desenhar_contatos()
        self._desenhar_supernos()
        self._desenhar_frota()
        self._desenhar_ficha()
        self._desenhar_minimapa()
        self._desenhar_credito_mapa()
        self._desenhar_painel()
        self._desenhar_menu()
        self._desenhar_aviso()
        # dialogo de adicao de embarcacao (modal: fica por cima de tudo)
        if self._dialogo_frota is not None:
            self._dialogo_frota.desenhar(self.tela)

    def _desenhar_base(self) -> None:
        """
        Desenha o fundo do mapa.

        O satelite vem de uma camada de tiles: a area visivel e montada a partir
        dos tiles do nivel de zoom correspondente, o que permite arrastar e
        aproximar como num mapa comum. Sem tiles utilizaveis (pasta vazia e sem
        rede) o fundo de reserva e a folha de carta, e nao um retangulo vazio.
        """
        self._credito_mapa = ""
        if self.camadas.base_carta:
            self._desenhar_base_fixa()
            return
        if self.camadas.base_satelite:
            camada = self._camada_mapa()
            if camada.tem_tiles() and self._desenhar_base_tiles(camada):
                return
        self._desenhar_base_fixa()

    def _desenhar_base_fixa(self) -> None:
        """Fundo antigo: imagem unica da base, recortada e ampliada."""
        base = self._garantir_base()
        if self.visao.zoom <= 1.001:
            self.tela.blit(self._garantir_base_1x(), (0, ALTURA_MENU))
            return
        recorte = self.visao.recorte_base().clamp(base.get_rect())
        if recorte.width < 2 or recorte.height < 2:
            return
        # o recorte so muda quando a visao ou o tempo mudam, entao o resultado
        # do recorte+escala e reaproveitado enquanto a vista ficar parada
        chave = (recorte.x, recorte.y, recorte.width, recorte.height)
        cache = self._base_recorte_cache
        if cache is not None and cache[0] is base and cache[1] == chave:
            self.tela.blit(cache[2], (0, ALTURA_MENU))
            return
        alvo = (LARGURA_SIMULACAO_BASE, ALTURA_TELA_BASE)
        if recorte.size == alvo:
            # ja esta na resolucao da janela: copia direta
            imagem = base.subsurface(recorte)
        else:
            imagem = pygame.transform.smoothscale(base.subsurface(recorte), alvo)
        self._base_recorte_cache = (base, chave, imagem)
        self.tela.blit(imagem, (0, ALTURA_MENU))

    # -- fundo por tiles (slippy map) ------------------------------------
    def _camada_mapa(self) -> CamadaTiles:
        """Camada de tiles do estilo escolhido, com a rede conforme o toggle."""
        camada = self.camada_ruas if self.mapa_estilo == "ruas" else self.camada_satelite
        camada.permitir_rede = self.mapa_online
        return camada

    def _zoom_tiles(self) -> int:
        """Nivel de tile que deixa a visao atual com ~1 px de tela por px."""
        return zoom_para_escala(
            self.visao.zoom, LARGURA_SIMULACAO_BASE,
            LONG_RIGHT - LONG_LEFT)

    def _superficie_mosaico(self, camada: CamadaTiles, z: int,
                            tx0: int, ty0: int, tx1: int, ty1: int):
        """Mosaico de tiles como superficie do pygame, cacheado."""
        chave = (id(camada), camada.versao, z, tx0, ty0, tx1, ty1)
        surf = self._cache_mosaico.get(chave)
        if surf is not None:
            return surf
        mos = camada.mosaico(z, tx0, ty0, tx1, ty1)
        if mos is None:
            return None
        surf = pygame.image.frombytes(mos.tobytes(), mos.size, "RGB")
        self._cache_mosaico[chave] = surf
        if len(self._cache_mosaico) > 10:
            self._cache_mosaico.pop(next(iter(self._cache_mosaico)))
        return surf

    def _desenhar_base_tiles(self, camada: CamadaTiles) -> bool:
        """
        Monta o fundo a partir dos tiles do nivel de zoom da visao.

        Devolve False quando nao ha nenhum tile na area (offline e fora do
        recorte), para o chamador cair no fundo de reserva.
        """
        w = LARGURA_SIMULACAO_BASE / self.visao.zoom
        h = ALTURA_TELA_BASE / self.visao.zoom
        u0 = self.visao.centro_u - w / 2.0
        v0 = self.visao.centro_v - h / 2.0
        lat_topo, lon_esq = mundo_para_geo(u0, v0 + ALTURA_MENU)
        lat_base, lon_dir = mundo_para_geo(u0 + w, v0 + h + ALTURA_MENU)

        z_max = min(self._zoom_tiles(), camada.zoom_max_efetivo())
        z_min = camada.provedor.zoom_min
        for z in range(z_max, z_min - 1, -1):
            gx0, gy0 = geo_para_px(lat_topo, lon_esq, z)
            gx1, gy1 = geo_para_px(lat_base, lon_dir, z)
            tx0 = int(math.floor(gx0 / LADO_TILE))
            tx1 = int(math.floor((gx1 - 1e-9) / LADO_TILE))
            ty0 = int(math.floor(gy0 / LADO_TILE))
            ty1 = int(math.floor((gy1 - 1e-9) / LADO_TILE))
            surf = self._superficie_mosaico(camada, z, tx0, ty0, tx1, ty1)
            if surf is None:
                continue
            cx0 = gx0 - tx0 * LADO_TILE
            cy0 = gy0 - ty0 * LADO_TILE
            cx1 = gx1 - tx0 * LADO_TILE
            cy1 = gy1 - ty0 * LADO_TILE
            recorte = pygame.Rect(
                int(round(cx0)), int(round(cy0)),
                max(1, int(round(cx1 - cx0))),
                max(1, int(round(cy1 - cy0))),
            ).clamp(surf.get_rect())
            if recorte.width < 2 or recorte.height < 2:
                continue
            alvo = (LARGURA_SIMULACAO_BASE, ALTURA_TELA_BASE)
            # com a vista parada o mesmo recorte e reaproveitado. A superficie
            # entra na chave por identidade: quando um tile chega o mosaico e
            # trocado e o cache antigo deixa de casar, sem depender de `id()`
            chave_recorte = (recorte.x, recorte.y,
                             recorte.width, recorte.height)
            cache = self._tile_recorte_cache
            if cache is not None and cache[0] is surf and cache[1] == chave_recorte:
                imagem = cache[2]
            elif recorte.size == alvo:
                # ja esta na resolucao da janela: copia direta
                imagem = surf.subsurface(recorte)
                self._tile_recorte_cache = (surf, chave_recorte, imagem)
            else:
                imagem = pygame.transform.smoothscale(
                    surf.subsurface(recorte), alvo)
                self._tile_recorte_cache = (surf, chave_recorte, imagem)
            self.tela.blit(imagem, (0, ALTURA_MENU))
            self._credito_mapa = camada.provedor.atribuicao
            return True
        return False

    def _desenhar_credito_mapa(self) -> None:
        """Credito do provedor de tiles, exigido pela licenca da imagem."""
        if not self._credito_mapa:
            return
        cache = self._credito_cache
        if cache is None or cache[0] != self._credito_mapa:
            surf = self.f_pequena.render(
                self._credito_mapa, True, (238, 242, 246))
            pad = 4
            fundo = pygame.Surface(
                (surf.get_width() + 2 * pad, surf.get_height() + 2 * pad),
                pygame.SRCALPHA)
            fundo.fill((8, 14, 22, 170))
            fundo.blit(surf, (pad, pad))
            cache = (self._credito_mapa, fundo)
            self._credito_cache = cache
        fundo = cache[1]
        self.tela.blit(fundo, (8, ALTURA_MENU + ALTURA_TELA_BASE
                               - fundo.get_height() - 6))

    # -- rotas -----------------------------------------------------------
    def _desenhar_rotas(self) -> None:
        """
        Desenha a hidrovia em quatro passes: leito, halo, fluxo e eixo.

        Leito, halo e fluxo sao translucidos e vao para uma unica superficie
        alpha, composta sobre a tela em uma so operacao. Compor cada um
        separadamente custava tres blits de tela cheia por quadro, cerca de
        5 ms, e nao mudava o resultado.
        """
        if not self.camadas.rotas:
            return
        z = self.visao.zoom
        canais: list[tuple[object, list[tuple[int, int]]]] = []
        for canal in CANAIS.values():
            base = self._caminho(canal)[1]
            if not any(self.visao.visivel(u, v, 8) for u, v in base[::8]):
                continue
            pts = self._polilinha_tela(base)
            if len(pts) >= 2:
                canais.append((canal, pts))
        if not canais:
            return

        camada = self._tela_transparente()
        for canal, pts in canais:
            # O rio e desenhado em quatro faixas concéntricas, da margem para o
            # eixo. Antes era uma linha de espessura fixa com um halo: uma fita
            # azul de largura constante que nao lia como rio em cima do satelite.
            # A largura vem da calha e da faixa navegavel, e cada faixa tem uma
            # cor: a margem rasa e clara, o fundo e escuro, e a linha de
            #thalweg marca o meio. E o mesmo desenho que a folha de carta faz com
            # a profundidade, aqui em versao de tela.
            largura = self.visao.largura_px(
                max(3.0, canal.largura_navegavel_km / KM_POR_PX * 0.9))
            if self.camadas.efeitos_rota:
                # 1. margem: faixa larga e fraca que separa o rio da mata
                pygame.draw.lines(camada, (*COR_MARGEM, 60), False, pts,
                                  largura + self.visao.largura_px(7.0))
                # 2. leito: banda translucida, unica camada que tinge a agua
                pygame.draw.lines(camada, (*COR_LEITO, 120), False, pts, largura)
                # 3. borda escura fina: e o contraste que segura o rio tanto na
                # foto escura quanto na carta clara, sem virar brilho
                pygame.draw.lines(camada, (*COR_HALO, 110), False, pts,
                                  max(1, int(largura * 0.82)))
                # 4. eixo creme, opaco e fino, sempre legivel nas duas bases
                pygame.draw.lines(camada, (*COR_EIXO, 235), False, pts,
                                  self.visao.largura_px(1.4))
            else:
                pygame.draw.lines(camada, (*COR_LEITO, 165), False, pts, largura)
                pygame.draw.lines(camada, (*COR_EIXO, 235), False, pts,
                                  self.visao.largura_px(1.4))
            # 6. fluxo animado por cima do eixo, senao os pulsos ficam escondidos
            if self.camadas.fluxo_rota and z > 0.75:
                self._desenhar_fluxo(canal, camada)
        self._compor_mapa(camada)

        if self.camadas.marcos_km and z > 1.1:
            for canal, _pts in canais:
                self._desenhar_marcos_canal(canal)

    def _desenhar_fluxo(self, canal, camada: pygame.Surface) -> None:
        """
        Tracos curtos deslizando ao longo do canal, no sentido da corrente.

        O deslocamento vem do relogio real, entao o efeito e continuo e barato: a
        posicao de cada traco e uma interpolacao vetorizada sobre a polilinha do
        canal, e o custo nao depende do zoom.

        O que mudou em relacao a versao anterior e o comprimento e o brilho. Os
        tracos tinham extensao fixa, e ao passar do maior zoom aparecia uma fileira
        deriscos iguais, como um tracejado de régua. Agora a extensao cresce com o
        zoom e o brilho de cada traco segue uma senoide, de modo que o rio parece
        corr em vez de piscar. A velocidade tambem esta em px de tela por segundo e
        nao em km por segundo, para o efeito ficar igual em qualquer zoom.
        """
        cum, base = self._caminho(canal)
        total = float(cum[-1])
        if total <= 1.0:
            return
        z = self.visao.zoom
        # extensao proporcional ao espaco entre tracos: o Rio fica sempre com a
        # mesma proporcao de cheio, e nao uma regua de tracos iguais
        espaco = max(14.0, 30.0 / max(0.5, z))
        extensao = espaco * 0.42
        desl = (pygame.time.get_ticks() / 1000.0 * 26.0 * min(2.0, z)) % espaco
        n = int(total // espaco) + 2
        s0 = np.arange(n) * espaco + desl
        s1 = np.minimum(s0 + extensao, total)
        u0 = np.interp(s0, cum, base[:, 0])
        v0 = np.interp(s0, cum, base[:, 1])
        u1 = np.interp(s1, cum, base[:, 0])
        v1 = np.interp(s1, cum, base[:, 1])
        x0, y0 = self.visao.projetar(u0, v0)
        x1, y1 = self.visao.projetar(u1, v1)
        # descarta o que esta fora da area do mapa
        dentro = ((x0 > -20) & (x0 < LARGURA_SIMULACAO_BASE + 20)
                  & (y0 > ALTURA_MENU - 20)
                  & (y0 < ALTURA_TOTAL + 20))
        if not dentro.any():
            return
        # os pulsos sao mais largos que o eixo para nao sumirem por baixo dele
        largura = self.visao.largura_px(6.0)
        nucleo = max(1, self.visao.largura_px(2.4))
        # brilho oscillando ao longo do rio, para os tracos nao virarem tracejado
        fase = pygame.time.get_ticks() / 1000.0 * 2.2
        for a, b, c, d, s in zip(x0[dentro], y0[dentro], x1[dentro], y1[dentro],
                                 s0[dentro]):
            pulso = 0.5 + 0.5 * math.sin(fase - s * 0.02)
            halo = int(70 + 80 * pulso)
            nucleo_alfa = int(170 + 85 * pulso)
            pygame.draw.line(camada, (*COR_FLUXO, halo), (a, b), (c, d), largura)
            pygame.draw.line(camada, (*COR_FLUXO, nucleo_alfa), (a, b), (c, d), nucleo)

    def _desenhar_marcos_canal(self, canal) -> None:
        for km in range(20, int(canal.comprimento_km), 20):
            pos = canal.posicao_em(float(km), 0.0)[0]
            sx, sy = self.visao.para_tela(pos)
            if not (0 <= sx < LARGURA_SIMULACAO_BASE
                    and ALTURA_MENU <= sy < ALTURA_TOTAL):
                continue
            r = self.visao.largura_px(3.5)
            pygame.draw.circle(self.tela, (10, 20, 28), (sx, sy), r + 1)
            pygame.draw.circle(self.tela, (235, 245, 255), (sx, sy), r, 1)
            self._texto(f"{km}", (sx + r + 3, sy - 6), (200, 228, 245), self.f_pequena)

    def _desenhar_marcos(self) -> None:
        """Cidades e bifurcacoes do rio, rotuladas em texto legivel."""
        z = self.visao.zoom
        for nome, pos in WAYPOINTS.items():
            u, v = self.visao.para_base(pos)
            if not self.visao.visivel(u, v, 40):
                continue
            sx, sy = self.visao.para_tela(pos)
            r = self.visao.largura_px(3.0)
            pygame.draw.polygon(self.tela, (255, 250, 235), (
                (sx, sy - r), (sx + r, sy), (sx, sy + r), (sx - r, sy)))
            pygame.draw.polygon(self.tela, (30, 40, 52), (
                (sx, sy - r), (sx + r, sy), (sx, sy + r), (sx - r, sy)), 1)
            rotulo = nome.replace("_", " ")
            self._texto(rotulo, (sx + r + 4, sy - 6), (246, 238, 220), self.f_pequena)
        if z <= 1.0:
            return

    # -- obstaculos, contatos e supernos ---------------------------------
    def _desenhar_obstaculos(self) -> None:
        if not self.camadas.obstaculos:
            return
        t_h = self.motor.t_s / 3600.0
        for obst in self.motor.cenario.obstaculos_ativos(t_h):
            u, v = self.visao.para_base(obst.posicao_px)
            if not self.visao.visivel(u, v, obst.raio_km / KM_POR_PX + 30):
                continue
            x, y = self.visao.para_tela(obst.posicao_px)
            r = max(8, self.visao.largura_px(obst.raio_km / KM_POR_PX))
            camada = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(camada, (225, 60, 40, 95), (r, r), r)
            pygame.draw.circle(camada, (255, 200, 120, 255), (r, r), r, 2)
            pygame.draw.circle(camada, (255, 240, 210, 140), (r, r),
                               max(1, r - 4), 1)
            self.tela.blit(camada, (x - r, y - r))
            self._texto(obst.rotulo, (x + r + 5, y - 8), (255, 225, 190),
                        self.f_pequena)

    def _desenhar_contatos(self) -> None:
        if not self.camadas.contatos:
            return
        z = self.visao.zoom
        for no in self.motor.frota:
            un, vn = self.visao.para_base(no.pos)
            for viz in no.contatos_ativos:
                outro = self.motor.frota[viz]
                if not self.visao.visivel(un, vn, 20) \
                        and not self.visao.visivel(*self.visao.para_base(outro.pos), 20):
                    continue
                a = self.visao.para_tela(no.pos)
                b = self.visao.para_tela(outro.pos)
                ativo = no.em_transmissao or outro.em_transmissao
                cor = DESTAQUE if ativo else (56, 84, 112)
                if ativo:
                    pygame.draw.line(self.tela, (255, 176, 64, 60), a, b,
                                     self.visao.largura_px(3.0))
                pygame.draw.line(self.tela, cor, a, b, max(1, self.visao.largura_px(1.0)))

    def _desenhar_supernos(self) -> None:
        """
        Gateways de internet sobre o mapa — versao visual melhorada.

        Gateway fixo : icone de torre de comunicacao (mastro + base + ondas).
        Gateway movel: icone de antena de satelite (prato + haste + satelite).

        Um tooltip rico aparece quando o cursor fica sobre o marcador por mais
        de 300 ms, mostrando km, bundles drenados, cota livre e alcance.
        """
        if not self.camadas.supernos:
            self._tooltip_sn = None
            return

        reservados: list[pygame.Rect] = []
        self._rotulos_supernos = reservados
        self._tooltip_sn = None          # calculado abaixo se houver hover

        mx, my = self._pos_mouse         # posicao do cursor para hover

        for sn in self.motor.supernos:
            u, v = self.visao.para_base(sn.pos)
            if not self.visao.visivel(u, v, sn.alcance_km / KM_POR_PX + 20):
                continue
            x, y = self.visao.para_tela(sn.pos)

            # -- cor base --------------------------------------------------
            cor_fixo  = (40, 220, 110)    # verde
            cor_movel = (255, 176, 64)    # ambar
            cor = cor_fixo if not sn.movel else cor_movel

            # -- circulo de alcance ----------------------------------------
            if self.camadas.circulos_alcance:
                r = self.visao.largura_px(sn.alcance_km / KM_POR_PX)
                camada = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                pygame.draw.circle(camada, (*cor, 22), (r, r), r)
                pygame.draw.circle(camada, (*cor, 90), (r, r), r, 2)
                self.tela.blit(camada, (x - r, y - r))

            s = max(7, self.visao.largura_px(6.5))

            if not sn.movel:
                # ============================================================
                # GATEWAY FIXO — torre de comunicacao
                # ============================================================
                # base da torre (trapezio)
                base_w = int(s * 1.1)
                base_h = int(s * 0.55)
                pygame.draw.polygon(self.tela, cor, [
                    (x - base_w, y + s),
                    (x + base_w, y + s),
                    (x + s // 2, y + s - base_h),
                    (x - s // 2, y + s - base_h),
                ])
                pygame.draw.polygon(self.tela, (8, 38, 18), [
                    (x - base_w, y + s),
                    (x + base_w, y + s),
                    (x + s // 2, y + s - base_h),
                    (x - s // 2, y + s - base_h),
                ], 1)
                # mastro vertical
                pygame.draw.line(self.tela, cor, (x, y + s - base_h), (x, y - s), max(2, s // 4))
                # cabecote/antena no topo
                top_y = y - s
                pygame.draw.circle(self.tela, (255, 255, 255), (x, top_y), max(2, s // 4))
                pygame.draw.circle(self.tela, cor, (x, top_y), max(1, s // 5))
                # ondas de sinal (arcos concentricos)
                for k_arc, raio_arc in enumerate([s * 0.65, s * 1.1, s * 1.6]):
                    raio_i = int(raio_arc)
                    if raio_i < 2:
                        continue
                    alpha_arc = 200 - k_arc * 45
                    arc_surf = pygame.Surface((raio_i * 2 + 2, raio_i * 2 + 2), pygame.SRCALPHA)
                    pygame.draw.arc(arc_surf, (*cor, alpha_arc),
                                    arc_surf.get_rect(),
                                    math.radians(30), math.radians(150), max(1, s // 5 - k_arc))
                    self.tela.blit(arc_surf, (x - raio_i - 1, top_y - raio_i - 1))

                linhas_rot = (sn.nome, f"km {sn.km_canal:.0f}")
                cores_rot  = ((200, 255, 215), (160, 230, 180))

            else:
                # ============================================================
                # GATEWAY MOVEL — antena de satelite (prato + haste + satelite)
                # ============================================================
                livre = sn._cota >= 1.0
                cor_ef = cor if livre else (110, 84, 44)
                cor_ef_brilho = (255, 210, 90) if livre else (150, 110, 60)

                # haste inclinada
                haste_dx = int(s * 0.55)
                haste_dy = int(s * 0.45)
                px0, py0 = x, y + s
                px1, py1 = x - haste_dx, y - haste_dy
                pygame.draw.line(self.tela, cor_ef, (px0, py0), (px1, py1),
                                 max(2, s // 4))

                # prato parabolico (elipse achatada)
                prato_rx = s
                prato_ry = max(3, s // 3)
                ang_prato = math.radians(40)
                cdx = int(prato_rx * math.cos(ang_prato))
                cdy = int(prato_rx * math.sin(ang_prato))
                prato_cx = px1 + int(s * 0.3 * math.cos(ang_prato + math.pi / 2))
                prato_cy = py1 + int(s * 0.3 * math.sin(ang_prato + math.pi / 2))
                prato_rect = pygame.Rect(prato_cx - prato_rx, prato_cy - prato_ry,
                                         prato_rx * 2, prato_ry * 2)
                if prato_rect.width > 2 and prato_rect.height > 2:
                    pygame.draw.ellipse(self.tela, cor_ef if livre else (40, 36, 30), prato_rect)
                    pygame.draw.ellipse(self.tela, cor_ef_brilho, prato_rect, max(1, s // 5))

                # satelite pequeno no topo
                sat_x = px1 - s // 2
                sat_y = py1 - s
                sat_s = max(4, s // 2)
                pygame.draw.rect(self.tela, cor_ef_brilho,
                                 (sat_x - sat_s, sat_y - sat_s // 3, sat_s * 2, sat_s // 3 * 2))
                # paineis solares
                panel_color = (80, 160, 230) if livre else (90, 90, 100)
                pygame.draw.rect(self.tela, panel_color,
                                 (sat_x - sat_s - sat_s // 2 - 1, sat_y - sat_s // 5,
                                  sat_s // 2, sat_s // 5 * 2))
                pygame.draw.rect(self.tela, panel_color,
                                 (sat_x + sat_s + 1, sat_y - sat_s // 5,
                                  sat_s // 2, sat_s // 5 * 2))

                # linha de sinal do satelite ao prato
                pygame.draw.line(self.tela, (*cor_ef, 160), (sat_x, sat_y),
                                 (prato_cx, prato_cy), 1)

                linhas_rot = (sn.nome, "cota livre" if livre else "aguardando cota")
                cores_rot  = ((255, 222, 160), (220, 190, 130))

            # -- rotulo ao lado do marcador --------------------------------
            larg = max(self.f_pequena.size(t)[0] for t in linhas_rot)
            caixa = pygame.Rect(x + s + 7, y - 13, larg + 6, 26)
            if not any(caixa.colliderect(c) for c in reservados):
                for i, txt in enumerate(linhas_rot):
                    self._texto(txt, (caixa.x + 3, caixa.y + 2 + i * 13),
                                cores_rot[i], self.f_pequena)
                reservados.append(caixa)

            # -- hover: calcula tooltip se o cursor estiver perto ----------
            raio_hit = max(16, s + 6)
            if ((mx - x) ** 2 + (my - y) ** 2) <= raio_hit ** 2:
                self._tooltip_sn = self._superficie_tooltip_sn(sn), (x, y)

        # desenha o tooltip por cima de tudo
        if self._tooltip_sn is not None:
            surf, (tx, ty) = self._tooltip_sn
            sw, sh = surf.get_size()
            # posiciona abaixo e a direita, empurrando para dentro da tela
            px = min(tx + 16, LARGURA_SIMULACAO_BASE - sw - 4)
            py = min(ty + 16, ALTURA_TOTAL - sh - 4)
            self.tela.blit(surf, (px, py))

    def _superficie_tooltip_sn(self, sn) -> pygame.Surface:
        """Tooltip rico de hover de um superno/gateway."""
        t_h = self.motor.t_s / 3600.0
        tipo_str   = "Gateway fixo"  if not sn.movel else "Gateway movel"
        cor_tipo   = (140, 255, 180) if not sn.movel else (255, 210, 100)
        cota_str   = f"{sn._cota:.2f}" if sn.movel else "—"
        cota_cor   = (100, 240, 140) if (not sn.movel or sn._cota >= 1.0) else (255, 140, 80)

        titulo = sn.nome
        linhas = [
            ("Tipo",           tipo_str,                             cor_tipo),
            ("km no canal",    f"{sn.km_canal:.1f} km",             (220, 235, 255)),
            ("Alcance",        f"{sn.alcance_km:.1f} km",           (200, 220, 250)),
            ("Bundles drenados", str(sn.pacotes_drenados),          (180, 230, 200)),
            ("Embarc. atendidas", str(len(sn.embarcoes_atendidas)), (180, 230, 200)),
            ("Aguardando cota",  str(sn.aguardando_cota),
             (255, 150, 80) if sn.aguardando_cota > 0 else (150, 168, 190)),
            ("Cota disponivel",  cota_str,                          cota_cor),
        ]
        if sn.movel and sn.anfitriao is not None:
            emb = sn.anfitriao
            linhas += [
                ("Embarcacao",    f"ID {emb.id} — {emb.nome_tipo}", (220, 220, 255)),
                ("Veloc.",        f"{emb.velocidade_nos:.1f} nós",   (200, 210, 240)),
                ("Sentido",       "jusante" if emb.sentido > 0 else "montante",
                 (200, 210, 240)),
            ]

        larg = 220
        lin_h = 14
        alt = 10 + 18 + 4 + len(linhas) * lin_h + 6
        surf = pygame.Surface((larg, alt), pygame.SRCALPHA)

        # fundo
        pygame.draw.rect(surf, (10, 16, 26, 230), surf.get_rect(), border_radius=5)
        # borda colorida conforme tipo
        borda_cor = (40, 220, 110) if not sn.movel else (255, 176, 64)
        pygame.draw.rect(surf, borda_cor, surf.get_rect(), 1, border_radius=5)
        # barra lateral esquerda
        pygame.draw.rect(surf, borda_cor, pygame.Rect(0, 0, 3, alt), border_radius=3)

        y_tt = 8
        # titulo
        self._blit_texto(surf, titulo, (10, y_tt), (255, 250, 220), self.f_painel_t)
        y_tt += 18
        pygame.draw.line(surf, (60, 76, 100), (10, y_tt), (larg - 10, y_tt))
        y_tt += 5

        for rot, val, cor_v in linhas:
            self._blit_texto(surf, rot, (10, y_tt), (130, 148, 170), self.f_pequena)
            s_val = self._texto_surf(val, cor_v, self.f_pequena)
            surf.blit(s_val, (larg - 10 - s_val.get_width(), y_tt))
            y_tt += lin_h

        return surf



    # -- frota com icones -------------------------------------------------
    def _proa(self, no) -> float:
        """
        Rumo do casco em graus, derivado da tangente do canal no ponto atual.

        A diferenca e avaliada a 1 km, porque a polilinha do canal tem passos
        de 0,19 km e uma diferenca menor devolveria o mesmo vertice. O
        resultado e memorizado por balde de meio quilometro: o rumo varia
        lentamente ao longo de um canal suave, e assim as 15 embarcacoes
        custam uma interpolacao por quadro em vez de 30 chamadas ao canal.
        """
        chave = (id(no.canal), int(no.km_atual * 2.0), no.sentido)
        angulo = self._cache_proa.get(chave)
        if angulo is not None:
            return angulo
        canal = no.canal
        km = no.km_atual
        eps = 1.0
        a = canal.posicao_em(max(0.0, km - eps), no.offset_faixa_km)[0]
        b = canal.posicao_em(min(canal.comprimento_km, km + eps), no.offset_faixa_km)[0]
        dx = float(b[0] - a[0])
        dy = float(b[1] - a[1])
        if no.sentido < 0:
            dx, dy = -dx, -dy
        angulo = math.degrees(math.atan2(dy, dx))
        if len(self._cache_proa) > 4000:
            self._cache_proa.clear()
        self._cache_proa[chave] = angulo
        return angulo

    def _superficie_icone(self, tipo: str, cor: tuple[int, int, int]) -> pygame.Surface:
        """
        Silhueta do tipo de embarcacao, desenhada uma vez e depois rotacionada.

        A proa aponta para +x. O casco e desenhado 4x maior e reduzido com
        `smoothscale`, o que dá a borda um anti-aliasing de verdade: o
        `pygame.draw` nao tem, e a proa de 26 px saía serrilhada. Por cima vai
        um contorno quase preto de 2 px, porque sobre a foto de satelite o
        casco perde o contorno contra o verde da mata, e um vetor por baixo
        deslocado de 1 px, que e a sombra que separa o casco do rio.
        """
        chave = (tipo, cor)
        surf = self._cache_icones.get(chave)
        if surf is not None:
            return surf
        comp = COMPRIMENTO_ICONE.get(tipo, 18.0)
        larg = LARGURA_ICONE.get(tipo, 11.0)
        pad = 8
        tam = int(comp) + pad * 2
        cx = cy = tam / 2.0

        ss = 4
        sup = pygame.Surface((tam * ss, tam * ss), pygame.SRCALPHA)

        def poly(chave_geo, dx=0.0, dy=0.0):
            return [(cx + x * comp + dx, cy + y * larg + dy) for x, y in chave_geo]

        def p(geo):
            return [(x * ss, y * ss) for x, y in geo]

        def pt(x, y):
            return (x * ss, y * ss)

        geo = ICONES.get(tipo, ICONES_PADRAO)
        # poly centraliza (cx + x*comp) e p aplica o supersampling; as duas sao
        # obrigatorias. So p deixa a geometria normalizada no canto superior
        # esquerdo, com 4 px de lado, e o casco some sob a propria sombra.
        casco = p(poly(geo["casco"]))
        poroes = p(poly(geo["poroes"]))
        cabine = p(poly(geo["cabine"]))

        # sombra: mesmo casco, deslocado para descolar o contorno do rio
        pygame.draw.polygon(sup, (0, 0, 0, 105), p(poly(geo["casco"], 1.0, 1.2)))
        pygame.draw.polygon(sup, cor, casco)
        pygame.draw.polygon(sup, _mistura(cor, 0.62), poroes)

        if "conteineres" in geo:
            cores_cont = [(40, 90, 180), (180, 70, 40), (40, 140, 70), (220, 140, 30)]
            for i, c_geo in enumerate(geo["conteineres"]):
                c_cor = cores_cont[i % len(cores_cont)]
                pygame.draw.polygon(sup, c_cor, p(poly(c_geo)))
                pygame.draw.polygon(sup, (20, 30, 40), p(poly(c_geo)), max(1, ss // 2))

        pygame.draw.polygon(sup, _mistura(cor, 1.45), cabine)
        if geo.get("mastro"):
            (mx, my), (mx2, my2) = geo["mastro"]
            pygame.draw.line(sup, (12, 18, 24),
                             pt(cx + mx * comp, cy + my * larg),
                             pt(cx + mx2 * comp, cy + my2 * larg), ss)
        pygame.draw.polygon(sup, (8, 12, 16), casco, 2 * ss)
        surf = pygame.transform.smoothscale(sup, (tam, tam))
        if len(self._cache_icones) > 64:
            self._cache_icones.clear()
        self._cache_icones[chave] = surf
        return surf

    def _icone_rotacionado(self, tipo: str, cor, angulo: float) -> pygame.Surface:
        """
        Icono ja orientado segundo a proa.

        O angulo e arredondado para passos de 6 graus: com 15 embarcacoes, os
        60 tamanhos de cache resultantes custam menos que rotacionar as
        superficies a cada quadro.
        """
        passo = 6.0
        ang = round(angulo / passo) * passo
        chave = (tipo, cor, ang)
        surf = self._cache_icones.get(chave)
        if surf is not None:
            return surf
        base = self._superficie_icone(tipo, cor)
        surf = (pygame.transform.rotozoom(base, -ang, 1.0)
                if abs(ang % 360) > 0.5 else base)
        if len(self._cache_icones) > 1500:
            self._cache_icones.clear()
        self._cache_icones[chave] = surf
        return surf

    def _desenhar_frota(self) -> None:
        if not self.camadas.frota:
            return
        if self.camadas.rastros:
            for no in self.motor.frota:
                if len(no.historico) < 2:
                    continue
                hist = np.asarray(no.historico[-400:], dtype=float)
                pts = self._polilinha_tela(hist)
                if len(pts) > 1:
                    pygame.draw.lines(self.tela, (*no.cor_base, 70), False, pts,
                                      max(1, self.visao.largura_px(2.0)))

        mx, my = self._pos_mouse
        hover_no = None
        hover_d2 = (20 * self.visao.zoom) ** 2   # raio de hover em px de tela

        for no in self.motor.frota:
            pos = self._pos_desenho(no)
            u, v = self.visao.para_base(pos)
            if not self.visao.visivel(u, v, 20):
                continue
            x, y = self.visao.para_tela(pos)
            cor = no.cor_base if no.classe_risco == RISCO_SEGURO else no.cor_risco

            # -- anel de alerta de risco ----------------------------------
            if no.classe_risco != RISCO_SEGURO:
                raio = self.visao.largura_px(11.0)
                pygame.draw.circle(self.tela, (8, 14, 20), (x, y), raio + 1, 2)
                pygame.draw.circle(self.tela, cor, (x, y), raio, 2)

            # -- icone do casco -------------------------------------------
            icone = self._icone_rotacionado(no.tipo, cor, self._proa(no))
            self.tela.blit(icone, (x - icone.get_width() // 2,
                                   y - icone.get_height() // 2))

            # -- anel de transmissao (onda LoRa) --------------------------
            if no.em_transmissao:
                pygame.draw.circle(self.tela, (0, 210, 255), (x, y),
                                   self.visao.largura_px(13.0), 2)

            # -- exclamacao de risco critico ------------------------------
            if no.classe_risco == RISCO_CRITICO:
                self._texto("!", (x + 12, y - 14), CORES_RISCO[RISCO_CRITICO],
                            self.f_painel_t)

            # -- label flutuante com informacoes do no --------------------
            self._desenhar_label_no(no, x, y, cor)

            # -- deteccao de hover ----------------------------------------
            d2 = (mx - x) ** 2 + (my - y) ** 2
            if d2 < hover_d2:
                hover_d2 = d2
                hover_no = no

        self._desenhar_anel_selecao()

        # -- tooltip de hover do no movel ---------------------------------
        if hover_no is not None and hover_no.id != self.selecionado_id:
            surf = self._superficie_tooltip_no(hover_no)
            sw, sh = surf.get_size()
            hx, hy = self.visao.para_tela(self._pos_desenho(hover_no))
            px = min(hx + 18, LARGURA_SIMULACAO_BASE - sw - 4)
            py = min(hy + 18, ALTURA_TOTAL - sh - 4)
            self.tela.blit(surf, (px, py))

    def _desenhar_label_no(self, no, x: int, y: int, cor: tuple) -> None:
        """
        Etiqueta compacta acima do casco com ID, tipo abreviado, km e risco.

        A zoom 1x cabe apenas o ID (nao sobrepoe os vizinhos); a zoom alto
        expande para tipo + km + velocidade. A etiqueta tem um fundo semi-
        transparente para ser legivel sobre qualquer fundo de carta.
        """
        z = self.visao.zoom

        # abreviacao do tipo de embarcacao
        abrev = {"PRINCIPAL": "NAV", "LANCHA": "LCH", "RIBEIRINHO": "RIB"}.get(no.tipo, no.tipo[:3])

        if z < 1.5:
            # zoom baixo: so o ID
            txt = f"#{no.id}"
            linhas = [txt]
        elif z < 3.0:
            # zoom medio: ID + tipo + km
            linhas = [f"#{no.id} {abrev}", f"km {no.km_atual:.0f}"]
        else:
            # zoom alto: completo
            sentido_s = "↓" if no.sentido > 0 else "↑"
            linhas = [
                f"#{no.id} {abrev}",
                f"km {no.km_atual:.1f} {sentido_s}",
                f"{no.velocidade_nos:.1f} nós",
            ]
            if no.classe_risco != RISCO_SEGURO:
                cor_rsk = CORES_RISCO.get(no.classe_risco, TEXTO)
                linhas.append(f"MSK {no.margem_sob_quilha_m:.2f}m")

        # dimensionar a caixa de fundo
        larg_max = max(self.f_pequena.size(l)[0] for l in linhas)
        alt_total = len(linhas) * 13 + 4
        # calcula a meia-altura do icone para posicionar o label acima do casco
        icone_h = self.visao.largura_px(
            {"PRINCIPAL": 15.0, "LANCHA": 11.0, "RIBEIRINHO": 13.0}.get(no.tipo, 12.0))
        ly = y - icone_h // 2 - alt_total - 3
        lx = x - larg_max // 2

        # fundo semi-transparente
        bg = pygame.Surface((larg_max + 6, alt_total), pygame.SRCALPHA)
        bg.fill((8, 12, 20, 185))
        pygame.draw.rect(bg, (*cor, 160), bg.get_rect(), 1, border_radius=2)
        self.tela.blit(bg, (lx - 3, ly))

        for i, linha in enumerate(linhas):
            cor_linha = CORES_RISCO.get(no.classe_risco, TEXTO) if (
                no.classe_risco != RISCO_SEGURO and i == len(linhas) - 1 and z >= 3.0
            ) else (230, 238, 248)
            self._texto(linha, (lx, ly + 2 + i * 13), cor_linha, self.f_pequena)

    def _superficie_tooltip_no(self, no) -> pygame.Surface:
        """Tooltip rico de hover de uma embarcacao (sem estar selecionada)."""
        cor_risco_v = CORES_RISCO.get(no.classe_risco, TEXTO)
        sentido_s   = "jusante ↓" if no.sentido > 0 else "montante ↑"
        a_bordo     = len(no.buffer)
        ocupacao    = a_bordo / max(1, self.cfg.limite_buffer)

        # Geolocalização: converte posição simulada em coordenadas geográficas reais
        lat, lon = mundo_para_geo(*no.pos)
        lat_s = f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}"
        lon_s = f"{abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"

        titulo = f"ID {no.id}  —  {no.nome_tipo}"
        linhas = [
            ("Tipo",              no.nome_tipo,                                no.cor_base),
            ("Canal",             no.canal.nome if hasattr(no.canal, "nome") else "principal",
                                  (200, 220, 255)),
            # Geolocalização em tempo real
            ("Latitude",          lat_s,                                       (120, 220, 160)),
            ("Longitude",         lon_s,                                       (120, 220, 160)),
            ("Pos. no mapa",      f"x {no.pos[0]:.0f} · y {no.pos[1] - ALTURA_MENU:.0f} px",
                                  (150, 180, 210)),
            # Distância percorrida substitui "posição km"
            ("Dist. percorrida",  f"{no.distancia_percorrida_km:.1f} km",      (220, 235, 255)),
            ("Pos. no canal",     f"km {no.km_atual:.1f} / {no.canal.comprimento_km:.0f}",
                                  (180, 200, 230)),
            ("Sentido",           sentido_s,                                   (200, 215, 240)),
            ("Velocidade",        f"{no.velocidade_nos:.1f} nós",             (200, 215, 240)),
            ("Calado",            f"{no.calado_m:.1f} m",                     (190, 210, 235)),
            ("Profundidade",      f"{no.profundidade_m:.1f} m",               (190, 210, 235)),
            ("Marg. sob quilha",  f"{no.margem_sob_quilha_m:.2f} m",          cor_risco_v),
            ("Risco",             no.classe_risco,                             cor_risco_v),
            ("A bordo",           f"{a_bordo}/{self.cfg.limite_buffer} ({ocupacao*100:.0f}%)",
             DESTAQUE if ocupacao > 0.5 else (180, 220, 200)),
            ("Transmissoes",      str(no.transmitidos),                        (160, 200, 220)),
            ("Energia",           f"{no.energia_j * 1000:.1f} mJ",            (160, 200, 220)),
        ]

        larg  = 260
        lin_h = 14
        alt   = 10 + 18 + 4 + len(linhas) * lin_h + 6
        surf  = pygame.Surface((larg, alt), pygame.SRCALPHA)

        pygame.draw.rect(surf, (10, 16, 26, 228), surf.get_rect(), border_radius=5)
        borda = no.cor_base
        pygame.draw.rect(surf, borda, surf.get_rect(), 1, border_radius=5)
        pygame.draw.rect(surf, borda, pygame.Rect(0, 0, 3, alt), border_radius=3)

        y_tt = 8
        self._blit_texto(surf, titulo, (10, y_tt), (255, 250, 220), self.f_painel_t)
        y_tt += 18
        pygame.draw.line(surf, (60, 76, 100), (10, y_tt), (larg - 10, y_tt))
        y_tt += 5

        for rot, val, cor_v in linhas:
            self._blit_texto(surf, rot, (10, y_tt), (130, 148, 170), self.f_pequena)
            s_val = self._texto_surf(str(val), cor_v, self.f_pequena)
            surf.blit(s_val, (larg - 10 - s_val.get_width(), y_tt))
            y_tt += lin_h

        return surf



    def _desenhar_anel_selecao(self) -> None:
        """Realca a embarcacao selecionada com um anel pulsante."""
        no = self._embarcacao_selecionada()
        if no is None or not self.camadas.frota:
            return
        pos = self._pos_desenho(no)
        u, v = self.visao.para_base(pos)
        if not self.visao.visivel(u, v, 24):
            return
        x, y = self.visao.para_tela(pos)
        t = pygame.time.get_ticks() / 1000.0
        pulso = 0.5 + 0.5 * math.sin(t * 5.0)
        raio = self.visao.largura_px(16.0 + 3.0 * pulso)
        pygame.draw.circle(self.tela, (8, 14, 20), (x, y), raio + 2, 3)
        pygame.draw.circle(self.tela, (255, 214, 92), (x, y), raio, 2)
        for ang in (0, 90, 180, -90):
            a = math.radians(ang)
            pygame.draw.circle(
                self.tela, (255, 240, 190),
                (x + int(math.cos(a) * raio), y + int(math.sin(a) * raio)), 3)

    # -- ficha de status de coleta ---------------------------------------
    def _desenhar_ficha(self) -> None:
        """
        Cartao flutuante com o status de coleta da embarcacao selecionada.

        O texto muda a cada quadro quando a simulacao corre, entao a superficie
        e rerasterizada so quando o conteudo muda de fato.
        """
        no = self._embarcacao_selecionada()
        if no is None or self._carta is not None:
            return
        u, v = self.visao.para_base(no.pos)
        cartao = self._superficie_ficha(no)
        x, y = self.visao.para_tela(no.pos)
        # ao lado da embarcacao, dentro do mapa e longe do painel
        px = x + 26
        if px + cartao.get_width() > LARGURA_SIMULACAO_BASE - 8:
            px = x - 26 - cartao.get_width()
        py = y - cartao.get_height() // 2
        py = max(ALTURA_MENU + 8, min(py, ALTURA_TOTAL - cartao.get_height() - 8))
        px = max(8, px)
        # seta ligando o cartao a embarcacao
        pygame.draw.line(self.tela, (255, 214, 92), (x, y), (px + 4, py + 14), 1)
        self.tela.blit(cartao, (px, py))

    def _superficie_ficha(self, no) -> pygame.Surface:
        linhas = self._linhas_ficha(no)
        chave = (no.id,) + tuple(linhas)
        if self._ficha is not None and self._ficha_chave == chave:
            return self._ficha

        # Ícone do tipo da embarcação, na mesma simbologia do mapa (a cor vem
        # do próprio nó, para o cartão não divergir do casco desenhado)
        tipo = no.tipo
        icone = self._superficie_icone(tipo, no.cor_base)

        larg = 244
        # altura: padding top(8) + ícone(24) + espaço(8) + primeira linha(18) + 
        #       linha do horizonte(5) + linhas(15 cada) + bottom(8)
        alt = 8 + 24 + 8 + 18 + 5 + max(0, (len(linhas) - 1) * 15) + 8

        surf = pygame.Surface((larg, alt), pygame.SRCALPHA)
        pygame.draw.rect(surf, (16, 22, 31, 232), surf.get_rect(), border_radius=6)
        pygame.draw.rect(surf, (255, 214, 92), surf.get_rect(), 1, border_radius=6)
        pygame.draw.rect(surf, (255, 214, 92), pygame.Rect(0, 0, 4, alt), border_radius=3)

        # desenha o ícone do tipo no canto superior esquerdo
        surf.blit(icone, (8, 8))

        y = 32
        self._blit_texto(surf, f"ID {no.id}  {no.nome_tipo}", (10, y),
                         (255, 240, 200), self.f_painel_t)
        y += 18
        
        pygame.draw.line(surf, (70, 84, 104), (10, y), (larg - 10, y))
        y += 5
        for rot, val, cor in linhas:
            self._blit_texto(surf, rot, (10, y), TEXTO_FRACO, self.f_pequena)
            s = self._texto_surf(val, cor, self.f_pequena)
            surf.blit(s, (larg - 10 - s.get_width(), y))
            y += 15
        self._ficha = surf
        self._ficha_chave = chave
        return surf

    def _blit_texto(self, surf, txt, pos, cor, fonte) -> None:
        surf.blit(self._texto_surf(txt, cor, fonte), pos)

    def _linhas_ficha(self, no) -> list[tuple[str, str, tuple]]:
        """Conteudo da ficha: geolocalização, distância percorrida, coleta e comunicacao."""
        cfg = self.cfg
        t_s = self.motor.t_s
        agora = no.buffer
        a_bordo = len(agora)
        ocupacao = a_bordo / max(1, cfg.limite_buffer)
        mais_velho = max((b.idade_h(t_s) for b in agora.values()), default=0.0)

        # contabilidade da coleta por tipo de leitura
        rotina = seguranca = alerta = 0
        for b in agora.values():
            if b.categoria != CAT_SEGURANCA:
                rotina += 1
            elif b.carga.get("alerta"):
                alerta += 1
            else:
                seguranca += 1

        # Geolocalização: coordenadas geográficas em tempo real
        lat, lon = mundo_para_geo(*no.pos)
        lat_s = f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}"
        lon_s = f"{abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"

        cor_risco = CORES_RISCO.get(no.classe_risco, TEXTO)
        linhas = [
            # --- Geolocalização ---
            ("Latitude",           lat_s,                                         (120, 220, 160)),
            ("Longitude",          lon_s,                                         (120, 220, 160)),
            # --- Navegação ---
            ("Dist. percorrida",   f"{no.distancia_percorrida_km:.1f} km",        TEXTO),
            ("Pos. no canal",      f"km {no.km_atual:6.1f} / {no.canal.comprimento_km:.0f}", (180, 200, 230)),
            ("Sentido",            "jusante" if no.sentido > 0 else "montante",   TEXTO),
            ("Velocidade",         f"{no.velocidade_nos:.1f} nós",                 TEXTO),
            ("Calado / prof.",     f"{no.calado_m:.1f} / {no.profundidade_m:.1f} m", TEXTO),
            ("Margem sob quilha",  f"{no.margem_sob_quilha_m:.2f} m",             cor_risco),
            ("Risco de calado",    no.classe_risco,                               cor_risco),
            ("", "", TEXTO),
            ("Coletas geradas", str(no.bundles_criados), TEXTO),
            ("A bordo agora", f"{a_bordo} de {cfg.limite_buffer} "
                              f"({ocupacao * 100:.0f}%)",
             DESTAQUE if ocupacao > 0.5 else TEXTO),
            ("  leitura de rotina", str(rotina), TEXTO_FRACO),
            ("  seguranca periodica", str(seguranca), TEXTO_FRACO),
            ("  alerta de risco", str(alerta),
             CORES_RISCO[RISCO_CRITICO] if alerta else TEXTO_FRACO),
            ("Mais antiga a bordo", f"{mais_velho:.1f} h" if mais_velho else "-", TEXTO),
            ("Enviada ao gateway", str(no.transmitiu_ao_gateway), AZUL),
            ("Informacao a tempo", "sim" if no.informacao_a_tempo else "nao",
             VERDE if no.informacao_a_tempo else TEXTO_FRACO),
            ("", "", TEXTO),
            ("Transmissoes / recebidas",
             f"{no.transmitidos} / {no.recebidos}", TEXTO),
            ("Saltos / copias",
             f"{no.saltos_totais} / {len(no.bids_enviados)}", TEXTO),
            ("Em transmissao", "sim" if no.em_transmissao else "nao",
             (0, 210, 255) if no.em_transmissao else TEXTO_FRACO),
            ("Contatos ativos", str(len(no.contatos_ativos)), AZUL),
            ("Energia", f"{no.energia_j * 1000.0:.1f} mJ", AZUL),
        ]
        return linhas

    # -- minimapa --------------------------------------------------------
    def _desenhar_minimapa(self) -> None:
        if not self.camadas.minimapa or self.visao.zoom <= 1.001:
            return
        larg, alt = 150, 90
        x1 = LARGURA_SIMULACAO_BASE - larg - 12
        y1 = ALTURA_MENU + 12
        if self._minimapa is None:
            self._minimapa = pygame.transform.smoothscale(
                self._garantir_base_1x(), (larg, alt))
        self.tela.blit(self._minimapa, (x1, y1))
        pygame.draw.rect(self.tela, BORDA, (x1, y1, larg, alt), 1)
        escala = larg / LARGURA_SIMULACAO_BASE
        r = self.visao.recorte_base()
        caixa = pygame.Rect(
            x1 + r.x / RES_BASE * escala, y1 + r.y / RES_BASE * escala,
            r.width / RES_BASE * escala, r.height / RES_BASE * escala)
        # com a folga de arrasto o recorte pode sair do mundo; limita a caixa
        # para o retangulo nao vazar sobre o painel
        caixa = caixa.clip(pygame.Rect(x1, y1, larg, alt))
        pygame.draw.rect(self.tela, (10, 16, 22), caixa.inflate(4, 4), 1)
        pygame.draw.rect(self.tela, (255, 255, 255), caixa, 1)
        self._texto(f"{self.visao.zoom:.1f}x", (x1 + larg - 34, y1 + alt + 2),
                    (230, 238, 248), self.f_pequena)

    # -- painel ----------------------------------------------------------
    def _desenhar_painel(self) -> None:
        x0 = LARGURA_SIMULACAO_BASE
        pygame.draw.rect(self.tela, COR_PAINEL, (x0, 0, LARGURA_PAINEL, ALTURA_TOTAL))
        pygame.draw.line(self.tela, BORDA, (x0, 0), (x0, ALTURA_TOTAL), 1)
        r = self.motor.resumo()
        y = 10
        self._texto("ESTADO DA SIMULACAO", (x0 + 12, y), DESTAQUE, self.f_painel_t)
        y += 24
        for rot, val in (
            ("Cenario", f"{r.get('cenario', '?')} - {r.get('cenario_nome', '?')}"),
            ("Protocolo", r.get("protocolo_rotulo", r.get("protocolo", "?"))),
            ("Tempo", f"{_n(r.get('tempo_simulado_h'))} h de {self.cfg.horizonte_h:.0f} h"),
            ("Passo", f"{self.cfg.passo_s:.0f} s"),
            ("Velocidade", f"{self.velocidade} passos/s"),
            ("Ritmo real", f"{self.velocidade_efetiva * self.cfg.passo_s / 3600.0:.2f} h/s"),
            ("Zoom", f"{self.visao.zoom:.2f}x"),
            ("Semente", str(self.cfg.semente)),
        ):
            y = self._linha_painel(x0, y, rot, val)
        y = self._divisor(x0, y)
        self._texto("DESEMPENHO", (x0 + 12, y), DESTAQUE, self.f_painel_t)
        y += 22
        for rot, val in (
            ("TED", f"{_n(r.get('ted_percentual'))}%"),
            ("TED (6 h)", f"{_n(r.get('ted_no_horizonte_percentual'))}%"),
            ("LPA", f"{_n(r.get('lpa_minutos'))} min"),
            ("CAR", _n(r.get("car_percentual")) + "%"),
            ("TCI", _n(r.get("tci_horas")) + " h"),
            ("Overhead", f"{_n(r.get('overhead_copias'), 2)} x"),
            ("Saltos medios", f"{_n(r.get('saltos_medios'), 2)}"),
            ("Transmissoes", str(r.get("transmissoes", 0))),
            ("Adiadas (duty)", str(r.get("transmissoes_adiaadas", 0))),
            ("Redund. suprimidas", str(r.get("retransmissoes_suprimidas", 0))),
            ("Uploads redundantes", str(r.get("uploads_redundantes", 0))),
            ("Airtime", f"{_n(r.get('airtime_total_s'), 0)} s"),
            ("Energia", f"{_n(r.get('energia_media_por_no_mJ'))} mJ/no"),
        ):
            y = self._linha_painel(x0, y, rot, val, cor=AZUL)
        y = self._divisor(x0, y)
        y = self._linha_painel(x0, y, "Cobertura fixa", f"{_n(r.get('cobertura_gateway_percentual'))}%")
        y = self._linha_painel(x0, y, "Maior vao", f"{_n(r.get('maior_vao_gateway_km'))} km")
        y = self._linha_painel(x0, y, "Cobertura instantanea",
                               f"{_n(r.get('cobertura_instantanea_media'))}%", cor=AZUL)
        y = self._linha_painel(x0, y, "Gateways (fixos + moveis)",
                               f"{_n(r.get('super_nos'))} "
                               f"({_n(r.get('gateways_moveis'))} moveis)", cor=AZUL)
        y = self._divisor(x0, y)
        frota = self.motor.frota
        # a frota tem mais nos que o painel comporta: a lista rola com a roda
        # do mouse sobre o painel, senao parte das embarcacoes ficaria
        # inalcancavel para selecao
        disponivel = max(ALTURA_LINHA_FROTA, ALTURA_TOTAL - y - 18)
        visiveis = max(1, disponivel // ALTURA_LINHA_FROTA)
        self._frota_scroll = max(0, min(self._frota_scroll, len(frota) - visiveis))
        titulo = "FROTA (clique para o status)"
        if len(frota) > visiveis:
            titulo += f"  {self._frota_scroll + 1}-{self._frota_scroll + visiveis}/{len(frota)}"
        self._texto(titulo, (x0 + 12, y), DESTAQUE, self.f_painel_t)
        y += 20
        self._linhas_frota = []
        for no in frota[self._frota_scroll:self._frota_scroll + visiveis]:
            cor = CORES_RISCO[no.classe_risco]
            escolhido = no.id == self.selecionado_id
            if escolhido:
                pygame.draw.rect(self.tela, (46, 56, 72),
                                 pygame.Rect(x0 + 4, y - 2, LARGURA_PAINEL - 8,
                                             ALTURA_LINHA_FROTA))
            icone = self._icone_rotacionado(no.tipo, cor, 0.0)
            self.tela.blit(pygame.transform.scale(
                icone, (10, 10)), (x0 + 12, y))
            rot = f"ID {no.id} {no.nome_tipo[:13]}"
            val = f"km {no.km_atual:5.1f}  {len(no.buffer):3d} bds"
            self.tela.blit(self._texto_surf(rot, TEXTO, self.f_pequena), (x0 + 26, y - 1))
            self.tela.blit(self._texto_surf(val, cor, self.f_pequena), (x0 + 150, y - 1))
            self._linhas_frota.append(
                (pygame.Rect(x0 + 4, y - 2, LARGURA_PAINEL - 8, ALTURA_LINHA_FROTA),
                 no.id))
            y += ALTURA_LINHA_FROTA
        if len(frota) > visiveis:
            # indicador de rolagem
            h = disponivel
            p = h / len(frota)
            y0 = self._frota_scroll * p
            pygame.draw.rect(self.tela, (20, 26, 34),
                             pygame.Rect(x0 + LARGURA_PAINEL - 7, y - visiveis * ALTURA_LINHA_FROTA,
                                         4, h))
            pygame.draw.rect(self.tela, BORDA,
                             pygame.Rect(x0 + LARGURA_PAINEL - 7,
                                         y - visiveis * ALTURA_LINHA_FROTA + int(y0), 4,
                                         max(12, int(p * visiveis))))

    def _divisor(self, x0: int, y: int) -> int:
        pygame.draw.line(self.tela, BORDA, (x0 + 10, y + 4), (x0 + LARGURA_PAINEL - 10, y + 4))
        return y + 14

    def _linha_painel(self, x0: int, y: int, rot: str, val: str, cor=None) -> int:
        self.tela.blit(self._texto_surf(rot, TEXTO_FRACO, self.f_pequena), (x0 + 12, y))
        surf = self._texto_surf(val, cor or TEXTO, self.f_painel)
        self.tela.blit(surf, (x0 + LARGURA_PAINEL - 12 - surf.get_width(), y - 1))
        return y + 17

    # -- menu ------------------------------------------------------------
    def _desenhar_menu(self) -> None:
        pygame.draw.rect(self.tela, (18, 24, 33), (0, 0, LARGURA_TOTAL, ALTURA_MENU))
        pygame.draw.line(self.tela, BORDA, (0, ALTURA_MENU - 1), (LARGURA_TOTAL, ALTURA_MENU - 1))
        x = 8
        for i, (menu, larg) in enumerate(zip(self.menus, self._larguras_menu)):
            ativo = self._menu_aberto == i
            if ativo:
                pygame.draw.rect(self.tela, (38, 48, 62), (x - 6, 0, larg, ALTURA_MENU))
            self.tela.blit(self._texto_surf(
                menu.titulo, DESTAQUE if ativo else TEXTO, self.f_menu),
                (x, (ALTURA_MENU - self.f_menu.get_height()) // 2))
            x += larg
        self._desenhar_botoes()
        # indicador de estado: cenário · protocolo · tempo
        cenario_cod = self.motor.cenario.codigo
        protocolo = self.motor.protocolo.nome
        t_h = self.motor.t_s / 3600.0
        estado_str = f"{cenario_cod} · {protocolo} · t={t_h:.1f}h"
        s_estado = self._texto_surf(estado_str, (150, 170, 200), self.f_pequena)
        # centralizado entre os menus (à esquerda) e os botões (à direita)
        menus_fim = sum(self._larguras_menu) + 8
        botoes = self._botoes_acao()
        botoes_inicio = botoes[0][0].x if botoes else LARGURA_TOTAL
        cx = (menus_fim + botoes_inicio) // 2
        self.tela.blit(s_estado, (cx - s_estado.get_width() // 2,
                                   (ALTURA_MENU - s_estado.get_height()) // 2))
        if self._menu_aberto is not None:
            self._desenhar_dropdown(self.menus[self._menu_aberto], self._menu_aberto)

    def _desenhar_botoes(self) -> None:
        """
        Botoes de execucao na barra superior.

        Iniciar e parar ficam em botao, e nao so em item de menu: sao a acao mais
        frequente da interface e o menudropdown exigia dois cliques para abrir.
        A velocidade tambem ganha botao, com o valor pedido entre os dois, para
        que ajustar o ritmo nao exija abrir o menu *Simulacao*.
        """
        for caixa, chave, principal in self._botoes_acao():
            if chave == "velocidade":
                # indicador do ritmo pedido em passos por segundo real
                pygame.draw.rect(self.tela, (20, 26, 36), caixa)
                pygame.draw.rect(self.tela, BORDA, caixa, 1)
                txt = f"{self.velocidade}"
                cor_txt = DESTAQUE if self.rodando else TEXTO_FRACO
            elif chave in ("mais_rapido", "mais_devagar"):
                pygame.draw.rect(self.tela, (32, 40, 52), caixa)
                pygame.draw.rect(self.tela, BORDA, caixa, 1)
                no_extremo = ((chave == "mais_rapido" and
                               self.indice_velocidade == len(VELOCIDADES) - 1) or
                              (chave == "mais_devagar" and self.indice_velocidade == 0))
                cor_txt = (58, 68, 84) if no_extremo else TEXTO
                txt = "+" if chave == "mais_rapido" else "-"
            elif chave == "executar":
                pygame.draw.rect(self.tela, (34, 96, 74) if not self.rodando
                                 else (112, 46, 44), caixa)
                pygame.draw.rect(self.tela,
                                 VERDE if not self.rodando else (240, 120, 110),
                                 caixa, 2)
                cor_txt = (238, 250, 242) if not self.rodando else (255, 232, 228)
                txt = "Parar" if self.rodando else "Iniciar"
            else:
                pygame.draw.rect(self.tela, (32, 40, 52) if chave == "passo"
                                 else (26, 32, 42), caixa)
                pygame.draw.rect(self.tela, BORDA, caixa, 1)
                cor_txt = TEXTO
                txt = "Passo" if chave == "passo" else "Reiniciar"
            surf = self._texto_surf(txt, cor_txt, self.f_menu)
            self.tela.blit(surf, (caixa.centerx - surf.get_width() // 2,
                                  caixa.centery - surf.get_height() // 2))

    def _desenhar_dropdown(self, menu: Menu, indice: int) -> None:
        caixas = self._caixas_dropdown(menu, indice)
        largura = self._largura_dropdown(menu)
        alt = 4 + sum((20 if i.rotulo else 9) if i.separador else 26 for i in menu.itens)
        x = caixas[0][0].x if caixas else 8
        if x + largura > LARGURA_TOTAL:
            x = LARGURA_TOTAL - largura - 4
        pygame.draw.rect(self.tela, (26, 33, 44), (x, ALTURA_MENU, largura, alt))
        pygame.draw.rect(self.tela, BORDA, (x, ALTURA_MENU, largura, alt), 1)
        for caixa, item in caixas:
            if item.separador:
                if item.rotulo:
                    s_sec = self._texto_surf(item.rotulo, (135, 160, 195), self.f_pequena)
                    self.tela.blit(s_sec, (caixa.x + 14, caixa.y + 4))
                else:
                    pygame.draw.line(self.tela, (48, 60, 78),
                                     (caixa.x + 8, caixa.centery), (caixa.right - 8, caixa.centery))
                continue
            self.tela.blit(self._texto_surf(item.rotulo, TEXTO, self.f_menu),
                           (caixa.x + 14, caixa.y + 2))
            if item.marcado is not None:
                marca = pygame.Rect(caixa.right - 24, caixa.y + 5, 14, 14)
                pygame.draw.rect(self.tela, (44, 54, 68), marca)
                pygame.draw.rect(self.tela, (44, 54, 68), marca, 1)
                if item.marcado():
                    pygame.draw.rect(self.tela, VERDE, marca.inflate(-4, -4))

    # -- texto -----------------------------------------------------------
    def _texto_surf(self, txt: str, cor, fonte=None) -> pygame.Surface:
        """Rasteriza uma string, memorizando o resultado por conteudo e cor."""
        f = fonte or self.f_pequena
        chave = (id(f), txt, cor)
        surf = self._cache_texto.get(chave)
        if surf is None:
            surf = f.render(txt, True, cor)
            if len(self._cache_texto) > 3000:
                self._cache_texto.clear()
            self._cache_texto[chave] = surf
        return surf

    def _texto(self, txt: str, pos, cor, fonte=None) -> None:
        self.tela.blit(self._texto_surf(txt, cor, fonte), pos)

    def _avisar(self, msg: str) -> None:
        self.mensagem = msg
        self.mensagem_ate = pygame.time.get_ticks() + 3000

    def _desenhar_aviso(self) -> None:
        if not self.mensagem or pygame.time.get_ticks() > self.mensagem_ate:
            return
        surf = self._texto_surf(self.mensagem, (20, 26, 34), self.f_pequena)
        pad = pygame.Rect(0, 0, surf.get_width() + 18, surf.get_height() + 10)
        pad.center = (LARGURA_SIMULACAO_BASE // 2, ALTURA_TOTAL - 30)
        pygame.draw.rect(self.tela, (250, 205, 130), pad)
        self.tela.blit(surf, pad.topleft + (9, 5))

    # -- carta nautica ---------------------------------------------------
    def _gerar_carta(self) -> pygame.Surface:
        """Monta a carta completa e a reduz para caber na janela."""
        carta = CartaNautica(self.camadas.para_opcoes(1.6))
        img = carta.render(self.motor.cenario, self.motor.t_s / 3600.0, motor=self.motor)
        cheia = pygame.image.frombytes(img.tobytes(), img.size, "RGB")
        fator = min(LARGURA_TOTAL / img.width, (ALTURA_TOTAL - 34) / img.height)
        return pygame.transform.smoothscale(cheia, (int(img.width * fator),
                                                    int(img.height * fator)))

    def _janela_carta(self) -> pygame.Surface:
        return self._carta_cheia or self._carta

    def _alternar_carta(self) -> None:
        self._menu_aberto = None
        if self._carta is not None:
            self._carta = None
            self._restaurar_titulo()
            return
        self._carta_cheia = self._gerar_carta()
        self._carta = self._carta_cheia
        pygame.display.set_caption("Carta nautica  |  S: salvar PNG   ESC: voltar")
        self._avisar("Carta gerada.")

    def _restaurar_titulo(self) -> None:
        pygame.display.set_caption(
            "FLoRA-DTN  |  Simulador DTN-LoRa - Calha do Amazonas (UFAM)")

    def _salvar_padrao(self) -> None:
        self._menu_aberto = None
        self._carta_cheia = self._gerar_carta()
        self._carta = self._carta_cheia
        nome = (f"carta_{self.motor.cenario.codigo}_"
                f"{self.motor.t_s / 3600.0:.0f}h_{self.motor.protocolo.nome}.png")
        pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cartas")
        self._salvar_em(os.path.join(pasta, nome))

    def _gerar_e_salvar(self) -> None:
        self._menu_aberto = None
        self._carta_cheia = self._gerar_carta()
        self._carta = self._carta_cheia
        caminho = self._salvar_carta_dialogo()
        if caminho:
            self._salvar_em(caminho)

    def _salvar_carta_dialogo(self) -> str | None:
        try:
            import tkinter as tk
            from tkinter import filedialog

            raiz = tk.Tk()
            raiz.withdraw()
            inicial = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cartas")
            os.makedirs(inicial, exist_ok=True)
            caminho = filedialog.asksaveasfilename(
                title="Salvar carta nautica", defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("Todos os arquivos", "*.*")],
                initialdir=inicial)
            raiz.destroy()
            return caminho or None
        except Exception as exc:
            self._avisar(f"Janela de dialogo indisponivel ({exc.__class__.__name__}); "
                         f"use 'Salvar no diretorio padrao'.")
            return None

    def _salvar_em(self, caminho: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
        pygame.image.save(self._janela_carta(), caminho)
        self._avisar(f"Carta salva em {caminho}")

    def _exportar_metricas(self) -> None:
        self._menu_aberto = None
        pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
        os.makedirs(pasta, exist_ok=True)
        nome = (f"metricas_{self.motor.cenario.codigo}_{self.motor.protocolo.nome}_"
                f"{self.motor.t_s / 3600.0:.0f}h.csv")
        caminho = os.path.join(pasta, nome)
        self.motor.exportar_metricas(caminho)
        self._avisar(f"Metricas salvas em {caminho}")

    def _exportar_frota(self) -> None:
        self._menu_aberto = None
        pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
        os.makedirs(pasta, exist_ok=True)
        nome = (f"frota_{self.motor.cenario.codigo}_{self.motor.protocolo.nome}_"
                f"{self.motor.t_s / 3600.0:.0f}h.csv")
        caminho = os.path.join(pasta, nome)
        self.motor.exportar_frota(caminho)
        self._avisar(f"Frota salva em {caminho}")

    def _exportar_config(self) -> None:
        self._menu_aberto = None
        pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
        os.makedirs(pasta, exist_ok=True)
        nome = (f"config_{self.motor.cenario.codigo}_{self.motor.protocolo.nome}.json")
        caminho = os.path.join(pasta, nome)
        self.motor.exportar_config(caminho)
        self._avisar(f"Config salva em {caminho}")

    def _exportar_simulacao(self) -> None:
        """Grava a simulacao inteira em um unico JSON, pronto para analise."""
        self._menu_aberto = None
        pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
        os.makedirs(pasta, exist_ok=True)
        nome = (f"simulacao_{self.motor.cenario.codigo}_"
                f"{self.motor.protocolo.nome}_"
                f"{self.motor.t_s / 3600.0:.0f}h_s{self.cfg.semente}.json")
        caminho = os.path.join(pasta, nome)
        self.motor.exportar_simulacao(caminho)
        self._avisar(f"Simulacao completa salva em {caminho}")

    def _exportar_tudo(self) -> None:
        self._menu_aberto = None
        pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
        os.makedirs(pasta, exist_ok=True)
        base = os.path.join(pasta,
                            f"{self.motor.cenario.codigo}_{self.motor.protocolo.nome}_"
                            f"{self.motor.t_s / 3600.0:.0f}h_s{self.cfg.semente}")
        self.motor.exportar_tudo(base)
        self._avisar(f"Exportado em {base}_*.csv/json")

    def _abrir_dialogo_adicionar(self) -> None:
        """Abre o dialogo inline para adicionar uma nova embarcacao."""
        self._menu_aberto = None
        self._dialogo_frota = DialogoAdicionarEmbarcacao(self)

    def _remover_selecionada(self) -> None:
        """Remove a embarcacao selecionada da frota."""
        self._menu_aberto = None
        no = self._embarcacao_selecionada()
        if no is None:
            self._avisar("Nenhuma embarcacao selecionada. Clique numa para selecionar.")
            return
        id_rem = no.id
        tipo_rem = no.nome_tipo
        ok = self.motor.remover_embarcacao(id_rem)
        if ok:
            self.selecionado_id = None
            self._ficha_chave = None
            self._avisar(f"Embarcacao {tipo_rem} ID {id_rem} removida da frota.")
        else:
            self._avisar(f"Nao foi possivel remover ID {id_rem}.")

    # -- ajuda -----------------------------------------------------------
    def _mostrar_atalhos(self) -> None:
        self._menu_aberto = None
        self._avisar("Botoes: Iniciar/Parar, Passo, Reiniciar | "
                     "Espaco: iniciar/pausar | Direita: passo | R: reiniciar | "
                     "C: carta | Ctrl+S: salvar | 1-5: protocolo | "
                     "Roda/+/-: zoom | 0: reenquadrar | arrastar: mover | "
                     "clique na embarcacao: status de coleta | Esc: limpar")

    def _mostrar_sobre(self) -> None:
        self._menu_aberto = None
        self._avisar("FLoRA-DTN: simulador de redes tolerantes a atraso com "
                     "LoRa sobre a calha do Amazonas (UFAM).")
