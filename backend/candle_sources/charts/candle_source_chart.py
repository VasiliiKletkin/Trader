from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash

from candle_sources.models import CandleSource

app = DjangoDash("CandleSourceChart")
app.layout = html.Div(
    [
        dcc.Graph(id="candle-source-chart"),
        dcc.Store(id="candle-source-id", data=None),
        dcc.Store(id="candle-source-date-range", data=None),
    ]
)


@app.callback(
    Output("candle-source-date-range", "data"),
    [Input("candle-source-chart", "relayoutData")],
    [State("candle-source-date-range", "data")],
)
def update_date_range(relayout_data, stored_range):
    if relayout_data:
        x0 = relayout_data.get("xaxis.range[0]")
        x1 = relayout_data.get("xaxis.range[1]")
        if x0 and x1:
            return {"start": x0, "end": x1}
        if relayout_data.get("xaxis.autorange"):
            return None
    return stored_range


@app.callback(
    Output("candle-source-chart", "figure"),
    [
        Input("candle-source-id", "data"),
        Input("candle-source-date-range", "data"),
    ],
)
def update_chart(source_id, date_range):
    end_date = timezone.now()
    start_date = end_date - timedelta(days=7)

    if date_range and date_range.get("start") and date_range.get("end"):
        try:
            start_date = pd.to_datetime(date_range["start"])
            end_date = pd.to_datetime(date_range["end"])
        except Exception:
            pass

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

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(localtime)

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
