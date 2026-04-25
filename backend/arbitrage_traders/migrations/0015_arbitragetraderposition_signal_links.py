import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arbitrage_traders', '0014_alter_arbitragetrader_candles_lookback_count'),
    ]

    operations = [
        migrations.AddField(
            model_name='arbitragetraderposition',
            name='open_signal',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='opened_position',
                to='arbitrage_traders.arbitragetradersignal',
                verbose_name='Сигнал открытия',
            ),
        ),
        migrations.AddField(
            model_name='arbitragetraderposition',
            name='close_signal',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='closed_position',
                to='arbitrage_traders.arbitragetradersignal',
                verbose_name='Сигнал закрытия',
            ),
        ),
    ]
