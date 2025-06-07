from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView
from traders.models import Trader


class TraderDetailView(LoginRequiredMixin, DetailView):
    model = Trader
    template_name = "traders/trader_detail.html"
    context_object_name = "trader"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        trader: Trader = self.get_object()
        context_data["dash_context"] = {
            "trader-id": {"data": trader.pk},
            "candle-source-id": {"data": trader.candle_source.pk},
        }
        return context_data
