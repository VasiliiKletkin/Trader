from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from core.utils.types import Timeframe
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime, make_aware
from django_plotly_dash import DjangoDash
from exchanges.models import Candle
from traders.models import Trader, TraderSignal

app = DjangoDash("SignalChart")
app.layout = html.Div(
    [
        dcc.Graph(id="combined-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Interval(
            id="interval-component",
            interval=60 * 1000,
            n_intervals=0,
        ),
    ]
)


@app.callback(
    Output("combined-chart", "figure"),
    Input("trader-id", "data"),
)
def update_combined_chart(trader_id):
    if not trader_id:
        return go.Figure()

    trader = Trader.objects.get(id=trader_id)
    candles = Candle.objects.filter(
        candle_source=trader.candle_source,
        # timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    if not candles.exists():
        return go.Figure()

    df = pd.DataFrame.from_records(
        candles.values("timestamp", "open", "high", "low", "close")
    )

    df["timestamp"] = df["timestamp"].apply(localtime)

    # Получаем сигналы
    signals = TraderSignal.objects.filter(
        trader=trader,
        # timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    buy_signals = signals.filter(type="buy")
    sell_signals = signals.filter(type="sell")

    fig = go.Figure()

    # Добавляем свечной график
    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Candles",
        )
    )

    # Добавляем сигналы "Buy"
    fig.add_trace(
        go.Scatter(
            x=[localtime(s.timestamp) for s in buy_signals],
            y=[s.price for s in buy_signals],
            mode="markers",
            name="Buy",
            marker=dict(color="green", symbol="triangle-up", size=20),
        )
    )

    # Добавляем сигналы "Sell"
    fig.add_trace(
        go.Scatter(
            x=[localtime(s.timestamp) for s in sell_signals],
            y=[s.price for s in sell_signals],
            mode="markers",
            name="Sell",
            marker=dict(color="red", symbol="triangle-down", size=20),
        )
    )

    # Настройки графика
    fig.update_layout(
        title="Свечной график с торговыми сигналами",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=600,
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )

    return fig
