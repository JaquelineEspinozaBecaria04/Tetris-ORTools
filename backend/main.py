# backend/main.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import io, base64

from .io_utils import load_catalog_from_csv
from .solver_cpsat import CpsatPacker, SolverParams
from .plot_layout import render_layout_png

app = FastAPI(title="VM Packing CP-SAT")

def _to_bool(x) -> bool:
    return str(x).strip().lower() in {"1","true","t","yes","y","on"}

@app.post("/api/run-cpsat")
async def run_cpsat(
    file: UploadFile = File(...),
    enforceAZ: str = Form("true"),
    timeLimit: float = Form(20.0),
    delimiter: str | None = Form(None)
):
    # 1) Leer CSV
    try:
        raw = await file.read()
        vms = load_catalog_from_csv(io.BytesIO(raw), delimiter=delimiter or None)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Error al leer CSV: {str(e)}"})

    if not vms:
        return JSONResponse(status_code=422, content={"error": "El CSV no contiene VMs (Requerimiento=0 en todas las filas?)"})

    # 2) Resolver con CP-SAT
    params = SolverParams(enforce_az_per_host=_to_bool(enforceAZ), time_limit_s=float(timeLimit))
    packer = CpsatPacker(vms, params)
    hosts, stats = packer.solve()
    # stats siempre tendrá claves útiles; añadimos extra
    stats["n_vms"] = len(vms)
    stats["az_values"] = sorted({vm.az for vm in vms})

    # 3) Si no hay hosts, reporta claramente que no hubo solución
    if not hosts:
        return JSONResponse(status_code=422, content={"error": f"No se encontró solución ({stats.get('status','UNKNOWN')}). Revisa restricciones (anti-afinidad/AZ) o aumenta time limit.", "stats": stats})

    # 4) Render PNG con matplotlib
    png_bytes = render_layout_png(hosts)
    img_b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    return {"image": img_b64, "stats": stats}

# --- FRONTEND estático ---
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
def root():
    return FileResponse("frontend/index.html")
