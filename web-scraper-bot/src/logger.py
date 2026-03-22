"""
Sistema de Logging e Auditoria
Gera logs estruturados de falhas, auditorias e eventos do sistema.
"""

import json
import logging
import logging.handlers
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any


class AuditLogger:
    """Logger principal para auditoria e registro de falhas."""

    def __init__(self, config: Dict[str, Any], session_id: str):
        self.config = config
        self.session_id = session_id
        self.log_dir = Path(config.get("log_dir", "logs"))
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._setup_loggers()
        self._audit_records = []
        self._failure_records = []

    def _setup_loggers(self):
        log_cfg = self.config
        level_str = log_cfg.get("level", "INFO")
        level = getattr(logging, level_str.upper(), logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Logger principal
        self.logger = logging.getLogger(f"WebAuditBot.{self.session_id}")
        self.logger.setLevel(level)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        self.logger.addHandler(console_handler)

        # File handler principal
        max_bytes = log_cfg.get("max_log_size_mb", 10) * 1024 * 1024
        backup_count = log_cfg.get("backup_count", 5)

        main_log_file = self.log_dir / f"audit_{self.session_id}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            main_log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Logger de falhas separado
        self.failure_logger = logging.getLogger(f"WebAuditBot.Failures.{self.session_id}")
        self.failure_logger.setLevel(logging.WARNING)

        failure_log_file = self.log_dir / f"failures_{self.session_id}.log"
        failure_handler = logging.handlers.RotatingFileHandler(
            failure_log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        failure_handler.setFormatter(formatter)
        self.failure_logger.addHandler(failure_handler)

    def info(self, message: str, extra: Optional[Dict] = None):
        self.logger.info(message)
        self._add_audit_record("INFO", message, extra)

    def warning(self, message: str, extra: Optional[Dict] = None):
        self.logger.warning(message)
        self._add_audit_record("WARNING", message, extra)

    def error(self, message: str, extra: Optional[Dict] = None, exc_info: bool = False):
        self.logger.error(message, exc_info=exc_info)
        stack_trace = traceback.format_exc() if exc_info else None
        self._add_audit_record("ERROR", message, extra, stack_trace=stack_trace)

    def critical(self, message: str, extra: Optional[Dict] = None):
        self.logger.critical(message)
        self._add_audit_record("CRITICAL", message, extra)

    def log_failure(
        self,
        url: str,
        error_type: str,
        error_code: Optional[str],
        description: str,
        suggestion: str,
        severity: str,
        category: str,
        page_title: Optional[str] = None,
        element: Optional[str] = None,
        extra: Optional[Dict] = None
    ):
        """Registra uma falha detectada durante a auditoria."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "url": url,
            "error_type": error_type,
            "error_code": error_code,
            "description": description,
            "suggestion": suggestion,
            "severity": severity,
            "category": category,
            "page_title": page_title,
            "element": element,
            "extra": extra or {}
        }
        self._failure_records.append(record)
        self.failure_logger.warning(
            f"[{severity}][{category}] {error_type} em {url}: {description}"
        )
        # Persiste imediatamente em JSON
        self._append_json_log(
            self.log_dir / f"failures_{self.session_id}.jsonl", record
        )

    def log_page_audit(
        self,
        url: str,
        status_code: int,
        response_time_ms: float,
        html_size_bytes: int,
        errors_found: int,
        warnings_found: int,
        page_title: Optional[str] = None
    ):
        """Registra auditoria de uma página."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": "PAGE_AUDIT",
            "url": url,
            "status_code": status_code,
            "response_time_ms": round(response_time_ms, 2),
            "html_size_bytes": html_size_bytes,
            "html_size_kb": round(html_size_bytes / 1024, 2),
            "errors_found": errors_found,
            "warnings_found": warnings_found,
            "page_title": page_title
        }
        self._audit_records.append(record)
        self._append_json_log(
            self.log_dir / f"audit_{self.session_id}.jsonl", record
        )
        self.logger.info(
            f"AUDITADO: {url} | Status: {status_code} | "
            f"Tempo: {response_time_ms:.0f}ms | "
            f"Erros: {errors_found} | Alertas: {warnings_found}"
        )

    def log_session_start(self, targets: list):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": "SESSION_START",
            "targets": targets
        }
        self._audit_records.append(record)
        self._append_json_log(
            self.log_dir / f"audit_{self.session_id}.jsonl", record
        )
        self.logger.info(f"Sessão {self.session_id} iniciada | Alvos: {len(targets)}")

    def log_session_end(self, summary: Dict):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": "SESSION_END",
            "summary": summary
        }
        self._audit_records.append(record)
        self._append_json_log(
            self.log_dir / f"audit_{self.session_id}.jsonl", record
        )
        self.logger.info(
            f"Sessão {self.session_id} finalizada | "
            f"Páginas: {summary.get('pages_analyzed', 0)} | "
            f"Erros: {summary.get('total_errors', 0)} | "
            f"Alertas: {summary.get('total_warnings', 0)}"
        )

    def _add_audit_record(
        self,
        level: str,
        message: str,
        extra: Optional[Dict],
        stack_trace: Optional[str] = None
    ):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "level": level,
            "message": message,
            "extra": extra or {}
        }
        if stack_trace and self.config.get("include_stack_traces", True):
            record["stack_trace"] = stack_trace
        self._audit_records.append(record)

    def _append_json_log(self, filepath: Path, record: Dict):
        """Appends a JSON record to a JSONL file (one JSON object per line)."""
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.error(f"Erro ao escrever log JSON: {e}")

    def get_failure_records(self) -> list:
        return self._failure_records.copy()

    def get_audit_records(self) -> list:
        return self._audit_records.copy()

    def get_summary(self) -> Dict:
        severities = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        categories = {}
        for rec in self._failure_records:
            sev = rec.get("severity", "LOW")
            severities[sev] = severities.get(sev, 0) + 1
            cat = rec.get("category", "OTHER")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "session_id": self.session_id,
            "total_failures": len(self._failure_records),
            "by_severity": severities,
            "by_category": categories
        }
