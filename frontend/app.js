// Frontend JS
// - Llama /api/run-cpsat
// - STOP con AbortController
// - Muestra HTML interactivo (iframe) o PNG (fallback)
// - Descarga CSV sólo si backend devolvió URL válida

const $ = (s) => document.querySelector(s);

// helper para leer valores de inputs/selector
function getValue(sel, fallback = "") {
  const el = document.querySelector(sel);
  return el ? el.value : fallback;
}

function fitIframeToContent(iframe) {
  try {
    const doc = iframe.contentDocument || iframe.contentWindow.document;
    const h = Math.max(
      doc.documentElement ? doc.documentElement.scrollHeight : 0,
      doc.body ? doc.body.scrollHeight : 0
    );
    iframe.style.height = h + "px";
    iframe.style.width = "100%";
  } catch (e) {}
}


const statsEl        = $("#stats");
const layoutEl       = $("#layout");
const btnRun         = $("#btnRun");
const btnStop        = $("#btnStop");
const btnDownload    = $("#btnDownload");     // PNG
const btnDownloadCSV = $("#btnDownloadCSV");  // CSV

let currentRefitHandler = null;

let currentAbort = null;

const fmtPct = (x) => (isFinite(x) ? (x * 100).toFixed(1) + "%" : "—");
const safe    = (v) => (v === 0 || v ? v : "—");

function hideDownloads() {
  if (btnDownload) {
    btnDownload.style.display = "none";
    btnDownload.removeAttribute("href");
  }
  if (btnDownloadCSV) {
    btnDownloadCSV.style.display = "none";
    btnDownloadCSV.removeAttribute("href");
    btnDownloadCSV.removeAttribute("download");
    btnDownloadCSV.dataset.ready = "0";
  }
}
function showCsv(url, filename) {
  if (!btnDownloadCSV) return;
  if (url) {
    btnDownloadCSV.href = url;
    btnDownloadCSV.download = filename || "tetris.csv";
    btnDownloadCSV.dataset.ready = "1";
    btnDownloadCSV.style.display = "inline-block";
  } else {
    btnDownloadCSV.dataset.ready = "0";
    btnDownloadCSV.style.display = "none";
  }
}

// Bloquea descargas “vacías”
if (btnDownloadCSV) {
  btnDownloadCSV.addEventListener("click", (e) => {
    if (btnDownloadCSV.dataset.ready !== "1" || !btnDownloadCSV.href) {
      e.preventDefault();
      e.stopPropagation();
    }
  });
}

// estado inicial
hideDownloads();

btnRun.onclick = async () => {
  const file = $("#csvFile")?.files?.[0];
  if (!file) { alert("Sube un CSV."); return; }

  // UI
  statsEl.innerHTML = "";
  layoutEl.innerHTML = '<i class="hint">Procesando…</i>';
  btnRun.disabled = true;
  btnStop.disabled = false;
  hideDownloads();

  // FormData
  const fd = new FormData();
  fd.append("file", file);
  fd.append("delimiter", getValue("#delimiter", ""));
  fd.append("algo", getValue("#algo", "cpsat2"));
  fd.append("imageEngine", getValue("#imageEngine", "plotly"));
  fd.append("outputFormat", getValue("#outputFormat", "html")); // 'html' | 'png' | 'both'
  fd.append("includeTable", "true");

  // AbortController
  currentAbort = new AbortController();

  try {
    const res = await fetch("/api/run-cpsat", {
      method: "POST",
      body: fd,
      signal: currentAbort.signal,
    });

    const contentType = res.headers.get("content-type") || "";
    const text = await res.text();

    let data;
    if (contentType.includes("application/json")) {
      try { data = JSON.parse(text); }
      catch {
        layoutEl.innerHTML = `<div class="error">Respuesta JSON inválida: ${text.slice(0, 200)}</div>`;
        return;
      }
    } else {
      layoutEl.innerHTML = `<div class="error">Respuesta no-JSON (${res.status} ${res.statusText}): ${text.slice(0, 200)}</div>`;
      return;
    }

    if (!res.ok) {
      layoutEl.innerHTML = `<div class="error">${(data && data.error) || "Error en /api/run-cpsat"}</div>`;
      if (data && data.stats) renderStats(data.stats);
      hideDownloads();
      return;
    }

    // ----- Render del resultado (HTML interactivo > PNG) -----
    const htmlUrl = (data && typeof data.html_url === "string" && data.html_url) ? data.html_url : null;
    const pngData = (data && typeof data.image === "string" && data.image.startsWith("data:image/")) ? data.image : null;

    if (htmlUrl) {
      layoutEl.innerHTML = `
          <div class="html-wrapper">
            <iframe id="htmlLayout" class="html-frame" src="${htmlUrl}" loading="lazy" referrerpolicy="no-referrer"></iframe>
          </div>`;

        const ifr = document.getElementById("htmlLayout");

        if (currentRefitHandler) {
          window.removeEventListener("resize", currentRefitHandler);
          currentRefitHandler = null;
        }
        const refit = () => fitIframeToContent(ifr);

        ifr.addEventListener("load", () => {
          refit();
          setTimeout(refit, 50);
          setTimeout(refit, 250);
          setTimeout(refit, 500);
        });

        currentRefitHandler = refit;
        window.addEventListener("resize", currentRefitHandler, { passive: true });
    } else if (pngData) {
      layoutEl.innerHTML = `<img id="imgLayout" alt="Acomodo" src="${pngData}"/>`;
    } else {
      layoutEl.innerHTML = `<div class="error">No se recibió ni <code>html_url</code> ni <code>image</code> del backend.</div>`;
    }

    // Descarga PNG (solo si hay PNG)
    if (btnDownload && pngData) {
      btnDownload.href = pngData;
      const status = (data.stats && data.stats.status) ? String(data.stats.status).toLowerCase() : "ok";
      btnDownload.download = `acomodo_${status}.png`;
      btnDownload.style.display = "inline-block";
    }

    // Descarga CSV
    if (data.table && data.table.url) {
      showCsv(data.table.url, data.table.filename);
    } else {
      showCsv(null);
    }

    renderStats(data.stats || {});
  } catch (err) {
    layoutEl.innerHTML = (err?.name === "AbortError")
      ? `<div class="error">Ejecución cancelada.</div>`
      : `<div class="error">${err.message}</div>`;
    hideDownloads();
  } finally {
    btnRun.disabled = false;
    btnStop.disabled = true;
    currentAbort = null;
  }
};

btnStop.onclick = () => { if (currentAbort) currentAbort.abort(); };

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
    statsEl.innerHTML += `<div class="stat"><b>AZ detectadas</b><div>${s.az_values.join(", ")}</div></div>`;
  }
  if (s.per_az) {
    for (const [az, v] of Object.entries(s.per_az)) {
      statsEl.innerHTML += `<div class="stat"><b>${az}</b>
        <div>hosts: ${safe(v.hosts)}<br>utilidad: ${fmtPct(v.utilization)}</div></div>`;
    }
  }
}
