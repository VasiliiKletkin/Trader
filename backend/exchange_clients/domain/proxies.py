from typing import Literal

from pydantic import BaseModel


class ExchangeClientProxy(BaseModel):
    protocol: Literal["http", "socks5", "socks4", "https"] = "socks5"
    host: str
    port: str
    username: str
    password: str
