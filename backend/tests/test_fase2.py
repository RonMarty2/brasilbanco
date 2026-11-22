import importlib
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Configura un entorno aislado con SQLite temporal, auth activa y storage en tmp_path."""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_remesas.db"))
    monkeypatch.setenv("ADMIN_PIN", "1234")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")

    for mod_name in ("database", "reconciler", "sheets_sync", "backup", "main"):
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)

    import backup
    import main

    storage_historial = tmp_path / "storage" / "Historial"
    storage_historial.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "respaldos")
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(main, "STORAGE_HISTORIAL", storage_historial)

    with TestClient(main.app) as test_client:
        yield test_client


def _login(client: TestClient, nombre: str, pin: str) -> dict:
    resp = client.post("/api/auth/login", json={"nombre": nombre, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _primer_grupo(client: TestClient, headers: dict) -> dict:
    resp = client.get("/api/grupos", headers=headers)
    assert resp.status_code == 200, resp.text
    grupos = resp.json()
    assert len(grupos) > 0
    return grupos[0]


def test_imagen_voucher_seguridad_y_entrega(client, tmp_path):
    admin = _login(client, "admin", "1234")
    headers = _auth_headers(admin["token"])

    # Path traversal fuera de storage/Historial -> 403
    r_traversal = client.get("/api/vouchers/imagen", params={"path": "../.env"}, headers=headers)
    assert r_traversal.status_code == 403

    r_traversal_deep = client.get(
        "/api/vouchers/imagen",
        params={"path": "storage/Historial/../../backend/.env"},
        headers=headers,
    )
    assert r_traversal_deep.status_code == 403

    # Archivo inexistente dentro de storage/Historial -> 404
    r_missing = client.get(
        "/api/vouchers/imagen",
        params={"path": "storage/Historial/2026-11-22/vouchers/no_existe.jpg"},
        headers=headers,
    )
    assert r_missing.status_code == 404

    # Archivo real dentro de storage/Historial -> 200 con bytes reales
    img_dir = tmp_path / "storage" / "Historial" / "2026-11-22" / "vouchers"
    img_dir.mkdir(parents=True, exist_ok=True)
    contenido = b"\xff\xd8\xff\xe0FAKE_JPEG_DATA_12345"
    (img_dir / "voucher_ok.jpg").write_bytes(contenido)

    r_ok = client.get(
        "/api/vouchers/imagen",
        params={"path": "storage/Historial/2026-11-22/vouchers/voucher_ok.jpg"},
        headers=headers,
    )
    assert r_ok.status_code == 200
    assert r_ok.content == contenido


def test_anular_voucher_en_espera(client):
    import database as db

    admin = _login(client, "admin", "1234")
    headers = _auth_headers(admin["token"])
    grupo = _primer_grupo(client, headers)

    r_espera = client.post(
        "/api/vouchers/en-espera",
        headers=headers,
        json={
            "monto": 180.50,
            "fecha_comprobante": db.hoy_negocio(),
            "pagador_nombre": "Cliente Espera",
            "grupo_whatsapp_id": grupo["id"],
            "grupo_whatsapp_nombre": grupo["nombre"],
        },
    )
    assert r_espera.status_code == 200, r_espera.text
    vid = r_espera.json()["voucher_id"]

    r_anular = client.post(
        f"/api/vouchers/{vid}/anular",
        headers=headers,
        json={"motivo": "Comprobante duplicado en chat"},
    )
    assert r_anular.status_code == 200, r_anular.text
    data = r_anular.json()
    assert data["success"] is True
    assert data["voucher"]["estado"] == "ANULADO"

    v_db = db.get_voucher_por_id(vid)
    assert v_db is not None
    assert v_db["estado"] == "ANULADO"


def test_reintentar_sheets_sync(client, monkeypatch):
    import database as db
    import sheets_sync

    admin = _login(client, "admin", "1234")
    headers = _auth_headers(admin["token"])
    grupo = _primer_grupo(client, headers)

    # Crear voucher en espera en modo simulado -> sheets_synced queda en 0
    r_espera = client.post(
        "/api/vouchers/en-espera",
        headers=headers,
        json={
            "monto": 350.0,
            "fecha_comprobante": db.hoy_negocio(),
            "pagador_nombre": "Pagador Sync",
            "grupo_whatsapp_id": grupo["id"],
            "grupo_whatsapp_nombre": grupo["nombre"],
        },
    )
    assert r_espera.status_code == 200, r_espera.text
    vid = r_espera.json()["voucher_id"]
    assert db.get_voucher_por_id(vid)["sheets_synced"] == 0

    # Caso 1: Sheets falla -> sigue pendiente y guarda error
    monkeypatch.setattr(
        sheets_sync,
        "sincronizar_voucher_sheets",
        lambda voucher, estado_display="🟢 SÍ": {
            "success": False,
            "simulado": True,
            "error": "Timeout de red",
        },
    )
    r_fail = client.post("/api/sheets/reintentar", headers=headers)
    assert r_fail.status_code == 200, r_fail.text
    assert r_fail.json() == {"intentados": 1, "sincronizados": 0, "pendientes": 1}
    assert db.get_voucher_por_id(vid)["sheets_synced"] == 0
    assert db.get_voucher_por_id(vid)["sheets_sync_error"] == "Timeout de red"

    # Caso 2: Sheets responde OK real -> marca sheets_synced = 1
    monkeypatch.setattr(
        sheets_sync,
        "sincronizar_voucher_sheets",
        lambda voucher, estado_display="🟢 SÍ": {
            "success": True,
            "simulado": False,
            "mensaje": "OK",
        },
    )
    r_ok = client.post("/api/sheets/reintentar", headers=headers)
    assert r_ok.status_code == 200, r_ok.text
    assert r_ok.json() == {"intentados": 1, "sincronizados": 1, "pendientes": 0}
    assert db.get_voucher_por_id(vid)["sheets_synced"] == 1
    assert db.get_voucher_por_id(vid)["sheets_sync_error"] is None


def test_hoy_negocio_formato_yyyy_mm_dd():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import database as db

    hoy = db.hoy_negocio()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", hoy)
