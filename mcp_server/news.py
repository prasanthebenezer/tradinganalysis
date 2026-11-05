"""Headlines from Google News RSS (India edition) and Yahoo, fenced at as_of.

Google News dates older items at day precision, so an item dated as_of may have
been published during that day. Decisions are assumed to be made after the
close, so same-day items are allowed.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import yfinance as yf

from .asof import IST, is_live, today_ist
from .cache import cached
from .symbols import USER_AGENT, company_name, short_name, to_yahoo

GOOGLE_RSS = "https://news.google.com/rss/search"
MAX_DAYS = 30


@dataclass(frozen=True)
class Headline:
    published: datetime  # IST
    source: str
    title: str
    link: str


def _google(query: str, start: date, as_of: date) -> list[Headline]:
    q = f"{query} after:{start.isoformat()} before:{(as_of + timedelta(days=1)).isoformat()}"
    url = GOOGLE_RSS + "?" + urllib.parse.urlencode({"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        root = ET.fromstring(resp.read())
    out = []
    for item in root.findall("./channel/item"):
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(IST)
        except (TypeError, ValueError):
            continue
        out.append(Headline(pub, item.findtext("source") or "", (item.findtext("title") or "").strip(),
                            item.findtext("link") or ""))
    return out


def _yahoo(yahoo_symbol: str) -> list[Headline]:
    out = []
    for n in yf.Ticker(yahoo_symbol).news or []:
        c = n.get("content") or {}
        try:
            pub = datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00")).astimezone(IST)
        except (KeyError, ValueError, AttributeError):
            continue
        link = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or ""
        out.append(Headline(pub, (c.get("provider") or {}).get("displayName", "Yahoo"), (c.get("title") or "").strip(), link))
    return out


def _norm(title: str) -> str:
    title = re.sub(r"\s+-\s+[^-]+$", "", title)  # Google appends " - Source"
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _fence(items: list[Headline], start: date, as_of: date, limit: int) -> list[Headline]:
    seen, out = set(), []
    for h in sorted(items, key=lambda h: h.published, reverse=True):
        d = h.published.date()
        if d > as_of or d < start:
            continue
        k = _norm(h.title)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(h)
    return out[:limit]


def _days(days: int) -> int:
    return max(1, min(int(days), MAX_DAYS))


def company_news(symbol: str, as_of: date, days: int = 7, limit: int = 25) -> tuple[list[Headline], list[str]]:
    days = _days(days)
    start = as_of - timedelta(days=days)
    name = short_name(company_name(symbol))
    notes = []
    items: list[Headline] = []
    key = f"gnews:{name}:{start}:{as_of}"
    try:
        items += cached(key, 1800 if is_live(as_of) else 7 * 86400, lambda: _google(f'"{name}"', start, as_of))
    except Exception as exc:  # network
        notes.append(f"Google News unavailable: {exc.__class__.__name__}")
    if (today_ist() - as_of).days <= 10:  # Yahoo only carries recent stories
        try:
            items += cached(f"ynews:{symbol}", 1800, lambda: _yahoo(to_yahoo(symbol)))
        except Exception as exc:
            notes.append(f"Yahoo news unavailable: {exc.__class__.__name__}")
    out = _fence(items, start, as_of, limit)
    if len(out) < 5:
        notes.append("few headlines found; Google News coverage of older dates is thin, so absence of news is weak evidence")
    return out, notes


MARKET_QUERY = '(Sensex OR Nifty OR RBI OR "Indian economy" OR FII)'


def market_news(as_of: date, days: int = 3, limit: int = 25) -> tuple[list[Headline], list[str]]:
    days = _days(days)
    start = as_of - timedelta(days=days)
    notes = []
    try:
        items = cached(f"gnews:market:{start}:{as_of}", 1800 if is_live(as_of) else 7 * 86400,
                       lambda: _google(MARKET_QUERY, start, as_of))
    except Exception as exc:
        items = []
        notes.append(f"Google News unavailable: {exc.__class__.__name__}")
    return _fence(items, start, as_of, limit), notes


def render(items: list[Headline]) -> str:
    if not items:
        return "(no headlines in window)"
    def title(h: Headline) -> str:
        suffix = f" - {h.source}"
        return h.title[: -len(suffix)] if h.source and h.title.endswith(suffix) else h.title
    return "\n".join(f"- {h.published.date().isoformat()} | {h.source} | {title(h)} | {h.link}" for h in items)
