import pandas as pd
import re, io
from typing import List, Optional
from .models import VM, VMType

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

def _decode_bytes(raw: bytes) -> str:
    for enc in ["utf-8-sig","utf-8","cp1252","latin1"]:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    # último recurso: latin1 “a la fuerza”
    return raw.decode("latin1", errors="ignore")

def _read_csv_robusto(file_like, delimiter: Optional[str] = None) -> pd.DataFrame:
    """
    Lee CSV desde file-like o ruta.
    - Si 'delimiter' viene, lo usa tal cual.
    - Si no, intenta autodetectar: decodifica bytes y escoge sep por conteo.
    """
    # Obtener bytes
    if isinstance(file_like, (str, bytes)):
        raw = open(file_like, "rb").read() if isinstance(file_like, str) else file_like
    else:
        # UploadFile/BytesIO
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
    # Si autodetección duda entre ',' y ';' por decimales, preferir ';' si aparece en cabecera
    header = text.splitlines()[0] if text else ""
    if delimiter is None and ',' in header and ';' in header:
        # heurística: si hay más ';' que ',' en header, usa ';'
        sep = ';' if header.count(';') >= header.count(',') else ','

    # Leer dataframe
    df = pd.read_csv(io.StringIO(text), sep=sep, engine="python")
    return df

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

def load_catalog_from_csv(file_like, delimiter: Optional[str] = None) -> List[VM]:
    df = _read_csv_robusto(file_like, delimiter=delimiter)
    df.columns = [_clean_col(c) for c in df.columns]
    # alias
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
        raise ValueError(f"Faltan columnas: {missing}")

    vms: List[VM] = []
    idx = 0
    for _, r in df.iterrows():
        inst = int(r['Inst'])
        vnf = str(r['VNF']); vnfc = str(r['VNFC'])
        size = int(r['Longitud'])
        az = str(r['AZ'])
        anti = int(r['Anti-afinidad'])
        req = int(r['Requerimiento'])
        color = normalize_hex_color(r['Color'])
        if size <= 0 or size > 17:
            raise ValueError(f"VM {vnf}/{vnfc} con Longitud={size} inválida (1..17).")
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
