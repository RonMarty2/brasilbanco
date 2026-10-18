// content.js - Lector DOM no invasivo de extractos bancarios abiertos
(() => {
  const depList = [];
  const hoyStr = new Date().toISOString().split("T")[0];

  function normalizarMonto(txt) {
    if (!txt) return 0;
    // Remueve R$, espacios y cambia formato BR 1.250,50 a 1250.50
    let clean = txt.replace(/R\$/g, "").replace(/\s+/g, "").trim();
    if (clean.includes(",") && clean.includes(".")) {
      clean = clean.replace(/\./g, "").replace(",", ".");
    } else if (clean.includes(",")) {
      clean = clean.replace(",", ".");
    }
    const val = parseFloat(clean);
    return isNaN(val) ? 0 : val;
  }

  function normalizarFecha(txt) {
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

  // Buscar todas las filas de tablas en el documento
  const rows = document.querySelectorAll("tr, div[role='row'], li");
  rows.forEach((row) => {
    const text = row.innerText || "";
    // Buscar si parece una entrada o crédito (PIX RECEBIDO, CREDITO, +, etc.)
    if (
      (text.includes("PIX") || text.includes("RECEB") || text.includes("CRÉD") || text.includes("CRED") || text.includes("+")) &&
      !text.includes("ENVIADO") && !text.includes("PAGTO") && !text.includes("DEBITO") && !text.includes("-")
    ) {
      const cells = row.querySelectorAll("td, div[role='cell'], span");
      let fecha = hoyStr;
      let monto = 0;
      let desc = text.substring(0, 80).replace(/\n/g, " ");

      cells.forEach((c) => {
        const ct = c.innerText.trim();
        if (ct.match(/\d{2}\/\d{2}/)) {
          fecha = normalizarFecha(ct);
        }
        if (ct.match(/\d+[\.,]\d{2}/) && !ct.startsWith("-")) {
          const m = normalizarMonto(ct);
          if (m > monto) monto = m;
        }
      });

      // Extraer EndToEndId si figura
      const matchPixId = text.match(/E\d{8}\d{4}[a-zA-Z0-9]{15,}/);
      const pixId = matchPixId ? matchPixId[0] : null;

      if (monto > 0) {
        depList.push({
          banco: "Itaú / Bradesco",
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
})();
