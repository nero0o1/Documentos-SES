"""
Suite de Testes: Rejeição de Importação de Arquivos
Verifica como o sistema lida com ZIPs inválidos, corrompidos,
mal formatados, sem targets e com URLs inválidas.
"""

import json
import os
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.zip_handler import ZipImporter, ZipExporter
from src.logger import AuditLogger

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS  = Path(__file__).parent / "results"


def _make_logger(session_id="IMP"):
    cfg = {
        "level": "WARNING",
        "log_dir": str(RESULTS),
        "audit_log_enabled": True,
        "failure_log_enabled": True,
        "log_rotation": False,
        "max_log_size_mb": 5,
        "backup_count": 1,
        "include_stack_traces": True,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    return AuditLogger(cfg, session_id)


def _make_importer(logger):
    cfg = {"import_dir": str(FIXTURES), "output_dir": str(RESULTS)}
    return ZipImporter(cfg, logger)


# ─── Testes de Importação Válida ──────────────────────────────────────────────

class TestImportValid(unittest.TestCase):
    """ZIPs válidos devem importar as URLs corretamente."""

    def setUp(self):
        self.logger = _make_logger("IMP-VALID-" + self._testMethodName[:8])
        self.importer = _make_importer(self.logger)

    # ── T21 ──────────────────────────────────────────────────────────────────
    def test_T21_importa_targets_json(self):
        """ZIP com targets.json válido deve retornar lista de URLs."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_valido_json.zip")
        )
        self.assertIsInstance(urls, list, "Deve retornar lista")
        self.assertGreater(len(urls), 0, "Lista não deve estar vazia")
        for url in urls:
            self.assertTrue(
                url.startswith("http://") or url.startswith("https://"),
                f"URL inválida importada: {url}"
            )

    # ── T22 ──────────────────────────────────────────────────────────────────
    def test_T22_importa_targets_txt(self):
        """ZIP com targets.txt deve importar URLs linha a linha."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_valido_txt.zip")
        )
        self.assertGreater(len(urls), 0, "Deve importar URLs do .txt")
        self.assertTrue(all(u.startswith("http") for u in urls))

    # ── T23 ──────────────────────────────────────────────────────────────────
    def test_T23_importa_targets_csv(self):
        """ZIP com targets.csv deve importar coluna 'url'."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_valido_csv.zip")
        )
        self.assertGreater(len(urls), 0, "Deve importar URLs do .csv")

    # ── T24 ──────────────────────────────────────────────────────────────────
    def test_T24_importa_config_embutida(self):
        """ZIP com config.json deve retornar configuração válida."""
        config = self.importer.import_config_from_zip(
            str(FIXTURES / "zip_com_config.zip")
        )
        self.assertIsNotNone(config, "Deve importar config do ZIP")
        self.assertIsInstance(config, dict)
        self.assertIn("scraper", config)
        self.assertEqual(config["scraper"]["max_depth"], 1)

    # ── T25 ──────────────────────────────────────────────────────────────────
    def test_T25_sem_duplicatas(self):
        """URLs importadas não devem conter duplicatas."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_valido_json.zip")
        )
        self.assertEqual(
            len(urls), len(set(urls)),
            "URLs importadas não devem ter duplicatas"
        )


# ─── Testes de Rejeição / Tratamento de Erros ────────────────────────────────

class TestImportRejection(unittest.TestCase):
    """ZIPs inválidos, corrompidos ou sem targets devem ser rejeitados graciosamente."""

    def setUp(self):
        self.logger = _make_logger("IMP-REJ-" + self._testMethodName[:8])
        self.importer = _make_importer(self.logger)

    # ── T26 ──────────────────────────────────────────────────────────────────
    def test_T26_arquivo_inexistente_retorna_lista_vazia(self):
        """Caminho inexistente deve retornar [] sem lançar exceção."""
        urls = self.importer.import_targets_from_zip(
            "/tmp/nao_existe_mesmo.zip"
        )
        self.assertEqual(urls, [], "Arquivo inexistente deve retornar lista vazia")

    # ── T27 ──────────────────────────────────────────────────────────────────
    def test_T27_arquivo_nao_e_zip_retorna_lista_vazia(self):
        """Arquivo que não é ZIP (mas tem extensão .zip) deve ser rejeitado."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "nao_e_zip.zip")
        )
        self.assertEqual(
            urls, [],
            "Arquivo inválido (não-ZIP) deve retornar lista vazia"
        )

    # ── T28 ──────────────────────────────────────────────────────────────────
    def test_T28_zip_corrompido_retorna_lista_vazia(self):
        """ZIP com bytes corrompidos deve ser rejeitado graciosamente."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_corrompido.zip")
        )
        self.assertEqual(
            urls, [],
            "ZIP corrompido deve retornar lista vazia sem exceção"
        )

    # ── T29 ──────────────────────────────────────────────────────────────────
    def test_T29_zip_vazio_sem_targets_retorna_lista_vazia(self):
        """ZIP sem nenhum arquivo targets.* deve retornar lista vazia."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_vazio.zip")
        )
        self.assertEqual(
            urls, [],
            "ZIP sem targets deve retornar lista vazia"
        )

    # ── T30 ──────────────────────────────────────────────────────────────────
    def test_T30_json_invalido_retorna_lista_vazia(self):
        """targets.json com JSON malformado deve ser rejeitado sem exceção."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_json_invalido.zip")
        )
        self.assertEqual(
            urls, [],
            "JSON malformado deve retornar lista vazia"
        )

    # ── T31 ──────────────────────────────────────────────────────────────────
    def test_T31_urls_invalidas_sao_filtradas(self):
        """URLs sem prefixo http:// ou https:// devem ser ignoradas."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_urls_invalidas.zip")
        )
        for url in urls:
            self.assertTrue(
                url.startswith("http://") or url.startswith("https://"),
                f"URL inválida não deveria ter sido importada: '{url}'"
            )
        # Nenhuma das entradas era URL válida, então deve retornar []
        self.assertEqual(urls, [], "Nenhuma URL válida deve ser importada")

    # ── T32 ──────────────────────────────────────────────────────────────────
    def test_T32_config_inexistente_retorna_none(self):
        """ZIP sem config.json deve retornar None para import_config_from_zip."""
        config = self.importer.import_config_from_zip(
            str(FIXTURES / "zip_valido_json.zip")
        )
        self.assertIsNone(config, "ZIP sem config.json deve retornar None")

    # ── T33 ──────────────────────────────────────────────────────────────────
    def test_T33_arquivo_inexistente_config_retorna_none(self):
        """Arquivo inexistente em import_config_from_zip deve retornar None."""
        config = self.importer.import_config_from_zip("/tmp/ghost.zip")
        self.assertIsNone(config)

    # ── T34 ──────────────────────────────────────────────────────────────────
    def test_T34_nao_e_zip_config_retorna_none(self):
        """Arquivo não-ZIP em import_config_from_zip deve retornar None sem exceção."""
        config = self.importer.import_config_from_zip(
            str(FIXTURES / "nao_e_zip.zip")
        )
        self.assertIsNone(config)


# ─── Testes de Exportação ZIP ─────────────────────────────────────────────────

class TestZipExport(unittest.TestCase):
    """Verifica integridade e conteúdo dos ZIPs exportados."""

    def setUp(self):
        self.logger = _make_logger("EXP-" + self._testMethodName[:8])
        self.export_dir = RESULTS / "exports_test"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        cfg = {
            "output_dir": str(self.export_dir),
            "report_dir": str(RESULTS),
            "zip_compression_level": 6,
            "include_html_snapshots": True,
        }
        self.exporter = ZipExporter(cfg, self.logger)

    # ── T35 ──────────────────────────────────────────────────────────────────
    def test_T35_exporta_zip_valido(self):
        """Export deve criar arquivo ZIP não-vazio."""
        pages = [{"url": "http://teste.com", "status_code": 200, "response_time_ms": 150,
                  "html_size_kb": 12, "page_title": "Teste", "errors_found": 1,
                  "warnings_found": 2, "timestamp": "2024-01-01T00:00:00Z"}]
        failures = [{"url": "http://teste.com", "error_type": "MISSING_TITLE",
                     "error_code": "HTML_001", "description": "Sem título",
                     "suggestion": "Adicione <title>", "severity": "LOW",
                     "category": "SEO", "page_title": None, "element": None, "extra": {}}]
        summary = {"pages_analyzed": 1, "total_failures": 1}

        zip_path = self.exporter.export_session(
            session_id="TEST-EXPORT-001",
            pages=pages, failures=failures,
            audit_records=[], summary=summary
        )
        self.assertTrue(zip_path.exists(), "ZIP deve ser criado")
        self.assertGreater(zip_path.stat().st_size, 0, "ZIP não deve estar vazio")

    # ── T36 ──────────────────────────────────────────────────────────────────
    def test_T36_zip_contem_relatorio_html(self):
        """ZIP exportado deve conter relatório HTML."""
        zip_path = self.exporter.export_session(
            session_id="TEST-EXPORT-002",
            pages=[], failures=[], audit_records=[], summary={}
        )
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
        html_files = [n for n in names if n.endswith(".html")]
        self.assertTrue(len(html_files) > 0, "ZIP deve conter ao menos um .html")

    # ── T37 ──────────────────────────────────────────────────────────────────
    def test_T37_zip_contem_csv_de_falhas(self):
        """ZIP exportado deve conter CSV de falhas."""
        failures = [
            {"url": "http://a.com", "error_type": "HTTP_500", "error_code": "500",
             "description": "Erro 500", "suggestion": "Corrija", "severity": "CRITICAL",
             "category": "SERVER", "page_title": "A", "element": None, "extra": {}},
        ]
        zip_path = self.exporter.export_session(
            session_id="TEST-EXPORT-003",
            pages=[], failures=failures, audit_records=[], summary={}
        )
        with zipfile.ZipFile(zip_path, "r") as zf:
            csv_files = [n for n in zf.namelist() if "falhas" in n and n.endswith(".csv")]
            self.assertTrue(len(csv_files) > 0, "ZIP deve conter CSV de falhas")
            content = zf.read(csv_files[0]).decode("utf-8-sig")
        self.assertIn("HTTP_500", content, "CSV deve conter o erro HTTP_500")
        self.assertIn("CRITICAL", content, "CSV deve conter severidade CRITICAL")

    # ── T38 ──────────────────────────────────────────────────────────────────
    def test_T38_zip_contem_manifesto(self):
        """ZIP exportado deve conter MANIFESTO.json."""
        zip_path = self.exporter.export_session(
            session_id="TEST-EXPORT-004",
            pages=[], failures=[], audit_records=[], summary={}
        )
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
        self.assertIn("MANIFESTO.json", names, "ZIP deve conter MANIFESTO.json")

    # ── T39 ──────────────────────────────────────────────────────────────────
    def test_T39_zip_e_reaberto_como_zip_valido(self):
        """ZIP exportado deve ser um arquivo ZIP válido e abrível."""
        zip_path = self.exporter.export_session(
            session_id="TEST-EXPORT-005",
            pages=[], failures=[], audit_records=[], summary={}
        )
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                bad = zf.testzip()
            self.assertIsNone(bad, f"ZIP com arquivo corrompido: {bad}")
        except zipfile.BadZipFile as e:
            self.fail(f"ZIP exportado é inválido: {e}")

    # ── T40 ──────────────────────────────────────────────────────────────────
    def test_T40_snapshot_html_incluido_no_zip(self):
        """HTML snapshots devem ser incluídos no ZIP quando habilitado."""
        snapshots = {"abc123": "<html><body>Snapshot de teste</body></html>"}
        zip_path = self.exporter.export_session(
            session_id="TEST-EXPORT-006",
            pages=[], failures=[], audit_records=[],
            html_snapshots=snapshots, summary={}
        )
        with zipfile.ZipFile(zip_path, "r") as zf:
            snap_files = [n for n in zf.namelist() if n.startswith("snapshots/")]
        self.assertEqual(len(snap_files), 1, "Deve conter 1 snapshot HTML")
