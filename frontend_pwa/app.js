// ========================================================
// LÓGICA PRINCIPAL FRONTEND PWA - REMESAS BRASIL ⇄ BOLIVIA
// ========================================================

const API_BASE = (window.location.protocol === "file:" || !window.location.origin || window.location.origin === "null")
  ? "http://localhost:8000"
  : window.location.origin;

// Estado global de la aplicación
const AppState = {
  grupos: [],
  grupoSeleccionado: null,
  voucherActual: null,
  diagnosticoActual: null,
  depositoSeleccionadoId: null,
  modoOperacion: "AUTOMATICO",
  archivoGuardadoPath: "",
  voucherPendienteEditandoId: null,
  cierreActual: null,
  colaVouchers: [],
  historialLista: [],
  libresLista: [],
  previewObjectUrl: null,
  modalTempBlobUrl: null,
  procesandoVoucher: false
};

// ========================================================
// HELPERS DE SEGURIDAD, UI Y RED
// ========================================================
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function conBotonOcupado(btn, asyncFn) {
  if (!btn) return asyncFn();
  if (btn.disabled) return;
  const htmlOriginal = btn.innerHTML;
  btn.disabled = true;
  btn.classList.add("opacity-60", "cursor-not-allowed");
  try {
    return await asyncFn();
  } finally {
    btn.disabled = false;
    btn.classList.remove("opacity-60", "cursor-not-allowed");
    if (btn.innerHTML !== htmlOriginal) {
      btn.innerHTML = htmlOriginal;
    }
  }
}

async function parsearJsonSeguro(res, mensajeDefault = "Error en el servidor") {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || mensajeDefault);
  }
  return data;
}

function actualizarEstadoConexion() {
  const badge = document.getElementById("conn-status");
  if (!badge) return;
  if (navigator.onLine) {
    badge.textContent = "● Online";
    badge.className = "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-950 text-emerald-400 border border-emerald-800";
  } else {
    badge.textContent = "○ Offline";
    badge.className = "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-rose-950 text-rose-400 border border-rose-800";
  }
}

// ========================================================
// AUTENTICACIÓN Y API FETCH
// ========================================================
function mostrarLogin() {
  const loginScreen = document.getElementById("login-screen");
  const userInfo = document.getElementById("header-user-info");
  const userNameEl = document.getElementById("header-user-name");
  const pinInput = document.getElementById("login-pin");
  const errEl = document.getElementById("login-error");

  if (loginScreen) {
    loginScreen.classList.remove("hidden");
    loginScreen.classList.add("flex");
  }
  if (userInfo) {
    userInfo.classList.add("hidden");
    userInfo.classList.remove("flex");
  }
  if (userNameEl) userNameEl.textContent = "";
  if (pinInput) pinInput.value = "";
  if (errEl) {
    errEl.textContent = "";
    errEl.classList.add("hidden");
  }
}

function ocultarLogin(user) {
  const loginScreen = document.getElementById("login-screen");
  const userInfo = document.getElementById("header-user-info");
  const userNameEl = document.getElementById("header-user-name");
  const errEl = document.getElementById("login-error");

  if (loginScreen) {
    loginScreen.classList.add("hidden");
    loginScreen.classList.remove("flex");
  }
  if (errEl) {
    errEl.textContent = "";
    errEl.classList.add("hidden");
  }

  let userData = user;
  if (!userData) {
    try {
      userData = JSON.parse(localStorage.getItem("remesas_user") || "null");
    } catch (_) {
      userData = null;
    }
  }
  if (userInfo && userData) {
    if (userNameEl) userNameEl.textContent = userData.nombre || userData.username || "";
    userInfo.classList.remove("hidden");
    userInfo.classList.add("flex");
  }
}

async function apiFetch(url, opts = {}) {
  const token = localStorage.getItem("remesas_token");
  const headers = new Headers(opts.headers || {});
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(url, { ...opts, headers });
  if (res.status === 401) {
    localStorage.removeItem("remesas_token");
    localStorage.removeItem("remesas_user");
    mostrarLogin();
    throw new Error("Sesión expirada. Inicia sesión nuevamente.");
  }
  return res;
}

function cargarDatosIniciales() {
  cargarGruposWhatsApp();
  cargarEstadisticas();
  cargarPendientes();
  cargarDepositosLibres();
}

function initAuth() {
  const loginForm = document.getElementById("login-form");
  const errEl = document.getElementById("login-error");
  const btnLogout = document.getElementById("btn-logout");

  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const nombre = document.getElementById("login-nombre").value.trim();
      const pin = document.getElementById("login-pin").value.trim();
      const submitBtn = document.getElementById("btn-login-submit");

      if (errEl) {
        errEl.textContent = "";
        errEl.classList.add("hidden");
      }
      if (submitBtn) submitBtn.disabled = true;

      try {
        const res = await fetch(`${API_BASE}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ nombre, pin })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || "Usuario o PIN incorrecto");
        }

        const token = data.token || data.access_token;
        if (!token) {
          throw new Error("El servidor no devolvió un token válido");
        }
        const user = data.usuario || data.user || { nombre };

        localStorage.setItem("remesas_token", token);
        localStorage.setItem("remesas_user", JSON.stringify(user));

        ocultarLogin(user);
        cargarDatosIniciales();
        await procesarVoucherCompartido();
        showToast(`Bienvenido, ${user.nombre || nombre}`, "success");
      } catch (err) {
        if (errEl) {
          errEl.textContent = err.message;
          errEl.classList.remove("hidden");
        }
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  if (btnLogout) {
    btnLogout.addEventListener("click", () => {
      localStorage.removeItem("remesas_token");
      localStorage.removeItem("remesas_user");
      mostrarLogin();
      showToast("Sesión cerrada", "info");
    });
  }
}

// ========================================================
// INICIALIZACIÓN Y SERVICE WORKER
// ========================================================
document.addEventListener("DOMContentLoaded", async () => {
  actualizarEstadoConexion();
  window.addEventListener("online", () => {
    actualizarEstadoConexion();
    showToast("Conexión restablecida", "success");
  });
  window.addEventListener("offline", () => {
    actualizarEstadoConexion();
    showToast("Sin conexión a internet", "warning");
  });

  initServiceWorker();
  initTabs();
  initModalImagen();
  initVoucherUpload();
  initActionButtons();
  initFiltrosEnVivo();
  initCierreCaja();
  initAuth();

  const token = localStorage.getItem("remesas_token");
  if (!token) {
    mostrarLogin();
    return;
  }

  try {
    const res = await apiFetch(`${API_BASE}/api/auth/yo`);
    const data = await parsearJsonSeguro(res, "Sesión inválida");
    const user = data.usuario || data.user || data;
    localStorage.setItem("remesas_user", JSON.stringify(user));
    ocultarLogin(user);
    cargarDatosIniciales();
    await procesarVoucherCompartido();
  } catch (err) {
    localStorage.removeItem("remesas_token");
    localStorage.removeItem("remesas_user");
    mostrarLogin();
  }
});

function initServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/pwa/sw.js")
      .then(() => console.log("Service Worker PWA registrado exitosamente"))
      .catch((err) => console.log("Fallo registro Service Worker:", err));
  }
}

async function procesarVoucherCompartido() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("shared") !== "1") return;

  params.delete("shared");
  const newSearch = params.toString();
  const cleanUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
  window.history.replaceState(null, "", cleanUrl);

  if (!("caches" in window)) return;

  try {
    const cache = await caches.open("remesas-share-tmp");
    const resp = await cache.match("/shared-voucher");
    if (!resp) return;

    const blob = await resp.blob();
    const rawName = resp.headers.get("X-Filename");
    const filename = rawName ? decodeURIComponent(rawName) : "voucher.jpg";
    const contentType = resp.headers.get("Content-Type") || blob.type || "image/jpeg";
    const file = new File([blob], filename, { type: contentType });

    await cache.delete("/shared-voucher");

    AppState.colaVouchers.push(file);
    actualizarBannerCola();

    if (!AppState.grupoSeleccionado) {
      showToast("📲 Comprobante recibido desde WhatsApp. Selecciona el Grupo de WhatsApp para analizarlo.", "info");
    } else if (!AppState.procesandoVoucher && document.getElementById("resultado-voucher").classList.contains("hidden")) {
      await procesarSiguienteEnCola();
    }
  } catch (err) {
    console.error("Error leyendo voucher compartido:", err);
    showToast("No se pudo recuperar el comprobante compartido", "error");
  }
}

// ========================================================
// VISOR DE IMAGEN (MODAL)
// ========================================================
function initModalImagen() {
  const modal = document.getElementById("modal-imagen");
  const btnCerrar = document.getElementById("btn-cerrar-modal-imagen");
  const previewImg = document.getElementById("voucher-preview-img");

  if (btnCerrar) {
    btnCerrar.addEventListener("click", cerrarModalImagen);
  }
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) cerrarModalImagen();
    });
  }
  if (previewImg) {
    previewImg.addEventListener("click", () => {
      if (previewImg.src) {
        abrirModalImagen(previewImg.src, "Comprobante actual", false);
      }
    });
  }
}

function abrirModalImagen(src, titulo = "Comprobante", esTempBlob = false) {
  const modal = document.getElementById("modal-imagen");
  const img = document.getElementById("modal-imagen-img");
  const titleEl = document.getElementById("modal-imagen-titulo");
  if (!modal || !img) return;

  if (AppState.modalTempBlobUrl) {
    URL.revokeObjectURL(AppState.modalTempBlobUrl);
    AppState.modalTempBlobUrl = null;
  }
  if (esTempBlob) {
    AppState.modalTempBlobUrl = src;
  }

  img.src = src;
  if (titleEl) titleEl.textContent = titulo;
  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function cerrarModalImagen() {
  const modal = document.getElementById("modal-imagen");
  const img = document.getElementById("modal-imagen-img");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
  if (img) img.src = "";
  if (AppState.modalTempBlobUrl) {
    URL.revokeObjectURL(AppState.modalTempBlobUrl);
    AppState.modalTempBlobUrl = null;
  }
}

async function verFotoVoucher(imagenPath, etiqueta = "") {
  if (!imagenPath) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/vouchers/imagen?path=${encodeURIComponent(imagenPath)}`);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "No se pudo cargar la imagen");
    }
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    if (blob.type === "application/pdf") {
      window.open(blobUrl, "_blank");
      return;
    }
    abrirModalImagen(blobUrl, `Comprobante ${etiqueta}`, true);
  } catch (err) {
    showToast("Error cargando foto: " + err.message, "error");
  }
}

function limpiarPreviewLocal() {
  const box = document.getElementById("voucher-preview-box");
  const img = document.getElementById("voucher-preview-img");
  if (box) box.classList.add("hidden");
  if (img) img.src = "";
  if (AppState.previewObjectUrl) {
    URL.revokeObjectURL(AppState.previewObjectUrl);
    AppState.previewObjectUrl = null;
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
  toast.innerHTML = `<span>${icon}</span><span class="flex-1">${escapeHtml(mensaje)}</span>`;
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

      navTabs.forEach((t) => {
        t.classList.remove("text-emerald-400", "active");
        t.classList.add("text-slate-400");
      });
      tab.classList.add("text-emerald-400", "active");
      tab.classList.remove("text-slate-400");

      document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
      const targetEl = document.getElementById(targetId);
      if (targetEl) targetEl.classList.remove("hidden");

      if (targetId === "tab-pendientes") cargarPendientes();
      if (targetId === "tab-extractos") cargarDepositosLibres();
      if (targetId === "tab-historial") {
        cargarEstadisticas();
        cargarHistorial();
      }
      if (targetId === "tab-cierre") cargarCierreCaja();
    });
  });
}

// ========================================================
// GRUPOS DE WHATSAPP (ORIGEN OBLIGATORIO - SIN PRESELECCIÓN)
// ========================================================
async function cargarGruposWhatsApp() {
  try {
    const res = await apiFetch(`${API_BASE}/api/grupos`);
    AppState.grupos = await parsearJsonSeguro(res, "Error cargando grupos");
    renderGrupos();
  } catch (err) {
    console.error("Error cargando grupos:", err);
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

  AppState.grupos.forEach((grupo) => {
    const isSelected = AppState.grupoSeleccionado && AppState.grupoSeleccionado.id === grupo.id;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `whitespace-nowrap px-3.5 py-1.5 rounded-xl text-xs font-semibold transition border flex items-center space-x-1.5 ${
      isSelected
        ? "bg-emerald-500 text-slate-950 border-emerald-400 shadow-md shadow-emerald-500/20"
        : "bg-slate-950 text-slate-300 border-slate-700 hover:border-slate-500"
    }`;
    btn.innerHTML = `<span class="w-2 h-2 rounded-full" style="background-color: ${escapeHtml(grupo.color || "#10B981")}"></span><span>${escapeHtml(grupo.nombre)}</span>`;
    btn.addEventListener("click", () => {
      AppState.grupoSeleccionado = grupo;
      renderGrupos();
      if (
        AppState.colaVouchers.length > 0 &&
        !AppState.procesandoVoucher &&
        document.getElementById("resultado-voucher").classList.contains("hidden")
      ) {
        procesarSiguienteEnCola();
      }
    });
    container.appendChild(btn);
  });
}

// ========================================================
// COLA Y PROCESAMIENTO DE VOUCHERS (GEMINI FLASH)
// ========================================================
function actualizarBannerCola() {
  const banner = document.getElementById("cola-vouchers-banner");
  const texto = document.getElementById("cola-vouchers-texto");
  if (!banner || !texto) return;

  const n = AppState.colaVouchers.length;
  if (n > 0) {
    texto.textContent = `📚 ${n} comprobante(s) pendiente(s) en cola`;
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

function encolarArchivosVouchers(fileList) {
  const archivos = Array.from(fileList || []).filter(Boolean);
  if (archivos.length === 0) return;

  AppState.colaVouchers.push(...archivos);
  actualizarBannerCola();

  if (!AppState.grupoSeleccionado) {
    showToast("Selecciona primero el Grupo de WhatsApp origen para procesar", "warning");
    return;
  }

  if (!AppState.procesandoVoucher && document.getElementById("resultado-voucher").classList.contains("hidden")) {
    procesarSiguienteEnCola();
  } else {
    showToast(`📚 ${archivos.length} comprobante(s) agregado(s) a la cola`, "info");
  }
}

async function procesarSiguienteEnCola() {
  if (AppState.procesandoVoucher || AppState.colaVouchers.length === 0) {
    actualizarBannerCola();
    return;
  }
  if (!AppState.grupoSeleccionado) {
    showToast("Por favor selecciona primero el Grupo de WhatsApp de origen", "warning");
    return;
  }

  const siguiente = AppState.colaVouchers.shift();
  actualizarBannerCola();
  await procesarArchivoVoucher(siguiente);
}

function initVoucherUpload() {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("voucher-file-input");
  const btnLimpiarCola = document.getElementById("btn-limpiar-cola");

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
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      encolarArchivosVouchers(e.dataTransfer.files);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      encolarArchivosVouchers(e.target.files);
      fileInput.value = "";
    }
  });

  if (btnLimpiarCola) {
    btnLimpiarCola.addEventListener("click", () => {
      AppState.colaVouchers = [];
      actualizarBannerCola();
      if (document.getElementById("resultado-voucher").classList.contains("hidden")) {
        AppState.grupoSeleccionado = null;
        renderGrupos();
      }
      showToast("Cola de comprobantes vaciada", "info");
    });
  }

  const btnRecalcular = document.getElementById("btn-recalcular");
  btnRecalcular.addEventListener("click", () => conBotonOcupado(btnRecalcular, reanalizarManual));
}

async function procesarArchivoVoucher(archivo) {
  if (!AppState.grupoSeleccionado) {
    showToast("Por favor selecciona primero el Grupo de WhatsApp de origen", "warning");
    return;
  }

  const loadingEl = document.getElementById("ai-loading");
  const resultadoEl = document.getElementById("resultado-voucher");

  AppState.procesandoVoucher = true;
  loadingEl.classList.remove("hidden");
  resultadoEl.classList.add("hidden");

  limpiarPreviewLocal();
  if (archivo.type && archivo.type.startsWith("image/")) {
    const previewBox = document.getElementById("voucher-preview-box");
    const previewImg = document.getElementById("voucher-preview-img");
    AppState.previewObjectUrl = URL.createObjectURL(archivo);
    if (previewImg && previewBox) {
      previewImg.src = AppState.previewObjectUrl;
      previewBox.classList.remove("hidden");
    }
  }

  const formData = new FormData();
  formData.append("archivo", archivo);
  formData.append("grupo_whatsapp_id", AppState.grupoSeleccionado.id);
  formData.append("grupo_whatsapp_nombre", AppState.grupoSeleccionado.nombre);

  try {
    const res = await apiFetch(`${API_BASE}/api/vouchers/analizar-archivo`, {
      method: "POST",
      body: formData
    });

    const data = await parsearJsonSeguro(res, "Error en el servidor al analizar voucher");
    loadingEl.classList.add("hidden");

    AppState.voucherActual = data.datos_extraidos;
    AppState.diagnosticoActual = data.diagnostico;
    AppState.archivoGuardadoPath = data.archivo_guardado;
    AppState.voucherPendienteEditandoId = null;

    llenarFormularioHumanInTheLoop(data.datos_extraidos);
    renderDiagnostico(data.diagnostico);

    resultadoEl.classList.remove("hidden");
    if (data.datos_extraidos?._es_mock) {
      showToast(data.datos_extraidos._aviso || "Modo simulación activo", "warning");
    } else {
      showToast("Voucher analizado con éxito", "success");
    }
  } catch (err) {
    loadingEl.classList.add("hidden");
    limpiarPreviewLocal();
    showToast("Error analizando con IA: " + err.message, "error");
    console.error(err);
  } finally {
    AppState.procesandoVoucher = false;
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
          <p class="text-xs mt-1 text-rose-300 leading-relaxed">${escapeHtml(diag.mensaje)}</p>
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
          <p class="text-xs mt-1 text-emerald-200 leading-relaxed">${escapeHtml(diag.mensaje)}</p>
          <div class="mt-2.5 p-2 bg-slate-900/80 rounded-xl border border-emerald-500/30 text-[11px] font-mono text-emerald-300">
            <strong>Depósito:</strong> ${escapeHtml(diag.deposito.banco)} | ${escapeHtml(diag.deposito.descripcion)} | R$ ${Number(diag.deposito.monto).toFixed(2)}
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
          <p class="text-xs mt-1 text-amber-200 leading-relaxed">${escapeHtml(diag.mensaje)}</p>
        </div>
      </div>
    `;

    empateContainer.classList.remove("hidden");
    diag.candidatos.forEach((cand, idx) => {
      const card = document.createElement("div");
      card.className = `p-3 rounded-xl border cursor-pointer transition flex items-center justify-between ${
        idx === 0 ? "border-amber-400 bg-amber-500/10" : "border-slate-700 bg-slate-950 hover:border-slate-500"
      }`;
      card.innerHTML = `
        <div class="text-xs space-y-0.5">
          <p class="font-bold text-white">${escapeHtml(cand.banco)} - <span class="font-mono text-emerald-400">R$ ${Number(cand.monto).toFixed(2)}</span></p>
          <p class="text-slate-400 text-[11px]">${escapeHtml(cand.descripcion)}</p>
          <p class="text-slate-500 text-[10px]">Hora: ${escapeHtml(cand.hora || "No especificada")} | Fecha: ${escapeHtml(cand.fecha)}</p>
        </div>
        <input type="radio" name="candidato-radio" value="${escapeHtml(cand.id)}" ${idx === 0 ? "checked" : ""} class="text-amber-500 focus:ring-amber-500">
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
    AppState.depositoSeleccionadoId = null;
    AppState.modoOperacion = "AUTOMATICO";
    banner.className = "rounded-2xl p-4 border bg-rose-950/60 border-rose-500/50 text-rose-200 shadow-rose-950/40 shadow-lg";
    banner.innerHTML = `
      <div class="flex items-start space-x-3">
        <span class="text-3xl">🔴</span>
        <div>
          <h3 class="text-sm font-extrabold uppercase tracking-wide text-rose-400">DEPÓSITO NO REGISTRADO EN EXTRACTO</h3>
          <p class="text-xs mt-1 text-rose-200 leading-relaxed">${escapeHtml(diag.mensaje)}</p>
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
    const res = await apiFetch(`${API_BASE}/api/vouchers/reanalizar-manual`, {
      method: "POST",
      body: formData
    });
    const data = await parsearJsonSeguro(res, "Error al re-verificar cruce");
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
  const btnConfirmar = document.getElementById("btn-confirmar-conciliacion");
  btnConfirmar.addEventListener("click", () =>
    conBotonOcupado(btnConfirmar, async () => {
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

        const res = await apiFetch(`${API_BASE}/api/vouchers/confirmar`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const resp = await parsearJsonSeguro(res, "Error al confirmar");
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
    })
  );

  const btnEspera = document.getElementById("btn-dejar-espera");
  btnEspera.addEventListener("click", () =>
    conBotonOcupado(btnEspera, async () => {
      const datos = obtenerDatosFormulario();
      if (!datos) return;

      try {
        const payload = {
          ...datos,
          id: AppState.voucherPendienteEditandoId,
          imagen_path: AppState.archivoGuardadoPath
        };

        const res = await apiFetch(`${API_BASE}/api/vouchers/en-espera`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const resp = await parsearJsonSeguro(res, "Error guardando en espera");
        if (resp.success) {
          showToast("🔴 Voucher guardado EN ESPERA y registrado en Sheets", "warning");
          resetearFormularioVoucher();
          cargarEstadisticas();
          cargarPendientes();
        } else {
          throw new Error(resp.detail || "Error guardando en espera");
        }
      } catch (err) {
        showToast("Error guardando en espera: " + err.message, "error");
      }
    })
  );

  const btnForzar = document.getElementById("btn-forzar-si");
  btnForzar.addEventListener("click", () =>
    conBotonOcupado(btnForzar, async () => {
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

        const res = await apiFetch(`${API_BASE}/api/vouchers/forzar-si`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        const resp = await parsearJsonSeguro(res, "Error al forzar SÍ");
        if (resp.success) {
          showToast("🔓 Voucher FORZADO MANUALMENTE y marcado en Google Sheets", "success");
          resetearFormularioVoucher();
          cargarEstadisticas();
          cargarPendientes();
        } else {
          throw new Error(resp.detail || "Error al forzar SÍ");
        }
      } catch (err) {
        showToast("Error al forzar SÍ: " + err.message, "error");
      }
    })
  );

  const btnUploadExtracto = document.getElementById("btn-upload-extracto");
  btnUploadExtracto.addEventListener("click", () => conBotonOcupado(btnUploadExtracto, uploadExtractoManual));

  const btnRecruzarTodos = document.getElementById("btn-recruzar-todos");
  btnRecruzarTodos.addEventListener("click", () => conBotonOcupado(btnRecruzarTodos, recruzarTodosPendientes));

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
  limpiarPreviewLocal();
  AppState.voucherActual = null;
  AppState.diagnosticoActual = null;
  AppState.depositoSeleccionadoId = null;
  AppState.archivoGuardadoPath = "";
  AppState.voucherPendienteEditandoId = null;

  if (AppState.colaVouchers.length > 0) {
    procesarSiguienteEnCola();
  } else {
    AppState.grupoSeleccionado = null;
    renderGrupos();
    actualizarBannerCola();
  }
}

// ========================================================
// PENDIENTES / EN ESPERA
// ========================================================
async function cargarPendientes() {
  const container = document.getElementById("lista-pendientes");
  const badgeCount = document.getElementById("badge-pendientes-count");

  try {
    const res = await apiFetch(`${API_BASE}/api/vouchers/pendientes`);
    const pendientes = await parsearJsonSeguro(res, "Error cargando pendientes");

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
      const tieneFoto = Boolean(item.imagen_path);

      card.innerHTML = `
        <div class="flex items-center justify-between gap-2">
          <span class="text-xs font-bold text-white flex items-center gap-1.5 min-w-0">
            <span class="w-2 h-2 rounded-full bg-rose-500 shrink-0"></span>
            <span class="truncate">Voucher #${escapeHtml(item.id)} - ${escapeHtml(item.grupo_whatsapp_nombre)}</span>
          </span>
          <span class="font-mono text-sm font-extrabold text-rose-400 shrink-0">R$ ${Number(item.monto).toFixed(2)}</span>
        </div>
        <div class="text-[11px] text-slate-400 space-y-0.5">
          <p><strong>Fecha Comprobante:</strong> ${escapeHtml(item.fecha_comprobante)} ${escapeHtml(item.hora_comprobante || "")}</p>
          <p><strong>Pagador:</strong> ${escapeHtml(item.pagador_nombre || "No identificado")}</p>
          <p class="truncate font-mono text-[10px] text-slate-500">ID PIX: ${escapeHtml(item.id_transaccion_pix || "S/N")}</p>
        </div>
        <div class="flex flex-wrap gap-2 pt-1 border-t border-slate-800/80">
          <button type="button" class="btn-recruzar-pendiente flex-1 min-w-[110px] py-1.5 px-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 rounded-lg text-xs font-semibold">
            ⚡ Reintentar Cruce
          </button>
          <button type="button" class="btn-forzar-pendiente flex-1 min-w-[90px] py-1.5 px-2 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 rounded-lg text-xs font-semibold">
            🔓 Forzar SÍ
          </button>
          ${tieneFoto ? `<button type="button" class="btn-foto-pendiente py-1.5 px-2.5 bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 rounded-lg text-xs font-semibold">👁️ Foto</button>` : ""}
          <button type="button" class="btn-anular-pendiente py-1.5 px-2.5 bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 text-rose-300 rounded-lg text-xs font-semibold">
            🗑️ Anular
          </button>
        </div>
      `;

      card.querySelector(".btn-recruzar-pendiente").addEventListener("click", () => retomarVoucherPendiente(item));
      const btnForzarPend = card.querySelector(".btn-forzar-pendiente");
      btnForzarPend.addEventListener("click", () => conBotonOcupado(btnForzarPend, () => forzarVoucherDirecto(item)));
      if (tieneFoto) {
        card.querySelector(".btn-foto-pendiente").addEventListener("click", () => verFotoVoucher(item.imagen_path, `#${item.id}`));
      }
      const btnAnularPend = card.querySelector(".btn-anular-pendiente");
      btnAnularPend.addEventListener("click", () => conBotonOcupado(btnAnularPend, () => anularVoucherPorId(item)));

      container.appendChild(card);
    });
  } catch (err) {
    console.error("Error cargando pendientes:", err);
    showToast("Error cargando pendientes: " + err.message, "error");
  }
}

async function anularVoucherPorId(v) {
  if (!confirm(`¿Seguro que deseas ANULAR el voucher #${v.id} (R$ ${Number(v.monto).toFixed(2)})? Si tenía depósito asociado, quedará libre nuevamente.`)) {
    return;
  }
  try {
    const res = await apiFetch(`${API_BASE}/api/vouchers/${v.id}/anular`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ motivo: "Corrección manual" })
    });
    const data = await parsearJsonSeguro(res, "No se pudo anular el voucher");

    showToast(
      data.deposito_liberado
        ? `⚪ Voucher #${v.id} anulado y depósito liberado`
        : `⚪ Voucher #${v.id} anulado`,
      "warning"
    );
    cargarPendientes();
    cargarHistorial();
    cargarEstadisticas();
    cargarDepositosLibres();
  } catch (err) {
    showToast("Error anulando voucher: " + err.message, "error");
  }
}

function retomarVoucherPendiente(item) {
  document.querySelector('.nav-tab[data-target="tab-escanear"]').click();

  const grp = AppState.grupos.find((g) => g.id === item.grupo_whatsapp_id);
  if (grp) {
    AppState.grupoSeleccionado = grp;
    renderGrupos();
  }

  AppState.voucherPendienteEditandoId = item.id;
  AppState.archivoGuardadoPath = item.imagen_path || "";
  limpiarPreviewLocal();

  llenarFormularioHumanInTheLoop({
    monto: item.monto,
    fecha: item.fecha_comprobante,
    hora: item.hora_comprobante,
    id_transaccion_pix: item.id_transaccion_pix,
    pagador_nombre: item.pagador_nombre,
    receptor_nombre: item.receptor_nombre,
    banco_destino: item.banco_destino
  });

  if (item.imagen_path && !String(item.imagen_path).toLowerCase().endsWith(".pdf")) {
    apiFetch(`${API_BASE}/api/vouchers/imagen?path=${encodeURIComponent(item.imagen_path)}`)
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => {
        if (!blob || !blob.type.startsWith("image/")) return;
        const previewBox = document.getElementById("voucher-preview-box");
        const previewImg = document.getElementById("voucher-preview-img");
        AppState.previewObjectUrl = URL.createObjectURL(blob);
        if (previewImg && previewBox) {
          previewImg.src = AppState.previewObjectUrl;
          previewBox.classList.remove("hidden");
        }
      })
      .catch(() => {});
  }

  document.getElementById("resultado-voucher").classList.remove("hidden");
  reanalizarManual();
}

async function forzarVoucherDirecto(item) {
  if (!confirm(`¿Forzar aprobación de Voucher #${item.id} por R$ ${item.monto}?`)) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/vouchers/forzar-si`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: item.id,
        monto: item.monto,
        fecha_comprobante: item.fecha_comprobante,
        grupo_whatsapp_id: item.grupo_whatsapp_id,
        grupo_whatsapp_nombre: item.grupo_whatsapp_nombre,
        imagen_path: item.imagen_path || "",
        modo: "FORZADO"
      })
    });
    const data = await parsearJsonSeguro(res, "Error forzando voucher");
    if (data.success) {
      showToast("Voucher aprobado manualmente", "success");
      cargarPendientes();
      cargarEstadisticas();
    }
  } catch (err) {
    showToast("Error forzando voucher: " + err.message, "error");
  }
}

async function recruzarTodosPendientes() {
  try {
    const res = await apiFetch(`${API_BASE}/api/vouchers/recruzar-pendientes`, {
      method: "POST"
    });
    const data = await parsearJsonSeguro(res, "Error al re-cruzar pendientes");

    if (data.resueltos_count > 0) {
      showToast(`⚡ Se conciliaron ${data.resueltos_count} voucher(s) automáticamente (${data.pendientes_restantes} restante(s))`, "success");
    } else {
      showToast(`Sin coincidencias exactas nuevas (${data.pendientes_restantes} en espera)`, "info");
    }
    cargarPendientes();
    cargarEstadisticas();
  } catch (err) {
    showToast("Error al re-cruzar pendientes: " + err.message, "error");
  }
}

// ========================================================
// EXTRACTOS BANCARIOS Y FILTRO EN VIVO
// ========================================================
function initFiltrosEnVivo() {
  document.getElementById("libres-buscar")?.addEventListener("input", renderDepositosLibres);
  document.getElementById("historial-buscar")?.addEventListener("input", renderHistorial);
  document.getElementById("historial-filtro-estado")?.addEventListener("change", renderHistorial);
}

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
    const res = await apiFetch(`${API_BASE}/api/extractos/upload`, {
      method: "POST",
      body: formData
    });

    const data = await parsearJsonSeguro(res, "Error en el servidor al procesar extracto");

    if (data.success) {
      showToast(`✅ Se agregaron ${data.insertados} depósitos libres al bolsón`, "success");
      if (data.recruce_pendientes?.resueltos_count > 0) {
        showToast(`⚡ ${data.recruce_pendientes.resueltos_count} voucher(s) EN ESPERA conciliados automáticamente`, "success");
        cargarPendientes();
      }
      fileInput.value = "";
      cargarDepositosLibres();
      cargarEstadisticas();
    }
  } catch (err) {
    showToast("Error subiendo extracto: " + err.message, "error");
  }
}

async function cargarDepositosLibres() {
  try {
    const res = await apiFetch(`${API_BASE}/api/extractos/libres`);
    AppState.libresLista = await parsearJsonSeguro(res, "Error cargando depósitos libres");
    renderDepositosLibres();
  } catch (err) {
    console.error("Error cargando depósitos libres:", err);
    showToast("Error cargando depósitos libres: " + err.message, "error");
  }
}

function renderDepositosLibres() {
  const container = document.getElementById("lista-depositos-libres");
  const countEl = document.getElementById("count-dep-libres");
  const sumaEl = document.getElementById("suma-dep-libres");
  const query = (document.getElementById("libres-buscar")?.value || "").trim().toLowerCase();

  const filtrados = AppState.libresLista.filter((dep) => {
    if (!query) return true;
    const texto = [
      dep.banco,
      dep.descripcion,
      dep.fecha,
      dep.hora,
      dep.origen_extracto,
      dep.id_transaccion_pix,
      String(dep.monto),
      Number(dep.monto).toFixed(2)
    ].join(" ").toLowerCase();
    return texto.includes(query);
  });

  countEl.textContent = filtrados.length;
  const totalSuma = filtrados.reduce((acc, d) => acc + Number(d.monto || 0), 0);
  sumaEl.textContent = `R$ ${totalSuma.toLocaleString("es-BO", { minimumFractionDigits: 2 })}`;

  container.innerHTML = "";
  if (filtrados.length === 0) {
    container.innerHTML = `
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 text-center text-slate-400 text-xs">
        ${query ? "Sin depósitos que coincidan con tu búsqueda." : "No hay depósitos libres en este momento. Carga un extracto o usa la Extensión de Chrome."}
      </div>
    `;
    return;
  }

  filtrados.slice(0, 50).forEach((dep) => {
    const card = document.createElement("div");
    card.className = "bg-slate-900 border border-slate-800 rounded-xl p-3 flex items-center justify-between";
    card.innerHTML = `
      <div class="text-xs space-y-0.5">
        <p class="font-bold text-white flex items-center gap-1.5">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          ${escapeHtml(dep.banco)}
          <span class="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded font-normal">${escapeHtml(dep.origen_extracto)}</span>
        </p>
        <p class="text-slate-400 text-[11px] truncate max-w-[240px]">${escapeHtml(dep.descripcion)}</p>
        <p class="text-[10px] text-slate-500 font-mono">${escapeHtml(dep.fecha)} ${escapeHtml(dep.hora || "")}</p>
      </div>
      <div class="text-right">
        <span class="font-mono text-sm font-extrabold text-emerald-400">R$ ${Number(dep.monto).toFixed(2)}</span>
        <p class="text-[10px] text-emerald-500/80 font-semibold">LIBRE</p>
      </div>
    `;
    container.appendChild(card);
  });
}

// ========================================================
// HISTORIAL Y ESTADÍSTICAS
// ========================================================
async function cargarEstadisticas() {
  try {
    const res = await apiFetch(`${API_BASE}/api/stats`);
    const s = await parsearJsonSeguro(res, "Error cargando estadísticas");
    document.getElementById("stat-monto-conciliado").textContent = `R$ ${s.conciliados_monto.toLocaleString("es-BO", { minimumFractionDigits: 2 })}`;
    document.getElementById("stat-count-conciliado").textContent = s.conciliados_count;
    document.getElementById("stat-monto-espera").textContent = `R$ ${s.espera_monto.toLocaleString("es-BO", { minimumFractionDigits: 2 })}`;
    document.getElementById("stat-count-espera").textContent = s.espera_count;
  } catch (err) {
    console.error("Error cargando stats:", err);
  }
}

async function cargarHistorial() {
  try {
    const res = await apiFetch(`${API_BASE}/api/vouchers/historial?limite=120`);
    AppState.historialLista = await parsearJsonSeguro(res, "Error cargando historial");
    renderHistorial();
  } catch (err) {
    console.error("Error cargando historial:", err);
    showToast("Error cargando historial: " + err.message, "error");
  }
}

function renderHistorial() {
  const container = document.getElementById("lista-historial");
  const query = (document.getElementById("historial-buscar")?.value || "").trim().toLowerCase();
  const filtroEstado = document.getElementById("historial-filtro-estado")?.value || "TODOS";

  const filtrados = AppState.historialLista.filter((v) => {
    if (filtroEstado !== "TODOS" && v.estado !== filtroEstado) return false;
    if (!query) return true;
    const texto = [
      `#${v.id}`,
      v.grupo_whatsapp_nombre,
      v.pagador_nombre,
      v.receptor_nombre,
      String(v.monto),
      Number(v.monto).toFixed(2),
      v.id_transaccion_pix,
      v.banco_destino,
      v.fecha_comprobante
    ].join(" ").toLowerCase();
    return texto.includes(query);
  });

  container.innerHTML = "";
  if (filtrados.length === 0) {
    container.innerHTML = `
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 text-center text-slate-400 text-xs">
        ${AppState.historialLista.length === 0 ? "Aún no hay vouchers registrados en el historial." : "Sin resultados para los filtros seleccionados."}
      </div>
    `;
    return;
  }

  filtrados.forEach((v) => {
    const card = document.createElement("div");
    let estadoBadge = `<span class="bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded text-[10px] font-bold">🟢 SÍ</span>`;
    if (v.estado === "FORZADO_MANUAL") {
      estadoBadge = `<span class="bg-amber-500/20 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded text-[10px] font-bold">🔓 SÍ (MANUAL)</span>`;
    } else if (v.estado === "EN_ESPERA") {
      estadoBadge = `<span class="bg-rose-500/20 text-rose-400 border border-rose-500/30 px-2 py-0.5 rounded text-[10px] font-bold">🔴 ESPERA</span>`;
    } else if (v.estado === "ANULADO") {
      estadoBadge = `<span class="bg-slate-700/50 text-slate-300 border border-slate-600/50 px-2 py-0.5 rounded text-[10px] font-bold">⚪ ANULADO</span>`;
    }

    const puedeAnular = v.estado === "CONCILIADO" || v.estado === "FORZADO_MANUAL" || v.estado === "EN_ESPERA";
    const tieneFoto = Boolean(v.imagen_path);

    card.className = "bg-slate-900 border border-slate-800 rounded-xl p-3 space-y-1.5 shadow-sm";
    card.innerHTML = `
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center space-x-2 min-w-0">
          ${estadoBadge}
          <span class="text-xs font-bold text-white truncate">#${escapeHtml(v.id)} - ${escapeHtml(v.grupo_whatsapp_nombre)}</span>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <span class="font-mono text-sm font-extrabold text-white">R$ ${Number(v.monto).toFixed(2)}</span>
          ${tieneFoto ? `<button type="button" class="btn-ver-foto px-2 py-0.5 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 text-sky-300 text-[10px] font-semibold transition">👁️ Foto</button>` : ""}
          ${puedeAnular ? `<button type="button" class="btn-anular-voucher px-2 py-0.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 text-rose-300 text-[10px] font-semibold transition">🗑️ Anular</button>` : ""}
        </div>
      </div>
      <div class="text-[11px] text-slate-400 flex justify-between">
        <span>De: ${escapeHtml(v.pagador_nombre || "N/A")}</span>
        <span>${escapeHtml(v.fecha_comprobante)}</span>
      </div>
      <div class="text-[10px] text-slate-500 font-mono truncate">
        ${v.id_transaccion_pix ? `PIX: ${escapeHtml(v.id_transaccion_pix)}` : `Banco: ${escapeHtml(v.banco_destino || "N/A")}`}
      </div>
    `;

    if (tieneFoto) {
      card.querySelector(".btn-ver-foto").addEventListener("click", () => verFotoVoucher(v.imagen_path, `#${v.id}`));
    }
    if (puedeAnular) {
      const btnAnular = card.querySelector(".btn-anular-voucher");
      btnAnular.addEventListener("click", () => conBotonOcupado(btnAnular, () => anularVoucherPorId(v)));
    }

    container.appendChild(card);
  });
}

// ========================================================
// CIERRE DE CAJA NOCTURNO
// ========================================================
function formatearBRL(valor) {
  const num = Number(valor) || 0;
  return `R$ ${num.toLocaleString("es-BO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function initCierreCaja() {
  const fechaInput = document.getElementById("cierre-fecha");
  const hoy = new Date().toISOString().split("T")[0];
  if (fechaInput && !fechaInput.value) {
    fechaInput.value = hoy;
  }

  fechaInput?.addEventListener("change", (e) => cargarCierreCaja(e.target.value));
  document.getElementById("btn-refresh-cierre")?.addEventListener("click", () => {
    cargarCierreCaja(fechaInput?.value);
  });

  ["cierre-saldo-inicial", "cierre-salidas", "cierre-saldo-real"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", recalcularCuadreCierre);
  });

  const btnReintentarSheets = document.getElementById("btn-reintentar-sheets");
  btnReintentarSheets?.addEventListener("click", () => conBotonOcupado(btnReintentarSheets, reintentarSheetsSync));

  document.getElementById("btn-copiar-whatsapp")?.addEventListener("click", copiarResumenWhatsApp);

  const btnConfirmarCierre = document.getElementById("btn-confirmar-cierre");
  btnConfirmarCierre?.addEventListener("click", () => conBotonOcupado(btnConfirmarCierre, confirmarCierreCaja));
}

async function reintentarSheetsSync() {
  try {
    const res = await apiFetch(`${API_BASE}/api/sheets/reintentar`, { method: "POST" });
    const data = await parsearJsonSeguro(res, "Error al reintentar sincronización con Sheets");
    showToast(
      `🔄 Sheets: ${data.sincronizados}/${data.intentados} sincronizado(s), ${data.pendientes} pendiente(s)`,
      data.pendientes === 0 ? "success" : "warning"
    );
  } catch (err) {
    showToast("Error reintentando Sheets: " + err.message, "error");
  }
}

async function cargarCierreCaja(fechaParam) {
  const fechaInput = document.getElementById("cierre-fecha");
  const fecha = fechaParam || fechaInput?.value || new Date().toISOString().split("T")[0];
  if (fechaInput) fechaInput.value = fecha;

  try {
    const res = await apiFetch(`${API_BASE}/api/cierre-caja?fecha=${encodeURIComponent(fecha)}`);
    const data = await parsearJsonSeguro(res, "Error cargando cierre de caja");

    AppState.cierreActual = data;
    const tot = data.totales || {};

    const badge = document.getElementById("cierre-estado-badge");
    if (data.estado_caja === "CERRADO") {
      badge.textContent = "🔒 CERRADO";
      badge.className = "inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40";
    } else {
      badge.textContent = "ABIERTO";
      badge.className = "inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30";
    }

    document.getElementById("cierre-total-aprobado").textContent = formatearBRL(tot.aprobado_monto);
    document.getElementById("cierre-count-aprobado").textContent = `${tot.aprobado_count || 0} ops (${tot.conciliados_count || 0} auto, ${tot.forzados_count || 0} manual)`;

    document.getElementById("cierre-total-extracto").textContent = formatearBRL(tot.depositos_dia_monto);
    document.getElementById("cierre-count-extracto").textContent = `${tot.depositos_dia_count || 0} entradas`;

    document.getElementById("cierre-total-espera").textContent = formatearBRL(tot.espera_monto);
    document.getElementById("cierre-count-espera").textContent = `${tot.espera_count || 0} pendientes`;

    document.getElementById("cierre-total-libres").textContent = formatearBRL(tot.depositos_libres_monto);
    document.getElementById("cierre-count-libres").textContent = `${tot.depositos_libres_count || 0} sin asignar`;

    const alertasBox = document.getElementById("cierre-alertas-box");
    const alertas = data.alertas || {};
    const espera = alertas.vouchers_espera || [];
    const forzados = alertas.vouchers_forzados || [];
    const libres = alertas.depositos_libres || [];

    if (espera.length === 0 && forzados.length === 0 && libres.length === 0) {
      alertasBox.className = "bg-emerald-950/40 border border-emerald-500/30 rounded-2xl p-3.5 text-xs text-emerald-300";
      alertasBox.innerHTML = `<p class="font-semibold">✨ Caja limpia: sin vouchers en espera, forzados ni depósitos sueltos.</p>`;
    } else {
      alertasBox.className = "bg-amber-950/30 border border-amber-500/40 rounded-2xl p-3.5 space-y-1.5 text-xs text-amber-200";
      const items = [];
      if (espera.length > 0) {
        items.push(`<p>🔴 <strong>${espera.length}</strong> voucher(s) EN ESPERA (${formatearBRL(tot.espera_monto)})</p>`);
      }
      if (forzados.length > 0) {
        items.push(`<p>🟠 <strong>${forzados.length}</strong> forzado(s) manual sin depósito (${formatearBRL(tot.forzados_monto)})</p>`);
      }
      if (libres.length > 0) {
        items.push(`<p>🟡 <strong>${libres.length}</strong> depósito(s) libre(s) sin dueño (${formatearBRL(tot.depositos_libres_monto)})</p>`);
      }
      alertasBox.innerHTML = `<p class="font-bold text-amber-300 uppercase tracking-wider text-[11px]">⚠️ Alertas del Día</p>${items.join("")}`;
    }

    const porGrupoEl = document.getElementById("cierre-por-grupo");
    const grupos = data.por_grupo || [];
    if (grupos.length === 0) {
      porGrupoEl.innerHTML = `<p class="text-slate-500">Sin movimientos registrados para esta fecha.</p>`;
    } else {
      porGrupoEl.innerHTML = grupos.map((g) => `
        <div class="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-xl px-3 py-2">
          <div>
            <p class="font-semibold text-white">${escapeHtml(g.grupo)}</p>
            <p class="text-[10px] text-slate-400">${g.total_aprobado_count} aprobados${g.forzados_count ? ` (${g.forzados_count} manual)` : ""}${g.espera_count ? ` · ${g.espera_count} en espera` : ""}</p>
          </div>
          <span class="font-mono font-bold text-emerald-400">${formatearBRL(g.total_aprobado_monto)}</span>
        </div>
      `).join("");
    }

    const porBancoEl = document.getElementById("cierre-por-banco");
    const bancos = data.por_banco || [];
    if (bancos.length === 0) {
      porBancoEl.innerHTML = `<p class="text-slate-500">Sin entradas de extracto para esta fecha.</p>`;
    } else {
      porBancoEl.innerHTML = bancos.map((b) => `
        <div class="flex items-center justify-between bg-slate-950 border border-slate-800 rounded-xl px-3 py-2">
          <div>
            <p class="font-semibold text-white">${escapeHtml(b.banco)}</p>
            <p class="text-[10px] text-slate-400">${b.entradas_count} entradas · ${b.usados_count} usados / ${b.libres_count} libres</p>
          </div>
          <span class="font-mono font-bold text-sky-400">${formatearBRL(b.entradas_monto)}</span>
        </div>
      `).join("");
    }

    const cg = data.cierre_guardado;
    document.getElementById("cierre-saldo-inicial").value = cg ? cg.saldo_inicial_brl : 0;
    document.getElementById("cierre-salidas").value = cg ? cg.salidas_brl : 0;
    document.getElementById("cierre-saldo-real").value = cg && cg.saldo_final_real_brl !== null && cg.saldo_final_real_brl !== undefined ? cg.saldo_final_real_brl : "";
    document.getElementById("cierre-observaciones").value = cg?.observaciones || "";

    recalcularCuadreCierre();
  } catch (err) {
    showToast("Error cargando cierre: " + err.message, "error");
  }
}

function recalcularCuadreCierre() {
  const saldoInicial = parseFloat(document.getElementById("cierre-saldo-inicial")?.value) || 0;
  const salidas = parseFloat(document.getElementById("cierre-salidas")?.value) || 0;
  const depositosDia = AppState.cierreActual?.totales?.depositos_dia_monto || 0;

  const teorico = saldoInicial + depositosDia - salidas;
  document.getElementById("cierre-saldo-teorico").textContent = formatearBRL(teorico);

  const saldoRealRaw = document.getElementById("cierre-saldo-real")?.value;
  const difEl = document.getElementById("cierre-diferencia");
  if (saldoRealRaw === "" || saldoRealRaw === undefined || saldoRealRaw === null) {
    difEl.textContent = "—";
    difEl.className = "text-sm font-extrabold font-mono text-slate-400 mt-0.5";
    return;
  }

  const saldoReal = parseFloat(saldoRealRaw) || 0;
  const diferencia = saldoReal - teorico;
  if (Math.abs(diferencia) < 0.01) {
    difEl.textContent = `${formatearBRL(0)} (CUADRA)`;
    difEl.className = "text-sm font-extrabold font-mono text-emerald-400 mt-0.5";
  } else if (diferencia > 0) {
    difEl.textContent = `+${formatearBRL(diferencia)} (SOBRANTE)`;
    difEl.className = "text-sm font-extrabold font-mono text-amber-400 mt-0.5";
  } else {
    difEl.textContent = `${formatearBRL(diferencia)} (FALTANTE)`;
    difEl.className = "text-sm font-extrabold font-mono text-rose-400 mt-0.5";
  }
}

async function copiarResumenWhatsApp() {
  const texto = AppState.cierreActual?.resumen_whatsapp;
  if (!texto) {
    showToast("No hay resumen disponible para copiar", "warning");
    return;
  }

  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(texto);
    } else {
      throw new Error("Clipboard API no disponible");
    }
    showToast("📋 Resumen copiado para WhatsApp", "success");
  } catch {
    const ta = document.createElement("textarea");
    ta.value = texto;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    showToast("📋 Resumen copiado para WhatsApp", "success");
  }
}

async function confirmarCierreCaja() {
  const fecha = document.getElementById("cierre-fecha")?.value || new Date().toISOString().split("T")[0];
  if (AppState.cierreActual?.estado_caja === "CERRADO") {
    if (!confirm(`El cierre del día ${fecha} ya estaba CERRADO. ¿Deseas volver a guardarlo y sobrescribirlo?`)) {
      return;
    }
  }

  const saldoInicial = parseFloat(document.getElementById("cierre-saldo-inicial")?.value) || 0;
  const salidas = parseFloat(document.getElementById("cierre-salidas")?.value) || 0;
  const saldoRealRaw = document.getElementById("cierre-saldo-real")?.value;
  const saldoReal = saldoRealRaw !== "" && saldoRealRaw !== undefined ? parseFloat(saldoRealRaw) : null;
  const observaciones = document.getElementById("cierre-observaciones")?.value || "";

  try {
    const res = await apiFetch(`${API_BASE}/api/cierre-caja/cerrar`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fecha,
        saldo_inicial_brl: saldoInicial,
        salidas_brl: salidas,
        saldo_final_real_brl: saldoReal,
        observaciones
      })
    });
    await parsearJsonSeguro(res, "Error al guardar el cierre");

    showToast(`🔒 Cierre de caja ${fecha} guardado correctamente`, "success");
    await cargarCierreCaja(fecha);
  } catch (err) {
    showToast("Error cerrando caja: " + err.message, "error");
  }
}
