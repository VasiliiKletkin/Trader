from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.detail import DetailView

from candle_sources.models import CandleSource, CandleSourceError


class CandleSourceDetailView(LoginRequiredMixin, DetailView):
    model = CandleSource
    template_name = "candle_sources/candle_source_detail.html"
    context_object_name = "source"

    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        source: CandleSource = self.get_object()

        errors = CandleSourceError.objects.filter(candle_source=source).order_by(
            "-created_at"
        )[:20]

        context_data["candles_count"] = source.candles_count()
        context_data["errors"] = errors
        context_data["dash_context"] = {
            "candle-source-id": {"data": source.pk},
        }
        return context_data
