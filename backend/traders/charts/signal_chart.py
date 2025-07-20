from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from strategies.domain.schemas import SignalType
from exchanges.models import Candle
from traders.models import Trader, TraderSignal

app = DjangoDash("SignalChart")
app.layout = html.Div(
    [
        dcc.Graph(id="combined-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="signal-date-range", data=None),
        # dcc.Interval(
        #     id="interval-component",
        #     interval=60 * 1000,
        #     n_intervals=0,
        # ),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("signal-date-range", "data"),
    [
        Input("combined-chart", "relayoutData"),
    ],
    [
        State("signal-date-range", "data"),
    ],
)
def update_date_range(relayout_data, stored_range):
    if relayout_data:
        x0 = relayout_data.get("xaxis.range[0]")
        x1 = relayout_data.get("xaxis.range[1]")
        if x0 and x1:
            return {"start": x0, "end": x1}
        if relayout_data.get("xaxis.autorange") or relayout_data.get(
            "xaxis.autorange", False
        ):
            return None
    return stored_range


# Callback для построения графика по диапазону
@app.callback(
    Output("combined-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("signal-date-range", "data"),
    ],
)
def update_combined_chart(trader_id, date_range):
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    if date_range and date_range.get("start") and date_range.get("end"):
        try:
            start_date = pd.to_datetime(date_range["start"])
            end_date = pd.to_datetime(date_range["end"])
        except Exception:
            pass

    fig = go.Figure()

    fig.update_layout(
        title="Свечной график с торговыми сигналами",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=500,
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )
    if not trader_id:
        return fig

    trader = Trader.objects.get(id=trader_id)
    candles = Candle.objects.filter(
        exchange=trader.exchange_client.exchange,
        timeframe=trader.timeframe,
        trading_pair=trader.trading_pair,
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    if not candles.exists():
        return fig

    df = pd.DataFrame.from_records(
        candles.values("timestamp", "open", "high", "low", "close")
    )

    df["timestamp"] = df["timestamp"].apply(localtime)

    # Получаем сигналы
    signals = TraderSignal.objects.filter(
        trader=trader,
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    buy_signals = signals.filter(type=SignalType.BUY)
    sell_signals = signals.filter(type=SignalType.SELL)
    wait_signals = signals.filter(type=SignalType.WAIT)

    # Добавляем свечной график
    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            close=df["close"],
            high=df["high"],
            low=df["low"],
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

    fig.add_trace(
        go.Scatter(
            x=[localtime(s.timestamp) for s in wait_signals],
            y=[s.price for s in wait_signals],
            mode="markers",
            name="Wait",
            marker=dict(color="blue", symbol="circle", size=10),
        )
    )
    return fig
