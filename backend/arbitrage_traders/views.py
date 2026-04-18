from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.html import escape
from django.views.generic.detail import DetailView

from arbitrage_traders.models import ArbitrageTrader, ArbitrageTraderPosition


class ArbitrageTraderDetailView(LoginRequiredMixin, DetailView):
    """Детальная страница арбитражного трейдера.

    POST принимает hidden поле `action`, диспетчеризует на приватные методы.
    """

    model = ArbitrageTrader
    template_name = "arbitrage_traders/arbitrage_trader_detail.html"
    context_object_name = "trader"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "left_candle_source__trading_pair",
                "left_candle_source__exchange",
                "right_candle_source__trading_pair",
                "right_candle_source__exchange",
                "left_exchange_client__exchange",
                "right_exchange_client__exchange",
                "strategy",
                "risk_manager",
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        trader: ArbitrageTrader = self.object
        orders = trader.orders.select_related(
            "left_order",
            "right_order",
            "position",
        ).order_by("-position__opened_at")
        positions = trader.positions.order_by("-opened_at")

        ctx["orders"] = orders
        ctx["positions"] = positions
        ctx["dash_context"] = {
            "trader-id": {"data": trader.pk},
        }
        return ctx

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.object = self.get_object()
        action = request.POST.get("action")

        dispatchers = {
            "close_all_positions": self._close_all_positions,
            "close_position": self._close_position,
        }
        handler = dispatchers.get(action)
        if handler is None:
            messages.error(request, f"Неизвестное действие: {escape(action)}")
        else:
            try:
                handler(request)
            except Exception as e:
                messages.error(request, f"Ошибка: {escape(str(e))}")

        return redirect("arbitrage_trader_detail", pk=self.object.pk)

    def _get_position(self, request: HttpRequest) -> ArbitrageTraderPosition | None:
        position_pk = request.POST.get("position_pk")
        try:
            return self.object.positions.get(pk=position_pk)
        except (ArbitrageTraderPosition.DoesNotExist, ValueError, TypeError):
            messages.error(request, f"Позиция #{escape(position_pk)} не найдена")
            return None

    def _close_all_positions(self, request: HttpRequest) -> None:
        self.object.close_all_opened_positions()
        messages.success(request, "Все открытые позиции закрыты")

    def _close_position(self, request: HttpRequest) -> None:
        position = self._get_position(request)
        if position is None:
            return
        self.object.close_position(position=position)
        messages.success(request, f"Позиция #{position.pk} закрыта")
