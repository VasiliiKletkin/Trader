class ExchangeClientProxy:

    def __init__(
        self,
        protocol: str,
        host: str,
        port: str,
        username: str,
        password: str,
    ):
        self.protocol = protocol
        self.host = host
        self.port = port
        self.username = username
        self.password = password
