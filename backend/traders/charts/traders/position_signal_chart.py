import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash

from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from traders.models import Trader
from traders.schemas import SignalType

app = DjangoDash("PositionSignalChart")
app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="trader-position-signal-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("trader-position-signal-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_chart(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

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
    positions = trader.positions.filter(
        opened_at__range=(start_date, end_date),
    ).order_by("opened_at")
    signals = trader.signals.filter(
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")

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
