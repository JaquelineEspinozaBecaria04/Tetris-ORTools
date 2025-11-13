import pandas as pd
import numpy as np
import io
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from typing import List, Dict, Any

# Constantes
NUMERO_CHIPS = 2
NUMERO_CORES = 20
col_info = ['# S. TOTAL', '# S. ZONA', 'SERVIDOR']

def generar_excel_visual_to(df_original: pd.DataFrame, site_name: str = "Optimizado") -> bytes:
    """Genera el archivo Excel visual a partir del DF de TO."""
    df = df_original.copy()
    diccionario_colores = generar_diccionario_colores(df)
    matriz = generar_matriz_con_length(df) # Aquí está el ajuste clave
    cols = [f'chip_{i}_{j}' for i in range(1, NUMERO_CHIPS + 1) for j in range(1, NUMERO_CORES + 1)] + ['AZ'] + col_info
    df_excel = obtener_df_final(matriz, cols)
    return generar_excel_bytes(site_name, df_excel, diccionario_colores)

def generar_diccionario_colores(df: pd.DataFrame) -> Dict[str, str]:
    temp = df[['VM', 'Color']].drop_duplicates(subset='VM')
    dicc = {row.VM: row.Color for row in temp.itertuples(index=False)}
    dicc['INFRA'] = '#FBE2D5'
    for vm in dicc:
        if pd.isna(dicc[vm]): dicc[vm] = "#808080"
    return dicc

def generar_matriz_con_length(df: pd.DataFrame) -> List[List[Any]]:
    # Ordenamos por HOST global
    if 'HOST' in df.columns:
        df_sorted = df.sort_values(by='HOST')
        unique_hosts = df_sorted['HOST'].unique()
    else:
        # Fallback si no existe HOST global
        unique_hosts = range(len(df))

    host_to_idx = {h: i for i, h in enumerate(unique_hosts)}
    
    # Matriz vacía
    total_cols = (NUMERO_CORES * NUMERO_CHIPS) + len(col_info) + 1
    matriz = [[np.nan for _ in range(total_cols)] for _ in range(len(unique_hosts))]

    for row in df.itertuples(index=False):
        # Obtener índice de fila
        host_val = getattr(row, 'HOST', None)
        idx_fila = host_to_idx.get(host_val)
        if idx_fila is None: continue

        # Obtener índice de columna (Start)
        try:
            idx_col = int(row.Start)
        except:
            continue
            
        # Guardar Tupla (Nombre, Longitud)
        matriz[idx_fila][idx_col] = (row.VM, row.Length)

        # Metadatos del final
        matriz[idx_fila][-4] = row.AZ
        matriz[idx_fila][-3] = row.HOST       # # S. TOTAL
        
        # --- AJUSTE CLAVE PARA TO ---
        # Si existe HOST_RELATIVO úsalo, si no, usa Host
        host_relativo = getattr(row, 'HOST_RELATIVO', getattr(row, 'Host', 0))
        matriz[idx_fila][-2] = host_relativo  # # S. ZONA
        
        host_chip_str = getattr(row, 'host_chip', f"{row.AZ} - {host_relativo}")
        matriz[idx_fila][-1] = host_chip_str

    return matriz

def obtener_df_final(matriz: List[List[Any]], columnas: List[str]) -> pd.DataFrame:
    df = pd.DataFrame(matriz, columns=columnas)
    if 'SERVIDOR' in df.columns:
        df['SERVIDOR'] = df['SERVIDOR'].replace(' ', 'INFRA')
    
    # Insertar separadores por AZ
    if not df.empty and 'AZ' in df.columns:
        df_az = df['AZ'].astype(str)
        cambios = df_az != df_az.shift()
        indices = df.index[cambios].tolist()[1:]
        for idx in reversed(indices):
            vacio = pd.DataFrame([{}], columns=df.columns)
            df = pd.concat([df.iloc[:idx], vacio, df.iloc[idx:]], ignore_index=True)

    # Reordenar: [INFO] ... [CHIPS]
    cols = df.columns
    cols_info = cols[-3:].tolist()
    cols_az = [cols[-4]]
    cols_chips = cols[:-4].tolist()
    new_order = cols_info + cols_chips[:20] + cols_az + cols_chips[20:]
    
    # Protección si las columnas no coinciden exactamente
    try:
        df = df[new_order]
    except:
        pass 
    return df

def generar_excel_bytes(titulo: str, df: pd.DataFrame, colores: Dict[str, str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Tetris"
    
    # Headers
    for c_idx, col in enumerate(df.columns, 1):
        val = col.split("_")[-1] if "chip_" in col else col
        ws.cell(row=2, column=c_idx, value=val)

    # Datos
    for r_idx, row in enumerate(df.itertuples(index=False), 3):
        for c_idx, val in enumerate(row, 1):
            if isinstance(val, tuple):
                ws.cell(row=r_idx, column=c_idx, value=val[0])
            else:
                ws.cell(row=r_idx, column=c_idx, value=val)

    # Estilos Básicos (Simplificados para rendimiento, igual que TA)
    fuente = Font(name="Aptos Narrow", size=11)
    align = Alignment(horizontal="center", vertical="center")
    borde = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    
    # Aplicar estilos y merge (Lógica idéntica a TA)
    offset = 3
    cols_list = df.columns.tolist()
    
    for i, row in enumerate(df.itertuples(index=False)):
        r_excel = i + offset
        # Fila separadora
        if all(pd.isna(x) or x == '' for x in row):
            ws.merge_cells(start_row=r_excel, end_row=r_excel, start_column=1, end_column=df.shape[1])
            cell = ws.cell(r_excel, 1, value="INFRA")
            cell.fill = PatternFill("solid", fgColor="000000")
            cell.font = Font(color="FFFFFF")
            continue

        for j, val in enumerate(row):
            if "chip_" in cols_list[j] and isinstance(val, tuple):
                vm, length = val
                color = colores.get(vm, "808080").replace("#", "")
                if int(length) > 0:
                    c_end = j + 1 + int(length) - 1
                    if c_end <= df.shape[1]:
                        if int(length) > 1:
                            ws.merge_cells(start_row=r_excel, end_row=r_excel, start_column=j+1, end_column=c_end)
                        ws.cell(r_excel, j+1).fill = PatternFill("solid", fgColor=color)
            elif cols_list[j] == "AZ": # Columna AZ
                 ws.cell(r_excel, j+1).fill = PatternFill("solid", fgColor="B5E6A2")

    # Título
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=df.shape[1])
    ws.cell(1, 1, value=f"TETRIS OPTIMIZADO - {titulo}").font = Font(size=16, bold=True, color="FF0000")

    with io.BytesIO() as bio:
        wb.save(bio)
        return bio.getvalue()