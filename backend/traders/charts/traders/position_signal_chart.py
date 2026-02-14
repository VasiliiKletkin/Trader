from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash

from traders.models import Trader
from traders.schemas import SignalType

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
        Input("trader-position-signal-chart", "relayoutData"),
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
        title="Свечной график с сигналами и позициями",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=500,
        xaxis_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )

    if not trader_id:
        return fig

    trader = Trader.objects.get(id=trader_id)
    # candles = trader.candle_source.get_candles(
    #     start_date=start_date,
    #     end_date=end_date,
    # )
    positions = trader.positions.filter(
        opened_at__range=(start_date, end_date),
    ).order_by("opened_at")
    signals = trader.signals.filter(
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

    # df_candles = pd.DataFrame(
    #     list(candles.values("timestamp", "open", "high", "low", "close"))
    # )
    # if df_candles.empty:
    #     return fig

    # df_candles["timestamp"] = pd.to_datetime(df_candles["timestamp"])
    # df_candles["timestamp"] = df_candles["timestamp"].apply(localtime)

    # # Добавляем свечной график
    # fig.add_trace(
    #     go.Candlestick(
    #         x=df_candles["timestamp"],
    #         open=df_candles["open"],
    #         close=df_candles["close"],
    #         high=df_candles["high"],
    #         low=df_candles["low"],
    #     )
    # )

    buy_signals = [s for s in signals if s.type == SignalType.BUY]
    sell_signals = [s for s in signals if s.type == SignalType.SELL]
    wait_signals = [s for s in signals if s.type == SignalType.WAIT]

    # BUY сигналы: triangle-up, зеленый
    if buy_signals:
        fig.add_trace(
            go.Scatter(
                x=[localtime(s.timestamp) for s in buy_signals],
                y=[float(s.price) for s in buy_signals],
                mode="markers",
                name="BUY Signals",
                marker={"color": "green", "symbol": "triangle-up", "size": 15},
                hovertext=[f"{s.get_type_display()}|{s.price}" for s in buy_signals],
            )
        )

    # SELL сигналы: triangle-down, красный
    if sell_signals:
        fig.add_trace(
            go.Scatter(
                x=[localtime(s.timestamp) for s in sell_signals],
                y=[float(s.price) for s in sell_signals],
                mode="markers",
                name="SELL Signals",
                marker={"color": "red", "symbol": "triangle-down", "size": 15},
                hovertext=[f"{s.get_type_display()}|{s.price}" for s in sell_signals],
            )
        )

    # WAIT сигналы: circle, синий
    if wait_signals:
        fig.add_trace(
            go.Scatter(
                x=[localtime(s.timestamp) for s in wait_signals],
                y=[float(s.price) for s in wait_signals],
                mode="markers",
                name="WAIT Signals",
                marker={"color": "blue", "symbol": "circle", "size": 15},
                hovertext=[f"{s.get_type_display()}|{s.price}" for s in wait_signals],
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
            marker={"color": "blue", "symbol": "circle", "size": 20},
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
            marker={"color": "orange", "symbol": "x", "size": 20},
            hovertext=[
                f"id{p.pk} CLOSE {p.type}|{round(p.close_price, 4)}|Reason: {p.get_close_reason_display()}|PNL: {round(p.pnl, 2)}"
                for p in closed_positions
            ],
        )
    )
    return fig
