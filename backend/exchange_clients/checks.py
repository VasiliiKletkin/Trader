"""Проверки ExchangeClient. Используются в админке и на detail-странице."""

import asyncio
from decimal import Decimal

from django.db import models

from core.utils.common import format_spread
from exchange_clients.models import ExchangeClient
from exchange_clients.schemas import OrderSide
from exchanges.domain import Timeframe
from exchanges.models import ExchangeTradingPair
from exchanges.schemas import MarketType


def check_instantiate(client: ExchangeClient) -> str | None:
    try:
        client.instantiate()
        return None
    except Exception as e:
        return str(e)


def check_proxy(client: ExchangeClient) -> str | None:
    if not client.proxy:
        return None
    try:
        client.proxy.check_obj()
        return client.proxy.errors or None
    except Exception as e:
        return str(e)


def check_balances(client: ExchangeClient) -> str | None:
    for market_type in client.exchange.get_market_types():
        try:
            client.sync_balances(market_type=market_type)
        except Exception as e:
            return f"{market_type}: {e}"
    return None


def _get_exchange_trading_pair(
    client: ExchangeClient, market_type: MarketType
) -> tuple[ExchangeTradingPair, Decimal, Decimal] | None:
    """Самая дешёвая пара среди валют с балансом для тестового ордера."""
    balances = {
        b.currency: b.free
        for b in client.fetch_balances(market_type=market_type)
        if b.free > 0 and b.currency in ("USDT", "USDC")
    }
    if not balances:
        return None

    balance_filter = models.Q()
    for currency, free in balances.items():
        balance_filter |= models.Q(
            trading_pair__quote_currency=currency,
            min_cost__lte=free,
        ) | models.Q(
            trading_pair__quote_currency=currency,
            min_cost__isnull=True,
        )

    etps = (
        ExchangeTradingPair.active_objects.filter(
            balance_filter,
            exchange=client.exchange,
            trading_pair__type=market_type,
        )
        .select_related("trading_pair")
        .order_by("min_cost")
    )

    for etp in etps:
        rpc = client.get_rpc_client()
        candles = asyncio.run(
            rpc.fetch_candles(
                trading_pair=etp.instantiate(),
                timeframe=Timeframe.ONE_MINUTE,
                limit=1,
            )
        )
        if not candles or candles[-1].close <= 0:
            continue

        last_price = candles[-1].close

        if etp.min_amount:
            amount = etp.min_amount
        elif etp.min_cost:
            amount = etp.min_cost * Decimal("1.1") / last_price
        elif etp.amount_precision:
            amount = etp.amount_precision
        else:
            continue

        if etp.amount_precision:
            amount = amount.quantize(etp.amount_precision)
            if etp.min_cost and amount * last_price < etp.min_cost:
                amount += etp.amount_precision

        if amount <= 0:
            continue

        return etp, last_price, amount

    return None


def check_create_and_close_order(client: ExchangeClient) -> str | None:
    result = None
    for market_type in client.exchange.get_market_types():
        result = _get_exchange_trading_pair(client, market_type)
        if result:
            break
    if not result:
        return "Нет торговых пар с достаточным балансом на бирже"

    etp, price, amount = result
    trading_pair = etp.trading_pair
    cost = format_spread(amount * price)
    order_info = f"symbol={etp.symbol}, cost=${cost}"

    try:
        buy_order = client.create_market_order(
            trading_pair=trading_pair,
            side=OrderSide.BUY,
            amount=amount,
            price=price,
        )
    except Exception as e:
        return f"Ошибка при открытии ордера ({order_info}): {e}"

    try:
        client.fetch_order(
            exchange_order_id=buy_order.exchange_order_id,
            trading_pair=trading_pair,
        )
    except Exception as e:
        return f"Ордер открыт, но ошибка при получении ({order_info}): {e}"

    try:
        sell_order = client.create_market_order(
            trading_pair=trading_pair,
            side=OrderSide.SELL,
            amount=buy_order.amount,
            price=buy_order.price,
        )
    except Exception as e:
        return f"Ордер открыт, но ошибка при закрытии ({order_info}): {e}"

    buy_url = f"/admin/exchange_clients/exchangeclientorder/{buy_order.pk}/change/"
    sell_url = f"/admin/exchange_clients/exchangeclientorder/{sell_order.pk}/change/"
    return (
        f"OK ({order_info}, "
        f'buy=<a href="{buy_url}">#{buy_order.pk}</a>, '
        f'sell=<a href="{sell_url}">#{sell_order.pk}</a>)'
    )


CHECKS = [
    ("Создание клиента", check_instantiate),
    ("Проверка прокси", check_proxy),
    ("Получение балансов", check_balances),
    ("Открытие, получение и закрытие ордера", check_create_and_close_order),
]


def run_client_checks(client: ExchangeClient) -> dict[str, str | None]:
    """Запускает все проверки, возвращает {имя: ошибка | None}.

    Для OK-результатов с деталями (ссылки на ордера) значение начинается с 'OK'.
    Если "Создание клиента" упало — дальнейшие проверки не запускаются.
    """
    results: dict[str, str | None] = {}
    for check_name, check_fn in CHECKS:
        if check_name == "Проверка прокси" and not client.proxy:
            continue
        error = check_fn(client)
        results[check_name] = error
        if error is not None and check_name == "Создание клиента":
            break
    return results
