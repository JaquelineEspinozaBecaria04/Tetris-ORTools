from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import math
from ortools.sat.python import cp_model

from .models import (
    VM, VMType, Placement, HostResult, ChipResult,
    CHIP_CAPACITY, CHIPS_PER_HOST, HOST_CAPACITY
)

@dataclass
class SolverParams:
    enforce_az_per_host: bool = True
    time_limit_s: float = 15.0
    weight_hosts: int = 1_000_000  # objetivo lexicográfico aproximado
    weight_slack: int = 1          # penaliza espacio libre por chip (suave)

class CpsatPacker:
    def __init__(self, vms: List[VM], params: SolverParams):
        self.vms = vms
        self.params = params
        self.az_values = sorted(list({vm.az for vm in vms}))

    def _bounds_hosts(self) -> Tuple[int, int]:
        total_size = sum(vm.size for vm in self.vms)
        lb1 = math.ceil(total_size / HOST_CAPACITY)
        # anti-afinidad: por tipo t con límite k, LB >= ceil(n_t / k)
        counts: Dict[Tuple[str,str], int] = {}
        anti: Dict[Tuple[str,str], int] = {}
        for vm in self.vms:
            k = vm.vm_type.key()
            counts[k] = counts.get(k, 0) + 1
            anti[k] = vm.anti
        lb2 = 0
        for k, n in counts.items():
            lb2 = max(lb2, math.ceil(n / max(1, anti[k])))
        lb = max(lb1, lb2)
        ub = len(self.vms)  # cota superior segura (1 VM por host)
        return lb, ub

    def solve(self) -> Tuple[List[HostResult], Dict]:
        model = cp_model.CpModel()
        n = len(self.vms)
        lb, ub = self._bounds_hosts()
        H = ub  # candidatos de host

        # --- variables ---
        x, u, v, y = {}, {}, {}, {}
        for h in range(H):
            u[h] = model.NewBoolVar(f"u[{h}]")
            for c in range(CHIPS_PER_HOST):
                v[h,c] = model.NewBoolVar(f"v[{h},{c}]")

        if self.params.enforce_az_per_host:
            for h in range(H):
                for a in self.az_values:
                    y[h,a] = model.NewBoolVar(f"y[{h},{a}]")
                model.Add(sum(y[h,a] for a in self.az_values) <= u[h])  # a lo sumo una AZ si se usa

        for i in range(n):
            for h in range(H):
                for c in range(CHIPS_PER_HOST):
                    x[i,h,c] = model.NewBoolVar(f"x[{i},{h},{c}]")
                    model.Add(x[i,h,c] <= u[h])
                    model.Add(x[i,h,c] <= v[h,c])
                    if self.params.enforce_az_per_host:
                        model.Add(x[i,h,c] <= y[h, self.vms[i].az])

        # --- restricciones ---
        # cada VM exactamente en 1 chip
        for i in range(n):
            model.Add(sum(x[i,h,c] for h in range(H) for c in range(CHIPS_PER_HOST)) == 1)

        # capacidad por chip (17)
        for h in range(H):
            for c in range(CHIPS_PER_HOST):
                model.Add(sum(self.vms[i].size * x[i,h,c] for i in range(n)) <= CHIP_CAPACITY)

        # anti-afinidad por (VNF, VNFC) en cada host
        types = {}
        for i, vm in enumerate(self.vms):
            types.setdefault(vm.vm_type.key(), []).append(i)
        for h in range(H):
            for tkey, idxs in types.items():
                k_lim = max(1, self.vms[idxs[0]].anti)
                model.Add(sum(x[i,h,c] for i in idxs for c in range(CHIPS_PER_HOST)) <= k_lim)

        # objetivo: minimizar hosts y luego slack global
        cap = CHIP_CAPACITY
        slack_terms = []
        for h in range(H):
            for c in range(CHIPS_PER_HOST):
                expr_used = sum(self.vms[i].size * x[i,h,c] for i in range(n))
                slack_terms.append(cap * v[h,c] - expr_used)

        model.Minimize(
            self.params.weight_hosts * sum(u[h] for h in range(H)) +
            self.params.weight_slack * sum(slack_terms)
        )

        # Sugerencia: al menos lb hosts (no debe volver el modelo infeasible)
        model.Add(sum(u[h] for h in range(H)) >= lb)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.params.time_limit_s)
        solver.parameters.num_search_workers = 8
        # solver.parameters.log_search_progress = True  # si quieres logs

        res = solver.Solve(model)
        STATUS_MAP = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }
        status_name = STATUS_MAP.get(res, str(res))

        if res not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # devolver stats informativas aunque no haya hosts
            return [], {
                "status": status_name,
                "hosts": 0,
                "total_used": 0,
                "total_capacity": 0,
                "utilization": 0.0,
                "empty_pct": 1.0,
                "per_az": {}
            }

        # --- construir solución ---
        used_hosts = [h for h in range(H) if solver.Value(u[h]) == 1]
        host_id_map = {h: idx+1 for idx, h in enumerate(used_hosts)}
        hosts_out = {}

        for h in used_hosts:
            az = "MIX"
            if self.params.enforce_az_per_host:
                for a in self.az_values:
                    if solver.Value(y[h,a]) == 1:
                        az = a
                        break
            hosts_out[h] = HostResult(id=host_id_map[h], az=az, chips=[ChipResult(), ChipResult()])

        for i, vm in enumerate(self.vms):
            for h in used_hosts:
                done = False
                for c in range(CHIPS_PER_HOST):
                    if solver.Value(x[i,h,c]) == 1:
                        chip = hosts_out[h].chips[c]
                        start = chip.used
                        end = start + vm.size
                        chip.items.append(Placement(vm=vm, host_id=hosts_out[h].id, chip_idx=c, start=start, end=end))
                        chip.used += vm.size
                        done = True
                        break
                if done:
                    break

        hosts_list = list(hosts_out.values())
        hosts_list.sort(key=lambda H: (H.az, H.id))

        total_capacity = len(hosts_list) * HOST_CAPACITY
        total_used = sum(h.used for h in hosts_list)
        util = (total_used / total_capacity) if total_capacity else 0.0

        per_az = {}
        for h in hosts_list:
            a = h.az
            per_az.setdefault(a, {"hosts":0,"used":0,"capacity":0})
            per_az[a]["hosts"] += 1
            per_az[a]["used"] += h.used
            per_az[a]["capacity"] += HOST_CAPACITY

        stats = {
            "status": status_name,
            "hosts": len(hosts_list),
            "total_used": total_used,
            "total_capacity": total_capacity,
            "utilization": util,
            "empty_pct": 1 - util,
            "per_az": {a: {**v, "utilization": (v["used"]/v["capacity"]) if v["capacity"] else 0.0} for a, v in per_az.items()}
        }
        return hosts_list, stats
