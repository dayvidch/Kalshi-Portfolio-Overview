
from __future__ import annotations

from kalshi_dashboard.db import (
    get_sync_value,
    latest_fill_timestamp,
    save_fills,
    set_sync_value,
    save_market_positions,
    save_event_positions,
    save_settlements,
    save_deposits,
    save_withdrawals,
    save_credit_history,
    save_balance_snapshot,
)


def sync_fills(client, db_path: str) -> int:
    """Import historical fills once, then fetch newer fills incrementally."""

    backfill_done = (
        get_sync_value(db_path, "initial_backfill_done") == "true"
    )

    if not backfill_done:
        fills = client.fetch_all_fills()
        inserted = save_fills(db_path, fills)

        set_sync_value(db_path, "initial_backfill_done", "true")
        return inserted

    latest_ts = latest_fill_timestamp(db_path)

    # Small overlap protects against delayed fills and timestamp boundaries.
    min_ts = max(0, (latest_ts or 0) - 120)

    fills = client.fetch_recent_fills(min_ts)
    return save_fills(db_path, fills)


def sync_portfolio(client, db_path: str) -> dict:
    """
    Refresh account information.

    Positions are refreshed as snapshots.
    Settlements and cash records are safely upserted.
    Balance snapshots are retained over time.
    """

    results = {}

    # 1. Current account balance.
    balance = client.fetch_balance()
    save_balance_snapshot(db_path, balance)
    results["balance"] = "updated"

    # 2. Market-level positions.
    market_positions = client.fetch_market_positions(
        settlement_status="all"
    )
    results["market_positions"] = save_market_positions(
        db_path, market_positions
    )

    # 3. Event-level positions (aggregate view).
    event_positions = client.fetch_event_positions(
        settlement_status="all"
    )
    results["event_positions"] = save_event_positions(
        db_path, event_positions
    )

    # 4. Historical settlements.
    settlements = client.fetch_settlements()
    results["settlements"] = save_settlements(
        db_path, settlements
    )

    # 5. Deposits and withdrawals.
    deposits = client.fetch_deposits()
    results["deposits"] = save_deposits(
        db_path, deposits
    )

    withdrawals = client.fetch_withdrawals()
    results["withdrawals"] = save_withdrawals(
        db_path, withdrawals
    )

    # 6. Account credits.
    credits = client.fetch_credit_history()
    results["credit_history"] = save_credit_history(
        db_path, credits
    )

    set_sync_value(db_path, "last_portfolio_sync", __import__(
        "datetime"
    ).datetime.now(__import__("datetime").timezone.utc).isoformat())

    return results


def sync_all(client, db_path: str) -> dict:
    """Synchronize fills and the complete available portfolio data."""

    results = {}

    results["new_fills"] = sync_fills(client, db_path)
    results["portfolio"] = sync_portfolio(client, db_path)

    return results
