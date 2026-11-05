"""NSE symbols: validation, Yahoo mapping, and name search."""

from __future__ import annotations

import csv
import io
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

from .cache import cached

_DATA = Path(__file__).resolve().parent.parent / "data"
NIFTY50_CSV = _DATA / "nifty50.csv"
EQUITY_L_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
USER_AGENT = "tradinganalysis/0.1 (+https://github.com/prasanthebenezer/tradinganalysis)"

_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")


class SymbolError(ValueError):
    pass


def normalize(symbol: str) -> str:
    """'reliance', 'RELIANCE.NS', 'NSE:RELIANCE' -> 'RELIANCE'. Rejects anything else."""
    s = (symbol or "").strip().upper()
    if s.startswith("NSE:"):
        s = s[4:]
    if s.endswith(".NS"):
        s = s[:-3]
    if not _SYMBOL_RE.match(s):
        raise SymbolError(f"not a valid NSE symbol: {symbol!r}")
    return s


def to_yahoo(symbol: str) -> str:
    return normalize(symbol) + ".NS"


@lru_cache(maxsize=1)
def nifty50() -> list[dict]:
    """Pinned NIFTY 50 constituents (data/nifty50.csv, from NSE archives)."""
    with NIFTY50_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        {"symbol": r["Symbol"].strip(), "name": r["Company Name"].strip(),
         "industry": r["Industry"].strip(), "isin": r["ISIN Code"].strip()}
        for r in rows
    ]


def _fetch_equity_list() -> list[dict]:
    req = urllib.request.Request(EQUITY_L_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    rows = csv.DictReader(io.StringIO(text))
    out = []
    for r in rows:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        out.append({"symbol": r.get("SYMBOL", ""), "name": r.get("NAME OF COMPANY", ""),
                    "series": r.get("SERIES", ""), "isin": r.get("ISIN NUMBER", "")})
    return out


def equity_list() -> list[dict]:
    """All NSE-listed equities (cached 7 days). Falls back to NIFTY 50 if NSE is unreachable."""
    try:
        return cached("nse_equity_list", 7 * 86400, _fetch_equity_list)
    except Exception:
        return [{**r, "series": "EQ"} for r in nifty50()]


def company_name(symbol: str) -> str:
    s = normalize(symbol)
    for r in nifty50():
        if r["symbol"] == s:
            return r["name"]
    for r in equity_list():
        if r["symbol"] == s:
            return r["name"]
    return s


def short_name(name: str) -> str:
    """'Reliance Industries Ltd.' -> 'Reliance Industries' for news search."""
    return re.sub(r"\s+(Ltd\.?|Limited)$", "", name.strip(), flags=re.I)


def search(query: str, limit: int = 5) -> list[dict]:
    q = (query or "").strip().upper()
    if not q:
        return []
    n50 = {r["symbol"] for r in nifty50()}
    rows = equity_list()
    exact = [r for r in rows if r["symbol"] == q.removesuffix(".NS")]
    named = [r for r in rows if q in r["name"].upper() and r not in exact]
    hits = exact + sorted(named, key=lambda r: (not r["name"].upper().startswith(q), r["symbol"] not in n50, len(r["name"])))
    return [{**r, "yahoo": r["symbol"] + ".NS", "nifty50": r["symbol"] in n50} for r in hits[:limit]]
