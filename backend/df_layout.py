# backend/df_layout.py
from __future__ import annotations
import pandas as pd
from typing import List, Dict, Tuple

# mismas constantes que models.py
CHIPS_PER_HOST = 2
CHIP_TOTAL = 20
CHIP_CAPACITY = 17
HOST_CAPACITY = CHIP_CAPACITY * CHIPS_PER_HOST

def build_layout_dataframe(hosts) -> pd.DataFrame:
    """
    Toma la solución del solver (hosts -> chips -> placements) y devuelve un DataFrame
    equivalente al que usas en IDATI, con estas columnas:
    ['AZ','Host','Chip','VM','Start','Length','Color','Inst.','Anti-Afinidad','HOST']
      - Host: índice local dentro de su AZ (1..)
      - HOST: índice global acumulado (1..)
      - Chip: 'Chip 1' o 'Chip 2'
      - VM:  'VNF VNFC' (o 'INFRA' para la franja [17..20) dibujada como referencia)
    """
    # Ordenar por AZ y luego id (paridad con render actual)
    hosts_sorted = sorted(hosts, key=lambda H: (H.az, H.id))

    rows = []
    # contador global (HOST) y local por AZ (Host)
    global_counter = 0
    current_az = None
    local_counter = 0

    for H in hosts_sorted:
        if H.az != current_az:
            current_az = H.az
            local_counter = 0
        local_counter += 1
        global_counter += 1

        # Por cada chip
        for c_idx, ch in enumerate(H.chips, start=1):  # 1..2
            chip_label = f"Chip {c_idx}"

            # Piezas reales
            for plc in sorted(ch.items, key=lambda p: p.start):
                vm = plc.vm
                rows.append({
                    "AZ": H.az,
                    "Host": local_counter,            # local dentro de AZ
                    "Chip": chip_label,               # 'Chip 1' / 'Chip 2'
                    "VM": f"{vm.vm_type.vnf} {vm.vm_type.vnfc}",
                    "Start": plc.start + (0 if c_idx == 1 else 20),  # para eje 0..40 estilo IDATI
                    "Length": vm.size,
                    "Color": vm.color,
                    "Inst.": vm.inst,
                    "Anti-Afinidad": vm.anti,
                    "HOST": global_counter            # global acumulado
                })

            # Franja reservada [17..20) como fila 'INFRA' (opcional, útil para reproducir tu look)
            rows.append({
                "AZ": H.az,
                "Host": local_counter,
                "Chip": chip_label,
                "VM": "INFRA",
                "Start": (17 if c_idx == 1 else 37),
                "Length": (CHIP_TOTAL - CHIP_CAPACITY),  # 3
                "Color": "#000000",
                "Inst.": 0,
                "Anti-Afinidad": 1,
                "HOST": global_counter
            })

    df = pd.DataFrame(rows, columns=[
        "AZ","Host","Chip","VM","Start","Length","Color","Inst.","Anti-Afinidad","HOST"
    ])

    # Orden recomendado (igual a tu notebook): por AZ, Host, Chip, Start
    chip_order = {"Chip 1": 0, "Chip 2": 1}
    df["_chip_order"] = df["Chip"].map(chip_order).fillna(0)
    df = df.sort_values(by=["AZ","Host","_chip_order","Start"]).reset_index(drop=True)

    # Etiqueta de eje Y (útil para Plotly)
    df["host_chip"] = df["HOST"].astype(str) + " - " + df["AZ"] + " - " + df["Host"].astype(str)

    # ======= NUEVO: Numero y Requerimiento globales por VM =======
    real_mask = df["VM"].notna() & (df["VM"] != "INFRA")
    real = df.loc[real_mask].copy()

    real["_chip_order"] = real["Chip"].map(chip_order).fillna(0)
    real = real.sort_values(by=["VM", "AZ", "_chip_order", "Host", "Start"], ascending=[True, True, True, True, True])

    real["Requerimiento"] = real.groupby("VM")["VM"].transform("count").astype(int)
    real["_k"] = real.groupby("VM").cumcount() + 1
    real["Numero"] = real["_k"].astype(int).astype(str) + " de " + real["Requerimiento"].astype(int).astype(str)

    df["Requerimiento"] = 0
    df["Numero"] = ""
    df.loc[real.index, "Requerimiento"] = real["Requerimiento"].values
    df.loc[real.index, "Numero"] = real["Numero"].values

    # Limpieza
    df = df.drop(columns=["_chip_order"], errors="ignore")

    return df