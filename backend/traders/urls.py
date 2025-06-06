from django.urls import path
from traders.views import TraderDetailView

urlpatterns = [
    path("trader/<int:pk>/", TraderDetailView.as_view(), name="trader_detail")
]
