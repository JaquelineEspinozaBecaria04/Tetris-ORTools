# backend/plotly_layout.py
from __future__ import annotations
import plotly.graph_objects as go
from .df_layout import build_layout_dataframe


def render_layout_png_plotly(hosts, title: str = "", scale: int = 2, stats: dict | None = None) -> bytes:
    df = build_layout_dataframe(hosts)

    ordered_hosts = (
        df[["AZ", "Host", "host_chip"]]
        .drop_duplicates()
        .sort_values(by=["AZ", "Host"])["host_chip"]
        .tolist()[::-1]
    )

    fig = go.Figure()

    for _, row in df.iterrows():
        txt = (row["VM"] if row["VM"] != "INFRA" else None)
        hover = (
            f"<b>{row['VM']}</b><br>Longitud: {int(row['Length'])}"
            f"<br>Anti-Afinidad: {row.get('Anti-Afinidad','')}"
            f"<br>Pieza: {row.get('Numero','')}<extra></extra>"
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
            showlegend=False,
        ))

    fig.update_layout(
        barmode="stack",
        title=title or "TETRIS (estilo IDATI)",
        xaxis=dict(title="", tickmode="linear", dtick=1, showgrid=True),
        yaxis=dict(title="Host", categoryorder="array", categoryarray=ordered_hosts),
        height=max(400, 34 * len(ordered_hosts) + 140),
        showlegend=False,
        margin=dict(l=10, r=10, t=50, b=30),
    )

    # Exportar PNG via kaleido
    return fig.to_image(format="png", engine="kaleido", scale=scale)


def render_layout_html_plotly(
    hosts,
    title: str = "TETRIS (estilo IDATI)",
    include_plotlyjs: str = "cdn",
    full_html: bool = False,
) -> str:
    df = build_layout_dataframe(hosts)

    ordered_hosts = (
        df[["AZ", "Host", "host_chip"]]
        .drop_duplicates()
        .sort_values(by=["AZ", "Host"])["host_chip"]
        .tolist()[::-1]
    )

    fig = go.Figure()
    for _, r in df.sort_values(["AZ", "Host", "Chip", "Start", "VM"]).iterrows():
        host_chip = r["host_chip"]
        length = int(r["Length"])
        start = int(r["Start"])
        vm = str(r["VM"])
        color = str(r.get("Color", "#999999"))
        numero = str(r.get("Numero", ""))
        anti = str(r.get("Anti-Afinidad", ""))

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
            text = vm,
        ))

    fig.update_layout(
        barmode="stack",
        title=title,
        xaxis=dict(title="", tickmode="linear", dtick=1, showgrid=True, range=[0,40]),
        yaxis=dict(title="Host", categoryorder="array", categoryarray=ordered_hosts),
        height=max(420, 34 * len(ordered_hosts) + 160),
        showlegend=False,
        margin=dict(l=10, r=10, t=50, b=30),
    )
    fig.update_traces(
    textposition='inside',
    insidetextanchor='middle',
    textfont=dict(color='black', size=10),
    marker = dict(line = dict(width = 1.5, color = 'black')))

    # HTML responsive, sin márgenes de body y sin scroll interno
    html = fig.to_html(
        full_html=True,                 # página completa dentro del iframe
        include_plotlyjs="cdn",
        config={"responsive": True},    # ancho 100% del iframe
    )

    # Quitar márgenes y ocultar scroll del documento interno
    html = html.replace(
        "</head>",
        "<style>html,body{margin:0;padding:0;overflow:hidden}</style></head>"
    )
    return html

    return fig.to_html(full_html=full_html, include_plotlyjs=include_plotlyjs)
