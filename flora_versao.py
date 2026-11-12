# -*- coding: utf-8 -*-
"""
flora_versao.py
===============

Identidade da versao do simulador FLoRA-DTN.

A versao vem do codigo e o *commit* e resolvido em cascata, para funcionar
tanto num clone git quanto numa copia solta (o caso desta pasta):

1. variavel de ambiente ``FLORA_COMMIT`` (util em CI e em pacotes gerados);
2. ``git rev-parse --short HEAD`` no diretorio do projeto;
3. arquivo ``COMMIT`` na raiz do projeto (uma linha, gerado no empacotamento);
4. ``sem-git``.

Nenhuma etapa levanta excecao: o ``--version`` tem de responder mesmo sem
repositorio, sem rede e sem permissao de leitura.
"""

from __future__ import annotations

import os
import subprocess

from flora_geometria import DISTANCIA_CORREDOR_KM

#: Nome publico do projeto.
NOME = "FLoRA-DTN"

#: Versao semantica. A regra e: funcionalidade nova sobe o minor; correcao de
#: comportamento sobe o patch; mudanca incompativel de CLI ou de CSV sobe o
#: major.
VERSAO = "1.3.0"

RAIZ = os.path.dirname(os.path.abspath(__file__))

#: Sufixo devolvido quando o hash nao pode ser determinado de nenhum modo.
COMMIT_DESCONHECIDO = "sem-git"

#: Cache por raiz: `construir_parser` e chamado varias vezes na mesma sessao e
#: nao ha por que repetir a chamada ao git.
_CACHE_COMMIT: dict[str, str] = {}


def limpar_cache() -> None:
    """Esquece os hashes ja resolvidos (util em testes)."""
    _CACHE_COMMIT.clear()


def resolver_commit(raiz: str | None = None) -> str:
    """
    Devolve o hash curto do commit que gerou esta copia do simulador.

    Parameters
    ----------
    raiz:
        Diretorio onde procurar ``.git`` e o arquivo ``COMMIT``. Por padrao,
        o diretorio de `flora_versao.py`.

    Returns
    -------
    str
        Hash curto, ou ``"sem-git"`` se nada estiver disponivel.
    """
    ambiente = os.environ.get("FLORA_COMMIT", "").strip()
    if ambiente:
        return ambiente[:12]

    base = raiz or RAIZ
    if base in _CACHE_COMMIT:
        return _CACHE_COMMIT[base]

    _CACHE_COMMIT[base] = _descobrir_commit(base)
    return _CACHE_COMMIT[base]


def _descobrir_commit(base: str) -> str:
    try:
        saida = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=base,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if saida.returncode == 0:
            hash_git = saida.stdout.strip()
            if hash_git:
                return hash_git[:12]
    except (OSError, subprocess.SubprocessError):
        # git ausente, cwd invalido ou timeout: cai para o arquivo COMMIT.
        pass

    try:
        with open(os.path.join(base, "COMMIT"), encoding="utf-8") as fh:
            hash_arquivo = fh.readline().strip()
        if hash_arquivo:
            return hash_arquivo[:12]
    except OSError:
        pass

    return COMMIT_DESCONHECIDO


def versao_completa(raiz: str | None = None) -> str:
    """Texto de uma linha, por exemplo ``FLoRA-DTN 1.1.0 (commit abc1234)``."""
    return f"{NOME} {VERSAO} (commit {resolver_commit(raiz)}) distancia_corredor_km={DISTANCIA_CORREDOR_KM}"


def banner(raiz: str | None = None) -> str:
    """Banner de abertura das execucoes, com versao e commit."""
    return (
        f"{NOME} {VERSAO}\n"
        f"Simulador DTN-LoRa da calha do Amazonas (UFAM)\n"
        f"commit {resolver_commit(raiz)} | Python {_python()} | distancia_corredor_km={DISTANCIA_CORREDOR_KM}"
    )


def _python() -> str:
    import platform

    return platform.python_version()
