from datetime import timedelta
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import numpy as np
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from traders.models import Trader, TraderOrder
from core.utils.common import dt_str
from django.db.models import Exists, OuterRef

app = DjangoDash("EquityCurveChart")
app.layout = html.Div(
    [
        dcc.Graph(id="trader-equity-curve-chart"),
        dcc.Graph(id="trader-weekly-profit-chart"),
        dcc.Graph(id="trader-12-week-profit-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="trader-equity-date-range", data=None),
    ]
)


# # Первый callback: обновляет диапазон дат в Store при zoom/pan
@app.callback(
    Output("trader-equity-date-range", "data"),
    [
        Input("trader-equity-curve-chart", "relayoutData"),
    ],
    [
        State("trader-equity-date-range", "data"),
    ],
)
def update_date_range(relayout_data, stored_range):
    if relayout_data:
        x0 = relayout_data.get("xaxis.range[0]")
        x1 = relayout_data.get("xaxis.range[1]")
        if x0 and x1:
            return {"start": x0, "end": x1}
        # Если autoscale/reset — relayoutData содержит xaxis.autorange
        if relayout_data.get("xaxis.autorange") or relayout_data.get(
            "xaxis.autorange", False
        ):
            return None
    return stored_range


# Второй callback: строит график, используя диапазон из Store
@app.callback(
    Output("trader-equity-curve-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("trader-equity-date-range", "data"),
    ],
)
def update_equity_curve(trader_id, date_range):
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
        title="Кривая профита трейдера на позициях",
        xaxis_title="Время",
        yaxis_title="Профит",
        xaxis_rangeslider_visible=False,
        autosize=True,
    )

    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        return fig

    cumulative_pnl = Decimal("0.0")
    records = []
    positions = (
        trader.closed_positions.filter(opened_at__range=(start_date, end_date))
        .annotate(
            has_orders=Exists(TraderOrder.objects.filter(position=OuterRef("pk")))
        )
        .order_by("opened_at")
    )

    for pos in positions:
        pnl = pos.pnl or Decimal("0.0")
        cumulative_pnl += pnl
        has_orders = pos.has_orders
        records.append(
            {
                "timestamp": pos.closed_at,
                "cumulative_pnl": float(cumulative_pnl),
                "has_orders": has_orders,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        return fig

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["timestamp"] = df["timestamp"].apply(timezone.localtime)

    df["hovertext"] = [
        f"Date: {dt_str(row['timestamp'])}<br>Profit: {row['cumulative_pnl']:.2f}<br>Orders: {'Yes' if row['has_orders'] else 'No'}"
        for _, row in df.iterrows()
    ]

    # Цвета: красный для позиций с ордерами, синий для без
    colors = ["red" if has_orders else "blue" for has_orders in df["has_orders"]]

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["cumulative_pnl"],
            mode="lines+markers",
            name="Equity Curve",
            line=dict(color="blue"),
            marker=dict(color=colors),
            hovertext=df["hovertext"],
        )
    )

    # Минимальный расчёт линейной трендовой и R²
    if len(df) >= 2:
        x = np.arange(len(df))
        y = df["cumulative_pnl"].to_numpy()
        m, b = np.polyfit(x, y, 1)
        y_pred = m * x + b
        ss_res = ((y - y_pred) ** 2).sum()
        ss_tot = ((y - y.mean()) ** 2).sum()
        r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0

        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=y_pred,
                mode="lines",
                name="Trend",
                line=dict(color="red", dash="dash"),
                hoverinfo="skip",
            )
        )
        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=0.01,
            y=0.99,
            xanchor="left",
            yanchor="top",
            text=f"R² = {r2:.4f}",
            showarrow=False,
            bgcolor="rgba(255,255,255,0.8)",
        )

    return fig


# Новый callback для недельного графика профита
@app.callback(
    Output("trader-weekly-profit-chart", "figure"),
    [
        Input("trader-id", "data"),
    ],
)
def update_weekly_profit_chart(trader_id):
    fig = go.Figure()
    fig.update_layout(
        title="Профит за текущую неделю (по дням)",
        xaxis_title="День",
        yaxis_title="Профит",
        autosize=True,
    )

    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        return fig

    now = timezone.now()
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

    positions = trader.closed_positions.filter(closed_at__gte=start_of_week).order_by(
        "closed_at"
    )

    if not positions:
        return fig

    # Группировка по дням
    records = []
    for pos in positions:
        records.append(
            {
                "day": pos.closed_at.date(),
                "pnl": float(pos.pnl or Decimal("0.0")),
                "open_cost": float(pos.open_cost),
                "amount": float(pos.amount),
            }
        )

    df = pd.DataFrame(records)
    df_grouped = (
        df.groupby("day")
        .agg({"pnl": "sum", "open_cost": "sum", "amount": "sum"})
        .reset_index()
    )
    df_grouped["profit_per_open_cost"] = (
        df_grouped["pnl"] / df_grouped["open_cost"]
    ) * 100

    df_grouped["hovertext"] = [
        f"Day: {row['day']}<br>Sum Pnl: {row['pnl']:.2f}<br>Sum Open Cost: {row['open_cost']:.2f}<br>Sum Amount: {row['amount']:.2f}"
        for _, row in df_grouped.iterrows()
    ]

    fig.add_trace(
        go.Bar(
            x=df_grouped["day"],
            y=df_grouped["profit_per_open_cost"],
            name="Daily Profit",
            marker_color="green",
            hovertext=df_grouped["hovertext"],
        )
    )

    return fig


# Новый callback для графика профита за 12 недель
@app.callback(
    Output("trader-12-week-profit-chart", "figure"),
    [
        Input("trader-id", "data"),
    ],
)
def update_12_week_profit_chart(trader_id):
    fig = go.Figure()
    fig.update_layout(
        title="Профит за последние 12 недель",
        xaxis_title="Неделя",
        yaxis_title="Профит",
        autosize=True,
    )

    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        return fig

    # Получить дату 12 недель назад
    start_date = timezone.now() - timedelta(weeks=12)

    positions = (
        trader.get_closed_positions()
        .filter(closed_at__gte=start_date)
        .order_by("closed_at")
    )

    if not positions:
        return fig

    # Группировка по неделям
    records = []
    for pos in positions:
        week_start = pos.closed_at - timedelta(days=pos.closed_at.weekday())
        week_start = week_start.date()
        records.append(
            {
                "week": week_start,
                "pnl": float(pos.pnl or Decimal("0.0")),
                "open_cost": float(pos.open_cost),
                "amount": float(pos.amount),
            }
        )

    df = pd.DataFrame(records)
    df_grouped = (
        df.groupby("week")
        .agg({"pnl": "sum", "open_cost": "sum", "amount": "sum"})
        .reset_index()
    )
    df_grouped["profit_per_open_cost"] = (
        df_grouped["pnl"] / df_grouped["open_cost"]
    ) * 100

    df_grouped["hovertext"] = [
        f"Week: {row['week']} - {row['week'] + timedelta(days=6)}<br>Sum Pnl: {row['pnl']:.2f}<br>Sum Open Cost: {row['open_cost']:.2f}<br>Sum Amount: {row['amount']:.2f}"
        for _, row in df_grouped.iterrows()
    ]

    fig.add_trace(
        go.Bar(
            x=df_grouped["week"],
            y=df_grouped["profit_per_open_cost"],
            name="Weekly Profit",
            marker_color="orange",
            hovertext=df_grouped["hovertext"],
        )
    )

    return fig
