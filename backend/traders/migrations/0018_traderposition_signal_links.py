import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traders', '0017_alter_trader_candles_lookback_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='traderposition',
            name='open_signal',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='opened_position',
                to='traders.tradersignal',
                verbose_name='Сигнал открытия',
            ),
        ),
        migrations.AddField(
            model_name='traderposition',
            name='close_signal',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='closed_position',
                to='traders.tradersignal',
                verbose_name='Сигнал закрытия',
            ),
        ),
    ]
