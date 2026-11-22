import importlib
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Configura un entorno aislado con SQLite temporal, auth activa y respaldos en tmp_path."""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_remesas.db"))
    monkeypatch.setenv("ADMIN_PIN", "1234")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")

    for mod_name in ("database", "reconciler", "backup", "main"):
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)

    import backup
    import main

    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "respaldos")

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


def test_1_login_correcto_e_incorrecto(client):
    ok = client.post("/api/auth/login", json={"nombre": "admin", "pin": "1234"})
    assert ok.status_code == 200, ok.text
    data = ok.json()
    assert isinstance(data.get("token"), str) and len(data["token"]) > 0
    assert data.get("nombre") == "admin"
    assert data.get("rol") == "dueno"

    bad = client.post("/api/auth/login", json={"nombre": "admin", "pin": "0000"})
    assert bad.status_code == 401


def test_2_401_sin_token_en_endpoints_protegidos(client):
    assert client.get("/api/stats").status_code == 401
    assert client.get("/api/grupos").status_code == 401
    assert client.get("/api/auth/yo").status_code == 401

    payload_confirmar = {
        "monto": 100.0,
        "fecha_comprobante": "2026-11-22",
        "grupo_whatsapp_id": 1,
        "grupo_whatsapp_nombre": "Canal General",
    }
    assert client.post("/api/vouchers/confirmar", json=payload_confirmar).status_code == 401


def test_3_operador_403_al_intentar_forzar_si(client):
    admin = _login(client, "admin", "1234")
    admin_headers = _auth_headers(admin["token"])

    creado = client.post(
        "/api/auth/usuarios",
        headers=admin_headers,
        json={"nombre": "operador1", "pin": "5678", "rol": "operador"},
    )
    assert creado.status_code in (200, 201), creado.text

    operador = _login(client, "operador1", "5678")
    assert operador["rol"] == "operador"
    op_headers = _auth_headers(operador["token"])

    grupo = _primer_grupo(client, op_headers)
    resp = client.post(
        "/api/vouchers/forzar-si",
        headers=op_headers,
        json={
            "monto": 250.0,
            "fecha_comprobante": datetime.now().strftime("%Y-%m-%d"),
            "grupo_whatsapp_id": grupo["id"],
            "grupo_whatsapp_nombre": grupo["nombre"],
            "modo": "FORZADO",
        },
    )
    assert resp.status_code == 403


def test_4_doble_confirmacion_mismo_deposito_da_409(client):
    import database as db

    admin = _login(client, "admin", "1234")
    headers = _auth_headers(admin["token"])
    grupo = _primer_grupo(client, headers)

    fecha = datetime.now().strftime("%Y-%m-%d")
    insertados = db.guardar_depositos_extracto([
        {
            "banco": "Itaú",
            "fecha": fecha,
            "hora": "10:15:00",
            "monto": 500.0,
            "descripcion": "PIX RECEBIDO TEST",
            "id_transaccion_pix": "E000111222333",
            "origen_extracto": "OFX",
        }
    ])
    assert insertados == 1

    libres = db.get_depositos_libres(fecha)
    assert len(libres) == 1
    deposito_id = libres[0]["id"]

    payload_1 = {
        "monto": 500.0,
        "fecha_comprobante": fecha,
        "hora_comprobante": "10:15",
        "id_transaccion_pix": "E000111222333",
        "grupo_whatsapp_id": grupo["id"],
        "grupo_whatsapp_nombre": grupo["nombre"],
        "deposito_asociado_id": deposito_id,
        "modo": "AUTOMATICO",
    }
    r1 = client.post("/api/vouchers/confirmar", headers=headers, json=payload_1)
    assert r1.status_code == 200, r1.text

    payload_2 = {
        "monto": 500.0,
        "fecha_comprobante": fecha,
        "hora_comprobante": "10:16",
        "id_transaccion_pix": "E999888777666",
        "grupo_whatsapp_id": grupo["id"],
        "grupo_whatsapp_nombre": grupo["nombre"],
        "deposito_asociado_id": deposito_id,
        "modo": "AUTOMATICO",
    }
    r2 = client.post("/api/vouchers/confirmar", headers=headers, json=payload_2)
    assert r2.status_code == 409, r2.text
    assert (
        "Ese depósito ya fue usado por otra operación; vuelve a verificar el cruce"
        in r2.json().get("detail", "")
    )


def test_5_parsers_monto_br_y_fecha():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import parsers

    assert parsers.parse_monto_br("1.250,50") == pytest.approx(1250.50)
    assert parsers.parse_monto_br("1250.50") == pytest.approx(1250.50)
    assert parsers.parse_monto_br("R$ 1.250,50") == pytest.approx(1250.50)
    assert parsers.parse_monto_br("-50,00") == pytest.approx(-50.0)

    assert parsers.parse_fecha("22/11/2026") == "2026-11-22"
    assert parsers.parse_fecha("22/11/26") == "2026-11-22"
    assert parsers.parse_fecha("2026-11-22") == "2026-11-22"


def test_6_parsers_parse_ofx():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import parsers

    ofx_ejemplo = b"""OFXHEADER:100
DATA:OFXSGML
<OFX>
  <BANKMSGSRSV1>
    <STMTTRNRS>
      <STMTRS>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>CREDIT
            <DTPOSTED>20261122143000
            <TRNAMT>1250.50
            <FITID>FITID-PIX-001
            <MEMO>PIX RECEBIDO JOAO
          </STMTTRN>
          <STMTTRN>
            <TRNTYPE>DEBIT
            <DTPOSTED>20261122150000
            <TRNAMT>-300.00
            <FITID>FITID-DEB-002
            <MEMO>PAGAMENTO BOLETO
          </STMTTRN>
        </BANKTRANLIST>
      </STMTRS>
    </STMTTRNRS>
  </BANKMSGSRSV1>
</OFX>
"""
    depositos = parsers.parse_ofx(ofx_ejemplo, banco="Itaú")
    assert len(depositos) == 1
    dep = depositos[0]
    assert dep["banco"] == "Itaú"
    assert dep["monto"] == pytest.approx(1250.50)
    assert dep["fecha"] == "2026-11-22"
    assert dep["hora"] == "14:30:00"
    assert dep["id_transaccion_pix"] == "FITID-PIX-001"
    assert dep["origen_extracto"] == "OFX"


def test_7_dedupe_depositos_sin_hora_y_con_id_pix(client):
    import database as db

    fecha = "2026-11-22"
    dep_sin_hora = {
        "banco": "Nubank",
        "fecha": fecha,
        "hora": None,
        "monto": 320.0,
        "descripcion": "PIX RECEBIDO",
        "id_transaccion_pix": None,
        "origen_extracto": "CSV",
    }
    insertados = db.guardar_depositos_extracto([dict(dep_sin_hora), dict(dep_sin_hora)])
    assert insertados == 2

    libres = db.get_depositos_libres(fecha)
    nubank_deps = [d for d in libres if d["banco"] == "Nubank"]
    assert len(nubank_deps) == 2
    descripciones = [d["descripcion"] for d in nubank_deps]
    assert any("(revisar posible duplicado)" in desc for desc in descripciones)

    dep_con_pix = {
        "banco": "Bradesco",
        "fecha": fecha,
        "hora": "11:00:00",
        "monto": 750.0,
        "descripcion": "PIX CON ID",
        "id_transaccion_pix": "E123456789UNIQUE",
        "origen_extracto": "OFX",
    }
    insertados_pix = db.guardar_depositos_extracto([dict(dep_con_pix), dict(dep_con_pix)])
    assert insertados_pix == 1


def test_8_flujo_cierre_caja_basico(client):
    admin = _login(client, "admin", "1234")
    headers = _auth_headers(admin["token"])
    fecha = "2026-11-22"

    r_get = client.get(f"/api/cierre-caja?fecha={fecha}", headers=headers)
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["estado_caja"] == "ABIERTO"

    r_post = client.post(
        "/api/cierre-caja/cerrar",
        headers=headers,
        json={
            "fecha": fecha,
            "saldo_inicial_brl": 100.0,
            "salidas_brl": 20.0,
            "saldo_final_real_brl": 80.0,
            "observaciones": "Cierre de prueba",
        },
    )
    assert r_post.status_code == 200, r_post.text
    data = r_post.json()
    assert data["success"] is True
    assert data["cierre"]["estado_caja"] == "CERRADO"
