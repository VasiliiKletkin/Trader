from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.html import escape
from django.views.generic.detail import DetailView

from exchange_clients.schemas import OrderStatus
from exchange_clients.tasks import exchange_client_sync_order
from traders.models import Trader, TraderOrder, TraderPosition


class TraderDetailView(LoginRequiredMixin, DetailView):
    """Детальная страница трейдера.

    POST принимает hidden поле `action`, диспетчеризует на приватные методы.
    """

    model = Trader
    template_name = "traders/trader_detail.html"
    context_object_name = "trader"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        trader: Trader = self.object
        orders: TraderOrder = trader.orders.select_related("order").order_by(
            "-order__timestamp"
        )[:50]
        positions: TraderPosition = trader.positions.order_by("-opened_at")[:50]

        ctx["orders"] = [order.order for order in orders]
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
            "refresh_order": self._refresh_order,
        }
        handler = dispatchers.get(action)
        if handler is None:
            messages.error(request, f"Неизвестное действие: {escape(action)}")
        else:
            try:
                handler(request)
            except Exception as e:
                messages.error(request, f"Ошибка: {escape(str(e))}")

        return redirect("trader_detail", pk=self.object.pk)

    def _get_position(self, request: HttpRequest) -> TraderPosition | None:
        position_pk = request.POST.get("position_pk")
        try:
            return self.object.positions.get(pk=position_pk)
        except (TraderPosition.DoesNotExist, ValueError, TypeError):
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

    def _refresh_order(self, request: HttpRequest) -> None:
        order_id = request.POST.get("order_id")
        try:
            trader_order = self.object.orders.select_related("order").get(
                order__pk=order_id,
            )
        except (TraderOrder.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Ордер не найден")
            return

        order = trader_order.order
        if order.status == OrderStatus.CLOSED:
            messages.error(request, "Закрытый ордер нельзя обновлять")
            return

        exchange_client_sync_order(order.pk)
        messages.success(request, f"Ордер {order.exchange_order_id} обновлён")
