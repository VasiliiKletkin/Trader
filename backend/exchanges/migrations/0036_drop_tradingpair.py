"""Удаляет модель TradingPair после того, как все FK на неё дропнуты
(0035 в exchanges, 0014 в candle_sources, 0008 в exchange_clients).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0035_finalize_etp_and_ec"),
        ("candle_sources", "0014_finalize_cs"),
        ("exchange_clients", "0008_finalize_eco"),
    ]

    operations = [
        migrations.DeleteModel(
            name="TradingPair",
        ),
    ]
