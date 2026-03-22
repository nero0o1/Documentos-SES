"""
Suite de Testes: Erros de Interface e Instabilidade do Sistema
Verifica se o bot detecta corretamente falhas de UI, HTTP e comportamento instável.
"""

import sys
import time
import unittest
from pathlib import Path

# Ajusta path para importar src/
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import json
from src.analyzer import HTMLAnalyzer
from src.scraper import WebScraper, PageResult
from src.logger import AuditLogger
from tests.test_server import TestServer


def _make_logger(session_id="TEST"):
    cfg = {
        "level": "WARNING",
        "log_dir": str(ROOT / "tests" / "results"),
        "audit_log_enabled": True,
        "failure_log_enabled": True,
        "log_rotation": False,
        "max_log_size_mb": 5,
        "backup_count": 1,
        "include_stack_traces": True,
    }
    Path(cfg["log_dir"]).mkdir(parents=True, exist_ok=True)
    return AuditLogger(cfg, session_id)


def _make_analyzer(logger):
    rules_path = ROOT / "config" / "error_rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    config = {
        "check_broken_links": True,
        "check_missing_alt": True,
        "check_empty_forms": True,
        "check_http_errors": True,
        "check_slow_pages": True,
        "slow_page_threshold_ms": 3000,
        "check_missing_meta": True,
        "check_accessibility": True,
        "check_security_headers": True,
        "check_mixed_content": True,
        "check_large_resources": True,
        "large_resource_threshold_kb": 500,
    }
    return HTMLAnalyzer(config, rules, logger)


def _make_scraper(logger):
    cfg = {
        "timeout": 10,
        "max_retries": 2,
        "retry_delay": 0,
        "verify_ssl": False,
        "follow_redirects": True,
        "delay_between_requests": 0,
    }
    return WebScraper(cfg, logger)


# ─── Servidor compartilhado ───────────────────────────────────────────────────

SERVER = TestServer(port=18080)


def setUpModule():
    SERVER.start()
    time.sleep(0.2)


def tearDownModule():
    SERVER.stop()


# ─── Testes de Interface ──────────────────────────────────────────────────────

class TestInterfaceErrors(unittest.TestCase):
    """Verifica detecção de erros de interface HTML e semântica."""

    def setUp(self):
        self.logger = _make_logger("IF-" + self._testMethodName[:10])
        self.analyzer = _make_analyzer(self.logger)
        self.scraper = _make_scraper(self.logger)
        self.base = SERVER.base_url()

    # ── T01 ──────────────────────────────────────────────────────────────────
    def test_T01_pagina_valida_sem_erros(self):
        """Página completa e correta não deve gerar erros críticos/altos."""
        result = self.scraper.fetch_page(f"{self.base}/ok")
        errors = self.analyzer.analyze_page(result)

        criticos_altos = [e for e in errors if e.severity in ("CRITICAL", "HIGH")]
        self.assertEqual(result.status_code, 200, "Status esperado: 200")
        self.assertEqual(
            criticos_altos, [],
            f"Página OK não deveria ter erros CRITICAL/HIGH. Encontrados: "
            f"{[e.error_type for e in criticos_altos]}"
        )

    # ── T02 ──────────────────────────────────────────────────────────────────
    def test_T02_detecta_titulo_ausente(self):
        """Deve detectar MISSING_TITLE em página sem <title>."""
        result = self.scraper.fetch_page(f"{self.base}/sem-title")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        self.assertIn("MISSING_TITLE", tipos, "Deve detectar título ausente")

    # ── T03 ──────────────────────────────────────────────────────────────────
    def test_T03_detecta_imagens_sem_alt(self):
        """Deve detectar imagens sem atributo alt."""
        result = self.scraper.fetch_page(f"{self.base}/sem-alt")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        self.assertIn("MISSING_ALT_TEXT", tipos, "Deve detectar imagens sem alt")

        alt_error = next(e for e in errors if e.error_type == "MISSING_ALT_TEXT")
        self.assertIn("3", alt_error.description, "Deve contar 3 imagens sem alt")

    # ── T04 ──────────────────────────────────────────────────────────────────
    def test_T04_detecta_csrf_ausente(self):
        """Deve detectar formulários POST sem token CSRF."""
        result = self.scraper.fetch_page(f"{self.base}/sem-csrf")
        errors = self.analyzer.analyze_page(result)
        csrf_errors = [e for e in errors if e.error_type == "MISSING_CSRF_TOKEN"]
        self.assertGreaterEqual(
            len(csrf_errors), 2,
            "Deve detectar CSRF ausente nos 2 formulários POST"
        )
        # Valida que sugestão de correção está presente
        for e in csrf_errors:
            self.assertTrue(len(e.suggestion) > 10, "Sugestão de correção deve ser descritiva")

    # ── T05 ──────────────────────────────────────────────────────────────────
    def test_T05_detecta_conteudo_misto(self):
        """Deve detectar recursos HTTP em página que simula HTTPS."""
        # Injeta URL como HTTPS para forçar verificação de mixed content
        result = self.scraper.fetch_page(f"{self.base}/mixed-content")
        result.url = "https://exemplo.com/mixed-content"  # Simula HTTPS
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        self.assertIn("MIXED_CONTENT", tipos, "Deve detectar conteúdo misto HTTP/HTTPS")

    # ── T06 ──────────────────────────────────────────────────────────────────
    def test_T06_detecta_tags_depreciadas(self):
        """Deve detectar uso de tags HTML depreciadas."""
        result = self.scraper.fetch_page(f"{self.base}/depreciado")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        self.assertIn("DEPRECATED_HTML_TAGS", tipos, "Deve detectar tags depreciadas")

        depr_error = next(e for e in errors if e.error_type == "DEPRECATED_HTML_TAGS")
        tags = depr_error.extra.get("deprecated_tags", {})
        self.assertIn("font", tags)
        self.assertIn("marquee", tags)

    # ── T07 ──────────────────────────────────────────────────────────────────
    def test_T07_detecta_ausencia_headers_seguranca(self):
        """Deve detectar ausência de X-Frame-Options, CSP, X-Content-Type-Options."""
        result = self.scraper.fetch_page(f"{self.base}/sem-headers")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        self.assertIn(
            "MISSING_SECURITY_HEADER", tipos,
            "Deve detectar headers de segurança ausentes"
        )
        missing_headers = [
            e.extra.get("missing_header")
            for e in errors
            if e.error_type == "MISSING_SECURITY_HEADER"
        ]
        self.assertIn("x-frame-options", missing_headers)
        self.assertIn("content-security-policy", missing_headers)

    # ── T08 ──────────────────────────────────────────────────────────────────
    def test_T08_body_vazio_nao_quebra(self):
        """Body vazio não deve lançar exceção; apenas detectar meta ausentes."""
        result = self.scraper.fetch_page(f"{self.base}/vazio")
        try:
            errors = self.analyzer.analyze_page(result)
        except Exception as ex:
            self.fail(f"Analisador quebrou com body vazio: {ex}")
        # Página vazia ainda pode ter problemas de meta, title, etc.
        self.assertIsInstance(errors, list)

    # ── T09 ──────────────────────────────────────────────────────────────────
    def test_T09_html_corrompido_nao_quebra(self):
        """HTML malformado não deve lançar exceção no analisador."""
        result = self.scraper.fetch_page(f"{self.base}/html-corrompido")
        try:
            errors = self.analyzer.analyze_page(result)
        except Exception as ex:
            self.fail(f"Analisador quebrou com HTML corrompido: {ex}")
        self.assertIsInstance(errors, list)

    # ── T10 ──────────────────────────────────────────────────────────────────
    def test_T10_sugestao_presente_em_todos_erros(self):
        """Todos os erros detectados devem ter sugestão de correção não vazia."""
        routes = ["/sem-title", "/sem-alt", "/sem-csrf", "/depreciado"]
        for route in routes:
            result = self.scraper.fetch_page(f"{self.base}{route}")
            errors = self.analyzer.analyze_page(result)
            for e in errors:
                self.assertTrue(
                    e.suggestion and len(e.suggestion) > 5,
                    f"Erro {e.error_type} em {route} sem sugestão de correção"
                )


# ─── Testes de Instabilidade ──────────────────────────────────────────────────

class TestSystemInstability(unittest.TestCase):
    """Verifica comportamento do bot diante de instabilidade e erros HTTP."""

    def setUp(self):
        self.logger = _make_logger("INST-" + self._testMethodName[:10])
        self.analyzer = _make_analyzer(self.logger)
        self.scraper = _make_scraper(self.logger)
        self.base = SERVER.base_url()

    # ── T11 ──────────────────────────────────────────────────────────────────
    def test_T11_detecta_erro_500(self):
        """Erro 500 deve ser detectado e mapeado como CRITICAL."""
        result = self.scraper.fetch_page(f"{self.base}/erro-500")
        errors = self.analyzer.analyze_page(result)
        http_errors = [e for e in errors if "HTTP_500" in e.error_type]
        self.assertTrue(len(http_errors) > 0, "Deve detectar HTTP 500")
        self.assertEqual(http_errors[0].severity, "CRITICAL")
        self.assertIn("servidor", http_errors[0].suggestion.lower())

    # ── T12 ──────────────────────────────────────────────────────────────────
    def test_T12_detecta_erro_404(self):
        """Erro 404 deve ser detectado com severidade MEDIUM."""
        result = self.scraper.fetch_page(f"{self.base}/erro-404")
        errors = self.analyzer.analyze_page(result)
        http_errors = [e for e in errors if "HTTP_404" in e.error_type]
        self.assertTrue(len(http_errors) > 0, "Deve detectar HTTP 404")
        self.assertEqual(http_errors[0].severity, "MEDIUM")

    # ── T13 ──────────────────────────────────────────────────────────────────
    def test_T13_detecta_erro_403(self):
        """Erro 403 deve ser detectado com severidade HIGH."""
        result = self.scraper.fetch_page(f"{self.base}/erro-403")
        errors = self.analyzer.analyze_page(result)
        http_errors = [e for e in errors if "HTTP_403" in e.error_type]
        self.assertTrue(len(http_errors) > 0, "Deve detectar HTTP 403")
        self.assertEqual(http_errors[0].severity, "HIGH")

    # ── T14 ──────────────────────────────────────────────────────────────────
    def test_T14_detecta_erro_503(self):
        """Erro 503 deve ser detectado como CRITICAL."""
        result = self.scraper.fetch_page(f"{self.base}/erro-503")
        errors = self.analyzer.analyze_page(result)
        http_errors = [e for e in errors if "HTTP_503" in e.error_type]
        self.assertTrue(len(http_errors) > 0, "Deve detectar HTTP 503")
        self.assertEqual(http_errors[0].severity, "CRITICAL")

    # ── T15 ──────────────────────────────────────────────────────────────────
    def test_T15_detecta_pagina_lenta(self):
        """Página com resposta > 3000ms deve gerar alerta de performance."""
        result = self.scraper.fetch_page(f"{self.base}/lento")
        errors = self.analyzer.analyze_page(result)
        perf_errors = [e for e in errors if e.error_type == "SLOW_RESPONSE"]
        self.assertTrue(len(perf_errors) > 0, "Deve detectar página lenta (4s > 3s limite)")
        self.assertGreater(
            result.response_time_ms, 3000,
            f"Tempo esperado > 3000ms, obtido: {result.response_time_ms:.0f}ms"
        )

    # ── T16 ──────────────────────────────────────────────────────────────────
    def test_T16_servidor_inexistente_retorna_erro(self):
        """Requisição a servidor que não existe deve retornar status 0 e erro."""
        result = self.scraper.fetch_page("http://127.0.0.1:19999/inexistente")
        self.assertEqual(result.status_code, 0, "Status deve ser 0 para falha de conexão")
        self.assertIsNotNone(result.error, "Campo error deve ser preenchido")
        errors = self.analyzer.analyze_page(result)
        conn_errors = [e for e in errors if e.error_type == "CONNECTION_FAILED"]
        self.assertTrue(len(conn_errors) > 0, "Deve registrar CONNECTION_FAILED")
        self.assertEqual(conn_errors[0].severity, "CRITICAL")

    # ── T17 ──────────────────────────────────────────────────────────────────
    def test_T17_instabilidade_alternada(self):
        """Rota instável: múltiplas requisições devem ter mix de 200 e 503."""
        status_codes = []
        for _ in range(6):
            result = self.scraper.fetch_page(f"{self.base}/instavel")
            status_codes.append(result.status_code)

        has_ok = any(s == 200 for s in status_codes)
        has_error = any(s == 503 for s in status_codes)
        self.assertTrue(has_ok, f"Deve ter pelo menos um 200. Obtidos: {status_codes}")
        self.assertTrue(has_error, f"Deve ter pelo menos um 503. Obtidos: {status_codes}")

    # ── T18 ──────────────────────────────────────────────────────────────────
    def test_T18_contagem_erros_por_severidade(self):
        """Resumo do logger deve contabilizar corretamente por severidade."""
        routes_and_pages = [
            f"{self.base}/erro-500",  # CRITICAL
            f"{self.base}/erro-403",  # HIGH
            f"{self.base}/sem-title", # LOW
        ]
        for url in routes_and_pages:
            result = self.scraper.fetch_page(url)
            errors = self.analyzer.analyze_page(result)
            for e in errors:
                self.logger.log_failure(
                    url=e.url, error_type=e.error_type, error_code=e.error_code,
                    description=e.description, suggestion=e.suggestion,
                    severity=e.severity, category=e.category
                )

        summary = self.logger.get_summary()
        self.assertGreater(summary["by_severity"].get("CRITICAL", 0), 0)
        self.assertGreater(summary["by_severity"].get("HIGH", 0), 0)
        self.assertGreater(summary["total_failures"], 0)

    # ── T19 ──────────────────────────────────────────────────────────────────
    def test_T19_resultado_tem_timestamp(self):
        """PageResult deve sempre ter timestamp preenchido."""
        result = self.scraper.fetch_page(f"{self.base}/ok")
        self.assertTrue(
            result.timestamp and len(result.timestamp) > 10,
            "PageResult deve ter timestamp ISO"
        )

    # ── T20 ──────────────────────────────────────────────────────────────────
    def test_T20_crawl_respeita_max_pages(self):
        """Crawling com max_pages=2 não deve visitar mais que 2 páginas."""
        results = self.scraper.crawl(
            start_url=f"{self.base}/ok",
            max_depth=5,
            max_pages=2,
            same_domain_only=True
        )
        self.assertLessEqual(len(results), 2, "Crawl deve respeitar max_pages=2")
