from datetime import timedelta

import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from strategies.domain import MFIData, MoneyFlowIndexStrategy
from traders.models import Trader
from core.utils.common import dt_str  # Добавьте импорт

app = DjangoDash("MoneyFlowIndexStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="money_flow_index-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="money_flow_index-date-range", data=None),
    ]
)


# Callback для хранения диапазона дат (zoom/pan/autoscale)
@app.callback(
    Output("money_flow_index-date-range", "data"),
    [
        Input("money_flow_index-chart", "relayoutData"),
    ],
    [
        State("money_flow_index-date-range", "data"),
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
    Output("money_flow_index-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("money_flow_index-date-range", "data"),
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
        title="График MFI",
        xaxis_title="Время",
        yaxis_title="Indicator Value",
        xaxis_rangeslider_visible=False,
        legend=dict(x=0, y=1),
    )

    try:
        trader = Trader.objects.get(pk=trader_id)
    except Trader.DoesNotExist:
        return fig

    strategy: MoneyFlowIndexStrategy = trader.strategy.instantiate()
    overbought = strategy.overbought
    oversold = strategy.oversold

    records = []
    # Добавлена фильтрация по дате для оптимизации запроса
    states = trader.states.filter(
        timestamp__gte=start_date, timestamp__lte=end_date
    ).order_by("timestamp")
    for state in states:
        if not state.signal or not state.signal.data:
            continue
        data = MFIData(**state.signal.data)
        records.append(
            {
                "timestamp": state.timestamp,
                "mfi": data.mfi_value,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        return fig

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)

    # Hover-информация с использованием dt_str
    df["hovertext"] = (
        "Дата: "
        + df["timestamp"].apply(dt_str)
        + "<br>MFI: "
        + df["mfi"].astype(str)
    )

    # Рисуем линию MFI
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["mfi"],
            mode="lines+markers",
            name="MFI",
            line=dict(color="blue"),
            hovertext=df["hovertext"],
        )
    )
    # Добавляем горизонтальные линии overbought/oversold
    if overbought is not None:
        fig.add_trace(
            go.Scatter(
                x=[df["timestamp"].min(), df["timestamp"].max()],
                y=[overbought, overbought],
                mode="lines",
                name="Overbought",
                line=dict(color="red", dash="dash"),
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
                line=dict(color="green", dash="dash"),
                showlegend=True,
            )
        )

    return fig
