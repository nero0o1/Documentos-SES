"""
Handler de ZIP
Importa configurações/listas de URLs de ZIPs e exporta
relatórios, logs e snapshots HTML em pacotes ZIP.
"""

import csv
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


class ZipExporter:
    """Cria pacotes ZIP com relatórios de auditoria."""

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        self.export_dir = Path(config.get("output_dir", "exports"))
        self.report_dir = Path(config.get("report_dir", "reports"))
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.compression = zipfile.ZIP_DEFLATED
        self.compress_level = config.get("zip_compression_level", 6)

    def export_session(
        self,
        session_id: str,
        pages: List[Dict],
        failures: List[Dict],
        audit_records: List[Dict],
        html_snapshots: Optional[Dict[str, str]] = None,
        summary: Optional[Dict] = None
    ) -> Path:
        """
        Exporta todos os dados de uma sessão de auditoria em um arquivo ZIP.
        Inclui: relatórios JSON/HTML/CSV, logs, snapshots HTML.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        zip_filename = f"auditoria_{session_id}_{timestamp}.zip"
        zip_path = self.export_dir / zip_filename

        self.logger.info(f"Exportando sessão {session_id} para {zip_path}")

        with zipfile.ZipFile(
            zip_path, "w",
            compression=self.compression,
            compresslevel=self.compress_level
        ) as zf:
            # Manifesto da exportação
            manifest = {
                "session_id": session_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "contents": [],
                "summary": summary or {}
            }

            # 1. Relatório JSON completo
            report_json = self._build_json_report(session_id, pages, failures, summary)
            json_bytes = json.dumps(report_json, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr(f"reports/relatorio_{session_id}.json", json_bytes)
            manifest["contents"].append("reports/relatorio_<session_id>.json")

            # 2. Relatório HTML
            html_report = self._build_html_report(session_id, pages, failures, summary)
            zf.writestr(f"reports/relatorio_{session_id}.html", html_report.encode("utf-8"))
            manifest["contents"].append("reports/relatorio_<session_id>.html")

            # 3. CSV de falhas
            csv_bytes = self._build_failures_csv(failures)
            zf.writestr(f"reports/falhas_{session_id}.csv", csv_bytes)
            manifest["contents"].append("reports/falhas_<session_id>.csv")

            # 4. CSV de páginas auditadas
            pages_csv = self._build_pages_csv(pages)
            zf.writestr(f"reports/paginas_{session_id}.csv", pages_csv)
            manifest["contents"].append("reports/paginas_<session_id>.csv")

            # 5. Logs de auditoria JSONL
            if audit_records:
                audit_lines = "\n".join(
                    json.dumps(r, ensure_ascii=False) for r in audit_records
                )
                zf.writestr(f"logs/audit_{session_id}.jsonl", audit_lines.encode("utf-8"))
                manifest["contents"].append("logs/audit_<session_id>.jsonl")

            # 6. Snapshots HTML
            if html_snapshots and self.config.get("include_html_snapshots", True):
                for url_hash, html_content in html_snapshots.items():
                    snap_path = f"snapshots/{url_hash}.html"
                    zf.writestr(snap_path, html_content.encode("utf-8", errors="replace"))
                manifest["contents"].append(f"snapshots/ ({len(html_snapshots)} arquivos)")

            # 7. Manifesto
            zf.writestr(
                "MANIFESTO.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            )

            # 8. README da exportação
            readme = self._build_readme(session_id, summary)
            zf.writestr("LEIA-ME.txt", readme.encode("utf-8"))

        size_kb = zip_path.stat().st_size // 1024
        self.logger.info(f"ZIP exportado: {zip_path} ({size_kb}KB)")
        return zip_path

    def _build_json_report(
        self,
        session_id: str,
        pages: List[Dict],
        failures: List[Dict],
        summary: Optional[Dict]
    ) -> Dict:
        """Monta o relatório JSON completo."""
        by_severity = {}
        by_category = {}
        for f in failures:
            sev = f.get("severity", "UNKNOWN")
            cat = f.get("category", "UNKNOWN")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "meta": {
                "session_id": session_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generator": "WebAuditBot SES v1.0"
            },
            "summary": summary or {},
            "statistics": {
                "total_pages": len(pages),
                "total_failures": len(failures),
                "failures_by_severity": by_severity,
                "failures_by_category": by_category,
                "pages_with_errors": sum(1 for p in pages if p.get("errors_found", 0) > 0)
            },
            "pages": pages,
            "failures": failures
        }

    def _build_html_report(
        self,
        session_id: str,
        pages: List[Dict],
        failures: List[Dict],
        summary: Optional[Dict]
    ) -> str:
        """Gera relatório HTML formatado com tabelas e estatísticas."""
        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
        total_pages = len(pages)
        total_failures = len(failures)

        # Contagem por severidade
        critical = sum(1 for f in failures if f.get("severity") == "CRITICAL")
        high = sum(1 for f in failures if f.get("severity") == "HIGH")
        medium = sum(1 for f in failures if f.get("severity") == "MEDIUM")
        low = sum(1 for f in failures if f.get("severity") == "LOW")

        severity_color = {
            "CRITICAL": "#dc3545", "HIGH": "#fd7e14",
            "MEDIUM": "#ffc107", "LOW": "#28a745"
        }

        # Gera linhas da tabela de falhas
        failure_rows = ""
        for f in failures:
            sev = f.get("severity", "LOW")
            color = severity_color.get(sev, "#6c757d")
            failure_rows += f"""
            <tr>
                <td><span style="color:{color};font-weight:bold">{sev}</span></td>
                <td>{f.get('category','')}</td>
                <td>{f.get('error_type','')}</td>
                <td style="max-width:400px;word-break:break-all">{f.get('url','')[:100]}</td>
                <td>{f.get('description','')}</td>
                <td style="color:#0066cc">{f.get('suggestion','')}</td>
            </tr>"""

        # Gera linhas da tabela de páginas
        page_rows = ""
        for p in pages:
            status = p.get("status_code", 0)
            status_class = "color:#28a745" if 200 <= status < 300 else "color:#dc3545"
            page_rows += f"""
            <tr>
                <td style="max-width:300px;word-break:break-all">{p.get('url','')[:80]}</td>
                <td style="{status_class}">{status}</td>
                <td>{p.get('response_time_ms',0):.0f}ms</td>
                <td>{p.get('html_size_kb',0):.1f}KB</td>
                <td>{p.get('errors_found',0)}</td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Relatório de Auditoria Web - {session_id}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f8f9fa; color: #333; line-height: 1.5; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
  header {{ background: #003366; color: white; padding: 20px 30px; border-radius: 8px;
            margin-bottom: 20px; }}
  header h1 {{ font-size: 24px; }}
  header p {{ opacity: 0.8; font-size: 14px; margin-top: 5px; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px; margin-bottom: 20px; }}
  .stat-card {{ background: white; border-radius: 8px; padding: 15px; text-align: center;
               box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .stat-card .number {{ font-size: 36px; font-weight: bold; }}
  .stat-card .label {{ font-size: 13px; color: #666; margin-top: 5px; }}
  .critical {{ color: #dc3545; }}
  .high {{ color: #fd7e14; }}
  .medium {{ color: #ffc107; }}
  .low {{ color: #28a745; }}
  .section {{ background: white; border-radius: 8px; padding: 20px;
              margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .section h2 {{ font-size: 18px; border-bottom: 2px solid #003366;
                padding-bottom: 10px; margin-bottom: 15px; color: #003366; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #003366; color: white; padding: 10px 8px; text-align: left; }}
  td {{ padding: 8px; border-bottom: 1px solid #eee; vertical-align: top; }}
  tr:hover {{ background: #f8f9fa; }}
  footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 20px; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Relatório de Auditoria Web - SES</h1>
    <p>Sessão: {session_id} | Gerado em: {now}</p>
  </header>

  <div class="stats">
    <div class="stat-card">
      <div class="number">{total_pages}</div>
      <div class="label">Páginas Analisadas</div>
    </div>
    <div class="stat-card">
      <div class="number">{total_failures}</div>
      <div class="label">Total de Falhas</div>
    </div>
    <div class="stat-card">
      <div class="number critical">{critical}</div>
      <div class="label">Críticas</div>
    </div>
    <div class="stat-card">
      <div class="number high">{high}</div>
      <div class="label">Altas</div>
    </div>
    <div class="stat-card">
      <div class="number medium">{medium}</div>
      <div class="label">Médias</div>
    </div>
    <div class="stat-card">
      <div class="number low">{low}</div>
      <div class="label">Baixas</div>
    </div>
  </div>

  <div class="section">
    <h2>Falhas Detectadas ({total_failures})</h2>
    <table>
      <thead>
        <tr>
          <th>Severidade</th><th>Categoria</th><th>Tipo</th>
          <th>URL</th><th>Descrição</th><th>Sugestão de Correção</th>
        </tr>
      </thead>
      <tbody>{failure_rows}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Páginas Auditadas ({total_pages})</h2>
    <table>
      <thead>
        <tr>
          <th>URL</th><th>Status</th><th>Tempo</th>
          <th>Tamanho</th><th>Erros</th>
        </tr>
      </thead>
      <tbody>{page_rows}</tbody>
    </table>
  </div>

  <footer>
    <p>WebAuditBot SES v1.0 | Sistema de Auditoria de Saúde Digital</p>
  </footer>
</div>
</body>
</html>"""

    def _build_failures_csv(self, failures: List[Dict]) -> bytes:
        """Gera CSV das falhas."""
        output = io.StringIO()
        fieldnames = [
            "severidade", "categoria", "tipo_erro", "codigo_erro",
            "url", "titulo_pagina", "descricao", "sugestao", "elemento"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for f in failures:
            writer.writerow({
                "severidade": f.get("severity", ""),
                "categoria": f.get("category", ""),
                "tipo_erro": f.get("error_type", ""),
                "codigo_erro": f.get("error_code", ""),
                "url": f.get("url", ""),
                "titulo_pagina": f.get("page_title", ""),
                "descricao": f.get("description", ""),
                "sugestao": f.get("suggestion", ""),
                "elemento": f.get("element", "")
            })
        return output.getvalue().encode("utf-8-sig")  # utf-8-sig para Excel PT-BR

    def _build_pages_csv(self, pages: List[Dict]) -> bytes:
        """Gera CSV das páginas auditadas."""
        output = io.StringIO()
        fieldnames = [
            "url", "status_http", "tempo_ms", "tamanho_kb",
            "titulo", "erros", "alertas", "auditado_em"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in pages:
            writer.writerow({
                "url": p.get("url", ""),
                "status_http": p.get("status_code", ""),
                "tempo_ms": p.get("response_time_ms", ""),
                "tamanho_kb": p.get("html_size_kb", ""),
                "titulo": p.get("page_title", ""),
                "erros": p.get("errors_found", 0),
                "alertas": p.get("warnings_found", 0),
                "auditado_em": p.get("timestamp", "")
            })
        return output.getvalue().encode("utf-8-sig")

    def _build_readme(self, session_id: str, summary: Optional[Dict]) -> str:
        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")
        return f"""RELATÓRIO DE AUDITORIA WEB - SES
=================================
Sessão: {session_id}
Gerado em: {now}
Ferramenta: WebAuditBot SES v1.0

CONTEÚDO DO PACOTE:
-------------------
  reports/  - Relatórios em JSON, HTML e CSV
  logs/     - Logs de auditoria em formato JSONL
  snapshots/- Snapshots do HTML das páginas (se habilitado)
  MANIFESTO.json - Índice desta exportação

COMO USAR:
----------
  - Abra reports/relatorio_<id>.html em um navegador para visualização completa
  - Use reports/falhas_<id>.csv no Excel para filtragem e análise
  - Importe reports/relatorio_<id>.json em ferramentas de BI/análise
  - Logs JSONL podem ser processados com ferramentas como jq ou Elasticsearch

SEVERIDADES:
-----------
  CRITICAL - Problemas graves que impedem funcionamento
  HIGH     - Problemas sérios que afetam segurança/funcionalidade
  MEDIUM   - Problemas que degradam a experiência
  LOW      - Melhorias recomendadas

Sistema de Auditoria Digital - SES
"""


class ZipImporter:
    """Importa configurações e listas de URLs de arquivos ZIP."""

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        self.import_dir = Path(config.get("import_dir", "imports"))
        self.import_dir.mkdir(parents=True, exist_ok=True)

    def import_targets_from_zip(self, zip_path: str) -> List[str]:
        """
        Importa lista de URLs alvo de um ZIP.
        O ZIP pode conter:
          - targets.json  (lista de URLs ou objetos com 'url')
          - targets.txt   (uma URL por linha)
          - targets.csv   (coluna 'url')
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            self.logger.error(f"ZIP não encontrado: {zip_path}")
            return []

        urls = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                self.logger.info(f"Importando ZIP: {zip_path} | Arquivos: {names}")

                # targets.json
                json_files = [n for n in names if n.endswith("targets.json")]
                for jf in json_files:
                    with zf.open(jf) as f:
                        data = json.loads(f.read().decode("utf-8"))
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, str):
                                    if item.startswith(("http://", "https://")):
                                        urls.append(item)
                                elif isinstance(item, dict):
                                    url = item.get("url") or item.get("URL") or item.get("href")
                                    if url and url.startswith(("http://", "https://")):
                                        urls.append(url)
                        elif isinstance(data, dict):
                            targets = data.get("targets") or data.get("urls") or []
                            for t in targets:
                                u = t if isinstance(t, str) else t.get("url", "")
                                if u and u.startswith(("http://", "https://")):
                                    urls.append(u)

                # targets.txt
                txt_files = [n for n in names if n.endswith(".txt") and "target" in n.lower()]
                for tf in txt_files:
                    with zf.open(tf) as f:
                        for line in f.read().decode("utf-8").splitlines():
                            line = line.strip()
                            if line and line.startswith(("http://", "https://")):
                                urls.append(line)

                # targets.csv
                csv_files = [n for n in names if n.endswith(".csv") and "target" in n.lower()]
                for cf in csv_files:
                    with zf.open(cf) as f:
                        content = f.read().decode("utf-8-sig")
                        reader = csv.DictReader(io.StringIO(content))
                        for row in reader:
                            url = row.get("url") or row.get("URL") or row.get("href") or ""
                            if url.startswith(("http://", "https://")):
                                urls.append(url)

        except zipfile.BadZipFile:
            self.logger.error(f"Arquivo ZIP inválido: {zip_path}")
        except Exception as e:
            self.logger.error(f"Erro ao importar ZIP: {e}", exc_info=True)

        # Deduplica preservando ordem
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        self.logger.info(f"Importadas {len(unique_urls)} URLs únicas do ZIP.")
        return unique_urls

    def import_config_from_zip(self, zip_path: str) -> Optional[Dict]:
        """
        Importa configuração de um ZIP.
        Procura por config.json dentro do ZIP.
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            self.logger.error(f"ZIP não encontrado: {zip_path}")
            return None

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                config_files = [n for n in zf.namelist() if n.endswith("config.json")]
                if not config_files:
                    self.logger.warning("Nenhum config.json encontrado no ZIP.")
                    return None
                with zf.open(config_files[0]) as f:
                    config = json.loads(f.read().decode("utf-8"))
                    self.logger.info(f"Configuração importada do ZIP: {config_files[0]}")
                    return config
        except Exception as e:
            self.logger.error(f"Erro ao importar config do ZIP: {e}")
            return None

    def list_available_imports(self) -> List[Dict]:
        """Lista ZIPs disponíveis na pasta de importação."""
        zips = []
        for zip_file in self.import_dir.glob("*.zip"):
            stat = zip_file.stat()
            zips.append({
                "filename": zip_file.name,
                "path": str(zip_file),
                "size_kb": stat.st_size // 1024,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        return sorted(zips, key=lambda x: x["modified"], reverse=True)
