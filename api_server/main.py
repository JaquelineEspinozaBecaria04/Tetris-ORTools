import os, time, io, base64
from pathlib import Path

import cProfile
import pstats

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from .io_utils import load_vms_from_file
from .solver_cpsat import CpsatPacker, SolverParams
from .solver_sa import SaPacker
from .solver_idati import IdatiPacker
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

BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_DIR / "frontend" / "Media"
GENERATED_DIR = MEDIA_DIR / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VM Packing Solvers")


def _to_bool(x) -> bool:
    return str(x).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def _normalize_output_format(fmt: str | None) -> str:
    if not fmt: return "html"
    s = str(fmt).strip().lower()
    if s in {"html", "png", "both"}: return s
    if s.startswith("html"): return "html"
    if s.startswith("amb"): return "both"
    if "png" in s: return "png"
    return "html"


@app.post("/api/run-cpsat")
async def run_cpsat(
    file: UploadFile = File(...),
    algo: str = Form("cpsat2"),
    timeLimit: float = Form(120.0),
    includeTable: bool = Form(False),
    imageEngine: str = Form("plotly"),
    outputFormat: str = Form("html"),
):
    try:
        vms = load_vms_from_file(file)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Error al procesar el archivo: {str(e)}"})

    if not vms:
        return JSONResponse(status_code=422, content={"error": "El archivo no contiene VMs con Requerimiento > 0"})

    params = SolverParams(enforce_az_per_host=True, time_limit_s=float(timeLimit))

    # --- Medición de Tiempo de Ejecución ---
    start_time = time.monotonic() # Inicia el cronómetro
    profiler = cProfile.Profile()
    profiler.enable()
    if algo == "idati":
        packer = IdatiPacker(vms, params)
        hosts, stats = packer.solve()
    elif algo == "sa":
        packer = SaPacker(vms, params)
        hosts, stats = packer.solve()
    else:  
        packer = CpsatPacker(vms, params)
        if algo == "cpsat2":
            hosts, stats= packer.solve_two_phase()
        else:
            hosts, stats = packer.solve()
    profiler.disable()
    end_time = time.monotonic() # Detiene el cronómetro
    # --- Fin de la Medición -

    # Imprime los resultados en la consola de VSC
    stats_profiler = pstats.Stats(profiler).sort_stats('cumtime')
    stats_profiler.print_stats(20) # Muestra las 20 funciones más lentas

    # mostrar tiempo de ejecución en consola
    elapsed_time = end_time - start_time
    print(f"Tiempo de ejecución del solver ({algo}): {elapsed_time:.2f} segundos")

    stats["n_vms"] = len(vms)
    stats["az_values"] = sorted({vm.az for vm in vms})

    if not hosts:
        return JSONResponse(
            status_code=422,
            content={"error": f"No se encontró solución ({stats.get('status','UNKNOWN')}).", "stats": stats},
        )

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

    fmt = _normalize_output_format(outputFormat)
    resp = {"stats": stats}
    ts = int(time.time())

    if fmt in ("html", "both"):
        if render_plotly_html is None:
            return JSONResponse(status_code=500, content={"error": "Render HTML no disponible (plotly_html no importado)."},)
        html = render_plotly_html(
            hosts,
            title="TETRIS (Resultado del Solver)",
            # include_plotlyjs="cdn",
            # full_html=False,
        )
        html_name = f"layout_{ts}.html"
        (GENERATED_DIR / html_name).write_text(html, encoding="utf-8")
        resp["html_url"] = f"/media/generated/{html_name}"

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


# --- Montaje de directorios estáticos ---
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "frontend")), name="static")
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.get("/")
def root():
    return FileResponse(str(BASE_DIR / "frontend" / "index.html"))