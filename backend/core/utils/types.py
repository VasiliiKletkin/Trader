from django.db import models


class OrderType(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"


class SignalType(models.TextChoices):
    BUY = "buy", "Buy"
    SELL = "sell", "Sell"
    HOLD = "hold", "Hold"


class ProxyProtocol(models.TextChoices):
    SOCKS5 = "socks5", "Socks5"
    SOCKS4 = "socks4", "Socks4"
