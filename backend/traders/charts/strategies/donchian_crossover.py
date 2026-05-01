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
from core.utils.common import dt_str
from traders.domain import DonchianCrossoverData
from traders.models import Trader

app = DjangoDash("DonchianCrossoverStrategy")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="donchian_crossover-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("donchian_crossover-chart", "figure"),
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
        title="График Donchian Crossover",
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

    records = []
    signals = trader.signals.filter(timestamp__range=(start_date, end_date)).order_by(
        "timestamp"
    )
    for signal in signals:
        data = DonchianCrossoverData(**signal.data)
        records.append(
            {
                "timestamp": signal.timestamp,
                "fast_upper": data.fast_upper,
                "fast_lower": data.fast_lower,
                "slow_upper": data.slow_upper,
                "slow_lower": data.slow_lower,
            }
        )

    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    if df.empty:
        return fig

    df["hovertext_fast_upper"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Fast upper: "
        + df["fast_upper"].astype(str)
    )

    df["hovertext_fast_lower"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Fast lower: "
        + df["fast_lower"].astype(str)
    )

    df["hovertext_slow_upper"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Slow upper: "
        + df["slow_upper"].astype(str)
    )

    df["hovertext_slow_lower"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Slow lower: "
        + df["slow_lower"].astype(str)
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["fast_upper"],
            mode="lines+markers",
            name="Fast upper",
            line={"color": "orange"},
            hovertext=df["hovertext_fast_upper"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["fast_lower"],
            mode="lines+markers",
            name="Fast lower",
            line={"color": "orange"},
            hovertext=df["hovertext_fast_lower"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["slow_upper"],
            mode="lines+markers",
            name="Slow upper",
            line={"color": "orange"},
            hovertext=df["hovertext_slow_upper"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["slow_lower"],
            mode="lines+markers",
            name="Slow lower",
            line={"color": "orange"},
            hovertext=df["hovertext_slow_lower"],
        )
    )

    return fig
