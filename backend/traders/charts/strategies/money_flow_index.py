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
from traders.domain import MoneyFlowIndexStrategy, MoneyFlowIndexStrategyData
from traders.models import Trader

app = DjangoDash("MoneyFlowIndexStrategy")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Graph(id="money_flow_index-chart"),
        dcc.Store(id="trader-id", data=None),
    ]
)

register_date_preset_callbacks(app)


@app.callback(
    Output("money_flow_index-chart", "figure"),
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
        title="График MFI",
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

    strategy: MoneyFlowIndexStrategy = trader.strategy.instantiate()
    overbought = strategy.overbought
    oversold = strategy.oversold

    records = []
    signals = trader.signals.filter(
        timestamp__range=(start_date, end_date),
    ).order_by("timestamp")
    for signal in signals:
        data = MoneyFlowIndexStrategyData(**signal.data)
        records.append(
            {
                "timestamp": signal.timestamp,
                "mfi": data.mfi_value,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        return fig

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)

    df["hovertext"] = (
        "Дата: " + df["timestamp"].apply(dt_str) + "<br>MFI: " + df["mfi"].astype(str)
    )

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["mfi"],
            mode="lines+markers",
            name="MFI",
            line={"color": "blue"},
            hovertext=df["hovertext"],
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
