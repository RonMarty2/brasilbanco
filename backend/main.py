import os
import shutil
import json
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Importar módulos del sistema
import database as db
import ai_vision
import reconciler
import sheets_sync
import parsers
import backup

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
EXTENSIONES_IMAGEN_PDF = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        backup.respaldar()
    except Exception as e:
        print(f"[BACKUP] No se pudo crear respaldo inicial: {e}")
    yield


app = FastAPI(
    title="Sistema Semi-Automático de Conciliación de Remesas (Brasil ⇄ Bolivia)",
    version="1.0.0",
    description="Backend FastAPI con SQLite, Gemini Vision y Google Sheets",
    lifespan=lifespan,
)

# Configurar CORS para permitir comunicación con PWA y Extensión de Chrome
_cors_env = os.getenv("CORS_ORIGINS", "*")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas de almacenamiento
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_HISTORIAL = BASE_DIR / "storage" / "Historial"
STORAGE_HISTORIAL.mkdir(parents=True, exist_ok=True)
PWA_DIR = BASE_DIR / "frontend_pwa"


def get_directorio_hoy(subtipo: str = "vouchers") -> Path:
    hoy = db.hoy_negocio()
    d = STORAGE_HISTORIAL / hoy / subtipo
    d.mkdir(parents=True, exist_ok=True)
    return d


def _estado_display_sheets(estado: str) -> str:
    return {
        "CONCILIADO": "🟢 SÍ",
        "FORZADO_MANUAL": "🟢 SÍ (MANUAL)",
        "EN_ESPERA": "🔴 EN ESPERA",
        "ANULADO": "⚪ ANULADO",
    }.get(estado, estado or "PENDIENTE")


def _sincronizar_y_marcar_sheets(voucher: Dict[str, Any], estado_display: str) -> Dict[str, Any]:
    sheets_res = sheets_sync.sincronizar_voucher_sheets(voucher, estado_display=estado_display)
    vid = voucher.get("id")
    if vid is not None:
        db.marcar_sheets_sync(
            int(vid),
            bool(sheets_res.get("success") and not sheets_res.get("simulado")),
            sheets_res.get("error"),
        )
    return sheets_res


# ----------------------------------------------------
# AUTENTICACIÓN Y ROLES
# ----------------------------------------------------
def usuario_actual(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    if os.getenv("AUTH_DISABLED", "false").lower() in ("1", "true", "yes"):
        return {"id": 0, "nombre": "Back-office", "rol": "dueno"}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    user = db.get_usuario_por_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return user


def requerir_roles(*roles: str):
    def _verificar_rol(user: Dict[str, Any] = Depends(usuario_actual)) -> Dict[str, Any]:
        if user.get("rol") not in roles:
            raise HTTPException(status_code=403, detail="No tienes permisos para realizar esta acción")
        return user
    return _verificar_rol


# ----------------------------------------------------
# MODELOS DE ENTRADA
# ----------------------------------------------------
class LoginRequest(BaseModel):
    nombre: str
    pin: str

class UsuarioCreate(BaseModel):
    nombre: str
    pin: str
    rol: str = "operador"

class GrupoCreate(BaseModel):
    nombre: str
    color: Optional[str] = "#10B981"

class VoucherConfirmacion(BaseModel):
    id: Optional[int] = None
    monto: float = Field(gt=0)
    fecha_comprobante: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
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
    monto: float = Field(gt=0)
    fecha_comprobante: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
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
    banco: Optional[str] = None
    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hora: Optional[str] = None
    monto: float = Field(gt=0)
    descripcion: str
    id_transaccion_pix: Optional[str] = None
    tipo: Optional[str] = "PIX_IN"

class ExtractoImportJSON(BaseModel):
    banco: str
    depositos: List[DepositoItem]

class AnularVoucherRequest(BaseModel):
    motivo: Optional[str] = "Corrección manual"

class CierreCajaRequest(BaseModel):
    fecha: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    saldo_inicial_brl: float = 0.0
    salidas_brl: float = 0.0
    saldo_final_real_brl: Optional[float] = None
    observaciones: Optional[str] = ""


# ----------------------------------------------------
# ENDPOINTS: AUTENTICACIÓN
# ----------------------------------------------------
@app.post("/api/auth/login")
def login(payload: LoginRequest):
    sesion = db.autenticar_usuario(payload.nombre, payload.pin)
    if not sesion:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    return sesion


@app.get("/api/auth/yo")
def quien_soy(user: Dict[str, Any] = Depends(usuario_actual)):
    return user


@app.post("/api/auth/usuarios")
def crear_nuevo_usuario(
    payload: UsuarioCreate,
    user: Dict[str, Any] = Depends(requerir_roles("dueno"))
):
    if payload.rol not in ("dueno", "supervisor", "operador"):
        raise HTTPException(status_code=400, detail="Rol inválido. Debe ser dueno, supervisor u operador")
    try:
        return db.crear_usuario(payload.nombre, payload.pin, payload.rol)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese nombre")


# ----------------------------------------------------
# ENDPOINTS: GRUPOS DE WHATSAPP
# ----------------------------------------------------
@app.get("/api/grupos")
def listar_grupos(user: Dict[str, Any] = Depends(usuario_actual)):
    return db.get_grupos()

@app.post("/api/grupos")
def crear_nuevo_grupo(grupo: GrupoCreate, user: Dict[str, Any] = Depends(usuario_actual)):
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
    grupo_whatsapp_nombre: Optional[str] = Form("General"),
    user: Dict[str, Any] = Depends(usuario_actual)
):
    """
    1. Guarda el archivo en storage/Historial/YYYY-MM-DD/vouchers/
    2. Lo procesa con Gemini Vision (ai_vision)
    3. Cruza inmediatamente con el motor reconciler
    4. Devuelve los campos editables + diagnóstico al frontend (Human-in-the-Loop)
    """
    contenido = await archivo.read()
    if len(contenido) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máximo 10 MB)")
    mime_type = archivo.content_type or "image/jpeg"
    nombre_limpio = Path(archivo.filename or "voucher.jpg").name
    ext = Path(nombre_limpio).suffix or ".jpg"
    
    # Guardar archivo físicamente
    dir_destino = get_directorio_hoy("vouchers")
    timestamp = db.ahora_negocio().strftime("%H%M%S_%f")
    nombre_guardado = f"voucher_{timestamp}{ext}"
    ruta_guardado = dir_destino / nombre_guardado
    with open(ruta_guardado, "wb") as f:
        f.write(contenido)

    # 1. Extraer datos con Gemini Vision
    try:
        datos_ia = ai_vision.extraer_datos_voucher(contenido, mime_type)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    monto = float(datos_ia.get("monto", 0.0) or 0.0)
    fecha_comprobante = datos_ia.get("fecha") or db.hoy_negocio()
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
    banco_destino: Optional[str] = Form(None),
    user: Dict[str, Any] = Depends(usuario_actual)
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
def confirmar_voucher(
    payload: VoucherConfirmacion,
    user: Dict[str, Any] = Depends(usuario_actual)
):
    """
    Confirma la conciliación (automática o con desempate de candidato elegido por el usuario).
    1. Guarda en tabla vouchers con estado CONCILIADO.
    2. Bloquea el depósito como USADO.
    3. Sincroniza con Google Sheets (🟢 SÍ).
    """
    es_ant = 1 if payload.fecha_comprobante < db.hoy_negocio() else 0
    
    # Crear registro voucher
    voucher_data = {
        "id": payload.id,
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
        "fecha_conciliacion": db.ahora_negocio().isoformat()
    }

    try:
        vid = db.crear_y_conciliar_voucher(
            voucher_data,
            payload.deposito_asociado_id,
            payload.modo or "AUTOMATICO",
            payload.observaciones or "",
            usuario=user["nombre"]
        )
    except db.DepositoNoDisponible:
        raise HTTPException(
            status_code=409,
            detail="Ese depósito ya fue usado por otra operación; vuelve a verificar el cruce"
        )

    # Sincronizar con Google Sheets
    voucher_data["id"] = vid
    sheets_res = _sincronizar_y_marcar_sheets(voucher_data, estado_display="🟢 SÍ")

    return {
        "success": True,
        "voucher_id": vid,
        "estado": "CONCILIADO",
        "sheets_result": sheets_res
    }


@app.post("/api/vouchers/forzar-si")
def forzar_si_voucher(
    payload: VoucherConfirmacion,
    user: Dict[str, Any] = Depends(requerir_roles("dueno", "supervisor"))
):
    """
    BOTÓN DE EMERGENCIA: Permite al usuario aprobar manualmente un voucher
    incluso si aún no aparece en el extracto o si falló la API.
    """
    es_ant = 1 if payload.fecha_comprobante < db.hoy_negocio() else 0
    obs = (payload.observaciones or "") + " [FORZADO MANUAL POR USUARIO]"

    voucher_data = {
        "id": payload.id,
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
        "fecha_conciliacion": db.ahora_negocio().isoformat()
    }

    vid = db.crear_y_conciliar_voucher(
        voucher_data,
        None,
        "FORZADO",
        obs,
        usuario=user["nombre"]
    )

    voucher_data["id"] = vid
    sheets_res = _sincronizar_y_marcar_sheets(voucher_data, estado_display="🟢 SÍ (MANUAL)")

    return {
        "success": True,
        "voucher_id": vid,
        "estado": "FORZADO_MANUAL",
        "sheets_result": sheets_res
    }


@app.post("/api/vouchers/en-espera")
def guardar_en_espera(
    payload: VoucherEnEspera,
    user: Dict[str, Any] = Depends(usuario_actual)
):
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

    db.registrar_auditoria(
        vid,
        "EN_ESPERA",
        f"Dejado en espera para monto R$ {payload.monto}",
        usuario=user["nombre"]
    )

    voucher_data["id"] = vid
    sheets_res = _sincronizar_y_marcar_sheets(voucher_data, estado_display="🔴 EN ESPERA")

    return {
        "success": True,
        "voucher_id": vid,
        "estado": "EN_ESPERA",
        "sheets_result": sheets_res
    }


@app.get("/api/vouchers/pendientes")
def obtener_pendientes(user: Dict[str, Any] = Depends(usuario_actual)):
    return db.get_vouchers_pendientes()


@app.get("/api/vouchers/historial")
def obtener_historial(limite: int = 150, user: Dict[str, Any] = Depends(usuario_actual)):
    return db.get_vouchers_historial(limite)


@app.get("/api/vouchers/imagen")
def obtener_imagen_voucher(path: str, user: Dict[str, Any] = Depends(usuario_actual)):
    """Devuelve la imagen o PDF de un voucher guardado verificando estrictamente la ruta."""
    storage_root = STORAGE_HISTORIAL.resolve()
    ruta = (BASE_DIR / path).resolve()
    if ruta == storage_root or not ruta.is_relative_to(storage_root):
        raise HTTPException(status_code=403, detail="Ruta no permitida")
    if not ruta.exists() or not ruta.is_file():
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    return FileResponse(ruta)


# ----------------------------------------------------
# ENDPOINTS: EXTRACTOS BANCARIOS (VÍAS A Y B)
# ----------------------------------------------------
@app.post("/api/extractos/upload")
async def upload_extracto_archivo(
    archivo: UploadFile = File(...),
    banco: Optional[str] = Form("Itaú Unibanco"),
    user: Dict[str, Any] = Depends(usuario_actual)
):
    """
    Vía B (o manual):
    Sube capturas de pantalla o PDFs del extracto enviados por el socio en Brasil,
    o archivos .OFX / .CSV. La IA o el parser extraen todos los depósitos a la base de datos local.
    """
    contenido = await archivo.read()
    if len(contenido) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máximo 10 MB)")
    nombre_archivo = Path(archivo.filename or "extracto.jpg").name
    ext = Path(nombre_archivo).suffix.lower()

    if ext not in EXTENSIONES_IMAGEN_PDF and ext not in (".csv", ".ofx"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato de archivo no soportado: {ext or 'sin extensión'}. Usa imagen, PDF, CSV u OFX."
        )

    dir_destino = get_directorio_hoy("extractos")
    timestamp = db.ahora_negocio().strftime("%H%M%S")
    ruta_guardado = dir_destino / f"ext_{timestamp}_{nombre_archivo}"
    with open(ruta_guardado, "wb") as f:
        f.write(contenido)

    depositos_extraidos: List[Dict[str, Any]] = []

    if ext in EXTENSIONES_IMAGEN_PDF:
        mime = "application/pdf" if ext == ".pdf" else "image/jpeg"
        try:
            depositos_extraidos = ai_vision.extraer_datos_extracto(contenido, mime, banco or "Banco")
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e))
    elif ext == ".csv":
        depositos_extraidos = parsers.parse_csv(contenido, banco or "Banco")
    elif ext == ".ofx":
        depositos_extraidos = parsers.parse_ofx(contenido, banco or "Banco")

    for d in depositos_extraidos:
        d["archivo_fuente"] = str(ruta_guardado.relative_to(BASE_DIR))

    insertados = db.guardar_depositos_extracto(depositos_extraidos)
    recruce = reconciler.recruzar_pendientes_automatico(usuario=user["nombre"])

    return {
        "success": True,
        "insertados": insertados,
        "total_extraidos": len(depositos_extraidos),
        "archivo": nombre_archivo,
        "depositos": depositos_extraidos,
        "recruce_pendientes": recruce
    }


@app.post("/api/extractos/import-json")
def import_extracto_json(
    payload: ExtractoImportJSON,
    user: Dict[str, Any] = Depends(usuario_actual)
):
    """
    Vía A (Extensión de Chrome):
    Recibe directamente las líneas scrapeadas de la pestaña bancaria abierta en la PC del usuario.
    """
    depositos_list = []
    for dep in payload.depositos:
        d = dep.model_dump()
        if not d.get("banco"):
            d["banco"] = payload.banco
        d["origen_extracto"] = "CHROME_EXTENSION"
        depositos_list.append(d)

    insertados = db.guardar_depositos_extracto(depositos_list)
    recruce = reconciler.recruzar_pendientes_automatico(usuario=user["nombre"])

    return {
        "success": True,
        "insertados": insertados,
        "total_recibidos": len(depositos_list),
        "banco": payload.banco,
        "recruce_pendientes": recruce
    }


@app.get("/api/extractos/libres")
def listar_extractos_libres(
    fecha: Optional[str] = None,
    user: Dict[str, Any] = Depends(usuario_actual)
):
    """Devuelve los depósitos aún disponibles en el 'Bolsón de Depósitos Libres'."""
    return db.get_depositos_libres(fecha)


# ----------------------------------------------------
# ENDPOINTS: ANULACIÓN, RECRUCE Y CIERRE DE CAJA
# ----------------------------------------------------
@app.post("/api/vouchers/{voucher_id}/anular")
def anular_voucher_endpoint(
    voucher_id: int,
    payload: Optional[AnularVoucherRequest] = None,
    user: Dict[str, Any] = Depends(requerir_roles("dueno", "supervisor"))
):
    motivo = payload.motivo if payload else "Corrección manual"
    res = db.anular_voucher(voucher_id, motivo, usuario=user["nombre"])
    if not res["success"]:
        raise HTTPException(status_code=404, detail=res.get("error", "Voucher no encontrado"))
    _sincronizar_y_marcar_sheets(res["voucher"], estado_display="⚪ ANULADO")
    return res


@app.post("/api/vouchers/recruzar-pendientes")
def recruzar_pendientes_endpoint(user: Dict[str, Any] = Depends(usuario_actual)):
    return reconciler.recruzar_pendientes_automatico(usuario=user["nombre"])


@app.post("/api/sheets/reintentar")
def reintentar_sync_sheets(user: Dict[str, Any] = Depends(usuario_actual)):
    """Reintenta sincronizar con Google Sheets los vouchers con sheets_synced = 0."""
    pendientes_sync = db.get_vouchers_sin_sync_sheets()
    sincronizados = 0
    for v in pendientes_sync:
        estado_display = _estado_display_sheets(v.get("estado", ""))
        sheets_res = _sincronizar_y_marcar_sheets(v, estado_display=estado_display)
        if sheets_res.get("success") and not sheets_res.get("simulado"):
            sincronizados += 1
    intentados = len(pendientes_sync)
    return {
        "intentados": intentados,
        "sincronizados": sincronizados,
        "pendientes": intentados - sincronizados,
    }


@app.get("/api/cierre-caja")
def obtener_cierre_caja(
    fecha: Optional[str] = None,
    user: Dict[str, Any] = Depends(usuario_actual)
):
    fecha_obj = fecha or db.hoy_negocio()
    return db.get_resumen_cierre_dia(fecha_obj)


@app.post("/api/cierre-caja/cerrar")
def cerrar_caja_dia(
    payload: CierreCajaRequest,
    user: Dict[str, Any] = Depends(requerir_roles("dueno", "supervisor"))
):
    fecha_obj = payload.fecha or db.hoy_negocio()
    resumen = db.guardar_cierre_caja(
        fecha=fecha_obj,
        saldo_inicial_brl=payload.saldo_inicial_brl,
        salidas_brl=payload.salidas_brl,
        saldo_final_real_brl=payload.saldo_final_real_brl,
        observaciones=payload.observaciones or ""
    )
    try:
        backup.respaldar()
    except Exception as e:
        print(f"[BACKUP] No se pudo respaldar al cerrar caja: {e}")
    sheets_res = sheets_sync.sincronizar_cierre_sheets(resumen)
    return {"success": True, "cierre": resumen, "sheets_result": sheets_res}


@app.get("/api/cierre-caja/historial")
def obtener_historial_cierres(
    limite: int = 30,
    user: Dict[str, Any] = Depends(usuario_actual)
):
    return db.get_historial_cierres(limite)


# ----------------------------------------------------
# ENDPOINTS: DASHBOARD Y MÉTRICAS
# ----------------------------------------------------
@app.get("/api/stats")
def obtener_estadisticas(user: Dict[str, Any] = Depends(usuario_actual)):
    hoy = db.hoy_negocio()
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
    uvicorn.run("main:app", host=host, port=puerto, reload=os.getenv("DEBUG") == "1")
