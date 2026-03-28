from decimal import Decimal

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, dcc, html
from django.utils import timezone
from django.utils.timezone import localtime
from django_plotly_dash import DjangoDash
from plotly.subplots import make_subplots

from arbitrage_traders.models import ArbitrageTrader
from core.utils.charts import (
    create_date_picker_range,
    parse_date_range,
    register_date_preset_callbacks,
)
from core.utils.common import dt_str

app = DjangoDash("ArbitrageCandleChart")

app.layout = html.Div(
    [
        create_date_picker_range(),
        dcc.Store(id="trader-id", data=None),
        dcc.Graph(id="arbitrage-candle-chart"),
        dcc.Graph(id="arbitrage-equity-curve-chart"),
        dcc.Graph(id="arbitrage-lag-chart"),
    ]
)

register_date_preset_callbacks(app)


def _create_empty_figure():
    """Пустой figure с тремя subplot'ами и secondary Y для объёмов."""
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.35, 0.35, 0.30],
        subplot_titles=("Первая биржа", "Вторая биржа", "Соотношение цен"),
        specs=[
            [{"secondary_y": True}],
            [{"secondary_y": True}],
            [{"secondary_y": False}],
        ],
    )
    fig.update_layout(
        title="Арбитражный свечной график",
        height=1300,
        xaxis_rangeslider_visible=False,
        xaxis2_rangeslider_visible=False,
        xaxis3_rangeslider_visible=False,
        legend={"x": 0, "y": 1},
    )
    return fig


def _add_candlestick(fig, candles_qs, row):
    """Добавить свечной график и объёмы на subplot. Возвращает DataFrame."""
    df = pd.DataFrame(
        list(candles_qs.values("timestamp", "open", "high", "low", "close", "volume"))
    )
    if df.empty:
        return df

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
        row=row,
        col=1,
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
        row=row,
        col=1,
        secondary_y=True,
    )
    fig.update_yaxes(
        showgrid=False,
        range=[0, df["volume"].max() * 4],
        row=row,
        col=1,
        secondary_y=True,
    )
    return df


def _add_ratio_chart(fig, left_df, right_df, row):
    """Добавить график соотношения цен (left / right) на subplot."""
    merged = pd.merge(
        left_df[["timestamp", "close"]],
        right_df[["timestamp", "close"]],
        on="timestamp",
        suffixes=("_left", "_right"),
    )
    if merged.empty:
        return

    merged["ratio"] = merged["close_left"] / merged["close_right"]
    fig.add_trace(
        go.Scatter(
            x=merged["timestamp"],
            y=merged["ratio"],
            mode="lines",
            name="Left / Right",
            line={"color": "#636EFA", "width": 1.5},
            showlegend=False,
        ),
        row=row,
        col=1,
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray", row=row, col=1)


def _add_ratio_markers(
    fig, items, time_field, left_price, right_price, name, marker, hover_fn, row
):
    """Добавить маркеры на график соотношения (ratio = left / right)."""
    valid = [p for p in items if getattr(p, left_price) and getattr(p, right_price)]
    if not valid:
        return
    fig.add_trace(
        go.Scatter(
            x=[localtime(getattr(p, time_field)) for p in valid],
            y=[float(getattr(p, left_price) / getattr(p, right_price)) for p in valid],
            mode="markers",
            name=name,
            marker=marker,
            hovertext=[hover_fn(p) for p in valid],
            legendgroup=name.lower(),
            showlegend=False,
        ),
        row=row,
        col=1,
    )


def _add_order_markers(fig, orders):
    """Добавить маркеры ордеров на свечные subplot'ы (row 1 — left, row 2 — right)."""
    if not orders:
        return

    for side, color in [("buy", "green"), ("sell", "red")]:
        side_orders = [o for o in orders if o.left_order.side == side]
        if not side_orders:
            continue
        name = f"Order {side.upper()}"
        marker = {"color": color, "symbol": "diamond", "size": 10}
        for row, order_attr in [(1, "left_order"), (2, "right_order")]:
            fig.add_trace(
                go.Scatter(
                    x=[
                        localtime(getattr(o, order_attr).timestamp) for o in side_orders
                    ],
                    y=[float(getattr(o, order_attr).price) for o in side_orders],
                    mode="markers",
                    name=name,
                    marker=marker,
                    hovertext=[
                        f"#{getattr(o, order_attr).exchange_order_id} "
                        f"{getattr(o, order_attr).get_side_display()} "
                        f"{float(getattr(o, order_attr).amount):.4f} "
                        f"@ {float(getattr(o, order_attr).price):.2f} "
                        f"fee: {float(getattr(o, order_attr).fee):.4f}"
                        for o in side_orders
                    ],
                    legendgroup=name.lower(),
                    showlegend=(row == 1),
                ),
                row=row,
                col=1,
            )


def _add_position_markers(fig, positions):
    """Добавить маркеры открытия и закрытия позиций на график соотношения."""
    positions_list = list(positions)
    opened = [p for p in positions_list if p.opened_at]
    closed = [p for p in positions_list if p.closed_at]

    if opened:
        _add_ratio_markers(
            fig,
            opened,
            "opened_at",
            "left_open_price",
            "right_open_price",
            name="Open",
            marker={"color": "blue", "symbol": "circle", "size": 16},
            hover_fn=lambda p: f"id{p.pk} OPEN",
            row=3,
        )

    if closed:
        _add_ratio_markers(
            fig,
            closed,
            "closed_at",
            "left_close_price",
            "right_close_price",
            name="Close",
            marker={"color": "orange", "symbol": "x", "size": 16},
            hover_fn=lambda p: (
                f"id{p.pk} CLOSE|{p.get_close_reason_display()}|PNL: {round(p.pnl, 2)}"
            ),
            row=3,
        )


@app.callback(
    Output("arbitrage-candle-chart", "figure"),
    [
        Input("trader-id", "data"),
        Input("date-range-picker", "start_date"),
        Input("date-range-picker", "end_date"),
    ],
)
def update_chart(trader_id, start_date_str, end_date_str):
    start_date, end_date = parse_date_range(start_date_str, end_date_str)
    fig = _create_empty_figure()

    if not trader_id:
        return fig

    trader = ArbitrageTrader.objects.select_related(
        "left_candle_source__exchange_client__exchange",
        "left_candle_source__trading_pair",
        "right_candle_source__exchange_client__exchange",
        "right_candle_source__trading_pair",
        "left_exchange_client",
        "right_exchange_client",
    ).get(id=trader_id)

    fig.layout.annotations[0].text = str(trader.left_exchange_client)
    fig.layout.annotations[1].text = str(trader.right_exchange_client)

    left_df = _add_candlestick(
        fig,
        trader.left_candle_source.get_candles(start=start_date, end=end_date),
        row=1,
    )
    right_df = _add_candlestick(
        fig,
        trader.right_candle_source.get_candles(start=start_date, end=end_date),
        row=2,
    )

    if (
        left_df is not None
        and right_df is not None
        and not left_df.empty
        and not right_df.empty
    ):
        _add_ratio_chart(fig, left_df, right_df, row=3)

    positions = trader.positions.filter(
        opened_at__range=(start_date, end_date),
    ).order_by("opened_at")
    _add_position_markers(fig, positions)

    orders = list(
        trader.orders.filter(
            left_order__timestamp__range=(start_date, end_date),
        ).select_related("left_order", "right_order")
    )
    _add_order_markers(fig, orders)

    fig.update_yaxes(title_text="Цена", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Объём", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Цена", row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Объём", row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Соотношение", row=3, col=1)
    fig.update_xaxes(title_text="Время", row=3, col=1)

    return fig


@app.callback(
    Output("arbitrage-equity-curve-chart", "figure"),
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
        trader = ArbitrageTrader.objects.get(id=trader_id)
    except ArbitrageTrader.DoesNotExist:
        return fig

    positions = list(
        trader.closed_positions.filter(
            closed_at__range=(start_date, end_date),
        )
        .annotate(computed_pnl=ArbitrageTrader.theoretical_pnl_annotation())
        .order_by("closed_at")
        .values("closed_at", "computed_pnl")
    )

    if not positions:
        return fig

    cumulative_pnl = Decimal("0")
    records = []
    for pos in positions:
        pnl = pos["computed_pnl"] or Decimal("0")
        cumulative_pnl += pnl
        records.append(
            {
                "timestamp": pos["closed_at"],
                "pnl": float(pnl),
                "cumulative_pnl": float(cumulative_pnl),
            }
        )

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(timezone.localtime)

    df["hovertext"] = [
        f"Дата: {dt_str(row['timestamp'])}<br>"
        f"PnL: {row['pnl']:.2f}<br>"
        f"Кумулятивный: {row['cumulative_pnl']:.2f}"
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
            text=f"R² = {r2:.4f}",
            showarrow=False,
            bgcolor="rgba(255,255,255,0.8)",
        )

    return fig


@app.callback(
    Output("arbitrage-lag-chart", "figure"),
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
        legend={"x": 0, "y": 1},
    )

    if not trader_id:
        return fig

    try:
        trader = ArbitrageTrader.objects.get(id=trader_id)
    except ArbitrageTrader.DoesNotExist:
        return fig

    orders = (
        trader.orders.filter(
            left_order__timestamp__range=(start_date, end_date),
        )
        .select_related("left_order", "right_order")
        .order_by("left_order__timestamp")
    )

    if not orders.exists():
        return fig

    left_records = []
    right_records = []
    for order in orders:
        for rec_list, o in [
            (left_records, order.left_order),
            (right_records, order.right_order),
        ]:
            minute_start = o.timestamp.replace(second=0, microsecond=0)
            lag = (o.timestamp - minute_start).total_seconds()
            rec_list.append(
                {
                    "timestamp": o.timestamp,
                    "lag_seconds": lag,
                    "order_id": o.pk,
                }
            )

    for records, name, color in [
        (left_records, "Left", "red"),
        (right_records, "Right", "blue"),
    ]:
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"]).apply(timezone.localtime)
        df["hovertext"] = [
            f"Order ID: {row['order_id']}<br>"
            f"Время: {dt_str(row['timestamp'])}<br>"
            f"Лаг: {row['lag_seconds']:.2f} сек"
            for _, row in df.iterrows()
        ]
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["lag_seconds"],
                mode="lines+markers",
                name=f"Лаг {name}",
                marker={"color": color, "size": 8},
                line={"color": color, "width": 2},
                hovertext=df["hovertext"],
            )
        )

    return fig
