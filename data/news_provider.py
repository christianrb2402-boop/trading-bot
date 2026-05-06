from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Iterable
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from config.settings import Settings


@dataclass(slots=True, frozen=True)
class NewsProviderStatus:
    source: str
    status: str
    checked_at: str
    items_detected: int
    last_error: str | None


@dataclass(slots=True, frozen=True)
class NewsItem:
    source: str
    headline: str
    event_time: str
    detected_symbols: tuple[str, ...]
    sentiment_score: float
    confidence: float
    raw_payload: dict[str, object]


class NewsProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch_latest(self, *, symbols: Iterable[str], limit: int = 5) -> tuple[NewsProviderStatus, list[NewsItem]]:
        checked_at = datetime.now(timezone.utc).isoformat()
        if not self._settings.news_enabled:
            return NewsProviderStatus("COINDESK_RSS", "DISABLED", checked_at, 0, None), []
        request = Request(
            self._settings.coindesk_rss_url,
            headers={"User-Agent": "multiagent-trading-system/0.1"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8", errors="replace")
            root = ET.fromstring(payload)
            items: list[NewsItem] = []
            uppercase_symbols = tuple(symbol.upper() for symbol in symbols)
            for node in root.findall(".//item")[:limit]:
                headline = (node.findtext("title") or "").strip()
                pub_date = (node.findtext("pubDate") or checked_at).strip()
                detected = tuple(symbol for symbol in uppercase_symbols if symbol.replace("USDT", "") in headline.upper())
                sentiment_score = self._headline_sentiment(headline)
                items.append(
                    NewsItem(
                        source="COINDESK_RSS",
                        headline=headline,
                        event_time=pub_date,
                        detected_symbols=detected,
                        sentiment_score=sentiment_score,
                        confidence=0.35 if detected else 0.2,
                        raw_payload={"headline": headline, "pub_date": pub_date},
                    )
                )
            return NewsProviderStatus("COINDESK_RSS", "OK", checked_at, len(items), None), items
        except Exception as exc:
            return NewsProviderStatus("COINDESK_RSS", "FAIL", checked_at, 0, str(exc)), []

    @staticmethod
    def _headline_sentiment(headline: str) -> float:
        positive_words = ("surge", "breakout", "rally", "gain", "approval", "bull", "record")
        negative_words = ("crash", "hack", "ban", "lawsuit", "drop", "bear", "liquidation")
        upper = headline.upper()
        score = 0.0
        score += sum(1 for word in positive_words if word.upper() in upper) * 0.2
        score -= sum(1 for word in negative_words if word.upper() in upper) * 0.2
        return round(max(-1.0, min(1.0, score)), 6)


def news_item_to_payload(item: NewsItem) -> str:
    return json.dumps(
        {
            "source": item.source,
            "headline": item.headline,
            "event_time": item.event_time,
            "detected_symbols": list(item.detected_symbols),
            "sentiment_score": item.sentiment_score,
            "confidence": item.confidence,
            "raw_payload": item.raw_payload,
        },
        ensure_ascii=True,
    )
