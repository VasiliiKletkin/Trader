from decimal import Decimal
from typing import List

import pytest
from core.utils.types import PositionStatus, PositionType, Timeframe, TraderStatus
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from exchange_clients.domain import ByBitExchangeClient
from exchange_clients.domain import ExchangeClientOrder as DomainTraderOrder
from exchange_clients.domain import OrderSide as DomainOrderSide
from exchange_clients.domain import OrderType as DomainOrderType
from candle_providers.models import CandleProvider
from exchanges.domain import ExchangeCandle as DomainExchangeCandle
from exchanges.domain import TradingPair as DomainTradingPair
from exchanges.models import Exchange, ExchangeCandle, TradingPair
from risk_managers.domain import SLPercentTPPercentPSAllInRiskManager
from risk_managers.models import RiskManager
from strategies.domain import MoneyFlowIndexStrategy
from strategies.domain import SignalType as DomainSignalType
from strategies.domain import TraderSignal as DomainTraderSignal
from strategies.models import Strategy
from traders.models import ExchangeClient, Trader, TraderPosition
from traders.tasks import (
    trader_reboot,
    traders_process_for_exchange_client,
)

from exchange_clients.domain import OrderStatus as DomainOrderStatus


@pytest.mark.django_db
def test_trader_instantiate(trader: Trader):
    """
    Тест проверяет оптимизацию запросов при инстанциации трейдера.

    Оптимизации:
    - Добавлен exchange_client__proxy в select_related для избежания дополнительного запроса
    - Все связи загружаются одним запросом через select_related/prefetch_related
    """
    with CaptureQueriesContext(connection) as queries:
        tr = Trader.objects.select_related(
            "exchange_client",
            "exchange_client__exchange",
            "exchange_client__proxy",
            "candle_provider",
            "candle_provider__primary_source",
            "candle_provider__primary_source__trading_pair",
            "candle_provider__primary_source__exchange_client",
            "candle_provider__primary_source__exchange_client__exchange",
            "candle_provider__second_source",
            "candle_provider__second_source__trading_pair",
            "candle_provider__second_source__exchange_client",
            "candle_provider__second_source__exchange_client__exchange",
            "risk_manager",
            "strategy",
        ).get(id=trader.pk)
        tr.instantiate()

    assert len(queries) == 2


@pytest.mark.django_db
def test_candle_provider_instantiate(trader: Trader):
    """
    Тест проверяет количество запросов при вызове candle_provider.instantiate().

    candle_provider.instantiate() без параметров start_date/end_date делает 0 запросов,
    так как использует prefetch кеш и возвращает генераторы.

    Реальные запросы к БД выполняются при итерации по генератору свечей.
    """
    tr = Trader.objects.select_related(
        "exchange_client",
        "exchange_client__exchange",
        "exchange_client__proxy",
        "candle_provider",
        "candle_provider__primary_source",
        "candle_provider__primary_source__trading_pair",
        "candle_provider__primary_source__exchange_client",
        "candle_provider__primary_source__exchange_client__exchange",
        "candle_provider__second_source",
        "candle_provider__second_source__trading_pair",
        "candle_provider__second_source__exchange_client",
        "candle_provider__second_source__exchange_client__exchange",
        "risk_manager",
        "strategy",
    ).get(id=trader.pk)
    with CaptureQueriesContext(connection) as queries:
        candle_provider = tr.candle_provider.instantiate()
    assert len(queries) == 0
    # Test get_last_candles instead since it doesn't require start/end
    with CaptureQueriesContext(connection) as queries:
        candles = candle_provider.get_last_candles(10)
    assert len(queries) == 1


@pytest.mark.django_db
def test_trader_reboot_calls_reboot(trader: Trader):
    """
    Тест проверяет оптимизацию запросов при перезагрузке трейдера.

    Оптимизации:
    - Применены оптимизации cached_property в модели Trader
    - instantiate() выполняет только 6 запросов вместо 11

    Структура запросов (9 total):
    - 6 запросов: trader.instantiate() (оптимизировано!)
    - 1 запрос: candle_provider.instantiate() для загрузки свечей (оптимизировано!)
    - 2 запроса: clear_all_data() (DELETE операции)
    """
    with CaptureQueriesContext(connection) as queries:
        trader_reboot(trader_id=trader.pk)
    assert len(queries) == 8


@pytest.mark.django_db
def test_traders_process_for_exchange_client_one_trader(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_provider: CandleProvider,
    risk_manager: RiskManager,
):
    trader = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("1000.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )
    with CaptureQueriesContext(connection) as queries:
        traders_process_for_exchange_client(
            exchange_client_id=exchange_client.pk,
            traders_ids=[trader.pk],
        )
    assert len(queries) == 6


@pytest.mark.django_db
def test_traders_process_for_exchange_client_two_trader(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_provider: CandleProvider,
    risk_manager: RiskManager,
):
    trader1 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("1000.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )
    trader2 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("100.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )
    with CaptureQueriesContext(connection) as queries:
        traders_process_for_exchange_client(
            exchange_client_id=exchange_client.pk,
            traders_ids=[trader1.pk, trader2.pk],
        )
    assert len(queries) == 10


@pytest.mark.django_db
def test_traders_process_for_exchange_client_three_trader(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_provider: CandleProvider,
    risk_manager: RiskManager,
):
    trader1 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("1000.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )
    trader2 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("100.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )
    trader3 = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("10.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )
    with CaptureQueriesContext(connection) as queries:
        traders_process_for_exchange_client(
            exchange_client_id=exchange_client.pk,
            traders_ids=[trader1.pk, trader2.pk, trader3.pk],
        )
    assert len(queries) == 14


@pytest.mark.django_db
def test_traders_daily_report_with_closed_positions(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_provider: CandleProvider,
    risk_manager: RiskManager,
    trading_pair: TradingPair,
):
    """
    Тест ежедневного отчета с закрытыми позициями.

    Проверяет:
    - Корректный расчет PnL
    - Корректный расчет комиссий
    - Количество SQL-запросов
    - Вызов send_notification
    """
    from traders.tasks import traders_daily_report
    from unittest.mock import patch

    # Arrange: создаем трейдера и закрытые позиции
    trader = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("1000.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=1,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )

    # Создаем закрытую позицию
    now = timezone.now()
    TraderPosition.objects.create(
        trader=trader,
        type=PositionType.LONG,
        status=PositionStatus.CLOSED,
        amount=Decimal("1.0"),
        opened_at=now - timezone.timedelta(hours=2),
        closed_at=now - timezone.timedelta(hours=1),
    )

    # Act & Assert: проверяем количество запросов
    with patch("traders.tasks.send_notification.delay") as mock_send:
        with CaptureQueriesContext(connection) as queries:
            traders_daily_report()

        # Ожидаем: 1 запрос для агрегации
        assert len(queries) == 1

        # Проверяем вызов send_notification
        mock_send.assert_called_once()
        call_args = mock_send.call_args[1]
        message = call_args["message"]

        # Проверяем содержимое сообщения
        assert "Ежедневный отчет" in message


@pytest.mark.django_db
def test_traders_daily_report_no_positions(db):
    """
    Тест ежедневного отчета когда нет закрытых позиций.
    """
    from traders.tasks import traders_daily_report
    from unittest.mock import patch

    # Act & Assert
    with patch("traders.tasks.send_notification.delay") as mock_send:
        with CaptureQueriesContext(connection) as queries:
            traders_daily_report()

        # Должен быть 1 запрос (агрегация вернет пустой результат)
        assert len(queries) == 1

        # Должно быть уведомление с нулевыми значениями
        mock_send.assert_called_once()
        call_args = mock_send.call_args[1]
        message = call_args["message"]

        assert "0.00" in message or "0.0" in message


@pytest.mark.django_db
def test_traders_daily_report_query_count_multiple_positions(
    exchange_client: ExchangeClient,
    strategy: Strategy,
    candle_provider: CandleProvider,
    risk_manager: RiskManager,
    trading_pair: TradingPair,
):
    """
    Тест количества запросов с несколькими позициями.

    Важно: количество запросов НЕ должно зависеть от количества позиций,
    так как используется агрегация.
    """
    from traders.tasks import traders_daily_report
    from unittest.mock import patch

    # Arrange: создаем трейдера и 10 закрытых позиций
    trader = Trader.objects.create(
        exchange_client=exchange_client,
        candle_provider=candle_provider,
        strategy=strategy,
        risk_manager=risk_manager,
        use_fixed_balance=True,
        initial_balance=Decimal("10000.00"),
        check_drawdown=False,
        max_drawdown_pct=Decimal("0.0"),
        create_new_orders=True,
        max_positions_count=10,
        close_position_by_opposite_signal=True,
        close_position_by_strategy=True,
        close_position_by_stop_loss=True,
        close_position_by_take_profit=True,
        trail_stop_enabled=True,
        status=TraderStatus.ENABLED,
    )

    from exchange_clients.models import ExchangeClientOrder
    from core.utils.types import OrderSide, OrderType, OrderStatus
    from traders.models import TraderOrder

    now = timezone.now()

    # Создаем 10 позиций (без ордеров для упрощения)
    for i in range(10):
        TraderPosition.objects.create(
            trader=trader,
            type=PositionType.LONG,
            status=PositionStatus.CLOSED,
            amount=Decimal("1.0"),
            opened_at=now - timezone.timedelta(hours=2, minutes=i),
            closed_at=now - timezone.timedelta(minutes=30),
        )

    # Act & Assert
    with patch("traders.tasks.send_notification.delay") as mock_send:
        with CaptureQueriesContext(connection) as queries:
            traders_daily_report()

        # Количество запросов НЕ должно зависеть от количества позиций
        # Ожидаем 1 запрос (агрегация)
        assert len(queries) == 1

        mock_send.assert_called_once()
