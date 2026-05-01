"""Finalize CandleSource: drop старого trading_pair (FK на TP) и exchange,
переименовать trading_pair_new → trading_pair, обновить unique constraint.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("candle_sources", "0013_add_trading_pair_new"),
        ("exchanges", "0035_finalize_etp_and_ec"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="candlesource",
            name="unique_candle_source_exchange",
        ),
        migrations.RemoveField(
            model_name="candlesource",
            name="trading_pair",
        ),
        migrations.RemoveField(
            model_name="candlesource",
            name="exchange",
        ),
        migrations.RenameField(
            model_name="candlesource",
            old_name="trading_pair_new",
            new_name="trading_pair",
        ),
        migrations.AlterField(
            model_name="candlesource",
            name="trading_pair",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                related_name="candle_sources",
                to="exchanges.exchangetradingpair",
                verbose_name="Торговая пара биржи",
            ),
        ),
        migrations.AddConstraint(
            model_name="candlesource",
            constraint=models.UniqueConstraint(
                fields=["trading_pair", "timeframe"],
                name="unique_candle_source_exchange",
            ),
        ),
    ]
