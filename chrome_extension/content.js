// content.js - Lector DOM no invasivo de extractos bancarios abiertos
(() => {
  function obtenerFechaLocalHoy() {
    const ahora = new Date();
    const yyyy = ahora.getFullYear();
    const mm = String(ahora.getMonth() + 1).padStart(2, "0");
    const dd = String(ahora.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
  }

  function normalizarMonto(txt) {
    if (!txt) return 0;
    // Remueve R$, espacios y cambia formato BR 1.250,50 a 1250.50
    let clean = txt.replace(/R\$/gi, "").replace(/\s+/g, "").trim();
    let esNegativo = false;
    if (clean.startsWith("-")) {
      esNegativo = true;
      clean = clean.slice(1);
    } else if (clean.endsWith("-")) {
      esNegativo = true;
      clean = clean.slice(0, -1);
    }
    if (clean.includes(",") && clean.includes(".")) {
      clean = clean.replace(/\./g, "").replace(",", ".");
    } else if (clean.includes(",")) {
      clean = clean.replace(",", ".");
    }
    const val = parseFloat(clean);
    if (isNaN(val)) return 0;
    return esNegativo ? -Math.abs(val) : val;
  }

  function normalizarFecha(txt, hoyStr) {
    if (!txt) return hoyStr;
    const match = txt.match(/(\d{2})[\/\-](\d{2})[\/\-](\d{4})/);
    if (match) {
      return `${match[3]}-${match[2]}-${match[1]}`;
    }
    const matchDiaMes = txt.match(/(\d{2})[\/\-](\d{2})/);
    if (matchDiaMes) {
      const year = new Date().getFullYear();
      return `${year}-${matchDiaMes[2]}-${matchDiaMes[1]}`;
    }
    return hoyStr;
  }

  function extraerDepositos(bancoSeleccionado) {
    const depList = [];
    const hoyStr = obtenerFechaLocalHoy();
    const banco = typeof bancoSeleccionado === "string"
      ? bancoSeleccionado
      : (window.__REMESAS_BANCO__ || "");

    // Buscar todas las filas de tablas en el documento
    const rows = document.querySelectorAll("tr, div[role='row'], li");
    rows.forEach((row) => {
      const text = row.innerText || "";
      const upperText = text.toUpperCase();
      // Buscar si parece una entrada o crédito (PIX RECEBIDO, CREDITO, +, etc.)
      if (
        (upperText.includes("PIX") || upperText.includes("RECEB") || upperText.includes("CRÉD") || upperText.includes("CRED") || text.includes("+")) &&
        !upperText.includes("ENVIADO") && !upperText.includes("PAGTO")
      ) {
        const cells = row.querySelectorAll("td, div[role='cell'], span");
        let fecha = hoyStr;
        let monto = 0;
        let esSalida = false;
        const desc = text.substring(0, 80).replace(/\n/g, " ");

        cells.forEach((c) => {
          const ct = c.innerText.trim();
          const ctUpper = ct.toUpperCase();

          if (ctUpper === "D" || ctUpper === "DÉBITO" || ctUpper === "DEBITO" || ctUpper === "DEB") {
            esSalida = true;
            return;
          }

          if (ct.match(/\d{2}[\/\-]\d{2}/)) {
            fecha = normalizarFecha(ct, hoyStr);
          }

          if (ct.match(/\d+[\.,]\d{2}/)) {
            if (/\d+[\.,]\d{2}\s*D$/i.test(ct)) {
              esSalida = true;
              return;
            }
            const m = normalizarMonto(ct);
            if (m < 0) {
              esSalida = true;
            } else if (m > monto) {
              monto = m;
            }
          }
        });

        // Extraer EndToEndId si figura
        const matchPixId = text.match(/E\d{8}\d{4}[a-zA-Z0-9]{15,}/);
        const pixId = matchPixId ? matchPixId[0] : null;

        if (!esSalida && monto > 0) {
          depList.push({
            banco: banco,
            fecha: fecha,
            hora: null,
            monto: monto,
            descripcion: desc,
            id_transaccion_pix: pixId,
            tipo: "PIX_IN"
          });
        }
      }
    });

    return depList;
  }

  window.__remesasExtraerDepositos = extraerDepositos;

  if (!window.__REMESAS_LISTENER_REGISTERED__) {
    window.__REMESAS_LISTENER_REGISTERED__ = true;
    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      const banco = (msg && typeof msg.banco === "string")
        ? msg.banco
        : (window.__REMESAS_BANCO__ || "");
      const depositos = window.__remesasExtraerDepositos(banco);
      sendResponse({ depositos });
    });
  }

  return { depositos: extraerDepositos(window.__REMESAS_BANCO__ || "") };
})();
