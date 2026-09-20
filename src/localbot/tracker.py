from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

USAGE_DB = Path.home() / ".localbot" / "usage.db"


def _connect() -> sqlite3.Connection:
    USAGE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USAGE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spend_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                model TEXT,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                request_id TEXT
            )
            """
        )
        conn.commit()


def record_event(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    request_id: str | None = None,
) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO spend_events
                (created_at, model, input_tokens, output_tokens, cost_usd, request_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                request_id,
            ),
        )
        conn.commit()


def spend_summary() -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS spend FROM spend_events"
        ).fetchone()["spend"]
        today = conn.execute(
            """
            SELECT COALESCE(SUM(cost_usd), 0) AS spend
            FROM spend_events
            WHERE date(created_at) = date('now')
            """
        ).fetchone()["spend"]
        requests = conn.execute(
            "SELECT COUNT(*) AS count FROM spend_events"
        ).fetchone()["count"]
        top_models = conn.execute(
            """
            SELECT model, SUM(cost_usd) AS spend
            FROM spend_events
            WHERE model IS NOT NULL
            GROUP BY model
            ORDER BY spend DESC
            LIMIT 5
            """
        ).fetchall()

    return {
        "spend_usd": float(total),
        "spend_today_usd": float(today),
        "requests": int(requests),
        "top_models": [(row["model"], float(row["spend"])) for row in top_models],
    }


def _record_from_response(kwargs: dict[str, Any], response_obj: Any) -> None:
    usage = getattr(response_obj, "usage", None) or {}
    if isinstance(usage, dict):
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
    else:
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(
            getattr(usage, "completion_tokens", 0)
            or getattr(usage, "output_tokens", 0)
            or 0
        )

    hidden = getattr(response_obj, "_hidden_params", {}) or {}
    response_cost = hidden.get("response_cost")
    if response_cost is None:
        response_cost = kwargs.get("response_cost") or 0

    record_event(
        model=str(kwargs.get("model") or ""),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=float(response_cost or 0),
        request_id=str(getattr(response_obj, "id", "") or ""),
    )


class UsageLogger(CustomLogger):
    def log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: float,
        end_time: float,
    ) -> None:
        _record_from_response(kwargs, response_obj)

    async def async_log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: float,
        end_time: float,
    ) -> None:
        _record_from_response(kwargs, response_obj)


proxy_handler_instance = UsageLogger()
