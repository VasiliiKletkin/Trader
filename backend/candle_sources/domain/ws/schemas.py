from dataclasses import dataclass


@dataclass
class ExchangeConfig:
    """Конфигурация подключения к бирже (без зависимостей от Django)."""

    class_name: str
    arguments: dict
    proxy_url: str | None

    def __hash__(self):
        args_key = tuple(sorted(self.arguments.items()))
        return hash((self.class_name, args_key, self.proxy_url))

    def __eq__(self, other):
        if not isinstance(other, ExchangeConfig):
            return False
        return (
            self.class_name == other.class_name
            and self.arguments == other.arguments
            and self.proxy_url == other.proxy_url
        )


@dataclass
class SubscriptionConfig:
    """Подписка на OHLCV одного источника свечей."""

    source_id: int
    symbol: str
    timeframe: str
    exchange_config: ExchangeConfig
