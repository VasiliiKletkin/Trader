from datetime import timedelta
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html
from django.utils import timezone
from django_plotly_dash import DjangoDash
from traders.models import Trader

app = DjangoDash("EquityCurveChart")
app.layout = html.Div(
    [
        dcc.Graph(id="trader-equity-curve-chart"),
        dcc.Graph(id="trader-weekly-profit-chart"),
        dcc.Graph(id="trader-12-week-profit-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="equity-date-range", data=None),
    ]
)


# # Первый callback: обновляет диапазон дат в Store при zoom/pan
@app.callback(
    Output("equity-date-range", "data"),
    [
        Input("trader-equity-curve-chart", "relayoutData"),
    ],
    [
        State("equity-date-range", "data"),
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
        Input("equity-date-range", "data"),
    ],
)
def update_equity_curve(trader_id, date_range):
    # Диапазон по умолчанию — 30 дней
    end_date = timezone.now()
    # start_date = end_date - timedelta(days=30)
    start_date = end_date - timedelta(days=365 * 3)

    # Если есть диапазон в Store — используем его
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

    positions = (
        trader.get_closed_positions()
        .filter(opened_at__range=(start_date, end_date))
        .order_by("opened_at")
    )
    if not positions:
        return fig

    cumulative_pnl = Decimal("0.0")
    equity_curve = []

    for pos in positions:
        pnl = pos.pnl or Decimal("0.0")
        cumulative_pnl += pnl
        equity_curve.append(
            {
                "timestamp": pos.closed_at,
                "cumulative_pnl": float(cumulative_pnl),
            }
        )

    df = pd.DataFrame(equity_curve)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["cumulative_pnl"],
            mode="lines+markers",
            name="Equity Curve",
            line=dict(color="blue"),
            hovertext=[
                f"Date: {row['timestamp'].strftime('%Y-%m-%d %H:%M')}<br>Profit: {row['cumulative_pnl']:.2f}"
                for _, row in df.iterrows()
            ],
        )
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
    data = []
    for pos in positions:
        data.append(
            {
                "day": pos.closed_at.date(),
                "pnl": float(pos.pnl or Decimal("0.0")),
                "open_volume": float(pos.open_volume),
                "amount": float(pos.amount),
            }
        )

    df = pd.DataFrame(data)
    df_grouped = df.groupby("day").agg({"pnl": "sum", "open_volume": "sum", "amount": "sum"}).reset_index()
    df_grouped["profit_per_open_volume"] = (df_grouped["pnl"] / df_grouped["open_volume"]) * 100

    fig.add_trace(
        go.Bar(
            x=df_grouped["day"],
            y=df_grouped["profit_per_open_volume"],
            name="Daily Profit",
            marker_color="green",
            hovertext=[
                f"Day: {row['day']}<br>Sum Pnl: {row['pnl']:.2f}<br>Sum Open Volume: {row['open_volume']:.2f}<br>Sum Amount: {row['amount']:.2f}"
                for _, row in df_grouped.iterrows()
            ],
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
    data = []
    for pos in positions:
        week_start = pos.closed_at - timedelta(days=pos.closed_at.weekday())
        week_start = week_start.date()
        data.append(
            {
                "week": week_start,
                "pnl": float(pos.pnl or Decimal("0.0")),
                "open_volume": float(pos.open_volume),
                "amount": float(pos.amount),
            }
        )

    df = pd.DataFrame(data)
    df_grouped = df.groupby("week").agg({"pnl": "sum", "open_volume": "sum", "amount": "sum"}).reset_index()
    df_grouped["profit_per_open_volume"] = (df_grouped["pnl"] / df_grouped["open_volume"]) * 100

    fig.add_trace(
        go.Bar(
            x=df_grouped["week"],
            y=df_grouped["profit_per_open_volume"],
            name="Weekly Profit",
            marker_color="orange",
            hovertext=[
                f"Week: {row['week']} - {row['week'] + timedelta(days=6)}<br>Sum Pnl: {row['pnl']:.2f}<br>Sum Open Volume: {row['open_volume']:.2f}<br>Sum Amount: {row['amount']:.2f}"
                for _, row in df_grouped.iterrows()
            ],
        )
    )

    return fig
