"""
WebAuditBot SES - Interface Web
Servidor Flask com dashboard, upload de arquivos e análise em tempo real.
"""

import json
import os
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (Flask, jsonify, redirect, render_template, request,
                   send_file, url_for, Response, stream_with_context)

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config" / "config.json"
RULES_PATH  = ROOT / "config" / "error_rules.json"
UPLOAD_DIR  = ROOT / "imports"
EXPORT_DIR  = ROOT / "exports"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

# Armazena sessões ativas e seus resultados
_sessions: dict = {}        # session_id → {"status", "progress", "summary", "zip_path"}
_sse_queues: dict = {}       # session_id → Queue de eventos SSE


def _load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    # Força caminhos absolutos
    cfg.setdefault("export", {})
    cfg["export"]["output_dir"]  = str(EXPORT_DIR)
    cfg["export"]["import_dir"]  = str(UPLOAD_DIR)
    cfg["export"]["report_dir"]  = str(ROOT / "reports")
    cfg.setdefault("logging", {})["log_dir"] = str(ROOT / "logs")
    return cfg


def _push_event(session_id: str, event: str, data: dict):
    """Envia evento SSE para o cliente."""
    q = _sse_queues.get(session_id)
    if q:
        q.put({"event": event, "data": data})


def _run_audit(session_id: str, targets: list, import_zip: str = None):
    """Executa auditoria em thread separada."""
    import sys
    sys.path.insert(0, str(ROOT))
    from src.bot import WebAuditBot

    config = _load_config()
    rules  = json.loads(RULES_PATH.read_text(encoding="utf-8"))

    # Configura o bot com limite razoável para interface
    config["scraper"]["max_depth"]  = config["scraper"].get("max_depth", 2)
    config["scraper"]["max_pages"]  = min(config["scraper"].get("max_pages", 50), 50)
    config["scraper"]["delay_between_requests"] = 0.5

    _sessions[session_id]["status"] = "running"
    _push_event(session_id, "start", {
        "session_id": session_id,
        "targets": targets,
        "message": f"Iniciando análise de {len(targets)} alvo(s)..."
    })

    # Monkey-patch logger para enviar eventos SSE em tempo real
    bot = WebAuditBot(config, rules)
    original_log_page = bot.logger.log_page_audit

    def patched_log_page(url, status_code, response_time_ms, html_size_bytes,
                         errors_found, warnings_found, page_title=None):
        original_log_page(url, status_code, response_time_ms, html_size_bytes,
                          errors_found, warnings_found, page_title)
        _push_event(session_id, "page", {
            "url": url[:80],
            "status": status_code,
            "time_ms": round(response_time_ms),
            "errors": errors_found,
            "warnings": warnings_found,
            "title": page_title or ""
        })

    bot.logger.log_page_audit = patched_log_page
    bot.initialize()

    try:
        summary = bot.run(targets=targets, import_zip=import_zip)
        _sessions[session_id].update({
            "status": "done",
            "summary": summary,
            "zip_path": summary.get("zip_export"),
            "failures": bot.get_failures(),
            "pages": bot.get_pages(),
        })
        _push_event(session_id, "done", summary)
    except Exception as e:
        _sessions[session_id]["status"] = "error"
        _sessions[session_id]["error"] = str(e)
        _push_event(session_id, "error", {"message": str(e)})
    finally:
        bot.shutdown()
        # Sinaliza fim do stream SSE
        q = _sse_queues.get(session_id)
        if q:
            q.put(None)


# ─── Rotas da Interface ───────────────────────────────────────────────────────

@app.route("/")
def index():
    """Dashboard principal."""
    sessions_list = []
    for sid, s in _sessions.items():
        sessions_list.append({
            "id": sid,
            "status": s.get("status", "?"),
            "targets": s.get("targets", []),
            "summary": s.get("summary", {}),
            "zip_path": s.get("zip_path")
        })
    sessions_list.sort(key=lambda x: x["id"], reverse=True)
    return render_template("index.html", sessions=sessions_list[:20])


@app.route("/analyze", methods=["GET", "POST"])
def analyze():
    """Formulário para iniciar análise."""
    if request.method == "GET":
        return render_template("analyze.html")

    targets = []
    import_zip_path = None

    # URLs digitadas manualmente
    urls_raw = request.form.get("urls", "").strip()
    if urls_raw:
        for line in urls_raw.splitlines():
            url = line.strip()
            if url.startswith(("http://", "https://")):
                targets.append(url)

    # Upload de arquivo ZIP / XML / TXT / CSV
    uploaded = request.files.get("file")
    if uploaded and uploaded.filename:
        fname = uploaded.filename.lower()
        safe_name = f"{uuid.uuid4().hex}_{uploaded.filename}"
        save_path = UPLOAD_DIR / safe_name

        if fname.endswith(".zip"):
            uploaded.save(str(save_path))
            import_zip_path = str(save_path)
        elif fname.endswith(".txt"):
            content = uploaded.read().decode("utf-8", errors="replace")
            for line in content.splitlines():
                line = line.strip()
                if line.startswith(("http://", "https://")):
                    targets.append(line)
        elif fname.endswith(".xml"):
            import sys
            sys.path.insert(0, str(ROOT))
            from src.zip_handler import ZipImporter
            import zipfile, io as _io

            xml_bytes = uploaded.read()
            # Cria ZIP temporário com o XML para reutilizar o importer
            buf = _io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("targets.xml", xml_bytes)
            buf.seek(0)
            save_path.write_bytes(buf.getvalue())
            import_zip_path = str(save_path)
        elif fname.endswith(".csv"):
            import csv as _csv, io as _io
            content = uploaded.read().decode("utf-8-sig", errors="replace")
            reader = _csv.DictReader(_io.StringIO(content))
            for row in reader:
                url = row.get("url") or row.get("URL") or row.get("href") or ""
                if url.startswith(("http://", "https://")):
                    targets.append(url)
        elif fname.endswith(".json"):
            content = uploaded.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    for item in data:
                        u = item if isinstance(item, str) else item.get("url", "")
                        if u.startswith(("http://", "https://")):
                            targets.append(u)
            except Exception:
                pass

    if not targets and not import_zip_path:
        return render_template("analyze.html", error="Informe ao menos uma URL ou faça upload de um arquivo.")

    # Cria sessão e inicia thread
    session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6].upper()
    _sessions[session_id] = {
        "status": "starting",
        "targets": targets,
        "summary": {},
        "zip_path": None,
    }
    _sse_queues[session_id] = queue.Queue()

    thread = threading.Thread(
        target=_run_audit,
        args=(session_id, targets, import_zip_path),
        daemon=True
    )
    thread.start()

    return redirect(url_for("progress_page", session_id=session_id))


@app.route("/progress/<session_id>")
def progress_page(session_id):
    """Página de progresso em tempo real."""
    session = _sessions.get(session_id)
    if not session:
        return redirect(url_for("index"))
    return render_template("progress.html", session_id=session_id, targets=session.get("targets", []))


@app.route("/stream/<session_id>")
def sse_stream(session_id):
    """Server-Sent Events: envia eventos de progresso em tempo real."""
    def generate():
        q = _sse_queues.get(session_id)
        if not q:
            yield "data: {}\n\n"
            return
        while True:
            try:
                item = q.get(timeout=30)
                if item is None:  # Fim da análise
                    break
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
            except Exception:
                break
        yield "event: close\ndata: {}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@app.route("/results/<session_id>")
def results(session_id):
    """Página de resultados detalhados."""
    session = _sessions.get(session_id)
    if not session:
        return redirect(url_for("index"))
    failures = session.get("failures", [])
    pages    = session.get("pages", [])
    summary  = session.get("summary", {})

    # Agrupa falhas por categoria
    by_cat = {}
    for f in failures:
        cat = f.get("category", "OTHER")
        by_cat.setdefault(cat, []).append(f)

    return render_template(
        "results.html",
        session_id=session_id,
        summary=summary,
        failures=failures,
        pages=pages,
        by_category=by_cat,
        zip_available=bool(session.get("zip_path"))
    )


@app.route("/download/<session_id>")
def download(session_id):
    """Download do ZIP de relatório."""
    session = _sessions.get(session_id)
    if not session or not session.get("zip_path"):
        return "Relatório não disponível.", 404
    zip_path = Path(session["zip_path"])
    if not zip_path.exists():
        return "Arquivo não encontrado.", 404
    return send_file(str(zip_path), as_attachment=True, download_name=zip_path.name)


@app.route("/har", methods=["GET", "POST"])
def har_upload():
    """Upload e análise de logs HAR de navegadores."""
    if request.method == "GET":
        return render_template("har.html")

    uploaded = request.files.get("har_file")
    if not uploaded or not uploaded.filename.endswith(".har"):
        return render_template("har.html", error="Faça upload de um arquivo .har exportado pelo navegador.")

    try:
        import sys
        sys.path.insert(0, str(ROOT))
        from src.har_analyzer import HARAnalyzer

        har_data = json.loads(uploaded.read().decode("utf-8", errors="replace"))
        analyzer = HARAnalyzer()
        report   = analyzer.analyze(har_data)
        return render_template("har_results.html", report=report, filename=uploaded.filename)
    except Exception as e:
        return render_template("har.html", error=f"Erro ao processar HAR: {e}")


@app.route("/api/status/<session_id>")
def api_status(session_id):
    """API JSON com status da sessão (para polling em browsers antigos)."""
    session = _sessions.get(session_id)
    if not session:
        return jsonify({"error": "Sessão não encontrada"}), 404
    return jsonify({
        "status": session.get("status"),
        "summary": session.get("summary", {}),
        "pages_count": len(session.get("pages", [])),
        "failures_count": len(session.get("failures", [])),
        "zip_available": bool(session.get("zip_path"))
    })


if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*55}")
    print("  WebAuditBot SES - Interface Web")
    print(f"  Acesse: http://127.0.0.1:{port}")
    print(f"{'='*55}\n")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
