"""
Servidor Flask de Testes - Simula falhas reais de interface e instabilidade.
Levanta um servidor HTTP local que retorna cenários controlados de erro.

Rotas disponíveis:
  /ok              → Página HTML válida e completa
  /sem-title       → HTML sem <title>
  /sem-alt         → Imagens sem alt
  /sem-csrf        → Form POST sem token CSRF
  /mixed-content   → Conteúdo misto HTTP em página HTTPS simulada
  /depreciado      → Tags HTML depreciadas
  /lento           → Resposta demorada (simula lentidão)
  /erro-500        → Internal Server Error
  /erro-404        → Not Found
  /erro-403        → Forbidden
  /erro-503        → Service Unavailable
  /sem-headers     → Página sem headers de segurança
  /instavel        → Falha aleatória (simula instabilidade)
  /redirect-loop   → Redirecionamento que quebra
  /vazio           → Resposta vazia (sem body)
  /html-corrompido → HTML malformado
"""

import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# ─── HTMLs de teste ──────────────────────────────────────────────────────────

PAGES = {
    "/ok": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'",
            "Cache-Control": "no-cache",
        },
        "body": """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Página de teste válida para auditoria.">
  <title>Página OK - Teste</title>
</head>
<body>
  <h1>Página funcionando corretamente</h1>
  <img src="/logo.png" alt="Logo do sistema">
  <form method="POST" action="/enviar">
    <input type="hidden" name="csrf_token" value="tok_abc123">
    <input type="text" name="nome">
    <button type="submit">Enviar</button>
  </form>
  <a href="/ok">Link válido</a>
</body>
</html>""",
    },

    "/sem-title": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body><h1>Sem título</h1></body>
</html>""",
    },

    "/sem-alt": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<!DOCTYPE html>
<html>
<head><title>Imagens sem ALT</title></head>
<body>
  <img src="foto1.jpg">
  <img src="foto2.jpg">
  <img src="logo.png">
  <img src="banner.gif" alt="Banner com alt correto">
</body>
</html>""",
    },

    "/sem-csrf": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Formulário sem CSRF</title></head>
<body>
  <form method="POST" action="/login">
    <input type="text" name="usuario">
    <input type="password" name="senha">
    <button type="submit">Entrar</button>
  </form>
  <form method="POST" action="/cadastro">
    <input type="text" name="nome">
    <input type="email" name="email">
    <button>Cadastrar</button>
  </form>
</body>
</html>""",
    },

    "/mixed-content": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <title>Conteúdo Misto</title>
  <script src="http://cdn.externo.com/jquery.min.js"></script>
  <link rel="stylesheet" href="http://fonts.googleapis.com/css?family=Roboto">
</head>
<body>
  <img src="http://imagens.externas.com/foto.jpg" alt="Foto externa HTTP">
  <iframe src="http://widget.externo.com/embed"></iframe>
</body>
</html>""",
    },

    "/depreciado": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<!DOCTYPE html>
<html>
<head><title>Tags Depreciadas</title></head>
<body>
  <center><h1>Título centralizado</h1></center>
  <font color="red" size="5">Texto vermelho</font>
  <marquee>Texto animado depreciado</marquee>
  <blink>Texto piscando</blink>
  <strike>Texto riscado</strike>
  <tt>Texto monoespaçado depreciado</tt>
</body>
</html>""",
    },

    "/lento": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "delay": 4.0,
        "headers": {},
        "body": """<!DOCTYPE html>
<html lang="pt-BR">
<head><title>Página Lenta</title></head>
<body><h1>Carregou depois de 4 segundos</h1></body>
</html>""",
    },

    "/erro-500": {
        "status": 500,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<!DOCTYPE html>
<html>
<head><title>500 - Erro Interno</title></head>
<body>
  <h1>500 Internal Server Error</h1>
  <p>java.lang.NullPointerException at line 42 of UserController.java</p>
</body>
</html>""",
    },

    "/erro-404": {
        "status": 404,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": "<html><body><h1>404 Not Found</h1></body></html>",
    },

    "/erro-403": {
        "status": 403,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": "<html><body><h1>403 Forbidden</h1></body></html>",
    },

    "/erro-503": {
        "status": 503,
        "content_type": "text/html; charset=utf-8",
        "headers": {"Retry-After": "30"},
        "body": "<html><body><h1>503 Service Unavailable</h1></body></html>",
    },

    "/sem-headers": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <title>Sem Headers de Segurança</title>
  <meta name="description" content="Página sem X-Frame-Options, CSP, HSTS.">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body><h1>Headers de segurança ausentes</h1></body>
</html>""",
    },

    "/vazio": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": "",
    },

    "/html-corrompido": {
        "status": 200,
        "content_type": "text/html; charset=utf-8",
        "headers": {},
        "body": """<html><head><titl>Corrompido<body>
<div><p>Parágrafo sem fechar
<img src= alt="">
<form method=POST
<input type=text name=campo
</div></html""",
    },

    # ── Rotas XML ─────────────────────────────────────────────────────────────

    "/xml-valido": {
        "status": 200,
        "content_type": "application/xml; charset=utf-8",
        "headers": {},
        "body": """<?xml version="1.0" encoding="UTF-8"?>
<catalogo xmlns="http://ses.gov.br/catalogo">
  <item id="1">
    <nome>Produto A</nome>
    <preco moeda="BRL">29.90</preco>
  </item>
  <item id="2">
    <nome>Produto B</nome>
    <preco moeda="BRL">49.90</preco>
  </item>
</catalogo>""",
    },

    "/xml-tag-nao-fechada": {
        "status": 200,
        "content_type": "application/xml; charset=utf-8",
        "headers": {},
        "body": """<?xml version="1.0" encoding="UTF-8"?>
<relatorio>
  <item>
    <nome>Registro 1</nome>
    <valor>100
  </item>
  <item>
    <nome>Registro 2
  </item>
</relatorio>""",
    },

    "/xml-entidade-invalida": {
        "status": 200,
        "content_type": "application/xml; charset=utf-8",
        "headers": {},
        "body": """<?xml version="1.0" encoding="UTF-8"?>
<pagina>
  <descricao>Produto com preco em R&amp; e simbolo &copy; e espaco&nbsp;aqui</descricao>
  <titulo>Titulo &mdash; com travessao</titulo>
</pagina>""",
    },

    "/xml-declaracao-invalida": {
        "status": 200,
        "content_type": "application/xml; charset=utf-8",
        "headers": {},
        "body": """<?xml versao="1.0" encode="latin"?>
<dados>
  <campo>valor</campo>
</dados>""",
    },

    "/xml-namespace-nao-declarado": {
        "status": 200,
        "content_type": "application/xml; charset=utf-8",
        "headers": {},
        "body": """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope>
  <soap:Body>
    <ns2:resposta>
      <ns2:codigo>200</ns2:codigo>
    </ns2:resposta>
  </soap:Body>
</soap:Envelope>""",
    },

    "/xhtml-invalido": {
        "status": 200,
        "content_type": "application/xhtml+xml; charset=utf-8",
        "headers": {},
        "body": """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="pt-BR">
<head><title>XHTML Invalido</title></head>
<body>
  <br>
  <img src="foto.jpg">
  <p>Paragrafo sem fechar
</body>""",
    },

    "/xml-atributo-duplicado": {
        "status": 200,
        "content_type": "application/xml; charset=utf-8",
        "headers": {},
        "body": """<?xml version="1.0" encoding="UTF-8"?>
<produtos>
  <item id="1" nome="A" id="2">
    <descricao>Produto com id duplicado</descricao>
  </item>
</produtos>""",
    },
}

# Contador para instabilidade alternada
_instavel_counter = [0]


class TestServerHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # Silencia logs do servidor durante testes

    def do_GET(self):
        path = self.path.split("?")[0]

        # Rota de instabilidade: falha a cada 2 requisições
        if path == "/instavel":
            _instavel_counter[0] += 1
            if _instavel_counter[0] % 2 == 0:
                self.send_response(503)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>503 Instavel</h1></body></html>")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html lang='pt-BR'><head><title>Instavel OK</title></head>"
                    b"<body><h1>Respondeu desta vez</h1></body></html>"
                )
            return

        page = PAGES.get(path)
        if not page:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>404 - Rota de teste nao encontrada</h1></body></html>")
            return

        # Delay simulado
        if page.get("delay"):
            time.sleep(page["delay"])

        self.send_response(page["status"])
        self.send_header("Content-Type", page["content_type"])
        for k, v in page.get("headers", {}).items():
            self.send_header(k, v)
        body = page["body"].encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestServer:
    """Gerencia o servidor HTTP de testes em thread separada."""

    def __init__(self, host: str = "127.0.0.1", port: int = 18080):
        self.host = host
        self.port = port
        self._server: HTTPServer = None
        self._thread: threading.Thread = None

    def start(self):
        self._server = HTTPServer((self.host, self.port), TestServerHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()

    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def get_all_routes(self) -> dict:
        return {
            route: {
                "status": data["status"],
                "delay": data.get("delay", 0),
                "description": _route_description(route)
            }
            for route, data in PAGES.items()
        }


def _route_description(route: str) -> str:
    descriptions = {
        "/ok": "Página válida e completa (sem erros esperados)",
        "/sem-title": "HTML sem tag <title>",
        "/sem-alt": "Imagens sem atributo alt",
        "/sem-csrf": "Formulários POST sem token CSRF",
        "/mixed-content": "Recursos HTTP em página HTTPS",
        "/depreciado": "Tags HTML depreciadas",
        "/lento": "Resposta com delay de 4s (lentidão)",
        "/erro-500": "Internal Server Error",
        "/erro-404": "Not Found",
        "/erro-403": "Forbidden",
        "/erro-503": "Service Unavailable",
        "/sem-headers": "Sem headers de segurança",
        "/instavel": "Alterna entre 200 e 503",
        "/vazio": "Body vazio",
        "/html-corrompido": "HTML malformado",
        "/xml-valido": "XML válido e bem formado",
        "/xml-tag-nao-fechada": "XML com tag não fechada",
        "/xml-entidade-invalida": "XML com entidades HTML inválidas (&copy; &nbsp; &mdash;)",
        "/xml-declaracao-invalida": "XML com declaração <?xml> inválida",
        "/xml-namespace-nao-declarado": "XML com namespaces (soap:, ns2:) não declarados",
        "/xhtml-invalido": "XHTML servido como application/xhtml+xml mas inválido",
        "/xml-atributo-duplicado": "XML com atributo id duplicado na mesma tag",
    }
    return descriptions.get(route, route)
