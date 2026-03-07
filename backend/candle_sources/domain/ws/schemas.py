from dataclasses import dataclass
from typing import Any

from exchanges.domain import Exchange, Timeframe, TradingPair


@dataclass
class SubscriptionConfig:
    """Подписка на OHLCV одного источника свечей."""

    source_id: int
    exchange: Exchange
    trading_pair: TradingPair
    timeframe: Timeframe
    exchange_client: Any  # AbstractExchangeClient
