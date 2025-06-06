from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView
from exchanges.models import CandleSource


class CandleSourceDetailView(LoginRequiredMixin, DetailView):
    model = CandleSource
    template_name = "exchanges/candle_source_detail.html"
    context_object_name = "candle_source"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data["dash_context"] = {
            "candle-source-id": {"data": self.get_object().pk}
        }
        return context_data
