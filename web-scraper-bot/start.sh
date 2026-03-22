#!/usr/bin/env bash
# WebAuditBot SES - Script de inicialização Linux/Mac
# Uso: ./start.sh [--port 8080] [--no-browser]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "============================================================"
echo "  WebAuditBot SES - Interface Web"
echo "============================================================"
echo ""

# Verifica Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERRO] Python 3 não encontrado. Instale em https://python.org"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Python: $PYTHON_VERSION"

# Cria ambiente virtual se não existir
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "  Criando ambiente virtual..."
    python3 -m venv "$VENV_DIR"
fi

# Ativa ambiente virtual
source "$VENV_DIR/bin/activate"

# Instala dependências
echo "  Verificando dependências..."
pip install -r "$SCRIPT_DIR/requirements.txt" -q

echo ""
echo "  Iniciando servidor..."
echo ""

# Inicia o launcher
python3 "$SCRIPT_DIR/run.py" "$@"
