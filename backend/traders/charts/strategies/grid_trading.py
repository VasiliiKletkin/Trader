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
from traders.domain import GridTradingData
from traders.models import Trader

app = DjangoDash("GridTradingStrategy")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="grid_trading-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("grid_trading-chart", "figure"),
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
        title="График Grid Trading",
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

    records = []
    states = trader.states.filter(
        timestamp__gte=start_date, timestamp__lte=end_date
    ).order_by("timestamp")
    for state in states:
        if not state.signal or not state.signal.data:
            continue
        data = GridTradingData(**state.signal.data)
        records.append(
            {
                "timestamp": state.timestamp,
                "candle_close": data.candle_close,
                "avg": data.avg,
                "narrow_grid_up": data.narrow_grid_up,
                "narrow_grid_down": data.narrow_grid_down,
                "wide_grid_up": data.wide_grid_up,
                "wide_grid_down": data.wide_grid_down,
            }
        )
    df = pd.DataFrame(records)

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)
    if df.empty:
        return fig

    df["hovertext_candle_close"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>candle_close: "
        + df["candle_close"].astype(str)
    )

    df["hovertext_avg"] = (
        "Дата: " + df["timestamp"].apply(dt_str) + "<br>avg: " + df["avg"].astype(str)
    )

    df["hovertext_narrow_grid_up"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>narrow grid up: "
        + df["narrow_grid_up"].astype(str)
    )

    df["hovertext_narrow_grid_down"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>narrow grid down: "
        + df["narrow_grid_down"].astype(str)
    )

    df["hovertext_wide_grid_up"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>wide grid up: "
        + df["wide_grid_up"].astype(str)
    )

    df["hovertext_wide_grid_down"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>wide grid down: "
        + df["wide_grid_down"].astype(str)
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["candle_close"],
            mode="lines+markers",
            name="candle_close",
            line={"color": "green"},
            hovertext=df["hovertext_candle_close"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["avg"],
            mode="lines+markers",
            name="avg",
            line={"color": "orange"},
            hovertext=df["hovertext_avg"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["narrow_grid_up"],
            mode="lines+markers",
            name="narrow grid up",
            line={"color": "orange"},
            hovertext=df["hovertext_narrow_grid_up"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["narrow_grid_down"],
            mode="lines+markers",
            name="narrow grid down",
            line={"color": "orange"},
            hovertext=df["hovertext_narrow_grid_down"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["wide_grid_up"],
            mode="lines+markers",
            name="wide grid up",
            line={"color": "orange"},
            hovertext=df["hovertext_wide_grid_up"],
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["wide_grid_down"],
            mode="lines+markers",
            name="wide grid down",
            line={"color": "orange"},
            hovertext=df["hovertext_wide_grid_down"],
        )
    )

    return fig
