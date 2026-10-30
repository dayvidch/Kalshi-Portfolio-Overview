
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


def connect(db_path: str):
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str):
    with connect(db_path) as conn:
        # Existing fills table: preserve all previously imported fills.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                created_time TEXT,
                ticker TEXT,
                action TEXT,
                side TEXT,
                count_fp TEXT,
                price_dollars TEXT,
                fee_cost TEXT,
                is_taker INTEGER,
                order_id TEXT,
                trade_id TEXT,
                raw_json TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Latest snapshot of each market position.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_positions (
                ticker TEXT PRIMARY KEY,
                position_fp TEXT,
                market_exposure_dollars TEXT,
                realized_pnl_dollars TEXT,
                fees_paid_dollars TEXT,
                total_traded_dollars TEXT,
                last_updated_ts TEXT,
                raw_json TEXT NOT NULL
            )
        """)

        # Event positions are an aggregate view, not additive to markets.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_positions (
                event_ticker TEXT PRIMARY KEY,
                event_exposure_dollars TEXT,
                realized_pnl_dollars TEXT,
                fees_paid_dollars TEXT,
                total_cost_dollars TEXT,
                total_cost_shares_fp TEXT,
                raw_json TEXT NOT NULL
            )
        """)

        # Settlements: deterministic hash prevents duplicate imports.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settlements (
                record_id TEXT PRIMARY KEY,
                ticker TEXT,
                event_ticker TEXT,
                settled_time TEXT,
                market_result TEXT,
                yes_count_fp TEXT,
                no_count_fp TEXT,
                yes_total_cost_dollars TEXT,
                no_total_cost_dollars TEXT,
                revenue TEXT,
                value TEXT,
                fee_cost TEXT,
                raw_json TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                deposit_id TEXT PRIMARY KEY,
                amount_cents INTEGER,
                fee_cents INTEGER,
                status TEXT,
                deposit_type TEXT,
                created_ts TEXT,
                finalized_ts TEXT,
                raw_json TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                withdrawal_id TEXT PRIMARY KEY,
                amount_cents INTEGER,
                fee_cents INTEGER,
                status TEXT,
                withdrawal_type TEXT,
                created_ts TEXT,
                finalized_ts TEXT,
                raw_json TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS credit_history (
                record_id TEXT PRIMARY KEY,
                raw_json TEXT NOT NULL
            )
        """)

        # Keep a history of balance snapshots instead of overwriting them.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS balance_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                captured_at TEXT NOT NULL,
                balance_dollars TEXT,
                portfolio_value TEXT,
                raw_json TEXT NOT NULL
            )
        """)

        conn.commit()


def _price_for_fill(fill: dict) -> str:
    side = str(
        fill.get("side", fill.get("outcome_side", "yes"))
    ).lower()

    field = "no_price_dollars" if side == "no" else "yes_price_dollars"
    return str(fill.get(field, ""))


def save_fills(db_path: str, fills: list[dict]) -> int:
    inserted = 0

    with connect(db_path) as conn:
        for fill in fills:
            fill_id = fill.get("fill_id")

            if not fill_id:
                continue

            cursor = conn.execute("""
                INSERT OR IGNORE INTO fills (
                    fill_id, created_time, ticker, action, side, count_fp,
                    price_dollars, fee_cost, is_taker, order_id, trade_id,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(fill_id),
                fill.get("created_time", ""),
                fill.get("ticker", fill.get("market_ticker", "")),
                fill.get("action", ""),
                fill.get("side", fill.get("outcome_side", "")),
                str(fill.get("count_fp", fill.get("count", ""))),
                _price_for_fill(fill),
                str(fill.get("fee_cost", "0")),
                1 if fill.get("is_taker") else 0,
                str(fill.get("order_id", "")),
                str(fill.get("trade_id", "")),
                json.dumps(fill, separators=(",", ":")),
            ))

            inserted += cursor.rowcount

        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO sync_state(key, value) VALUES('last_sync', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (now,),
        )

        conn.commit()

    return inserted


def load_fills(db_path: str) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("""
            SELECT fill_id, created_time, ticker, action, side, count_fp,
                   price_dollars, fee_cost, is_taker, order_id, trade_id
            FROM fills
            ORDER BY created_time DESC
        """).fetchall()

    return [dict(row) for row in rows]


def count_fills(db_path: str) -> int:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM fills"
        ).fetchone()[0]


def last_sync(db_path: str) -> str | None:
    return get_sync_value(db_path, "last_sync")


def get_sync_value(db_path: str, key: str) -> str | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key=?",
            (key,),
        ).fetchone()

    return row["value"] if row else None


def set_sync_value(db_path: str, key: str, value: str):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sync_state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


def latest_fill_timestamp(db_path: str) -> int | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(created_time) AS latest FROM fills"
        ).fetchone()

    value = row["latest"] if row else None

    if not value:
        return None

    try:
        return int(
            datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).timestamp()
        )
    except ValueError:
        return None


def _json(value: dict) -> str:
    return json.dumps(value, separators=(",", ":"))


def _record_id(record: dict) -> str:
    """Create a stable identifier for records without an API-provided ID."""
    raw = _json(record).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def save_market_positions(db_path: str, records: list[dict]) -> int:
    with connect(db_path) as conn:
        for item in records:
            ticker = item.get("ticker")
            if not ticker:
                continue

            conn.execute("""
                INSERT INTO market_positions (
                    ticker, position_fp, market_exposure_dollars,
                    realized_pnl_dollars, fees_paid_dollars,
                    total_traded_dollars, last_updated_ts, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    position_fp=excluded.position_fp,
                    market_exposure_dollars=excluded.market_exposure_dollars,
                    realized_pnl_dollars=excluded.realized_pnl_dollars,
                    fees_paid_dollars=excluded.fees_paid_dollars,
                    total_traded_dollars=excluded.total_traded_dollars,
                    last_updated_ts=excluded.last_updated_ts,
                    raw_json=excluded.raw_json
            """, (
                str(ticker),
                str(item.get("position_fp", "")),
                str(item.get("market_exposure_dollars", "")),
                str(item.get("realized_pnl_dollars", "")),
                str(item.get("fees_paid_dollars", "")),
                str(item.get("total_traded_dollars", "")),
                str(item.get("last_updated_ts", "")),
                _json(item),
            ))

        conn.commit()

    return len(records)


def save_event_positions(db_path: str, records: list[dict]) -> int:
    with connect(db_path) as conn:
        for item in records:
            event_ticker = item.get("event_ticker")
            if not event_ticker:
                continue

            conn.execute("""
                INSERT INTO event_positions (
                    event_ticker, event_exposure_dollars,
                    realized_pnl_dollars, fees_paid_dollars,
                    total_cost_dollars, total_cost_shares_fp, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_ticker) DO UPDATE SET
                    event_exposure_dollars=excluded.event_exposure_dollars,
                    realized_pnl_dollars=excluded.realized_pnl_dollars,
                    fees_paid_dollars=excluded.fees_paid_dollars,
                    total_cost_dollars=excluded.total_cost_dollars,
                    total_cost_shares_fp=excluded.total_cost_shares_fp,
                    raw_json=excluded.raw_json
            """, (
                str(event_ticker),
                str(item.get("event_exposure_dollars", "")),
                str(item.get("realized_pnl_dollars", "")),
                str(item.get("fees_paid_dollars", "")),
                str(item.get("total_cost_dollars", "")),
                str(item.get("total_cost_shares_fp", "")),
                _json(item),
            ))

        conn.commit()

    return len(records)


def save_settlements(db_path: str, records: list[dict]) -> int:
    with connect(db_path) as conn:
        for item in records:
            record_id = _record_id(item)

            conn.execute("""
                INSERT OR IGNORE INTO settlements (
                    record_id, ticker, event_ticker, settled_time,
                    market_result, yes_count_fp, no_count_fp,
                    yes_total_cost_dollars, no_total_cost_dollars,
                    revenue, value, fee_cost, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                str(item.get("ticker", "")),
                str(item.get("event_ticker", "")),
                str(item.get("settled_time", "")),
                str(item.get("market_result", "")),
                str(item.get("yes_count_fp", "")),
                str(item.get("no_count_fp", "")),
                str(item.get("yes_total_cost_dollars", "")),
                str(item.get("no_total_cost_dollars", "")),
                str(item.get("revenue", "")),
                str(item.get("value", "")),
                str(item.get("fee_cost", "")),
                _json(item),
            ))

        conn.commit()

    return len(records)


def _save_cash_records(
    db_path: str,
    table: str,
    id_column: str,
    records: list[dict],
) -> int:
    if table not in {"deposits", "withdrawals"}:
        raise ValueError("Unsupported cash record table.")

    with connect(db_path) as conn:
        for item in records:
            record_id = item.get("id")
            if not record_id:
                continue

            conn.execute(f"""
                INSERT INTO {table} (
                    {id_column}, amount_cents, fee_cents, status,
                    {table[:-1] + "_type"}, created_ts, finalized_ts, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT({id_column}) DO UPDATE SET
                    amount_cents=excluded.amount_cents,
                    fee_cents=excluded.fee_cents,
                    status=excluded.status,
                    {table[:-1] + "_type"}=excluded.{table[:-1] + "_type"},
                    created_ts=excluded.created_ts,
                    finalized_ts=excluded.finalized_ts,
                    raw_json=excluded.raw_json
            """, (
                str(record_id),
                item.get("amount_cents"),
                item.get("fee_cents"),
                str(item.get("status", "")),
                str(item.get("type", "")),
                str(item.get("created_ts", "")),
                str(item.get("finalized_ts", "")),
                _json(item),
            ))

        conn.commit()

    return len(records)


def save_deposits(db_path: str, records: list[dict]) -> int:
    return _save_cash_records(
        db_path, "deposits", "deposit_id", records
    )


def save_withdrawals(db_path: str, records: list[dict]) -> int:
    return _save_cash_records(
        db_path, "withdrawals", "withdrawal_id", records
    )


def save_credit_history(db_path: str, records: list[dict]) -> int:
    with connect(db_path) as conn:
        for item in records:
            conn.execute("""
                INSERT OR IGNORE INTO credit_history (
                    record_id, raw_json
                ) VALUES (?, ?)
            """, (_record_id(item), _json(item)))

        conn.commit()

    return len(records)


def save_balance_snapshot(db_path: str, balance: dict) -> str:
    captured_at = datetime.now(timezone.utc).isoformat()

    snapshot_id = _record_id({
        "captured_at": captured_at,
        "balance": balance,
    })

    with connect(db_path) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO balance_snapshots (
                snapshot_id, captured_at, balance_dollars,
                portfolio_value, raw_json
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            snapshot_id,
            captured_at,
            str(balance.get("balance_dollars", "")),
            str(balance.get("portfolio_value", "")),
            _json(balance),
        ))

        conn.commit()

    return snapshot_id


def load_table(db_path: str, table: str) -> list[dict]:
    allowed = {
        "market_positions",
        "event_positions",
        "settlements",
        "deposits",
        "withdrawals",
        "credit_history",
        "balance_snapshots",
    }

    if table not in allowed:
        raise ValueError("Unsupported table.")

    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table}"
        ).fetchall()

    return [dict(row) for row in rows]
