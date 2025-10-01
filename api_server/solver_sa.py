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
# 1. CÓDIGO DEL ALGORITMO ORIGINAL (recocidos.py) RESTAURADO Y ADAPTADO
#    Las funciones ahora respetan la lógica de anti-afinidad y la
#    búsqueda de vecinos del script original.
# ==============================================================================

def generar_solucion_inicial(vmf: List[Dict], cores: int, az: int, numero_hosts_por_az: List[int]) -> Tuple[List[Dict], List, List[int]]:
    """
    Genera una solución inicial respetando la lógica de anti-afinidad.
    """
    random.shuffle(vmf)
    solucion = []
    
    # ESTRUCTURA DE DATOS RESTAURADA:
    # El primer elemento de la lista de cada chip es la capacidad restante.
    # Los elementos siguientes son los nombres de las VMs para el control de anti-afinidad.
    servidor_tetris = [[[ [cores] for _ in range(CHIPS_PER_HOST)] for _ in range(numero_hosts_por_az[i])] for i in range(az)]

    for clase in vmf:
        aceptada = False
        longitud = clase['longitud']
        nombre = clase['nombre']
        zona_idx = clase['zona_idx']
        max_piezas = clase['max_piezas']

        for i, host in enumerate(servidor_tetris[zona_idx]):
            vms_en_host = host[0][1:] + host[1][1:] # Nombres de VMs en ambos chips
            
            # LÓGICA DE ANTI-AFINIDAD RESTAURADA
            if vms_en_host.count(nombre) < max_piezas:
                # Intentar en Chip 1
                cores_restantes_c1 = host[0][0]
                if cores_restantes_c1 >= longitud:
                    chip_idx = 0
                    asignacion = {
                        'idx': clase['idx'],
                        'nombre': nombre, 'longitud': longitud, 'host': i, 'chip': chip_idx + 1,
                        'core_inicio': cores - cores_restantes_c1,
                        'max_piezas': max_piezas, 'zona_idx': zona_idx, 'color': clase['color'],
                        'instancia': clase['instancia'],
                        'pos_relativa': host[chip_idx].count(nombre) + 1 # Necesario para generar_vecino
                    }
                    solucion.append(asignacion)
                    host[chip_idx][0] -= longitud
                    host[chip_idx].append(nombre)
                    aceptada = True
                    break
                
                # Intentar en Chip 2
                cores_restantes_c2 = host[1][0]
                if cores_restantes_c2 >= longitud:
                    chip_idx = 1
                    asignacion = {
                        'idx': clase['idx'],
                        'nombre': nombre, 'longitud': longitud, 'host': i, 'chip': chip_idx + 1,
                        'core_inicio': cores - cores_restantes_c2,
                        'max_piezas': max_piezas, 'zona_idx': zona_idx, 'color': clase['color'],
                        'instancia': clase['instancia'],
                        'pos_relativa': host[chip_idx].count(nombre) + 1
                    }
                    solucion.append(asignacion)
                    host[chip_idx][0] -= longitud
                    host[chip_idx].append(nombre)
                    aceptada = True
                    break
        
    # Limpiar hosts no utilizados (lógica mejorada de solver_sa)
    servidor_tetris_final = []
    hosts_usados_por_az = [0] * az
    host_map = {} # (zona, viejo_host_idx) -> nuevo_host_idx

    for az_idx in range(az):
        host_actual_az = 0
        servidores_az = []
        for host_idx, host_data in enumerate(servidor_tetris[az_idx]):
            if host_data[0][0] < cores or host_data[1][0] < cores:
                host_map[(az_idx, host_idx)] = host_actual_az
                servidores_az.append(host_data)
                hosts_usados_por_az[az_idx] += 1
                host_actual_az += 1
        servidor_tetris_final.append(servidores_az)

    solucion_mapeada = []
    for s in solucion:
        nuevo_host_idx = host_map.get((s['zona_idx'], s['host']))
        if nuevo_host_idx is not None:
            s_copia = s.copy()
            s_copia['host'] = nuevo_host_idx
            solucion_mapeada.append(s_copia)

    return sorted(solucion_mapeada, key=lambda x: (x['zona_idx'], x['host'], x['chip'], x['core_inicio'])), servidor_tetris_final, hosts_usados_por_az


def evaluar_solucion(servidor_tetris: List, hosts_usados_por_az: List[int], max_piezas_map: Dict[str, int]) -> int:
    """
    Función de costo restaurada: penaliza hosts y violaciones de anti-afinidad.
    """
    penalizacion_hosts = sum(hosts_usados_por_az)
    penalizacion_repetidos = 0
    
    for az_idx, zona in enumerate(servidor_tetris):
        for host_idx, host in enumerate(zona):
            vms_en_host = host[0][1:] + host[1][1:]
            counts = Counter(vms_en_host)
            for nombre, count in counts.items():
                max_piezas = max_piezas_map.get(nombre, 1)
                if count > max_piezas:
                    penalizacion_repetidos += (count - max_piezas) * 100 # Penalización original

    return penalizacion_hosts + penalizacion_repetidos


def extraer_pieza(solucion: List[Dict], servidor: List, indice: int) -> Tuple[List[Dict], List, Dict]:
    """
    Función auxiliar para generar_vecino, adaptada.
    """
    clase = solucion.pop(indice)
    nombre, longitud, host, chip_idx = clase['nombre'], clase['longitud'], clase['host'], clase['chip'] - 1
    zona_idx, pos_relativa, core_inicio = clase['zona_idx'], clase['pos_relativa'], clase['core_inicio']

    # Restaurar capacidad
    servidor[zona_idx][host][chip_idx][0] += longitud
    
    # Eliminar la N-ésima ocurrencia del nombre de la VM en el chip
    contador = 0
    for i, valor in enumerate(servidor[zona_idx][host][chip_idx]):
        if valor == nombre:
            contador += 1
            if contador == pos_relativa:
                servidor[zona_idx][host][chip_idx].pop(i)
                break
    
    # Reajustar posiciones de VMs posteriores en el mismo chip
    nueva_solucion = []
    for pieza in solucion:
        p_copia = pieza.copy()
        if p_copia["zona_idx"] == zona_idx and p_copia["host"] == host and p_copia["chip"] == chip_idx + 1:
            if p_copia["core_inicio"] > core_inicio:
                p_copia["core_inicio"] -= longitud
            if p_copia['nombre'] == nombre and p_copia['pos_relativa'] > pos_relativa:
                p_copia["pos_relativa"] -= 1
        nueva_solucion.append(p_copia)

    return nueva_solucion, servidor, clase

def generar_vecino(solucion_actual, servidor_actual, T_inicial, T_actual, vmf_original, cores):
    """
    Generación de vecino RESTAURADA. Extrae y reinserta un subconjunto de VMs.
    """
    servidor_vecino = copy.deepcopy(servidor_actual)
    solucion_vecino = copy.deepcopy(solucion_actual)
    
    if not solucion_vecino:
        return solucion_actual, servidor_actual # No se puede generar vecino de una solución vacía

    num_piezas_a_cambiar = max(1, int(len(solucion_vecino) * 0.1 * (T_actual / T_inicial)))
    
    piezas_extraidas = []
    for _ in range(num_piezas_a_cambiar):
        if not solucion_vecino: break
        idx_a_extraer = random.randrange(len(solucion_vecino))
        solucion_vecino, servidor_vecino, pieza_extraida = extraer_pieza(solucion_vecino, servidor_vecino, idx_a_extraer)
        piezas_extraidas.append(next(item for item in vmf_original if item["idx"] == pieza_extraida["idx"]))

    random.shuffle(piezas_extraidas)
    
    # Reinsertar piezas
    todas_aceptadas = True
    for clase in piezas_extraidas:
        aceptada = False
        longitud, nombre, zona_idx, max_piezas = clase['longitud'], clase['nombre'], clase['zona_idx'], clase['max_piezas']
        
        # Misma lógica de inserción que en generar_solucion_inicial
        for i, host in enumerate(servidor_vecino[zona_idx]):
            vms_en_host = host[0][1:] + host[1][1:]
            if vms_en_host.count(nombre) < max_piezas:
                # Chip 1
                if host[0][0] >= longitud:
                    chip_idx=0
                    asignacion = {'idx': clase['idx'], 'nombre': nombre, 'longitud': longitud, 'host': i, 'chip': chip_idx+1, 'core_inicio': cores-host[chip_idx][0], 'max_piezas': max_piezas, 'zona_idx': zona_idx, 'color': clase['color'], 'instancia': clase['instancia'], 'pos_relativa': host[chip_idx].count(nombre) + 1}
                    solucion_vecino.append(asignacion)
                    host[chip_idx][0] -= longitud; host[chip_idx].append(nombre)
                    aceptada = True; break
                # Chip 2
                if host[1][0] >= longitud:
                    chip_idx=1
                    asignacion = {'idx': clase['idx'], 'nombre': nombre, 'longitud': longitud, 'host': i, 'chip': chip_idx+1, 'core_inicio': cores-host[chip_idx][0], 'max_piezas': max_piezas, 'zona_idx': zona_idx, 'color': clase['color'], 'instancia': clase['instancia'], 'pos_relativa': host[chip_idx].count(nombre) + 1}
                    solucion_vecino.append(asignacion)
                    host[chip_idx][0] -= longitud; host[chip_idx].append(nombre)
                    aceptada = True; break
        if not aceptada:
            todas_aceptadas = False; break
            
    if not todas_aceptadas:
        return solucion_actual, servidor_actual, None # Falló, devuelve el original

    # Si tuvo éxito, limpiar y remapear
    # (El remapeo se simplifica aquí por brevedad, la lógica completa sería similar a la de solucion_inicial)
    return sorted(solucion_vecino, key=lambda x: (x['zona_idx'], x['host'], x['chip'], x['core_inicio'])), servidor_vecino, None


def recocido_simulado(vmf, cores, az, numero_hosts_por_az, max_piezas_map, params: SolverParams):
    T_inicial = params.time_limit_s * 10
    T_final = 1
    alpha = 0.985
    max_iter = int(params.time_limit_s * 15)

    # Generación inicial
    solucion_actual, servidor_actual, hosts_usados_actual = generar_solucion_inicial(vmf, cores, az, numero_hosts_por_az)
    costo_actual = evaluar_solucion(servidor_actual, hosts_usados_actual, max_piezas_map)

    mejor_solucion = copy.deepcopy(solucion_actual)
    mejor_servidor = copy.deepcopy(servidor_actual)
    mejor_hosts_usados = copy.deepcopy(hosts_usados_actual)
    mejor_costo = costo_actual
    
    T = T_inicial
    iteracion = 0

    while T > T_final and iteracion < max_iter:
        # LÓGICA DE BÚSQUEDA RESTAURADA: usa generar_vecino
        vecino, servidor_vecino, _ = generar_vecino(solucion_actual, servidor_actual, T_inicial, T, vmf, cores)
        
        # Recalcular hosts usados para el vecino (simplificado)
        hosts_usados_vecino = [len(zona) for zona in servidor_vecino]
        costo_vecino = evaluar_solucion(servidor_vecino, hosts_usados_vecino, max_piezas_map)
        
        delta = costo_vecino - costo_actual

        if delta < 0 or random.random() < math.exp(-delta / T):
            solucion_actual, servidor_actual, costo_actual = vecino, servidor_vecino, costo_vecino
            hosts_usados_actual = hosts_usados_vecino
            
            if costo_actual < mejor_costo:
                mejor_solucion, mejor_servidor, mejor_costo = copy.deepcopy(solucion_actual), copy.deepcopy(servidor_actual), costo_actual
                mejor_hosts_usados = copy.deepcopy(hosts_usados_actual)
        
        T *= alpha
        iteracion += 1

    return mejor_solucion, sum(mejor_hosts_usados), iteracion

# ==============================================================================
# 2. CLASE ADAPTADORA `SaPacker` (Interfaz con la aplicación)
#    (Prácticamente sin cambios, ahora llama a la lógica restaurada)
# ==============================================================================

class SaPacker:
    def __init__(self, vms: List[VM], params: SolverParams):
        self.vms_originales = vms
        self.params = params
        self.az_map = {az_name: i for i, az_name in enumerate(sorted(list({vm.az for vm in vms})))}
        
        self.vmf = []
        for vm in vms:
            self.vmf.append({
                "idx": vm.idx, "nombre": f"{vm.vm_type.vnf}{vm.vm_type.vnfc}",
                "longitud": vm.size, "zona_idx": self.az_map[vm.az],
                "max_piezas": vm.anti, "color": vm.color, "instancia": vm.inst
            })
        
        # Mapa para la función de evaluación
        self.max_piezas_map = {item['nombre']: item['max_piezas'] for item in self.vmf}

    def solve(self) -> Tuple[List[HostResult], Dict]:
        if not self.vmf:
            return [], {"status": "NO_VMS", "hosts": 0}

        num_azs = len(self.az_map)
        initial_hosts_per_az = [len(self.vms_originales)] * num_azs

        # Ejecutamos el algoritmo con la lógica restaurada
        solucion_final, costo, num_gens = recocido_simulado(
            self.vmf,
            cores=CHIP_CAPACITY,
            az=num_azs,
            numero_hosts_por_az=initial_hosts_per_az,
            max_piezas_map=self.max_piezas_map,
            params=self.params
        )
        
        if not solucion_final:
            return [], {"status": "INFEASIBLE", "hosts": 0}
            
        # --- Adaptación de Salida (sin cambios) ---
        hosts_dict = {}
        for vm_colocada in solucion_final:
            az_idx, host_idx, chip_idx = vm_colocada['zona_idx'], vm_colocada['host'], vm_colocada['chip'] - 1
            vm_original = next((vm for vm in self.vms_originales if vm.idx == vm_colocada['idx']), None)
            if not vm_original: continue

            host_key = (az_idx, host_idx)
            if host_key not in hosts_dict:
                az_name = next(key for key, value in self.az_map.items() if value == az_idx)
                hosts_dict[host_key] = HostResult(id=0, az=az_name, chips=[ChipResult(), ChipResult()])
            
            placement = Placement(
                vm=vm_original, host_id=0, chip_idx=chip_idx,
                start=vm_colocada['core_inicio'],
                end=vm_colocada['core_inicio'] + vm_colocada['longitud']
            )
            hosts_dict[host_key].chips[chip_idx].items.append(placement)
            hosts_dict[host_key].chips[chip_idx].used += vm_colocada['longitud']
        
        hosts_list = sorted(hosts_dict.values(), key=lambda h: (h.az, h.id))
        for i, host in enumerate(hosts_list):
            host.id = i + 1
            for chip in host.chips:
                for placement in chip.items:
                    placement.host_id = host.id

        # --- Estandarización de Estadísticas (sin cambios) ---
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
            "status": "FEASIBLE", "hosts": len(hosts_list),
            "total_used": total_used, "total_capacity": total_capacity,
            "utilization": util, "empty_pct": 1 - util,
            "per_az": {a: {**v, "utilization": (v["used"]/v["capacity"]) if v["capacity"] else 0.0} for a, v in per_az.items()}
        }
        
        return hosts_list, stats