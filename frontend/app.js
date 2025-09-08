// Frontend JS (modular y comentado)
// - Ejecuta el endpoint /api/run-cpsat
// - STOP: usa AbortController para cancelar la petición en curso
// - Renderiza estadísticas y muestra/descarga el PNG generado

const $ = (s)=>document.querySelector(s);
const statsEl = $('#stats');
const layoutEl = $('#layout');
const btnRun = $('#btnRun');
const btnStop = $('#btnStop');
const btnDownload = $('#btnDownload');

let currentAbort = null;   // controlador para STOP

// Helpers de formato
const fmtPct = (x)=> (isFinite(x) ? (x*100).toFixed(1)+'%' : '—');
const safe   = (v)=> (v===0 || v ? v : '—');

btnRun.onclick = async () => {
  const file = $('#csvFile').files[0];
  if (!file) { alert('Sube un CSV.'); return; }

  // Preparación UI
  statsEl.innerHTML = '';
  layoutEl.innerHTML = '<i class="hint">Procesando…</i>';
  btnRun.disabled = true;
  btnStop.disabled = false;
  btnDownload.style.display = 'none';

  // Armar FormData
  const fd = new FormData();
  fd.append('file', file);
  fd.append('delimiter', $('#delimiter').value);
  fd.append('algo', $('#algo').value);
  // timeLimit se mantiene interno; si quieres, puedes exponerlo de nuevo

  // AbortController para STOP
  currentAbort = new AbortController();

  try {
    const res = await fetch('/api/run-cpsat', {
      method: 'POST',
      body: fd,
      signal: currentAbort.signal
    });
    const data = await res.json();

    if (!res.ok) {
      layoutEl.innerHTML = `<div class="error">${data.error || 'Error en /api/run-cpsat'}</div>`;
      if (data.stats) renderStats(data.stats);
      return;
    }

    // Mostrar PNG
    layoutEl.innerHTML = `<img id="imgLayout" alt="Acomodo" src="${data.image}"/>`;

    // Botón de descarga
    btnDownload.href = data.image;
    btnDownload.download = `acomodo_${(data.stats?.status||'OK').toLowerCase()}.png`;
    btnDownload.style.display = 'inline-block';

    // Stats
    renderStats(data.stats || {});
  } catch (err) {
    if (err.name === 'AbortError') {
      layoutEl.innerHTML = `<div class="error">Ejecución cancelada.</div>`;
    } else {
      layoutEl.innerHTML = `<div class="error">${err.message}</div>`;
    }
  } finally {
    btnRun.disabled = false;
    btnStop.disabled = true;
    currentAbort = null;
  }
};

// STOP: cancela la petición actual
btnStop.onclick = () => {
  if (currentAbort) currentAbort.abort();
};

// Render de estadísticas (las básicas se quedan; añadimos sugeridas)
function renderStats(s) {
  statsEl.innerHTML = `
    <div class="stat"><b>Estado</b><div>${safe(s.status)}</div></div>
    <div class="stat"><b>VMs</b><div>${safe(s.n_vms)}</div></div>
    <div class="stat"><b>Hosts</b><div>${safe(s.hosts)}</div></div>
    <div class="stat"><b>Capacidad</b><div>${safe(s.total_capacity)}</div></div>
    <div class="stat"><b>Usado</b><div>${safe(s.total_used)}</div></div>
    <div class="stat"><b>Utilización</b><div>${fmtPct(s.utilization)}</div></div>
    <div class="stat"><b>Sin Uso</b><div>${fmtPct(s.empty_pct)}</div></div>
  `;

  // Sugeridas: chips usados, util por host, histograma de huecos, AZs
  if (s.chips_used !== undefined) {
    statsEl.innerHTML += `<div class="stat"><b>Chips usados</b><div>${s.chips_used}</div></div>`;
  }
  if (s.host_utilization) {
    statsEl.innerHTML += `<div class="stat"><b>Utilización/host</b>
      <div>Promedio: ${fmtPct(s.host_utilization.avg)}<br>
           Máximo: ${fmtPct(s.host_utilization.max)}<br>
           Mínimo: ${fmtPct(s.host_utilization.min)}</div></div>`;
  }
  if (s.az_values && s.az_values.length) {
    statsEl.innerHTML += `<div class="stat"><b>AZ detectadas</b><div>${s.az_values.join(', ')}</div></div>`;
  }
  if (s.per_az) {
    for (const [az,v] of Object.entries(s.per_az)) {
      statsEl.innerHTML += `<div class="stat"><b>${az}</b>
        <div>hosts: ${safe(v.hosts)}<br>utilidad: ${fmtPct(v.utilization)}</div></div>`;
    }
  }
  // El histograma de huecos (opcional) lo podrías graficar con barras en una V2.
}
