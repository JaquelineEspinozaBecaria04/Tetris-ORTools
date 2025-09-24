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
    df = df.sort_values(by=["AZ","Host","_chip_order","Start"]).drop(columns=["_chip_order"]).reset_index(drop=True)

    # Campo auxiliar opcional: etiqueta única por host para el eje Y de Plotly
    df["host_chip"] = df["HOST"].astype(str) + " - " + df["AZ"] + " - " + df["Host"].astype(str)

    # Campo 'Numero' como "k de total" por VM/AZ/Chip/Host (como tu PRIMER INTENTO)
    # (solo para VMs reales; INFRA queda en blanco)
    real_vm_mask = df["VM"] != "INFRA"
    if real_vm_mask.any():
        grp = df.loc[real_vm_mask].groupby(["VM","AZ","Chip","Host"], as_index=False)
        # rango 1..n por grupo
        df.loc[real_vm_mask, "_rank"] = grp.cumcount() + 1
        # tamaño por grupo
        sizes = grp.size().rename(columns={"size": "_n"})
        df = df.merge(sizes, on=["VM","AZ","Chip","Host"], how="left")
        df["Numero"] = df.apply(
            lambda r: (f"{int(r['_rank'])} de {int(r['_n'])}") if r["VM"] != "INFRA" else "",
            axis=1
        )
        df = df.drop(columns=["_rank","_n"])
    else:
        df["Numero"] = ""

    return df
