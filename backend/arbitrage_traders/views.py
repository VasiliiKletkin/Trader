from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView

from arbitrage_traders.models import ArbitrageTrader


class ArbitrageTraderDetailView(LoginRequiredMixin, DetailView):
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
        context_data = super().get_context_data(**kwargs)
        trader: ArbitrageTrader = self.object
        orders = trader.orders.select_related(
            "left_order",
            "right_order",
            "position",
        ).order_by("-position__opened_at")
        positions = trader.positions.order_by("-opened_at")

        context_data["orders"] = orders
        context_data["positions"] = positions
        context_data["dash_context"] = {
            "trader-id": {"data": trader.pk},
        }
        return context_data
