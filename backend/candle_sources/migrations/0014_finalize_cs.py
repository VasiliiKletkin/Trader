"""Finalize CandleSource: drop старого trading_pair (FK на TP) и exchange,
переименовать trading_pair_new → trading_pair, обновить unique constraint.
"""

from django.db import migrations, models


def _delete_orphan_sources(apps, schema_editor):
    """Защитное удаление CandleSource без trading_pair_new (orphan записей,
    для которых не нашлось ETP в data-миграции). На большинстве деплоев
    no-op."""
    CandleSource = apps.get_model("candle_sources", "CandleSource")
    CandleSource.objects.filter(trading_pair_new__isnull=True).delete()


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    # atomic=False: см. комментарий в exchanges/0035_finalize_etp_and_ec.py
    atomic = False

    dependencies = [
        ("candle_sources", "0013_add_trading_pair_new"),
        ("exchanges", "0035_finalize_etp_and_ec"),
    ]

    operations = [
        migrations.RunPython(_delete_orphan_sources, reverse_code=_noop),
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
