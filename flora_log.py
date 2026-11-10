# -*- coding: utf-8 -*-
"""
flora_log.py
============

Configuracao de logging em arquivo para o simulador FLoRA-DTN.

Cada execucao grava um arquivo proprio em ``logs/`` (ou no caminho pedido em
``--log-arquivo``). O terminal continua a cargo dos ``print`` existentes; o
handler de console so entra para avisos e erros, de modo que a tabela do modo
``comparar`` nao sai duplicada.

O logging e opcional e defensivo: se a pasta nao puder ser criada, a execucao
segue sem arquivo em vez de abortar a simulacao.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

RAIZ = os.path.dirname(os.path.abspath(__file__))

#: Nome do logger raiz do projeto. Os modulos usam ``logging.getLogger("flora")``.
LOGGER = "flora"

_FORMATO = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATA = "%Y-%m-%d %H:%M:%S"

#: Guarda o arquivo aberto pela ultima chamada, para os testes e para o resumo
#: final da execucao.
_arquivo_atual: str | None = None


def caminho_padrao(pasta: str | None = None) -> str:
    """Caminho sugerido para a proxima execucao, sem criar nada em disco."""
    destino = pasta or os.path.join(RAIZ, "logs")
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(destino, f"flora_{carimbo}_{os.getpid()}.log")


def configurar(
    arquivo: str | None = None,
    *,
    pasta: str | None = None,
    nivel: int = logging.INFO,
    console: bool = False,
    sobrescrever: bool = False,
) -> str | None:
    """
    Liga o logging em arquivo e devolve o caminho usado.

    Parameters
    ----------
    arquivo:
        Arquivo de log. Se omitido, usa `caminho_padrao`.
    pasta:
        Pasta onde criar o log padrao (ignorada quando ``arquivo`` e dado).
    nivel:
        Nivel minimo gravado no arquivo.
    console:
        Tambem escreve no ``stderr``. O padrao e nao duplicar a saida normal.
    sobrescrever:
        Reaproveita o mesmo arquivo em vez de anexar. Util em testes.

    Returns
    -------
    str | None
        Caminho do arquivo, ou ``None`` se nao foi possivel abrir.
    """
    global _arquivo_atual

    logger = logging.getLogger(LOGGER)
    _remover_handlers(logger)
    logger.setLevel(min(nivel, logging.DEBUG))
    logger.propagate = False

    caminho = arquivo or caminho_padrao(pasta)
    if os.path.dirname(caminho):
        os.makedirs(os.path.dirname(caminho), exist_ok=True)

    try:
        handler = logging.FileHandler(
            caminho, mode="w" if sobrescrever else "a", encoding="utf-8"
        )
    except OSError:
        _arquivo_atual = None
        return None

    handler.setLevel(nivel)
    handler.setFormatter(logging.Formatter(_FORMATO, datefmt=_DATA))
    logger.addHandler(handler)

    if console:
        tela = logging.StreamHandler()
        tela.setLevel(logging.WARNING if nivel >= logging.INFO else logging.DEBUG)
        tela.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(tela)

    _arquivo_atual = caminho
    return caminho


def obter_logger(nome: str | None = None) -> logging.Logger:
    """Logger filho de ``flora``, ja sob a configuracao ativa."""
    return logging.getLogger(LOGGER if not nome else f"{LOGGER}.{nome}")


def arquivo_atual() -> str | None:
    """Arquivo aberto pela ultima chamada a `configurar`."""
    return _arquivo_atual


def desligar() -> None:
    """Remove os handlers e silencia o logger (usado por ``--sem-log``)."""
    global _arquivo_atual
    logger = logging.getLogger(LOGGER)
    _remover_handlers(logger)
    logger.setLevel(logging.CRITICAL + 1)
    logger.propagate = False
    _arquivo_atual = None


def _remover_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
