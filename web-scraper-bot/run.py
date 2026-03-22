#!/usr/bin/env python3
"""
WebAuditBot SES - Launcher
Verifica dependências, inicia o servidor Flask e abre o navegador automaticamente.

Uso:
    python run.py
    python run.py --port 8080
    python run.py --no-browser
"""

import argparse
import importlib
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
REQUIRED = ["flask", "requests", "bs4", "lxml"]


def check_and_install_deps():
    """Verifica e instala dependências faltantes."""
    missing = []
    for pkg in REQUIRED:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[!] Dependências faltantes: {', '.join(missing)}")
        answer = input("    Instalar automaticamente? (s/n): ").strip().lower()
        if answer in ("s", "sim", "y", "yes"):
            req_file = ROOT / "requirements.txt"
            print("[*] Instalando dependências...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])
            print("[+] Dependências instaladas.\n")
        else:
            print("[!] Instale manualmente: pip install -r requirements.txt")
            sys.exit(1)


def wait_and_open(url: str, delay: float = 1.5):
    """Abre o navegador após um pequeno delay."""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="WebAuditBot SES - Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python run.py                 Inicia na porta padrão (5000)
  python run.py --port 8080     Inicia na porta 8080
  python run.py --no-browser    Não abre o navegador automaticamente
        """
    )
    parser.add_argument("--port",       type=int, default=5000,  help="Porta HTTP (padrão: 5000)")
    parser.add_argument("--host",       default="127.0.0.1",     help="Host (padrão: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true",     help="Não abrir navegador automaticamente")
    parser.add_argument("--debug",      action="store_true",     help="Modo debug do Flask (não recomendado em produção)")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  WebAuditBot SES - Interface Web")
    print("=" * 60)
    print()

    # Verifica dependências
    check_and_install_deps()

    # Garante que diretórios necessários existem
    for d in ["logs", "exports", "imports", "reports"]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)

    url = f"http://{args.host}:{args.port}"
    print(f"  Iniciando servidor em: {url}")
    print(f"  Pressione Ctrl+C para parar.\n")

    if not args.no_browser:
        t = threading.Thread(target=wait_and_open, args=(url,), daemon=True)
        t.start()

    # Importa e inicia o app Flask
    sys.path.insert(0, str(ROOT))
    from web_app import app
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        threaded=True,
        use_reloader=False
    )


if __name__ == "__main__":
    main()
