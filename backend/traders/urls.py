from django.urls import path
from traders.views import TraderDetailView, ArbitrageTraderDetailView

urlpatterns = [
    path(
        "trader/<int:pk>/",
        TraderDetailView.as_view(),
        name="trader_detail",
    ),
    path(
        "arbitrage-trader/<int:pk>/",
        ArbitrageTraderDetailView.as_view(),
        name="arbitrage_trader_detail",
    ),
]
