# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('strategies', '0002_arbitragestrategy'),
        ('traders', '0003_refactor_arbitrage_trader'),
    ]

    operations = [
        migrations.AlterField(
            model_name='arbitragetrader',
            name='strategy',
            field=models.ForeignKey(
                help_text='Выберите арбитражную стратегию, которую будет использовать трейдер.',
                limit_choices_to={'is_active': True},
                on_delete=django.db.models.deletion.CASCADE,
                to='strategies.arbitragestrategy',
                verbose_name='Арбитражная стратегия'
            ),
        ),
    ]
