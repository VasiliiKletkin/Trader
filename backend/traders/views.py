from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView
from traders.models import Trader, TraderPosition
from exchange_clients.models import ExchangeClientOrder


class TraderDetailView(LoginRequiredMixin, DetailView):
    model = Trader
    template_name = "traders/trader_detail.html"
    context_object_name = "trader"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        trader: Trader = self.get_object()
        orders: ExchangeClientOrder = trader.orders.order_by("-timestamp")
        positions: TraderPosition = trader.positions.order_by("-opened_at")

        context_data["orders"] = orders
        context_data["positions"] = positions
        context_data["dash_context"] = {
            "trader-id": {"data": trader.pk},
        }
        return context_data
