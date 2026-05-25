"""
Javris Finance Skill — Multi-Source Market Data
────────────────────────────────────────────────
Sources:
  • Alpha Vantage  — stock quotes, forex, crypto
  • Finnhub        — real-time quotes + news sentiment
  • Financial Modeling Prep (FMP) — company info, earnings
  • FRED (St. Louis Fed)  — macroeconomic indicators (free)

5-minute cache + retry for all live calls.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger
from core.retry import resilient, with_retry, cached

logger = get_logger("javris.skill.finance")
cfg = get_config()


class FinanceSkill(BaseSkill):
    name = "finance"
    aliases = ["get_stock", "market_data", "trading_data"]
    description = "Real-time stock prices, forex, crypto and economic indicators"

    tool_definition = {
        "name": "finance",
        "description": (
            "Fetch real-time stock prices, forex rates, crypto prices, "
            "company info, and macroeconomic indicators."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["quote", "price", "company", "forex", "crypto", "macro", "sentiment"],
                    "description": "What to fetch. Use 'quote' or 'price' for stock price.",
                    "default": "quote",
                },
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol (e.g. AAPL, BTC, EURUSD)",
                },
                "indicator": {
                    "type": "string",
                    "description": "Macro indicator for FRED e.g. GDP, CPI, UNRATE",
                    "default": "GDP",
                },
            },
            "required": ["action"],
        },
    }

    @resilient(ttl=300, max_retries=3, base_delay=1.0, max_delay=15.0)
    async def run(self, action: str = "quote", symbol: str = "", indicator: str = "GDP", **_) -> dict:
        symbol = symbol.upper().strip()

        if action in ("quote", "price"):
            return await self._quote(symbol)
        elif action == "company":
            return await self._company(symbol)
        elif action == "forex":
            return await self._forex(symbol or "EURUSD")
        elif action == "crypto":
            return await self._crypto(symbol or "BTC")
        elif action == "macro":
            return await self._fred(indicator)
        elif action == "sentiment":
            return await self._sentiment(symbol)
        else:
            return {"error": f"Unknown action: {action}"}

    # ── Stock quote ─────────────────────────────────────────────

    async def _quote(self, symbol: str) -> dict:
        if not symbol:
            return {"error": "Symbol required for quote"}

        # Try Finnhub first (real-time)
        if cfg.finnhub_api_key:
            result = await self._finnhub_quote(symbol)
            if result and "error" not in result:
                return result

        # Fall back to Alpha Vantage
        if cfg.alpha_vantage_api_key:
            return await self._av_quote(symbol)

        # FMP as final fallback
        if cfg.fmp_api_key:
            return await self._fmp_quote(symbol)

        return {"error": "No finance API key configured"}

    @with_retry(max_retries=2, base_delay=0.5)
    async def _finnhub_quote(self, symbol: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    "https://finnhub.io/api/v1/quote",
                    params={"symbol": symbol, "token": cfg.finnhub_api_key},
                )
                if r.status_code == 200:
                    d = r.json()
                    if d.get("c"):
                        change = d["c"] - d["pc"]
                        pct    = (change / d["pc"] * 100) if d["pc"] else 0
                        return {
                            "symbol":         symbol,
                            "price":          round(d["c"], 4),
                            "change":         round(change, 4),
                            "change_percent": f"{pct:+.2f}%",
                            "high":           d["h"],
                            "low":            d["l"],
                            "open":           d["o"],
                            "prev_close":     d["pc"],
                            "source":         "Finnhub",
                        }
        except Exception as e:
            logger.debug(f"Finnhub quote error: {e}")
        return {}

    @with_retry(max_retries=2, base_delay=1.0)
    async def _av_quote(self, symbol: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://www.alphavantage.co/query",
                    params={"function": "GLOBAL_QUOTE", "symbol": symbol,
                            "apikey": cfg.alpha_vantage_api_key},
                )
                if r.status_code == 200:
                    gq = r.json().get("Global Quote", {})
                    if gq.get("05. price"):
                        return {
                            "symbol":         symbol,
                            "price":          float(gq["05. price"]),
                            "change":         float(gq.get("09. change", 0)),
                            "change_percent": gq.get("10. change percent", "0%"),
                            "volume":         int(gq.get("06. volume", 0)),
                            "source":         "AlphaVantage",
                        }
        except Exception as e:
            logger.debug(f"Alpha Vantage quote error: {e}")
        return {}

    @with_retry(max_retries=2, base_delay=1.0)
    async def _fmp_quote(self, symbol: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"https://financialmodelingprep.com/api/v3/quote/{symbol}",
                    params={"apikey": cfg.fmp_api_key},
                )
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        d = data[0]
                        return {
                            "symbol":         d["symbol"],
                            "price":          d["price"],
                            "change":         d.get("change", 0),
                            "change_percent": f"{d.get('changesPercentage', 0):.2f}%",
                            "market_cap":     d.get("marketCap"),
                            "pe_ratio":       d.get("pe"),
                            "source":         "FMP",
                        }
        except Exception as e:
            logger.debug(f"FMP quote error: {e}")
        return {}

    # ── Company info ────────────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _company(self, symbol: str) -> dict:
        if not symbol:
            return {"error": "Symbol required"}
        try:
            if cfg.finnhub_api_key:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(
                        "https://finnhub.io/api/v1/stock/profile2",
                        params={"symbol": symbol, "token": cfg.finnhub_api_key},
                    )
                    if r.status_code == 200 and r.json():
                        d = r.json()
                        return {
                            "name":        d.get("name", symbol),
                            "symbol":      symbol,
                            "exchange":    d.get("exchange", ""),
                            "industry":    d.get("finnhubIndustry", ""),
                            "country":     d.get("country", ""),
                            "market_cap":  d.get("marketCapitalization", "N/A"),
                            "employees":   d.get("employeeTotal", "N/A"),
                            "website":     d.get("weburl", ""),
                            "ipo":         d.get("ipo", ""),
                            "source":      "Finnhub",
                        }
        except Exception as e:
            logger.debug(f"Company info error: {e}")
        return {"error": f"No data for {symbol}"}

    # ── Forex ────────────────────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _forex(self, pair: str) -> dict:
        # Interpret: EURUSD → from=EUR to=USD
        pair = pair.replace("/", "").replace("-", "").upper()
        from_c = pair[:3] if len(pair) >= 6 else "EUR"
        to_c   = pair[3:] if len(pair) >= 6 else "USD"
        try:
            if cfg.alpha_vantage_api_key:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(
                        "https://www.alphavantage.co/query",
                        params={
                            "function": "CURRENCY_EXCHANGE_RATE",
                            "from_currency": from_c,
                            "to_currency": to_c,
                            "apikey": cfg.alpha_vantage_api_key,
                        },
                    )
                    if r.status_code == 200:
                        info = r.json().get("Realtime Currency Exchange Rate", {})
                        if info.get("5. Exchange Rate"):
                            return {
                                "pair":       f"{from_c}/{to_c}",
                                "rate":       float(info["5. Exchange Rate"]),
                                "bid":        float(info.get("8. Bid Price", 0)),
                                "ask":        float(info.get("9. Ask Price", 0)),
                                "last_refreshed": info.get("6. Last Refreshed", ""),
                                "source": "AlphaVantage",
                            }
        except Exception as e:
            logger.debug(f"Forex error: {e}")
        return {"error": f"Forex data unavailable for {pair}"}

    # ── Crypto ──────────────────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _crypto(self, symbol: str) -> dict:
        sym = symbol.upper().replace("USDT", "").replace("USD", "")
        try:
            if cfg.alpha_vantage_api_key:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(
                        "https://www.alphavantage.co/query",
                        params={
                            "function": "CURRENCY_EXCHANGE_RATE",
                            "from_currency": sym,
                            "to_currency": "USD",
                            "apikey": cfg.alpha_vantage_api_key,
                        },
                    )
                    if r.status_code == 200:
                        info = r.json().get("Realtime Currency Exchange Rate", {})
                        if info.get("5. Exchange Rate"):
                            return {
                                "symbol":  sym,
                                "price_usd": float(info["5. Exchange Rate"]),
                                "name":    info.get("2. From_Currency Name", sym),
                                "source":  "AlphaVantage",
                            }
        except Exception as e:
            logger.debug(f"Crypto error: {e}")
        return {"error": f"Crypto data unavailable for {symbol}"}

    # ── FRED macro indicators ───────────────────────────────────

    @cached(ttl=3600)  # macro data doesn't change often
    @with_retry(max_retries=2, base_delay=1.0)
    async def _fred(self, series_id: str) -> dict:
        # Map friendly names to FRED series IDs
        aliases = {
            "GDP": "GDP", "CPI": "CPIAUCSL", "INFLATION": "CPIAUCSL",
            "UNEMPLOYMENT": "UNRATE", "UNRATE": "UNRATE",
            "FED_RATE": "FEDFUNDS", "INTEREST": "FEDFUNDS",
            "SP500": "SP500", "VIX": "VIXCLS",
        }
        series = aliases.get(series_id.upper(), series_id.upper())
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{cfg.fred_base_url}/v2/series/observations",
                    params={
                        "series_id": series,
                        "format": "json",
                        "sort_order": "desc",
                        "limit": 3,
                    },
                )
                if r.status_code == 200:
                    obs = r.json().get("observations", [])
                    if obs:
                        latest = obs[0]
                        return {
                            "series":    series,
                            "value":     latest.get("value", "N/A"),
                            "date":      latest.get("date", ""),
                            "previous":  obs[1].get("value", "N/A") if len(obs) > 1 else "N/A",
                            "source":    "FRED",
                        }
        except Exception as e:
            logger.debug(f"FRED error: {e}")
        return {"error": f"FRED data unavailable for {series_id} (no API key in FRED free tier — URL access only)"}

    # ── News sentiment ──────────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _sentiment(self, symbol: str) -> dict:
        if not symbol:
            return {"error": "Symbol required for sentiment"}
        try:
            if cfg.finnhub_api_key:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get(
                        "https://finnhub.io/api/v1/news-sentiment",
                        params={"symbol": symbol, "token": cfg.finnhub_api_key},
                    )
                    if r.status_code == 200:
                        d = r.json()
                        return {
                            "symbol":           symbol,
                            "sentiment_score":  d.get("companyNewsScore", "N/A"),
                            "bullish_percent":  d.get("buzz", {}).get("buyPercentage", "N/A"),
                            "bearish_percent":  d.get("buzz", {}).get("sellPercentage", "N/A"),
                            "articles_count":   d.get("buzz", {}).get("articlesInLastWeek", 0),
                            "source":           "Finnhub",
                        }
        except Exception as e:
            logger.debug(f"Sentiment error: {e}")
        return {"error": f"Sentiment data unavailable for {symbol}"}
