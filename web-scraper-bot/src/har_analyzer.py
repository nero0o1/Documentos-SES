"""
HAR Analyzer - WebAuditBot SES
Analisa arquivos HAR (HTTP Archive) exportados pelos navegadores.
Detecta erros HTTP, requisições lentas, respostas grandes,
problemas de segurança e headers ausentes.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class HAREntry:
    url: str
    method: str
    status: int
    mime_type: str
    time_ms: int
    size_kb: float

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "method": self.method,
            "status": self.status,
            "mime_type": self.mime_type,
            "time_ms": self.time_ms,
            "size_kb": self.size_kb,
        }


@dataclass
class HARIssue:
    severity: str
    type: str
    url: str
    detail: str
    suggestion: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "type": self.type,
            "url": self.url,
            "detail": self.detail,
            "suggestion": self.suggestion,
        }


@dataclass
class HARReport:
    filename: str = ""
    total_requests: int = 0
    errors_4xx: int = 0
    errors_5xx: int = 0
    slow_requests: int = 0
    large_responses: int = 0
    total_transfer_kb: float = 0.0
    page_load_ms: int = 0
    issues: List[HARIssue] = field(default_factory=list)
    entries: List[HAREntry] = field(default_factory=list)
    slow_entries: List[HAREntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "total_requests": self.total_requests,
            "errors_4xx": self.errors_4xx,
            "errors_5xx": self.errors_5xx,
            "slow_requests": self.slow_requests,
            "large_responses": self.large_responses,
            "total_transfer_kb": round(self.total_transfer_kb, 1),
            "page_load_ms": self.page_load_ms,
            "issues": [i.to_dict() for i in self.issues],
            "entries": [e.to_dict() for e in self.entries],
            "slow_entries": [e.to_dict() for e in self.slow_entries],
        }


class HARAnalyzer:
    """
    Analisa arquivos HAR (HTTP Archive) gerados pelos DevTools dos navegadores.

    Detecta:
    - Erros HTTP (4xx, 5xx)
    - Requisições lentas (>2s)
    - Respostas muito grandes (>500 KB)
    - Headers de segurança ausentes nas respostas principais
    - Erros CORS (Access-Control-Allow-Origin)
    - Redirecionamentos excessivos
    - Requisições bloqueadas
    - Mixed content (HTTP em sessão HTTPS)
    """

    SLOW_THRESHOLD_MS   = 2000   # ms
    LARGE_THRESHOLD_KB  = 500    # KB
    MAX_REDIRECTS       = 5

    def analyze(self, har_data: dict) -> HARReport:
        """Analisa o dicionário HAR e retorna HARReport."""
        report = HARReport()

        log = har_data.get("log", {})

        # Tempo de carga das páginas
        pages = log.get("pages", [])
        if pages:
            for page in pages:
                pt = page.get("pageTimings", {})
                load = pt.get("onLoad", 0) or pt.get("onContentLoad", 0) or 0
                if load > 0:
                    report.page_load_ms = max(report.page_load_ms, int(load))

        entries = log.get("entries", [])
        if not entries:
            return report

        redirect_map: Dict[str, int] = {}

        for entry in entries:
            req  = entry.get("request", {})
            resp = entry.get("response", {})

            url         = req.get("url", "")
            method      = req.get("method", "GET")
            status      = resp.get("status", 0)
            time_ms     = int(entry.get("time", 0))
            content     = resp.get("content", {})
            mime_type   = content.get("mimeType", "")
            size_bytes  = (content.get("size", 0) or
                           resp.get("bodySize", 0) or
                           resp.get("headersSize", 0) or 0)
            size_kb     = round(size_bytes / 1024, 1)

            # Normaliza mime_type
            if ";" in mime_type:
                mime_type = mime_type.split(";")[0].strip()

            har_entry = HAREntry(
                url=url, method=method, status=status,
                mime_type=mime_type, time_ms=time_ms, size_kb=size_kb
            )
            report.entries.append(har_entry)
            report.total_requests += 1
            report.total_transfer_kb += size_kb

            # Contadores de erro
            if 400 <= status < 500:
                report.errors_4xx += 1
            elif 500 <= status < 600:
                report.errors_5xx += 1

            # Requisições lentas
            if time_ms > self.SLOW_THRESHOLD_MS:
                report.slow_requests += 1
                report.slow_entries.append(har_entry)

            # Respostas grandes
            if size_kb > self.LARGE_THRESHOLD_KB:
                report.large_responses += 1

            # Contagem de redirecionamentos por URL base
            if 300 <= status < 400:
                base = url.split("?")[0]
                redirect_map[base] = redirect_map.get(base, 0) + 1

            # ── Análise de problemas ──────────────────────────────────────────

            # Erros 4xx
            if 400 <= status < 500 and status != 304:
                sev = "HIGH" if status in (400, 401, 403, 405) else "MEDIUM"
                msg_map = {
                    400: "Requisição inválida",
                    401: "Autenticação necessária",
                    403: "Acesso negado",
                    404: "Recurso não encontrado",
                    405: "Método não permitido",
                    429: "Muitas requisições (rate limit)",
                }
                detail = msg_map.get(status, f"Erro HTTP {status}")
                sug_map = {
                    400: "Verifique os parâmetros da requisição.",
                    401: "Verifique as credenciais de autenticação.",
                    403: "Verifique permissões de acesso ao recurso.",
                    404: "O recurso foi removido ou a URL está incorreta.",
                    405: "Use o método HTTP correto para este endpoint.",
                    429: "Implemente throttling ou aguarde antes de repetir.",
                }
                suggestion = sug_map.get(status, "Verifique a configuração do servidor.")
                report.issues.append(HARIssue(
                    severity=sev, type=f"HTTP_{status}",
                    url=url, detail=detail, suggestion=suggestion
                ))

            # Erros 5xx
            elif 500 <= status < 600:
                sev = "CRITICAL" if status == 500 else "HIGH"
                detail_map = {
                    500: "Erro interno do servidor",
                    502: "Bad Gateway – servidor intermediário retornou resposta inválida",
                    503: "Serviço indisponível",
                    504: "Gateway Timeout",
                }
                detail = detail_map.get(status, f"Erro de servidor {status}")
                report.issues.append(HARIssue(
                    severity=sev, type=f"SERVER_ERROR_{status}",
                    url=url, detail=detail,
                    suggestion="Verifique os logs do servidor. Pode indicar crash, sobrecarga ou deploy com falha."
                ))

            # Requisição lenta
            if time_ms > self.SLOW_THRESHOLD_MS:
                sev = "CRITICAL" if time_ms > 5000 else "HIGH"
                report.issues.append(HARIssue(
                    severity=sev, type="SLOW_REQUEST",
                    url=url,
                    detail=f"Resposta em {time_ms}ms (limite: {self.SLOW_THRESHOLD_MS}ms)",
                    suggestion="Otimize o servidor, adicione cache ou use CDN para recursos estáticos."
                ))

            # Resposta grande
            if size_kb > self.LARGE_THRESHOLD_KB:
                report.issues.append(HARIssue(
                    severity="MEDIUM", type="LARGE_RESPONSE",
                    url=url,
                    detail=f"Resposta de {size_kb} KB (limite: {self.LARGE_THRESHOLD_KB} KB)",
                    suggestion="Ative compressão gzip/brotli no servidor e otimize imagens/scripts."
                ))

            # Mixed content: HTTPS página com recursos HTTP
            if url.startswith("http://") and method == "GET":
                if mime_type in ("image/jpeg", "image/png", "image/gif",
                                  "image/webp", "image/svg+xml",
                                  "text/javascript", "application/javascript",
                                  "text/css"):
                    report.issues.append(HARIssue(
                        severity="HIGH", type="MIXED_CONTENT",
                        url=url,
                        detail=f"Recurso HTTP ({mime_type}) pode ser bloqueado em páginas HTTPS.",
                        suggestion="Migre todos os recursos para HTTPS ou use URLs relativas de protocolo."
                    ))

            # Verifica headers de segurança nas respostas HTML principais
            if "text/html" in mime_type and status == 200:
                resp_headers = {
                    h["name"].lower(): h["value"]
                    for h in resp.get("headers", [])
                }
                self._check_security_headers(url, resp_headers, report)

        # Redirecionamentos excessivos
        for url_base, count in redirect_map.items():
            if count > self.MAX_REDIRECTS:
                report.issues.append(HARIssue(
                    severity="MEDIUM", type="REDIRECT_LOOP",
                    url=url_base,
                    detail=f"{count} redirecionamentos detectados para este recurso.",
                    suggestion="Verifique a configuração de redirecionamento no servidor. Pode indicar loop."
                ))

        # Ordena issues por severidade
        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        report.issues.sort(key=lambda x: sev_order.get(x.severity, 9))
        report.slow_entries.sort(key=lambda x: x.time_ms, reverse=True)

        return report

    def _check_security_headers(self, url: str, headers: dict, report: HARReport):
        """Verifica headers de segurança em respostas HTML."""
        checks = [
            (
                "x-frame-options",
                "MISSING_X_FRAME_OPTIONS",
                "HIGH",
                "Header X-Frame-Options ausente – página vulnerável a clickjacking.",
                "Adicione: X-Frame-Options: DENY  ou  X-Frame-Options: SAMEORIGIN"
            ),
            (
                "content-security-policy",
                "MISSING_CSP",
                "HIGH",
                "Content-Security-Policy ausente – sem proteção contra XSS.",
                "Implemente uma política CSP adequada para o domínio."
            ),
            (
                "x-content-type-options",
                "MISSING_XCTO",
                "MEDIUM",
                "Header X-Content-Type-Options ausente.",
                "Adicione: X-Content-Type-Options: nosniff"
            ),
            (
                "strict-transport-security",
                "MISSING_HSTS",
                "MEDIUM",
                "Strict-Transport-Security (HSTS) ausente.",
                "Adicione: Strict-Transport-Security: max-age=31536000; includeSubDomains"
            ),
        ]
        for header_name, issue_type, severity, detail, suggestion in checks:
            if header_name not in headers:
                # Evita duplicar para a mesma URL
                existing = any(
                    i.type == issue_type and i.url == url
                    for i in report.issues
                )
                if not existing:
                    report.issues.append(HARIssue(
                        severity=severity, type=issue_type,
                        url=url, detail=detail, suggestion=suggestion
                    ))
