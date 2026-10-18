import os
from datetime import datetime
from typing import Dict, Any, Optional

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
    fecha_voucher = voucher.get("fecha_comprobante", datetime.now().strftime("%Y-%m-%d"))
    hoy_str = datetime.now().strftime("%Y-%m-%d %H:%M")

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

        # Fila a agregar o actualizar
        fila = [
            f"#{voucher.get('id')}",
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

        worksheet.append_row(fila)

        return {
            "success": True,
            "simulado": False,
            "mensaje": f"Sincronizado en pestaña '{nombre_pestana}' de Google Sheets"
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
