"""Finalize ExchangeClientOrder: drop старого trading_pair (FK на TP),
переименовать trading_pair_new → trading_pair.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exchange_clients", "0007_add_trading_pair_new"),
        ("exchanges", "0035_finalize_etp_and_ec"),
    ]

    operations = [
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
