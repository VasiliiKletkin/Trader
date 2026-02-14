from django.urls import path

from arbitrage_traders.views import ArbitrageTraderDetailView

urlpatterns = [
    path(
        "arbitrage_trader/<int:pk>/",
        ArbitrageTraderDetailView.as_view(),
        name="arbitrage_trader_detail",
    ),
]
