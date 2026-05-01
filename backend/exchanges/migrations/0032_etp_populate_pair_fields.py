"""Data migration: copy TradingPair fields into ExchangeTradingPair.

Часть рефактора объединения TradingPair → ExchangeTradingPair.
Фаза 1: после добавления nullable-полей в ExchangeTradingPair (миграция
0031) копируем значения name/base_currency/quote_currency/settle_currency/
type/is_linear из связанной TradingPair в каждый ExchangeTradingPair.
"""

from django.db import migrations


def copy_trading_pair_fields(apps, schema_editor):
    ExchangeTradingPair = apps.get_model("exchanges", "ExchangeTradingPair")
    qs = ExchangeTradingPair.objects.select_related("trading_pair").all()
    to_update = []
    for etp in qs:
        tp = etp.trading_pair
        etp.name = tp.name
        etp.base_currency = tp.base_currency
        etp.quote_currency = tp.quote_currency
        etp.settle_currency = tp.settle_currency
        etp.type = tp.type
        etp.is_linear = tp.is_linear
        to_update.append(etp)
    ExchangeTradingPair.objects.bulk_update(
        to_update,
        fields=[
            "name",
            "base_currency",
            "quote_currency",
            "settle_currency",
            "type",
            "is_linear",
        ],
        batch_size=1000,
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0031_etp_add_pair_fields"),
    ]

    operations = [
        migrations.RunPython(copy_trading_pair_fields, reverse_code=noop),
    ]
