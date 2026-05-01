"""Data migration: populate trading_pair_new on CandleSource,
ExchangeCandle, ExchangeClientOrder.

Часть рефактора объединения TradingPair → ExchangeTradingPair, фаза 2.
Для каждой записи в трёх таблицах находим соответствующий
ExchangeTradingPair (по exchange + trading_pair) и записываем в новую
FK trading_pair_new.

Используем ORM Subquery для всех трёх — это превращается в один SQL
UPDATE с подзапросом, что критично для ExchangeCandle (потенциально
миллионы строк).
"""

from django.db import migrations
from django.db.models import OuterRef, Subquery


def populate_trading_pair_new(apps, schema_editor):
    ETP = apps.get_model("exchanges", "ExchangeTradingPair")
    CandleSource = apps.get_model("candle_sources", "CandleSource")
    ExchangeCandle = apps.get_model("exchanges", "ExchangeCandle")
    ExchangeClient = apps.get_model("exchange_clients", "ExchangeClient")
    ExchangeClientOrder = apps.get_model(
        "exchange_clients", "ExchangeClientOrder"
    )

    # CandleSource — exchange и trading_pair прямо на модели
    CandleSource.objects.update(
        trading_pair_new=Subquery(
            ETP.objects.filter(
                exchange=OuterRef("exchange"),
                trading_pair=OuterRef("trading_pair"),
            ).values("id")[:1]
        )
    )

    # ExchangeCandle — exchange и trading_pair прямо на модели
    ExchangeCandle.objects.update(
        trading_pair_new=Subquery(
            ETP.objects.filter(
                exchange=OuterRef("exchange"),
                trading_pair=OuterRef("trading_pair"),
            ).values("id")[:1]
        )
    )

    # ExchangeClientOrder — exchange выводится через exchange_client,
    # делаем по одной бирже за раз для простоты SQL.
    for ec in ExchangeClient.objects.all().only("id", "exchange_id"):
        ExchangeClientOrder.objects.filter(exchange_client_id=ec.id).update(
            trading_pair_new=Subquery(
                ETP.objects.filter(
                    exchange_id=ec.exchange_id,
                    trading_pair=OuterRef("trading_pair"),
                ).values("id")[:1]
            )
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0033_add_trading_pair_new"),
        ("candle_sources", "0013_add_trading_pair_new"),
        ("exchange_clients", "0007_add_trading_pair_new"),
    ]

    operations = [
        migrations.RunPython(populate_trading_pair_new, reverse_code=noop),
    ]
