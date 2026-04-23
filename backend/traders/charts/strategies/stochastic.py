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
from traders.domain import StochasticData, StochasticStrategy
from traders.models import Trader

app = DjangoDash("StochasticStrategy")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="stochastic-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("stochastic-chart", "figure"),
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
        title="График Stochastic (K и D)",
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
            "candle_source__exchange",
            "candle_source__trading_pair",
        ).get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    strategy: StochasticStrategy = trader.strategy.instantiate()
    overbought = strategy.overbought
    oversold = strategy.oversold

    records = []
    signals = trader.signals.filter(
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")
    for signal in signals:
        data = StochasticData(**signal.data)
        records.append(
            {
                "timestamp": signal.timestamp,
                "k_value": data.k_value,
                "d_value": data.d_value,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        return fig

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)

    if df.empty:
        return fig

    df["hovertext_k"] = (
        "Дата: " + df["timestamp"].apply(dt_str) + "<br>K: " + df["k_value"].astype(str)
    )

    df["hovertext_d"] = (
        "Дата: " + df["timestamp"].apply(dt_str) + "<br>D: " + df["d_value"].astype(str)
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["k_value"],
            mode="lines+markers",
            name="K",
            line={"color": "blue"},
            hovertext=df["hovertext_k"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["d_value"],
            mode="lines+markers",
            name="D",
            line={"color": "orange"},
            hovertext=df["hovertext_d"],
        )
    )

    if overbought is not None:
        fig.add_trace(
            go.Scatter(
                x=[df["timestamp"].min(), df["timestamp"].max()],
                y=[overbought, overbought],
                mode="lines",
                name="Overbought",
                line={"color": "red", "dash": "dash"},
                showlegend=True,
            )
        )
    if oversold is not None:
        fig.add_trace(
            go.Scatter(
                x=[df["timestamp"].min(), df["timestamp"].max()],
                y=[oversold, oversold],
                mode="lines",
                name="Oversold",
                line={"color": "green", "dash": "dash"},
                showlegend=True,
            )
        )

    return fig
