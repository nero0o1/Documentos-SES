"""
Analisador de HTML e Detector de Erros
Analisa o HTML coletado, detecta problemas e gera sugestões de correção.
"""

import re
import time
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup, Tag

from .scraper import PageResult


class AnalysisError:
    """Representa um erro/problema encontrado na análise."""

    def __init__(
        self,
        url: str,
        error_type: str,
        error_code: Optional[str],
        description: str,
        suggestion: str,
        severity: str,
        category: str,
        element: Optional[str] = None,
        page_title: Optional[str] = None,
        extra: Optional[Dict] = None
    ):
        self.url = url
        self.error_type = error_type
        self.error_code = error_code
        self.description = description
        self.suggestion = suggestion
        self.severity = severity
        self.category = category
        self.element = element
        self.page_title = page_title
        self.extra = extra or {}

    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "description": self.description,
            "suggestion": self.suggestion,
            "severity": self.severity,
            "category": self.category,
            "element": self.element,
            "page_title": self.page_title,
            "extra": self.extra
        }


class HTMLAnalyzer:
    """Analisa HTML e detecta problemas de acessibilidade, SEO, segurança e performance."""

    DEPRECATED_TAGS = {
        "font", "center", "strike", "tt", "big", "small", "basefont",
        "applet", "marquee", "bgsound", "blink", "dir", "isindex",
        "listing", "plaintext", "xmp", "frame", "frameset", "noframes"
    }

    SECURITY_HEADERS_REQUIRED = [
        ("x-frame-options", "missing_x_frame_options"),
        ("content-security-policy", "missing_csp"),
        ("strict-transport-security", "missing_hsts"),
        ("x-content-type-options", "missing_x_content_type"),
    ]

    def __init__(self, config: Dict, error_rules: Dict, logger):
        self.config = config
        self.error_rules = error_rules
        self.logger = logger

    def analyze_page(self, result: PageResult) -> List[AnalysisError]:
        """Analisa uma página e retorna lista de erros encontrados."""
        errors: List[AnalysisError] = []

        # Verifica erros HTTP
        if self.config.get("check_http_errors", True):
            http_errors = self._check_http_status(result)
            errors.extend(http_errors)

        # Verifica performance
        if self.config.get("check_slow_pages", True):
            perf_errors = self._check_performance(result)
            errors.extend(perf_errors)

        # Verifica headers de segurança
        if self.config.get("check_security_headers", True):
            sec_errors = self._check_security_headers(result)
            errors.extend(sec_errors)

        # Se não tem HTML válido, para aqui
        if not result.soup or not result.html:
            return errors

        # Verifica meta tags
        if self.config.get("check_missing_meta", True):
            meta_errors = self._check_meta_tags(result)
            errors.extend(meta_errors)

        # Verifica acessibilidade
        if self.config.get("check_accessibility", True):
            acc_errors = self._check_accessibility(result)
            errors.extend(acc_errors)

        # Verifica links quebrados internos
        if self.config.get("check_broken_links", True):
            link_errors = self._check_internal_links(result)
            errors.extend(link_errors)

        # Verifica formulários
        if self.config.get("check_empty_forms", True):
            form_errors = self._check_forms(result)
            errors.extend(form_errors)

        # Verifica conteúdo misto
        if self.config.get("check_mixed_content", True):
            mixed_errors = self._check_mixed_content(result)
            errors.extend(mixed_errors)

        # Verifica tags depreciadas
        depr_errors = self._check_deprecated_tags(result)
        errors.extend(depr_errors)

        return errors

    def _check_http_status(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        code = result.status_code
        if code == 0 and result.error:
            errors.append(AnalysisError(
                url=result.url,
                error_type="CONNECTION_FAILED",
                error_code="0",
                description=f"Falha de conexão: {result.error}",
                suggestion="Verifique se o servidor está acessível, se a URL está correta e se não há bloqueio de firewall.",
                severity="CRITICAL",
                category="CONNECTIVITY",
                page_title=result.page_title
            ))
        elif code and code >= 400:
            rule_key = str(code)
            http_rules = self.error_rules.get("http_errors", {})
            rule = http_rules.get(rule_key, {})
            errors.append(AnalysisError(
                url=result.url,
                error_type=f"HTTP_{code}",
                error_code=rule_key,
                description=f"HTTP {code}: {rule.get('name', 'Erro HTTP')}",
                suggestion=rule.get("suggestion", "Verifique os logs do servidor para mais detalhes."),
                severity=rule.get("severity", "HIGH"),
                category=rule.get("category", "HTTP"),
                page_title=result.page_title
            ))
        return errors

    def _check_performance(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        threshold = self.config.get("slow_page_threshold_ms", 3000)
        if result.response_time_ms > threshold:
            perf_rule = self.error_rules.get("performance", {}).get("slow_response", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="SLOW_RESPONSE",
                error_code="PERF_001",
                description=f"Tempo de resposta elevado: {result.response_time_ms:.0f}ms (limite: {threshold}ms)",
                suggestion=perf_rule.get("suggestion", "Otimize o tempo de resposta do servidor."),
                severity=perf_rule.get("severity", "MEDIUM"),
                category="PERFORMANCE",
                page_title=result.page_title,
                extra={"response_time_ms": result.response_time_ms, "threshold_ms": threshold}
            ))

        size_threshold_bytes = self.config.get("large_resource_threshold_kb", 500) * 1024
        if result.html_size_bytes > size_threshold_bytes:
            errors.append(AnalysisError(
                url=result.url,
                error_type="LARGE_PAGE",
                error_code="PERF_002",
                description=f"Página muito grande: {result.html_size_bytes // 1024}KB (limite: {size_threshold_bytes // 1024}KB)",
                suggestion="Reduza o tamanho do HTML: remova comentários, whitespace excessivo, inline scripts/styles grandes. Considere lazy loading.",
                severity="LOW",
                category="PERFORMANCE",
                page_title=result.page_title,
                extra={"size_kb": result.html_size_bytes // 1024}
            ))
        return errors

    def _check_security_headers(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        if not result.headers:
            return errors

        lower_headers = {k.lower(): v for k, v in result.headers.items()}
        is_https = result.url.startswith("https://")
        sec_rules = self.error_rules.get("security_headers", {})

        for header_name, rule_key in self.SECURITY_HEADERS_REQUIRED:
            # HSTS só é relevante para HTTPS
            if header_name == "strict-transport-security" and not is_https:
                continue
            if header_name not in lower_headers:
                rule = sec_rules.get(rule_key, {})
                errors.append(AnalysisError(
                    url=result.url,
                    error_type="MISSING_SECURITY_HEADER",
                    error_code=rule_key.upper(),
                    description=f"Header de segurança ausente: {header_name}",
                    suggestion=rule.get("suggestion", f"Adicione o header {header_name} na resposta do servidor."),
                    severity=rule.get("severity", "MEDIUM"),
                    category="SECURITY",
                    page_title=result.page_title,
                    extra={"missing_header": header_name}
                ))

        # Verifica Cache-Control
        if "cache-control" not in lower_headers:
            perf_rule = self.error_rules.get("performance", {}).get("no_cache_control", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="MISSING_CACHE_CONTROL",
                error_code="PERF_003",
                description="Header Cache-Control não configurado",
                suggestion=perf_rule.get("suggestion", "Configure o header Cache-Control adequadamente."),
                severity="LOW",
                category="PERFORMANCE",
                page_title=result.page_title
            ))
        return errors

    def _check_meta_tags(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        soup = result.soup
        html_rules = self.error_rules.get("html_errors", {})

        # Title
        title_tag = soup.find("title")
        if not title_tag or not title_tag.get_text(strip=True):
            rule = html_rules.get("missing_title", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="MISSING_TITLE",
                error_code="HTML_001",
                description="Página sem tag <title> ou com título vazio",
                suggestion=rule.get("suggestion", "Adicione uma tag <title> descritiva no <head>."),
                severity=rule.get("severity", "LOW"),
                category="SEO",
                page_title=result.page_title
            ))

        # Meta description
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
        if not meta_desc or not meta_desc.get("content", "").strip():
            rule = html_rules.get("missing_meta_description", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="MISSING_META_DESCRIPTION",
                error_code="HTML_002",
                description="Meta description ausente ou vazia",
                suggestion=rule.get("suggestion", "Adicione meta description no <head>."),
                severity=rule.get("severity", "LOW"),
                category="SEO",
                page_title=result.page_title
            ))

        # Viewport
        meta_vp = soup.find("meta", attrs={"name": re.compile(r"viewport", re.I)})
        if not meta_vp:
            rule = html_rules.get("missing_viewport", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="MISSING_VIEWPORT",
                error_code="HTML_003",
                description="Meta viewport ausente - página pode não ser responsiva",
                suggestion=rule.get("suggestion", "Adicione meta viewport no <head>."),
                severity=rule.get("severity", "MEDIUM"),
                category="MOBILE",
                page_title=result.page_title
            ))

        # Lang attribute
        html_tag = soup.find("html")
        if html_tag and not html_tag.get("lang"):
            rule = html_rules.get("missing_lang", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="MISSING_LANG_ATTR",
                error_code="HTML_004",
                description="Atributo 'lang' ausente na tag <html>",
                suggestion=rule.get("suggestion", "Adicione lang='pt-BR' na tag <html>."),
                severity=rule.get("severity", "LOW"),
                category="ACCESSIBILITY",
                page_title=result.page_title
            ))
        return errors

    def _check_accessibility(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        soup = result.soup
        html_rules = self.error_rules.get("html_errors", {})

        # Imagens sem alt
        imgs_without_alt = []
        for img in soup.find_all("img"):
            if not img.get("alt") and img.get("alt") != "":
                src = img.get("src", "N/A")[:100]
                imgs_without_alt.append(src)

        if imgs_without_alt:
            rule = html_rules.get("missing_alt", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="MISSING_ALT_TEXT",
                error_code="ACC_001",
                description=f"{len(imgs_without_alt)} imagem(ns) sem atributo 'alt'",
                suggestion=rule.get("suggestion", "Adicione alt descritivo em todas as imagens."),
                severity=rule.get("severity", "LOW"),
                category="ACCESSIBILITY",
                page_title=result.page_title,
                extra={"images": imgs_without_alt[:10]}
            ))
        return errors

    def _check_internal_links(self, result: PageResult) -> List[AnalysisError]:
        """Verifica links com href inválidos ou suspeitos (broken links são checados no crawl)."""
        errors = []
        soup = result.soup
        html_rules = self.error_rules.get("html_errors", {})

        empty_links = []
        for a_tag in soup.find_all("a"):
            href = a_tag.get("href", "").strip()
            if href == "" or href == "#":
                text = a_tag.get_text(strip=True)[:50] or "[sem texto]"
                empty_links.append(text)

        if empty_links:
            errors.append(AnalysisError(
                url=result.url,
                error_type="EMPTY_LINKS",
                error_code="NAV_001",
                description=f"{len(empty_links)} link(s) sem destino válido (href vazio ou '#')",
                suggestion="Defina href válidos nos links ou use buttons para ações JavaScript. Links sem destino prejudicam acessibilidade e SEO.",
                severity="LOW",
                category="NAVIGATION",
                page_title=result.page_title,
                extra={"links": empty_links[:10]}
            ))
        return errors

    def _check_forms(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        soup = result.soup
        html_rules = self.error_rules.get("html_errors", {})

        for idx, form in enumerate(soup.find_all("form"), 1):
            action = form.get("action", "").strip()
            method = form.get("method", "get").lower()

            # Formulário sem action e sem JS handler óbvio
            if not action:
                rule = html_rules.get("empty_form_action", {})
                errors.append(AnalysisError(
                    url=result.url,
                    error_type="FORM_NO_ACTION",
                    error_code="FORM_001",
                    description=f"Formulário #{idx} sem atributo 'action' definido",
                    suggestion=rule.get("suggestion", "Adicione action no formulário."),
                    severity=rule.get("severity", "MEDIUM"),
                    category="FUNCTIONALITY",
                    element=str(form)[:200],
                    page_title=result.page_title
                ))

            # Formulário POST sem token CSRF visível
            if method == "post":
                csrf_found = any(
                    inp.get("name", "").lower() in ("csrf_token", "_token", "csrfmiddlewaretoken", "authenticity_token", "__requestverificationtoken")
                    for inp in form.find_all("input", type="hidden")
                )
                if not csrf_found:
                    rule = html_rules.get("missing_csrf", {})
                    errors.append(AnalysisError(
                        url=result.url,
                        error_type="MISSING_CSRF_TOKEN",
                        error_code="SEC_001",
                        description=f"Formulário POST #{idx} sem token CSRF detectado",
                        suggestion=rule.get("suggestion", "Adicione proteção CSRF ao formulário."),
                        severity=rule.get("severity", "HIGH"),
                        category="SECURITY",
                        element=f"Form #{idx} action='{action}'",
                        page_title=result.page_title
                    ))
        return errors

    def _check_mixed_content(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        if not result.url.startswith("https://"):
            return errors

        soup = result.soup
        html_rules = self.error_rules.get("html_errors", {})
        mixed_items = []

        # Verifica scripts, links CSS, imagens, iframes com HTTP
        for tag_name, attr in [("script", "src"), ("link", "href"), ("img", "src"), ("iframe", "src")]:
            for tag in soup.find_all(tag_name):
                src = tag.get(attr, "")
                if src.startswith("http://"):
                    mixed_items.append(f"<{tag_name} {attr}='{src[:80]}'>")

        if mixed_items:
            rule = html_rules.get("mixed_content", {})
            errors.append(AnalysisError(
                url=result.url,
                error_type="MIXED_CONTENT",
                error_code="SEC_002",
                description=f"{len(mixed_items)} recurso(s) HTTP em página HTTPS (conteúdo misto)",
                suggestion=rule.get("suggestion", "Substitua todos os recursos HTTP por HTTPS."),
                severity=rule.get("severity", "HIGH"),
                category="SECURITY",
                page_title=result.page_title,
                extra={"items": mixed_items[:10]}
            ))
        return errors

    def _check_deprecated_tags(self, result: PageResult) -> List[AnalysisError]:
        errors = []
        soup = result.soup
        html_rules = self.error_rules.get("html_errors", {})
        found_deprecated = {}

        for tag in soup.find_all(True):
            if tag.name in self.DEPRECATED_TAGS:
                found_deprecated[tag.name] = found_deprecated.get(tag.name, 0) + 1

        if found_deprecated:
            rule = html_rules.get("deprecated_html", {})
            desc_parts = [f"<{tag}>: {count}x" for tag, count in found_deprecated.items()]
            errors.append(AnalysisError(
                url=result.url,
                error_type="DEPRECATED_HTML_TAGS",
                error_code="HTML_005",
                description=f"Tags HTML depreciadas encontradas: {', '.join(desc_parts)}",
                suggestion=rule.get("suggestion", "Substitua tags depreciadas por equivalentes CSS modernos."),
                severity="LOW",
                category="CODE_QUALITY",
                page_title=result.page_title,
                extra={"deprecated_tags": found_deprecated}
            ))
        return errors

    def analyze_broken_link(
        self, source_url: str, link_url: str, status_code: int, page_title: Optional[str] = None
    ) -> Optional[AnalysisError]:
        """Cria um erro para um link quebrado encontrado durante o crawl."""
        if status_code >= 400:
            html_rules = self.error_rules.get("html_errors", {})
            http_rules = self.error_rules.get("http_errors", {})
            rule = html_rules.get("broken_link", {})
            http_rule = http_rules.get(str(status_code), {})
            return AnalysisError(
                url=source_url,
                error_type="BROKEN_LINK",
                error_code=f"LINK_{status_code}",
                description=f"Link quebrado ({status_code}): {link_url}",
                suggestion=rule.get("suggestion", "Corrija ou remova o link quebrado.") + f" ({http_rule.get('name', '')})",
                severity="MEDIUM",
                category="NAVIGATION",
                element=f"<a href='{link_url}'>",
                page_title=page_title,
                extra={"broken_url": link_url, "http_status": status_code}
            )
        return None
