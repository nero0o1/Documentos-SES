"""
Conector Oracle DB
Persiste e recupera dados de auditoria no banco Oracle.
Cria tabelas automaticamente se não existirem.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

try:
    import oracledb
    ORACLE_AVAILABLE = True
except ImportError:
    ORACLE_AVAILABLE = False


# DDL das tabelas
CREATE_TABLES_DDL = [
    """
    CREATE TABLE WEB_AUDIT_SESSIONS (
        SESSION_ID      VARCHAR2(64)   NOT NULL,
        STARTED_AT      TIMESTAMP      NOT NULL,
        FINISHED_AT     TIMESTAMP,
        TARGETS         CLOB,
        TOTAL_PAGES     NUMBER(10)     DEFAULT 0,
        TOTAL_ERRORS    NUMBER(10)     DEFAULT 0,
        TOTAL_WARNINGS  NUMBER(10)     DEFAULT 0,
        STATUS          VARCHAR2(20)   DEFAULT 'RUNNING',
        CREATED_AT      TIMESTAMP      DEFAULT SYSTIMESTAMP,
        CONSTRAINT PK_WEB_AUDIT_SESSIONS PRIMARY KEY (SESSION_ID)
    )
    """,
    """
    CREATE TABLE WEB_AUDIT_PAGES (
        ID              NUMBER         GENERATED ALWAYS AS IDENTITY,
        SESSION_ID      VARCHAR2(64)   NOT NULL,
        URL             VARCHAR2(2000) NOT NULL,
        FINAL_URL       VARCHAR2(2000),
        STATUS_CODE     NUMBER(5),
        RESPONSE_MS     NUMBER(10),
        HTML_SIZE_KB    NUMBER(10),
        PAGE_TITLE      VARCHAR2(500),
        ERRORS_FOUND    NUMBER(10)     DEFAULT 0,
        WARNINGS_FOUND  NUMBER(10)     DEFAULT 0,
        AUDITED_AT      TIMESTAMP      DEFAULT SYSTIMESTAMP,
        CONSTRAINT PK_WEB_AUDIT_PAGES PRIMARY KEY (ID),
        CONSTRAINT FK_PAGES_SESSION FOREIGN KEY (SESSION_ID)
            REFERENCES WEB_AUDIT_SESSIONS(SESSION_ID)
    )
    """,
    """
    CREATE TABLE WEB_AUDIT_FAILURES (
        ID              NUMBER         GENERATED ALWAYS AS IDENTITY,
        SESSION_ID      VARCHAR2(64)   NOT NULL,
        URL             VARCHAR2(2000) NOT NULL,
        ERROR_TYPE      VARCHAR2(100),
        ERROR_CODE      VARCHAR2(50),
        DESCRIPTION     VARCHAR2(2000),
        SUGGESTION      CLOB,
        SEVERITY        VARCHAR2(20),
        CATEGORY        VARCHAR2(50),
        PAGE_TITLE      VARCHAR2(500),
        ELEMENT         VARCHAR2(500),
        EXTRA_DATA      CLOB,
        DETECTED_AT     TIMESTAMP      DEFAULT SYSTIMESTAMP,
        CONSTRAINT PK_WEB_AUDIT_FAILURES PRIMARY KEY (ID),
        CONSTRAINT FK_FAILURES_SESSION FOREIGN KEY (SESSION_ID)
            REFERENCES WEB_AUDIT_SESSIONS(SESSION_ID)
    )
    """,
    """
    CREATE TABLE WEB_AUDIT_HTML_SNAPSHOTS (
        ID              NUMBER         GENERATED ALWAYS AS IDENTITY,
        SESSION_ID      VARCHAR2(64)   NOT NULL,
        URL             VARCHAR2(2000) NOT NULL,
        HTML_CONTENT    CLOB,
        HTML_HASH       VARCHAR2(64),
        CAPTURED_AT     TIMESTAMP      DEFAULT SYSTIMESTAMP,
        CONSTRAINT PK_WEB_AUDIT_SNAPSHOTS PRIMARY KEY (ID)
    )
    """,
    "CREATE INDEX IDX_PAGES_SESSION ON WEB_AUDIT_PAGES (SESSION_ID)",
    "CREATE INDEX IDX_FAILURES_SESSION ON WEB_AUDIT_FAILURES (SESSION_ID)",
    "CREATE INDEX IDX_FAILURES_SEVERITY ON WEB_AUDIT_FAILURES (SEVERITY)",
    "CREATE INDEX IDX_FAILURES_CATEGORY ON WEB_AUDIT_FAILURES (CATEGORY)",
]


class OracleConnector:
    """Gerencia conexão e operações no banco Oracle."""

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        self.pool = None
        self._enabled = config.get("enabled", False)

        if self._enabled and not ORACLE_AVAILABLE:
            self.logger.error(
                "Oracle habilitado mas 'oracledb' não instalado. "
                "Execute: pip install oracledb"
            )
            self._enabled = False

    def connect(self) -> bool:
        """Inicializa connection pool Oracle."""
        if not self._enabled:
            self.logger.info("Oracle desabilitado na configuração.")
            return False

        try:
            dsn = oracledb.makedsn(
                host=self.config["host"],
                port=self.config.get("port", 1521),
                service_name=self.config.get("service_name", "ORCL")
            )
            self.pool = oracledb.create_pool(
                user=self.config["username"],
                password=self.config["password"],
                dsn=dsn,
                min=self.config.get("pool_min", 2),
                max=self.config.get("pool_max", 10),
                increment=self.config.get("pool_increment", 1)
            )
            self.logger.info(
                f"Conectado ao Oracle: {self.config['host']}:{self.config.get('port', 1521)}"
            )
            if self.config.get("auto_create_tables", True):
                self._create_tables_if_not_exist()
            return True
        except Exception as e:
            self.logger.error(f"Falha ao conectar Oracle: {e}", exc_info=True)
            self._enabled = False
            return False

    def disconnect(self):
        if self.pool:
            try:
                self.pool.close()
                self.logger.info("Conexão Oracle encerrada.")
            except Exception as e:
                self.logger.error(f"Erro ao fechar pool Oracle: {e}")

    def _create_tables_if_not_exist(self):
        """Cria tabelas se não existirem."""
        if not self.pool:
            return
        conn = self.pool.acquire()
        try:
            cursor = conn.cursor()
            # Verifica tabelas existentes
            cursor.execute(
                "SELECT TABLE_NAME FROM USER_TABLES WHERE TABLE_NAME LIKE 'WEB_AUDIT_%'"
            )
            existing = {row[0] for row in cursor.fetchall()}

            for ddl in CREATE_TABLES_DDL:
                table_match = None
                for keyword in ["CREATE TABLE ", "CREATE INDEX "]:
                    if keyword in ddl:
                        parts = ddl.strip().split(keyword)
                        if len(parts) > 1:
                            table_match = parts[1].split()[0].split("(")[0].strip()
                        break

                # Pula se já existe
                if table_match and table_match in existing:
                    continue
                if table_match and table_match.startswith("IDX_"):
                    # Verifica índices
                    cursor.execute(
                        "SELECT INDEX_NAME FROM USER_INDEXES WHERE INDEX_NAME = :name",
                        name=table_match
                    )
                    if cursor.fetchone():
                        continue

                try:
                    cursor.execute(ddl)
                    self.logger.info(f"Criado: {table_match or 'objeto DB'}")
                except Exception as e:
                    if "ORA-00955" not in str(e) and "ORA-01408" not in str(e):
                        self.logger.warning(f"DDL ignorado: {e}")

            conn.commit()
            self.logger.info("Estrutura do banco Oracle verificada/criada.")
        except Exception as e:
            self.logger.error(f"Erro ao criar tabelas Oracle: {e}", exc_info=True)
        finally:
            self.pool.release(conn)

    def save_session(self, session_id: str, targets: List[str]) -> bool:
        if not self._enabled or not self.pool:
            return False
        conn = self.pool.acquire()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO WEB_AUDIT_SESSIONS
                   (SESSION_ID, STARTED_AT, TARGETS, STATUS)
                   VALUES (:sid, SYSTIMESTAMP, :targets, 'RUNNING')""",
                sid=session_id,
                targets=json.dumps(targets, ensure_ascii=False)
            )
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Erro ao salvar sessão Oracle: {e}")
            return False
        finally:
            self.pool.release(conn)

    def update_session(self, session_id: str, summary: Dict) -> bool:
        if not self._enabled or not self.pool:
            return False
        conn = self.pool.acquire()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE WEB_AUDIT_SESSIONS SET
                   FINISHED_AT = SYSTIMESTAMP,
                   TOTAL_PAGES = :pages,
                   TOTAL_ERRORS = :errors,
                   TOTAL_WARNINGS = :warnings,
                   STATUS = 'COMPLETED'
                   WHERE SESSION_ID = :sid""",
                pages=summary.get("pages_analyzed", 0),
                errors=summary.get("total_errors", 0),
                warnings=summary.get("total_warnings", 0),
                sid=session_id
            )
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Erro ao atualizar sessão Oracle: {e}")
            return False
        finally:
            self.pool.release(conn)

    def save_page(self, session_id: str, page_data: Dict) -> bool:
        if not self._enabled or not self.pool:
            return False
        conn = self.pool.acquire()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO WEB_AUDIT_PAGES
                   (SESSION_ID, URL, FINAL_URL, STATUS_CODE, RESPONSE_MS,
                    HTML_SIZE_KB, PAGE_TITLE, ERRORS_FOUND, WARNINGS_FOUND)
                   VALUES (:sid, :url, :final_url, :status_code, :response_ms,
                           :html_size_kb, :page_title, :errors, :warnings)""",
                sid=session_id,
                url=page_data.get("url", "")[:2000],
                final_url=page_data.get("final_url", "")[:2000],
                status_code=page_data.get("status_code"),
                response_ms=page_data.get("response_time_ms"),
                html_size_kb=page_data.get("html_size_kb"),
                page_title=str(page_data.get("page_title") or "")[:500],
                errors=page_data.get("errors_found", 0),
                warnings=page_data.get("warnings_found", 0)
            )
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Erro ao salvar página Oracle: {e}")
            return False
        finally:
            self.pool.release(conn)

    def save_failures_batch(self, session_id: str, failures: List[Dict]) -> bool:
        if not self._enabled or not self.pool or not failures:
            return False

        batch_size = self.config.get("batch_insert_size", 100)
        conn = self.pool.acquire()
        try:
            cursor = conn.cursor()
            for i in range(0, len(failures), batch_size):
                batch = failures[i:i + batch_size]
                data = [
                    (
                        session_id,
                        f.get("url", "")[:2000],
                        f.get("error_type", "")[:100],
                        f.get("error_code", "")[:50],
                        f.get("description", "")[:2000],
                        f.get("suggestion", ""),
                        f.get("severity", "")[:20],
                        f.get("category", "")[:50],
                        str(f.get("page_title") or "")[:500],
                        str(f.get("element") or "")[:500],
                        json.dumps(f.get("extra", {}), ensure_ascii=False)
                    )
                    for f in batch
                ]
                cursor.executemany(
                    """INSERT INTO WEB_AUDIT_FAILURES
                       (SESSION_ID, URL, ERROR_TYPE, ERROR_CODE, DESCRIPTION,
                        SUGGESTION, SEVERITY, CATEGORY, PAGE_TITLE, ELEMENT, EXTRA_DATA)
                       VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11)""",
                    data
                )
            conn.commit()
            self.logger.info(f"Salvas {len(failures)} falhas no Oracle.")
            return True
        except Exception as e:
            self.logger.error(f"Erro ao salvar falhas Oracle: {e}")
            return False
        finally:
            self.pool.release(conn)

    def save_html_snapshot(self, session_id: str, url: str, html: str, html_hash: str) -> bool:
        if not self._enabled or not self.pool:
            return False
        conn = self.pool.acquire()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO WEB_AUDIT_HTML_SNAPSHOTS
                   (SESSION_ID, URL, HTML_CONTENT, HTML_HASH)
                   VALUES (:sid, :url, :html, :hash)""",
                sid=session_id,
                url=url[:2000],
                html=html,
                hash=html_hash[:64]
            )
            conn.commit()
            return True
        except Exception as e:
            self.logger.error(f"Erro ao salvar snapshot HTML Oracle: {e}")
            return False
        finally:
            self.pool.release(conn)

    def query_failures(
        self,
        session_id: Optional[str] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 1000
    ) -> List[Dict]:
        """Consulta falhas no Oracle com filtros opcionais."""
        if not self._enabled or not self.pool:
            return []

        conditions = []
        params = {}
        if session_id:
            conditions.append("SESSION_ID = :sid")
            params["sid"] = session_id
        if severity:
            conditions.append("SEVERITY = :sev")
            params["sev"] = severity.upper()
        if category:
            conditions.append("CATEGORY = :cat")
            params["cat"] = category.upper()

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT SESSION_ID, URL, ERROR_TYPE, ERROR_CODE, DESCRIPTION,
                   SUGGESTION, SEVERITY, CATEGORY, PAGE_TITLE, DETECTED_AT
            FROM WEB_AUDIT_FAILURES
            {where}
            ORDER BY DETECTED_AT DESC
            FETCH FIRST :lim ROWS ONLY
        """
        params["lim"] = limit

        conn = self.pool.acquire()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, **params)
            columns = [col[0].lower() for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            self.logger.error(f"Erro ao consultar falhas Oracle: {e}")
            return []
        finally:
            self.pool.release(conn)

    def is_connected(self) -> bool:
        return self._enabled and self.pool is not None
