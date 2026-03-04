from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView

from exchanges.models import TradingPairSpreadAnalytics


class TradingPairSpreadDetailView(LoginRequiredMixin, DetailView):
    model = TradingPairSpreadAnalytics
    template_name = "exchanges/trading_pair_spread_detail.html"
    context_object_name = "trading_pair"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        trading_pair = self.get_object()
        context_data["dash_context"] = {
            "trading-pair-id": {"data": trading_pair.pk},
        }
        return context_data
