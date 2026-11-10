# ==========================================================================
#  executar.ps1 - launcher do FLoRA-DTN para PowerShell.
#
#  Chamadas com caminho absoluto precisam de um unico par de aspas. Este
#  script resolve o caminho a partir da propria localizacao, entao nao ha
#  aspas aninhadas para o usuario escrever:
#
#      .\executar.ps1 --version
#      .\executar.ps1 rodar -c C3 -p flora -H 168
#      .\executar.ps1 comparar -c C3 -H 168 --paralelo
#      .\executar.ps1 analisar -e resultados
#
#  Se a politica de execucao bloquear o .ps1, use executar.bat ou rode:
#      powershell -ExecutionPolicy Bypass -File .\executar.ps1 --version
# ==========================================================================

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $raiz "dtn_simulador.py"

if (-not (Test-Path -LiteralPath $script)) {
    Write-Error "dtn_simulador.py nao encontrado em $raiz"
    exit 1
}

$python = $env:FLORA_PYTHON
if (-not $python) {
    $comando = Get-Command python -ErrorAction SilentlyContinue
    if ($comando) { $python = $comando.Source }
}
if (-not $python) {
    Write-Error "Python nao encontrado no PATH. Defina FLORA_PYTHON com o caminho do python.exe."
    exit 1
}

& $python $script @args
exit $LASTEXITCODE
