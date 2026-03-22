"""
WebAuditBot - Orquestrador principal
Coordena scraping, análise, logging, Oracle e exportação ZIP.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .scraper import WebScraper, PageResult
from .analyzer import HTMLAnalyzer, AnalysisError
from .logger import AuditLogger
from .oracle_connector import OracleConnector
from .zip_handler import ZipExporter, ZipImporter


class WebAuditBot:
    """
    Bot de auditoria web configurável.

    Fluxo de execução:
      1. Carrega configuração
      2. Conecta Oracle (se habilitado)
      3. Inicia sessão de auditoria
      4. Crawla URLs alvo
      5. Analisa cada página (HTML, headers, performance)
      6. Registra falhas e sugestões
      7. Salva no Oracle (se habilitado)
      8. Exporta ZIP com relatórios
    """

    def __init__(self, config: Dict, error_rules: Dict):
        self.config = config
        self.error_rules = error_rules
        self.session_id = self._generate_session_id()

        # Inicializa componentes
        log_cfg = config.get("logging", {})
        log_dir = Path(config.get("export", {}).get("report_dir", "reports")).parent / log_cfg.get("log_dir", "logs")
        log_cfg_with_dir = {**log_cfg, "log_dir": str(log_dir)}

        self.logger = AuditLogger(log_cfg_with_dir, self.session_id)
        self.scraper = WebScraper(config.get("scraper", {}), self.logger)
        self.analyzer = HTMLAnalyzer(
            config.get("analysis", {}), error_rules, self.logger
        )
        self.oracle = OracleConnector(config.get("oracle", {}), self.logger)

        export_cfg = config.get("export", {})
        self.exporter = ZipExporter(export_cfg, self.logger)
        self.importer = ZipImporter(export_cfg, self.logger)

        # Estado da sessão
        self._pages_data: List[Dict] = []
        self._all_failures: List[Dict] = []
        self._html_snapshots: Dict[str, str] = {}

    def _generate_session_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        uid = uuid.uuid4().hex[:8].upper()
        return f"SES-{ts}-{uid}"

    def initialize(self) -> bool:
        """Inicializa conexões e prepara a sessão."""
        self.logger.info(f"Inicializando WebAuditBot | Sessão: {self.session_id}")

        if self.config.get("oracle", {}).get("enabled", False):
            self.oracle.connect()

        return True

    def shutdown(self):
        """Encerra conexões graciosamente."""
        self.oracle.disconnect()
        self.logger.info("WebAuditBot encerrado.")

    def run(
        self,
        targets: Optional[List[str]] = None,
        import_zip: Optional[str] = None
    ) -> Dict:
        """
        Executa auditoria completa.

        Args:
            targets: Lista de URLs para auditar
            import_zip: Caminho de ZIP com targets e/ou configuração

        Returns:
            Dicionário com resumo da sessão e caminho do ZIP exportado
        """
        # Importa targets de ZIP se fornecido
        if import_zip:
            imported_urls = self.importer.import_targets_from_zip(import_zip)
            if imported_urls:
                targets = (targets or []) + imported_urls
                self.logger.info(f"URLs importadas do ZIP: {len(imported_urls)}")

            imported_config = self.importer.import_config_from_zip(import_zip)
            if imported_config:
                self._merge_config(imported_config)

        # Usa targets da config se não fornecidos
        if not targets:
            targets = self.config.get("targets", [])

        if not targets:
            self.logger.error("Nenhuma URL alvo definida. Use --targets ou --import-zip.")
            return {"error": "Nenhum target definido", "session_id": self.session_id}

        # Normaliza targets (aceita strings ou dicts com 'url')
        url_list = []
        for t in targets:
            if isinstance(t, str):
                url_list.append(t)
            elif isinstance(t, dict):
                url = t.get("url") or t.get("href", "")
                if url:
                    url_list.append(url)

        self.logger.log_session_start(url_list)

        if self.oracle.is_connected():
            self.oracle.save_session(self.session_id, url_list)

        # Processa cada URL alvo
        scraper_cfg = self.config.get("scraper", {})
        for target_url in url_list:
            self.logger.info(f"--- Processando alvo: {target_url} ---")
            try:
                self._process_target(
                    target_url,
                    max_depth=scraper_cfg.get("max_depth", 3),
                    max_pages=scraper_cfg.get("max_pages", 100)
                )
            except Exception as e:
                self.logger.error(f"Erro ao processar {target_url}: {e}", exc_info=True)

        # Monta resumo
        summary = self._build_summary()
        self.logger.log_session_end(summary)

        # Salva falhas no Oracle
        if self.oracle.is_connected() and self._all_failures:
            self.oracle.save_failures_batch(self.session_id, self._all_failures)
            self.oracle.update_session(self.session_id, summary)

        # Exporta ZIP
        zip_path = None
        if self.config.get("export", {}).get("auto_export_on_complete", True):
            zip_path = self.exporter.export_session(
                session_id=self.session_id,
                pages=self._pages_data,
                failures=self._all_failures,
                audit_records=self.logger.get_audit_records(),
                html_snapshots=self._html_snapshots,
                summary=summary
            )

        summary["zip_export"] = str(zip_path) if zip_path else None
        summary["session_id"] = self.session_id
        return summary

    def _process_target(self, target_url: str, max_depth: int, max_pages: int):
        """Crawla e analisa todas as páginas de um alvo."""
        results = self.scraper.crawl(
            start_url=target_url,
            max_depth=max_depth,
            max_pages=max_pages
        )

        for page_result in results:
            self._analyze_and_record(page_result)

    def _analyze_and_record(self, page_result: PageResult):
        """Analisa uma página e registra tudo."""
        errors: List[AnalysisError] = self.analyzer.analyze_page(page_result)

        errors_count = sum(1 for e in errors if e.severity in ("CRITICAL", "HIGH"))
        warnings_count = sum(1 for e in errors if e.severity in ("MEDIUM", "LOW"))

        # Registra auditoria da página
        self.logger.log_page_audit(
            url=page_result.url,
            status_code=page_result.status_code,
            response_time_ms=page_result.response_time_ms,
            html_size_bytes=page_result.html_size_bytes,
            errors_found=errors_count,
            warnings_found=warnings_count,
            page_title=page_result.page_title
        )

        page_data = {
            "url": page_result.url,
            "final_url": page_result.final_url,
            "status_code": page_result.status_code,
            "response_time_ms": round(page_result.response_time_ms, 2),
            "html_size_kb": round(page_result.html_size_bytes / 1024, 2),
            "page_title": page_result.page_title,
            "errors_found": errors_count,
            "warnings_found": warnings_count,
            "timestamp": page_result.timestamp
        }
        self._pages_data.append(page_data)

        # Salva snapshot HTML
        include_snapshots = self.config.get("export", {}).get("include_html_snapshots", True)
        if include_snapshots and page_result.html:
            url_hash = hashlib.md5(page_result.url.encode()).hexdigest()[:16]
            self._html_snapshots[url_hash] = page_result.html
            if self.oracle.is_connected():
                self.oracle.save_html_snapshot(
                    self.session_id, page_result.url,
                    page_result.html, page_result.get_hash()
                )

        # Salva página no Oracle
        if self.oracle.is_connected():
            self.oracle.save_page(self.session_id, page_data)

        # Registra cada falha
        for error in errors:
            self.logger.log_failure(
                url=error.url,
                error_type=error.error_type,
                error_code=error.error_code,
                description=error.description,
                suggestion=error.suggestion,
                severity=error.severity,
                category=error.category,
                page_title=error.page_title,
                element=error.element,
                extra=error.extra
            )
            self._all_failures.append(error.to_dict())

    def _build_summary(self) -> Dict:
        """Constrói resumo da sessão."""
        by_severity = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        by_category: Dict[str, int] = {}

        for f in self._all_failures:
            sev = f.get("severity", "LOW")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            cat = f.get("category", "OTHER")
            by_category[cat] = by_category.get(cat, 0) + 1

        total_response = sum(p.get("response_time_ms", 0) for p in self._pages_data)
        avg_response = total_response / len(self._pages_data) if self._pages_data else 0

        return {
            "session_id": self.session_id,
            "pages_analyzed": len(self._pages_data),
            "total_failures": len(self._all_failures),
            "total_errors": by_severity.get("CRITICAL", 0) + by_severity.get("HIGH", 0),
            "total_warnings": by_severity.get("MEDIUM", 0) + by_severity.get("LOW", 0),
            "failures_by_severity": by_severity,
            "failures_by_category": by_category,
            "avg_response_time_ms": round(avg_response, 2),
            "html_snapshots_captured": len(self._html_snapshots),
            "oracle_connected": self.oracle.is_connected()
        }

    def _merge_config(self, new_config: Dict):
        """Mescla configuração importada com a configuração atual."""
        for key, value in new_config.items():
            if isinstance(value, dict) and key in self.config:
                self.config[key].update(value)
            else:
                self.config[key] = value
        self.logger.info("Configuração mesclada do ZIP importado.")

    def get_failures(self) -> List[Dict]:
        return self._all_failures.copy()

    def get_pages(self) -> List[Dict]:
        return self._pages_data.copy()

    def export_now(self) -> Optional[Path]:
        """Força exportação ZIP imediata."""
        return self.exporter.export_session(
            session_id=self.session_id,
            pages=self._pages_data,
            failures=self._all_failures,
            audit_records=self.logger.get_audit_records(),
            html_snapshots=self._html_snapshots,
            summary=self._build_summary()
        )
