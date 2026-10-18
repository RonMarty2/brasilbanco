from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from database import (
    get_db_connection, 
    rows_to_list, 
    row_to_dict, 
    actualizar_voucher_estado,
    registrar_auditoria
)

TOLERANCIA_CENTAVOS = 0.01  # Para comparaciones de coma flotante

def analizar_conciliacion_voucher(
    monto: float, 
    fecha_comprobante: str, 
    id_transaccion_pix: Optional[str] = None,
    banco_destino: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evalúa un voucher contra la base de datos de extractos y vouchers previos.
    Aplica las reglas de negocio inquebrantables:
    - Fraude / Duplicado si ya existe previamente
    - Coincidencia Única (Verde)
    - Colisión / Empate (Amarillo)
    - Sin Coincidencia (Rojo)
    - Fechas pasadas vs HOY
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    hoy_str = datetime.now().strftime("%Y-%m-%d")
    es_fecha_anterior = 1 if fecha_comprobante < hoy_str else 0

    # 1. VERIFICACIÓN DE FRAUDE / DUPLICADO
    # Si tiene id_transaccion_pix, buscar si ya fue conciliado antes
    if id_transaccion_pix and len(id_transaccion_pix.strip()) > 6:
        cursor.execute("""
            SELECT v.id, v.fecha_comprobante, v.grupo_whatsapp_nombre, v.fecha_conciliacion, v.estado, v.monto
            FROM vouchers v
            WHERE v.id_transaccion_pix = ? AND v.estado IN ('CONCILIADO', 'FORZADO_MANUAL');
        """, (id_transaccion_pix.strip(),))
        dup = cursor.fetchone()
        if dup:
            conn.close()
            return {
                "estado_diagnostico": "DUPLICADO_FRAUDE",
                "color_alerta": "ROJO_CRITICO",
                "mensaje": f"🚨 ALERTA DE FRAUDE: Este voucher PIX ya fue cobrado previamente el {dup['fecha_conciliacion'] or dup['fecha_comprobante']} por el grupo '{dup['grupo_whatsapp_nombre']}' (Voucher #{dup['id']}).",
                "es_fecha_anterior": es_fecha_anterior,
                "candidatos": [],
                "voucher_previo": dict(dup)
            }

    # También verificar si existe un voucher idéntico (mismo monto, fecha y banco) ya conciliado
    cursor.execute("""
        SELECT v.id, v.fecha_comprobante, v.grupo_whatsapp_nombre, v.fecha_conciliacion, v.monto
        FROM vouchers v
        WHERE abs(v.monto - ?) <= ? AND v.fecha_comprobante = ? AND v.estado IN ('CONCILIADO', 'FORZADO_MANUAL');
    """, (monto, TOLERANCIA_CENTAVOS, fecha_comprobante))
    posible_dup = cursor.fetchone()

    # 2. BÚSQUEDA EN EXTRACTOS (DEPÓSITOS LIBRES)
    # Si coincide fecha con hoy o fecha pasada
    cursor.execute("""
        SELECT * FROM depositos_extracto
        WHERE estado = 'LIBRE' 
        AND fecha = ?
        AND abs(monto - ?) <= ?
        ORDER BY hora DESC;
    """, (fecha_comprobante, monto, TOLERANCIA_CENTAVOS))
    candidatos_libres = rows_to_list(cursor.fetchall())

    conn.close()

    total_candidatos = len(candidatos_libres)

    # 3. REGLAS PARA FECHA DE HOY
    if not es_fecha_anterior:
        if total_candidatos == 1:
            dep = candidatos_libres[0]
            aviso_dup = f" (Nota: Existe otro voucher conciliado de R$ {monto} hoy #{posible_dup['id']}, verifica si fue depósito repetido)" if posible_dup else ""
            return {
                "estado_diagnostico": "MATCH_EXACTO",
                "color_alerta": "VERDE",
                "mensaje": f"🟢 Coincidencia única confirmada con depósito libre en {dep['banco']} ({dep['fecha']} {dep.get('hora', '')}).{aviso_dup}",
                "es_fecha_anterior": False,
                "deposito_id": dep["id"],
                "deposito": dep,
                "candidatos": candidatos_libres
            }
        elif total_candidatos > 1:
            return {
                "estado_diagnostico": "COLISION_EMPATE",
                "color_alerta": "AMARILLO",
                "mensaje": f"🟡 Se encontraron {total_candidatos} depósitos libres de R$ {monto:.2f} hoy. Selecciona cuál corresponde vincular:",
                "es_fecha_anterior": False,
                "deposito_id": None,
                "candidatos": candidatos_libres
            }
        else:
            return {
                "estado_diagnostico": "SIN_COINCIDENCIA",
                "color_alerta": "ROJO",
                "mensaje": "🔴 No figura aún ningún depósito libre de este monto en el extracto de hoy. Puedes dejarlo en espera o forzar SÍ manual.",
                "es_fecha_anterior": False,
                "deposito_id": None,
                "candidatos": []
            }

    # 4. REGLAS PARA FECHAS ANTERIORES (DÍAS PASADOS)
    else:
        if total_candidatos >= 1:
            # Hay depósitos libres en la fecha pasada
            if total_candidatos == 1:
                dep = candidatos_libres[0]
                return {
                    "estado_diagnostico": "MATCH_FECHA_ANTERIOR",
                    "color_alerta": "VERDE_ANTERIOR",
                    "mensaje": f"🟢 Coincidencia encontrada en fecha anterior ({fecha_comprobante}) en {dep['banco']}. Se bloqueará en su fecha original y se anotará con fecha de hoy.",
                    "es_fecha_anterior": True,
                    "deposito_id": dep["id"],
                    "deposito": dep,
                    "candidatos": candidatos_libres
                }
            else:
                return {
                    "estado_diagnostico": "COLISION_EMPATE_ANTERIOR",
                    "color_alerta": "AMARILLO",
                    "mensaje": f"🟡 Se encontraron {total_candidatos} depósitos libres de R$ {monto:.2f} en fecha pasada ({fecha_comprobante}). Selecciona uno:",
                    "es_fecha_anterior": True,
                    "deposito_id": None,
                    "candidatos": candidatos_libres
                }
        else:
            return {
                "estado_diagnostico": "SIN_COINCIDENCIA_HISTORICA",
                "color_alerta": "ROJO",
                "mensaje": f"🔴 No se encontró ningún depósito libre para la fecha anterior {fecha_comprobante}. Verifica si falta cargar el extracto de ese día.",
                "es_fecha_anterior": True,
                "deposito_id": None,
                "candidatos": []
            }


def confirmar_conciliacion_reconciler(
    voucher_id: int, 
    deposito_id: Optional[int], 
    modo: str = "AUTOMATICO", 
    observaciones: str = ""
) -> Dict[str, Any]:
    """
    Bloquea el depósito como USADO, pasa el voucher a CONCILIADO (o FORZADO_MANUAL)
    y registra auditoría.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    estado_final = "FORZADO_MANUAL" if modo == "FORZADO" else "CONCILIADO"
    now = datetime.now().isoformat()

    # Actualizar voucher
    cursor.execute("""
        UPDATE vouchers
        SET estado = ?,
            deposito_asociado_id = ?,
            fecha_conciliacion = ?,
            observaciones = CASE WHEN ? != '' THEN ? ELSE observaciones END
        WHERE id = ?;
    """, (estado_final, deposito_id, now, observaciones, observaciones, voucher_id))

    # Si hay depósito vinculado, marcarlo como USADO
    if deposito_id:
        cursor.execute("""
            UPDATE depositos_extracto
            SET estado = 'USADO',
                voucher_id = ?
            WHERE id = ?;
        """, (voucher_id, deposito_id))

    # Auditoría
    accion_audit = "DESEMPATE_MANUAL" if modo == "DESEMPATE" else ("FORZADO_MANUAL" if modo == "FORZADO" else "MATCH_AUTOMATICO")
    cursor.execute("""
        INSERT INTO auditoria_conciliaciones (voucher_id, deposito_id, accion, detalles)
        VALUES (?, ?, ?, ?);
    """, (voucher_id, deposito_id, accion_audit, f"Modo: {modo}. {observaciones}"))

    conn.commit()
    conn.close()

    return {
        "success": True,
        "voucher_id": voucher_id,
        "deposito_id": deposito_id,
        "estado": estado_final,
        "fecha_conciliacion": now
    }
