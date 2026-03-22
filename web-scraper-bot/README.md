# WebAuditBot SES - Sistema de Auditoria Web

Bot configurável para auditar sites: lê HTML completo, detecta falhas com sugestões de correção, gera logs de auditoria, integra com Oracle DB e exporta/importa via ZIP.

## Funcionalidades

| Módulo | Descrição |
|--------|-----------|
| **Scraper** | Lê HTML completo de sites com crawling recursivo configurável |
| **Analisador** | Detecta erros HTTP, acessibilidade, SEO, segurança, performance |
| **Logger** | Logs estruturados JSONL de falhas e auditoria com rotação |
| **Oracle DB** | Persiste sessões, páginas, falhas e snapshots HTML |
| **ZIP Handler** | Importa targets/config de ZIP; exporta relatórios em ZIP |
| **Relatórios** | HTML visual, JSON completo, CSV para Excel |

## Instalação

```bash
cd web-scraper-bot
pip install -r requirements.txt

# Para Oracle DB (opcional):
pip install oracledb
```

## Uso

```bash
# Auditar uma URL
python main.py --targets https://www.exemplo.com.br

# Auditar com profundidade máxima 2 e até 50 páginas
python main.py --targets https://site.com --depth 2 --max-pages 50

# Importar lista de URLs de um ZIP
python main.py --import-zip imports/targets.zip

# Usar configuração customizada
python main.py --config config/minha_config.json --targets https://site.com

# Listar ZIPs disponíveis para importação
python main.py --list-imports

# Consultar falhas críticas no Oracle
python main.py --query-oracle --severity CRITICAL

# Consultar falhas de uma sessão específica
python main.py --query-oracle --session SES-20240322120000-ABCD1234
```

## Configuração (`config/config.json`)

```json
{
  "scraper": {
    "timeout": 30,
    "max_depth": 3,
    "max_pages": 100,
    "delay_between_requests": 1.0
  },
  "oracle": {
    "enabled": true,
    "host": "localhost",
    "port": 1521,
    "service_name": "ORCL",
    "username": "ses_user",
    "password": "senha"
  },
  "targets": [
    "https://site1.com",
    "https://site2.com"
  ]
}
```

## Importação via ZIP

O bot aceita ZIPs contendo:
- `targets.json` — lista de URLs: `["https://url1.com", ...]`
- `targets.txt` — uma URL por linha
- `targets.csv` — coluna `url`
- `config.json` — configuração a mesclar

Coloque ZIPs em `imports/` e use `--import-zip imports/arquivo.zip`.

## Exportação

Cada sessão gera um ZIP em `exports/` contendo:

```
auditoria_<SESSION_ID>_<timestamp>.zip
├── reports/
│   ├── relatorio_<id>.html    ← Relatório visual (abra no navegador)
│   ├── relatorio_<id>.json    ← Dados completos
│   ├── falhas_<id>.csv        ← Falhas (compatível Excel PT-BR)
│   └── paginas_<id>.csv       ← Páginas auditadas
├── logs/
│   └── audit_<id>.jsonl       ← Log de auditoria
├── snapshots/
│   └── *.html                 ← HTML capturado das páginas
├── MANIFESTO.json
└── LEIA-ME.txt
```

## Tipos de Falhas Detectadas

### HTTP
- 4xx/5xx com descrição e sugestão específica por código

### Acessibilidade
- Imagens sem `alt`
- Atributo `lang` ausente no `<html>`

### SEO
- `<title>` ausente ou vazio
- Meta description ausente
- Meta viewport ausente

### Segurança
- Headers ausentes: `X-Frame-Options`, `Content-Security-Policy`, `HSTS`, `X-Content-Type-Options`
- Formulários POST sem token CSRF
- Conteúdo misto HTTP/HTTPS

### Performance
- Páginas lentas (configurável, padrão > 3000ms)
- Páginas grandes (configurável, padrão > 500KB)
- `Cache-Control` ausente

### Qualidade de Código
- Tags HTML depreciadas (`<font>`, `<center>`, etc.)
- Links sem destino válido

## Tabelas Oracle (criadas automaticamente)

```sql
WEB_AUDIT_SESSIONS       -- Sessões de auditoria
WEB_AUDIT_PAGES          -- Páginas auditadas por sessão
WEB_AUDIT_FAILURES       -- Falhas detectadas com sugestões
WEB_AUDIT_HTML_SNAPSHOTS -- Snapshots do HTML capturado
```

## Estrutura do Projeto

```
web-scraper-bot/
├── config/
│   ├── config.json          ← Configuração principal
│   └── error_rules.json     ← Regras e sugestões de correção
├── src/
│   ├── bot.py               ← Orquestrador principal
│   ├── scraper.py           ← Motor de web scraping
│   ├── analyzer.py          ← Analisador de HTML e erros
│   ├── logger.py            ← Sistema de logging e auditoria
│   ├── oracle_connector.py  ← Integração Oracle DB
│   └── zip_handler.py       ← Import/Export ZIP
├── imports/                 ← ZIPs para importação
├── exports/                 ← ZIPs gerados
├── logs/                    ← Arquivos de log
├── reports/                 ← Relatórios gerados
├── main.py                  ← Ponto de entrada
└── requirements.txt
```
