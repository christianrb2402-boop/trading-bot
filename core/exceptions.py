"""Excepciones del dominio."""


class TradingSystemError(Exception):
    """Excepcion base del sistema."""


class ConfigurationError(TradingSystemError):
    """Error de configuracion."""


class ExternalServiceError(TradingSystemError):
    """Error al comunicarse con un servicio externo."""


class DatabaseError(TradingSystemError):
    """Error de persistencia."""

