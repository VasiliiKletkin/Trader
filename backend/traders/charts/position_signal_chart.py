from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from core.utils.types import PositionStatus
from exchanges.models import Candle
from traders.models import Trader, TraderPosition

from datetime import timedelta
from typing import List

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from core.utils.types import SignalType
from exchanges.models import Candle
from traders.models import Trader, TraderSignal

app = DjangoDash("PositionSignalChart")
app.layout = html.Div(
    [
        dcc.Graph(id="trader-position-signal-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="trader-position-signal-date-range", data=None),
        # dcc.Interval(
        #     id="interval-component",
        #     interval=60 * 1000,
        #     n_intervals=0,
        # ),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("trader-position-signal-date-range", "data"),
    [
        Input("trader-position-chart", "relayoutData"),
    ],
    [
        State("trader-position-signal-date-range", "data"),
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
    Output("trader-position-signal-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("trader-position-signal-date-range", "data"),
    ],
)
def update_chart(trader_id, date_range):
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
        title="Свечной график c позициями и сигналами",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=500,
        xaxis_rangeslider_visible=True,
        legend=dict(x=0, y=1),
    )

    if not trader_id:
        return fig

    trader = Trader.objects.get(id=trader_id)
    candles = trader.candles.filter(
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")
    positions = trader.positions.filter(
        opened_at__range=(start_date, end_date),
    ).order_by("opened_at")
    signals = trader.signals.filter(
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    df_candles = pd.DataFrame.from_records(
        candles.values("timestamp", "open", "high", "low", "close")
    )
    df_candles["timestamp"] = df_candles["timestamp"].apply(localtime)

    buy_signals: List[TraderSignal] = []
    sell_signals: List[TraderSignal] = []
    wait_signals: List[TraderSignal] = []

    for signal in signals:
        if signal.type == SignalType.BUY:
            buy_signals.append(signal)
        elif signal.type == SignalType.SELL:
            sell_signals.append(signal)
        elif signal.type == SignalType.WAIT:
            wait_signals.append(signal)

    # Добавляем свечной график
    fig.add_trace(
        go.Candlestick(
            x=df_candles["timestamp"],
            open=df_candles["open"],
            close=df_candles["close"],
            high=df_candles["high"],
            low=df_candles["low"],
        )
    )

    # Входы в позиции
    opened_positions = positions.filter(opened_at__isnull=False)
    fig.add_trace(
        go.Scatter(
            x=[localtime(p.opened_at) for p in opened_positions],
            y=[float(p.open_price) * 0.999 for p in opened_positions],
            mode="markers",
            name="Position Open",
            marker=dict(color="blue", symbol="circle", size=20),
            hovertext=[
                f"id{p.pk} OPEN {p.type}|{p.open_price}" for p in opened_positions
            ],
        )
    )

    # Закрытые позиции
    closed_positions = positions.filter(closed_at__isnull=False)
    fig.add_trace(
        go.Scatter(
            x=[localtime(p.closed_at) for p in closed_positions],
            y=[float(p.close_price) * 1.001 for p in closed_positions],
            mode="markers",
            name="Position Close",
            marker=dict(color="orange", symbol="x", size=20),
            hovertext=[
                f"id{p.pk} CLOSE {p.type}|{round(p.close_price, 4)}|Reason: {p.get_close_reason_display()}|PNL: {round(p.pnl, 2)}"
                for p in closed_positions
            ],
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
            hovertext=[
                (
                    f"Signal: {s.get_type_display()}<br>"
                    f"Time: {localtime(s.timestamp).strftime('%d %H:%M')}<br>"
                    f"Price: {s.price}<br>"
                    f"Data: {s.data}<br>"
                    f"ID: {s.pk}"
                )
                for s in buy_signals
            ],
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
            hovertext=[
                (
                    f"Signal: {s.get_type_display()}<br>"
                    f"Time: {localtime(s.timestamp).strftime('%d %H:%M')}<br>"
                    f"Price: {s.price}<br>"
                    f"Data: {s.data}<br>"
                    f"ID: {s.pk}"
                )
                for s in sell_signals
            ],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=[localtime(s.timestamp) for s in wait_signals],
            y=[s.price for s in wait_signals],
            mode="markers",
            name="Wait",
            marker=dict(color="blue", symbol="circle", size=10),
            hovertext=[
                (
                    f"Signal: {s.get_type_display()}<br>"
                    f"Time: {localtime(s.timestamp).strftime('%d %H:%M')}<br>"
                    f"Price: {s.price}<br>"
                    f"Data: {s.data}<br>"
                    f"ID: {s.pk}"
                )
                for s in wait_signals
            ],
        )
    )
    return fig
