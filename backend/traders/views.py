from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView
from traders.models import Trader


class TraderDetailView(LoginRequiredMixin, DetailView):
    model = Trader
    template_name = "traders/trader_detail.html"
    context_object_name = "trader"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data["dash_context"] = {"value": 1}
        return context_data
