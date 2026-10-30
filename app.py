
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.express as px
from dotenv import load_dotenv

from kalshi_dashboard.db import (
    init_db,
    load_fills,
    count_fills,
    last_sync,
    load_table,
    get_sync_value,
)

from kalshi_dashboard.kalshi_api import KalshiClient
from kalshi_dashboard.sync import sync_all


load_dotenv()

st.set_page_config(
    page_title="Kalshi Analytics",
    page_icon="◫",
    layout="wide",
)

DB_PATH = os.getenv("KALSHI_DB_PATH", "data/kalshi.db")

init_db(DB_PATH)


# -------------------------
# Styling
# -------------------------


st.markdown("""
<style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1600px;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: #f7f8fa !important;
        border: 1px solid #e7e9ee !important;
        padding: 16px 18px;
        border-radius: 12px;
    }

    [data-testid="stMetricLabel"],
    [data-testid="stMetricLabel"] p {
        color: #667085 !important;
    }

    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] div {
        color: #101828 !important;
    }

    [data-testid="stMetricDelta"] {
        color: #475467 !important;
    }

    /* Tables */
    div[data-testid="stDataFrame"] {
        border: 1px solid #e7e9ee;
        border-radius: 10px;
    }

    /* Headings */
    h1 {
        letter-spacing: -0.04em;
    }
</style>
""", unsafe_allow_html=True)



# -------------------------
# Helpers
# -------------------------

def money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def records_df(records):
    return pd.DataFrame(records) if records else pd.DataFrame()


# -------------------------
# Connection
# -------------------------

st.title("Kalshi Analytics")

st.caption(
    "Trading history · Portfolio analytics · Local database · Read-only API"
)

key_id = os.getenv("KALSHI_API_KEY_ID", "").strip()
key_file = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
api_env = os.getenv("KALSHI_ENV", "production").strip().lower()

configured = bool(
    key_id
    and key_file
    and Path(key_file).expanduser().exists()
)


def get_client():
    if not configured:
        return None

    return KalshiClient(
        key_id=key_id,
        private_key_path=key_file,
        environment=api_env,
    )


with st.sidebar:
    st.subheader("Connection")

    st.write(
        "Environment:",
        "Production" if api_env == "production" else "Demo",
    )

    st.write(
        "API credentials:",
        "Configured" if configured else "Not configured",
    )

    st.divider()

    st.subheader("Synchronization")

    st.caption(
        "Automatic refresh target: every 5 minutes while this dashboard is open."
    )

    manual_sync = st.button(
        "Sync all account data",
        use_container_width=True,
        type="primary",
        disabled=not configured,
    )

    st.divider()

    st.caption(f"Local database: `{DB_PATH}`")


# -------------------------
# Synchronization
# -------------------------

def perform_sync():
    client = get_client()

    if client is None:
        raise RuntimeError("API credentials are not configured.")

    return sync_all(client, DB_PATH)


if manual_sync:
    try:
        with st.spinner("Synchronizing your Kalshi account..."):
            sync_results = perform_sync()

        st.success("Account synchronization completed.")

        st.write("New fills:", sync_results["new_fills"])

        st.write(
            "Portfolio records:",
            sync_results["portfolio"],
        )

    except Exception as exc:
        st.error(f"Synchronization failed: {exc}")


@st.fragment(run_every=300)
def automatic_sync():
    if configured:
        try:
            perform_sync()
        except Exception as exc:
            st.warning(f"Automatic synchronization issue: {exc}")

    st.caption(
        f"Last fill sync: {last_sync(DB_PATH) or 'Not synced yet'}"
    )

    st.caption(
        "Last portfolio sync: "
        f"{get_sync_value(DB_PATH, 'last_portfolio_sync') or 'Not synced yet'}"
    )


automatic_sync()


# -------------------------
# Load data
# -------------------------

fills = load_fills(DB_PATH)

market_positions = load_table(DB_PATH, "market_positions")
event_positions = load_table(DB_PATH, "event_positions")
settlements = load_table(DB_PATH, "settlements")
deposits = load_table(DB_PATH, "deposits")
withdrawals = load_table(DB_PATH, "withdrawals")
credits = load_table(DB_PATH, "credit_history")
balances = load_table(DB_PATH, "balance_snapshots")


# -------------------------
# Setup message
# -------------------------

if not configured:

    st.info(
        "Connect your Kalshi read-only API credentials to import account history."
    )

elif not balances and not market_positions and not fills:

    st.info(
        "Your database is ready. Select "
        "**Sync all account data** in the sidebar to import your history."
    )


# -------------------------
# Account overview
# -------------------------

if balances:

    latest_balance = max(
        balances,
        key=lambda item: item.get("captured_at", ""),
    )

    st.subheader("Account overview")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Cash balance",
        money(latest_balance.get("balance_dollars")),
    )

    positions_value = (
        float(latest_balance.get("portfolio_value", 0)) / 100
    )

    credit_value = (
        float(latest_balance.get("credit", 0)) / 100
    )

    total_account_value = (
        float(latest_balance.get("balance_dollars", 0))
        + positions_value
        + credit_value
    )

    c2.metric(
        "Positions value",
        money(positions_value),
    )

    c3.metric(
        "Total account value",
        money(total_account_value),
    )

    st.caption(
        "Total account value is calculated as cash balance + positions value + credit."
    )

# -------------------------
# Realized P&L and positions
# -------------------------

if market_positions:

    positions_df = records_df(market_positions)

    positions_df["realized_pnl_num"] = (
        pd.to_numeric(
            positions_df["realized_pnl_dollars"],
            errors="coerce",
        ).fillna(0)
    )

    positions_df["fees_num"] = (
        pd.to_numeric(
            positions_df["fees_paid_dollars"],
            errors="coerce",
        ).fillna(0)
    )

    positions_df["exposure_num"] = (
        pd.to_numeric(
            positions_df["market_exposure_dollars"],
            errors="coerce",
        ).fillna(0)
    )

    st.subheader("Position analytics")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Market-level realized P&L",
        money(positions_df["realized_pnl_num"].sum()),
    )

    c2.metric(
        "Market exposure",
        money(positions_df["exposure_num"].sum()),
    )

    c3.metric(
        "Fees paid on positions",
        money(positions_df["fees_num"].sum()),
    )

    st.caption(
        "Realized P&L is the value reported by Kalshi for market positions. "
        "It is not added to event-level P&L or independently calculated "
        "account cash flows."
    )

    st.subheader("Market positions")

    display_positions = [
        "ticker",
        "position_fp",
        "market_exposure_dollars",
        "realized_pnl_dollars",
        "fees_paid_dollars",
        "total_traded_dollars",
    ]

    display_positions = [
        col for col in display_positions
        if col in positions_df.columns
    ]

    st.dataframe(
        positions_df[display_positions],
        use_container_width=True,
        hide_index=True,
    )


# -------------------------
# Event-level positions
# -------------------------

if event_positions:

    events_df = records_df(event_positions)

    events_df["realized_pnl_num"] = pd.to_numeric(
        events_df["realized_pnl_dollars"],
        errors="coerce",
    ).fillna(0)

    st.subheader("Event-level position summary")

    st.metric(
        "Event-level realized P&L",
        money(events_df["realized_pnl_num"].sum()),
    )

    st.caption(
        "This is a separate aggregate view. Do not add it to market-level "
        "realized P&L because events can contain multiple markets."
    )

    st.dataframe(
        events_df.drop(columns=["raw_json"], errors="ignore"),
        use_container_width=True,
        hide_index=True,
    )


# -------------------------
# Balance history
# -------------------------

if balances:

    balance_df = records_df(balances)

    balance_df["captured_at"] = pd.to_datetime(
        balance_df["captured_at"],
        utc=True,
        errors="coerce",
    )

    balance_df["balance_num"] = pd.to_numeric(
        balance_df["balance_dollars"],
        errors="coerce",
    )

    balance_df["portfolio_num"] = (
        pd.to_numeric(
            balance_df["portfolio_value"],
            errors="coerce",
        ) / 100
    )

    balance_df["credit_num"] = 0.0

    balance_df["total_account_num"] = (
        balance_df["balance_num"]
        + balance_df["portfolio_num"]
        + balance_df["credit_num"]
    )
    

    st.subheader("Account balance history")

    balance_df = balance_df.dropna(subset=["captured_at"])

    if not balance_df.empty:

        balance_df = balance_df.sort_values("captured_at")

        chart_balance = balance_df.set_index("captured_at")[
            ["balance_num", "portfolio_num", "total_account_num"]
        ]

        chart_balance.columns = [
            "Cash",
            "Positions",
            "Total account value",
        ]

        st.line_chart(
            chart_balance,
            height=300,
        )

        st.caption(
            "Historical snapshots collected while this dashboard is running. "
            "This history starts with the first successful portfolio sync."
        )


# -------------------------
# Settlements
# -------------------------

if settlements:

    settlement_df = records_df(settlements)

    st.subheader("Settlement history")

    st.metric(
        "Recorded settlements",
        f"{len(settlement_df):,}",
    )

    display_settlements = [
        "settled_time",
        "ticker",
        "event_ticker",
        "market_result",
        "yes_count_fp",
        "no_count_fp",
        "yes_total_cost_dollars",
        "no_total_cost_dollars",
        "revenue",
        "value",
        "fee_cost",
    ]

    display_settlements = [
        col for col in display_settlements
        if col in settlement_df.columns
    ]

    st.dataframe(
        settlement_df[display_settlements],
        use_container_width=True,
        hide_index=True,
    )


# -------------------------
# Cumulative settlement P&L
# -------------------------

if settlements:

    settlement_chart_df = records_df(settlements).copy()

    settlement_chart_df["settled_time"] = pd.to_datetime(
        settlement_chart_df["settled_time"],
        utc=True,
        errors="coerce",
    )

    settlement_chart_df["result"] = (
        settlement_chart_df["market_result"].str.lower()
    )

    settlement_chart_df["payout"] = 0.0

    settlement_chart_df.loc[
        settlement_chart_df["result"] == "yes", "payout"
    ] = pd.to_numeric(
        settlement_chart_df["yes_count_fp"],
        errors="coerce",
    )

    settlement_chart_df.loc[
        settlement_chart_df["result"] == "no", "payout"
    ] = pd.to_numeric(
        settlement_chart_df["no_count_fp"],
        errors="coerce",
    )

    settlement_chart_df.loc[
        settlement_chart_df["result"] == "scalar", "payout"
    ] = pd.to_numeric(
        settlement_chart_df["revenue"],
        errors="coerce",
    ) / 100

    settlement_chart_df["yes_cost"] = pd.to_numeric(
        settlement_chart_df["yes_total_cost_dollars"],
        errors="coerce",
    ).fillna(0)

    settlement_chart_df["no_cost"] = pd.to_numeric(
        settlement_chart_df["no_total_cost_dollars"],
        errors="coerce",
    ).fillna(0)

    settlement_chart_df["fees"] = pd.to_numeric(
        settlement_chart_df["fee_cost"],
        errors="coerce",
    ).fillna(0)

    settlement_chart_df["net_pnl"] = (
        settlement_chart_df["payout"]
        - settlement_chart_df["yes_cost"]
        - settlement_chart_df["no_cost"]
        - settlement_chart_df["fees"]
    )

    settlement_chart_df["date"] = (
        settlement_chart_df["settled_time"]
        .dt.tz_convert("America/Los_Angeles")
        .dt.date
    )

    daily_pnl = (
        settlement_chart_df.groupby("date")["net_pnl"]
        .sum()
        .reset_index()
        .sort_values("date")
    )

    daily_pnl["cumulative_pnl"] = daily_pnl["net_pnl"].cumsum()

    st.subheader("Cumulative P&L")

    st.metric(
        "Net P&L after settlement fees",
        money(daily_pnl["cumulative_pnl"].iloc[-1]),
    )

    chart_data = daily_pnl.set_index("date")[["cumulative_pnl"]]
    chart_data.columns = ["P&L"]

    st.line_chart(
        chart_data,
        height=350,
    )

    st.caption(
        "Cumulative realized P&L from recorded settlements, "
        "after settlement fees. Does not include unrealized P&L "
        "from open positions."
    )
    
# -------------------------
# Deposits and withdrawals
# -------------------------

st.subheader("Cash movement history")

cash1, cash2 = st.columns(2)

with cash1:

    st.markdown("**Deposits**")

    if deposits:

        deposits_df = records_df(deposits)

        deposits_df["amount_dollars"] = (
            pd.to_numeric(
                deposits_df["amount_cents"],
                errors="coerce",
            ) / 100
        )

        deposits_df["fee_dollars"] = (
            pd.to_numeric(
                deposits_df["fee_cents"],
                errors="coerce",
            ) / 100
        )

        st.metric(
            "Recorded deposits",
            f"{len(deposits_df):,}",
        )

        st.dataframe(
            deposits_df.drop(
                columns=["raw_json"],
                errors="ignore",
            ),
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.caption("No deposit records imported yet.")


with cash2:

    st.markdown("**Withdrawals**")

    if withdrawals:

        withdrawals_df = records_df(withdrawals)

        withdrawals_df["amount_dollars"] = (
            pd.to_numeric(
                withdrawals_df["amount_cents"],
                errors="coerce",
            ) / 100
        )

        withdrawals_df["fee_dollars"] = (
            pd.to_numeric(
                withdrawals_df["fee_cents"],
                errors="coerce",
            ) / 100
        )

        st.metric(
            "Recorded withdrawals",
            f"{len(withdrawals_df):,}",
        )

        st.dataframe(
            withdrawals_df.drop(
                columns=["raw_json"],
                errors="ignore",
            ),
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.caption("No withdrawal records imported yet.")


# -------------------------
# Fill-level trading activity
# -------------------------

if fills:

    df = pd.DataFrame(fills)

    df["created_time"] = pd.to_datetime(
        df["created_time"],
        utc=True,
        errors="coerce",
    )

    df["fee_cost_num"] = pd.to_numeric(
        df["fee_cost"],
        errors="coerce",
    ).fillna(0)

    df["count_num"] = pd.to_numeric(
        df["count_fp"],
        errors="coerce",
    ).fillna(0)

    df["price_num"] = pd.to_numeric(
        df["price_dollars"],
        errors="coerce",
    ).fillna(0)

    df["notional"] = df["count_num"] * df["price_num"]

    st.subheader("Trading activity")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Historical fills",
        f"{len(df):,}",
    )

    c2.metric(
        "Contracts filled",
        f"{df['count_num'].sum():,.2f}",
    )

    c3.metric(
        "Fill notional",
        money(df["notional"].sum()),
    )

    c4.metric(
        "Fill fees",
        money(df["fee_cost_num"].sum()),
    )

    st.caption(
        "Fill notional is contracts multiplied by execution price. "
        "It is trading activity, not profit or loss."
    )

    chart_df = df.dropna(
        subset=["created_time"]
    ).copy()

    if not chart_df.empty:

        chart_df["date"] = (
            chart_df["created_time"]
            .dt.tz_convert(None)
            .dt.date
        )

        daily = chart_df.groupby(
            "date",
            as_index=False,
        ).agg(
            fills=("fill_id", "count"),
            notional=("notional", "sum"),
            fees=("fee_cost_num", "sum"),
        )

        st.subheader("Daily trading activity")

        st.line_chart(
            daily.set_index("date")[["notional"]],
            height=260,
        )

    # -------------------------
    # Fill history and filters
    # -------------------------

    st.subheader("Complete fill history")

    search = st.text_input(
        "Search ticker, order ID, or fill ID"
    )

    filtered = df.copy()

    if search:

        mask = (
            filtered["ticker"].astype(str).str.contains(
                search,
                case=False,
                na=False,
            )
            | filtered["order_id"].astype(str).str.contains(
                search,
                case=False,
                na=False,
            )
            | filtered["fill_id"].astype(str).str.contains(
                search,
                case=False,
                na=False,
            )
        )

        filtered = filtered[mask]

    min_date = (
        filtered["created_time"].min()
        if not filtered.empty else None
    )

    max_date = (
        filtered["created_time"].max()
        if not filtered.empty else None
    )

    if min_date is not None and max_date is not None:

        start, end = st.date_input(
            "Date range",
            value=(
                min_date.date(),
                max_date.date(),
            ),
        )

        filtered = filtered[
            (filtered["created_time"].dt.date >= start)
            & (filtered["created_time"].dt.date <= end)
        ]

    display_cols = [
        "created_time",
        "ticker",
        "action",
        "side",
        "count_fp",
        "price_dollars",
        "fee_cost",
        "is_taker",
        "order_id",
        "fill_id",
    ]

    display_cols = [
        col for col in display_cols
        if col in filtered.columns
    ]

    st.dataframe(
        filtered[display_cols].sort_values(
            "created_time",
            ascending=False,
        ),
        use_container_width=True,
        hide_index=True,
        height=520,
    )

    st.download_button(
        "Export filtered fills as CSV",
        filtered[display_cols].to_csv(
            index=False
        ).encode("utf-8"),
        file_name="kalshi_fills_export.csv",
        mime="text/csv",
    )


# -------------------------
# Footer
# -------------------------

st.divider()

st.caption(
    "Kalshi Analytics is an independent, local read-only analytics tool. "
    "Account-level profit/loss reconciliation is not yet verified."
)
