from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.db.models import Exists, FloatField, OuterRef
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from plotly.subplots import make_subplots

from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from core.utils.common import (
    dt_str,
    format_amount,
    format_fee,
    format_pnl,
    format_price,
    format_spread,
)
from exchange_clients.schemas import OrderSide
from traders.models import Trader, TraderOrder
from traders.schemas import PositionType, SignalType

app = DjangoDash("TraderChart")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Store(id="trader-id", data=None),
        dcc.Graph(id="trader-candle-chart"),
        dcc.Graph(id="trader-equity-curve-chart"),
        dcc.Graph(id="trader-weekly-profit-chart"),
        dcc.Graph(id="trader-12-week-profit-chart"),
        dcc.Graph(id="trader-lag-chart"),
    ]
)

register_date_preset_callbacks(app)


# ==================== Свечной график с сигналами и позициями ====================


def _create_candle_figure():
    """Свечной график с secondary Y для объёмов."""
    fig = make_subplots(
        rows=1,
        cols=1,
        specs=[[{"secondary_y": True}]],
    )
    fig.update_layout(
        title="Свечной график с сигналами и ордерами",
        height=700,
        xaxis_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )
    return fig


def _add_candlestick(fig, candles_qs):
    """Добавить свечной график и объёмы."""
    candles_qs = candles_qs.annotate(
        open_f=Cast("open", FloatField()),
        high_f=Cast("high", FloatField()),
        low_f=Cast("low", FloatField()),
        close_f=Cast("close", FloatField()),
        volume_f=Cast("volume", FloatField()),
    ).values("timestamp", "open_f", "high_f", "low_f", "close_f", "volume_f")

    df = pd.DataFrame(list(candles_qs))
    if df.empty:
        return df

    df.rename(
        columns={
            "open_f": "open",
            "high_f": "high",
            "low_f": "low",
            "close_f": "close",
            "volume_f": "volume",
        },
        inplace=True,
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(localtime)
    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            showlegend=False,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=df["timestamp"],
            y=df["volume"],
            name="Volume",
            marker_color="rgba(100, 149, 237, 0.3)",
            showlegend=False,
        ),
        secondary_y=True,
    )
    fig.update_yaxes(
        showgrid=False,
        range=[0, df["volume"].max() * 4],
        secondary_y=True,
    )
    return df


def _add_signal_markers(fig, signals):
    """Добавить маркеры сигналов на свечной график."""
    signal_styles = {
        SignalType.BUY: {"color": "green", "symbol": "star", "size": 10},
        SignalType.SELL: {"color": "red", "symbol": "star", "size": 10},
        SignalType.WAIT: {"color": "gray", "symbol": "circle-open", "size": 5},
    }
    for signal_type, marker in signal_styles.items():
        filtered = [s for s in signals if s["type"] == signal_type]
        if not filtered:
            continue
        fig.add_trace(
            go.Scatter(
                x=[localtime(s["timestamp"]) for s in filtered],
                y=[float(s["price"]) for s in filtered],
                mode="markers",
                name=f"Signal {signal_type.label}",
                marker=marker,
                hovertext=[f"{signal_type.label}|{s['price']}" for s in filtered],
            ),
            secondary_y=False,
        )


def _add_order_markers(fig, orders):
    """Добавить маркеры ордеров на свечной график."""
    if not orders:
        return

    order_styles = {
        "buy": {"color": "green", "symbol": "triangle-up", "size": 12},
        "sell": {"color": "red", "symbol": "triangle-down", "size": 12},
    }
    for side, marker in order_styles.items():
        side_orders = [o for o in orders if o.order.side == side]
        if not side_orders:
            continue
        fig.add_trace(
            go.Scatter(
                x=[localtime(o.order.timestamp) for o in side_orders],
                y=[float(o.order.price) for o in side_orders],
                mode="markers",
                name=f"Order {side.upper()}",
                marker=marker,
                hovertext=[
                    f"#{o.order.exchange_order_id} "
                    f"{o.order.get_side_display()} "
                    f"{format_amount(o.order.amount)} "
                    f"@ {format_price(o.order.price)} "
                    f"fee: {format_fee(o.order.fee)}"
                    for o in side_orders
                ],
            ),
            secondary_y=False,
        )


@app.callback(
    Output("trader-candle-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_candle_chart(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)
    fig = _create_candle_figure()

    if not trader_id:
        return fig

    trader = Trader.objects.select_related(
        "candle_source__exchange",
        "candle_source__trading_pair",
        "exchange_client",
    ).get(id=trader_id)

    _add_candlestick(
        fig,
        trader.candle_source.get_candles(start=start_date, end=end_date),
    )

    signals = list(
        trader.signals.filter(
            timestamp__range=(start_date, end_date),
        )
        .order_by("timestamp")
        .values("timestamp", "type", "price")
    )
    _add_signal_markers(fig, signals)

    orders = list(
        trader.orders.filter(
            order__timestamp__range=(start_date, end_date),
        ).select_related("order")
    )
    _add_order_markers(fig, orders)

    fig.update_yaxes(title_text="Цена", secondary_y=False)
    fig.update_yaxes(title_text="Объём", secondary_y=True)
    fig.update_xaxes(title_text="Время")

    return fig


# ==================== Кривая профита ====================


@app.callback(
    Output("trader-equity-curve-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_equity_curve(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

    fig = go.Figure()
    fig.update_layout(
        title="Кривая профита на позициях",
        xaxis_title="Время",
        yaxis_title="Профит",
        xaxis_rangeslider_visible=False,
        autosize=True,
    )

    if not trader_id:
        return fig

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
        records.append(
            {
                "timestamp": pos.closed_at,
                "pnl": float(pnl),
                "cumulative_pnl": float(cumulative_pnl),
                "has_orders": pos.has_orders,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        return fig

    df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(timezone.localtime)
    df["hovertext"] = [
        f"Дата: {dt_str(row['timestamp'])}<br>"
        f"PnL: {format_pnl(row['pnl'])}<br>"
        f"Кумулятивный: {format_pnl(row['cumulative_pnl'])}"
        for _, row in df.iterrows()
    ]
    colors = ["green" if row["pnl"] >= 0 else "red" for _, row in df.iterrows()]

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["cumulative_pnl"],
            mode="lines+markers",
            name="Equity Curve",
            line={"color": "blue"},
            marker={"color": colors, "size": 6},
            hovertext=df["hovertext"],
        )
    )

    if len(df) >= 2:
        x = df["timestamp"].astype(np.int64).to_numpy()
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
                name="Тренд",
                line={"color": "red", "dash": "dash"},
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
            text=f"R² = {format_spread(r2)}",
            showarrow=False,
            bgcolor="rgba(255,255,255,0.8)",
        )

    return fig


# ==================== Профит по дням (текущая неделя) ====================


@app.callback(
    Output("trader-weekly-profit-chart", "figure"),
    [Input("trader-id", "data")],
)
def update_weekly_profit_chart(trader_id):
    fig = go.Figure()
    fig.update_layout(
        title="Профит за текущую неделю (по дням)",
        xaxis_title="День",
        yaxis_title="Профит %",
        autosize=True,
    )

    if not trader_id:
        return fig

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

    records = [
        {
            "day": pos.closed_at.date(),
            "pnl": float(pos.pnl or Decimal("0.0")),
            "open_cost": float(pos.open_cost),
            "amount": float(pos.open_amount or 0),
        }
        for pos in positions
    ]

    df = pd.DataFrame(records)
    df_grouped = (
        df.groupby("day")
        .agg({"pnl": "sum", "open_cost": "sum", "amount": "sum"})
        .reset_index()
    )
    df_grouped["profit_pct"] = (df_grouped["pnl"] / df_grouped["open_cost"]) * 100

    df_grouped["hovertext"] = [
        f"День: {row['day']}<br>"
        f"PnL: {format_pnl(row['pnl'])}<br>"
        f"Open Cost: {format_pnl(row['open_cost'])}<br>"
        f"Amount: {format_pnl(row['amount'])}"
        for _, row in df_grouped.iterrows()
    ]

    fig.add_trace(
        go.Bar(
            x=df_grouped["day"],
            y=df_grouped["profit_pct"],
            name="Daily Profit",
            marker_color="green",
            hovertext=df_grouped["hovertext"],
        )
    )

    return fig


# ==================== Профит по неделям (12 недель) ====================


@app.callback(
    Output("trader-12-week-profit-chart", "figure"),
    [Input("trader-id", "data")],
)
def update_12_week_profit_chart(trader_id):
    fig = go.Figure()
    fig.update_layout(
        title="Профит за последние 12 недель",
        xaxis_title="Неделя",
        yaxis_title="Профит %",
        autosize=True,
    )

    if not trader_id:
        return fig

    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        return fig

    start_date = timezone.now() - timedelta(weeks=12)
    positions = (
        trader.get_closed_positions()
        .filter(closed_at__gte=start_date)
        .order_by("closed_at")
    )

    if not positions:
        return fig

    records = [
        {
            "week": (pos.closed_at - timedelta(days=pos.closed_at.weekday())).date(),
            "pnl": float(pos.pnl or Decimal("0.0")),
            "open_cost": float(pos.open_cost),
            "amount": float(pos.open_amount or 0),
        }
        for pos in positions
    ]

    df = pd.DataFrame(records)
    df_grouped = (
        df.groupby("week")
        .agg({"pnl": "sum", "open_cost": "sum", "amount": "sum"})
        .reset_index()
    )
    df_grouped["profit_pct"] = (df_grouped["pnl"] / df_grouped["open_cost"]) * 100

    df_grouped["hovertext"] = [
        f"Неделя: {row['week']} - {row['week'] + timedelta(days=6)}<br>"
        f"PnL: {format_pnl(row['pnl'])}<br>"
        f"Open Cost: {format_pnl(row['open_cost'])}<br>"
        f"Amount: {format_pnl(row['amount'])}"
        for _, row in df_grouped.iterrows()
    ]

    fig.add_trace(
        go.Bar(
            x=df_grouped["week"],
            y=df_grouped["profit_pct"],
            name="Weekly Profit",
            marker_color="orange",
            hovertext=df_grouped["hovertext"],
        )
    )

    return fig


# ==================== Лаг ордеров ====================


@app.callback(
    Output("trader-lag-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_lag_chart(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)

    fig = go.Figure()
    fig.update_layout(
        title="График задержки лага ордеров",
        xaxis_title="Время ордера",
        yaxis_title="Лаг (секунды)",
        xaxis_rangeslider_visible=False,
        autosize=True,
    )

    if not trader_id:
        return fig

    try:
        trader = Trader.objects.get(id=trader_id)
    except Trader.DoesNotExist:
        return fig

    orders = list(
        trader.orders.filter(
            order__timestamp__range=(start_date, end_date),
        )
        .select_related("order", "position")
        .order_by("order__timestamp")
    )

    if not orders:
        return fig

    records = []
    for trader_order in orders:
        order = trader_order.order
        position = trader_order.position
        is_close = (
            position.type == PositionType.LONG and order.side == OrderSide.SELL
        ) or (position.type == PositionType.SHORT and order.side == OrderSide.BUY)
        ref_time = position.closed_at if is_close else position.opened_at
        if ref_time is None:
            continue
        lag = (order.timestamp - ref_time).total_seconds()
        records.append(
            {
                "timestamp": order.timestamp,
                "lag_seconds": lag,
                "order_id": order.pk,
                "kind": "закрытие" if is_close else "открытие",
            }
        )

    if not records:
        return fig

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(timezone.localtime)
    df["hovertext"] = [
        f"Order ID: {row['order_id']}<br>"
        f"Тип: {row['kind']}<br>"
        f"Время: {dt_str(row['timestamp'])}<br>"
        f"Лаг: {format_pnl(row['lag_seconds'])} сек"
        for _, row in df.iterrows()
    ]

    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["lag_seconds"],
            mode="lines+markers",
            name="Лаг ордеров",
            marker={"color": "red", "size": 8},
            line={"color": "red", "width": 2},
            hovertext=df["hovertext"],
        )
    )

    return fig
