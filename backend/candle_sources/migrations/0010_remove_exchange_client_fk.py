from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("candle_sources", "0009_update_unique_constraint"),
        ("exchanges", "0024_add_min_leverage"),
    ]

    operations = [
        # 1. Make exchange non-null (data already populated by 0008)
        migrations.AlterField(
            model_name="candlesource",
            name="exchange",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="candle_sources",
                to="exchanges.exchange",
                verbose_name="Биржа",
            ),
        ),
        # 2. Remove exchange_client FK
        migrations.RemoveField(
            model_name="candlesource",
            name="exchange_client",
        ),
    ]
