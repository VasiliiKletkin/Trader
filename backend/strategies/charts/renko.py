import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django_plotly_dash import DjangoDash
from traders.models import Trader

app = DjangoDash("RenkoStrategy")

app.layout = html.Div(
    [
        dcc.Graph(id="brick-chart"),
        dcc.Store(id="trader-id", data=None),
        dcc.Interval(
            id="interval-component-strategy",
            interval=60 * 1000,
            n_intervals=0,
        ),
    ]
)


@app.callback(
    Output("brick-chart", "figure"),
    Input("interval-component-strategy", "n_intervals"),
    State("trader-id", "data"),
)
def update_graph(n_intervals, trader_id):
    if not trader_id:
        return go.Figure()

    trader = Trader.objects.get(pk=trader_id)
    state = trader.strategy_data or {}
    bricks = state.get("bricks", [])

    if not bricks:
        return go.Figure()

    df = pd.DataFrame(bricks)
    df["index"] = range(len(df))
    df["color"] = df["type"].map(
        lambda t: "green" if t == "up" else ("red" if t == "down" else "gray")
    )
    df["height"] = abs(df["close"] - df["open"])
    df["bar_base"] = df[["open", "close"]].min(axis=1)

    fig = go.Figure(
        data=[
            go.Bar(
                x=df["index"],
                y=df["height"],
                base=df["bar_base"],
                marker_color=df["color"],
            )
        ]
    )

    fig.update_layout(
        title="Renko Bricks Chart",
        xaxis_title="Brick Index",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
    )

    return fig
