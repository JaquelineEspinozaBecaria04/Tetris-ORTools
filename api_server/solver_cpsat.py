# api_server/solver_cpsat.py (Versión Final con Modelo de Empaquetado Optimizado)

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple
import math
from ortools.sat.python import cp_model

from .df_layout import build_layout_dataframe

from .models import (
    VM, VMType, Placement, HostResult, ChipResult,
    CHIP_CAPACITY, CHIPS_PER_HOST, HOST_CAPACITY
)

@dataclass
class SolverParams:
    enforce_az_per_host: bool = True
    time_limit_s: float = 15.0

class CpsatPacker:
    def __init__(self, vms: List[VM], params: SolverParams):
        self.vms = vms
        self.params = params
        self.az_values = sorted(list({vm.az for vm in vms}))
        self.vm_types = {vm.vm_type.key(): vm.anti for vm in vms}

    def _bounds_hosts(self) -> Tuple[int, int]:
        """Calcula el número mínimo (lb) y máximo (ub) de hosts a considerar."""
        total_size = sum(vm.size for vm in self.vms)
        lb1 = math.ceil(total_size / HOST_CAPACITY)
        
        counts = {key: 0 for key in self.vm_types}
        for vm in self.vms:
            counts[vm.vm_type.key()] += 1
        
        lb2 = 0
        for k, n in counts.items():
            lb2 = max(lb2, math.ceil(n / max(1, self.vm_types[k])))
        
        lb = max(lb1, lb2)
        # Cota superior optimizada: el mínimo + 30% de margen + 10 de colchón.
        ub = math.ceil(lb * 1.3) + 10
        return int(lb), int(ub)

    def solve(self) -> Tuple[List[HostResult], Dict]:
        """Punto de entrada principal que redirige al método optimizado de dos fases."""
        return self.solve_two_phase()

    def solve_two_phase(self) -> tuple[list[HostResult], dict]:
        """Resuelve el problema en dos fases para mayor eficiencia."""
        # --- FASE 1: Encontrar el número mínimo de hosts ---
        model1 = cp_model.CpModel()
        lb, ub = self._bounds_hosts()
        
        # Se construye un modelo cuyo único objetivo es minimizar los hosts usados.
        placements1, hosts_used1 = self._build_model_final(model1, ub)
        model1.Minimize(sum(hosts_used1))
        
        solver1 = cp_model.CpSolver()
        solver1.parameters.max_time_in_seconds = float(self.params.time_limit_s)
        solver1.parameters.num_search_workers = 8 # Usar múltiples núcleos de CPU
        status1 = solver1.Solve(model1)

        if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return [], {"status": solver1.StatusName(status1), "hosts": 0}
        
        best_hosts_count = int(solver1.ObjectiveValue())

        # --- FASE 2: Con el número de hosts ya fijo, buscar un mejor empaquetado ---
        model2 = cp_model.CpModel()
        placements2, hosts_used2 = self._build_model_final(model2, best_hosts_count)
        model2.Add(sum(hosts_used2) == best_hosts_count)
        
        solver2 = cp_model.CpSolver()
        solver2.parameters.max_time_in_seconds = float(self.params.time_limit_s)
        solver2.parameters.num_search_workers = 8
        status2 = solver2.Solve(model2)

        if status2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print("ADVERTENCIA: Fase 2 no encontró solución, devolviendo resultado de Fase 1.")
            return self._extract_solution(solver1, placements1)

        return self._extract_solution(solver2, placements2) 

    # Reemplaza la función _build_model_final completa en tu solver_cpsat.py con esta:

    def _build_model_final(self, model: cp_model.CpModel, num_hosts: int):
        """Construye un modelo de Bin-Packing usando las restricciones nativas y más eficientes."""
        num_vms = len(self.vms)
        num_chips = num_hosts * CHIPS_PER_HOST

        # --- VARIABLES PRINCIPALES (MODELO DE "AGENDA") ---
        starts = [model.NewIntVar(0, CHIP_CAPACITY, f'start_{i}') for i in range(num_vms)]
        chips = [model.NewIntVar(0, num_chips - 1, f'chip_{i}') for i in range(num_vms)]
        
        # --- RESTRICCIÓN DE CAPACIDAD (BIN-PACKING) con AddNoOverlap ---
        tasks_per_chip = [[] for _ in range(num_chips)]
        
        # <<< CORRECCIÓN: Se usa NewOptionalIntervalVar para crear los intervalos >>>
        for i in range(num_vms):
            for c in range(num_chips):
                # b es la variable que indica si la VM i ESTÁ PRESENTE en el chip c.
                b = model.NewBoolVar(f'presence_{i}_on_chip_{c}')
                model.Add(chips[i] == c).OnlyEnforceIf(b)
                model.Add(chips[i] != c).OnlyEnforceIf(b.Not())
                
                # Se crea un INTERVALO OPCIONAL. Este intervalo solo "existe" para el solver
                # si su variable de presencia (b) es verdadera.
                interval = model.NewOptionalIntervalVar(
                    starts[i], self.vms[i].size, starts[i] + self.vms[i].size, b, f'interval_{i}_on_{c}'
                )
                tasks_per_chip[c].append(interval)

        for c in range(num_chips):
            # AddNoOverlap ahora recibe una lista de intervalos opcionales.
            # Automáticamente ignorará los que no estén presentes.
            model.AddNoOverlap(tasks_per_chip[c])

        # --- OTRAS RESTRICCIONES (AZ y ANTI-AFINIDAD) ---
        host_of_vm = [model.NewIntVar(0, num_hosts - 1, f'host_of_vm_{i}') for i in range(num_vms)]
        for i in range(num_vms):
            model.AddDivisionEquality(host_of_vm[i], chips[i], CHIPS_PER_HOST)

        # AZ: Si dos VMs tienen AZ diferente, no pueden estar en el mismo host.
        if self.params.enforce_az_per_host:
            for i in range(num_vms):
                for j in range(i + 1, num_vms):
                    if self.vms[i].az != self.vms[j].az:
                        model.Add(host_of_vm[i] != host_of_vm[j])

        # Anti-afinidad: A lo sumo 'limit' VMs del mismo tipo por host.
        vms_by_type = {key: [] for key in self.vm_types}
        for i, vm in enumerate(self.vms):
            vms_by_type[vm.vm_type.key()].append(i)
        
        for type_key, vm_indices in vms_by_type.items():
            if not vm_indices: continue
            limit = self.vm_types[type_key]
            if limit >= len(vm_indices): continue
            
            for h in range(num_hosts):
                vms_on_host = [model.NewBoolVar(f'type_{type_key}_vm_{i}_on_host_{h}') for i in vm_indices]
                for i, b_var in zip(vm_indices, vms_on_host):
                    model.Add(host_of_vm[i] == h).OnlyEnforceIf(b_var)
                    model.Add(host_of_vm[i] != h).OnlyEnforceIf(b_var.Not())
                model.Add(sum(vms_on_host) <= limit)

        # --- OBJETIVO Y SIMETRÍA ---
        hosts_used = [model.NewBoolVar(f"host_used_{h}") for h in range(num_hosts)]
        for h in range(num_hosts):
            is_any_vm_on_host = [model.NewBoolVar(f'any_vm_{i}_on_host_{h}') for i in range(num_vms)]
            for i in range(num_vms):
                model.Add(host_of_vm[i] == h).OnlyEnforceIf(is_any_vm_on_host[i])
                model.Add(host_of_vm[i] != h).OnlyEnforceIf(is_any_vm_on_host[i].Not())
            model.AddMaxEquality(hosts_used[h], is_any_vm_on_host)

            if h > 0:
                model.Add(hosts_used[h] <= hosts_used[h-1])

        return (chips, starts), hosts_used

    def _extract_solution(self, solver: cp_model.CpSolver, placements: tuple) -> tuple[list, dict]:
        """Extrae la solución del nuevo modelo y la formatea."""
        chips_sol, starts_sol = placements
        hosts_out: Dict[int, HostResult] = {}
        
        for vm_idx, vm in enumerate(self.vms):
            chip_val = solver.Value(chips_sol[vm_idx])
            start_val = solver.Value(starts_sol[vm_idx])
            host_idx = chip_val // CHIPS_PER_HOST
            chip_idx_local = chip_val % CHIPS_PER_HOST
            
            if host_idx not in hosts_out:
                hosts_out[host_idx] = HostResult(id=0, az=vm.az, chips=[ChipResult(), ChipResult()])
            
            chip = hosts_out[host_idx].chips[chip_idx_local]
            placement_obj = Placement(vm=vm, host_id=0, chip_idx=chip_idx_local, start=start_val, end=start_val + vm.size)
            chip.items.append(placement_obj)
            chip.used += vm.size

        hosts_list = sorted(hosts_out.values(), key=lambda h: (h.az))
        for host in hosts_list:
            for chip in host.chips:
                chip.items.sort(key=lambda p: p.start)
        for i, host in enumerate(hosts_list):
            host.id = i + 1
            for chip in host.chips:
                for p in chip.items:
                    p.host_id = host.id

        # --- CÁLCULO DE ESTADÍSTICAS ---
        df = build_layout_dataframe(hosts_list)
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
                per_az[az] = {"hosts": int(hosts_in_az), "used": used_in_az, "capacity": int(capacity_in_az), "utilization": (used_in_az / capacity_in_az) if capacity_in_az else 0.0}

        chips_used, holes_hist = 0, {}
        if used_hosts > 0:
            for _, df_chip in df[df['VM'] != 'INFRA'].groupby(by=['Chip', 'HOST']):
                ch_used = df_chip["Length"].sum()
                slack = CHIP_CAPACITY - ch_used
                holes_hist[slack] = holes_hist.get(slack, 0) + 1
                chips_used += 1

        host_utils = [df_host.loc[df_host["VM"] != "INFRA", "Length"].sum() / HOST_CAPACITY for _, df_host in df.groupby(by='HOST')] if used_hosts > 0 else []
        
        stats = {
            "status": solver.StatusName(), "hosts": used_hosts, "total_used": total_used,
            "total_capacity": total_capacity, "utilization": util, "empty_pct": 1 - util,
            "chips_used": chips_used, "holes_histogram": {str(k): v for k, v in holes_hist.items()},
            "host_utilization": {
                "avg": sum(host_utils)/len(host_utils) if host_utils else 0.0,
                "max": max(host_utils) if host_utils else 0.0,
                "min": min(host_utils) if host_utils else 0.0,
            },
            "per_az": per_az
        }
        
        return hosts_list, stats