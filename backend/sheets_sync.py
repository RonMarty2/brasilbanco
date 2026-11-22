import os
from typing import Dict, Any, Optional

import database as db

# Intentar importar librerías oficiales de Google Sheets
HAS_GSPREAD = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    pass

SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
CREDENTIALS_FILE = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "service_account.json")

def _obtener_cliente_sheets():
    """Intenta autenticar con Google Sheets de forma segura."""
    if not HAS_GSPREAD:
        return None
    
    rutas_posibles = [
        CREDENTIALS_FILE,
        os.path.join(os.path.dirname(__file__), CREDENTIALS_FILE),
        os.path.join(os.path.dirname(__file__), "credentials.json"),
        os.path.join(os.path.dirname(__file__), "..", "service_account.json"),
    ]

    cred_path = None
    for r in rutas_posibles:
        if os.path.exists(r):
            cred_path = r
            break

    if not cred_path:
        return None

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        credentials = Credentials.from_service_account_file(cred_path, scopes=scopes)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        print(f"[WARN] Error al autenticar Google Sheets: {e}")
        return None


def sincronizar_voucher_sheets(voucher: Dict[str, Any], estado_display: str = "🟢 SÍ") -> Dict[str, Any]:
    """
    Registra o actualiza el voucher en la hoja de cálculo de Google Sheets.
    Crea o ubica la pestaña correspondiente a la fecha (o mes).
    Si no está configurado o falla, devuelve simulación exitosa sin romper el flujo (Tolerancia a fallos).
    """
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", SPREADSHEET_ID)
    fecha_voucher = voucher.get("fecha_comprobante") or db.hoy_negocio()
    hoy_str = db.ahora_negocio().strftime("%Y-%m-%d %H:%M")

    # Si no hay ID de spreadsheet o credenciales, opera en modo tolerancia a fallos
    client = _obtener_cliente_sheets()
    if not client or not spreadsheet_id:
        print(f"[INFO-SHEETS SIMULADO] Voucher #{voucher.get('id')} sincronizado en memoria: {estado_display} | {voucher.get('monto')} BRL | Grupo: {voucher.get('grupo_whatsapp_nombre')}")
        return {
            "success": True,
            "simulado": True,
            "mensaje": "Sincronizado localmente (Modo Tolerancia a Fallos: Configura GOOGLE_SHEETS_SPREADSHEET_ID y service_account.json para enlace en la nube en vivo)"
        }

    try:
        doc = client.open_by_key(spreadsheet_id)
        
        # Nombre de pestaña: Usualmente fecha YYYY-MM-DD o formato mensual YYYY-MM
        nombre_pestana = fecha_voucher
        try:
            worksheet = doc.worksheet(nombre_pestana)
        except gspread.exceptions.WorksheetNotFound:
            # Crear la pestaña si no existe
            worksheet = doc.add_worksheet(title=nombre_pestana, rows="100", cols="12")
            # Encabezados
            worksheet.append_row([
                "ID", "Estado", "Monto (R$)", "Fecha Comprobante", "Hora",
                "Grupo WhatsApp", "Pagador / Remitente", "Receptor", 
                "Banco Destino", "ID PIX / Transacción", "Fecha Registro Back-Office", "Observaciones"
            ])

        # Fila a agregar o actualizar (evitar duplicados por #ID)
        voucher_tag = f"#{voucher.get('id')}"
        fila = [
            voucher_tag,
            estado_display,
            float(voucher.get("monto", 0.0)),
            voucher.get("fecha_comprobante"),
            voucher.get("hora_comprobante", ""),
            voucher.get("grupo_whatsapp_nombre", "General"),
            voucher.get("pagador_nombre", ""),
            voucher.get("receptor_nombre", ""),
            voucher.get("banco_destino", ""),
            voucher.get("id_transaccion_pix", ""),
            hoy_str,
            voucher.get("observaciones", "")
        ]

        celda_existente = None
        try:
            celda_existente = worksheet.find(voucher_tag, in_column=1)
        except Exception:
            celda_existente = None

        if celda_existente:
            worksheet.update(f"A{celda_existente.row}:L{celda_existente.row}", [fila])
            accion_msg = "actualizado"
        else:
            worksheet.append_row(fila)
            accion_msg = "registrado"

        return {
            "success": True,
            "simulado": False,
            "mensaje": f"Voucher {accion_msg} en pestaña '{nombre_pestana}' de Google Sheets"
        }

    except Exception as e:
        error_msg = f"Error conectando con Google Sheets: {str(e)}"
        print(f"[ERROR-SHEETS] {error_msg}")
        return {
            "success": False,
            "simulado": True,
            "error": error_msg,
            "mensaje": "Voucher guardado en base local. Se intentará resincronizar cuando Google Sheets esté disponible."
        }


def sincronizar_cierre_sheets(cierre_resumen: Dict[str, Any]) -> Dict[str, Any]:
    """Registra o actualiza una fila de cierre diario en la pestaña CIERRES_CAJA de Google Sheets."""
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", SPREADSHEET_ID)
    fecha = cierre_resumen.get("fecha") or db.hoy_negocio()
    tot = cierre_resumen.get("totales", {})
    cierre = cierre_resumen.get("cierre_guardado") or {}

    client = _obtener_cliente_sheets()
    if not client or not spreadsheet_id:
        print(f"[INFO-SHEETS SIMULADO] Cierre de caja {fecha} guardado localmente (Total aprobado: R$ {tot.get('aprobado_monto', 0):.2f})")
        return {
            "success": True,
            "simulado": True,
            "mensaje": "Cierre guardado localmente (Google Sheets en modo tolerancia a fallos)"
        }

    try:
        doc = client.open_by_key(spreadsheet_id)
        nombre_pestana = "CIERRES_CAJA"
        try:
            worksheet = doc.worksheet(nombre_pestana)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = doc.add_worksheet(title=nombre_pestana, rows="200", cols="14")
            worksheet.append_row([
                "Fecha", "Estado", "Conciliados (R$)", "Forzados (R$)", "Total Aprobado (R$)",
                "En Espera (R$)", "Entradas Extracto (R$)", "Depósitos Libres (R$)",
                "Saldo Inicial (R$)", "Salidas (R$)", "Saldo Teórico (R$)",
                "Saldo Real (R$)", "Diferencia (R$)", "Observaciones"
            ])

        fila = [
            fecha,
            cierre.get("estado", "CERRADO"),
            tot.get("conciliados_monto", 0.0),
            tot.get("forzados_monto", 0.0),
            tot.get("aprobado_monto", 0.0),
            tot.get("espera_monto", 0.0),
            tot.get("depositos_dia_monto", 0.0),
            tot.get("depositos_libres_monto", 0.0),
            cierre.get("saldo_inicial_brl", 0.0),
            cierre.get("salidas_brl", 0.0),
            cierre.get("saldo_final_teorico_brl", 0.0),
            cierre.get("saldo_final_real_brl") if cierre.get("saldo_final_real_brl") is not None else "",
            cierre.get("diferencia_brl", 0.0),
            cierre.get("observaciones", ""),
        ]

        celda_existente = None
        try:
            celda_existente = worksheet.find(fecha, in_column=1)
        except Exception:
            celda_existente = None

        if celda_existente:
            worksheet.update(f"A{celda_existente.row}:N{celda_existente.row}", [fila])
        else:
            worksheet.append_row(fila)

        return {
            "success": True,
            "simulado": False,
            "mensaje": f"Cierre {fecha} sincronizado en pestaña '{nombre_pestana}'"
        }
    except Exception as e:
        return {
            "success": False,
            "simulado": True,
            "error": str(e),
            "mensaje": "Cierre guardado localmente; error al sincronizar con Google Sheets."
        }
