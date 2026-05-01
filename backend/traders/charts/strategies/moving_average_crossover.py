import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash

from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from traders.domain import MovingAverageCrossoverData
from traders.models import Trader

app = DjangoDash("MovingAverageCrossoverStrategy")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="moving_average_crossover-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("moving_average_crossover-chart", "figure"),
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
        title="График Moving Average Crossover",
        xaxis_title="Время",
        yaxis_title="Indicator Value",
        xaxis_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )

    try:
        trader = Trader.objects.select_related(
            "exchange_client__exchange",
            "strategy",
            "risk_manager",
            "candle_source__trading_pair__exchange",
            "candle_source__trading_pair",
        ).get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    trader.strategy.instantiate()

    records = []
    states = trader.states.order_by("timestamp")
    for state in states:
        if not state.signal or not state.signal.data:
            continue
        data = MovingAverageCrossoverData(**state.signal.data)
        records.append(
            {
                "timestamp": state.timestamp,
                "fast_avg": data.fast_upper,
                "slow_avg": data.slow_upper,
            }
        )

    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    # Приводим start_date и end_date к той же таймзоне
    tz = timezone.get_current_timezone()
    if timezone.is_naive(start_date):
        start_date = timezone.make_aware(start_date, tz)
    if timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date, tz)

    df = df[(df["timestamp"] >= start_date) & (df["timestamp"] <= end_date)]
    if df.empty:
        return fig

    # Hover-информация для fast_avg
    df["hovertext_fast_avg"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>Fast avg: "
        + df["fast_avg"].astype(str)
    )

    # Hover-информация для slow_avg
    df["hovertext_slow_avg"] = (
        "Дата: "
        + df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + "<br>Slow avg: "
        + df["slow_avg"].astype(str)
    )

    # Рисуем линию fast_avg
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["fast_avg"],
            mode="lines+markers",
            name="Fast avg",
            line={"color": "blue"},
            hovertext=df["hovertext_fast_avg"],
        )
    )

    # Рисуем линию slow_avg
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["slow_avg"],
            mode="lines+markers",
            name="Slow avg",
            line={"color": "orange"},
            hovertext=df["hovertext_slow_avg"],
        )
    )

    return fig
