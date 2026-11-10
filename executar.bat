@echo off
rem ==========================================================================
rem  executar.bat - launcher do FLoRA-DTN para Windows.
rem
rem  Evita o problema de aspas aninhadas ao chamar o Python com caminho
rem  absoluto. Use da pasta do projeto:
rem
rem      executar.bat --version
rem      executar.bat rodar -c C3 -p flora -H 168
rem      executar.bat comparar -c C3 -H 168 --paralelo
rem      executar.bat analisar -e resultados
rem
rem  Para escolher outro interpretador, defina FLORA_PYTHON antes de chamar:
rem
rem      set FLORA_PYTHON=C:\caminho\python.exe
rem      executar.bat --version
rem ==========================================================================
setlocal

set "SCRIPT=%~dp0dtn_simulador.py"

if defined FLORA_PYTHON (
    "%FLORA_PYTHON%" "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%SCRIPT%" %*
    exit /b %ERRORLEVEL%
)

echo Python nao encontrado no PATH. Defina FLORA_PYTHON com o caminho do python.exe.
exit /b 1
