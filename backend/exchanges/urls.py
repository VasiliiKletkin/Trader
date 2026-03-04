from django.urls import path

from exchanges.views import TradingPairSpreadDetailView

urlpatterns = [
    path(
        "trading_pair_spread/<int:pk>/",
        TradingPairSpreadDetailView.as_view(),
        name="trading_pair_spread_detail",
    ),
]
