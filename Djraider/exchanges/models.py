from datetime import timedelta
from django.db import models
import requests


class ProxyProtocol(models.TextChoices):
    SOCKS5 = "socks5", "Socks5"
    SOCKS4 = "socks4", "Socks4"


class Proxy(models.Model):
    is_active = models.BooleanField(default=False)

    protocol = models.CharField(
        max_length=10,
        choices=ProxyProtocol.choices,
        default=ProxyProtocol.SOCKS5,
    )
    address = models.CharField(max_length=100, unique=True)
    port = models.IntegerField()
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=100)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    errors = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.protocol}://{self.username}:{self.password}@{self.address}:{self.port}"

    @property
    def is_ready(self):
        return self.is_active and not self.errors

    def check_obj(self):
        try:
            proxies = {"http": str(self)}
            response = requests.get(
                "http://www.httpbin.org/ip",
                proxies=proxies,
            )
            resp_data = response.json()

            if resp_data["origin"] != self.address:
                raise Exception(
                    f'Ip address{self.address} is not equal from http://www.httpbin.org/ip {resp_data["origin"]}'
                )

        except Exception as error:
            self.error = str(error)
        else:
            self.error = None
        finally:
            self.save()

    def get_proxy_dict(self):
        return {
            "proxy_type": self.protocol,
            "addr": self.address,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "rdns": True,
        }


class TradingPair(models.Model):
    name = models.CharField(max_length=15)

    def __str__(self):
        return self.name


class Timeframe(models.TextChoices):
    ONE_MINUTE = "1m", "1 Minute"
    FIVE_MINUTES = "5m", "5 Minutes"
    FIFTEEN_MINUTES = "15m", "15 Minutes"
    ONE_HOUR = "1h", "1 Hour"
    FOUR_HOURS = "4h", "4 Hours"
    ONE_DAY = "1d", "1 Day"
    ONE_WEEK = "1w", "1 Week"

    def to_timedelta(self) -> timedelta:
        return {
            self.ONE_MINUTE: timedelta(minutes=1),
            self.FIVE_MINUTES: timedelta(minutes=5),
            self.FIFTEEN_MINUTES: timedelta(minutes=15),
            self.ONE_HOUR: timedelta(hours=1),
            self.FOUR_HOURS: timedelta(hours=4),
            self.ONE_DAY: timedelta(days=1),
            self.ONE_WEEK: timedelta(weeks=1),
        }[self]


class Exchange(models.Model):
    is_active = models.BooleanField(default=False)
    name = models.CharField(max_length=20)
    api_key = models.CharField(max_length=200)
    api_secret = models.CharField(max_length=200)
    demo = models.BooleanField(default=True)
    proxy = models.ForeignKey(Proxy, models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
