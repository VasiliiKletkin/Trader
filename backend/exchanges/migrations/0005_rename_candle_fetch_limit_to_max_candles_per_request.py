from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("exchanges", "0004_alter_exchangecandle_volume"),
    ]

    operations = [
        migrations.RenameField(
            model_name="exchange",
            old_name="candle_fetch_limit",
            new_name="max_candles_per_request",
        ),
    ]
