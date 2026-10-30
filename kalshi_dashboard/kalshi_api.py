
from __future__ import annotations

import base64
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, ed25519


BASE_URLS = {
    "production": "https://external-api.kalshi.com",
    "demo": "https://external-api.demo.kalshi.co",
}


class KalshiAPIError(RuntimeError):
    pass


class KalshiClient:
    """Read-only Kalshi REST client supporting Ed25519 and RSA-PSS PEM keys."""

    def __init__(
        self,
        key_id: str,
        private_key_path: str,
        environment: str = "production",
    ):
        if environment not in BASE_URLS:
            raise ValueError("KALSHI_ENV must be 'production' or 'demo'.")

        self.key_id = key_id
        self.base_url = BASE_URLS[environment]

        key_bytes = Path(private_key_path).expanduser().read_bytes()
        self.private_key = serialization.load_pem_private_key(
            key_bytes,
            password=None,
        )

        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _signature(self, timestamp: str, method: str, path: str) -> str:
        path_without_query = urlparse(path).path.split("?")[0]
        message = (
            f"{timestamp}{method.upper()}{path_without_query}"
        ).encode("utf-8")

        if isinstance(self.private_key, ed25519.Ed25519PrivateKey):
            signature = self.private_key.sign(message)
        else:
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )

        return base64.b64encode(signature).decode("utf-8")

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        path = f"/trade-api/v2/{endpoint.lstrip('/')}"
        timestamp = str(int(time.time() * 1000))

        headers = {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": self._signature(
                timestamp, "GET", path
            ),
        }

        response = self.session.get(
            self.base_url + path,
            headers=headers,
            params=params or {},
            timeout=30,
        )

        if response.status_code >= 400:
            detail = response.text[:500]
            raise KalshiAPIError(
                f"Kalshi returned HTTP {response.status_code}: {detail}"
            )

        return response.json()

    def get_all_pages(
        self,
        endpoint: str,
        collection_key: str,
        limit: int = 500,
        extra_params: dict | None = None,
    ) -> list[dict]:
        """Retrieve every page of a paginated API collection."""

        items: list[dict] = []
        cursor = None
        seen_cursors = set()

        while True:
            params = {"limit": limit}

            if extra_params:
                params.update(extra_params)

            if cursor:
                params["cursor"] = cursor

            payload = self.get(endpoint, params=params)

            page = payload.get(collection_key, [])
            if isinstance(page, list):
                items.extend(page)

            next_cursor = payload.get("cursor")

            if not next_cursor or next_cursor in seen_cursors:
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return items

    # -------------------------
    # Fills
    # -------------------------

    def fetch_all_fills(self) -> list[dict]:
        historical = self.get_all_pages(
            "historical/fills",
            "fills",
        )

        live = self.get_all_pages(
            "portfolio/fills",
            "fills",
        )

        return self._dedupe_fills(historical + live)

    def fetch_recent_fills(self, min_ts: int) -> list[dict]:
        live = self.get_all_pages(
            "portfolio/fills",
            "fills",
            extra_params={"min_ts": min_ts},
        )

        return self._dedupe_fills(live)

    @staticmethod
    def _dedupe_fills(fills: list[dict]) -> list[dict]:
        unique = {}

        for fill in fills:
            fill_id = fill.get("fill_id")
            if fill_id:
                unique[fill_id] = fill

        return list(unique.values())

    # -------------------------
    # Account balance
    # -------------------------

    def fetch_balance(self) -> dict:
        """Retrieve the current account balance snapshot."""
        return self.get("portfolio/balance")

    # -------------------------
    # Positions
    # -------------------------

    def fetch_market_positions(
        self,
        settlement_status: str = "all",
    ) -> list[dict]:
        return self.get_all_pages(
            "portfolio/positions",
            "market_positions",
            extra_params={
                "settlement_status": settlement_status,
            },
        )

    def fetch_event_positions(
        self,
        settlement_status: str = "all",
    ) -> list[dict]:
        return self.get_all_pages(
            "portfolio/positions",
            "event_positions",
            extra_params={
                "settlement_status": settlement_status,
            },
        )

    # -------------------------
    # Settlements
    # -------------------------

    def fetch_settlements(self) -> list[dict]:
        return self.get_all_pages(
            "portfolio/settlements",
            "settlements",
        )

    # -------------------------
    # Deposits and withdrawals
    # -------------------------

    def fetch_deposits(self) -> list[dict]:
        return self.get_all_pages(
            "portfolio/deposits",
            "deposits",
        )

    def fetch_withdrawals(self) -> list[dict]:
        return self.get_all_pages(
            "portfolio/withdrawals",
            "withdrawals",
        )

    def fetch_credit_history(self) -> list[dict]:
        return self.get_all_pages(
            "portfolio/credit_history",
            "credits",
        )
