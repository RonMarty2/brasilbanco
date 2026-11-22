import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_FILE = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "remesas.db"))

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Tabla de Grupos de WhatsApp
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS grupos_whatsapp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        color TEXT DEFAULT '#10B981',
        activo INTEGER DEFAULT 1,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Tabla de Depósitos del Extracto Bancario ("Bolsón de Depósitos")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS depositos_extracto (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        banco TEXT NOT NULL,
        cuenta TEXT,
        fecha TEXT NOT NULL,                -- YYYY-MM-DD
        hora TEXT,                          -- HH:MM:SS o HH:MM
        monto REAL NOT NULL,                -- En Reais (BRL)
        tipo TEXT DEFAULT 'PIX_IN',         -- PIX_IN, TED, TRANSFERENCIA, DEPOSITO
        descripcion TEXT,                   -- Descripción del extracto
        id_transaccion_pix TEXT,            -- EndToEndId si viene en el extracto
        origen_extracto TEXT NOT NULL,      -- 'CHROME_EXTENSION', 'OFX', 'CSV', 'IA_IMAGEN', 'IA_PDF'
        estado TEXT DEFAULT 'LIBRE',        -- 'LIBRE', 'USADO', 'ANULADO'
        voucher_id INTEGER,                 -- FK a vouchers cuando se usa
        archivo_fuente TEXT,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (voucher_id) REFERENCES vouchers (id) ON DELETE SET NULL
    );
    """)

    # Índices para búsqueda rápida en conciliación
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dep_monto_fecha ON depositos_extracto(monto, fecha, estado);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dep_pix ON depositos_extracto(id_transaccion_pix);")

    # 3. Tabla de Vouchers / Comprobantes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vouchers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grupo_whatsapp_id INTEGER,
        grupo_whatsapp_nombre TEXT NOT NULL,
        monto REAL NOT NULL,
        fecha_comprobante TEXT NOT NULL,    -- YYYY-MM-DD
        hora_comprobante TEXT,              -- HH:MM
        pagador_nombre TEXT,
        pagador_documento TEXT,             -- CPF / CNPJ
        receptor_nombre TEXT,
        receptor_documento TEXT,
        banco_origen TEXT,
        banco_destino TEXT,
        id_transaccion_pix TEXT,            -- EndToEndId o código de autenticación
        tipo_operacion TEXT DEFAULT 'PIX',
        estado TEXT NOT NULL,               -- 'CONCILIADO', 'EN_ESPERA', 'DUPLICADO_FRAUDE', 'FORZADO_MANUAL'
        deposito_asociado_id INTEGER,       -- Relación al depósito conciliado
        es_fecha_anterior INTEGER DEFAULT 0,-- 1 si la fecha comprobante es previa a hoy
        imagen_path TEXT,
        datos_ia_raw TEXT,                  -- JSON completo de lo extraído por Gemini
        observaciones TEXT,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        fecha_conciliacion TIMESTAMP,
        sheets_synced INTEGER DEFAULT 0,
        sheets_sync_error TEXT,
        FOREIGN KEY (grupo_whatsapp_id) REFERENCES grupos_whatsapp (id) ON DELETE SET NULL,
        FOREIGN KEY (deposito_asociado_id) REFERENCES depositos_extracto (id) ON DELETE SET NULL
    );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_pix ON vouchers(id_transaccion_pix);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_monto_fecha ON vouchers(monto, fecha_comprobante);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_estado ON vouchers(estado);")

    # 4. Tabla de Auditoría / Historial de Eventos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auditoria_conciliaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        voucher_id INTEGER NOT NULL,
        deposito_id INTEGER,
        accion TEXT NOT NULL,               -- 'MATCH_AUTOMATICO', 'DESEMPATE_MANUAL', 'FORZADO_MANUAL', 'EN_ESPERA', 'DUPLICADO_DETECTADO', 'ANULADO', 'AUTO_RECRUCE'
        detalles TEXT,
        usuario TEXT DEFAULT 'Back-office',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (voucher_id) REFERENCES vouchers (id)
    );
    """)

    # 5. Tabla de Cierres de Caja Nocturnos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cierres_caja (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL UNIQUE,         -- YYYY-MM-DD
        estado TEXT DEFAULT 'CERRADO',      -- 'ABIERTO', 'CERRADO'
        saldo_inicial_brl REAL DEFAULT 0,
        salidas_brl REAL DEFAULT 0,
        saldo_final_teorico_brl REAL DEFAULT 0,
        saldo_final_real_brl REAL,
        diferencia_brl REAL DEFAULT 0,
        total_conciliado_brl REAL DEFAULT 0,
        total_forzado_brl REAL DEFAULT 0,
        total_espera_brl REAL DEFAULT 0,
        total_depositos_dia_brl REAL DEFAULT 0,
        total_libres_brl REAL DEFAULT 0,
        observaciones TEXT,
        resumen_json TEXT,
        resumen_whatsapp TEXT,
        cerrado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Insertar grupos por defecto si no existen
    cursor.execute("SELECT COUNT(*) FROM grupos_whatsapp;")
    if cursor.fetchone()[0] == 0:
        grupos_iniciales = [
            ("Grupo São Paulo 🇧🇷", "#10B981"),
            ("Grupo Rio de Janeiro 🇧🇷", "#3B82F6"),
            ("Grupo Santa Cruz 🇧🇴", "#F59E0B"),
            ("Grupo La Paz / CBBA 🇧🇴", "#8B5CF6"),
            ("Remesas Express VIP", "#EC4899"),
            ("Canal General", "#6B7280"),
        ]
        cursor.executemany(
            "INSERT INTO grupos_whatsapp (nombre, color) VALUES (?, ?);",
            grupos_iniciales
        )

    conn.commit()
    conn.close()

# --- Funciones Auxiliares para DB ---

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row) if row else {}

def rows_to_list(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]

# Grupos
def get_grupos() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM grupos_whatsapp WHERE activo = 1 ORDER BY id ASC;")
    res = rows_to_list(cursor.fetchall())
    conn.close()
    return res

def crear_grupo(nombre: str, color: str = "#10B981") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO grupos_whatsapp (nombre, color) VALUES (?, ?);", (nombre, color))
    gid = cursor.lastrowid
    conn.commit()
    conn.close()
    return gid

# Depósitos de extracto
def guardar_depositos_extracto(depositos: List[Dict[str, Any]]) -> int:
    """Guarda múltiples líneas de depósitos bancarios asegurando que no se dupliquen registros idénticos."""
    conn = get_db_connection()
    cursor = conn.cursor()
    insertados = 0
    for dep in depositos:
        # Prevenir duplicar la misma línea si ya existe exactamente igual
        cursor.execute("""
            SELECT id FROM depositos_extracto 
            WHERE banco = ? AND fecha = ? AND monto = ? AND descripcion = ? 
            AND (hora = ? OR hora IS NULL OR ? IS NULL)
        """, (
            dep.get("banco", "Banco"),
            dep.get("fecha"),
            float(dep.get("monto", 0.0)),
            dep.get("descripcion", ""),
            dep.get("hora"),
            dep.get("hora")
        ))
        existente = cursor.fetchone()
        if not existente:
            cursor.execute("""
                INSERT INTO depositos_extracto (
                    banco, cuenta, fecha, hora, monto, tipo, descripcion, 
                    id_transaccion_pix, origen_extracto, estado, archivo_fuente
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'LIBRE', ?);
            """, (
                dep.get("banco", "Banco"),
                dep.get("cuenta"),
                dep.get("fecha"),
                dep.get("hora"),
                float(dep.get("monto", 0.0)),
                dep.get("tipo", "PIX_IN"),
                dep.get("descripcion", ""),
                dep.get("id_transaccion_pix"),
                dep.get("origen_extracto", "DESCONOCIDO"),
                dep.get("archivo_fuente")
            ))
            insertados += 1
    conn.commit()
    conn.close()
    return insertados

def get_depositos_libres(fecha: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if fecha:
        cursor.execute("""
            SELECT * FROM depositos_extracto 
            WHERE estado = 'LIBRE' AND fecha = ? 
            ORDER BY fecha DESC, hora DESC, id DESC;
        """, (fecha,))
    else:
        cursor.execute("""
            SELECT * FROM depositos_extracto 
            WHERE estado = 'LIBRE' 
            ORDER BY fecha DESC, hora DESC, id DESC LIMIT 200;
        """)
    res = rows_to_list(cursor.fetchall())
    conn.close()
    return res

def get_deposito_por_id(deposito_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM depositos_extracto WHERE id = ?;", (deposito_id,))
    row = cursor.fetchone()
    conn.close()
    return row_to_dict(row) if row else None

# Vouchers
def crear_voucher(data: Dict[str, Any]) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO vouchers (
            grupo_whatsapp_id, grupo_whatsapp_nombre, monto, fecha_comprobante,
            hora_comprobante, pagador_nombre, pagador_documento, receptor_nombre,
            receptor_documento, banco_origen, banco_destino, id_transaccion_pix,
            tipo_operacion, estado, deposito_asociado_id, es_fecha_anterior,
            imagen_path, datos_ia_raw, observaciones, fecha_conciliacion, sheets_synced
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        data.get("grupo_whatsapp_id"),
        data.get("grupo_whatsapp_nombre", "General"),
        float(data.get("monto", 0.0)),
        data.get("fecha_comprobante"),
        data.get("hora_comprobante"),
        data.get("pagador_nombre"),
        data.get("pagador_documento"),
        data.get("receptor_nombre"),
        data.get("receptor_documento"),
        data.get("banco_origen"),
        data.get("banco_destino"),
        data.get("id_transaccion_pix"),
        data.get("tipo_operacion", "PIX"),
        data.get("estado", "EN_ESPERA"),
        data.get("deposito_asociado_id"),
        data.get("es_fecha_anterior", 0),
        data.get("imagen_path"),
        data.get("datos_ia_raw"),
        data.get("observaciones"),
        data.get("fecha_conciliacion"),
        data.get("sheets_synced", 0)
    ))
    vid = cursor.lastrowid
    conn.commit()
    conn.close()
    return vid

def actualizar_voucher_estado(voucher_id: int, estado: str, deposito_id: Optional[int] = None, observaciones: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        UPDATE vouchers 
        SET estado = ?, 
            deposito_asociado_id = COALESCE(?, deposito_asociado_id),
            fecha_conciliacion = CASE WHEN ? IN ('CONCILIADO', 'FORZADO_MANUAL') THEN ? ELSE fecha_conciliacion END,
            observaciones = COALESCE(?, observaciones)
        WHERE id = ?;
    """, (estado, deposito_id, estado, now, observaciones, voucher_id))
    
    if deposito_id and estado in ('CONCILIADO', 'FORZADO_MANUAL'):
        cursor.execute("UPDATE depositos_extracto SET estado = 'USADO', voucher_id = ? WHERE id = ?;", (voucher_id, deposito_id))

    conn.commit()
    conn.close()

def get_voucher_por_id(voucher_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vouchers WHERE id = ?;", (voucher_id,))
    row = cursor.fetchone()
    conn.close()
    return row_to_dict(row) if row else None

def get_vouchers_pendientes() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.*, g.color as grupo_color
        FROM vouchers v
        LEFT JOIN grupos_whatsapp g ON v.grupo_whatsapp_id = g.id
        WHERE v.estado = 'EN_ESPERA'
        ORDER BY v.fecha_creacion DESC;
    """)
    res = rows_to_list(cursor.fetchall())
    conn.close()
    return res

def get_vouchers_historial(limite: int = 150) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.*, g.color as grupo_color, d.banco as deposito_banco, d.descripcion as deposito_desc
        FROM vouchers v
        LEFT JOIN grupos_whatsapp g ON v.grupo_whatsapp_id = g.id
        LEFT JOIN depositos_extracto d ON v.deposito_asociado_id = d.id
        ORDER BY v.id DESC LIMIT ?;
    """, (limite,))
    res = rows_to_list(cursor.fetchall())
    conn.close()
    return res

def registrar_auditoria(voucher_id: int, accion: str, detalles: str, deposito_id: Optional[int] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO auditoria_conciliaciones (voucher_id, deposito_id, accion, detalles)
        VALUES (?, ?, ?, ?);
    """, (voucher_id, deposito_id, accion, detalles))
    conn.commit()
    conn.close()

def get_estadisticas_hoy(fecha_hoy: str) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()

    # Vouchers conciliados hoy
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(monto), 0)
        FROM vouchers
        WHERE (estado = 'CONCILIADO' OR estado = 'FORZADO_MANUAL')
        AND (fecha_comprobante = ? OR date(fecha_conciliacion) = ?);
    """, (fecha_hoy, fecha_hoy))
    row_conciliados = cursor.fetchone()

    # Vouchers en espera
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(monto), 0)
        FROM vouchers
        WHERE estado = 'EN_ESPERA';
    """)
    row_espera = cursor.fetchone()

    # Depósitos libres hoy
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(monto), 0)
        FROM depositos_extracto
        WHERE estado = 'LIBRE' AND fecha = ?;
    """, (fecha_hoy,))
    row_dep_hoy = cursor.fetchone()

    # Total depósitos libres acumulados
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(monto), 0)
        FROM depositos_extracto
        WHERE estado = 'LIBRE';
    """)
    row_dep_total = cursor.fetchone()

    conn.close()

    return {
        "fecha": fecha_hoy,
        "conciliados_count": row_conciliados[0],
        "conciliados_monto": round(row_conciliados[1], 2),
        "espera_count": row_espera[0],
        "espera_monto": round(row_espera[1], 2),
        "libres_hoy_count": row_dep_hoy[0],
        "libres_hoy_monto": round(row_dep_hoy[1], 2),
        "libres_total_count": row_dep_total[0],
        "libres_total_monto": round(row_dep_total[1], 2),
    }

def anular_voucher(voucher_id: int, motivo: str = "") -> Dict[str, Any]:
    """Anula un voucher y libera su depósito asociado (si tenía uno) para corregir errores."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM vouchers WHERE id = ?;", (voucher_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": f"Voucher #{voucher_id} no encontrado"}

    voucher = dict(row)
    dep_id = voucher.get("deposito_asociado_id")
    obs_anterior = voucher.get("observaciones") or ""
    nueva_obs = f"{obs_anterior} [ANULADO: {motivo or 'Corrección manual'}]".strip()

    cursor.execute("""
        UPDATE vouchers
        SET estado = 'ANULADO',
            deposito_asociado_id = NULL,
            observaciones = ?
        WHERE id = ?;
    """, (nueva_obs, voucher_id))

    deposito_liberado = False
    if dep_id:
        cursor.execute("""
            UPDATE depositos_extracto
            SET estado = 'LIBRE',
                voucher_id = NULL
            WHERE id = ?;
        """, (dep_id,))
        deposito_liberado = True

    cursor.execute("""
        INSERT INTO auditoria_conciliaciones (voucher_id, deposito_id, accion, detalles)
        VALUES (?, ?, 'ANULADO', ?);
    """, (voucher_id, dep_id, motivo or "Anulado manualmente"))

    conn.commit()
    conn.close()
    return {
        "success": True,
        "voucher_id": voucher_id,
        "deposito_liberado": deposito_liberado,
        "deposito_id": dep_id,
        "voucher": {**voucher, "estado": "ANULADO", "observaciones": nueva_obs}
    }


def get_resumen_cierre_dia(fecha: str) -> Dict[str, Any]:
    """Calcula el cuadre completo de cierre de caja para una fecha YYYY-MM-DD."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Vouchers del día (por fecha_comprobante o fecha_conciliacion), excluyendo ANULADO
    cursor.execute("""
        SELECT * FROM vouchers
        WHERE estado != 'ANULADO'
        AND (fecha_comprobante = ? OR date(fecha_conciliacion) = ?)
        ORDER BY id DESC;
    """, (fecha, fecha))
    vouchers_dia = rows_to_list(cursor.fetchall())

    # Todos los vouchers EN_ESPERA activos (incluyendo de días anteriores)
    cursor.execute("""
        SELECT * FROM vouchers
        WHERE estado = 'EN_ESPERA'
        ORDER BY fecha_comprobante DESC, id DESC;
    """)
    vouchers_espera = rows_to_list(cursor.fetchall())

    # Depósitos del extracto de esa fecha
    cursor.execute("""
        SELECT * FROM depositos_extracto
        WHERE fecha = ? AND estado != 'ANULADO'
        ORDER BY banco ASC, hora DESC, id DESC;
    """, (fecha,))
    depositos_dia = rows_to_list(cursor.fetchall())

    # Cierre ya guardado (si existe)
    cursor.execute("SELECT * FROM cierres_caja WHERE fecha = ?;", (fecha,))
    cierre_row = cursor.fetchone()
    cierre_guardado = row_to_dict(cierre_row) if cierre_row else None

    conn.close()

    conciliados = [v for v in vouchers_dia if v["estado"] == "CONCILIADO"]
    forzados = [v for v in vouchers_dia if v["estado"] == "FORZADO_MANUAL"]
    depositos_usados = [d for d in depositos_dia if d["estado"] == "USADO"]
    depositos_libres = [d for d in depositos_dia if d["estado"] == "LIBRE"]

    total_conciliado = round(sum(v["monto"] for v in conciliados), 2)
    total_forzado = round(sum(v["monto"] for v in forzados), 2)
    total_aprobado = round(total_conciliado + total_forzado, 2)
    total_espera = round(sum(v["monto"] for v in vouchers_espera), 2)
    total_depositos_dia = round(sum(d["monto"] for d in depositos_dia), 2)
    total_usados_dia = round(sum(d["monto"] for d in depositos_usados), 2)
    total_libres_dia = round(sum(d["monto"] for d in depositos_libres), 2)

    # Desglose por Grupo de WhatsApp
    grupos_map: Dict[str, Dict[str, Any]] = {}
    for v in vouchers_dia:
        nombre = v.get("grupo_whatsapp_nombre") or "General"
        if nombre not in grupos_map:
            grupos_map[nombre] = {
                "grupo": nombre,
                "conciliados_count": 0,
                "conciliados_monto": 0.0,
                "forzados_count": 0,
                "forzados_monto": 0.0,
                "espera_count": 0,
                "espera_monto": 0.0,
                "total_aprobado_count": 0,
                "total_aprobado_monto": 0.0,
            }
        g = grupos_map[nombre]
        if v["estado"] == "CONCILIADO":
            g["conciliados_count"] += 1
            g["conciliados_monto"] = round(g["conciliados_monto"] + v["monto"], 2)
            g["total_aprobado_count"] += 1
            g["total_aprobado_monto"] = round(g["total_aprobado_monto"] + v["monto"], 2)
        elif v["estado"] == "FORZADO_MANUAL":
            g["forzados_count"] += 1
            g["forzados_monto"] = round(g["forzados_monto"] + v["monto"], 2)
            g["total_aprobado_count"] += 1
            g["total_aprobado_monto"] = round(g["total_aprobado_monto"] + v["monto"], 2)
        elif v["estado"] == "EN_ESPERA":
            g["espera_count"] += 1
            g["espera_monto"] = round(g["espera_monto"] + v["monto"], 2)

    por_grupo = sorted(grupos_map.values(), key=lambda x: x["total_aprobado_monto"], reverse=True)

    # Desglose por Banco
    bancos_map: Dict[str, Dict[str, Any]] = {}
    for d in depositos_dia:
        banco = d.get("banco") or "Banco"
        if banco not in bancos_map:
            bancos_map[banco] = {
                "banco": banco,
                "entradas_count": 0,
                "entradas_monto": 0.0,
                "usados_count": 0,
                "usados_monto": 0.0,
                "libres_count": 0,
                "libres_monto": 0.0,
            }
        b = bancos_map[banco]
        b["entradas_count"] += 1
        b["entradas_monto"] = round(b["entradas_monto"] + d["monto"], 2)
        if d["estado"] == "USADO":
            b["usados_count"] += 1
            b["usados_monto"] = round(b["usados_monto"] + d["monto"], 2)
        elif d["estado"] == "LIBRE":
            b["libres_count"] += 1
            b["libres_monto"] = round(b["libres_monto"] + d["monto"], 2)

    por_banco = sorted(bancos_map.values(), key=lambda x: x["entradas_monto"], reverse=True)

    # Armar texto listo para WhatsApp
    lineas_wa = [
        f"🌙 *CIERRE DE CAJA — {fecha}*",
        f"✅ Conciliados: *{len(conciliados)}* | *R$ {total_conciliado:,.2f}*",
    ]
    if forzados:
        lineas_wa.append(f"🔓 Forzados manual: *{len(forzados)}* | *R$ {total_forzado:,.2f}*")
    lineas_wa.append(f"💰 *TOTAL APROBADO: R$ {total_aprobado:,.2f}*")
    lineas_wa.append(f"🏦 Entradas extracto día: *{len(depositos_dia)}* | *R$ {total_depositos_dia:,.2f}*")

    if por_grupo:
        lineas_wa.append("")
        lineas_wa.append("📲 *POR GRUPO WHATSAPP:*")
        for g in por_grupo:
            extra = f" (incl. {g['forzados_count']} manual)" if g["forzados_count"] else ""
            lineas_wa.append(f"• {g['grupo']}: *{g['total_aprobado_count']}* ops | *R$ {g['total_aprobado_monto']:,.2f}*{extra}")

    if por_banco:
        lineas_wa.append("")
        lineas_wa.append("🏦 *POR BANCO:*")
        for b in por_banco:
            lineas_wa.append(f"• {b['banco']}: R$ {b['entradas_monto']:,.2f} ({b['usados_count']} usados / {b['libres_count']} libres)")

    alertas_wa = []
    if vouchers_espera:
        alertas_wa.append(f"🔴 En espera: {len(vouchers_espera)} (R$ {total_espera:,.2f})")
    if forzados:
        alertas_wa.append(f"🟠 Forzados sin depósito: {len(forzados)} (R$ {total_forzado:,.2f})")
    if depositos_libres:
        alertas_wa.append(f"🟡 Depósitos libres sin dueño: {len(depositos_libres)} (R$ {total_libres_dia:,.2f})")

    if alertas_wa:
        lineas_wa.append("")
        lineas_wa.append("⚠️ *PENDIENTES / ALERTAS:*")
        lineas_wa.extend(alertas_wa)
    else:
        lineas_wa.append("")
        lineas_wa.append("✨ *Caja limpia: sin pendientes ni depósitos sueltos.*")

    if cierre_guardado:
        lineas_wa.append("")
        lineas_wa.append(
            f"🧮 Saldo Inicial: R$ {cierre_guardado['saldo_inicial_brl']:,.2f} | "
            f"Salidas: R$ {cierre_guardado['salidas_brl']:,.2f} | "
            f"Teórico: R$ {cierre_guardado['saldo_final_teorico_brl']:,.2f}"
        )
        if cierre_guardado.get("saldo_final_real_brl") is not None:
            dif = cierre_guardado.get("diferencia_brl", 0.0)
            marca = "✅ CUADRA" if abs(dif) < 0.01 else ("📈 SOBRANTE" if dif > 0 else "📉 FALTANTE")
            lineas_wa.append(f"💵 Saldo Real Banco: R$ {cierre_guardado['saldo_final_real_brl']:,.2f} ({marca}: R$ {dif:,.2f})")

    return {
        "fecha": fecha,
        "estado_caja": cierre_guardado["estado"] if cierre_guardado else "ABIERTO",
        "cierre_guardado": cierre_guardado,
        "totales": {
            "conciliados_count": len(conciliados),
            "conciliados_monto": total_conciliado,
            "forzados_count": len(forzados),
            "forzados_monto": total_forzado,
            "aprobado_count": len(conciliados) + len(forzados),
            "aprobado_monto": total_aprobado,
            "espera_count": len(vouchers_espera),
            "espera_monto": total_espera,
            "depositos_dia_count": len(depositos_dia),
            "depositos_dia_monto": total_depositos_dia,
            "depositos_usados_count": len(depositos_usados),
            "depositos_usados_monto": total_usados_dia,
            "depositos_libres_count": len(depositos_libres),
            "depositos_libres_monto": total_libres_dia,
        },
        "por_grupo": por_grupo,
        "por_banco": por_banco,
        "alertas": {
            "vouchers_espera": vouchers_espera,
            "vouchers_forzados": forzados,
            "depositos_libres": depositos_libres,
        },
        "resumen_whatsapp": "\n".join(lineas_wa),
    }


def guardar_cierre_caja(
    fecha: str,
    saldo_inicial_brl: float = 0.0,
    salidas_brl: float = 0.0,
    saldo_final_real_brl: Optional[float] = None,
    observaciones: str = ""
) -> Dict[str, Any]:
    """Guarda o actualiza el snapshot oficial del cierre de caja del día."""
    import json as _json
    resumen = get_resumen_cierre_dia(fecha)
    tot = resumen["totales"]

    saldo_teorico = round(saldo_inicial_brl + tot["depositos_dia_monto"] - salidas_brl, 2)
    diferencia = round(saldo_final_real_brl - saldo_teorico, 2) if saldo_final_real_brl is not None else 0.0

    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cierres_caja (
            fecha, estado, saldo_inicial_brl, salidas_brl,
            saldo_final_teorico_brl, saldo_final_real_brl, diferencia_brl,
            total_conciliado_brl, total_forzado_brl, total_espera_brl,
            total_depositos_dia_brl, total_libres_brl,
            observaciones, resumen_json, resumen_whatsapp, cerrado_en
        ) VALUES (?, 'CERRADO', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(fecha) DO UPDATE SET
            estado = 'CERRADO',
            saldo_inicial_brl = excluded.saldo_inicial_brl,
            salidas_brl = excluded.salidas_brl,
            saldo_final_teorico_brl = excluded.saldo_final_teorico_brl,
            saldo_final_real_brl = excluded.saldo_final_real_brl,
            diferencia_brl = excluded.diferencia_brl,
            total_conciliado_brl = excluded.total_conciliado_brl,
            total_forzado_brl = excluded.total_forzado_brl,
            total_espera_brl = excluded.total_espera_brl,
            total_depositos_dia_brl = excluded.total_depositos_dia_brl,
            total_libres_brl = excluded.total_libres_brl,
            observaciones = excluded.observaciones,
            resumen_json = excluded.resumen_json,
            resumen_whatsapp = excluded.resumen_whatsapp,
            cerrado_en = excluded.cerrado_en;
    """, (
        fecha, saldo_inicial_brl, salidas_brl,
        saldo_teorico, saldo_final_real_brl, diferencia,
        tot["conciliados_monto"], tot["forzados_monto"], tot["espera_monto"],
        tot["depositos_dia_monto"], tot["depositos_libres_monto"],
        observaciones, _json.dumps(resumen, ensure_ascii=False),
        resumen["resumen_whatsapp"], now
    ))
    conn.commit()
    conn.close()

    # Releer resumen actualizado (ya incluye cierre_guardado en texto WhatsApp)
    resumen_final = get_resumen_cierre_dia(fecha)
    # Actualizar resumen_whatsapp con los saldos recién guardados
    conn = get_db_connection()
    conn.execute("UPDATE cierres_caja SET resumen_whatsapp = ? WHERE fecha = ?;", (resumen_final["resumen_whatsapp"], fecha))
    conn.commit()
    conn.close()
    return resumen_final


def get_historial_cierres(limite: int = 30) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, fecha, estado, saldo_inicial_brl, salidas_brl,
               saldo_final_teorico_brl, saldo_final_real_brl, diferencia_brl,
               total_conciliado_brl, total_forzado_brl, total_espera_brl,
               total_depositos_dia_brl, total_libres_brl, observaciones, cerrado_en
        FROM cierres_caja
        ORDER BY fecha DESC LIMIT ?;
    """, (limite,))
    res = rows_to_list(cursor.fetchall())
    conn.close()
    return res


# Inicializar DB al importar
init_db()
