"""Finalize ExchangeClientOrder: drop старого trading_pair (FK на TP),
переименовать trading_pair_new → trading_pair.
"""

from django.db import migrations, models


def _delete_orphan_orders(apps, schema_editor):
    """Защитное удаление ExchangeClientOrder без trading_pair_new (orphan
    записей, для которых не нашлось ETP в data-миграции)."""
    ECO = apps.get_model("exchange_clients", "ExchangeClientOrder")
    ECO.objects.filter(trading_pair_new__isnull=True).delete()


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    # atomic=False: см. комментарий в exchanges/0035_finalize_etp_and_ec.py
    atomic = False

    dependencies = [
        ("exchange_clients", "0007_add_trading_pair_new"),
        ("exchanges", "0035_finalize_etp_and_ec"),
    ]

    operations = [
        migrations.RunPython(_delete_orphan_orders, reverse_code=_noop),
        migrations.RemoveConstraint(
            model_name="exchangeclientorder",
            name="unique_exchange_order",
        ),
        migrations.RemoveField(
            model_name="exchangeclientorder",
            name="trading_pair",
        ),
        migrations.RenameField(
            model_name="exchangeclientorder",
            old_name="trading_pair_new",
            new_name="trading_pair",
        ),
        migrations.AlterField(
            model_name="exchangeclientorder",
            name="trading_pair",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE,
                to="exchanges.exchangetradingpair",
                verbose_name="Торговая пара биржи",
            ),
        ),
        migrations.AddConstraint(
            model_name="exchangeclientorder",
            constraint=models.UniqueConstraint(
                fields=[
                    "exchange_client",
                    "trading_pair",
                    "exchange_order_id",
                    "timestamp",
                ],
                name="unique_exchange_order",
            ),
        ),
    ]
