"""
Suite de Testes: Validação de Erros XML
Cobre detecção de XML malformado, entidades inválidas, namespaces não
declarados, declaração incorreta, XHTML inválido, atributos duplicados
e importação de targets.xml via ZIP.
"""

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import json
from src.analyzer import HTMLAnalyzer
from src.scraper import WebScraper, PageResult
from src.logger import AuditLogger
from src.zip_handler import ZipImporter
from tests.test_server import TestServer

FIXTURES = Path(__file__).parent / "fixtures"
RESULTS  = Path(__file__).parent / "results"


def _make_logger(session_id="XML"):
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


def _make_analyzer(logger):
    rules = json.loads((ROOT / "config" / "error_rules.json").read_text(encoding="utf-8"))
    config = {
        "check_http_errors": True,
        "check_slow_pages": False,
        "check_security_headers": False,
        "check_missing_meta": False,
        "check_accessibility": False,
        "check_broken_links": False,
        "check_empty_forms": False,
        "check_mixed_content": False,
        "check_xml": True,
    }
    return HTMLAnalyzer(config, rules, logger)


def _make_scraper(logger):
    cfg = {"timeout": 10, "max_retries": 1, "retry_delay": 0,
           "verify_ssl": False, "follow_redirects": True, "delay_between_requests": 0}
    return WebScraper(cfg, logger)


def _make_importer(logger):
    cfg = {"import_dir": str(FIXTURES), "output_dir": str(RESULTS)}
    return ZipImporter(cfg, logger)


def _xml_result(url: str, body: str, content_type: str = "application/xml") -> PageResult:
    """Cria um PageResult sintético com conteúdo XML."""
    return PageResult(
        url=url, status_code=200, html=body,
        response_time_ms=10, headers={"content-type": content_type}
    )


# ─── Servidor compartilhado ───────────────────────────────────────────────────

SERVER = TestServer(port=18081)  # Porta diferente para não conflitar


def setUpModule():
    SERVER.start()
    time.sleep(0.2)


def tearDownModule():
    SERVER.stop()


# ─── Testes de Detecção de Erros XML ─────────────────────────────────────────

class TestXMLDetection(unittest.TestCase):
    """Verifica se o analisador detecta corretamente falhas em documentos XML."""

    def setUp(self):
        self.logger = _make_logger("XML-DET-" + self._testMethodName[:8])
        self.analyzer = _make_analyzer(self.logger)
        self.scraper = _make_scraper(self.logger)
        self.base = SERVER.base_url()

    # ── T42 ──────────────────────────────────────────────────────────────────
    def test_T42_xml_valido_sem_erros(self):
        """XML bem formado e válido não deve gerar erros de XML."""
        result = self.scraper.fetch_page(f"{self.base}/xml-valido")
        errors = self.analyzer.analyze_page(result)
        xml_errors = [e for e in errors if e.category == "XML"]
        self.assertEqual(
            xml_errors, [],
            f"XML válido não deve ter erros XML. Encontrados: {[e.error_type for e in xml_errors]}"
        )

    # ── T43 ──────────────────────────────────────────────────────────────────
    def test_T43_detecta_tag_nao_fechada(self):
        """XML com tag não fechada deve gerar MALFORMED_XML."""
        result = self.scraper.fetch_page(f"{self.base}/xml-tag-nao-fechada")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        self.assertIn("MALFORMED_XML", tipos, "Deve detectar XML malformado (tag não fechada)")

        err = next(e for e in errors if e.error_type == "MALFORMED_XML")
        self.assertEqual(err.severity, "HIGH")
        self.assertIn("XML", err.category)
        self.assertTrue(len(err.suggestion) > 10, "Deve ter sugestão de correção")

    # ── T44 ──────────────────────────────────────────────────────────────────
    def test_T44_detecta_entidades_invalidas(self):
        """XML com entidades HTML (&copy; &nbsp; &mdash;) deve ser detectado."""
        body = """<?xml version="1.0" encoding="UTF-8"?>
<pagina>
  <texto>Direitos &copy; reservados&nbsp;aqui &mdash; sempre</texto>
</pagina>"""
        result = _xml_result("http://teste.com/feed.xml", body)
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        # XML é inválido por causa das entidades E pelas entidades em si
        xml_related = [e for e in errors if e.category == "XML"]
        self.assertTrue(len(xml_related) > 0, "Deve detectar erros XML com entidades inválidas")

    # ── T45 ──────────────────────────────────────────────────────────────────
    def test_T45_detecta_declaracao_xml_invalida(self):
        """XML com 'versao' em vez de 'version' deve gerar erro de declaração ou malformado."""
        result = self.scraper.fetch_page(f"{self.base}/xml-declaracao-invalida")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        # Pode ser INVALID_XML_DECLARATION (declaração inválida detectada por regex)
        # ou MALFORMED_XML (parser estrito falha na declaração incorreta)
        xml_errors = [e for e in errors if e.category == "XML"]
        self.assertTrue(
            len(xml_errors) > 0,
            "Deve detectar erro XML na declaração inválida (versao= em vez de version=)"
        )
        self.assertTrue(
            "INVALID_XML_DECLARATION" in tipos or "MALFORMED_XML" in tipos,
            f"Deve gerar INVALID_XML_DECLARATION ou MALFORMED_XML. Obtidos: {tipos}"
        )

    # ── T46 ──────────────────────────────────────────────────────────────────
    def test_T46_detecta_namespace_nao_declarado(self):
        """XML com prefixos soap: e ns2: sem xmlns: deve gerar erro de namespace."""
        result = self.scraper.fetch_page(f"{self.base}/xml-namespace-nao-declarado")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        # O XML é inválido (namespace não declarado causa ParseError)
        # então deve haver MALFORMED_XML ou UNDEFINED_XML_NAMESPACE
        xml_errors = [e for e in errors if e.category == "XML"]
        self.assertTrue(
            len(xml_errors) > 0,
            "Deve detectar erro de namespace não declarado"
        )

    # ── T47 ──────────────────────────────────────────────────────────────────
    def test_T47_detecta_xhtml_invalido(self):
        """XHTML servido como application/xhtml+xml mas mal formado deve gerar erro."""
        result = self.scraper.fetch_page(f"{self.base}/xhtml-invalido")
        errors = self.analyzer.analyze_page(result)
        xml_errors = [e for e in errors if e.category == "XML"]
        self.assertTrue(
            len(xml_errors) > 0,
            "XHTML inválido servido como application/xhtml+xml deve gerar erro XML"
        )

    # ── T48 ──────────────────────────────────────────────────────────────────
    def test_T48_detecta_atributo_duplicado(self):
        """XML com atributo id duplicado na mesma tag deve ser detectado."""
        result = self.scraper.fetch_page(f"{self.base}/xml-atributo-duplicado")
        errors = self.analyzer.analyze_page(result)
        tipos = [e.error_type for e in errors]
        # Atributo duplicado causa ParseError no parser estrito
        xml_errors = [e for e in errors if e.category == "XML"]
        self.assertTrue(
            len(xml_errors) > 0,
            "Deve detectar atributo duplicado no XML"
        )

    # ── T49 ──────────────────────────────────────────────────────────────────
    def test_T49_xml_sintetico_tag_nao_fechada(self):
        """Testa detector diretamente com XML sintético de tag não fechada."""
        body = """<?xml version="1.0" encoding="UTF-8"?>
<root>
  <item>texto sem fechar
  <outro>ok</outro>
</root>"""
        result = _xml_result("http://exemplo.com/dados.xml", body)
        errors = self.analyzer.analyze_page(result)
        self.assertTrue(
            any(e.error_type == "MALFORMED_XML" for e in errors),
            "Deve detectar MALFORMED_XML em XML sintético"
        )

    # ── T50 ──────────────────────────────────────────────────────────────────
    def test_T50_xml_sintetico_declaracao_sem_version(self):
        """XML com declaração sem atributo version deve gerar INVALID_XML_DECLARATION."""
        body = '<?xml encoding="UTF-8"?>\n<root><item>ok</item></root>'
        result = _xml_result("http://exemplo.com/feed.xml", body)
        errors = self.analyzer.analyze_page(result)
        self.assertTrue(
            any(e.error_type == "INVALID_XML_DECLARATION" for e in errors),
            "Deve detectar declaração XML sem version"
        )

    # ── T51 ──────────────────────────────────────────────────────────────────
    def test_T51_html_normal_nao_detecta_xml(self):
        """HTML puro sem declaração XML não deve gerar erros de categoria XML."""
        body = """<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Página Normal</title></head>
<body><h1>Sem XML</h1></body>
</html>"""
        result = PageResult(
            url="http://exemplo.com/", status_code=200, html=body,
            response_time_ms=10, headers={"content-type": "text/html; charset=utf-8"}
        )
        errors = self.analyzer.analyze_page(result)
        xml_errors = [e for e in errors if e.category == "XML"]
        self.assertEqual(
            xml_errors, [],
            "HTML puro não deve gerar erros XML"
        )

    # ── T52 ──────────────────────────────────────────────────────────────────
    def test_T52_todos_erros_xml_tem_sugestao(self):
        """Todos os erros XML detectados devem ter sugestão de correção não vazia."""
        routes_xml = [
            "/xml-tag-nao-fechada",
            "/xml-declaracao-invalida",
            "/xml-namespace-nao-declarado",
            "/xml-atributo-duplicado",
            "/xhtml-invalido",
        ]
        for route in routes_xml:
            result = self.scraper.fetch_page(f"{self.base}{route}")
            errors = self.analyzer.analyze_page(result)
            for e in errors:
                if e.category == "XML":
                    self.assertTrue(
                        e.suggestion and len(e.suggestion) > 10,
                        f"Erro {e.error_type} em {route} sem sugestão de correção"
                    )


# ─── Testes de Importação XML via ZIP ────────────────────────────────────────

class TestXMLImport(unittest.TestCase):
    """Verifica importação de targets.xml de dentro de ZIPs."""

    def setUp(self):
        self.logger = _make_logger("XML-IMP-" + self._testMethodName[:8])
        self.importer = _make_importer(self.logger)

    # ── T53 ──────────────────────────────────────────────────────────────────
    def test_T53_importa_targets_xml_formato_url_texto(self):
        """ZIP com <urls><url>...</url></urls> deve importar URLs corretamente."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_targets_xml_valido.zip")
        )
        self.assertGreater(len(urls), 0, "Deve importar URLs do XML")
        for url in urls:
            self.assertTrue(url.startswith("http"), f"URL inválida: {url}")

    # ── T54 ──────────────────────────────────────────────────────────────────
    def test_T54_importa_targets_xml_formato_atributo(self):
        """ZIP com <target url='...'> deve importar URLs corretamente."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_targets_xml_attrs.zip")
        )
        self.assertGreater(len(urls), 0, "Deve importar URLs de atributos XML")
        for url in urls:
            self.assertTrue(url.startswith("http"), f"URL inválida: {url}")

    # ── T55 ──────────────────────────────────────────────────────────────────
    def test_T55_xml_malformado_retorna_lista_vazia(self):
        """targets.xml com tag não fechada deve ser rejeitado graciosamente."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_targets_xml_malformado.zip")
        )
        self.assertEqual(
            urls, [],
            "XML malformado deve retornar lista vazia sem lançar exceção"
        )

    # ── T56 ──────────────────────────────────────────────────────────────────
    def test_T56_xml_sem_urls_retorna_lista_vazia(self):
        """targets.xml sem URLs http/https deve retornar lista vazia."""
        urls = self.importer.import_targets_from_zip(
            str(FIXTURES / "zip_targets_xml_sem_urls.zip")
        )
        self.assertEqual(
            urls, [],
            "XML sem URLs válidas deve retornar lista vazia"
        )

    # ── T57 ──────────────────────────────────────────────────────────────────
    def test_T57_xml_nao_importa_ftp_nem_texto(self):
        """URLs com esquema ftp:// ou texto simples não devem ser importadas."""
        from src.zip_handler import ZipImporter
        import zipfile, io as _io

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urls>
  <url>ftp://servidor.com/arquivo</url>
  <url>apenas-texto-sem-esquema</url>
  <url>http://valida.com</url>
</urls>"""
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("targets.xml", xml)
        buf.seek(0)

        # Salva temporariamente
        tmp = FIXTURES / "tmp_ftp_test.zip"
        tmp.write_bytes(buf.getvalue())
        try:
            urls = self.importer.import_targets_from_zip(str(tmp))
            self.assertEqual(len(urls), 1, "Deve importar apenas a URL http://")
            self.assertEqual(urls[0], "http://valida.com")
        finally:
            tmp.unlink(missing_ok=True)

    # ── T58 ──────────────────────────────────────────────────────────────────
    def test_T58_xml_encoding_errado_tratado(self):
        """targets.xml com encoding declarado incompatível não deve quebrar o sistema."""
        try:
            urls = self.importer.import_targets_from_zip(
                str(FIXTURES / "zip_targets_xml_enc_errado.zip")
            )
            # Pode retornar lista vazia ou URLs – não deve lançar exceção
            self.assertIsInstance(urls, list)
        except Exception as e:
            self.fail(f"Não deve lançar exceção com XML de encoding incorreto: {e}")

    # ── T59 ──────────────────────────────────────────────────────────────────
    def test_T59_parser_xml_direto_valido(self):
        """_parse_targets_xml direto com XML válido deve retornar URLs."""
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<urls>
  <url>http://site1.com</url>
  <url>https://site2.com</url>
</urls>"""
        urls = self.importer._parse_targets_xml(xml)
        self.assertEqual(len(urls), 2)
        self.assertIn("http://site1.com", urls)
        self.assertIn("https://site2.com", urls)

    # ── T60 ──────────────────────────────────────────────────────────────────
    def test_T60_parser_xml_direto_malformado(self):
        """_parse_targets_xml com XML malformado deve retornar [] sem exceção."""
        xml_ruim = b"<urls><url>http://ok.com</url<urls>"
        try:
            urls = self.importer._parse_targets_xml(xml_ruim)
            self.assertEqual(urls, [], "XML malformado deve retornar []")
        except Exception as e:
            self.fail(f"_parse_targets_xml não deve lançar exceção: {e}")
