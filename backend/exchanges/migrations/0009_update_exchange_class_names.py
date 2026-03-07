# Data migration: обновление class_name с имён клиентов на имена бирж

from django.db import migrations

CLASS_NAME_MAP = {
    "BinanceExchangeClient": "BinanceExchange",
    "ByBitExchangeClient": "BybitExchange",
    "OKXExchangeClient": "OKXExchange",
    "KrakenExchangeClient": "KrakenExchange",
    "BitgetExchangeClient": "BitgetExchange",
    "CoinbaseExchangeClient": "CoinbaseExchange",
    "KuCoinExchangeClient": "KuCoinExchange",
    "GateIOExchangeClient": "GateIOExchange",
    "HTXExchangeClient": "HTXExchange",
    "MEXCExchangeClient": "MEXCExchange",
    "PhemexExchangeClient": "PhemexExchange",
    "DeribitExchangeClient": "DeribitExchange",
    "BitMEXExchangeClient": "BitMEXExchange",
    "BitfinexExchangeClient": "BitfinexExchange",
    "WooFiProExchangeClient": "WooFiProExchange",
    "ParadexExchangeClient": "ParadexExchange",
    "HyperliquidExchangeClient": "HyperliquidExchange",
    "CoinExExchangeClient": "CoinExExchange",
}


def update_class_names(apps, schema_editor):
    Exchange = apps.get_model("exchanges", "Exchange")
    for old_name, new_name in CLASS_NAME_MAP.items():
        Exchange.objects.filter(class_name=old_name).update(class_name=new_name)


def reverse_class_names(apps, schema_editor):
    Exchange = apps.get_model("exchanges", "Exchange")
    for old_name, new_name in CLASS_NAME_MAP.items():
        Exchange.objects.filter(class_name=new_name).update(class_name=old_name)


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0008_alter_exchange_class_name"),
    ]

    operations = [
        migrations.RunPython(update_class_names, reverse_class_names),
    ]
