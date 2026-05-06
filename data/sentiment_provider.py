from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from urllib.request import Request, urlopen

from config.settings import Settings


@dataclass(slots=True, frozen=True)
class SentimentProviderStatus:
    source: str
    status: str
    checked_at: str
    last_error: str | None


@dataclass(slots=True, frozen=True)
class SentimentSnapshot:
    source: str
    sentiment_label: str
    sentiment_score: float
    confidence: float
    snapshot_time: str
    raw_payload: dict[str, object]


class SentimentProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch_latest(self) -> tuple[SentimentProviderStatus, SentimentSnapshot | None]:
        checked_at = datetime.now(timezone.utc).isoformat()
        if not self._settings.sentiment_enabled:
            return SentimentProviderStatus("ALTERNATIVE_ME_FNG", "DISABLED", checked_at, None), None
        request = Request(
            self._settings.alternative_me_fng_url,
            headers={"User-Agent": "multiagent-trading-system/0.1"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            entry = (payload.get("data") or [{}])[0]
            value = float(entry.get("value", 50.0))
            label = str(entry.get("value_classification", "NEUTRAL")).upper().replace(" ", "_")
            normalized = round((value - 50.0) / 50.0, 6)
            snapshot = SentimentSnapshot(
                source="ALTERNATIVE_ME_FNG",
                sentiment_label=label,
                sentiment_score=normalized,
                confidence=0.5,
                snapshot_time=str(entry.get("timestamp", checked_at)),
                raw_payload=payload,
            )
            return SentimentProviderStatus("ALTERNATIVE_ME_FNG", "OK", checked_at, None), snapshot
        except Exception as exc:
            return SentimentProviderStatus("ALTERNATIVE_ME_FNG", "FAIL", checked_at, str(exc)), None


def sentiment_snapshot_to_payload(snapshot: SentimentSnapshot) -> str:
    return json.dumps(
        {
            "source": snapshot.source,
            "sentiment_label": snapshot.sentiment_label,
            "sentiment_score": snapshot.sentiment_score,
            "confidence": snapshot.confidence,
            "snapshot_time": snapshot.snapshot_time,
            "raw_payload": snapshot.raw_payload,
        },
        ensure_ascii=True,
    )
