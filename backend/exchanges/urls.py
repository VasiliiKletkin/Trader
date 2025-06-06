from django.urls import path
from exchanges.views import CandleSourceDetailView

urlpatterns = [
    path(
        "candle_source/<int:pk>/",
        CandleSourceDetailView.as_view(),
        name="candle_source_detail",
    )
]
