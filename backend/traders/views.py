from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView

from traders.models import (
    ArbitrageTrader,
    Trader,
    TraderOrder,
    TraderPosition,
)


class TraderDetailView(LoginRequiredMixin, DetailView):
    model = Trader
    template_name = "traders/trader_detail.html"
    context_object_name = "trader"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        trader: Trader = self.get_object()
        orders: TraderOrder = trader.orders.select_related("order").order_by(
            "-order__timestamp"
        )
        positions: TraderPosition = trader.positions.order_by("-opened_at")

        context_data["orders"] = [order.order for order in orders]
        context_data["positions"] = positions
        context_data["dash_context"] = {
            "trader-id": {"data": trader.pk},
        }
        return context_data


class ArbitrageTraderDetailView(LoginRequiredMixin, DetailView):
    model = ArbitrageTrader
    template_name = "traders/arbitrage_trader_detail.html"
    context_object_name = "trader"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        trader: ArbitrageTrader = self.get_object()
        orders = trader.orders.select_related(
            "left_order", "right_order", "position"
        ).order_by("-left_order__timestamp")
        positions = trader.positions.order_by("-opened_at")

        context_data["orders"] = orders
        context_data["positions"] = positions
        return context_data
