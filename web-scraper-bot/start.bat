@echo off
REM WebAuditBot SES - Script de inicialização Windows
REM Duplo clique para iniciar ou execute: start.bat [--port 8080]

title WebAuditBot SES

echo.
echo ============================================================
echo   WebAuditBot SES - Interface Web
echo ============================================================
echo.

REM Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo        Baixe em: https://python.org/downloads
    echo        Marque "Add Python to PATH" na instalacao.
    pause
    exit /b 1
)

SET SCRIPT_DIR=%~dp0
SET VENV_DIR=%SCRIPT_DIR%.venv

REM Cria ambiente virtual se nao existir
if not exist "%VENV_DIR%" (
    echo   Criando ambiente virtual...
    python -m venv "%VENV_DIR%"
)

REM Ativa ambiente virtual
call "%VENV_DIR%\Scripts\activate.bat"

REM Instala dependencias
echo   Verificando dependencias...
pip install -r "%SCRIPT_DIR%requirements.txt" -q

echo.
echo   Iniciando servidor...
echo.

REM Inicia o launcher
python "%SCRIPT_DIR%run.py" %*

pause
