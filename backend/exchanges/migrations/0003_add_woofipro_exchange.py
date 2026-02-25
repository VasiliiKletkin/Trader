from django.db import migrations


def add_exchanges(apps, schema_editor):
    Exchange = apps.get_model("exchanges", "Exchange")
    exchanges = [
        {"name": "WOOFI PRO", "class_name": "WooFiProExchangeClient", "candle_fetch_limit": 1000},
        {"name": "Paradex", "class_name": "ParadexExchangeClient", "candle_fetch_limit": 1000},
        {"name": "Hyperliquid", "class_name": "HyperliquidExchangeClient", "candle_fetch_limit": 5000},
    ]
    for data in exchanges:
        Exchange.objects.update_or_create(
            class_name=data["class_name"],
            defaults={"name": data["name"], "candle_fetch_limit": data["candle_fetch_limit"]},
        )


def remove_exchanges(apps, schema_editor):
    Exchange = apps.get_model("exchanges", "Exchange")
    Exchange.objects.filter(
        class_name__in=[
            "WooFiProExchangeClient",
            "ParadexExchangeClient",
            "HyperliquidExchangeClient",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0002_populate_exchanges_and_pairs"),
    ]

    operations = [
        migrations.RunPython(add_exchanges, remove_exchanges),
    ]
