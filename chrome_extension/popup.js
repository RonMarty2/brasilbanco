document.getElementById("btn-capturar").addEventListener("click", async () => {
  const statusDiv = document.getElementById("status");
  const banco = document.getElementById("banco").value;
  const servidor = document.getElementById("servidor").value.trim().replace(/\/$/, "");

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

    const depositos = results && results[0] && results[0].result ? results[0].result : [];

    if (!depositos || depositos.length === 0) {
      statusDiv.className = "status-err";
      statusDiv.textContent = "No se detectaron líneas de crédito/depósito en esta página.";
      return;
    }

    statusDiv.textContent = `Encontrados ${depositos.length} depósitos. Enviando al servidor...`;

    // Enviar al servidor local FastAPI
    const res = await fetch(`${servidor}/api/extractos/import-json`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        banco: banco,
        depositos: depositos
      })
    });

    const data = await res.json();
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
