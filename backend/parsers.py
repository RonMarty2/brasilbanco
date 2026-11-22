import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def parse_monto_br(texto: Any) -> float:
    """Convierte montos en formato BR/US ('1.250,50', '1250.50', 'R$ 1.250,50', '-50,00') a float."""
    if isinstance(texto, (int, float)) and not isinstance(texto, bool):
        return float(texto)

    s = str(texto or "").strip()
    if not s:
        raise ValueError("Monto vacío")

    # Quitar moneda y espacios
    s = re.sub(r"R\$|BRL", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", "", s)

    negativo = False
    if s.startswith("(") and s.endswith(")"):
        negativo = True
        s = s[1:-1]
    if s.startswith("-"):
        negativo = True
        s = s[1:]
    elif s.endswith("-"):
        negativo = True
        s = s[:-1]
    elif s.startswith("+"):
        s = s[1:]

    if not s or not re.search(r"\d", s):
        raise ValueError(f"Monto no válido: {texto}")

    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            # Formato BR: 1.250,50
            s = s.replace(".", "").replace(",", ".")
        else:
            # Formato US: 1,250.50
            s = s.replace(",", "")
    elif "," in s:
        # Formato BR sin miles: 1250,50
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        # Múltiples puntos de miles sin decimales: 1.000.000
        s = s.replace(".", "")

    valor = float(s)
    return -valor if negativo else valor


def parse_fecha(texto: str) -> str:
    """Normaliza fechas DD/MM/YYYY, DD/MM/YY o YYYY-MM-DD a formato ISO YYYY-MM-DD."""
    s = str(texto or "").strip()
    if not s:
        raise ValueError("Fecha vacía")

    # ISO YYYY-MM-DD (acepta sufijo de hora si viene pegado)
    m_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\b|T|\s|$)", s)
    if m_iso:
        return datetime.strptime(m_iso.group(0)[:10], "%Y-%m-%d").strftime("%Y-%m-%d")

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    raise ValueError(f"Formato de fecha no soportado: {texto}")


def _decodificar_bytes(contenido: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return contenido.decode(enc)
        except UnicodeDecodeError:
            continue
    return contenido.decode("utf-8", errors="ignore")


def _detectar_delimitador(muestra: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(muestra, delimiters=";,\t|")
        return dialect.delimiter
    except csv.Error:
        return ";"


def _buscar_indice_columna(headers: List[str], keywords: tuple) -> Optional[int]:
    for idx, h in enumerate(headers):
        hl = h.strip().lower()
        if any(k in hl for k in keywords):
            return idx
    return None


def parse_csv(contenido: bytes, banco: str = "Banco") -> List[Dict[str, Any]]:
    """Extrae depósitos de crédito (> 0) desde un extracto CSV bancario."""
    texto = _decodificar_bytes(contenido)
    lineas_no_vacias = [ln for ln in texto.splitlines() if ln.strip()]
    if not lineas_no_vacias:
        return []

    muestra = "\n".join(lineas_no_vacias[:10])
    delimitador = _detectar_delimitador(muestra)
    reader = csv.reader(io.StringIO("\n".join(lineas_no_vacias)), delimiter=delimitador)
    filas = [fila for fila in reader if any(c.strip() for c in fila)]
    if not filas:
        return []

    fecha_idx, desc_idx, monto_idx = 0, 1, 2
    hora_idx: Optional[int] = None
    pix_idx: Optional[int] = None
    inicio = 0

    primera = filas[0]
    es_cabecera = False
    try:
        parse_fecha(primera[0])
    except Exception:
        es_cabecera = True

    if es_cabecera:
        inicio = 1
        f_col = _buscar_indice_columna(primera, ("data", "fecha", "dt"))
        d_col = _buscar_indice_columna(primera, ("descri", "hist", "lanc", "memo", "detal"))
        m_col = _buscar_indice_columna(primera, ("valor", "monto", "quantia", "amount", "créd", "cred"))
        h_col = _buscar_indice_columna(primera, ("hora", "time"))
        p_col = _buscar_indice_columna(primera, ("endtoend", "fitid", "id_pix", "autentic", "docto", "doc"))

        if f_col is not None:
            fecha_idx = f_col
        if d_col is not None:
            desc_idx = d_col
        if m_col is not None:
            monto_idx = m_col
        hora_idx = h_col
        pix_idx = p_col

    depositos: List[Dict[str, Any]] = []
    for fila in filas[inicio:]:
        if len(fila) <= max(fecha_idx, monto_idx):
            continue
        try:
            fecha_iso = parse_fecha(fila[fecha_idx])
            monto = parse_monto_br(fila[monto_idx])
        except Exception:
            continue

        if monto <= 0:
            continue

        descripcion = fila[desc_idx].strip() if desc_idx < len(fila) else ""
        hora = fila[hora_idx].strip() or None if (hora_idx is not None and hora_idx < len(fila)) else None
        id_pix = fila[pix_idx].strip() or None if (pix_idx is not None and pix_idx < len(fila)) else None

        depositos.append({
            "banco": banco or "Banco",
            "fecha": fecha_iso,
            "hora": hora,
            "monto": round(monto, 2),
            "descripcion": descripcion,
            "id_transaccion_pix": id_pix,
            "tipo": "PIX_IN",
            "origen_extracto": "CSV",
        })

    return depositos


def _extraer_tag_ofx(bloque: str, tag: str) -> Optional[str]:
    m = re.search(rf"<{tag}>\s*([^<\r\n]+)", bloque, re.IGNORECASE)
    return m.group(1).strip() if m else None


def parse_ofx(contenido: bytes, banco: str = "Banco") -> List[Dict[str, Any]]:
    """Extrae depósitos de crédito (> 0) desde bloques <STMTTRN> de un archivo OFX."""
    texto = _decodificar_bytes(contenido)
    bloques = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", texto, re.IGNORECASE | re.DOTALL)

    depositos: List[Dict[str, Any]] = []
    for bloque in bloques:
        trnamt = _extraer_tag_ofx(bloque, "TRNAMT")
        dtposted = _extraer_tag_ofx(bloque, "DTPOSTED")
        if not trnamt or not dtposted:
            continue

        try:
            monto = parse_monto_br(trnamt)
        except Exception:
            continue

        if monto <= 0:
            continue

        m_dt = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{6})?", dtposted)
        if not m_dt:
            continue

        try:
            fecha_iso = datetime.strptime(f"{m_dt.group(1)}-{m_dt.group(2)}-{m_dt.group(3)}", "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            continue

        hora: Optional[str] = None
        if m_dt.group(4) and m_dt.group(4) != "000000":
            hhmmss = m_dt.group(4)
            hora = f"{hhmmss[0:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}"

        memo = _extraer_tag_ofx(bloque, "MEMO") or _extraer_tag_ofx(bloque, "NAME") or ""
        fitid = _extraer_tag_ofx(bloque, "FITID")

        depositos.append({
            "banco": banco or "Banco",
            "fecha": fecha_iso,
            "hora": hora,
            "monto": round(monto, 2),
            "descripcion": memo,
            "id_transaccion_pix": fitid,
            "tipo": "PIX_IN",
            "origen_extracto": "OFX",
        })

    return depositos
