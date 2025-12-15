from pydantic import BaseModel
from typing import Literal


class ExchangeClientProxy(BaseModel):
    protocol: Literal["http", "socks5", "socks4", "https"] = "socks5"
    host: str
    port: str
    username: str
    password: str
