"""
Общие helper-функции для тестов.

Этот модуль содержит утилиты для создания тестовых данных,
используемые в доменных тестах всех приложений.
"""

from decimal import Decimal
from datetime import datetime, timezone

from exchanges.domain import ExchangeCandle
from candle_providers.domain import ProviderCandle


def build_provider_candle(exchange_candle: ExchangeCandle) -> ProviderCandle:
    """
    Конвертирует ExchangeCandle в ProviderCandle.

    Args:
        exchange_candle: Исходная биржевая свеча

    Returns:
        ProviderCandle: Обертка провайдера со ссылкой на primary_candle
    """
    return ProviderCandle(
        dt_unix=exchange_candle.dt_unix,
        open=exchange_candle.open,
        high=exchange_candle.high,
        low=exchange_candle.low,
        close=exchange_candle.close,
        volume=exchange_candle.volume,
        primary_candle=exchange_candle,
        secondary_candle=None,
    )


def make_test_candle(
    close: Decimal = Decimal("100"),
    candle_id: int = 1,
    dt_unix: int | None = None,
) -> ProviderCandle:
    """
    Создает тестовую ProviderCandle с заданной ценой закрытия.

    Автоматически генерирует OHLV значения на основе close:
    - open = close
    - high = close + 10
    - low = close - 10
    - volume = 1000

    Args:
        close: Цена закрытия свечи
        candle_id: ID свечи (по умолчанию 1)
        dt_unix: Unix timestamp в миллисекундах (по умолчанию текущее время)

    Returns:
        ProviderCandle: Тестовая свеча с сгенерированными значениями
    """
    if dt_unix is None:
        dt_unix = int(datetime.now(timezone.utc).timestamp() * 1000)

    exchange_candle = ExchangeCandle(
        id=candle_id,
        dt_unix=dt_unix,
        open=close,
        high=close + Decimal("10"),
        low=close - Decimal("10"),
        close=close,
        volume=Decimal("1000"),
    )
    return build_provider_candle(exchange_candle)


def build_candle(
    dt_unix: int,
    open_price: Decimal = Decimal("100"),
    high_price: Decimal = Decimal("110"),
    low_price: Decimal = Decimal("90"),
    close_price: Decimal = Decimal("105"),
    volume: Decimal = Decimal("1000"),
) -> ExchangeCandle:
    """
    Создает ExchangeCandle с заданными параметрами.

    Используется в тестах candle_sources для создания
    биржевых свечей с полным контролем над OHLCV.

    Args:
        dt_unix: Unix timestamp в миллисекундах
        open_price: Цена открытия
        high_price: Максимальная цена
        low_price: Минимальная цена
        close_price: Цена закрытия
        volume: Объем

    Returns:
        ExchangeCandle: Биржевая свеча
    """
    return ExchangeCandle(
        id=1,
        dt_unix=dt_unix,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )
