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
    KAS_USDT = "KAS/USDT", "KAS/USDT"
    DEEP_USDT = "DEEP/USDT", "DEEP/USDT"
    DOGE_USDT = "DOGE/USDT", "DOGE/USDT"
    LINK_USDT = "LINK/USDT", "LINK/USDT"
    SHIB1000_USDT = "SHIB1000/USDT", "SHIB1000/USDT"
    AVAX_USDT = "AVAX/USDT", "AVAX/USDT"
    MLN_USDT = "MLN/USDT", "MLN/USDT"
    DOT_USDT = "DOT/USDT", "DOT/USDT"
    # 10000WHY_USDT = '10000WHY/USDT', '10000WHY/USDT'
    BIO_USDT = "BIO/USDT", "BIO/USDT"
    CLOUD_USDT = "CLOUD/USDT", "CLOUD/USDT"
    CORE_USDT = "CORE/USDT", "CORE/USDT"
    RONIN_USDT = "RONIN/USDT", "RONIN/USDT"
    SHELLU_SDT = "SHELLU/SDT", "SHELLU/SDT"
    SOLAYER_USDT = "SOLAYER/USDT", "SOLAYER/USDT"
    VIRTUAL_USDT = "VIRTUAL/USDT", "VIRTUAL/USDT"
    ARB_USDT = "ARB/USDT", "ARB/USDT"
    BSV_USDT = "BSV/USDT", "BSV/USDT"
    DOGS_USDT = "DOGS/USDT", "DOGS/USDT"
    GMT_USDT = "GMT/USDT", "GMT/USDT"
    NTRN_USDT = "NTRN/USDT", "NTRN/USDT"
    COTI_USDT = "COTI/USDT", "COTI/USDT"
    KOMA_USDT = "KOMA/USDT", "KOMA/USDT"
    BMT_USDT = "BMT/USDT", "BMT/USDT"
    THE_USDT = "THE/USDT", "THE/USDT"
    GODS_USDT = "GODS/USDT", "GODS/USDT"
    ZRO_USDT = "ZRO/USDT", "ZRO/USDT"
    CAKE_USDT = "CAKE/USDT", "CAKE/USDT"
    TRX_USDT = "TRX/USDT", "TRX/USDT"
    PARTI_USDT = "PARTI/USDT", "PARTI/USDT"
    XTER_USDT = "XTER/USDT", "XTER/USDT"
    SYN_USDT = "SYN/USDT", "SYN/USDT"
    ACX_USDT = "ACX/USDT", "ACX/USDT"
    # 1000TURBO_USDT = '1000TURBO/USDT', '1000TURBO/USDT'
    MAVIA_USDT = "MAVIA/USDT", "MAVIA/USDT"
    XCN_USDT = "XCN/USDT", "XCN/USDT"
    CETUS_USDT = "CETUS/USDT", "CETUS/USDT"
    AIXBT_USDT = "AIXBT/USDT", "AIXBT/USDT"
    SUI_USDT = "SUI/USDT", "SUI/USDT"
    XRD_USDT = "XRD/USDT", "XRD/USDT"
    PROMPT_USDT = "PROMPT/USDT", "PROMPT/USDT"
    SPELL_USDT = "SPELL/USDT", "SPELL/USDT"
    # 1000CAT_USDT = '1000CAT/USDT', '1000CAT/USDT'
    PNUT_USDT = "PNUT/USDT", "PNUT/USDT"
    # 1000X_USDT = '1000X/USDT', '1000X/USDT'
    AR_USDT = "AR/USDT", "AR/USDT"
    MICHI_USDT = "MICHI/USDT", "MICHI/USDT"
    MERL_USDT = "MERL/USDT", "MERL/USDT"
    # 1000CATS_USDT = '1000CATS/USDT', '1000CATS/USDT'
    AVAIL_USDT = "AVAIL/USDT", "AVAIL/USDT"
    AI_USDT = "AI/USDT", "AI/USDT"
    UNI_USDT = "UNI/USDT", "UNI/USDT"
    IP_USDT = "IP/USDT", "IP/USDT"
    ZEN_USDT = "ZEN/USDT", "ZEN/USDT"
    AEVO_USDT = "AEVO/USDT", "AEVO/USDT"
    AI16Z_USDT = "AI16Z/USDT", "AI16Z/USDT"
    LOOKS_USDT = "LOOKS/USDT", "LOOKS/USDT"
    XVG_USDT = "XVG/USDT", "XVG/USDT"
    SLERF_USDT = "SLERF/USDT", "SLERF/USDT"
    GMX_USDT = "GMX/USDT", "GMX/USDT"
    RENDER_USDT = "RENDER/USDT", "RENDER/USDT"
    TNSR_USDT = "TNSR/USDT", "TNSR/USDT"
    GALA_USDT = "GALA/USDT", "GALA/USDT"
    IO_USDT = "IO/USDT", "IO/USDT"
    RPL_USDT = "RPL/USDT", "RPL/USDT"
    SWEAT_USDT = "SWEAT/USDT", "SWEAT/USDT"
    TIA_USDT = "TIA/USDT", "TIA/USDT"
    BLAST_USDT = "BLAST/USDT", "BLAST/USDT"
    # 1000BTT_USDT = '1000BTT/USDT', '1000BTT/USDT'
    CPOOL_USDT = "CPOOL/USDT", "CPOOL/USDT"
    ONT_USDT = "ONT/USDT", "ONT/USDT"
    ETC_USDT = "ETC/USDT", "ETC/USDT"
    SUN_USDT = "SUN/USDT", "SUN/USDT"
    DGB_USDT = "DGB/USDT", "DGB/USDT"
    PORTAL_USDT = "PORTAL/USDT", "PORTAL/USDT"
    STG_USDT = "STG/USDT", "STG/USDT"
    PIXEL_USDT = "PIXEL/USDT", "PIXEL/USDT"
    S_USDT = "S/USDT", "S/USDT"
    # 1000RATS_USDT = '1000RATS/USDT', '1000RATS/USDT'
    RIF_USDT = "RIF/USDT", "RIF/USDT"
    WAXP_USDT = "WAXP/USDT", "WAXP/USDT"
    NS_USDT = "NS/USDT", "NS/USDT"
    OSMO_USDT = "OSMO/USDT", "OSMO/USDT"
    MOBILE_USDT = "MOBILE/USDT", "MOBILE/USDT"
    ANKR_USDT = "ANKR/USDT", "ANKR/USDT"
    ALICE_USDT = "ALICE/USDT", "ALICE/USDT"


class PositionType(models.TextChoices):
    LONG = "long", "Long"
    SHORT = "short", "Short"


class PositionStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class TraderStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    REBOOTING = "rebooting", "Rebooting"
