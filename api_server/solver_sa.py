# backend/solver_sa.py

import math
import random
import copy
from collections import Counter
from typing import List, Dict, Tuple

# --- Importaciones del proyecto para la estandarización ---
from .models import (
    VM, VMType, HostResult, ChipResult, Placement,
    CHIP_CAPACITY, HOST_CAPACITY, CHIPS_PER_HOST
)
from .solver_cpsat import SolverParams

# ==============================================================================
# 1. CÓDIGO ORIGINAL DEL ALGORITMO DE RECOCIDO SIMULADO (recocidos.py)
#    (con pequeños ajustes para que funcione como un módulo)
# ==============================================================================

# Nota: Las variables que antes eran globales (cores, az, numero_hosts) ahora
# se pasan como parámetros a las funciones para un mejor encapsulamiento.

def generar_solucion_inicial(vmf, cores, az, numero_hosts_por_az):
    random.shuffle(vmf)
    solucion = []
    no_aceptadas = []
    
    # Estructura de datos para el seguimiento de la capacidad
    servidor_tetris = [[[ [cores] for _ in range(CHIPS_PER_HOST)] for _ in range(numero_hosts_por_az[i])] for i in range(az)]

    for clase in vmf:
        aceptada = False
        longitud = clase['longitud']
        nombre = clase['nombre']
        zona_idx = clase['zona_idx']
        max_piezas = clase['max_piezas']

        for i, host in enumerate(servidor_tetris[zona_idx]):
            cores_restantes_c1 = servidor_tetris[zona_idx][i][0][0]
            cores_restantes_c2 = servidor_tetris[zona_idx][i][1][0]
            
            # Intenta en Chip 1 si hay espacio
            if cores_restantes_c1 >= longitud:
                chip = 1
                asignacion = {
                    'idx': clase['idx'], # Pasamos el índice original
                    'nombre': nombre,
                    'longitud': longitud,
                    'host': i,
                    'core_inicio': cores - cores_restantes_c1,
                    'chip': chip,
                    'max_piezas': max_piezas,
                    'zona_idx': zona_idx,
                    'color': clase['color'],
                    'instancia': clase['instancia']
                }
                solucion.append(asignacion)
                servidor_tetris[zona_idx][i][chip-1][0] -= longitud
                aceptada = True
                break
            # Intenta en Chip 2 si hay espacio
            elif cores_restantes_c2 >= longitud:
                chip = 2
                asignacion = {
                    'idx': clase['idx'],
                    'nombre': nombre,
                    'longitud': longitud,
                    'host': i,
                    'core_inicio': cores - cores_restantes_c2,
                    'chip': chip,
                    'max_piezas': max_piezas,
                    'zona_idx': zona_idx,
                    'color': clase['color'],
                    'instancia': clase['instancia']
                }
                solucion.append(asignacion)
                servidor_tetris[zona_idx][i][chip-1][0] -= longitud
                aceptada = True
                break
        
        if not aceptada:
            no_aceptadas.append(clase)

    if no_aceptadas:
        print(f"ADVERTENCIA: {len(no_aceptadas)} VMs no pudieron ser asignadas en la solución inicial.")

    # Limpiar hosts no utilizados
    servidor_tetris_final = copy.deepcopy(servidor_tetris)
    hosts_usados_por_az = [0] * az
    
    solucion_mapeada = []
    host_map = {} # (zona, viejo_host_idx) -> nuevo_host_idx

    for az_idx in range(az):
        host_actual = 0
        for host_idx in range(len(servidor_tetris[az_idx])):
            # Si el host fue utilizado (capacidad no es la inicial en ambos chips)
            if servidor_tetris[az_idx][host_idx][0][0] < cores or servidor_tetris[az_idx][host_idx][1][0] < cores:
                host_map[(az_idx, host_idx)] = host_actual
                hosts_usados_por_az[az_idx] += 1
                host_actual += 1

    for s in solucion:
        nuevo_host_idx = host_map.get((s['zona_idx'], s['host']))
        if nuevo_host_idx is not None:
            s_copia = s.copy()
            s_copia['host'] = nuevo_host_idx
            solucion_mapeada.append(s_copia)

    return sorted(solucion_mapeada, key=lambda x: (x['zona_idx'], x['host'], x['chip'], x['core_inicio'])), hosts_usados_por_az

def evaluar_solucion(hosts_usados_por_az):
    # En este modelo simplificado, el costo es simplemente el número de hosts utilizados.
    # El objetivo es minimizar este número.
    return sum(hosts_usados_por_az)

def recocido_simulado(vmf, cores, az, numero_hosts_por_az, T_inicial=1000, T_final=1, alpha=0.985, max_iter=1000):
    # Genera una solución inicial aleatoria pero válida
    solucion_actual, hosts_usados_actual = generar_solucion_inicial(vmf, cores, az, numero_hosts_por_az)
    costo_actual = evaluar_solucion(hosts_usados_actual)

    mejor_solucion = copy.deepcopy(solucion_actual)
    mejor_costo = costo_actual
    
    T = T_inicial
    iteracion = 0

    # Bucle principal del recocido simulado
    while T > T_final and iteracion < max_iter:
        # Generar un "vecino" es simplemente volver a intentar una colocación aleatoria
        vecino, hosts_usados_vecino = generar_solucion_inicial(vmf, cores, az, numero_hosts_por_az)
        costo_vecino = evaluar_solucion(hosts_usados_vecino)
        
        delta = costo_vecino - costo_actual

        # Si el vecino es mejor, o si se acepta una solución peor por probabilidad, se actualiza
        if delta < 0 or random.random() < math.exp(-delta / T):
            solucion_actual = vecino
            costo_actual = costo_vecino
            hosts_usados_actual = hosts_usados_vecino

            # Si la solución actual es la mejor encontrada hasta ahora, se guarda
            if costo_actual < mejor_costo:
                mejor_solucion = copy.deepcopy(solucion_actual)
                mejor_costo = costo_actual
        
        T *= alpha
        iteracion += 1

    return mejor_solucion, mejor_costo, iteracion


# ==============================================================================
# 2. CLASE ADAPTADORA `SaPacker`
#    Esta clase hace que el algoritmo de Recocido Simulado sea compatible
#    con el resto de la aplicación.
# ==============================================================================

class SaPacker:
    def __init__(self, vms: List[VM], params: SolverParams):
        self.vms_originales = vms
        self.params = params
        self.az_map = {az_name: i for i, az_name in enumerate(sorted(list({vm.az for vm in vms})))}
        
        # --- Adaptación de Entrada ---
        # Convierte la lista de objetos `VM` al formato `vmf` (lista de dicts)
        # que el algoritmo SA entiende.
        self.vmf = []
        for vm in vms:
            self.vmf.append({
                "idx": vm.idx, # Guardamos el índice original para poder mapear la salida
                "nombre": f"{vm.vm_type.vnf}{vm.vm_type.vnfc}",
                "longitud": vm.size,
                "zona_idx": self.az_map[vm.az], # Usamos un índice numérico para la zona
                "max_piezas": vm.anti,
                "color": vm.color,
                "instancia": vm.inst
            })

    def solve(self) -> Tuple[List[HostResult], Dict]:
        """
        Ejecuta el algoritmo y adapta la salida al formato estándar.
        """
        if not self.vmf:
            return [], {"status": "NO_VMS", "hosts": 0}

        num_azs = len(self.az_map)
        # Un número inicial grande y seguro de hosts por zona para la colocación
        # El algoritmo se encargará de usar solo los necesarios.
        initial_hosts_per_az = [len(self.vms_originales)] * num_azs

        # Ejecutamos el algoritmo
        solucion_final, costo, num_gens = recocido_simulado(
            self.vmf,
            cores=CHIP_CAPACITY,
            az=num_azs,
            numero_hosts_por_az=initial_hosts_per_az,
            T_inicial=self.params.time_limit_s * 10, # Heurística simple para la temperatura
            max_iter=int(self.params.time_limit_s * 15) # Heurística para iteraciones
        )
        
        # --- Adaptación de Salida ---
        # Convierte la `solucion_final` (lista de dicts) a `List[HostResult]`.
        if not solucion_final:
            return [], {"status": "INFEASIBLE", "hosts": 0}
            
        hosts_dict = {} # (az_idx, host_idx) -> HostResult

        # 1. Agrupar VMs por host y chip
        for vm_colocada in solucion_final:
            az_idx = vm_colocada['zona_idx']
            host_idx = vm_colocada['host']
            chip_idx = vm_colocada['chip'] - 1 # 0 o 1
            
            # Recuperar el objeto VM original usando el índice que guardamos
            vm_original = next((vm for vm in self.vms_originales if vm.idx == vm_colocada['idx']), None)
            if not vm_original:
                continue

            host_key = (az_idx, host_idx)
            if host_key not in hosts_dict:
                az_name = next(key for key, value in self.az_map.items() if value == az_idx)
                hosts_dict[host_key] = HostResult(id=0, az=az_name, chips=[ChipResult(), ChipResult()])
            
            placement = Placement(
                vm=vm_original,
                host_id=0, # Se asignará después
                chip_idx=chip_idx,
                start=vm_colocada['core_inicio'],
                end=vm_colocada['core_inicio'] + vm_colocada['longitud']
            )
            hosts_dict[host_key].chips[chip_idx].items.append(placement)
            hosts_dict[host_key].chips[chip_idx].used += vm_colocada['longitud']
        
        # 2. Convertir a lista y asignar IDs globales
        hosts_list = sorted(hosts_dict.values(), key=lambda h: (h.az, h.id))
        for i, host in enumerate(hosts_list):
            host.id = i + 1
            for chip in host.chips:
                for placement in chip.items:
                    placement.host_id = host.id

        # --- Estandarización de Estadísticas ---
        # Se calculan las mismas métricas que CpsatPacker para consistencia.
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
            "status": "FEASIBLE", # SA siempre encuentra una si hay suficientes hosts
            "hosts": len(hosts_list),
            "total_used": total_used,
            "total_capacity": total_capacity,
            "utilization": util,
            "empty_pct": 1 - util,
            "per_az": {a: {**v, "utilization": (v["used"]/v["capacity"]) if v["capacity"] else 0.0}
                       for a, v in per_az.items()}
        }
        
        return hosts_list, stats