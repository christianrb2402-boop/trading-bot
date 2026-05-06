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
            return NewsProviderStatus("MULTI_SOURCE_NEWS", "DISABLED", checked_at, 0, None), []

        uppercase_symbols = tuple(symbol.upper() for symbol in symbols)
        all_items: list[NewsItem] = []
        errors: list[str] = []

        rss_items, rss_error = self._fetch_coindesk_rss(uppercase_symbols=uppercase_symbols, checked_at=checked_at, limit=limit)
        all_items.extend(rss_items)
        if rss_error:
            errors.append(f"COINDESK_RSS: {rss_error}")

        gdelt_items, gdelt_error = self._fetch_gdelt(uppercase_symbols=uppercase_symbols, checked_at=checked_at, limit=limit)
        all_items.extend(gdelt_items)
        if gdelt_error:
            errors.append(f"GDELT: {gdelt_error}")

        deduped: list[NewsItem] = []
        seen: set[tuple[str, str]] = set()
        for item in all_items:
            key = (item.source, item.headline)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= limit:
                break

        status = "OK" if deduped else "FAIL" if errors else "EMPTY"
        last_error = "; ".join(errors) if errors else None
        return NewsProviderStatus("MULTI_SOURCE_NEWS", status, checked_at, len(deduped), last_error), deduped

    def _fetch_coindesk_rss(
        self,
        *,
        uppercase_symbols: tuple[str, ...],
        checked_at: str,
        limit: int,
    ) -> tuple[list[NewsItem], str | None]:
        request = Request(
            self._settings.coindesk_rss_url,
            headers={"User-Agent": "multiagent-trading-system/0.1"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8", errors="replace")
            root = ET.fromstring(payload)
            items: list[NewsItem] = []
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
            return items, None
        except Exception as exc:
            return [], str(exc)

    def _fetch_gdelt(
        self,
        *,
        uppercase_symbols: tuple[str, ...],
        checked_at: str,
        limit: int,
    ) -> tuple[list[NewsItem], str | None]:
        request = Request(
            self._settings.gdelt_api_url,
            headers={"User-Agent": "multiagent-trading-system/0.1"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            articles = payload.get("articles") or []
            items: list[NewsItem] = []
            for article in articles[:limit]:
                headline = str(article.get("title") or article.get("seendate") or "").strip()
                if not headline:
                    continue
                event_time = str(article.get("seendate") or checked_at).strip()
                detected = tuple(symbol for symbol in uppercase_symbols if symbol.replace("USDT", "") in headline.upper())
                sentiment_score = self._headline_sentiment(headline)
                items.append(
                    NewsItem(
                        source="GDELT",
                        headline=headline,
                        event_time=event_time,
                        detected_symbols=detected,
                        sentiment_score=sentiment_score,
                        confidence=0.3 if detected else 0.15,
                        raw_payload=article if isinstance(article, dict) else {"headline": headline},
                    )
                )
            return items, None
        except Exception as exc:
            return [], str(exc)

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
