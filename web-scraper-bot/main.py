#!/usr/bin/env python3
"""
WebAuditBot - Ponto de entrada principal
Sistema de Auditoria Web com mapeamento de erros e sugestões de correção.

Uso:
  # Auditar uma URL
  python main.py --targets https://exemplo.com

  # Auditar múltiplas URLs
  python main.py --targets https://site1.com https://site2.com

  # Importar targets de ZIP
  python main.py --import-zip imports/targets.zip

  # Usar arquivo de configuração customizado
  python main.py --config config/minha_config.json --targets https://exemplo.com

  # Listar ZIPs disponíveis para importação
  python main.py --list-imports

  # Consultar falhas no Oracle
  python main.py --query-oracle --session <SESSION_ID>
"""

import argparse
import json
import sys
from pathlib import Path


def load_json_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_args():
    parser = argparse.ArgumentParser(
        description="WebAuditBot - Sistema de Auditoria Web SES",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--targets", nargs="+", metavar="URL",
        help="URLs para auditar (espaço entre URLs)"
    )
    parser.add_argument(
        "--import-zip", metavar="ZIP",
        help="Caminho para ZIP com targets e/ou configuração"
    )
    parser.add_argument(
        "--config", default="config/config.json",
        metavar="JSON",
        help="Arquivo de configuração (padrão: config/config.json)"
    )
    parser.add_argument(
        "--rules", default="config/error_rules.json",
        metavar="JSON",
        help="Arquivo de regras de erro (padrão: config/error_rules.json)"
    )
    parser.add_argument(
        "--depth", type=int, default=None,
        help="Profundidade máxima de crawling (sobrescreve config)"
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="Máximo de páginas por alvo (sobrescreve config)"
    )
    parser.add_argument(
        "--no-oracle", action="store_true",
        help="Desabilita integração Oracle mesmo se configurado"
    )
    parser.add_argument(
        "--no-snapshots", action="store_true",
        help="Não captura snapshots HTML"
    )
    parser.add_argument(
        "--list-imports", action="store_true",
        help="Lista ZIPs disponíveis na pasta de importação"
    )
    parser.add_argument(
        "--query-oracle", action="store_true",
        help="Consulta falhas no Oracle"
    )
    parser.add_argument(
        "--session", metavar="SESSION_ID",
        help="ID de sessão para consulta Oracle"
    )
    parser.add_argument(
        "--severity", choices=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        help="Filtra por severidade (para --query-oracle)"
    )
    parser.add_argument(
        "--output-dir", metavar="DIR",
        help="Diretório de saída para exportações"
    )
    parser.add_argument(
        "--version", action="version", version="WebAuditBot SES v1.0"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Localiza arquivos de config relativos ao diretório do script
    script_dir = Path(__file__).parent
    config_path = script_dir / args.config
    rules_path = script_dir / args.rules

    # Carrega configuração
    if not config_path.exists():
        print(f"ERRO: Arquivo de configuração não encontrado: {config_path}", file=sys.stderr)
        sys.exit(1)
    config = load_json_file(str(config_path))

    if not rules_path.exists():
        print(f"AVISO: Arquivo de regras não encontrado: {rules_path}. Usando regras vazias.")
        error_rules = {}
    else:
        error_rules = load_json_file(str(rules_path))

    # Aplica overrides da linha de comando
    if args.depth is not None:
        config.setdefault("scraper", {})["max_depth"] = args.depth
    if args.max_pages is not None:
        config.setdefault("scraper", {})["max_pages"] = args.max_pages
    if args.no_oracle:
        config.setdefault("oracle", {})["enabled"] = False
    if args.no_snapshots:
        config.setdefault("export", {})["include_html_snapshots"] = False
    if args.output_dir:
        config.setdefault("export", {})["output_dir"] = args.output_dir

    # Ajusta caminhos relativos ao diretório do script
    for dir_key in ["output_dir", "import_dir", "report_dir"]:
        val = config.get("export", {}).get(dir_key, "")
        if val and not Path(val).is_absolute():
            config["export"][dir_key] = str(script_dir / val)
    log_dir = config.get("logging", {}).get("log_dir", "logs")
    if not Path(log_dir).is_absolute():
        config.setdefault("logging", {})["log_dir"] = str(script_dir / log_dir)

    # Importa o bot
    sys.path.insert(0, str(script_dir))
    from src.bot import WebAuditBot
    from src.zip_handler import ZipImporter

    # Modo: listar imports disponíveis
    if args.list_imports:
        importer = ZipImporter(config.get("export", {}), _DummyLogger())
        zips = importer.list_available_imports()
        if not zips:
            print("Nenhum ZIP encontrado na pasta de importação.")
        else:
            print(f"\nZIPs disponíveis em: {config.get('export', {}).get('import_dir', 'imports')}")
            print("-" * 60)
            for z in zips:
                print(f"  {z['filename']} ({z['size_kb']}KB) - {z['modified']}")
        return

    # Modo: consulta Oracle
    if args.query_oracle:
        bot = WebAuditBot(config, error_rules)
        bot.initialize()
        failures = bot.oracle.query_failures(
            session_id=args.session,
            severity=args.severity
        )
        if not failures:
            print("Nenhuma falha encontrada com os filtros informados.")
        else:
            print(f"\n{len(failures)} falha(s) encontrada(s):\n")
            for f in failures[:50]:
                print(f"  [{f.get('severity','')}] {f.get('error_type','')} - {f.get('url','')[:60]}")
                print(f"    {f.get('description','')}")
                print()
        bot.shutdown()
        return

    # Modo principal: auditoria
    if not args.targets and not args.import_zip and not config.get("targets"):
        print(
            "ERRO: Informe URLs via --targets, --import-zip ou configure 'targets' no config.json",
            file=sys.stderr
        )
        print("\nExemplo de uso:")
        print("  python main.py --targets https://www.exemplo.com.br")
        print("  python main.py --import-zip imports/meus_targets.zip")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("  WebAuditBot SES - Sistema de Auditoria Web")
    print(f"{'='*60}\n")

    bot = WebAuditBot(config, error_rules)
    bot.initialize()

    try:
        summary = bot.run(
            targets=args.targets,
            import_zip=args.import_zip
        )
    finally:
        bot.shutdown()

    # Exibe resumo
    print(f"\n{'='*60}")
    print("  RESUMO DA AUDITORIA")
    print(f"{'='*60}")
    print(f"  Sessão:          {summary.get('session_id')}")
    print(f"  Páginas:         {summary.get('pages_analyzed', 0)}")
    print(f"  Total falhas:    {summary.get('total_failures', 0)}")
    print(f"    CRITICAL:      {summary.get('failures_by_severity', {}).get('CRITICAL', 0)}")
    print(f"    HIGH:          {summary.get('failures_by_severity', {}).get('HIGH', 0)}")
    print(f"    MEDIUM:        {summary.get('failures_by_severity', {}).get('MEDIUM', 0)}")
    print(f"    LOW:           {summary.get('failures_by_severity', {}).get('LOW', 0)}")
    print(f"  Tempo médio:     {summary.get('avg_response_time_ms', 0):.0f}ms")
    print(f"  Oracle:          {'Conectado' if summary.get('oracle_connected') else 'Desabilitado'}")
    if summary.get("zip_export"):
        print(f"  Exportado para: {summary['zip_export']}")
    print(f"{'='*60}\n")


class _DummyLogger:
    """Logger mínimo para operações sem sessão ativa."""
    def info(self, msg, **kw): print(f"[INFO] {msg}")
    def warning(self, msg, **kw): print(f"[WARN] {msg}")
    def error(self, msg, **kw): print(f"[ERROR] {msg}", file=sys.stderr)
    def critical(self, msg, **kw): print(f"[CRITICAL] {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
