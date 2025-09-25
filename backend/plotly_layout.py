# backend/plotly_layout.py
from __future__ import annotations
import plotly.graph_objects as go
from .df_layout import build_layout_dataframe  # << NUEVO

def render_layout_png_plotly(hosts, title: str = "", scale: int = 2, stats: dict | None = None) -> bytes:
    df = build_layout_dataframe(hosts)  # << construir DF “IDATI-like”

    # Orden de hosts para el eje Y (de menor a mayor y luego invertimos como en tu notebook)
    ordered_hosts = (
        df[["AZ","Host","host_chip"]]
        .drop_duplicates()
        .sort_values(by=["AZ","Host"])["host_chip"]
        .tolist()[::-1]  # invertir
    )

    fig = go.Figure()

    # Barras apiladas horizontales por fila de DF (exactamente como tu IDATI)
    for _, row in df.iterrows():
        showlegend = False  # evitamos leyenda larga
        txt = (row["VM"] if row["VM"] != "INFRA" else None)
        hover = (
            f"<b>{row['VM']}</b><br>Longitud: {int(row['Length'])}"
            f"<br>Anti-Afinidad: {int(row['Anti-Afinidad'])}<br>Pieza: {row['Numero']}<extra></extra>"
            if row["VM"] != "INFRA" else "<extra></extra>"
        )
        fig.add_trace(go.Bar(
            x=[row["Length"]],
            y=[row["host_chip"]],
            base=row["Start"],
            name=row["VM"],
            orientation="h",
            marker=dict(color=row["Color"], line=dict(width=1.5, color="black")),
            text=txt,
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color="black", size=10),
            hovertemplate=hover,
            showlegend=showlegend
        ))

    fig.update_layout(
        barmode="stack",
        title=title or "TETRIS (estilo IDATI)",
        xaxis=dict(title="", tickmode="linear", dtick=1, range=[0, 40], showgrid=True),
        yaxis=dict(title="Host", categoryorder="array", categoryarray=ordered_hosts),
        height=max(400, 34 * len(ordered_hosts) + 140),
        showlegend=False
    )

    # Exportar PNG via kaleido
    png = fig.to_image(format="png", engine="kaleido", scale=scale)
    return png

def render_layout_html_plotly(
    hosts,
    title: str = "TETRIS (estilo IDATI)",
    include_plotlyjs: str = "cdn",
    full_html: bool = False,
) -> str:
    import pandas as pd
    from .df_layout import build_layout_dataframe
    import plotly.graph_objects as go

    df = build_layout_dataframe(hosts)

    ordered_hosts = (
        df[["AZ","Host","host_chip"]]
        .drop_duplicates()
        .sort_values(by=["AZ","Host"])["host_chip"]
        .tolist()[::-1]
    )

    fig = go.Figure()
    for _, r in df.sort_values(["AZ","Host","Chip","Start","VM"]).iterrows():
        host_chip = r["host_chip"]
        length = int(r["Length"])
        start  = int(r["Start"])
        vm     = str(r["VM"])
        color  = str(r.get("Color", "#999999"))
        numero = str(r.get("Numero",""))
        anti   = str(r.get("Anti-Afinidad",""))

        hovertemplate = (
            "<b>%{customdata[0]}</b><br>"
            "Longitud: %{customdata[1]}<br>"
            "Anti-Afinidad: %{customdata[2]}<br>"
            "Pieza: %{customdata[3]}<extra></extra>"
        ) if vm != "INFRA" else "<extra></extra>"

        fig.add_trace(go.Bar(
            x=[length], y=[host_chip],
            base=[start], orientation="h",
            marker=dict(color=color),
            hovertemplate=hovertemplate,
            customdata=[[vm, length, anti, numero]],
            showlegend=False,
            name=vm if vm != "INFRA" else "",
        ))

    fig.update_layout(
        barmode="stack",
        title=title,
        xaxis=dict(title="", tickmode="linear", dtick=1, showgrid=True),
        yaxis=dict(title="Host", categoryorder="array", categoryarray=ordered_hosts),
        height=max(420, 34 * len(ordered_hosts) + 160),
        showlegend=False,
        margin=dict(l=10, r=10, t=50, b=30),
    )

    return fig.to_html(full_html=full_html, include_plotlyjs=include_plotlyjs)
