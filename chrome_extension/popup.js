const STORAGE_KEYS = ["banco", "servidor", "token"];

function guardarConfiguracion() {
  const banco = document.getElementById("banco").value;
  const servidor = document.getElementById("servidor").value.trim().replace(/\/$/, "");
  const token = document.getElementById("token").value.trim();
  chrome.storage.local.set({ banco, servidor, token });
}

document.addEventListener("DOMContentLoaded", () => {
  const bancoEl = document.getElementById("banco");
  const servidorEl = document.getElementById("servidor");
  const tokenEl = document.getElementById("token");

  chrome.storage.local.get(STORAGE_KEYS, (items) => {
    if (items.banco) bancoEl.value = items.banco;
    if (items.servidor) servidorEl.value = items.servidor;
    if (items.token) tokenEl.value = items.token;
  });

  bancoEl.addEventListener("change", guardarConfiguracion);
  servidorEl.addEventListener("input", guardarConfiguracion);
  tokenEl.addEventListener("input", guardarConfiguracion);
});

document.getElementById("btn-capturar").addEventListener("click", async () => {
  const statusDiv = document.getElementById("status");
  const banco = document.getElementById("banco").value;
  const servidor = document.getElementById("servidor").value.trim().replace(/\/$/, "");
  const token = document.getElementById("token").value.trim();

  guardarConfiguracion();

  statusDiv.style.display = "block";
  statusDiv.className = "status-ok";
  statusDiv.textContent = "Leyendo movimientos de la página...";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // Inyectar script de lectura en la pestaña bancaria
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"]
    });

    let depositos = [];
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { banco });
      if (response && Array.isArray(response.depositos)) {
        depositos = response.depositos;
      } else if (Array.isArray(response)) {
        depositos = response;
      }
    } catch (_) {
      // Fallback a results?.[0]?.result si hiciera falta
    }

    if (depositos.length === 0 && results?.[0]?.result) {
      const fallback = results[0].result;
      if (Array.isArray(fallback)) {
        depositos = fallback;
      } else if (Array.isArray(fallback.depositos)) {
        depositos = fallback.depositos;
      }
    }

    if (!depositos || depositos.length === 0) {
      statusDiv.className = "status-err";
      statusDiv.textContent = "No se detectaron líneas de crédito/depósito en esta página.";
      return;
    }

    statusDiv.textContent = `Encontrados ${depositos.length} depósitos. Enviando al servidor...`;

    const headers = { "Content-Type": "application/json" };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    // Enviar al servidor local FastAPI
    const res = await fetch(`${servidor}/api/extractos/import-json`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        banco: banco,
        depositos: depositos
      })
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Error HTTP ${res.status}`);
    }

    if (data.success) {
      statusDiv.className = "status-ok";
      statusDiv.textContent = `✅ ¡Éxito! ${data.insertados} depósitos nuevos ingresados al Bolsón Libre.`;
    } else {
      throw new Error(data.detail || "Error en el servidor");
    }

  } catch (err) {
    statusDiv.className = "status-err";
    statusDiv.textContent = "Error: " + err.message;
  }
});
