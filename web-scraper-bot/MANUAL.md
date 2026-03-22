# WebAuditBot SES — Manual de Uso

## Índice

1. [Visão Geral](#visão-geral)
2. [Requisitos do Sistema](#requisitos-do-sistema)
3. [Instalação](#instalação)
4. [Interface Web (Recomendada)](#interface-web-recomendada)
5. [Linha de Comando (CLI)](#linha-de-comando-cli)
6. [Formatos de Entrada](#formatos-de-entrada)
7. [Análise de Logs HAR](#análise-de-logs-har)
8. [Relatórios e Exportação](#relatórios-e-exportação)
9. [Configuração Avançada](#configuração-avançada)
10. [Banco de Dados Oracle](#banco-de-dados-oracle)
11. [Executando os Testes](#executando-os-testes)
12. [Solução de Problemas](#solução-de-problemas)

---

## Visão Geral

O **WebAuditBot SES** é uma ferramenta de auditoria automatizada de sites que:

- Rastreia sites de forma recursiva (crawling) lendo o HTML completo de cada página
- Detecta **20+ tipos de erros**: HTTP, acessibilidade, segurança, performance, XML, formulários e mais
- Gera **logs estruturados** (JSONL) com mapeamento de erros e sugestões de correção
- Exporta relatórios em **ZIP** contendo JSON, HTML (moderno + legado HTML 4.01), CSV e snapshots
- Oferece **interface web amigável** com upload de arquivos e progresso em tempo real
- Analisa **logs HAR** exportados por qualquer navegador
- Integra opcionalmente com **Oracle Database**

---

## Requisitos do Sistema

- **Python 3.8 ou superior**
- Conexão com a internet (para rastrear os sites alvo)
- Aproximadamente 100 MB de espaço em disco para logs e relatórios

### Dependências Python

```
flask>=2.3.0
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
```

---

## Instalação

### Método 1 — Script automático (mais fácil)

**Linux / Mac:**
```bash
chmod +x start.sh
./start.sh
```

**Windows:**
```
Duplo clique em start.bat
```

O script cria automaticamente um ambiente virtual Python, instala as dependências e inicia a interface web.

### Método 2 — Instalação manual

```bash
# 1. Crie e ative ambiente virtual (recomendado)
python3 -m venv .venv
source .venv/bin/activate        # Linux/Mac
.venv\Scripts\activate           # Windows

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Inicie a interface
python run.py
```

---

## Interface Web (Recomendada)

### Iniciando

```bash
python run.py
```

O sistema abre automaticamente o navegador em `http://127.0.0.1:5000`.

Para usar uma porta diferente:
```bash
python run.py --port 8080
```

### Opções do launcher

| Opção          | Descrição                              | Padrão        |
|----------------|----------------------------------------|---------------|
| `--port`       | Porta HTTP                             | `5000`        |
| `--host`       | Endereço de escuta                     | `127.0.0.1`   |
| `--no-browser` | Não abrir navegador automaticamente    | (abre)        |
| `--debug`      | Modo debug Flask (não use em produção) | desativado    |

### Páginas da interface

| Página               | URL                            | Função                                    |
|----------------------|--------------------------------|-------------------------------------------|
| Dashboard            | `/`                            | Lista de sessões recentes                 |
| Nova Análise         | `/analyze`                     | Formulário de entrada de URLs e upload    |
| Progresso            | `/progress/<session_id>`       | Acompanhamento em tempo real (SSE)        |
| Resultados           | `/results/<session_id>`        | Tabela de falhas por categoria            |
| Download ZIP         | `/download/<session_id>`       | Baixar relatório completo                 |
| Logs HAR             | `/har`                         | Upload e análise de arquivos HAR          |
| Status API           | `/api/status/<session_id>`     | JSON de status (para integrações)         |

### Realizando uma análise via interface

1. Acesse **Nova Análise** (`/analyze`)
2. Digite as URLs na caixa de texto **ou** faça upload de um arquivo
3. Clique em **Iniciar Análise**
4. Acompanhe o progresso em tempo real na página de progresso
5. Ao terminar, clique em **Ver Resultados** ou **Baixar ZIP**

---

## Linha de Comando (CLI)

Para uso avançado sem interface gráfica:

```bash
python main.py --targets https://www.example.com https://outro.com
```

### Opções principais

| Opção              | Descrição                                        |
|--------------------|--------------------------------------------------|
| `--targets`        | URLs para analisar (uma ou mais)                 |
| `--import-zip`     | Caminho para ZIP com lista de alvos              |
| `--config`         | Caminho para config.json alternativo             |
| `--depth`          | Profundidade máxima de crawling (padrão: 2)      |
| `--max-pages`      | Limite de páginas por alvo (padrão: 50)          |
| `--no-oracle`      | Desativa integração Oracle mesmo se configurada  |
| `--no-snapshots`   | Não salva snapshots HTML                         |
| `--output-dir`     | Diretório de saída dos relatórios                |

### Exemplos de uso CLI

```bash
# Analisar um único site
python main.py --targets https://portal.ses.gov.br

# Analisar múltiplos sites com limite
python main.py --targets https://site1.com https://site2.com --max-pages 20

# Importar lista de ZIP
python main.py --import-zip imports/alvos.zip

# Consultar falhas no Oracle
python main.py --query-oracle --severity CRITICAL

# Listar o que seria importado de um ZIP (sem executar)
python main.py --list-imports --import-zip imports/alvos.zip
```

---

## Formatos de Entrada

O sistema aceita alvos nos seguintes formatos:

### TXT — Uma URL por linha
```
https://www.site1.com
https://www.site2.com
https://portal.ses.gov.br
```

### CSV — Coluna "url", "URL" ou "href"
```csv
url,nome
https://www.site1.com,Site Principal
https://www.site2.com,Portal
```

### JSON — Array de strings ou objetos
```json
["https://www.site1.com", "https://www.site2.com"]
```
```json
[{"url": "https://www.site1.com", "nome": "Site Principal"}]
```

### XML — Tags `<url>` ou atributo `url=`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<urls>
  <url>https://www.site1.com</url>
  <url>https://www.site2.com</url>
</urls>
```
```xml
<?xml version="1.0" encoding="UTF-8"?>
<targets>
  <target url="https://www.site1.com" nome="Site 1"/>
  <target url="https://www.site2.com" nome="Site 2"/>
</targets>
```

### ZIP — Arquivo comprimido
O ZIP pode conter qualquer um dos formatos acima com o nome:
- `targets.json`
- `targets.txt`
- `targets.csv`
- `targets.xml`

---

## Análise de Logs HAR

Os arquivos HAR (HTTP Archive) registram todas as requisições feitas pelo navegador durante uma sessão.

### Como exportar o HAR

**Google Chrome / Microsoft Edge:**
1. Pressione `F12` para abrir as DevTools
2. Clique na aba **Network**
3. Navegue pelo site que deseja analisar
4. Clique com botão direito na lista de requisições → **Save all as HAR with content**

**Mozilla Firefox:**
1. Pressione `F12` → aba **Network**
2. Navegue pelo site
3. Clique no ícone de engrenagem (⚙) → **Save All As HAR**

**Apple Safari:**
1. Preferências → Avançado → Marque "Show Develop menu in menu bar"
2. Menu Develop → Show Web Inspector → aba Network
3. Navegue pelo site
4. File → **Export HAR**

### Análise via interface web

1. Acesse **Logs HAR** no menu superior
2. Faça upload do arquivo `.har`
3. Clique em **Analisar HAR**
4. Veja o relatório com:
   - Total de requisições
   - Erros HTTP (4xx e 5xx)
   - Requisições lentas (>2 segundos)
   - Respostas muito grandes (>500 KB)
   - Headers de segurança ausentes
   - Problemas de Mixed Content

---

## Relatórios e Exportação

Ao final de cada análise, um arquivo ZIP é gerado em `exports/` contendo:

| Arquivo                            | Conteúdo                                              |
|------------------------------------|-------------------------------------------------------|
| `reports/relatorio.json`           | Relatório completo em JSON                            |
| `reports/relatorio_<id>.html`      | Relatório HTML moderno (CSS Grid, cores)              |
| `reports/relatorio_legado_<id>.html` | Relatório HTML 4.01 (tabelas puras, qualquer navegador) |
| `reports/falhas.csv`               | Planilha com todas as falhas detectadas               |
| `reports/paginas.csv`              | Planilha com todas as páginas analisadas              |
| `logs/audit.jsonl`                 | Log completo linha a linha (JSONL)                    |
| `snapshots/*.html`                 | Cópias HTML das páginas analisadas                    |
| `MANIFESTO.json`                   | Metadados do relatório                                |
| `LEIA-ME.txt`                      | Instruções de uso do ZIP                              |

### Relatório legado (HTML 4.01)

O relatório `relatorio_legado_*.html` usa apenas HTML puro com tabelas, sem CSS externo nem JavaScript. Funciona em qualquer navegador, inclusive versões antigas (Internet Explorer 6+, Netscape Navigator, etc.).

---

## Configuração Avançada

O arquivo `config/config.json` controla todos os parâmetros:

### Scraper

```json
"scraper": {
    "max_depth": 2,          // Profundidade de crawling (1=só a página inicial)
    "max_pages": 50,         // Máximo de páginas por alvo
    "timeout": 30,           // Timeout em segundos por requisição
    "max_retries": 3,        // Tentativas em caso de falha
    "delay_between_requests": 1.0,  // Pausa entre requisições (segundos)
    "verify_ssl": true,      // Verificar certificado SSL
    "follow_redirects": true // Seguir redirecionamentos
}
```

### Análises ativadas

```json
"analysis": {
    "check_http_errors": true,
    "check_slow_pages": true,
    "slow_page_threshold_ms": 3000,
    "check_security_headers": true,
    "check_missing_meta": true,
    "check_accessibility": true,
    "check_broken_links": false,
    "check_empty_forms": true,
    "check_mixed_content": true,
    "check_xml": true
}
```

### Logging

```json
"logging": {
    "level": "INFO",           // DEBUG, INFO, WARNING, ERROR
    "log_dir": "logs",
    "audit_log_enabled": true,
    "failure_log_enabled": true,
    "log_rotation": true,
    "max_log_size_mb": 10,
    "backup_count": 5
}
```

---

## Banco de Dados Oracle

A integração Oracle é **opcional**. Para ativá-la:

1. Instale o driver:
   ```bash
   pip install oracledb>=2.0.0
   ```

2. Configure `config/config.json`:
   ```json
   "oracle": {
       "enabled": true,
       "user": "seu_usuario",
       "password": "sua_senha",
       "dsn": "host:1521/ORCL",
       "pool_min": 1,
       "pool_max": 5
   }
   ```

3. O sistema cria automaticamente as tabelas necessárias na primeira execução:
   - `WEBAUDIT_SESSIONS` — Sessões de auditoria
   - `WEBAUDIT_PAGES` — Páginas analisadas
   - `WEBAUDIT_FAILURES` — Falhas detectadas
   - `WEBAUDIT_HTML_SNAPSHOTS` — Snapshots HTML

---

## Executando os Testes

O sistema inclui 60 testes automatizados cobrindo:
- Erros de interface e instabilidade (T01–T20)
- Rejeição de importação de arquivos (T21–T41)
- Validação de erros XML (T42–T60)

```bash
# Executar todos os testes
python tests/run_tests.py

# Executar apenas uma suite
python tests/run_tests.py --suite interface
python tests/run_tests.py --suite import
python tests/run_tests.py --suite xml

# Ver detalhes de falhas
python tests/run_tests.py --verbose
```

Os resultados são salvos em `tests/results/test_report_<timestamp>.json`.

---

## Solução de Problemas

### "ModuleNotFoundError: No module named 'flask'"

```bash
pip install -r requirements.txt
```

### A interface não abre no navegador

Acesse manualmente: `http://127.0.0.1:5000`

Se a porta estiver em uso:
```bash
python run.py --port 8080
```

### Erro de SSL ao analisar sites internos

Desative a verificação SSL no `config/config.json`:
```json
"scraper": { "verify_ssl": false }
```

### Análise muito lenta

Reduza a profundidade e o limite de páginas:
```json
"scraper": {
    "max_depth": 1,
    "max_pages": 10,
    "delay_between_requests": 0.3
}
```

### Logs HAR muito grandes falham no upload

O limite padrão é 50 MB. Para aumentar, edite `web_app.py`:
```python
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB
```

### Oracle: "DPI-1047: Cannot locate a 64-bit Oracle Client library"

Instale o Oracle Instant Client: https://oracle.github.io/node-oracledb/INSTALL.html

---

## Estrutura do Projeto

```
web-scraper-bot/
├── run.py              ← Launcher da interface web
├── start.sh            ← Script de inicialização Linux/Mac
├── start.bat           ← Script de inicialização Windows
├── main.py             ← Interface de linha de comando (CLI)
├── web_app.py          ← Servidor Flask
├── requirements.txt    ← Dependências Python
├── config/
│   ├── config.json     ← Configuração principal
│   └── error_rules.json ← Regras de erros e sugestões
├── src/
│   ├── scraper.py      ← Crawler web
│   ├── analyzer.py     ← Analisador de HTML/XML
│   ├── logger.py       ← Sistema de logs
│   ├── oracle_connector.py ← Integração Oracle
│   ├── zip_handler.py  ← Importação/exportação ZIP
│   ├── har_analyzer.py ← Análise de logs HAR
│   └── bot.py          ← Orquestrador principal
├── templates/          ← Templates HTML da interface web
├── static/             ← CSS, JS e imagens da interface
├── tests/              ← Testes automatizados
│   ├── run_tests.py    ← Runner de testes
│   ├── test_server.py  ← Servidor HTTP de testes
│   ├── fixtures/       ← Arquivos de teste (ZIPs, XMLs)
│   └── results/        ← Relatórios de testes
├── logs/               ← Logs de auditoria (gerado)
├── exports/            ← ZIPs exportados (gerado)
├── imports/            ← Uploads recebidos (gerado)
└── reports/            ← Relatórios avulsos (gerado)
```

---

*WebAuditBot SES — Desenvolvido para auditoria de sistemas web da SES*
