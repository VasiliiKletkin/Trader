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
        dcc.Store(id="trader-id", data=None),
        dcc.Store(id="equity-date-range", data=None),
    ]
)




# Первый callback: обновляет диапазон дат в Store при zoom/pan
@app.callback(
    Output("equity-date-range", "data"),
    [
        Input("trader-equity-curve-chart", "relayoutData"),
    ],
    [State("equity-date-range", "data")],
)
def update_date_range(relayout_data, stored_range):
    if relayout_data:
        x0 = relayout_data.get("xaxis.range[0]")
        x1 = relayout_data.get("xaxis.range[1]")
        if x0 and x1:
            return {"start": x0, "end": x1}
        # Если autoscale/reset — relayoutData содержит xaxis.autorange
        if relayout_data.get("xaxis.autorange") or relayout_data.get("xaxis.autorange", False):
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
    start_date = end_date - timedelta(days=30)

    # Если есть диапазон в Store — используем его
    if date_range and date_range.get("start") and date_range.get("end"):
        try:
            start_date = pd.to_datetime(date_range["start"])
            end_date = pd.to_datetime(date_range["end"])
        except Exception:
            pass

    fig = go.Figure()
    fig.update_layout(
        title="Кривая профита трейдера",
        xaxis_title="Время",
        yaxis_title="Профит",
        height=500,
        xaxis_rangeslider_visible=False,
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
        pnl = pos.pnl() or Decimal("0.0")
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
        )
    )

    return fig
