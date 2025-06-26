from datetime import timedelta
from django.db import models


class OrderSide(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"


class SignalType(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"
    WAIT = "wait", "Wait"


class OrderType(models.TextChoices):
    MARKET = "market", "Market"
    LIMIT = "limit", "Limit"
    STOP = "stop", "Stop"


class ProxyProtocol(models.TextChoices):
    SOCKS5 = "socks5", "Socks5"
    SOCKS4 = "socks4", "Socks4"


class Timeframe(models.TextChoices):
    ONE_MINUTE = "1m", "1 Minute"
    FIVE_MINUTES = "5m", "5 Minutes"
    FIFTEEN_MINUTES = "15m", "15 Minutes"
    ONE_HOUR = "1h", "1 Hour"
    FOUR_HOURS = "4h", "4 Hours"
    ONE_DAY = "1d", "1 Day"
    ONE_WEEK = "1w", "1 Week"

    def timedelta(self) -> timedelta:
        return {
            self.ONE_MINUTE: timedelta(minutes=1),
            self.FIVE_MINUTES: timedelta(minutes=5),
            self.FIFTEEN_MINUTES: timedelta(minutes=15),
            self.ONE_HOUR: timedelta(hours=1),
            self.FOUR_HOURS: timedelta(hours=4),
            self.ONE_DAY: timedelta(days=1),
            self.ONE_WEEK: timedelta(weeks=1),
        }[self]


class OrderStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    CANCELED = "canceled", "Canceled"


class TradingPair(models.TextChoices):
    BTC_USDT = "BTC/USDT", "BTC/USDT"
    ETH_USDT = "ETH/USDT", "ETH/USDT"
    ADA_USDT = "ADA/USDT", "ADA/USDT"
    XRP_USDT = "XRP/USDT", "XRP/USDT"


class PositionType(models.TextChoices):
    LONG = "LONG", "Long"
    SHORT = "SHORT", "Short"


class PositionStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class TraderStatus(models.TextChoices):
    TRADING = "TRADING", "Trading"
    REBOOTING = "REBOOTING", "Rebooting"
