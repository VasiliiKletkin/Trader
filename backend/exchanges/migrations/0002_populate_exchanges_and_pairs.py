# Data migration to populate Exchange and TradingPair objects

from decimal import Decimal

from django.db import migrations


def populate_exchanges_and_pairs(apps, schema_editor):
    Exchange = apps.get_model("exchanges", "Exchange")
    TradingPair = apps.get_model("exchanges", "TradingPair")

    exchanges_data = [
        {"name": "Binance", "class_name": "BinanceExchangeClient", "candle_fetch_limit": 1000},
        {"name": "Bybit", "class_name": "ByBitExchangeClient", "candle_fetch_limit": 1000},
        {"name": "OKX", "class_name": "OKXExchangeClient", "candle_fetch_limit": 300},
        {"name": "Kraken", "class_name": "KrakenExchangeClient", "candle_fetch_limit": 720},
        {"name": "Bitget", "class_name": "BitgetExchangeClient", "candle_fetch_limit": 200},
        {"name": "Coinbase", "class_name": "CoinbaseExchangeClient", "candle_fetch_limit": 300},
        {"name": "KuCoin", "class_name": "KuCoinExchangeClient", "candle_fetch_limit": 200},
        {"name": "Gate.io", "class_name": "GateIOExchangeClient", "candle_fetch_limit": 1000},
        {"name": "HTX", "class_name": "HTXExchangeClient", "candle_fetch_limit": 2000},
        {"name": "MEXC", "class_name": "MEXCExchangeClient", "candle_fetch_limit": 1000},
        {"name": "Phemex", "class_name": "PhemexExchangeClient", "candle_fetch_limit": 1000},
        {"name": "Deribit", "class_name": "DeribitExchangeClient", "candle_fetch_limit": 5000},
        {"name": "BitMEX", "class_name": "BitMEXExchangeClient", "candle_fetch_limit": 1000},
        {"name": "Bitfinex", "class_name": "BitfinexExchangeClient", "candle_fetch_limit": 10000},
    ]

    for data in exchanges_data:
        Exchange.objects.update_or_create(
            class_name=data["class_name"],
            defaults={"name": data["name"], "candle_fetch_limit": data["candle_fetch_limit"]},
        )

    trading_pairs_data = [
        ("BTC/USDT", "BTC/USDT:USDT", "0.001", "1000"),
        ("ETH/USDT", "ETH/USDT:USDT", "0.01", "10000"),
        ("BNB/USDT", "BNB/USDT:USDT", "0.01", "10000"),
        ("XRP/USDT", "XRP/USDT:USDT", "1", "1000000"),
        ("SOL/USDT", "SOL/USDT:USDT", "0.1", "100000"),
        ("ADA/USDT", "ADA/USDT:USDT", "1", "1000000"),
        ("DOGE/USDT", "DOGE/USDT:USDT", "1", "10000000"),
        ("TRX/USDT", "TRX/USDT:USDT", "1", "10000000"),
        ("AVAX/USDT", "AVAX/USDT:USDT", "0.1", "100000"),
        ("DOT/USDT", "DOT/USDT:USDT", "0.1", "100000"),
        ("MATIC/USDT", "MATIC/USDT:USDT", "1", "1000000"),
        ("LINK/USDT", "LINK/USDT:USDT", "0.1", "100000"),
        ("ATOM/USDT", "ATOM/USDT:USDT", "0.1", "100000"),
        ("LTC/USDT", "LTC/USDT:USDT", "0.01", "10000"),
        ("UNI/USDT", "UNI/USDT:USDT", "0.1", "100000"),
        ("BCH/USDT", "BCH/USDT:USDT", "0.01", "10000"),
        ("ETC/USDT", "ETC/USDT:USDT", "0.1", "100000"),
        ("NEAR/USDT", "NEAR/USDT:USDT", "0.1", "100000"),
        ("FIL/USDT", "FIL/USDT:USDT", "0.1", "100000"),
        ("APT/USDT", "APT/USDT:USDT", "0.1", "100000"),
        ("AAVE/USDT", "AAVE/USDT:USDT", "0.01", "10000"),
        ("CRV/USDT", "CRV/USDT:USDT", "1", "1000000"),
        ("MKR/USDT", "MKR/USDT:USDT", "0.001", "1000"),
        ("SNX/USDT", "SNX/USDT:USDT", "0.1", "100000"),
        ("COMP/USDT", "COMP/USDT:USDT", "0.01", "10000"),
        ("LDO/USDT", "LDO/USDT:USDT", "1", "1000000"),
        ("SUSHI/USDT", "SUSHI/USDT:USDT", "1", "1000000"),
        ("1INCH/USDT", "1INCH/USDT:USDT", "1", "1000000"),
        ("SAND/USDT", "SAND/USDT:USDT", "1", "1000000"),
        ("MANA/USDT", "MANA/USDT:USDT", "1", "1000000"),
        ("AXS/USDT", "AXS/USDT:USDT", "0.1", "100000"),
        ("ENJ/USDT", "ENJ/USDT:USDT", "1", "1000000"),
        ("GALA/USDT", "GALA/USDT:USDT", "10", "10000000"),
        ("IMX/USDT", "IMX/USDT:USDT", "1", "1000000"),
        ("GRT/USDT", "GRT/USDT:USDT", "1", "1000000"),
        ("FET/USDT", "FET/USDT:USDT", "1", "1000000"),
        ("RNDR/USDT", "RNDR/USDT:USDT", "0.1", "100000"),
        ("INJ/USDT", "INJ/USDT:USDT", "0.1", "100000"),
        ("AR/USDT", "AR/USDT:USDT", "0.1", "100000"),
        ("FTT/USDT", "FTT/USDT:USDT", "0.1", "100000"),
        ("OKB/USDT", "OKB/USDT:USDT", "0.1", "100000"),
        ("CRO/USDT", "CRO/USDT:USDT", "1", "10000000"),
        ("SHIB/USDT", "SHIB/USDT:USDT", "100000", "100000000000"),
        ("PEPE/USDT", "PEPE/USDT:USDT", "1000000", "100000000000"),
        ("FLOKI/USDT", "FLOKI/USDT:USDT", "10000", "100000000000"),
        ("WIF/USDT", "WIF/USDT:USDT", "1", "1000000"),
        ("BONK/USDT", "BONK/USDT:USDT", "100000", "100000000000"),
        ("OP/USDT", "OP/USDT:USDT", "0.1", "100000"),
        ("ARB/USDT", "ARB/USDT:USDT", "0.1", "100000"),
        ("SUI/USDT", "SUI/USDT:USDT", "1", "1000000"),
        ("SEI/USDT", "SEI/USDT:USDT", "1", "1000000"),
        ("TIA/USDT", "TIA/USDT:USDT", "0.1", "100000"),
    ]

    for name, symbol, min_amount, max_amount in trading_pairs_data:
        TradingPair.objects.get_or_create(
            name=name,
            defaults={
                "symbol": symbol,
                "min_amount": Decimal(min_amount),
                "max_amount": Decimal(max_amount),
                "fee_percent": Decimal("0.1"),
            },
        )

    ExchangeTradingPair = apps.get_model("exchanges", "ExchangeTradingPair")
    kraken = Exchange.objects.filter(name="Kraken").first()
    deribit = Exchange.objects.filter(name="Deribit").first()
    btc = TradingPair.objects.filter(name="BTC/USDT").first()
    eth = TradingPair.objects.filter(name="ETH/USDT").first()

    custom_pairs = [
        (kraken, btc, "PF_XBTUSD", "0.001", "1000", "0.02"),
        (kraken, eth, "PF_ETHUSD", "0.01", "10000", "0.02"),
        (deribit, btc, "BTC-PERPETUAL", "0.001", "1000", "0.05"),
        (deribit, eth, "ETH-PERPETUAL", "0.01", "10000", "0.05"),
    ]
    for exchange, pair, symbol, min_amt, max_amt, fee in custom_pairs:
        if exchange and pair:
            ExchangeTradingPair.objects.get_or_create(
                exchange=exchange,
                trading_pair=pair,
                defaults={
                    "symbol": symbol,
                    "min_amount": Decimal(min_amt),
                    "max_amount": Decimal(max_amt),
                    "fee_percent": Decimal(fee),
                },
            )


def reverse_populate(apps, schema_editor):
    Exchange = apps.get_model("exchanges", "Exchange")
    TradingPair = apps.get_model("exchanges", "TradingPair")
    ExchangeTradingPair = apps.get_model("exchanges", "ExchangeTradingPair")

    ExchangeTradingPair.objects.filter(
        symbol__in=["PF_XBTUSD", "PF_ETHUSD", "BTC-PERPETUAL", "ETH-PERPETUAL"]
    ).delete()
    Exchange.objects.all().delete()
    TradingPair.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(populate_exchanges_and_pairs, reverse_populate),
    ]
