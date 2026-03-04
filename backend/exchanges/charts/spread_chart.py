from itertools import combinations

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash

from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from exchanges.models import Exchange, ExchangeCandle, ExchangeTradingPair

app = DjangoDash("SpreadChart")

app.layout = html.Div(
    [
        create_date_picker_range(days=1),
        dcc.Store(id="trading-pair-id", data=None),
        dcc.Graph(id="spread-chart"),
    ]
)

register_date_preset_callbacks(app)

COLORS = [
    "#636EFA",
    "#EF553B",
    "#00CC96",
    "#AB63FA",
    "#FFA15A",
    "#19D3F3",
    "#FF6692",
    "#B6E880",
    "#FF97FF",
    "#FECB52",
]


@app.callback(
    Output("spread-chart", "figure"),
    [
        Input("trading-pair-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_spread_chart(trading_pair_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str, days=1)

    fig = go.Figure()
    fig.update_layout(
        title="Спред между биржами",
        xaxis_title="Время",
        yaxis_title="Соотношение цен",
        height=600,
        xaxis_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )

    if not trading_pair_id:
        return fig

    exchange_ids = list(
        ExchangeTradingPair.objects.filter(
            trading_pair_id=trading_pair_id,
        ).values_list("exchange_id", flat=True)
    )

    if len(exchange_ids) < 2:
        fig.add_annotation(
            text="Недостаточно бирж для расчёта спреда (нужно минимум 2)",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        return fig

    exchanges = {e.pk: e.name for e in Exchange.objects.filter(pk__in=exchange_ids)}

    exchange_dfs = {}
    for exchange_id in exchange_ids:
        candles = (
            ExchangeCandle.objects.filter(
                exchange_id=exchange_id,
                trading_pair_id=trading_pair_id,
                timeframe="1m",
                timestamp__gte=start_date,
                timestamp__lte=end_date,
            )
            .order_by("timestamp")
            .values("timestamp", "close")
        )

        df = pd.DataFrame(list(candles))
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(localtime)
            exchange_dfs[exchange_id] = df

    if len(exchange_dfs) < 2:
        fig.add_annotation(
            text="Недостаточно данных свечей для расчёта спреда",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font={"size": 16},
        )
        return fig

    for idx, (ex_a, ex_b) in enumerate(combinations(exchange_dfs.keys(), 2)):
        df_a = exchange_dfs[ex_a]
        df_b = exchange_dfs[ex_b]

        merged = pd.merge(
            df_a[["timestamp", "close"]],
            df_b[["timestamp", "close"]],
            on="timestamp",
            suffixes=("_a", "_b"),
        )
        if merged.empty:
            continue

        merged["ratio"] = merged["close_a"] / merged["close_b"]

        name_a = exchanges.get(ex_a, str(ex_a))
        name_b = exchanges.get(ex_b, str(ex_b))
        color = COLORS[idx % len(COLORS)]

        fig.add_trace(
            go.Scatter(
                x=merged["timestamp"],
                y=merged["ratio"],
                mode="lines",
                name=f"{name_a} / {name_b}",
                line={"color": color, "width": 1.5},
            )
        )

    fig.add_hline(
        y=1.0,
        line_dash="dash",
        line_color="gray",
        annotation_text="1.0",
    )

    return fig
