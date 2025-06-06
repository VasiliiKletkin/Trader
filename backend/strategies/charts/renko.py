import pandas as pd
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from django_plotly_dash import DjangoDash
from traders.models import Trader

app = DjangoDash("TraderBricks")

app.layout = html.Div(
    [
        dcc.Store(id="bricks-data"),
        dcc.Graph(id="brick-chart"),
    ]
)


@app.callback(
    Output("brick-chart", "figure"),
    Output("bricks-data", "data"),
    Input("brick-chart", "relayoutData"),
    State("bricks-data", "data"),
)
def update_graph(relayout_data, stored_data):
    # Загружаем трейдера
    trader = Trader.objects.get(pk=1)
    state = trader.strategy_state or {}
    bricks = state.get("bricks", [])

    # Если уже есть данные, используем их (например, после zoom)
    if stored_data:
        df = pd.read_json(stored_data)
    else:
        # Преобразуем bricks в DataFrame
        df = pd.DataFrame(bricks)
        if df.empty:
            # Чтобы избежать ошибок, если bricks пуст
            df = pd.DataFrame(columns=["price", "direction"])
        else:
            df["index"] = range(len(df))
            df["color"] = df["direction"].map(lambda d: "green" if d == "up" else "red")

    fig = go.Figure(
        data=[
            go.Bar(
                x=df["index"],
                y=df["price"],
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

    return fig, df.to_json()
