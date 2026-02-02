# Generated manually

from django.db import migrations, models
import django.db.models.deletion
from core.utils.mixins import TimeStampedMixin


class Migration(migrations.Migration):

    dependencies = [
        ('strategies', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ArbitrageStrategy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Дата обновления')),
                ('is_active', models.BooleanField(default=True, help_text='Укажите, активна ли запись', verbose_name='Активна')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Название арбитражной стратегии')),
                ('class_name', models.CharField(max_length=100, verbose_name='Класс стратегии')),
                ('arguments', models.JSONField(blank=True, default=dict, verbose_name='Параметры (аргументы)')),
            ],
            options={
                'verbose_name': 'Арбитражная стратегия',
                'verbose_name_plural': 'Арбитражные стратегии',
            },
        ),
    ]
