from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from config.settings import Settings
from core.database import Database, NewsEventRecord, SentimentSnapshotRecord
from data.news_provider import NewsProvider, news_item_to_payload
from data.sentiment_provider import SentimentProvider, sentiment_snapshot_to_payload


def refresh_external_context(
    *,
    database: Database,
    settings: Settings,
    symbols: Iterable[str],
    limit: int = 5,
) -> dict[str, object]:
    news_provider = NewsProvider(settings)
    sentiment_provider = SentimentProvider(settings)

    news_status, news_items = news_provider.fetch_latest(symbols=symbols, limit=limit)
    for item in news_items:
        database.insert_news_event(
            NewsEventRecord(
                source=item.source,
                headline=item.headline,
                event_time=item.event_time,
                detected_symbols=",".join(item.detected_symbols),
                sentiment_score=item.sentiment_score,
                confidence=item.confidence,
                raw_payload=news_item_to_payload(item),
            )
        )

    sentiment_status, sentiment_snapshot = sentiment_provider.fetch_latest()
    if sentiment_snapshot is not None:
        database.insert_sentiment_snapshot(
            SentimentSnapshotRecord(
                source=sentiment_snapshot.source,
                sentiment_label=sentiment_snapshot.sentiment_label,
                sentiment_score=sentiment_snapshot.sentiment_score,
                confidence=sentiment_snapshot.confidence,
                snapshot_time=sentiment_snapshot.snapshot_time,
                raw_payload=sentiment_snapshot_to_payload(sentiment_snapshot),
            )
        )

    return {
        "news_status": {
            "source": news_status.source,
            "status": news_status.status,
            "checked_at": news_status.checked_at,
            "items_detected": news_status.items_detected,
            "last_error": news_status.last_error,
        },
        "sentiment_status": {
            "source": sentiment_status.source,
            "status": sentiment_status.status,
            "checked_at": sentiment_status.checked_at,
            "last_error": sentiment_status.last_error,
        },
        "latest_news": database.get_recent_news_events(limit=10),
        "latest_sentiment": database.get_recent_sentiment_snapshots(limit=10),
    }


def build_symbol_context_bias(
    *,
    database: Database,
    symbol: str,
    direction: str,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    relevant_news: list[dict[str, Any]] = []
    for row in database.get_recent_news_events(limit=20):
        detected_symbols_raw = str(row.get("detected_symbols") or "")
        detected_symbols = {item.strip().upper() for item in detected_symbols_raw.replace("[", "").replace("]", "").replace('"', "").split(",") if item.strip()}
        event_time_raw = str(row.get("event_time") or "")
        try:
            event_time = datetime.fromisoformat(event_time_raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                event_time = parsedate_to_datetime(event_time_raw)
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                event_time = datetime.now(timezone.utc)
        if event_time < cutoff:
            continue
        if symbol.upper() in detected_symbols or symbol.replace("USDT", "") in detected_symbols_raw.upper():
            relevant_news.append(row)

    news_used = bool(relevant_news)
    avg_news_sentiment = (
        sum(float(row.get("sentiment_score") or 0.0) * float(row.get("confidence") or 0.0) for row in relevant_news)
        / max(sum(float(row.get("confidence") or 0.0) for row in relevant_news), 0.000001)
        if relevant_news
        else 0.0
    )
    recent_sentiment = database.get_recent_sentiment_snapshots(limit=1)
    latest_sentiment = recent_sentiment[0] if recent_sentiment else None
    sentiment_score = float(latest_sentiment.get("sentiment_score") or 0.0) if latest_sentiment else 0.0
    sentiment_used = latest_sentiment is not None

    confidence_adjustment = 0.0
    contradiction_penalty = 0.0
    risk_event = False
    market_caution = False
    news_conflict = False

    if direction == "LONG":
        if avg_news_sentiment <= -0.35:
            confidence_adjustment -= 0.08
            contradiction_penalty += 0.12
            news_conflict = True
        elif avg_news_sentiment >= 0.2:
            confidence_adjustment += 0.04
        if sentiment_score <= -0.5:
            confidence_adjustment -= 0.05
            contradiction_penalty += 0.08
        elif sentiment_score >= 0.4:
            confidence_adjustment += 0.03
    elif direction == "SHORT":
        if avg_news_sentiment >= 0.35:
            confidence_adjustment -= 0.08
            contradiction_penalty += 0.12
            news_conflict = True
        elif avg_news_sentiment <= -0.2:
            confidence_adjustment += 0.04
        if sentiment_score >= 0.5:
            confidence_adjustment -= 0.05
            contradiction_penalty += 0.08
        elif sentiment_score <= -0.4:
            confidence_adjustment += 0.03

    if abs(avg_news_sentiment) >= 0.5 or abs(sentiment_score) >= 0.7:
        risk_event = True
        market_caution = True
        contradiction_penalty += 0.05

    if len(relevant_news) >= 3 and abs(avg_news_sentiment) >= 0.25:
        market_caution = True

    return {
        "news_used": news_used,
        "sentiment_used": sentiment_used,
        "news_conflict": news_conflict,
        "risk_event": risk_event,
        "market_caution": market_caution,
        "confidence_adjustment": round(max(-0.15, min(0.15, confidence_adjustment)), 6),
        "contradiction_penalty": round(max(0.0, min(0.2, contradiction_penalty)), 6),
        "avg_news_sentiment": round(avg_news_sentiment, 6),
        "sentiment_score": round(sentiment_score, 6),
        "headline_count": len(relevant_news),
        "recent_headlines": [str(row.get("headline") or "") for row in relevant_news[:5]],
    }
