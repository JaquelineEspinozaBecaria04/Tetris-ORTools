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
