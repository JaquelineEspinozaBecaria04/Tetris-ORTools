# api_server/solver_idati.py (Versión Corregida)

import pandas as pd
import numpy as np
import math
from typing import List, Dict, Tuple # <<< CORRECCIÓN: Se añaden las importaciones que faltaban
from scipy.optimize import linear_sum_assignment

# Importamos los modelos de datos de nuestro proyecto para la estandarización
from .models import VM, HostResult, ChipResult, Placement, CHIP_CAPACITY, HOST_CAPACITY
from .solver_cpsat import SolverParams


# =======================================================
# FUNCIONES ORIGINALES DEL ALGORITMO IDATI 
# =======================================================

def f_reducir_anti_afinidad(requerimiento: pd.DataFrame) -> pd.DataFrame:
    filas = requerimiento.apply(
        lambda f: [pd.Series({**f.to_dict(), 'Requerimiento': r}) for r in
                   [*([f.Requerimiento // f['Anti-Afinidad'] + 1] * (f.Requerimiento % f['Anti-Afinidad'])) +
                    [f.Requerimiento // f['Anti-Afinidad']] * (f['Anti-Afinidad'] - f.Requerimiento % f['Anti-Afinidad'])]],
        axis=1
    ).explode().apply(pd.Series)
    filas['Anti-Afinidad'] = 1
    piezas = filas.groupby('Longitud', group_keys=False).apply(
        lambda df: df.sort_values(['AZ', 'Requerimiento', 'VNF'], ascending=[True, True, False])
                      .assign(Longitud=lambda x: x['Longitud'] + (x.reset_index(drop=True).index + 1) * 0.001)
    )
    return piezas.reset_index(drop=True)

def f_proceso(piezas: pd.DataFrame, conjuntos: pd.DataFrame, limite):
    def f_seleccionar_elementos(numeros, excluidos):
        seleccion = []
        for n in numeros:
            if n not in excluidos and sum(seleccion) + n <= limite:
                seleccion.append(n)
        return seleccion

    numeros = piezas.sort_values(['Requerimiento', 'Longitud'], ascending=[False, False])['Longitud'].to_list()
    elemento1 = f_seleccionar_elementos(numeros, [])

    piezas.loc[piezas['Longitud'].isin(elemento1), 'Requerimiento'] -= 1
    piezas = piezas[piezas['Requerimiento'] != 0]

    numeros = piezas.sort_values(['Requerimiento', 'Longitud'], ascending=[False, False])['Longitud'].to_list()
    elemento2 = f_seleccionar_elementos(numeros, elemento1) if numeros else []

    piezas.loc[piezas['Longitud'].isin(elemento2), 'Requerimiento'] -= 1
    piezas = piezas[piezas['Requerimiento'] != 0]

    return piezas, elemento1, elemento2

def f_acomodo_por_chip(conjuntos):
    conjuntos_ordenado = conjuntos.copy()
    existencias = []
    for i in range(len(conjuntos_ordenado)):
        chip1 = conjuntos_ordenado.at[i, "Chip 1"]
        chip2 = conjuntos_ordenado.at[i, "Chip 2"]
        if chip1 in existencias:
            continue
        elif chip2 in existencias:
            conjuntos_ordenado.at[i, "Chip 1"] = chip2
            conjuntos_ordenado.at[i, "Chip 2"] = chip1
            existencias.append(chip2)
        else:
            existencias.append(chip1)
    return conjuntos_ordenado

def f_reordenar_chip2(conjuntos_zona):
    n = len(conjuntos_zona)
    costo = np.full((n, n), np.inf)

    for i in range(n):
        chip1_set = set(conjuntos_zona.loc[i, 'Chip 1'])
        for j in range(n):
            chip2_set = set(conjuntos_zona.loc[j, 'Chip 2'])
            if chip1_set.isdisjoint(chip2_set):
                costo[i, j] = -conjuntos_zona.loc[j, 'Suma2']
    row_ind, col_ind = linear_sum_assignment(costo)
    conjuntos_zona['Chip2_opt'] = conjuntos_zona.loc[col_ind, 'Chip 2'].values
    conjuntos_zona['Suma2_opt'] = conjuntos_zona.loc[col_ind, 'Suma2'].values
    conjuntos_zona = conjuntos_zona[['Chip 1','Chip2_opt']]
    conjuntos_zona.columns = ['Chip 1', 'Chip 2']
    return conjuntos_zona

def f_tetris_piezas(conjuntos, piezas_respaldo, requerimiento, zona, limite, sin_uso):
    piezas = piezas_respaldo.drop(['Anti-Afinidad', 'Requerimiento'], axis=1)
    piezas = piezas.merge(requerimiento[['VNF', 'VNFC', 'Anti-Afinidad', 'Requerimiento']], on=['VNF', 'VNFC'], how='left')
    tetris = []
    for host in conjuntos['Host'].unique():
        for chip, (start, extra) in zip(['Chip 1', 'Chip 2'], [(0, limite), (limite + sin_uso, 2*limite + sin_uso)]):
            for conjunto in conjuntos[conjuntos['Host'] == host][chip]:
                for pieza in conjunto:
                    match = piezas[piezas['Longitud'] == pieza].iloc[0]
                    tetris.append({
                        'AZ': zona,
                        'Host': host,
                        'Chip': chip,
                        'VM': f"{match['VNF']} {match['VNFC']}",
                        'Start': start,
                        'Length': int(pieza),
                        'Color': match['Color'],
                        'Inst.': match['Inst.'],
                        'Anti-Afinidad': match['Anti-Afinidad'],
                        'Requerimiento': match['Requerimiento'], 
                        'VNF': match['VNF'],
                        'VNFC': match['VNFC']
                    })
                    start += int(pieza)
            tetris.append({
                'AZ': zona, 'Host': host, 'Chip': chip, 'VM': 'INFRA', 'Start': extra,
                'Length': sin_uso, 'Color': '#000000', 'Inst.': 0, 'Anti-Afinidad': 0, 'Requerimiento': 0, 
                'VNF': np.nan, 'VNFC': np.nan
            })
    return pd.DataFrame(tetris)

def f_numero(tetris_piezas: pd.DataFrame) -> pd.DataFrame:
    df = tetris_piezas.copy().sort_values(by=['VM', 'AZ', 'Host', 'Chip', 'Start']).reset_index(drop=True)
    df['Numero'] = df.groupby('VM').cumcount() + 1
    df['Total'] = df.groupby('VM')['VM'].transform('count')
    df['Numero'] = df['Numero'].astype(str) + ' de ' + df['Total'].astype(str)
    return df.drop(columns='Total')

# =======================================================
# CLASE ADAPTADORA IDATI
# =======================================================
class IdatiPacker:
    def __init__(self, vms: List[VM], params: SolverParams):
        self.params = params
        self.vms_originales = vms
        if not vms:
            self.requerimiento_df = pd.DataFrame()
            return
        requerimiento_list = []
        for vm in vms:
            requerimiento_list.append({
                'VNF': vm.vm_type.vnf, 'VNFC': vm.vm_type.vnfc, 'Longitud': vm.size,
                'AZ': vm.az, 'Color': vm.color, 'Anti-Afinidad': vm.anti,
                'Requerimiento': 1, 'Inst.': vm.inst, 'vm_idx': vm.idx
            })
        self.requerimiento_df = pd.DataFrame(requerimiento_list)

    def solve(self) -> Tuple[List[HostResult], Dict]:
        if self.requerimiento_df.empty:
            return [], {"status": "NO_VMS"}
        
        # --- LÓGICA IDATI  ---

        # --- PASO 1: RE-AGREGAR LOS DATOS ---
        # Agrupamos las VMs por todas sus propiedades para contarlas.
        # Esto recrea el formato que tu algoritmo espera (datos agregados).
        requerimiento_agregado = self.requerimiento_df.groupby(
            ['VNF', 'VNFC', 'Longitud', 'AZ', 'Color', 'Anti-Afinidad', 'Inst.']
        ).agg(
            # Contamos cuántas VMs hay en cada grupo para obtener el 'Requerimiento'
            Requerimiento=('vm_idx', 'count')
        ).reset_index()

        #===============================
        # --- PASO 2: EJECUTAR EL ALGORITMO IDATI ---
        requerimiento = requerimiento_agregado
        tamaño_chip, sin_uso = 17, 3
        requerimiento_modificado = f_reducir_anti_afinidad(requerimiento).reset_index(drop=True)
        conjuntos = pd.DataFrame()
        for zona in requerimiento['AZ'].unique():
            piezas = requerimiento_modificado[requerimiento_modificado['AZ'] == zona]
            conjuntos_zona = pd.DataFrame()
            while not piezas.empty:
                piezas, elem1, elem2 = f_proceso(piezas, conjuntos_zona, tamaño_chip + 0.999)
                conjuntos_zona = pd.concat([
                    conjuntos_zona,
                    pd.DataFrame({'Chip 1': [sorted(elem1, reverse=True)], 'Chip 2': [sorted(elem2, reverse=True)]})
                ], ignore_index=True)
            for func in [f_acomodo_por_chip, f_reordenar_chip2]:
                conjuntos_zona['Suma1'] = conjuntos_zona['Chip 1'].apply(sum)
                conjuntos_zona['Suma2'] = conjuntos_zona['Chip 2'].apply(sum)
                conjuntos_zona = conjuntos_zona.sort_values(['Suma1', 'Suma2'], ascending=False).reset_index(drop=True)
                conjuntos_zona = func(conjuntos_zona)
            conjuntos_zona['Suma1'] = conjuntos_zona['Chip 1'].apply(sum)
            conjuntos_zona['Suma2'] = conjuntos_zona['Chip 2'].apply(sum)
            conjuntos_zona = conjuntos_zona.sort_values(['Suma1', 'Suma2'], ascending=False).reset_index(drop=True)
            conjuntos_zona['Host'] = conjuntos_zona.index + 1
            conjuntos_zona['AZ'] = zona
            conjuntos = pd.concat([conjuntos, conjuntos_zona[['AZ', 'Host', 'Chip 1', 'Chip 2']]], ignore_index=True)
        
        tetris_piezas = pd.concat([
            f_tetris_piezas(
                conjuntos[conjuntos['AZ'] == zona].drop(columns='AZ'),
                requerimiento_modificado[requerimiento_modificado['AZ'] == zona],
                requerimiento, zona, tamaño_chip, sin_uso
            ).sort_values(['AZ', 'Host', 'Chip', 'Start']).reset_index(drop=True)
            for zona in conjuntos['AZ'].unique()
        ], ignore_index=True)
        
        max_host_por_zona = tetris_piezas.groupby('AZ')['Host'].max().cumsum().shift(fill_value=0)
        tetris_piezas['HOST'] = tetris_piezas['Host'] + tetris_piezas['AZ'].map(max_host_por_zona)
        tetris_piezas = f_numero(tetris_piezas)
        
        # --- CÁLCULO DE ESTADÍSTICAS ---
        df = tetris_piezas
        used_hosts = int(df['HOST'].max()) if not df.empty else 0
        total_capacity = used_hosts * HOST_CAPACITY
        total_used = int(df.loc[df["VM"] != "INFRA", "Length"].sum())
        util = (total_used / total_capacity) if total_capacity else 0.0
        stats = {"status": "COMPUTED", "hosts": used_hosts, "total_used": total_used,
                 "total_capacity": total_capacity, "utilization": util, "empty_pct": 1 - util}
        
        # --- TRADUCTOR DE SALIDA ---
        hosts_dict = {}
        vm_map = {vm.idx: vm for vm in self.vms_originales}

        
        tetris_piezas_con_idx = pd.merge(
            tetris_piezas,
            self.requerimiento_df[['VNF', 'VNFC', 'Inst.', 'vm_idx']].drop_duplicates(),
            on=['VNF', 'VNFC', 'Inst.'],
            how='left'
        )

        for _, row in tetris_piezas_con_idx.iterrows():
            if row['VM'] == 'INFRA' or pd.isna(row['vm_idx']):
                continue

            host_key = (row['AZ'], row['Host'])
            if host_key not in hosts_dict:
                hosts_dict[host_key] = HostResult(id=0, az=row['AZ'], chips=[ChipResult(), ChipResult()])

            chip_idx = 0 if row['Chip'] == 'Chip 1' else 1
            

            vm_original = vm_map.get(int(row['vm_idx']))
            if not vm_original:
                continue

            
            placement = Placement(
                vm=vm_original,
                host_id=0,
                chip_idx=chip_idx, 
                start=row['Start'] % (tamaño_chip + sin_uso),
                end=(row['Start'] % (tamaño_chip + sin_uso)) + row['Length']
            )

            hosts_dict[host_key].chips[chip_idx].items.append(placement)
            hosts_dict[host_key].chips[chip_idx].used += row['Length']
            
        hosts_list = sorted(hosts_dict.values(), key=lambda h: h.az)
        for i, host in enumerate(hosts_list):
            host.id = i + 1
            for chip in host.chips:
                for p in chip.items:
                    p.host_id = host.id

        return hosts_list, stats