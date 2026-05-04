from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class WebsocketProviderStatus:
    provider: str
    status: str
    latency_ms: float
    heartbeat_ok: bool
    reconnect_attempts: int
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "heartbeat_ok": self.heartbeat_ok,
            "reconnect_attempts": self.reconnect_attempts,
            "reason": self.reason,
        }


class BinanceWebsocketProvider:
    name = "BINANCE_WEBSOCKET_PREPARED"

    def heartbeat(self) -> WebsocketProviderStatus:
        return WebsocketProviderStatus(
            provider=self.name,
            status="PREPARED_ONLY",
            latency_ms=0.0,
            heartbeat_ok=False,
            reconnect_attempts=0,
            reason="websocket provider is scaffolded but not activated yet; REST remains authoritative",
        )
