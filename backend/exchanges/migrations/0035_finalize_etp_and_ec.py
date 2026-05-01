"""Finalize TradingPair → ExchangeTradingPair refactor.

Дропаем старые FK на TradingPair, переименовываем trading_pair_new в
trading_pair, делаем поля ETP non-null, обновляем unique constraints.
TradingPair модель дропается отдельной миграцией 0036_drop_tradingpair
(после того, как все FK на неё уйдут — включая в candle_sources/exchange_clients).
"""

from django.db import migrations, models


def _delete_orphan_candles(apps, schema_editor):
    """Удаляет ExchangeCandle, для которых не нашлось соответствующего
    ExchangeTradingPair в data-миграции 0034 (orphan строки с
    trading_pair_new=NULL). Без этой очистки AlterField на non-null
    падает с NotNullViolation на проде, где исторически могли копиться
    свечи для пар, которые больше нет в ExchangeTradingPair."""
    ExchangeCandle = apps.get_model("exchanges", "ExchangeCandle")
    ExchangeCandle.objects.filter(trading_pair_new__isnull=True).delete()


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0034_etp_populate_trading_pair_new"),
    ]

    operations = [
        # Удаляем orphan ExchangeCandle до AlterField non-null.
        migrations.RunPython(_delete_orphan_candles, reverse_code=_noop),
        # --- ExchangeCandle: drop старого trading_pair (FK на TP) и exchange,
        #     rename trading_pair_new → trading_pair, обновить unique constraint
        migrations.RemoveConstraint(
            model_name="exchangecandle",
            name="unique_candle",
        ),
        migrations.RemoveField(
            model_name="exchangecandle",
            name="trading_pair",
        ),
        migrations.RemoveField(
            model_name="exchangecandle",
            name="exchange",
        ),
        migrations.RenameField(
            model_name="exchangecandle",
            old_name="trading_pair_new",
            new_name="trading_pair",
        ),
        migrations.AlterField(
            model_name="exchangecandle",
            name="trading_pair",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                to="exchanges.exchangetradingpair",
                verbose_name="Торговая пара биржи",
            ),
        ),
        migrations.AddConstraint(
            model_name="exchangecandle",
            constraint=models.UniqueConstraint(
                fields=["timeframe", "trading_pair", "timestamp"],
                name="unique_candle",
            ),
        ),
        # --- ExchangeTradingPair: drop trading_pair (FK на TP), сделать новые
        #     поля non-null, обновить unique constraint
        migrations.RemoveConstraint(
            model_name="exchangetradingpair",
            name="unique_exchange_trading_pair",
        ),
        migrations.RemoveField(
            model_name="exchangetradingpair",
            name="trading_pair",
        ),
        migrations.AlterField(
            model_name="exchangetradingpair",
            name="name",
            field=models.CharField(max_length=50, verbose_name="Название"),
        ),
        migrations.AlterField(
            model_name="exchangetradingpair",
            name="base_currency",
            field=models.CharField(
                help_text="BTC в BTC/USDT",
                max_length=20,
                verbose_name="Базовая валюта",
            ),
        ),
        migrations.AlterField(
            model_name="exchangetradingpair",
            name="quote_currency",
            field=models.CharField(
                help_text="USDT в BTC/USDT",
                max_length=20,
                verbose_name="Валюта котировки",
            ),
        ),
        migrations.AlterField(
            model_name="exchangetradingpair",
            name="type",
            field=models.CharField(
                choices=[("futures", "Futures"), ("spot", "Spot")],
                max_length=10,
                verbose_name="Тип рынка",
            ),
        ),
        migrations.AddConstraint(
            model_name="exchangetradingpair",
            constraint=models.UniqueConstraint(
                fields=["exchange", "name", "type"],
                name="unique_exchange_trading_pair",
            ),
        ),
    ]
