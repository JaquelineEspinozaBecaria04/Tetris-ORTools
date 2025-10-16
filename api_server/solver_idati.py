# api_server/solver_idati.py (Versión Final, Óptima y Corregida)

import pandas as pd
import numpy as np
import math
from typing import List, Dict, Tuple
from scipy.optimize import linear_sum_assignment

# Importamos los modelos de datos estándar del proyecto
from .models import VM, HostResult, ChipResult, Placement, CHIP_CAPACITY, HOST_CAPACITY, CHIPS_PER_HOST
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
        if chip1 in existencias: continue
        elif chip2 in existencias:
            conjuntos_ordenado.at[i, "Chip 1"] = chip2
            conjuntos_ordenado.at[i, "Chip 2"] = chip1
            existencias.append(chip2)
        else: existencias.append(chip1)
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
    piezas = piezas_respaldo.drop(['Anti-Afinidad', 'Requerimiento'], axis=1, errors='ignore')
    piezas = piezas.merge(requerimiento[['VNF', 'VNFC', 'Anti-Afinidad', 'Requerimiento']], on=['VNF', 'VNFC'], how='left')
    tetris = []
    for host in conjuntos['Host'].unique():
        for chip, (start, extra) in zip(['Chip 1', 'Chip 2'], [(0, limite), (limite + sin_uso, 2*limite + sin_uso)]):
            for conjunto in conjuntos[conjuntos['Host'] == host][chip]:
                for pieza in conjunto:
                    match = piezas[piezas['Longitud'] == pieza].iloc[0]
                    tetris.append({
                        'AZ': zona, 'Host': host, 'Chip': chip,
                        'VM': f"{match['VNF']} {match['VNFC']}", 'Start': start,
                        'Length': int(pieza), 'Color': match['Color'],
                        # 'Inst.' se añade después para el rastreo, no es parte del resultado original
                        'Anti-Afinidad': match['Anti-Afinidad'], 'Requerimiento': match['Requerimiento'],
                        'VNF': match['VNF'], 'VNFC': match['VNFC']
                    })
                    start += int(pieza)
            tetris.append({
                'AZ': zona, 'Host': host, 'Chip': chip, 'VM': 'INFRA', 'Start': extra,
                'Length': sin_uso, 'Color': '#000000', 'Anti-Afinidad': 0, 'Requerimiento': 0,
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
# CLASE ADAPTADORA IDATI (El Traductor)
# =======================================================
class IdatiPacker:
    def __init__(self, vms: List[VM], params: SolverParams):
        # Fase de Traducción de Entrada: List[VM] -> DataFrame
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

        # --- FASE 1: Preparación de Datos para preservar la lógica original ---
        # Se agrupan los datos sin 'Inst.' para que el algoritmo sea óptimo.
        requerimiento_agregado = self.requerimiento_df.groupby(
            ['VNF', 'VNFC', 'Longitud', 'AZ', 'Color', 'Anti-Afinidad']
        ).agg(
            Requerimiento=('vm_idx', 'count')
        ).reset_index()

        # --- FASE 2: Ejecución de la Lógica Original del Algoritmo IDATI ---
        requerimiento_para_algoritmo = requerimiento_agregado
        tamaño_chip, sin_uso = 17, 3
        requerimiento_modificado = f_reducir_anti_afinidad(requerimiento_para_algoritmo).reset_index(drop=True)
        
        conjuntos = pd.DataFrame()
        for zona in requerimiento_para_algoritmo['AZ'].unique():
            piezas = requerimiento_modificado[requerimiento_modificado['AZ'] == zona]
            conjuntos_zona = pd.DataFrame()
            while not piezas.empty:
                piezas, elem1, elem2 = f_proceso(piezas, conjuntos_zona, tamaño_chip + 0.999)
                conjuntos_zona = pd.concat([conjuntos_zona, pd.DataFrame({'Chip 1': [sorted(elem1, reverse=True)], 'Chip 2': [sorted(elem2, reverse=True)]})], ignore_index=True)
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
                requerimiento_para_algoritmo, zona, tamaño_chip, sin_uso
            ).sort_values(['AZ', 'Host', 'Chip', 'Start']).reset_index(drop=True)
            for zona in conjuntos['AZ'].unique()
        ], ignore_index=True)
        
        max_host_por_zona = tetris_piezas.groupby('AZ')['Host'].max().cumsum().shift(fill_value=0)
        tetris_piezas['HOST'] = tetris_piezas['Host'] + tetris_piezas['AZ'].map(max_host_por_zona)
        tetris_piezas = f_numero(tetris_piezas)
        
        # --- FASE 3: Traducción de Salida y Cálculo de Estadísticas ---
        
        # Primero, enriquecemos el resultado con la columna 'Inst.' para el rastreo.
        inst_map = self.requerimiento_df[['VNF', 'VNFC', 'Inst.']].drop_duplicates()
        tetris_piezas = pd.merge(tetris_piezas, inst_map, on=['VNF', 'VNFC'], how='left')
        
        # Segundo, calculamos todas las estadísticas (bloque completo y corregido).
        df = tetris_piezas
        used_hosts = int(df['HOST'].max()) if not df.empty else 0
        total_capacity = used_hosts * HOST_CAPACITY
        total_used = int(df.loc[df["VM"] != "INFRA", "Length"].sum())
        util = (total_used / total_capacity) if total_capacity else 0.0
        
        per_az = {}
        if used_hosts > 0:
            for az, df_zona in df.groupby(by='AZ'):
                hosts_in_az = df_zona['Host'].max() if not df_zona.empty else 0
                used_in_az = int(df_zona.loc[df_zona["VM"] != "INFRA", "Length"].sum())
                capacity_in_az = int(hosts_in_az) * HOST_CAPACITY
                per_az[az] = { "hosts": int(hosts_in_az), "used": used_in_az, "capacity": int(capacity_in_az), "utilization": (used_in_az / capacity_in_az) if capacity_in_az else 0.0 }

        chips_used, holes_hist = 0, {}
        if used_hosts > 0:
            for _, df_chip in df[df['VM'] != 'INFRA'].groupby(by=['Chip', 'HOST']):
                ch_used = df_chip["Length"].sum()
                slack = CHIP_CAPACITY - ch_used
                holes_hist[slack] = holes_hist.get(slack, 0) + 1
                chips_used += 1

        host_utils = [ df_host.loc[df_host["VM"] != "INFRA", "Length"].sum() / HOST_CAPACITY for _, df_host in df.groupby(by='HOST') ] if used_hosts > 0 else []
        
        stats = {
            "status": "FEASIBLE", "hosts": used_hosts, "total_used": total_used,
            "total_capacity": total_capacity, "utilization": util, "empty_pct": 1 - util,
            "chips_used": chips_used, "holes_histogram": {str(k): v for k, v in holes_hist.items()},
            "host_utilization": {
                "avg": sum(host_utils)/len(host_utils) if host_utils else 0.0,
                "max": max(host_utils) if host_utils else 0.0,
                "min": min(host_utils) if host_utils else 0.0,
            },
            "per_az": per_az
        }
        
        # Tercero, traducimos el resultado al formato estándar de la aplicación de forma robusta.
        hosts_dict = {}
        vm_map = {vm.idx: vm for vm in self.vms_originales}
        vm_idx_pool = self.requerimiento_df.groupby(['VNF', 'VNFC', 'Inst.']).apply(lambda x: sorted(list(x['vm_idx']))).to_dict()

        for _, row in tetris_piezas.iterrows():
            if row['VM'] == 'INFRA': continue

            pool_key = (row['VNF'], row['VNFC'], row['Inst.'])
            vm_idx_to_assign = None
            if pool_key in vm_idx_pool and vm_idx_pool[pool_key]:
                vm_idx_to_assign = vm_idx_pool[pool_key].pop(0)

            if vm_idx_to_assign is None: continue

            host_key = (row['AZ'], row['Host'])
            if host_key not in hosts_dict:
                hosts_dict[host_key] = HostResult(id=0, az=row['AZ'], chips=[ChipResult(), ChipResult()])

            chip_idx = 0 if row['Chip'] == 'Chip 1' else 1
            vm_original = vm_map.get(vm_idx_to_assign)
            
            if not vm_original: continue

            placement = Placement(
                vm=vm_original, host_id=0, chip_idx=chip_idx,
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