"""
backend/integrations/snowflake_client.py
Handles all persistence: Snowflake primary, SQLite fallback.
All public write methods are designed to be called as FastAPI BackgroundTasks.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

from backend.config import settings
from backend.models.schemas import AuditLogEntry, SimilarityAlert

logger = logging.getLogger(__name__)

# ── SQL Definitions ──────────────────────────────────────────────────────────
_CREATE_TEAMS = """
CREATE TABLE IF NOT EXISTS teams (
    team_id    VARCHAR PRIMARY KEY,
    team_name  VARCHAR,
    github_url VARCHAR,
    registered_at TIMESTAMP,
    blind_alias VARCHAR
)"""

_CREATE_EVALUATIONS = """
CREATE TABLE IF NOT EXISTS evaluations (
    eval_id    VARCHAR PRIMARY KEY,
    team_id    VARCHAR,
    agent_name VARCHAR,
    criterion  VARCHAR,
    score      INTEGER,
    rationale  TEXT,
    disputed   BOOLEAN,
    created_at TIMESTAMP
)"""

_CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    log_id       VARCHAR PRIMARY KEY,
    event_type   VARCHAR,
    team_id      VARCHAR,
    agent_name   VARCHAR,
    raw_prompt   TEXT,
    raw_response TEXT,
    created_at   TIMESTAMP
)"""

_CREATE_SIMILARITY_ALERTS = """
CREATE TABLE IF NOT EXISTS similarity_alerts (
    alert_id          VARCHAR PRIMARY KEY,
    team_a_id         VARCHAR,
    team_b_id         VARCHAR,
    similarity_score  FLOAT,
    created_at        TIMESTAMP
)"""

ALL_DDL = [_CREATE_TEAMS, _CREATE_EVALUATIONS, _CREATE_AUDIT_LOG, _CREATE_SIMILARITY_ALERTS]


class SnowflakeClient:
    """
    Unified persistence layer.  Uses Snowflake when credentials are available,
    otherwise silently falls back to SQLite.
    """

    def __init__(self):
        self._use_snowflake = settings.snowflake_available
        self._sf_conn = None
        self._sqlite_path = settings.sqlite_fallback_path

        if self._use_snowflake:
            self._init_snowflake()
        else:
            logger.warning("Snowflake credentials missing — using SQLite fallback at %s", self._sqlite_path)
            self._init_sqlite()

    # ── Snowflake setup ───────────────────────────────────────────────────────
    def _init_snowflake(self):
        try:
            import snowflake.connector
            self._sf_conn = snowflake.connector.connect(
                account=settings.snowflake_account,
                user=settings.snowflake_user,
                password=settings.snowflake_password,
                warehouse=settings.snowflake_warehouse,
                database=settings.snowflake_database,
                schema=settings.snowflake_schema,
            )
            self._run_ddl_snowflake()
            logger.info("Snowflake connected to %s", settings.snowflake_account)
        except Exception as exc:
            logger.warning("Snowflake init failed (%s) — falling back to SQLite", exc)
            self._use_snowflake = False
            self._sf_conn = None
            self._init_sqlite()

    def _run_ddl_snowflake(self):
        cur = self._sf_conn.cursor()
        for ddl in ALL_DDL:
            cur.execute(ddl)
        self._sf_conn.commit()
        cur.close()

    # ── SQLite setup ──────────────────────────────────────────────────────────
    def _init_sqlite(self):
        import os
        os.makedirs("data", exist_ok=True)
        with self._sqlite_ctx() as conn:
            for ddl in ALL_DDL:
                conn.execute(ddl)

    @contextmanager
    def _sqlite_ctx(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._sqlite_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Generic execute ───────────────────────────────────────────────────────
    def _execute(self, sql: str, params: tuple = ()):
        """Execute a write statement against the active backend."""
        try:
            if self._use_snowflake and self._sf_conn:
                cur = self._sf_conn.cursor()
                cur.execute(sql, params)
                self._sf_conn.commit()
                cur.close()
            else:
                with self._sqlite_ctx() as conn:
                    conn.execute(sql, params)
        except Exception as exc:
            logger.error("DB write error: %s | SQL: %s", exc, sql[:120])

    def _fetchall(self, sql: str, params: tuple = ()) -> List[Dict]:
        """Execute a SELECT and return list of dicts."""
        try:
            if self._use_snowflake and self._sf_conn:
                cur = self._sf_conn.cursor()
                cur.execute(sql, params)
                cols = [d[0].lower() for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                cur.close()
                return rows
            else:
                with self._sqlite_ctx() as conn:
                    rows = conn.execute(sql, params).fetchall()
                    return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("DB read error: %s", exc)
            return []

    # ── Public write API ──────────────────────────────────────────────────────
    def save_team(self, team_id: str, team_name: str, github_url: str,
                  registered_at: datetime, blind_alias: str):
        self._execute(
            "INSERT INTO teams (team_id, team_name, github_url, registered_at, blind_alias) "
            "VALUES (?, ?, ?, ?, ?)" if not self._use_snowflake else
            "INSERT INTO teams (team_id, team_name, github_url, registered_at, blind_alias) "
            "VALUES (%s, %s, %s, %s, %s)",
            (team_id, team_name, github_url, registered_at.isoformat(), blind_alias),
        )

    def save_evaluation(self, team_id: str, agent_name: str, criterion: str,
                        score: Optional[int], rationale: str, disputed: bool = False):
        ph = "?" if not self._use_snowflake else "%s"
        self._execute(
            f"INSERT INTO evaluations (eval_id, team_id, agent_name, criterion, score, rationale, disputed, created_at) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (str(uuid.uuid4()), team_id, agent_name, criterion, score, rationale, disputed, datetime.utcnow().isoformat()),
        )

    def log_audit(self, event_type: str, team_id: Optional[str], agent_name: Optional[str],
                  raw_prompt: Optional[str], raw_response: Optional[str]):
        ph = "?" if not self._use_snowflake else "%s"
        self._execute(
            f"INSERT INTO audit_log (log_id, event_type, team_id, agent_name, raw_prompt, raw_response, created_at) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (str(uuid.uuid4()), event_type, team_id, agent_name,
             (raw_prompt or "")[:10000], (raw_response or "")[:10000], datetime.utcnow().isoformat()),
        )

    def save_similarity_alert(self, alert: SimilarityAlert):
        ph = "?" if not self._use_snowflake else "%s"
        self._execute(
            f"INSERT INTO similarity_alerts (alert_id, team_a_id, team_b_id, similarity_score, created_at) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph})",
            (alert.alert_id, alert.team_a_id, alert.team_b_id,
             alert.similarity_score, alert.created_at.isoformat()),
        )

    def delete_team(self, team_id: str):
        ph = "?" if not self._use_snowflake else "%s"
        self._execute(f"DELETE FROM teams WHERE team_id = {ph}", (team_id,))
        self._execute(f"DELETE FROM evaluations WHERE team_id = {ph}", (team_id,))

    # ── Public read API ───────────────────────────────────────────────────────
    def get_all_teams(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM teams ORDER BY registered_at")

    def get_team(self, team_id: str) -> Optional[Dict]:
        rows = self._fetchall("SELECT * FROM teams WHERE team_id = ?" if not self._use_snowflake
                              else "SELECT * FROM teams WHERE team_id = %s", (team_id,))
        return rows[0] if rows else None

    def get_evaluations_for_team(self, team_id: str) -> List[Dict]:
        ph = "?" if not self._use_snowflake else "%s"
        return self._fetchall(
            f"SELECT * FROM evaluations WHERE team_id = {ph} ORDER BY created_at", (team_id,)
        )

    def get_audit_log(self, team_id: Optional[str] = None,
                      agent_name: Optional[str] = None,
                      event_type: Optional[str] = None) -> List[Dict]:
        clauses, params = [], []
        ph = "?" if not self._use_snowflake else "%s"
        if team_id:
            clauses.append(f"team_id = {ph}"); params.append(team_id)
        if agent_name:
            clauses.append(f"agent_name = {ph}"); params.append(agent_name)
        if event_type:
            clauses.append(f"event_type = {ph}"); params.append(event_type)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        return self._fetchall(f"SELECT * FROM audit_log {where} ORDER BY created_at DESC LIMIT 500", tuple(params))

    def get_similarity_alerts(self) -> List[Dict]:
        return self._fetchall("SELECT * FROM similarity_alerts ORDER BY similarity_score DESC")

    def close(self):
        if self._sf_conn:
            try:
                self._sf_conn.close()
            except Exception:
                pass
