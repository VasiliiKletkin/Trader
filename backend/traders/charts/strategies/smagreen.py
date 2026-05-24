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
from traders.domain import SMAGreenData
from traders.models import Trader

app = DjangoDash("SMAGreenStrategy")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="SMA_Green-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("SMA_Green-chart", "figure"),
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
        title="График SMA Green",
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
        data = SMAGreenData(**signal.data)
        records.append(
            {
                "timestamp": signal.timestamp,
                "sma": data.sma,
            }
        )

    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    if df.empty:
        return fig

    df["hovertext_sma"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>Fast upper: "
        + df["sma"].astype(str)
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["sma"],
            mode="lines+markers",
            name="Fast upper",
            line={"color": "orange"},
            hovertext=df["hovertext_sma"],
        )
    )

    return fig
