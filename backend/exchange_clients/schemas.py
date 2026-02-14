from django.db import models


class OrderSide(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"


class OrderType(models.TextChoices):
    MARKET = "market", "Market"
    LIMIT = "limit", "Limit"
    STOP = "stop", "Stop"


class OrderStatus(models.TextChoices):
    OPENED = "opened", "Opened"
    CLOSED = "closed", "Closed"
    CANCELED = "canceled", "Canceled"


class ProxyProtocol(models.TextChoices):
    SOCKS5 = "socks5", "Socks5"
    SOCKS4 = "socks4", "Socks4"
