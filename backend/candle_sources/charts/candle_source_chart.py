import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash

from candle_sources.models import CandleSource
from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)

app = DjangoDash("CandleSourceChart")
app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Store(id="candle-source-id", data=None),
        dcc.Graph(id="candle-source-chart"),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("candle-source-chart", "figure"),
    [
        Input("candle-source-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_chart(source_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

    fig = go.Figure()
    fig.update_layout(
        title="Свечной график",
        xaxis_title="Время",
        yaxis_title="Цена",
        height=500,
        xaxis_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )

    if not source_id:
        return fig

    source = CandleSource.objects.get(id=source_id)
    candles = source.get_candles(start=start_date, end=end_date)

    df = pd.DataFrame(
        list(candles.values("timestamp", "open", "high", "low", "close", "volume"))
    )
    if df.empty:
        return fig

    df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(localtime)

    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
        )
    )

    fig.add_trace(
        go.Bar(
            x=df["timestamp"],
            y=df["volume"],
            name="Volume",
            yaxis="y2",
            marker_color="rgba(100, 149, 237, 0.3)",
        )
    )

    fig.update_layout(
        yaxis2={
            "title": "Volume",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "range": [0, df["volume"].max() * 4],
        },
    )

    return fig
