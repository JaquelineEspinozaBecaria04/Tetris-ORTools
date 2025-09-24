"""
FastAPI backend para empaquetado de VMs con OR-Tools (CP-SAT).
- Endpoints:
  POST /api/run-cpsat   -> procesa CSV, resuelve (CP-SAT 1 o 2 fases), devuelve PNG base64 y estadísticas
  GET  /                -> sirve index.html (frontend)
  /static/*             -> sirve assets estáticos (css/js)

Nota: "Enforce AZ por host" está SIEMPRE activado en el solver.
"""
import os, base64, time

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import io, base64

from .io_utils import load_catalog_from_csv
from .solver_cpsat import CpsatPacker, SolverParams
from .plot_layout import render_layout_png as render_mpl_png
try:
    # Si tu archivo es plotly_layout.py:
    from .plotly_layout import render_layout_png_plotly as render_plotly_png
    # Si lo dejaste como plotly.py, usa esta en cambio:
    # from .plotly import render_layout_png_plotly as render_plotly_png
except Exception:
    render_plotly_png = None
from .df_layout import build_layout_dataframe

app = FastAPI(title="VM Packing CP-SAT")

def _to_bool(x) -> bool:
    return str(x).strip().lower() in {"1","true","t","yes","y","on"}

@app.post("/api/run-cpsat")
async def run_cpsat(
    file: UploadFile = File(...),
    # Enforce AZ está fijo a True en el solver; mantenemos compatibilidad de parámetro por si en un futuro se expone.
    delimiter: str | None = Form(None),
    algo: str = Form("cpsat2"),     # "cpsat" (1 fase) o "cpsat2" (dos fases, recomendado)
    timeLimit: float = Form(120.0),   # mantenido interno; en la UI no se expone (se usa STOP para cancelar la petición)
    includeTable: bool = Form(False), ##
    imageEngine: str = Form("plotly"),   # "mpl" o "plotly"
):
    """Lee CSV, ejecuta solver y devuelve imagen y estadísticas."""
    # 1) Cargar CSV
    try:
        raw = await file.read()
        vms = load_catalog_from_csv(io.BytesIO(raw), delimiter=delimiter or None)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Error al leer CSV: {str(e)}"})

    if not vms:
        return JSONResponse(status_code=422, content={"error": "El CSV no contiene VMs (¿Requerimiento=0?)"})

    # 2) Resolver con CP-SAT
    # Enforce AZ SIEMPRE true
    params = SolverParams(enforce_az_per_host=True, time_limit_s=float(timeLimit))
    packer = CpsatPacker(vms, params)

    if algo == "cpsat2":
        hosts, stats = packer.solve_two_phase()   # 2 fases: minimiza hosts y luego compacta chips/slack
    else:
        hosts, stats = packer.solve()             # 1 fase: minimiza hosts y slack lineal

    # Añadir métricas auxiliares para la UI
    stats["n_vms"] = len(vms)
    stats["az_values"] = sorted({vm.az for vm in vms})

    if not hosts:
        return JSONResponse(
            status_code=422,
            content={
                "error": f"No se encontró solución ({stats.get('status','UNKNOWN')}). Revisa restricciones o vuelve a intentarlo.",
                "stats": stats
            }
        )
    
    table = None
    if includeTable:
        try:
            df = build_layout_dataframe(hosts)
            os.makedirs("frontend/Media", exist_ok=True)
            fname = f"tetris_{int(time.time())}.csv"
            out_path = os.path.join("frontend", "Media", fname)
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            table = {"url": f"/media/{fname}", "filename": fname}
        except Exception as e:
            table = {"error": f"No se pudo generar CSV: {e}"}

    # 3) Render PNG con selector
    engine = os.getenv("IMAGE_ENGINE", "").strip().lower() or str(imageEngine).strip().lower()
    if engine == "plotly" and render_plotly_png is not None:
        png_bytes = render_plotly_png(hosts, stats=stats)
    else:
        png_bytes = render_mpl_png(hosts, stats=stats)

    img_b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    resp = {"image": img_b64, "stats": stats}
    if table:
        resp["table"] = table  # incluye link al CSV si lo pediste
    return resp

# Estático (frontend)
app.mount("/static", StaticFiles(directory="frontend"), name="static")
app.mount("/media", StaticFiles(directory="frontend/Media"), name="media")  # << aquí

@app.get("/")
def root():
    return FileResponse("frontend/index.html")
