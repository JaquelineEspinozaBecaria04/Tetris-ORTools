# backend/io_utils.py

import pandas as pd
import re
import io
from typing import List, Optional

# <<< CAMBIO: Se importa UploadFile para recibir el objeto del archivo desde FastAPI
from fastapi import UploadFile
from .models import VM, VMType

# La función _guess_sep no cambia
def _guess_sep(text: str) -> str:
    """Elige separador entre [;, , \t, |] por consistencia de conteos por línea."""
    candidates = [',',';','\t','|']
    lines = [ln for ln in text.splitlines() if ln.strip()]
    lines = lines[:20] if len(lines) > 20 else lines
    best = (0.0, 0.0, ',')  # (mean, -std, sep)
    import math
    for sep in candidates:
        counts = [ln.count(sep) for ln in lines]
        if max(counts) == 0:
            continue
        mean = sum(counts)/len(counts)
        var = sum((c-mean)**2 for c in counts)/len(counts)
        std = math.sqrt(var)
        score = (mean, -std)  # más alto mean, menor std
        if score > best[:2]:
            best = (score[0], score[1], sep)
    return best[2]

# La función _decode_bytes no cambia
def _decode_bytes(raw: bytes) -> str:
    for enc in ["utf-8-sig","utf-8","cp1252","latin1"]:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    # último recurso: latin1 “a la fuerza”
    return raw.decode("latin1", errors="ignore")

# La función _read_csv_robusto no cambia, pero ahora no recibirá delimitador
def _read_csv_robusto(file_like, delimiter: Optional[str] = None) -> pd.DataFrame:
    """
    Lee CSV desde file-like o ruta.
    - Si 'delimiter' viene, lo usa tal cual.
    - Si no, intenta autodetectar: decodifica bytes y escoge sep por conteo.
    """
    pos = None
    try:
        pos = file_like.tell()
    except Exception:
        pass
    raw = file_like.read()
    try:
        if pos is not None:
            file_like.seek(pos)
        else:
            file_like.seek(0)
    except Exception:
        pass

    text = _decode_bytes(raw)
    sep = delimiter if delimiter else _guess_sep(text)
    header = text.splitlines()[0] if text else ""
    if delimiter is None and ',' in header and ';' in header:
        sep = ';' if header.count(';') >= header.count(',') else ','

    df = pd.read_csv(io.StringIO(text), sep=sep, engine="python")
    return df

# Las funciones de limpieza no cambian
def _clean_col(s: str) -> str:
    s = str(s)
    s = s.replace("\ufeff","")
    s = s.replace("\u00A0"," ").replace("\u2007"," ").replace("\u202F"," ")
    s = s.replace("–","-").replace("—","-")
    s = re.sub(r"\s+"," ", s).strip()
    return s

def normalize_hex_color(c: str) -> str:
    c = str(c).strip()
    if not c.startswith("#"):
        c = "#" + c
    if not re.fullmatch(r"#([0-9A-Fa-f]{6})", c):
        return "#777777"
    return c

# <<< CAMBIO PRINCIPAL: Nueva función que reemplaza a load_catalog_from_csv >>>
def load_vms_from_file(file: UploadFile) -> List[VM]:
    """
    Lee un archivo subido (.csv o .xlsx) y lo convierte en una lista de VMs.
    """
    filename = file.filename.lower()
    
    # 1. Cargar el contenido en un DataFrame de Pandas
    try:
        if filename.endswith('.xlsx'):
            # Usa pd.read_excel para archivos Excel
            df = pd.read_excel(file.file)
        elif filename.endswith('.csv'):
            # Usa la lógica robusta para leer CSV
            raw_bytes = file.file.read()
            df = _read_csv_robusto(io.BytesIO(raw_bytes), delimiter=None)
        else:
            raise ValueError(f"Formato de archivo no soportado: '{filename}'. Use .csv o .xlsx.")
    except Exception as e:
        # Relanzar la excepción con un mensaje más amigable
        raise ValueError(f"No se pudo leer el archivo. Error: {e}")

    # 2. El resto del procesamiento es idéntico, ya que opera sobre el DataFrame
    df.columns = [_clean_col(c) for c in df.columns]
    
    rename = {
        "Instancia":"Inst","instancia":"Inst","inst":"Inst",
        "Vnf":"VNF","vnf":"VNF",
        "Vnfc":"VNFC","vnfc":"VNFC",
        "Tamaño":"Longitud","Tamano":"Longitud",
        "Anti-Afinidad":"Anti-afinidad","Anti_afinidad":"Anti-afinidad","AntiAfinidad":"Anti-afinidad",
        "req":"Requerimiento"
    }
    for k,v in rename.items():
        if k in df.columns and v not in df.columns:
            df.rename(columns={k:v}, inplace=True)

    required = ['Inst','VNF','VNFC','Color','Longitud','AZ','Anti-afinidad','Requerimiento']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas en el archivo: {', '.join(missing)}")

    vms: List[VM] = []
    idx = 0
    for _, r in df.iterrows():
        # Validaciones de datos
        try:
            req = int(r['Requerimiento'])
            if req == 0:
                continue # Saltar filas con 0 requerimientos
            
            inst = int(r['Inst'])
            vnf = str(r['VNF']); vnfc = str(r['VNFC'])
            size = int(r['Longitud'])
            az = str(r['AZ'])
            anti = int(r['Anti-afinidad'])
            color = normalize_hex_color(r['Color'])
        except (ValueError, TypeError) as e:
            raise ValueError(f"Dato inválido en la fila {idx+2}: {e}")

        if size <= 0 or size > 17:
            raise ValueError(f"VM {vnf}/{vnfc} con Longitud={size} inválida (debe estar entre 1 y 17).")
        if anti < 1:
            raise ValueError(f"Anti-afinidad debe ser >=1 en {vnf}/{vnfc}.")

        for _ in range(req):
            vms.append(VM(
                idx=idx,
                vm_type=VMType(vnf, vnfc),
                color=color,
                size=size,
                az=az,
                anti=anti,
                inst=inst
            ))
            idx += 1
    return vms