# backend/plot_layout.py
from __future__ import annotations
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Constantes de dibujo (coinciden con tu modelo)
CHIP_CAPACITY = 17
CHIP_TOTAL = 20
CHIPS_PER_HOST = 2
HOST_CAPACITY = CHIP_CAPACITY * CHIPS_PER_HOST

def _darken(hex_color: str, factor: float = 0.55) -> str:
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16); g = int(h[2:4], 16); b = int(h[4:6], 16)
    r = max(0, min(255, int(r*factor)))
    g = max(0, min(255, int(g*factor)))
    b = max(0, min(255, int(b*factor)))
    return f"#{r:02x}{g:02x}{b:02x}"

def render_layout_png(hosts, title: str = "", dpi: int = 170) -> bytes:
    from matplotlib import pyplot as plt, patches
    hosts_sorted = sorted(hosts, key=lambda H: (H.az, H.id))
    rows = len(hosts_sorted)

    az_band_w = 4.0
    gap_between_az = 0.6

    az_order = []
    if rows:
        last = None
        for H in hosts_sorted:
            if H.az != last:
                az_order.append(H.az)
                last = H.az

    fig_h = 2.8 if rows == 0 else max(3.0, 0.8*rows + 0.6*len(az_order))
    total_width = az_band_w + CHIPS_PER_HOST*CHIP_TOTAL + 2
    fig, ax = plt.subplots(figsize=(16, fig_h), dpi=dpi)

    if rows == 0:
        ax.text(0.5, 0.5, "Sin hosts para mostrar", transform=ax.transAxes,
                ha="center", va="center", fontsize=14, color="#64748b")
        ax.axis("off")
    else:
        # Header
        header_y = rows + 0.6
        for c_idx in range(CHIPS_PER_HOST):
            x0 = az_band_w + c_idx * (CHIP_TOTAL + 2)
            for t in range(1, CHIP_TOTAL+1):
                ax.text(x0 + (t-0.5), header_y, str(t), ha='center', va='bottom', fontsize=8, color="#4b5563")
            ax.add_patch(patches.Rectangle((x0 + CHIP_CAPACITY, header_y-0.3),
                                           CHIP_TOTAL-CHIP_CAPACITY, 0.25, linewidth=0,
                                           facecolor='none', hatch='//', edgecolor='#94a3b8', alpha=0.5))
        # Filas
        y = rows - 1
        last_az = None
        for H in hosts_sorted:
            if last_az is not None and H.az != last_az:
                y -= gap_between_az
                ax.plot([-az_band_w, total_width], [y+gap_between_az/2, y+gap_between_az/2],
                        linestyle='-', linewidth=1.0, color='#888888', alpha=0.7)
            ax.add_patch(patches.Rectangle((-az_band_w, y), az_band_w, 0.8, facecolor='#cfe9b6', edgecolor='none'))
            ax.text(-az_band_w/2, y+0.4, H.az, va='center', ha='center', fontsize=10, fontweight='bold')
            ax.text(-0.5, y+0.4, f"{H.az}-H{H.id:02d}", va='center', ha='right', fontsize=9, color="#475569")

            for c_idx, chip in enumerate(H.chips):
                x0 = az_band_w + c_idx * (CHIP_TOTAL + 2)
                ax.add_patch(patches.Rectangle((x0, y), CHIP_TOTAL, 0.8, linewidth=1.2, edgecolor='#e5e7eb', facecolor='none'))
                ax.add_patch(patches.Rectangle((x0 + CHIP_CAPACITY, y), CHIP_TOTAL-CHIP_CAPACITY, 0.8,
                                               linewidth=0, facecolor='none', hatch='//', edgecolor='#94a3b8'))
                for t in range(1, CHIP_TOTAL):
                    ax.plot([x0 + t, x0 + t], [y, y+0.8], linewidth=0.25, color='#475569', alpha=0.55)
                for plc in chip.items:
                    xx = x0 + plc.start
                    ax.add_patch(patches.Rectangle((xx, y), plc.vm.size, 0.8, linewidth=1.5,
                                                   edgecolor=_darken(plc.vm.color), facecolor=plc.vm.color, joinstyle='round'))
                    ax.text(xx + plc.vm.size/2, y+0.4, f"{plc.vm.vm_type.vnf}\n{plc.vm.vm_type.vnfc}",
                            va='center', ha='center', fontsize=7, color='#0b1020')

            last_az = H.az
            y -= 1

        ax.set_xlim(-az_band_w, total_width + 0.5)
        ax.set_ylim(-0.5, header_y + 0.8)
        ax.set_yticks([]); ax.set_xticks([])

    if not title:
        title = f"Acomodo final por host (CP-SAT). Hosts = {rows} | Capacidad usable/host = {HOST_CAPACITY} (17x2)"
    ax.set_title(title)
    fig.tight_layout()

    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.read()
