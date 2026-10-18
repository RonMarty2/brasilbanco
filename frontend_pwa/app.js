// ========================================================
// LÓGICA PRINCIPAL FRONTEND PWA - REMESAS BRASIL ⇄ BOLIVIA
// ========================================================

const API_BASE = window.location.origin.includes("localhost") || window.location.origin.includes("127.0.0.1") || window.location.origin.includes("192.168")
  ? window.location.origin
  : "http://localhost:8000";

// Estado global de la aplicación
const AppState = {
  grupos: [],
  grupoSeleccionado: null,
  voucherActual: null,
  diagnosticoActual: null,
  depositoSeleccionadoId: null,
  modoOperacion: "AUTOMATICO",
  archivoGuardadoPath: "",
  voucherPendienteEditandoId: null
};

// ========================================================
// INICIALIZACIÓN Y SERVICE WORKER
// ========================================================
document.addEventListener("DOMContentLoaded", () => {
  initServiceWorker();
  initTabs();
  cargarGruposWhatsApp();
  initVoucherUpload();
  initActionButtons();
  cargarEstadisticas();
  cargarPendientes();
  cargarDepositosLibres();
});

function initServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/pwa/sw.js")
      .then(() => console.log("Service Worker PWA registrado exitosamente"))
      .catch((err) => console.log("Fallo registro Service Worker:", err));
  }
}

// ========================================================
// NOTIFICACIONES TOAST
// ========================================================
function showToast(mensaje, tipo = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  
  let bgClass = "bg-slate-900 border-slate-700 text-slate-200";
  let icon = "ℹ️";
  if (tipo === "success") {
    bgClass = "bg-emerald-950 border-emerald-500/50 text-emerald-300";
    icon = "✅";
  } else if (tipo === "warning") {
    bgClass = "bg-amber-950 border-amber-500/50 text-amber-300";
    icon = "⚠️";
  } else if (tipo === "error") {
    bgClass = "bg-rose-950 border-rose-500/50 text-rose-300";
    icon = "🚨";
  }

  toast.className = `${bgClass} border rounded-2xl px-4 py-2.5 shadow-2xl flex items-center space-x-2 text-xs font-medium max-w-sm w-full transition-all duration-300 transform translate-y-2 opacity-0`;
  toast.innerHTML = `<span>${icon}</span><span class="flex-1">${mensaje}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.remove("translate-y-2", "opacity-0");
  }, 10);

  setTimeout(() => {
    toast.classList.add("translate-y-2", "opacity-0");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ========================================================
// NAVEGACIÓN ENTRE PESTAÑAS
// ========================================================
function initTabs() {
  const navTabs = document.querySelectorAll(".nav-tab");
  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-target");
      
      // Actualizar botones
      navTabs.forEach((t) => {
        t.classList.remove("text-emerald-400", "active");
        t.classList.add("text-slate-400");
      });
      tab.classList.add("text-emerald-400", "active");
      tab.classList.remove("text-slate-400");

      // Actualizar secciones
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
      const targetEl = document.getElementById(targetId);
      if (targetEl) targetEl.classList.remove("hidden");

      // Refrescos automáticos según pestaña
      if (targetId === "tab-pendientes") cargarPendientes();
      if (targetId === "tab-extractos") cargarDepositosLibres();
      if (targetId === "tab-historial") {
        cargarEstadisticas();
        cargarHistorial();
      }
    });
  });
}

// ========================================================
// GRUPOS DE WHATSAPP (ORIGEN OBLIGATORIO)
// ========================================================
async function cargarGruposWhatsApp() {
  try {
    const res = await fetch(`${API_BASE}/api/grupos`);
    AppState.grupos = await res.json();
    renderGrupos();
  } catch (err) {
    console.error("Error cargando grupos:", err);
    // Fallback local
    AppState.grupos = [
      { id: 1, nombre: "Grupo São Paulo 🇧🇷", color: "#10B981" },
      { id: 2, nombre: "Grupo Rio de Janeiro 🇧🇷", color: "#3B82F6" },
      { id: 3, nombre: "Grupo Santa Cruz 🇧🇴", color: "#F59E0B" },
      { id: 4, nombre: "Remesas Express VIP", color: "#EC4899" }
    ];
    renderGrupos();
  }
}

function renderGrupos() {
  const container = document.getElementById("grupos-container");
  container.innerHTML = "";

  if (!AppState.grupoSeleccionado && AppState.grupos.length > 0) {
    AppState.grupoSeleccionado = AppState.grupos[0];
  }

  AppState.grupos.forEach((grupo) => {
    const isSelected = AppState.grupoSeleccionado && AppState.grupoSeleccionado.id === grupo.id;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `whitespace-nowrap px-3.5 py-1.5 rounded-xl text-xs font-semibold transition border flex items-center space-x-1.5 ${
      isSelected
        ? "bg-emerald-500 text-slate-950 border-emerald-400 shadow-md shadow-emerald-500/20"
        : "bg-slate-950 text-slate-300 border-slate-700 hover:border-slate-500"
    }`;
    btn.innerHTML = `<span class="w-2 h-2 rounded-full" style="background-color: ${grupo.color}"></span><span>${grupo.nombre}</span>`;
    btn.addEventListener("click", () => {
      AppState.grupoSeleccionado = grupo;
      renderGrupos();
    });
    container.appendChild(btn);
  });
}

// ========================================================
// CARGA Y PROCESAMIENTO DE VOUCHERS (GEMINI FLASH)
// ========================================================
function initVoucherUpload() {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("voucher-file-input");

  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("border-emerald-500", "bg-emerald-500/5");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("border-emerald-500", "bg-emerald-500/5");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("border-emerald-500", "bg-emerald-500/5");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      procesarArchivoVoucher(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      procesarArchivoVoucher(e.target.files[0]);
    }
  });

  // Botón para recalcular diagnóstico si el usuario edita datos con el dedo
  document.getElementById("btn-recalcular").addEventListener("click", reanalizarManual);
}

async function procesarArchivoVoucher(archivo) {
  if (!AppState.grupoSeleccionado) {
    showToast("Por favor selecciona primero el Grupo de WhatsApp de origen", "warning");
    return;
  }

  const loadingEl = document.getElementById("ai-loading");
  const resultadoEl = document.getElementById("resultado-voucher");
  
  loadingEl.classList.remove("hidden");
  resultadoEl.classList.add("hidden");

  const formData = new FormData();
  formData.append("archivo", archivo);
  formData.append("grupo_whatsapp_id", AppState.grupoSeleccionado.id);
  formData.append("grupo_whatsapp_nombre", AppState.grupoSeleccionado.nombre);

  try {
    const res = await fetch(`${API_BASE}/api/vouchers/analizar-archivo`, {
      method: "POST",
      body: formData
    });

    if (!res.ok) throw new Error("Error en el servidor al analizar voucher");

    const data = await res.json();
    loadingEl.classList.add("hidden");

    AppState.voucherActual = data.datos_extraidos;
    AppState.diagnosticoActual = data.diagnostico;
    AppState.archivoGuardadoPath = data.archivo_guardado;
    AppState.voucherPendienteEditandoId = null;

    llenarFormularioHumanInTheLoop(data.datos_extraidos);
    renderDiagnostico(data.diagnostico);

    resultadoEl.classList.remove("hidden");
    showToast("Voucher analizado con éxito", "success");

  } catch (err) {
    loadingEl.classList.add("hidden");
    showToast("Error analizando con IA: " + err.message, "error");
    console.error(err);
  }
}

// Llenar campos editables con lo extraído por IA
function llenarFormularioHumanInTheLoop(datos) {
  document.getElementById("input-monto").value = datos.monto || "";
  document.getElementById("input-fecha").value = datos.fecha || new Date().toISOString().split("T")[0];
  document.getElementById("input-hora").value = datos.hora || "";
  document.getElementById("input-tipo-op").value = datos.tipo_operacion || "PIX";
  document.getElementById("input-id-pix").value = datos.id_transaccion_pix || "";
  document.getElementById("input-pagador").value = datos.pagador_nombre || "";
  document.getElementById("input-receptor").value = datos.receptor_nombre || "";
  document.getElementById("input-banco-orig").value = datos.banco_origen || "";
  document.getElementById("input-banco-dest").value = datos.banco_destino || "";
  document.getElementById("input-observaciones").value = "";
}

// Renderizar el banner de semáforo dinámico
function renderDiagnostico(diag) {
  const banner = document.getElementById("diagnostico-banner");
  const empateContainer = document.getElementById("candidatos-empate-container");
  const listaCandidatos = document.getElementById("candidatos-lista");
  const btnConfirmar = document.getElementById("btn-confirmar-conciliacion");

  empateContainer.classList.add("hidden");
  listaCandidatos.innerHTML = "";
  AppState.depositoSeleccionadoId = null;

  if (diag.estado_diagnostico === "DUPLICADO_FRAUDE") {
    banner.className = "rounded-2xl p-4 border bg-rose-950/80 border-rose-500 text-rose-200 shadow-rose-950/50 shadow-lg";
    banner.innerHTML = `
      <div class="flex items-start space-x-3">
        <span class="text-3xl">🚨</span>
        <div>
          <h3 class="text-sm font-extrabold uppercase tracking-wide text-rose-400">ALERTA CRÍTICA DE FRAUDE / DUPLICADO</h3>
          <p class="text-xs mt-1 text-rose-300 leading-relaxed">${diag.mensaje}</p>
        </div>
      </div>
    `;
    btnConfirmar.classList.add("opacity-50", "pointer-events-none");
    return;
  }

  btnConfirmar.classList.remove("opacity-50", "pointer-events-none");

  if (diag.estado_diagnostico === "MATCH_EXACTO" || diag.estado_diagnostico === "MATCH_FECHA_ANTERIOR") {
    AppState.depositoSeleccionadoId = diag.deposito_id;
    AppState.modoOperacion = "AUTOMATICO";

    banner.className = "rounded-2xl p-4 border bg-emerald-950/70 border-emerald-500/60 text-emerald-200 shadow-emerald-950/50 shadow-lg";
    banner.innerHTML = `
      <div class="flex items-start space-x-3">
        <span class="text-3xl">🟢</span>
        <div>
          <h3 class="text-sm font-extrabold uppercase tracking-wide text-emerald-400">
            ${diag.es_fecha_anterior ? "COINCIDENCIA EN FECHA ANTERIOR CONFIRMADA" : "COINCIDENCIA ÚNICA CONFIRMADA"}
          </h3>
          <p class="text-xs mt-1 text-emerald-200 leading-relaxed">${diag.mensaje}</p>
          <div class="mt-2.5 p-2 bg-slate-900/80 rounded-xl border border-emerald-500/30 text-[11px] font-mono text-emerald-300">
            <strong>Depósito:</strong> ${diag.deposito.banco} | ${diag.deposito.descripcion} | R$ ${diag.deposito.monto.toFixed(2)}
          </div>
        </div>
      </div>
    `;
  } else if (diag.estado_diagnostico === "COLISION_EMPATE" || diag.estado_diagnostico === "COLISION_EMPATE_ANTERIOR") {
    AppState.modoOperacion = "DESEMPATE";
    banner.className = "rounded-2xl p-4 border bg-amber-950/70 border-amber-500/60 text-amber-200 shadow-amber-950/50 shadow-lg";
    banner.innerHTML = `
      <div class="flex items-start space-x-3">
        <span class="text-3xl">🟡</span>
        <div>
          <h3 class="text-sm font-extrabold uppercase tracking-wide text-amber-400">COLISIÓN DE MONTOS (DESEMPATE REQUERIDO)</h3>
          <p class="text-xs mt-1 text-amber-200 leading-relaxed">${diag.mensaje}</p>
        </div>
      </div>
    `;

    // Renderizar candidatos de desempate
    empateContainer.classList.remove("hidden");
    diag.candidatos.forEach((cand, idx) => {
      const card = document.createElement("div");
      card.className = `p-3 rounded-xl border cursor-pointer transition flex items-center justify-between ${
        idx === 0 ? "border-amber-400 bg-amber-500/10" : "border-slate-700 bg-slate-950 hover:border-slate-500"
      }`;
      card.innerHTML = `
        <div class="text-xs space-y-0.5">
          <p class="font-bold text-white">${cand.banco} - <span class="font-mono text-emerald-400">R$ ${cand.monto.toFixed(2)}</span></p>
          <p class="text-slate-400 text-[11px]">${cand.descripcion}</p>
          <p class="text-slate-500 text-[10px]">Hora: ${cand.hora || 'No especificada'} | Fecha: ${cand.fecha}</p>
        </div>
        <input type="radio" name="candidato-radio" value="${cand.id}" ${idx === 0 ? "checked" : ""} class="text-amber-500 focus:ring-amber-500">
      `;
      if (idx === 0) AppState.depositoSeleccionadoId = cand.id;

      card.addEventListener("click", () => {
        AppState.depositoSeleccionadoId = cand.id;
        document.querySelectorAll("#candidatos-lista > div").forEach((c) => {
          c.classList.remove("border-amber-400", "bg-amber-500/10");
          c.classList.add("border-slate-700", "bg-slate-950");
        });
        card.classList.add("border-amber-400", "bg-amber-500/10");
        card.querySelector("input").checked = true;
      });

      listaCandidatos.appendChild(card);
    });

  } else {
    // SIN COINCIDENCIA (ROJO)
    AppState.depositoSeleccionadoId = null;
    AppState.modoOperacion = "AUTOMATICO";
    banner.className = "rounded-2xl p-4 border bg-rose-950/60 border-rose-500/50 text-rose-200 shadow-rose-950/40 shadow-lg";
    banner.innerHTML = `
      <div class="flex items-start space-x-3">
        <span class="text-3xl">🔴</span>
        <div>
          <h3 class="text-sm font-extrabold uppercase tracking-wide text-rose-400">DEPÓSITO NO REGISTRADO EN EXTRACTO</h3>
          <p class="text-xs mt-1 text-rose-200 leading-relaxed">${diag.mensaje}</p>
        </div>
      </div>
    `;
  }
}

// Reanalizar si el usuario cambia el monto o fecha con su dedo
async function reanalizarManual() {
  const monto = parseFloat(document.getElementById("input-monto").value);
  const fecha = document.getElementById("input-fecha").value;
  const idPix = document.getElementById("input-id-pix").value;
  const bancoDest = document.getElementById("input-banco-dest").value;

  if (!monto || isNaN(monto)) {
    showToast("Ingresa un monto válido", "warning");
    return;
  }

  const formData = new FormData();
  formData.append("monto", monto);
  formData.append("fecha_comprobante", fecha);
  if (idPix) formData.append("id_transaccion_pix", idPix);
  if (bancoDest) formData.append("banco_destino", bancoDest);

  try {
    const res = await fetch(`${API_BASE}/api/vouchers/reanalizar-manual`, {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    AppState.diagnosticoActual = data.diagnostico;
    renderDiagnostico(data.diagnostico);
    showToast("Cruce actualizado con nuevos valores", "info");
  } catch (err) {
    showToast("Error al re-verificar cruce: " + err.message, "error");
  }
}

// ========================================================
// ACCIONES INQUEBRANTABLES: CONFIRMAR, EN ESPERA, FORZAR SÍ
// ========================================================
function initActionButtons() {
  // 1. Confirmar y Conciliar
  document.getElementById("btn-confirmar-conciliacion").addEventListener("click", async () => {
    const datos = obtenerDatosFormulario();
    if (!datos) return;

    if (!AppState.depositoSeleccionadoId && AppState.diagnosticoActual?.estado_diagnostico === "SIN_COINCIDENCIA") {
      showToast("No hay depósito coincidente. Usa 'Dejar En Espera' o 'Forzar SÍ Manual'", "warning");
      return;
    }

    try {
      const payload = {
        ...datos,
        id: AppState.voucherPendienteEditandoId,
        deposito_asociado_id: AppState.depositoSeleccionadoId,
        modo: AppState.modoOperacion,
        imagen_path: AppState.archivoGuardadoPath
      };

      const res = await fetch(`${API_BASE}/api/vouchers/confirmar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const resp = await res.json();
      if (resp.success) {
        showToast("🟢 Voucher CONCILIADO exitosamente y marcado en Google Sheets", "success");
        resetearFormularioVoucher();
        cargarEstadisticas();
        cargarPendientes();
      } else {
        throw new Error(resp.detail || "Error al confirmar");
      }
    } catch (err) {
      showToast("Error confirmando voucher: " + err.message, "error");
    }
  });

  // 2. Dejar En Espera (Rojo)
  document.getElementById("btn-dejar-espera").addEventListener("click", async () => {
    const datos = obtenerDatosFormulario();
    if (!datos) return;

    try {
      const payload = {
        ...datos,
        id: AppState.voucherPendienteEditandoId,
        imagen_path: AppState.archivoGuardadoPath
      };

      const res = await fetch(`${API_BASE}/api/vouchers/en-espera`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const resp = await res.json();
      if (resp.success) {
        showToast("🔴 Voucher guardado EN ESPERA y registrado en Sheets", "warning");
        resetearFormularioVoucher();
        cargarEstadisticas();
        cargarPendientes();
      }
    } catch (err) {
      showToast("Error guardando en espera: " + err.message, "error");
    }
  });

  // 3. Forzar SÍ Manual (Emergencia)
  document.getElementById("btn-forzar-si").addEventListener("click", async () => {
    if (!confirm("⚠️ ¿Deseas autorizar manualmente este voucher sin depósito exacto en extracto? Se registrará como FORZADO MANUAL.")) {
      return;
    }

    const datos = obtenerDatosFormulario();
    if (!datos) return;

    try {
      const payload = {
        ...datos,
        id: AppState.voucherPendienteEditandoId,
        deposito_asociado_id: null,
        modo: "FORZADO",
        imagen_path: AppState.archivoGuardadoPath
      };

      const res = await fetch(`${API_BASE}/api/vouchers/forzar-si`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const resp = await res.json();
      if (resp.success) {
        showToast("🔓 Voucher FORZADO MANUALMENTE y marcado en Google Sheets", "success");
        resetearFormularioVoucher();
        cargarEstadisticas();
        cargarPendientes();
      }
    } catch (err) {
      showToast("Error al forzar SÍ: " + err.message, "error");
    }
  });

  // Carga de Extractos (Vía B / archivo)
  document.getElementById("btn-upload-extracto").addEventListener("click", uploadExtractoManual);
  document.getElementById("btn-refresh-pendientes").addEventListener("click", cargarPendientes);
  document.getElementById("btn-refresh-historial").addEventListener("click", () => {
    cargarEstadisticas();
    cargarHistorial();
  });
}

function obtenerDatosFormulario() {
  const monto = parseFloat(document.getElementById("input-monto").value);
  const fecha = document.getElementById("input-fecha").value;

  if (!monto || isNaN(monto)) {
    showToast("Por favor ingresa un monto válido", "warning");
    return null;
  }
  if (!fecha) {
    showToast("Por favor selecciona una fecha válida", "warning");
    return null;
  }
  if (!AppState.grupoSeleccionado) {
    showToast("Selecciona el Grupo de WhatsApp origen", "warning");
    return null;
  }

  return {
    monto: monto,
    fecha_comprobante: fecha,
    hora_comprobante: document.getElementById("input-hora").value,
    tipo_operacion: document.getElementById("input-tipo-op").value,
    id_transaccion_pix: document.getElementById("input-id-pix").value,
    pagador_nombre: document.getElementById("input-pagador").value,
    receptor_nombre: document.getElementById("input-receptor").value,
    banco_origen: document.getElementById("input-banco-orig").value,
    banco_destino: document.getElementById("input-banco-dest").value,
    observaciones: document.getElementById("input-observaciones").value,
    grupo_whatsapp_id: AppState.grupoSeleccionado.id,
    grupo_whatsapp_nombre: AppState.grupoSeleccionado.nombre
  };
}

function resetearFormularioVoucher() {
  document.getElementById("resultado-voucher").classList.add("hidden");
  document.getElementById("voucher-file-input").value = "";
  AppState.voucherActual = null;
  AppState.diagnosticoActual = null;
  AppState.depositoSeleccionadoId = null;
  AppState.voucherPendienteEditandoId = null;
}

// ========================================================
// PENDIENTES / EN ESPERA
// ========================================================
async function cargarPendientes() {
  const container = document.getElementById("lista-pendientes");
  const badgeCount = document.getElementById("badge-pendientes-count");
  
  try {
    const res = await fetch(`${API_BASE}/api/vouchers/pendientes`);
    const pendientes = await res.json();

    if (pendientes.length > 0) {
      badgeCount.textContent = pendientes.length;
      badgeCount.classList.remove("hidden");
    } else {
      badgeCount.classList.add("hidden");
    }

    container.innerHTML = "";
    if (pendientes.length === 0) {
      container.innerHTML = `
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-center text-slate-400 text-xs">
          🎉 No tienes ningún voucher en espera. Todos los comprobantes están al día.
        </div>
      `;
      return;
    }

    pendientes.forEach((item) => {
      const card = document.createElement("div");
      card.className = "bg-slate-900 border border-slate-800 hover:border-slate-700 rounded-2xl p-3.5 space-y-2 shadow-sm";
      card.innerHTML = `
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-white flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-rose-500"></span>
            Voucher #${item.id} - ${item.grupo_whatsapp_nombre}
          </span>
          <span class="font-mono text-sm font-extrabold text-rose-400">R$ ${item.monto.toFixed(2)}</span>
        </div>
        <div class="text-[11px] text-slate-400 space-y-0.5">
          <p><strong>Fecha Comprobante:</strong> ${item.fecha_comprobante} ${item.hora_comprobante || ''}</p>
          <p><strong>Pagador:</strong> ${item.pagador_nombre || 'No identificado'}</p>
          <p class="truncate font-mono text-[10px] text-slate-500">ID PIX: ${item.id_transaccion_pix || 'S/N'}</p>
        </div>
        <div class="grid grid-cols-2 gap-2 pt-1 border-t border-slate-800/80">
          <button class="btn-recruzar-pendiente py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 rounded-lg text-xs font-semibold" data-id="${item.id}">
            ⚡ Reintentar Cruce
          </button>
          <button class="btn-forzar-pendiente py-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 rounded-lg text-xs font-semibold" data-id="${item.id}">
            🔓 Forzar SÍ
          </button>
        </div>
      `;

      card.querySelector(".btn-recruzar-pendiente").addEventListener("click", () => retomarVoucherPendiente(item));
      card.querySelector(".btn-forzar-pendiente").addEventListener("click", () => forzarVoucherDirecto(item));

      container.appendChild(card);
    });
  } catch (err) {
    console.error("Error cargando pendientes:", err);
  }
}

function retomarVoucherPendiente(item) {
  // Cambiar a pestaña 1
  document.querySelector('.nav-tab[data-target="tab-escanear"]').click();

  // Seleccionar grupo
  const grp = AppState.grupos.find((g) => g.id === item.grupo_whatsapp_id);
  if (grp) {
    AppState.grupoSeleccionado = grp;
    renderGrupos();
  }

  AppState.voucherPendienteEditandoId = item.id;
  llenarFormularioHumanInTheLoop({
    monto: item.monto,
    fecha: item.fecha_comprobante,
    hora: item.hora_comprobante,
    id_transaccion_pix: item.id_transaccion_pix,
    pagador_nombre: item.pagador_nombre,
    receptor_nombre: item.receptor_nombre,
    banco_destino: item.banco_destino
  });

  document.getElementById("resultado-voucher").classList.remove("hidden");
  reanalizarManual();
}

async function forzarVoucherDirecto(item) {
  if (!confirm(`¿Forzar aprobación de Voucher #${item.id} por R$ ${item.monto}?`)) return;
  try {
    const res = await fetch(`${API_BASE}/api/vouchers/forzar-si`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: item.id,
        monto: item.monto,
        fecha_comprobante: item.fecha_comprobante,
        grupo_whatsapp_id: item.grupo_whatsapp_id,
        grupo_whatsapp_nombre: item.grupo_whatsapp_nombre,
        modo: "FORZADO"
      })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Voucher aprobado manualmente", "success");
      cargarPendientes();
      cargarEstadisticas();
    }
  } catch (err) {
    showToast("Error forzando voucher: " + err.message, "error");
  }
}

// ========================================================
// EXTRACTOS BANCARIOS (VÍA B Y EXTENSIÓN)
// ========================================================
async function uploadExtractoManual() {
  const fileInput = document.getElementById("extracto-file-input");
  const bancoSelect = document.getElementById("extracto-banco-select");

  if (!fileInput.files || !fileInput.files[0]) {
    showToast("Selecciona una captura, PDF o archivo CSV de extracto", "warning");
    return;
  }

  const formData = new FormData();
  formData.append("archivo", fileInput.files[0]);
  formData.append("banco", bancoSelect.value);

  showToast("Extrayendo depósitos con IA / Parser...", "info");

  try {
    const res = await fetch(`${API_BASE}/api/extractos/upload`, {
      method: "POST",
      body: formData
    });

    const data = await res.json();
    if (data.success) {
      showToast(`✅ Se agregaron ${data.insertados} depósitos libres al bolsón`, "success");
      fileInput.value = "";
      cargarDepositosLibres();
      cargarEstadisticas();
    }
  } catch (err) {
    showToast("Error subiendo extracto: " + err.message, "error");
  }
}

async function cargarDepositosLibres() {
  const container = document.getElementById("lista-depositos-libres");
  const countEl = document.getElementById("count-dep-libres");
  const sumaEl = document.getElementById("suma-dep-libres");

  try {
    const res = await fetch(`${API_BASE}/api/extractos/libres`);
    const depositos = await res.json();

    countEl.textContent = depositos.length;
    const totalSuma = depositos.reduce((acc, d) => acc + d.monto, 0);
    sumaEl.textContent = `R$ ${totalSuma.toLocaleString("es-BO", { minimumFractionDigits: 2 })}`;

    container.innerHTML = "";
    if (depositos.length === 0) {
      container.innerHTML = `
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 text-center text-slate-400 text-xs">
          No hay depósitos libres en este momento. Carga un extracto o usa la Extensión de Chrome.
        </div>
      `;
      return;
    }

    depositos.slice(0, 50).forEach((dep) => {
      const card = document.createElement("div");
      card.className = "bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center justify-between";
      card.innerHTML = `
        <div class="text-xs space-y-0.5">
          <p class="font-bold text-white flex items-center gap-1.5">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
            ${dep.banco}
            <span class="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded font-normal">${dep.origen_extracto}</span>
          </p>
          <p class="text-slate-400 text-[11px] truncate max-w-[240px]">${dep.descripcion}</p>
          <p class="text-[10px] text-slate-500 font-mono">${dep.fecha} ${dep.hora || ''}</p>
        </div>
        <div class="text-right">
          <span class="font-mono text-sm font-extrabold text-emerald-400">R$ ${dep.monto.toFixed(2)}</span>
          <p class="text-[10px] text-emerald-500/80 font-semibold">LIBRE</p>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Error cargando depósitos libres:", err);
  }
}

// ========================================================
// HISTORIAL Y ESTADÍSTICAS
// ========================================================
async function cargarEstadisticas() {
  try {
    const res = await fetch(`${API_BASE}/api/stats`);
    const s = await res.json();
    document.getElementById("stat-monto-conciliado").textContent = `R$ ${s.conciliados_monto.toLocaleString("es-BO", { minimumFractionDigits: 2 })}`;
    document.getElementById("stat-count-conciliado").textContent = s.conciliados_count;
    document.getElementById("stat-monto-espera").textContent = `R$ ${s.espera_monto.toLocaleString("es-BO", { minimumFractionDigits: 2 })}`;
    document.getElementById("stat-count-espera").textContent = s.espera_count;
  } catch (err) {
    console.error("Error cargando stats:", err);
  }
}

async function cargarHistorial() {
  const container = document.getElementById("lista-historial");
  try {
    const res = await fetch(`${API_BASE}/api/vouchers/historial?limite=80`);
    const lista = await res.json();

    container.innerHTML = "";
    if (lista.length === 0) {
      container.innerHTML = `
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 text-center text-slate-400 text-xs">
          Aún no hay vouchers registrados en el historial de hoy.
        </div>
      `;
      return;
    }

    lista.forEach((v) => {
      const card = document.createElement("div");
      let estadoBadge = `<span class="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded text-[10px] font-bold">🟢 SÍ</span>`;
      if (v.estado === "FORZADO_MANUAL") {
        estadoBadge = `<span class="bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded text-[10px] font-bold">🔓 SÍ (MANUAL)</span>`;
      } else if (v.estado === "EN_ESPERA") {
        estadoBadge = `<span class="bg-rose-500/20 text-rose-400 border border-rose-500/30 px-2 py-0.5 rounded text-[10px] font-bold">🔴 ESPERA</span>`;
      }

      card.className = "bg-slate-900 border border-slate-800 rounded-xl p-3 space-y-1.5 shadow-sm";
      card.innerHTML = `
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            ${estadoBadge}
            <span class="text-xs font-bold text-white">#${v.id} - ${v.grupo_whatsapp_nombre}</span>
          </div>
          <span class="font-mono text-sm font-extrabold text-white">R$ ${v.monto.toFixed(2)}</span>
        </div>
        <div class="text-[11px] text-slate-400 flex justify-between">
          <span>De: ${v.pagador_nombre || 'N/A'}</span>
          <span>${v.fecha_comprobante}</span>
        </div>
        <div class="text-[10px] text-slate-500 font-mono truncate">
          ${v.id_transaccion_pix ? `PIX: ${v.id_transaccion_pix}` : `Banco: ${v.banco_destino || 'N/A'}`}
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Error cargando historial:", err);
  }
}
