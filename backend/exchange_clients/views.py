import asyncio
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.generic.detail import DetailView

from core.utils.common import format_pnl
from exchange_clients.domain.schemas import MarginMode
from exchange_clients.models import (
    ExchangeClient,
    ExchangeClientBalance,
    ExchangeClientOrder,
)
from exchange_clients.schemas import OrderSide
from exchange_clients.tasks import exchange_client_sync_order
from exchanges.domain import Timeframe
from exchanges.models import ExchangeTradingPair
from exchanges.schemas import MarketType


class ExchangeClientDetailView(LoginRequiredMixin, DetailView):
    """Детальная страница клиента биржи: балансы, формы, ордера.

    POST принимает hidden поле `action`, диспетчеризует на приватные методы.
    """

    model = ExchangeClient
    template_name = "exchange_clients/exchange_client_detail.html"
    context_object_name = "client"

    def get_queryset(self):
        return super().get_queryset().select_related("exchange", "proxy")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        client: ExchangeClient = self.object

        balances = ExchangeClientBalance.objects.filter(
            exchange_client=client,
            total__gt=0,
        ).order_by("market_type", "-total")

        balances_by_market: dict[str, list[ExchangeClientBalance]] = {}
        for b in balances:
            balances_by_market.setdefault(b.get_market_type_display(), []).append(b)

        orders = (
            ExchangeClientOrder.objects.filter(exchange_client=client)
            .select_related("trading_pair")
            .order_by("-timestamp")[:100]
        )

        etps = list(
            ExchangeTradingPair.active_objects.filter(exchange=client.exchange)
            .select_related("trading_pair")
            .order_by("trading_pair__name")
        )
        etps_futures = [e for e in etps if e.trading_pair.type == MarketType.FUTURES]

        ctx["balances_by_market"] = balances_by_market
        ctx["orders"] = orders
        ctx["etps"] = etps
        ctx["etps_futures"] = etps_futures
        ctx["order_sides"] = [OrderSide.BUY, OrderSide.SELL]
        ctx["margin_modes"] = [MarginMode.ISOLATED, MarginMode.CROSS]
        return ctx

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.object = self.get_object()
        action = request.POST.get("action")

        dispatchers = {
            "create_order": self._create_market_order,
            "set_margin": self._set_margin_mode,
            "set_leverage": self._set_leverage,
            "cancel_orders": self._cancel_all_orders,
            "refresh_balances": self._refresh_balances,
            "refresh_order": self._refresh_order,
        }
        handler = dispatchers.get(action)
        if handler is None:
            messages.error(request, f"Неизвестное действие: {action}")
        else:
            try:
                handler(request)
            except Exception as e:
                messages.error(request, f"Ошибка: {e}")

        return redirect("exchange_client_detail", pk=self.object.pk)

    def _get_etp(self, request: HttpRequest) -> ExchangeTradingPair | None:
        """Извлекает и проверяет ExchangeTradingPair из POST."""
        etp_id = request.POST.get("etp_id")
        try:
            return ExchangeTradingPair.objects.select_related("trading_pair").get(
                pk=etp_id,
                exchange=self.object.exchange,
            )
        except (ExchangeTradingPair.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Торговая пара не найдена")
            return None

    def _create_market_order(self, request: HttpRequest) -> None:
        client: ExchangeClient = self.object
        etp = self._get_etp(request)
        if etp is None:
            return

        side = request.POST.get("side")
        if side not in (OrderSide.BUY, OrderSide.SELL):
            messages.error(request, "Некорректная сторона ордера")
            return

        try:
            amount = Decimal(str(request.POST.get("amount")))
            if amount <= 0:
                raise InvalidOperation
        except (InvalidOperation, TypeError):
            messages.error(request, "Некорректное количество")
            return

        rpc = client.get_rpc_client()
        candles = asyncio.run(
            rpc.fetch_candles(
                trading_pair=etp.instantiate(),
                timeframe=Timeframe.ONE_MINUTE,
                limit=1,
            )
        )
        if not candles or candles[-1].close <= 0:
            messages.error(request, "Не удалось получить текущую цену")
            return

        order = client.create_market_order(
            trading_pair=etp.trading_pair,
            side=side,
            amount=amount,
            price=candles[-1].close,
        )
        messages.success(
            request,
            (
                f"Ордер создан: {order.side.upper()} {order.amount} "
                f"{etp.symbol} @ {order.price} (cost ${format_pnl(order.cost)})"
            ),
        )

    def _set_margin_mode(self, request: HttpRequest) -> None:
        etp = self._get_etp(request)
        if etp is None:
            return
        try:
            margin_mode = MarginMode(request.POST.get("margin_mode"))
        except ValueError:
            messages.error(request, "Некорректный режим маржи")
            return

        self.object.set_margin_mode(
            margin_mode=margin_mode,
            trading_pair=etp.trading_pair,
        )
        messages.success(
            request,
            f"Режим маржи {margin_mode.value.upper()} установлен для {etp.symbol}",
        )

    def _set_leverage(self, request: HttpRequest) -> None:
        etp = self._get_etp(request)
        if etp is None:
            return
        try:
            leverage = float(request.POST.get("leverage"))  # type: ignore[arg-type]
            if leverage <= 0:
                raise ValueError
        except (ValueError, TypeError):
            messages.error(request, "Некорректное значение плеча")
            return

        self.object.set_leverage(leverage=leverage, trading_pair=etp.trading_pair)
        messages.success(request, f"Плечо {leverage}x установлено для {etp.symbol}")

    def _cancel_all_orders(self, request: HttpRequest) -> None:
        etp = self._get_etp(request)
        if etp is None:
            return
        self.object.cancel_all_orders(trading_pair=etp.trading_pair)
        messages.success(
            request,
            f"Все открытые ордера по {etp.symbol} отменены",
        )

    def _refresh_balances(self, request: HttpRequest) -> None:
        client: ExchangeClient = self.object
        total_non_zero = 0
        for market_type in client.exchange.get_market_types():
            balances = client.sync_balances(market_type=market_type)
            total_non_zero += sum(1 for b in balances if b.total > 0)
        messages.success(
            request,
            f"Балансы обновлены: {total_non_zero} ненулевых",
        )

    def _refresh_order(self, request: HttpRequest) -> None:
        order_id = request.POST.get("order_id")
        try:
            order = ExchangeClientOrder.objects.get(
                pk=order_id,
                exchange_client=self.object,
            )
        except (ExchangeClientOrder.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Ордер не найден")
            return

        exchange_client_sync_order(order.pk)
        messages.success(request, f"Ордер {order.exchange_order_id} обновлён")
