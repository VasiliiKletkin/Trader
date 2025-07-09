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
    OPENED = "opened", "Opened"
    CLOSED = "closed", "Closed"
    CANCELED = "canceled", "Canceled"


class TradingPair(models.TextChoices):
    BTC_USDT = "BTC/USDT:USDT", "BTC/USDT"
    ETH_USDT = "ETH/USDT:USDT", "ETH/USDT"
    ADA_USDT = "ADA/USDT:USDT", "ADA/USDT"
    XRP_USDT = "XRP/USDT:USDT", "XRP/USDT"
    KAS_USDT = "KAS/USDT:USDT", "KAS/USDT"
    DEEP_USDT = "DEEP/USDT:USDT", "DEEP/USDT"
    DOGE_USDT = "DOGE/USDT:USDT", "DOGE/USDT"
    LINK_USDT = "LINK/USDT:USDT", "LINK/USDT"
    SHIB1000_USDT = "SHIB1000/USDT:USDT", "SHIB1000/USDT"
    AVAX_USDT = "AVAX/USDT:USDT", "AVAX/USDT"
    MLN_USDT = "MLN/USDT:USDT", "MLN/USDT"
    DOT_USDT = "DOT/USDT:USDT", "DOT/USDT"
    BIO_USDT = "BIO/USDT:USDT", "BIO/USDT"
    CLOUD_USDT = "CLOUD/USDT:USDT", "CLOUD/USDT"
    CORE_USDT = "CORE/USDT:USDT", "CORE/USDT"
    RONIN_USDT = "RONIN/USDT:USDT", "RONIN/USDT"
    SHELLU_SDT = "SHELLU/SDT", "SHELLU/SDT"
    SOLAYER_USDT = "SOLAYER/USDT:USDT", "SOLAYER/USDT"
    VIRTUAL_USDT = "VIRTUAL/USDT:USDT", "VIRTUAL/USDT"
    ARB_USDT = "ARB/USDT:USDT", "ARB/USDT"
    BSV_USDT = "BSV/USDT:USDT", "BSV/USDT"
    DOGS_USDT = "DOGS/USDT:USDT", "DOGS/USDT"
    GMT_USDT = "GMT/USDT:USDT", "GMT/USDT"
    NTRN_USDT = "NTRN/USDT:USDT", "NTRN/USDT"
    COTI_USDT = "COTI/USDT:USDT", "COTI/USDT"
    KOMA_USDT = "KOMA/USDT:USDT", "KOMA/USDT"
    BMT_USDT = "BMT/USDT:USDT", "BMT/USDT"
    THE_USDT = "THE/USDT:USDT", "THE/USDT"
    GODS_USDT = "GODS/USDT:USDT", "GODS/USDT"
    ZRO_USDT = "ZRO/USDT:USDT", "ZRO/USDT"
    CAKE_USDT = "CAKE/USDT:USDT", "CAKE/USDT"
    TRX_USDT = "TRX/USDT:USDT", "TRX/USDT"
    PARTI_USDT = "PARTI/USDT:USDT", "PARTI/USDT"
    XTER_USDT = "XTER/USDT:USDT", "XTER/USDT"
    SYN_USDT = "SYN/USDT:USDT", "SYN/USDT"
    ACX_USDT = "ACX/USDT:USDT", "ACX/USDT"
    MAVIA_USDT = "MAVIA/USDT:USDT", "MAVIA/USDT"
    XCN_USDT = "XCN/USDT:USDT", "XCN/USDT"
    CETUS_USDT = "CETUS/USDT:USDT", "CETUS/USDT"
    AIXBT_USDT = "AIXBT/USDT:USDT", "AIXBT/USDT"
    SUI_USDT = "SUI/USDT:USDT", "SUI/USDT"
    XRD_USDT = "XRD/USDT:USDT", "XRD/USDT"
    PROMPT_USDT = "PROMPT/USDT:USDT", "PROMPT/USDT"
    SPELL_USDT = "SPELL/USDT:USDT", "SPELL/USDT"
    PNUT_USDT = "PNUT/USDT:USDT", "PNUT/USDT"
    AR_USDT = "AR/USDT:USDT", "AR/USDT"
    MICHI_USDT = "MICHI/USDT:USDT", "MICHI/USDT"
    MERL_USDT = "MERL/USDT:USDT", "MERL/USDT"
    AVAIL_USDT = "AVAIL/USDT:USDT", "AVAIL/USDT"
    AI_USDT = "AI/USDT:USDT", "AI/USDT"
    UNI_USDT = "UNI/USDT:USDT", "UNI/USDT"
    IP_USDT = "IP/USDT:USDT", "IP/USDT"
    ZEN_USDT = "ZEN/USDT:USDT", "ZEN/USDT"
    AEVO_USDT = "AEVO/USDT:USDT", "AEVO/USDT"
    AI16Z_USDT = "AI16Z/USDT:USDT", "AI16Z/USDT"
    LOOKS_USDT = "LOOKS/USDT:USDT", "LOOKS/USDT"
    XVG_USDT = "XVG/USDT:USDT", "XVG/USDT"
    SLERF_USDT = "SLERF/USDT:USDT", "SLERF/USDT"
    GMX_USDT = "GMX/USDT:USDT", "GMX/USDT"
    RENDER_USDT = "RENDER/USDT:USDT", "RENDER/USDT"
    TNSR_USDT = "TNSR/USDT:USDT", "TNSR/USDT"
    GALA_USDT = "GALA/USDT:USDT", "GALA/USDT"
    IO_USDT = "IO/USDT:USDT", "IO/USDT"
    RPL_USDT = "RPL/USDT:USDT", "RPL/USDT"
    SWEAT_USDT = "SWEAT/USDT:USDT", "SWEAT/USDT"
    TIA_USDT = "TIA/USDT:USDT", "TIA/USDT"
    BLAST_USDT = "BLAST/USDT:USDT", "BLAST/USDT"
    CPOOL_USDT = "CPOOL/USDT:USDT", "CPOOL/USDT"
    ONT_USDT = "ONT/USDT:USDT", "ONT/USDT"
    ETC_USDT = "ETC/USDT:USDT", "ETC/USDT"
    SUN_USDT = "SUN/USDT:USDT", "SUN/USDT"
    DGB_USDT = "DGB/USDT:USDT", "DGB/USDT"
    PORTAL_USDT = "PORTAL/USDT:USDT", "PORTAL/USDT"
    STG_USDT = "STG/USDT:USDT", "STG/USDT"
    PIXEL_USDT = "PIXEL/USDT:USDT", "PIXEL/USDT"
    S_USDT = "S/USDT:USDT", "S/USDT"
    RIF_USDT = "RIF/USDT:USDT", "RIF/USDT"
    WAXP_USDT = "WAXP/USDT:USDT", "WAXP/USDT"
    NS_USDT = "NS/USDT:USDT", "NS/USDT"
    OSMO_USDT = "OSMO/USDT:USDT", "OSMO/USDT"
    MOBILE_USDT = "MOBILE/USDT:USDT", "MOBILE/USDT"
    ANKR_USDT = "ANKR/USDT:USDT", "ANKR/USDT"
    ALICE_USDT = "ALICE/USDT:USDT", "ALICE/USDT"


class PositionType(models.TextChoices):
    LONG = "long", "Long"
    SHORT = "short", "Short"


class PositionStatus(models.TextChoices):
    OPENED = "opened", "Opened"
    CLOSED = "closed", "Closed"


class TraderStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    REBOOTING = "rebooting", "Rebooting"
