"""
Motor de Web Scraping
Responsável por buscar e armazenar o HTML completo de sites.
Suporta crawling recursivo configurável.
"""

import time
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse, urlencode
from pathlib import Path

import requests
from bs4 import BeautifulSoup


class PageResult:
    """Resultado do scraping de uma página."""

    def __init__(
        self,
        url: str,
        status_code: int,
        html: Optional[str],
        response_time_ms: float,
        headers: Dict,
        error: Optional[str] = None,
        final_url: Optional[str] = None
    ):
        self.url = url
        self.final_url = final_url or url
        self.status_code = status_code
        self.html = html or ""
        self.response_time_ms = response_time_ms
        self.headers = headers
        self.error = error
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.html_size_bytes = len(self.html.encode("utf-8")) if self.html else 0
        self.page_title = self._extract_title()
        self.soup: Optional[BeautifulSoup] = None
        if self.html:
            try:
                self.soup = BeautifulSoup(self.html, "lxml")
            except Exception:
                try:
                    self.soup = BeautifulSoup(self.html, "html.parser")
                except Exception:
                    pass

    def _extract_title(self) -> Optional[str]:
        if not self.html:
            return None
        try:
            soup = BeautifulSoup(self.html, "html.parser")
            title_tag = soup.find("title")
            return title_tag.get_text(strip=True) if title_tag else None
        except Exception:
            return None

    def is_success(self) -> bool:
        return self.status_code and 200 <= self.status_code < 300

    def get_hash(self) -> str:
        return hashlib.md5(self.html.encode("utf-8")).hexdigest()


class WebScraper:
    """Motor principal de scraping configurável."""

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        self.session = self._build_session()
        self._visited_urls: Set[str] = set()
        self._page_results: List[PageResult] = []

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        headers = {
            "User-Agent": self.config.get(
                "user_agent", "WebAuditBot/1.0"
            )
        }
        headers.update(self.config.get("headers", {}))
        session.headers.update(headers)
        return session

    def fetch_page(self, url: str) -> PageResult:
        """Busca uma única página e retorna o resultado."""
        timeout = self.config.get("timeout", 30)
        max_retries = self.config.get("max_retries", 3)
        retry_delay = self.config.get("retry_delay", 2)
        verify_ssl = self.config.get("verify_ssl", True)
        allow_redirects = self.config.get("follow_redirects", True)

        last_error = None
        for attempt in range(max_retries):
            if attempt > 0:
                self.logger.info(
                    f"Tentativa {attempt + 1}/{max_retries} para {url}"
                )
                time.sleep(retry_delay * attempt)

            try:
                start = time.monotonic()
                response = self.session.get(
                    url,
                    timeout=timeout,
                    verify=verify_ssl,
                    allow_redirects=allow_redirects
                )
                elapsed_ms = (time.monotonic() - start) * 1000

                try:
                    html = response.text
                except Exception:
                    html = response.content.decode("utf-8", errors="replace")

                result = PageResult(
                    url=url,
                    status_code=response.status_code,
                    html=html,
                    response_time_ms=elapsed_ms,
                    headers=dict(response.headers),
                    final_url=response.url
                )
                self.logger.info(
                    f"Fetch {url} → {response.status_code} "
                    f"({elapsed_ms:.0f}ms, {result.html_size_bytes // 1024}KB)"
                )
                return result

            except requests.exceptions.SSLError as e:
                last_error = f"Erro SSL: {e}"
                self.logger.error(f"SSL error em {url}: {e}")
                break  # Não faz retry em SSL error

            except requests.exceptions.ConnectionError as e:
                last_error = f"Erro de conexão: {e}"
                self.logger.warning(f"Conexão falhou em {url}: {e}")

            except requests.exceptions.Timeout as e:
                last_error = f"Timeout após {timeout}s: {e}"
                self.logger.warning(f"Timeout em {url}: {e}")

            except requests.exceptions.RequestException as e:
                last_error = f"Erro de requisição: {e}"
                self.logger.error(f"Erro em {url}: {e}")
                break

        return PageResult(
            url=url,
            status_code=0,
            html=None,
            response_time_ms=0,
            headers={},
            error=last_error
        )

    def crawl(
        self,
        start_url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        same_domain_only: bool = True
    ) -> List[PageResult]:
        """
        Crawla um site recursivamente a partir de uma URL inicial.
        Retorna lista de PageResult para cada página visitada.
        """
        max_depth = max_depth or self.config.get("max_depth", 3)
        max_pages = max_pages or self.config.get("max_pages", 100)
        delay = self.config.get("delay_between_requests", 1.0)

        base_domain = urlparse(start_url).netloc
        queue: List[Tuple[str, int]] = [(start_url, 0)]
        results: List[PageResult] = []
        visited: Set[str] = set()

        self.logger.info(
            f"Iniciando crawl: {start_url} | "
            f"Max profundidade: {max_depth} | Max páginas: {max_pages}"
        )

        while queue and len(results) < max_pages:
            url, depth = queue.pop(0)
            normalized_url = self._normalize_url(url)

            if normalized_url in visited:
                continue
            visited.add(normalized_url)

            result = self.fetch_page(url)
            results.append(result)
            self._page_results.append(result)

            if delay > 0:
                time.sleep(delay)

            # Extrai links para continuar crawling
            if depth < max_depth and result.soup and result.is_success():
                links = self._extract_links(result.soup, url)
                for link in links:
                    link_domain = urlparse(link).netloc
                    if same_domain_only and link_domain != base_domain:
                        continue
                    normalized_link = self._normalize_url(link)
                    if normalized_link not in visited:
                        queue.append((link, depth + 1))

        self.logger.info(
            f"Crawl finalizado: {len(results)} páginas visitadas"
        )
        return results

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extrai todos os links válidos de uma página."""
        links = []
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme in ("http", "https"):
                # Remove fragmento
                clean = parsed._replace(fragment="").geturl()
                links.append(clean)
        return links

    def _normalize_url(self, url: str) -> str:
        """Normaliza URL para comparação (remove trailing slash, lowercase scheme/host)."""
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=netloc,
            path=path,
            fragment=""
        )
        return normalized.geturl()

    def get_all_results(self) -> List[PageResult]:
        return self._page_results.copy()
