# Generated manually

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('candle_sources', '0001_initial'),
        ('traders', '0004_use_arbitrage_strategy'),
    ]

    operations = [
        # Remove the old index first (before renaming fields)
        migrations.RemoveIndex(
            model_name='arbitragetradererror',
            name='arb_trader_error_idx',
        ),
        # Rename ArbitrageTraderError fields
        migrations.RenameField(
            model_name='arbitragetradererror',
            old_name='arbitrage_trader',
            new_name='trader',
        ),
        migrations.RenameField(
            model_name='arbitragetradererror',
            old_name='error_message',
            new_name='message',
        ),
        migrations.RenameField(
            model_name='arbitragetradererror',
            old_name='error_traceback',
            new_name='traceback',
        ),
        migrations.RenameField(
            model_name='arbitragetradererror',
            old_name='error_type',
            new_name='type',
        ),
        # Add the index back with the new field name
        migrations.AddIndex(
            model_name='arbitragetradererror',
            index=models.Index(fields=['trader', '-created_at'], name='arb_trader_error_idx'),
        ),
        # Remove TraderSignal index before modifying fields
        migrations.RemoveIndex(
            model_name='tradersignal',
            name='trader_signal_candles_idx',
        ),
        # Rename primary_candle to candle in TraderSignal
        migrations.RenameField(
            model_name='tradersignal',
            old_name='primary_candle',
            new_name='candle',
        ),
        # Remove second_candle field (not needed for regular Trader)
        migrations.RemoveField(
            model_name='tradersignal',
            name='second_candle',
        ),
        # Add the index back with the new field name
        migrations.AddIndex(
            model_name='tradersignal',
            index=models.Index(fields=['candle'], name='trader_signal_candle_idx'),
        ),
        # Remove constraint first (before removing candle_provider field)
        migrations.RemoveConstraint(
            model_name='trader',
            name='unique_trader',
        ),
        # Add candle_source field to Trader
        migrations.AddField(
            model_name='trader',
            name='candle_source',
            field=models.ForeignKey(
                help_text='Выберите источник свечей для трейдера.',
                limit_choices_to={'is_active': True},
                on_delete=django.db.models.deletion.CASCADE,
                to='candle_sources.candlesource',
                verbose_name='Источник свечей',
                null=True,  # Temporarily allow null for migration
            ),
            preserve_default=False,
        ),
        # Remove candle_provider field from Trader
        migrations.RemoveField(
            model_name='trader',
            name='candle_provider',
        ),
        # Add new constraint with candle_source
        migrations.AddConstraint(
            model_name='trader',
            constraint=models.UniqueConstraint(
                fields=[
                    'candle_source',
                    'exchange_client',
                    'strategy',
                    'risk_manager',
                    'initial_balance',
                    'max_drawdown_pct',
                    'max_positions_count',
                    'close_position_by_opposite_signal',
                    'close_position_by_strategy',
                    'close_position_by_stop_loss',
                    'close_position_by_take_profit',
                    'trail_stop_enabled',
                ],
                name='unique_trader',
            ),
        ),
        # ArbitrageTrader: replace candle_provider with first/second_candle_source
        migrations.AddField(
            model_name='arbitragetrader',
            name='first_candle_source',
            field=models.ForeignKey(
                help_text='Первый источник свечей для арбитражного трейдера.',
                limit_choices_to={'is_active': True},
                on_delete=django.db.models.deletion.CASCADE,
                related_name='arbitrage_first_traders',
                to='candle_sources.candlesource',
                verbose_name='Первый источник свечей',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='arbitragetrader',
            name='second_candle_source',
            field=models.ForeignKey(
                help_text='Второй источник свечей для арбитражного трейдера.',
                limit_choices_to={'is_active': True},
                on_delete=django.db.models.deletion.CASCADE,
                related_name='arbitrage_second_traders',
                to='candle_sources.candlesource',
                verbose_name='Второй источник свечей',
                null=True,
            ),
        ),
        migrations.RemoveField(
            model_name='arbitragetrader',
            name='candle_provider',
        ),
    ]
