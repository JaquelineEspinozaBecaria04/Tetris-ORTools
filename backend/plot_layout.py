"""
Render de layout con Matplotlib:
- Host outline con borde grueso
- Chip outline con borde medio
- Hatch para [17..20)
- Tipografías VNF/VNFC más grandes/bold con contraste automático (negro/blanco)
- Etiqueta izquierda: "acumulado_global - AZxx - acumulado_en_AZ"
- Corrección del último bloque de AZ
"""

from __future__ import annotations
import matplotlib
matplotlib.use("Agg")  # usar backend sin GUI en servidores/headless
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Constantes de capacidad (coherentes con el solver)
CHIP_CAPACITY = 17
CHIP_TOTAL = 20
CHIPS_PER_HOST = 2
HOST_CAPACITY = CHIP_CAPACITY * CHIPS_PER_HOST

def _darken(hex_color: str, factor: float = 0.55) -> str:
    """Oscurece un color hex para usar en el borde."""
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
    r = max(0, min(255, int(r*factor)))
    g = max(0, min(255, int(g*factor)))
    b = max(0, min(255, int(b*factor)))
    return f"#{r:02x}{g:02x}{b:02x}"

def _text_contrast(hex_color: str) -> str:
    """Devuelve '#0b1020' (oscuro) o '#ffffff' (claro) según luminancia del color de fondo."""
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16)/255.0; g = int(h[2:4], 16)/255.0; b = int(h[4:6], 16)/255.0
    # luminancia percibida
    L = 0.2126*r + 0.7152*g + 0.0722*b
    return "#0b1020" if L > 0.6 else "#ffffff"

def render_layout_png(hosts, title: str = "", dpi: int = 170, stats: dict | None = None) -> bytes:
    """
    Dibuja el layout:
      - Ordenado por AZ y luego id.
      - Se agrupan AZ consecutivas y se separan visualmente.
      - Para cada host se pinta un rectángulo envolvente (chip A+B) con borde grueso.
      - Se devuelve PNG en bytes.
    """
    # Ordenar por AZ y id
    hosts_sorted = sorted(hosts, key=lambda H: (H.az, H.id))
    rows = len(hosts_sorted)

    # Agrupar por AZ
    groups: dict[str, list] = {}
    for h in hosts_sorted:
        groups.setdefault(h.az, []).append(h)
    az_order = list(groups.keys())  # ya están en orden por el sort de arriba

    # Parámetros de dibujo
    az_band_w = 5.0           # más ancho para la leyenda “global - AZ - local”
    gap_between_az = 1.0      # separación al cambiar de AZ
    chip_gap = 2.0            # separación entre chips A y B
    host_border_lw = 2.0      # borde host más grueso
    chip_border_lw = 1.4      # borde chip medio
    font_vm = 8.5             # fuente para VNF/VNFC (más grande)
    font_host = 10

    # Calcular alto de la figura con separación por zonas (no restamos al final -> arregla última AZ)
    rows_total = rows + int(max(0, len(az_order) - 1) * gap_between_az)
    fig_h = max(3.0, 0.85 * rows_total + 1.8)
    total_width = az_band_w + CHIPS_PER_HOST * CHIP_TOTAL + chip_gap

    fig, ax = plt.subplots(figsize=(16, fig_h), dpi=dpi)

    # Header 1..20 por chip
    header_y = rows_total + 0.6
    for c_idx in range(CHIPS_PER_HOST):
        x0 = az_band_w + c_idx * (CHIP_TOTAL + chip_gap)
        for t in range(1, CHIP_TOTAL+1):
            ax.text(x0 + (t-0.5), header_y, str(t), ha='center', va='bottom', fontsize=8, color="#4b5563")
        # hatch arriba de los reservados
        ax.add_patch(
            patches.Rectangle((x0 + CHIP_CAPACITY, header_y-0.3),
                              CHIP_TOTAL-CHIP_CAPACITY, 0.25,
                              linewidth=0, facecolor='none', hatch='//', edgecolor='#94a3b8', alpha=0.5)
        )

    # Dibujo por bloques de AZ
    y = rows_total - 1
    global_count = 0
    for az in az_order:
        local_count = 0
        for H in groups[az]:
            global_count += 1
            local_count += 1

            # Banda izquierda de AZ + contador "global - AZxx - local"
            ax.add_patch(patches.Rectangle((-az_band_w, y), az_band_w, 0.8,
                                           facecolor='#cfe9b6', edgecolor='none'))
            ax.text(-az_band_w/2, y+0.4, f"{global_count} - {az} - {local_count}",
                    va='center', ha='center', fontsize=font_host, fontweight='bold', color="#0b3d1a")

            # HOST OUTLINE (rectángulo que envuelve ambos chips)
            host_x0 = az_band_w
            host_w = CHIPS_PER_HOST * CHIP_TOTAL + chip_gap
            ax.add_patch(patches.Rectangle((host_x0, y), host_w, 0.8,
                                           linewidth=host_border_lw, edgecolor='#8f9bb3', facecolor='none'))

            # Cada chip (A y B)
            for c_idx, chip in enumerate(H.chips):
                x0 = az_band_w + c_idx * (CHIP_TOTAL + chip_gap)
                # marco de chip 20
                ax.add_patch(patches.Rectangle((x0, y), CHIP_TOTAL, 0.8,
                                               linewidth=chip_border_lw, edgecolor='#e5e7eb', facecolor='none'))
                # hatch reservados [17,20)
                ax.add_patch(patches.Rectangle((x0 + CHIP_CAPACITY, y), CHIP_TOTAL-CHIP_CAPACITY, 0.8,
                                               linewidth=0, facecolor='none', hatch='//', edgecolor='#94a3b8'))
                # rejilla
                for t in range(1, CHIP_TOTAL):
                    ax.plot([x0 + t, x0 + t], [y, y+0.8], linewidth=0.25, color='#475569', alpha=0.55)
                # piezas
                for plc in chip.items:
                    xx = x0 + plc.start
                    fill = plc.vm.color
                    edge = _darken(fill)
                    txt_color = _text_contrast(fill)
                    ax.add_patch(patches.Rectangle((xx, y), plc.vm.size, 0.8, linewidth=1.6,
                                                   edgecolor=edge, facecolor=fill, joinstyle='round'))
                    # VNF + VNFC en dos líneas, más grande y en negritas
                    ax.text(xx + plc.vm.size/2, y+0.43, plc.vm.vm_type.vnf, va='center', ha='center',
                            fontsize=font_vm, fontweight='bold', color=txt_color)
                    ax.text(xx + plc.vm.size/2, y+0.19, plc.vm.vm_type.vnfc, va='center', ha='center',
                            fontsize=font_vm-1, fontweight='bold', color=txt_color)

            y -= 1
        # separación entre zonas (si no es la última)
        if az != az_order[-1]:
            y -= gap_between_az
            ax.plot([-az_band_w, total_width], [y + gap_between_az/2, y + gap_between_az/2],
                    linestyle='-', linewidth=1.2, color='#9aa5b1', alpha=0.8)

    # Ejes
    ax.set_xlim(-az_band_w, total_width + 0.5)
    ax.set_ylim(-0.8, header_y + 0.8)
    ax.set_yticks([]); ax.set_xticks([])

    # Título
    if not title:
        title = f"Acomodo final por host (CP-SAT). Hosts = {len(hosts_sorted)} | Capacidad usable/host = {HOST_CAPACITY} (17x2)"
        if stats:
            # si hay % utilización úsalo en el título
            util = stats.get("utilization", None)
            if util is not None:
                title += f" | Utilización: {util:.1%}"
    ax.set_title(title)
    fig.tight_layout()

    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()
