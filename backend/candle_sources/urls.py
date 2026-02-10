from django.urls import path

from candle_sources.views import CandleSourceDetailView

urlpatterns = [
    path(
        "candle-source/<int:pk>/",
        CandleSourceDetailView.as_view(),
        name="candle_source_detail",
    ),
]
