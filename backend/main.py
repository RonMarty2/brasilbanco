import os
import shutil
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Importar módulos del sistema
import database as db
import ai_vision
import reconciler
import sheets_sync

app = FastAPI(
    title="Sistema Semi-Automático de Conciliación de Remesas (Brasil ⇄ Bolivia)",
    version="1.0.0",
    description="Backend FastAPI con SQLite, Gemini Vision y Google Sheets"
)

# Configurar CORS para permitir comunicación con PWA y Extensión de Chrome
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas de almacenamiento
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_HISTORIAL = BASE_DIR / "storage" / "Historial"
STORAGE_HISTORIAL.mkdir(parents=True, exist_ok=True)
PWA_DIR = BASE_DIR / "frontend_pwa"


def get_directorio_hoy(subtipo: str = "vouchers") -> Path:
    hoy = datetime.now().strftime("%Y-%m-%d")
    d = STORAGE_HISTORIAL / hoy / subtipo
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------
# MODELOS DE ENTRADA
# ----------------------------------------------------
class GrupoCreate(BaseModel):
    nombre: str
    color: Optional[str] = "#10B981"

class VoucherConfirmacion(BaseModel):
    id: Optional[int] = None
    monto: float
    fecha_comprobante: str
    hora_comprobante: Optional[str] = ""
    pagador_nombre: Optional[str] = ""
    pagador_documento: Optional[str] = ""
    receptor_nombre: Optional[str] = ""
    receptor_documento: Optional[str] = ""
    banco_origen: Optional[str] = ""
    banco_destino: Optional[str] = ""
    id_transaccion_pix: Optional[str] = ""
    tipo_operacion: Optional[str] = "PIX"
    grupo_whatsapp_id: int
    grupo_whatsapp_nombre: str
    deposito_asociado_id: Optional[int] = None
    es_fecha_anterior: Optional[int] = 0
    imagen_path: Optional[str] = ""
    observaciones: Optional[str] = ""
    modo: Optional[str] = "AUTOMATICO" # 'AUTOMATICO', 'DESEMPATE', 'FORZADO'

class VoucherEnEspera(BaseModel):
    id: Optional[int] = None
    monto: float
    fecha_comprobante: str
    hora_comprobante: Optional[str] = ""
    pagador_nombre: Optional[str] = ""
    receptor_nombre: Optional[str] = ""
    banco_destino: Optional[str] = ""
    id_transaccion_pix: Optional[str] = ""
    grupo_whatsapp_id: int
    grupo_whatsapp_nombre: str
    imagen_path: Optional[str] = ""
    observaciones: Optional[str] = ""

class DepositoItem(BaseModel):
    banco: str
    fecha: str
    hora: Optional[str] = None
    monto: float
    descripcion: str
    id_transaccion_pix: Optional[str] = None
    tipo: Optional[str] = "PIX_IN"

class ExtractoImportJSON(BaseModel):
    banco: str
    depositos: List[DepositoItem]


# ----------------------------------------------------
# ENDPOINTS: GRUPOS DE WHATSAPP
# ----------------------------------------------------
@app.get("/api/grupos")
def listar_grupos():
    return db.get_grupos()

@app.post("/api/grupos")
def crear_nuevo_grupo(grupo: GrupoCreate):
    try:
        gid = db.crear_grupo(grupo.nombre, grupo.color or "#10B981")
        return {"id": gid, "nombre": grupo.nombre, "color": grupo.color}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ----------------------------------------------------
# ENDPOINTS: VOUCHERS / COMPROBANTES
# ----------------------------------------------------
@app.post("/api/vouchers/analizar-archivo")
async def analizar_voucher_archivo(
    archivo: UploadFile = File(...),
    grupo_whatsapp_id: Optional[int] = Form(None),
    grupo_whatsapp_nombre: Optional[str] = Form("General")
):
    """
    1. Guarda el archivo en storage/Historial/YYYY-MM-DD/vouchers/
    2. Lo procesa con Gemini Vision (ai_vision)
    3. Cruza inmediatamente con el motor reconciler
    4. Devuelve los campos editables + diagnóstico al frontend (Human-in-the-Loop)
    """
    contenido = await archivo.read()
    mime_type = archivo.content_type or "image/jpeg"
    ext = Path(archivo.filename or "voucher.jpg").suffix or ".jpg"
    
    # Guardar archivo físicamente
    dir_destino = get_directorio_hoy("vouchers")
    timestamp = datetime.now().strftime("%H%M%S_%f")
    nombre_guardado = f"voucher_{timestamp}{ext}"
    ruta_guardado = dir_destino / nombre_guardado
    with open(ruta_guardado, "wb") as f:
        f.write(contenido)

    # 1. Extraer datos con Gemini Vision
    datos_ia = ai_vision.extraer_datos_voucher(contenido, mime_type)

    monto = float(datos_ia.get("monto", 0.0) or 0.0)
    fecha_comprobante = datos_ia.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    id_pix = datos_ia.get("id_transaccion_pix")

    # 2. Diagnóstico de conciliación automático
    diagnostico = reconciler.analizar_conciliacion_voucher(
        monto=monto,
        fecha_comprobante=fecha_comprobante,
        id_transaccion_pix=id_pix,
        banco_destino=datos_ia.get("banco_destino")
    )

    return {
        "datos_extraidos": datos_ia,
        "diagnostico": diagnostico,
        "archivo_guardado": str(ruta_guardado.relative_to(BASE_DIR)),
        "grupo_whatsapp_id": grupo_whatsapp_id,
        "grupo_whatsapp_nombre": grupo_whatsapp_nombre
    }


@app.post("/api/vouchers/reanalizar-manual")
def reanalizar_voucher_manual(
    monto: float = Form(...),
    fecha_comprobante: str = Form(...),
    id_transaccion_pix: Optional[str] = Form(None),
    banco_destino: Optional[str] = Form(None)
):
    """Permite recalcular el diagnóstico cuando el usuario edita el monto o fecha en la PWA con su dedo."""
    diagnostico = reconciler.analizar_conciliacion_voucher(
        monto=monto,
        fecha_comprobante=fecha_comprobante,
        id_transaccion_pix=id_pix if (id_pix := id_transaccion_pix) else None,
        banco_destino=banco_destino
    )
    return {"diagnostico": diagnostico}


@app.post("/api/vouchers/confirmar")
def confirmar_voucher(payload: VoucherConfirmacion):
    """
    Confirma la conciliación (automática o con desempate de candidato elegido por el usuario).
    1. Guarda en tabla vouchers con estado CONCILIADO.
    2. Bloquea el depósito como USADO.
    3. Sincroniza con Google Sheets (🟢 SÍ).
    """
    es_ant = 1 if payload.fecha_comprobante < datetime.now().strftime("%Y-%m-%d") else 0
    
    # Crear registro voucher
    voucher_data = {
        "grupo_whatsapp_id": payload.grupo_whatsapp_id,
        "grupo_whatsapp_nombre": payload.grupo_whatsapp_nombre,
        "monto": payload.monto,
        "fecha_comprobante": payload.fecha_comprobante,
        "hora_comprobante": payload.hora_comprobante,
        "pagador_nombre": payload.pagador_nombre,
        "pagador_documento": payload.pagador_documento,
        "receptor_nombre": payload.receptor_nombre,
        "receptor_documento": payload.receptor_documento,
        "banco_origen": payload.banco_origen,
        "banco_destino": payload.banco_destino,
        "id_transaccion_pix": payload.id_transaccion_pix,
        "tipo_operacion": payload.tipo_operacion,
        "estado": "CONCILIADO",
        "deposito_asociado_id": payload.deposito_asociado_id,
        "es_fecha_anterior": es_ant,
        "imagen_path": payload.imagen_path,
        "observaciones": payload.observaciones,
        "fecha_conciliacion": datetime.now().isoformat()
    }

    if payload.id:
        vid = payload.id
        db.actualizar_voucher_estado(vid, "CONCILIADO", payload.deposito_asociado_id, payload.observaciones)
    else:
        vid = db.crear_voucher(voucher_data)

    # Actualizar estado de conciliación y bloquear depósito
    reconciler.confirmar_conciliacion_reconciler(
        voucher_id=vid,
        deposito_id=payload.deposito_asociado_id,
        modo=payload.modo or "AUTOMATICO",
        observaciones=payload.observaciones or ""
    )

    # Sincronizar con Google Sheets
    voucher_data["id"] = vid
    sheets_res = sheets_sync.sincronizar_voucher_sheets(voucher_data, estado_display="🟢 SÍ")

    return {
        "success": True,
        "voucher_id": vid,
        "estado": "CONCILIADO",
        "sheets_result": sheets_res
    }


@app.post("/api/vouchers/forzar-si")
def forzar_si_voucher(payload: VoucherConfirmacion):
    """
    BOTÓN DE EMERGENCIA: Permite al usuario aprobar manualmente un voucher
    incluso si aún no aparece en el extracto o si falló la API.
    """
    es_ant = 1 if payload.fecha_comprobante < datetime.now().strftime("%Y-%m-%d") else 0
    obs = (payload.observaciones or "") + " [FORZADO MANUAL POR USUARIO]"

    voucher_data = {
        "grupo_whatsapp_id": payload.grupo_whatsapp_id,
        "grupo_whatsapp_nombre": payload.grupo_whatsapp_nombre,
        "monto": payload.monto,
        "fecha_comprobante": payload.fecha_comprobante,
        "hora_comprobante": payload.hora_comprobante,
        "pagador_nombre": payload.pagador_nombre,
        "pagador_documento": payload.pagador_documento,
        "receptor_nombre": payload.receptor_nombre,
        "receptor_documento": payload.receptor_documento,
        "banco_origen": payload.banco_origen,
        "banco_destino": payload.banco_destino,
        "id_transaccion_pix": payload.id_transaccion_pix,
        "tipo_operacion": payload.tipo_operacion,
        "estado": "FORZADO_MANUAL",
        "deposito_asociado_id": None,
        "es_fecha_anterior": es_ant,
        "imagen_path": payload.imagen_path,
        "observaciones": obs,
        "fecha_conciliacion": datetime.now().isoformat()
    }

    if payload.id:
        vid = payload.id
        db.actualizar_voucher_estado(vid, "FORZADO_MANUAL", None, obs)
    else:
        vid = db.crear_voucher(voucher_data)

    reconciler.confirmar_conciliacion_reconciler(
        voucher_id=vid,
        deposito_id=None,
        modo="FORZADO",
        observaciones=obs
    )

    voucher_data["id"] = vid
    sheets_res = sheets_sync.sincronizar_voucher_sheets(voucher_data, estado_display="🟢 SÍ (MANUAL)")

    return {
        "success": True,
        "voucher_id": vid,
        "estado": "FORZADO_MANUAL",
        "sheets_result": sheets_res
    }


@app.post("/api/vouchers/en-espera")
def guardar_en_espera(payload: VoucherEnEspera):
    """
    Guarda el voucher en la pestaña de Pendientes / En Espera (Rojo).
    Registra también en Google Sheets como 🔴 EN ESPERA.
    """
    voucher_data = {
        "grupo_whatsapp_id": payload.grupo_whatsapp_id,
        "grupo_whatsapp_nombre": payload.grupo_whatsapp_nombre,
        "monto": payload.monto,
        "fecha_comprobante": payload.fecha_comprobante,
        "hora_comprobante": payload.hora_comprobante,
        "pagador_nombre": payload.pagador_nombre,
        "receptor_nombre": payload.receptor_nombre,
        "banco_destino": payload.banco_destino,
        "id_transaccion_pix": payload.id_transaccion_pix,
        "estado": "EN_ESPERA",
        "imagen_path": payload.imagen_path,
        "observaciones": payload.observaciones or "Esperando ingreso de extracto bancario",
        "sheets_synced": 0
    }

    if payload.id:
        vid = payload.id
        db.actualizar_voucher_estado(vid, "EN_ESPERA", None, voucher_data["observaciones"])
    else:
        vid = db.crear_voucher(voucher_data)

    db.registrar_auditoria(vid, "EN_ESPERA", f"Dejado en espera para monto R$ {payload.monto}")

    voucher_data["id"] = vid
    sheets_res = sheets_sync.sincronizar_voucher_sheets(voucher_data, estado_display="🔴 EN ESPERA")

    return {
        "success": True,
        "voucher_id": vid,
        "estado": "EN_ESPERA",
        "sheets_result": sheets_res
    }


@app.get("/api/vouchers/pendientes")
def obtener_pendientes():
    return db.get_vouchers_pendientes()


@app.get("/api/vouchers/historial")
def obtener_historial(limite: int = 150):
    return db.get_vouchers_historial(limite)


# ----------------------------------------------------
# ENDPOINTS: EXTRACTOS BANCARIOS (VÍAS A Y B)
# ----------------------------------------------------
@app.post("/api/extractos/upload")
async def upload_extracto_archivo(
    archivo: UploadFile = File(...),
    banco: Optional[str] = Form("Itaú Unibanco")
):
    """
    Vía B (o manual):
    Sube capturas de pantalla o PDFs del extracto enviados por el socio en Brasil,
    o archivos .OFX / .CSV. La IA o el parser extraen todos los depósitos a la base de datos local.
    """
    contenido = await archivo.read()
    nombre_archivo = archivo.filename or "extracto.jpg"
    ext = Path(nombre_archivo).suffix.lower()
    
    dir_destino = get_directorio_hoy("extractos")
    timestamp = datetime.now().strftime("%H%M%S")
    ruta_guardado = dir_destino / f"ext_{timestamp}_{nombre_archivo}"
    with open(ruta_guardado, "wb") as f:
        f.write(contenido)

    depositos_extraidos: List[Dict[str, Any]] = []

    if ext in [".jpg", ".jpeg", ".png", ".webp", ".pdf"]:
        mime = "application/pdf" if ext == ".pdf" else "image/jpeg"
        depositos_extraidos = ai_vision.extraer_datos_extracto(contenido, mime, banco or "Banco")
    elif ext == ".csv":
        # Parseo simple de CSV bancario
        lineas = contenido.decode("utf-8", errors="ignore").splitlines()
        hoy = datetime.now().strftime("%Y-%m-%d")
        for linea in lineas[1:]:
            partes = linea.split(";") if ";" in linea else linea.split(",")
            if len(partes) >= 3:
                try:
                    m = float(partes[2].replace("R$", "").replace(".", "").replace(",", ".").strip())
                    if m > 0:
                        depositos_extraidos.append({
                            "banco": banco or "Banco",
                            "fecha": partes[0].strip() or hoy,
                            "hora": None,
                            "monto": m,
                            "descripcion": partes[1].strip(),
                            "id_transaccion_pix": None,
                            "tipo": "PIX_IN",
                            "origen_extracto": "CSV"
                        })
                except Exception:
                    continue
    else:
        # Formato no soportado directamente, intentar con IA
        depositos_extraidos = ai_vision.extraer_datos_extracto(contenido, "image/jpeg", banco or "Banco")

    for d in depositos_extraidos:
        d["archivo_fuente"] = str(ruta_guardado.relative_to(BASE_DIR))

    insertados = db.guardar_depositos_extracto(depositos_extraidos)

    return {
        "success": True,
        "insertados": insertados,
        "total_extraidos": len(depositos_extraidos),
        "archivo": nombre_archivo,
        "depositos": depositos_extraidos
    }


@app.post("/api/extractos/import-json")
def import_extracto_json(payload: ExtractoImportJSON):
    """
    Vía A (Extensión de Chrome):
    Recibe directamente las líneas scrapeadas de la pestaña bancaria abierta en la PC del usuario.
    """
    depositos_list = []
    for dep in payload.depositos:
        d = dep.model_dump()
        d["origen_extracto"] = "CHROME_EXTENSION"
        depositos_list.append(d)

    insertados = db.guardar_depositos_extracto(depositos_list)

    return {
        "success": True,
        "insertados": insertados,
        "total_recibidos": len(depositos_list),
        "banco": payload.banco
    }


@app.get("/api/extractos/libres")
def listar_extractos_libres(fecha: Optional[str] = None):
    """Devuelve los depósitos aún disponibles en el 'Bolsón de Depósitos Libres'."""
    return db.get_depositos_libres(fecha)


# ----------------------------------------------------
# ENDPOINTS: DASHBOARD Y MÉTRICAS
# ----------------------------------------------------
@app.get("/api/stats")
def obtener_estadisticas():
    hoy = datetime.now().strftime("%Y-%m-%d")
    return db.get_estadisticas_hoy(hoy)


# ----------------------------------------------------
# SERVIR FRONTEND PWA Y ASSETS
# ----------------------------------------------------
if PWA_DIR.exists():
    app.mount("/pwa", StaticFiles(directory=str(PWA_DIR), html=True), name="pwa")

@app.get("/")
def raiz_redireccion():
    """Redirige al inicio de la PWA móvil."""
    index_file = PWA_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Servidor de Control de Remesas en ejecución. Visita /pwa para la aplicación."}

if __name__ == "__main__":
    import uvicorn
    puerto = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Iniciando Sistema de Remesas en http://{host}:{puerto}")
    uvicorn.run("main:app", host=host, port=puerto, reload=True)
