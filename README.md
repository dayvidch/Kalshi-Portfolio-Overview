# Kalshi Analytics Dashboard

A local-first analytics dashboard for tracking and analyzing Kalshi prediction-market trading activity. Built with Python, Streamlit, SQLite, and the Kalshi API.

## Features

- **Account Overview:** Cash balance, portfolio value, and total account value.
- **Position Analytics:** Market-level exposure, realized P&L, and fees.
- **Settlement Analytics:** Historical settlement records and net profit/loss calculations.
- **Performance Visualization:** Cumulative settlement P&L line chart.
- **Trading Activity:** Historical fills, contract volume, notional value, and fees.
- **Balance History:** Historical cash, positions, and total account value.
- **Transaction History:** Deposits and withdrawals.
- **Automatic Synchronization:** Refreshes account data every five minutes while the dashboard is open.
- **Local Database:** SQLite storage for historical account data.
- **Read-Only API Access:** Retrieves account information without placing trades or initiating transfers.

## Tech Stack

- Python
- Streamlit
- Pandas
- SQLite
- Plotly
- Kalshi REST API

## Architecture

The application uses a local-first architecture:

1. Authenticates with the Kalshi API using an Ed25519 or RSA-PSS private key.
2. Retrieves account data through read-only API requests.
3. Stores synchronized records in a local SQLite database.
4. Processes trading activity and settlement data using Python.
5. Displays portfolio analytics through an interactive Streamlit dashboard.

## Installation

### Requirements

- Python 3.11+
- A Kalshi account and read-only API credentials

### Setup

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/kalshi-analytics-dashboard.git
cd kalshi-analytics-dashboard
```

Create a virtual environment:

**Windows PowerShell**
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your local environment configuration:

```bash
cp .env.example .env
```

On Windows PowerShell, use:

```powershell
Copy-Item .env.example .env
```

Configure your own API credentials in `.env` and store your private key outside the project directory.

Run the dashboard:

```bash
streamlit run app.py
```

Open the local address displayed in your terminal.

## Security and Privacy

- API credentials are stored locally in `.env`.
- Private keys are stored outside the project directory.
- The application uses read-only API access.
- Account databases and backups are excluded from version control.
- No personal account information or trading history is included in this repository.

**Important:** Never commit `.env`, private keys, SQLite databases, or personal account exports.

## Performance Calculation Notes

The cumulative P&L visualization is based on historical settlement records and includes settlement fees. It represents settlement performance rather than a complete account-level profit/loss reconciliation.

Open positions, unrealized P&L, and cash-flow reconciliation are separate considerations.

## Disclaimer

This project is an independent analytics tool and is not affiliated with or endorsed by Kalshi. It does not provide financial advice or execute trades.

## License

MIT License