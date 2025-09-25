"""
FastAPI backend para empaquetado de VMs con OR-Tools (CP-SAT).
- Endpoints:
  POST /api/run-cpsat   -> procesa CSV, resuelve (CP-SAT 1 o 2 fases), devuelve HTML/PNG y estadísticas
  GET  /                -> sirve index.html (frontend)
  /static/*             -> sirve assets estáticos (css/js)
  /media/*              -> sirve archivos generados (html/png/csv)

Nota: "Enforce AZ por host" está SIEMPRE activado en el solver.
"""
import os, time, io, base64
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .io_utils import load_catalog_from_csv
from .solver_cpsat import CpsatPacker, SolverParams
from .plot_layout import render_layout_png as render_mpl_png
try:
    from .plotly_layout import (
        render_layout_png_plotly as render_plotly_png,
        render_layout_html_plotly as render_plotly_html,
    )
except Exception:
    render_plotly_png = None
    render_plotly_html = None

from .df_layout import build_layout_dataframe

# --- RUTAS DE MEDIA GLOBALES ---
BASE_DIR = Path(__file__).resolve().parent.parent     # .../Tetris-ORTools
MEDIA_DIR = BASE_DIR / "frontend" / "Media"
GENERATED_DIR = MEDIA_DIR / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VM Packing CP-SAT")


def _to_bool(x) -> bool:
    return str(x).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _normalize_output_format(fmt: str | None) -> str:
    """
    Normaliza el valor del select del frontend a: 'html' | 'png' | 'both'.
    Acepta etiquetas en español como 'HTML interactivo (Plotly)' o 'Ambos'.
    """
    if not fmt:
        return "html"
    s = str(fmt).strip().lower()
    if s in {"html", "png", "both"}:
        return s
    if s.startswith("html"):
        return "html"
    if s.startswith("amb"):   # 'ambos'
        return "both"
    if "png" in s:
        return "png"
    return "html"


@app.post("/api/run-cpsat")
async def run_cpsat(
    file: UploadFile = File(...),
    delimiter: str | None = Form(None),
    algo: str = Form("cpsat2"),            # "cpsat" (1 fase) o "cpsat2" (dos fases)
    timeLimit: float = Form(120.0),
    includeTable: bool = Form(False),
    imageEngine: str = Form("plotly"),     # "mpl" o "plotly"
    outputFormat: str = Form("html"),      # "html" | "png" | "both"
):
    """Lee CSV, ejecuta solver y devuelve imagen/HTML y estadísticas."""
    # 1) Cargar CSV
    try:
        raw = await file.read()
        vms = load_catalog_from_csv(io.BytesIO(raw), delimiter=delimiter or None)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Error al leer CSV: {str(e)}"})

    if not vms:
        return JSONResponse(status_code=422, content={"error": "El CSV no contiene VMs (¿Requerimiento=0?)"})

    # 2) Resolver con CP-SAT (Enforce AZ SIEMPRE true)
    params = SolverParams(enforce_az_per_host=True, time_limit_s=float(timeLimit))
    packer = CpsatPacker(vms, params)

    if algo == "cpsat2":
        hosts, stats = packer.solve_two_phase()
    else:
        hosts, stats = packer.solve()

    # Métricas auxiliares para la UI
    stats["n_vms"] = len(vms)
    stats["az_values"] = sorted({vm.az for vm in vms})

    if not hosts:
        return JSONResponse(
            status_code=422,
            content={"error": f"No se encontró solución ({stats.get('status','UNKNOWN')}).", "stats": stats},
        )

    # 2.5) CSV (opcional)
    table = None
    if includeTable:
        try:
            df = build_layout_dataframe(hosts)
            fname = f"tetris_{int(time.time())}.csv"
            out_path = GENERATED_DIR / fname
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            table = {"url": f"/media/generated/{fname}", "filename": fname}
        except Exception as e:
            table = {"error": f"No se pudo generar CSV: {e}"}

    # 3) Respuesta según formato solicitado
    fmt = _normalize_output_format(outputFormat)
    resp = {"stats": stats}
    ts = int(time.time())

    # HTML interactivo (Plotly)
    if fmt in ("html", "both"):
        if render_plotly_html is None:
            return JSONResponse(
                status_code=500,
                content={"error": "Render HTML no disponible (plotly_html no importado)."},
            )
        html = render_plotly_html(
            hosts,
            title="TETRIS (estilo IDATI)",
            include_plotlyjs="cdn",
            full_html=False,
        )
        html_name = f"layout_{ts}.html"
        (GENERATED_DIR / html_name).write_text(html, encoding="utf-8")
        resp["html_url"] = f"/media/generated/{html_name}"

    # PNG (compatibilidad)
    if fmt in ("png", "both"):
        engine = (os.getenv("IMAGE_ENGINE", "") or str(imageEngine)).strip().lower()
        if engine == "plotly" and render_plotly_png is not None:
            png_bytes = render_plotly_png(hosts, stats=stats)
        else:
            png_bytes = render_mpl_png(hosts, stats=stats)
        resp["image"] = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    if table:
        resp["table"] = table

    return resp


# Estático (frontend)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend")), name="static")
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.get("/")
def root():
    return FileResponse(str(BASE_DIR / "frontend" / "index.html"))
