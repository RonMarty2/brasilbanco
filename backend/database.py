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
        accion TEXT NOT NULL,               -- 'MATCH_AUTOMATICO', 'DESEMPATE_MANUAL', 'FORZADO_MANUAL', 'EN_ESPERA', 'DUPLICADO_DETECTADO'
        detalles TEXT,
        usuario TEXT DEFAULT 'Back-office',
        fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (voucher_id) REFERENCES vouchers (id)
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

# Inicializar DB al importar
init_db()
