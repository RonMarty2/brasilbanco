# -*- coding: utf-8 -*-
"""METRICAS.csv del plan de delegacion: anotar, poner veredicto, medir tokens de Claude y resumir.

Uso (--sesion = id de ESTA sesion de Claude; obligatorio si hay otras sesiones abiertas):
  python metricas.py veredicto <id> ACEPTADO|CORREGIDO|RECHAZADO "<motivo>" --desde ISO [--hasta ISO] --sesion ID [--calidad N] [--linea-base N]
  python metricas.py claude --desde ISO [--hasta ISO] --sesion ID
  python metricas.py resumen
  python metricas.py base <tipo> "<materia>" "<tema>" --desde ISO [--hasta ISO] --sesion ID   (LINEA BASE: tarea hecha solo por Claude)
"""
import csv, os, sys, json, glob, socket, datetime, time

AQUI = os.path.dirname(os.path.abspath(__file__))


RAIZ = AQUI   # carpeta delegar (todo vive aqui)
CSV_PATH = os.path.join(RAIZ, "METRICAS.csv")
SESIONES = next((p for p in (os.path.join(os.path.expanduser("~"), c, "projects") for c in (".claude-2", ".claude-1", ".claude")) if os.path.isdir(p)), "")
COLS = ["id", "fecha", "hora", "pc", "tipo_tarea", "materia", "tema", "ejecutor", "modelo",
        "tokens_ejecutor", "tokens_claude", "tokens_claude_cache", "minutos", "chequeo_auto",
        "veredicto", "motivo", "calidad_docente", "linea_base", "ahorro", "carpeta", "fuera_de_cerco"]


def leer():
    if not os.path.exists(CSV_PATH):
        return []
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def escribir(filas):
    # Nunca "w" sobre el original: .tmp + os.replace (REGLA 0-BIS). ";" para Excel en espanol.
    tmp = CSV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in filas:
            w.writerow(r)
    for _ in range(10):                 # Synology o Excel pueden tener el archivo tomado un momento
        try:
            os.replace(tmp, CSV_PATH)
            return
        except PermissionError:
            time.sleep(2)
    raise SystemExit("[!] METRICAS.csv bloqueado (¿abierto en Excel?). Cierralo y repite. El .tmp quedo con los datos.")


def agregar(fila):
    filas = leer()
    base = {c: "" for c in COLS}
    ahora = datetime.datetime.now()
    base.update({"fecha": ahora.strftime("%Y-%m-%d"), "hora": ahora.strftime("%H:%M"), "pc": socket.gethostname()})
    base.update({k: str(v) for k, v in fila.items()})
    filas.append(base)
    escribir(filas)
    return base


def tokens_claude(desde_iso, sesion=None, hasta_iso=None):
    """Tokens de Claude en una ventana de tiempo. Devuelve (normales, cache_leida).
    Sin --sesion toma la sesion mas reciente: con otras sesiones abiertas MIDE LA EQUIVOCADA (error del 01-11)."""
    archivos = glob.glob(os.path.join(SESIONES, "*", (sesion or "*") + ".jsonl"))
    if not archivos:
        return None, None
    ses = max(archivos, key=os.path.getmtime)
    desde = datetime.datetime.fromisoformat(desde_iso).astimezone(datetime.timezone.utc)
    hasta = datetime.datetime.fromisoformat(hasta_iso).astimezone(datetime.timezone.utc) if hasta_iso else None
    vistos, normal, cache = set(), 0, 0
    with open(ses, encoding="utf-8", errors="replace") as f:
        for linea in f:
            try:
                e = json.loads(linea)
            except Exception:
                continue
            msg = e.get("message") or {}
            u = msg.get("usage") if isinstance(msg, dict) else None
            ts = e.get("timestamp")
            if not u or not ts:
                continue
            t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if t < desde or (hasta and t > hasta):
                continue
            mid = msg.get("id") or e.get("uuid")
            if mid in vistos:
                continue
            vistos.add(mid)
            normal += u.get("input_tokens", 0) + u.get("output_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            cache += u.get("cache_read_input_tokens", 0)
    return normal, cache


def entero(x):
    try:
        return int(float(x))
    except Exception:
        return None


def opciones(args):
    return dict(zip(args[0::2], args[1::2]))


def veredicto(args):
    rid, ver, motivo = args[0], args[1].upper(), args[2]
    op = opciones(args[3:])
    filas = leer()
    for r in filas:
        if r["id"] == rid:
            r["veredicto"], r["motivo"] = ver, motivo
            if "--desde" in op:
                n, c = tokens_claude(op["--desde"], op.get("--sesion"), op.get("--hasta"))
                r["tokens_claude"], r["tokens_claude_cache"] = n, c
            if "--calidad" in op:
                r["calidad_docente"] = op["--calidad"]
            if "--linea-base" in op:
                r["linea_base"] = op["--linea-base"]
            lb, tc = entero(r["linea_base"]), entero(r["tokens_claude"])
            if lb is not None and tc is not None:
                r["ahorro"] = lb - tc
            escribir(filas)
            print("anotado:", {k: r[k] for k in ("id", "veredicto", "tokens_claude", "ahorro")})
            return
    raise SystemExit("no existe el id " + rid)


def resumen():
    filas = leer()
    if not filas:
        print("METRICAS.csv vacio")
        return
    print(f"{'tipo':22} {'n':>3} {'acept%':>7} {'tok_agy':>9} {'tok_claude':>11} {'base':>8} {'ahorro':>8}")
    for t in sorted({r["tipo_tarea"] for r in filas}):
        rs = [r for r in filas if r["tipo_tarea"] == t and r["ejecutor"] != "claude-base"]
        bs = [x for x in (entero(r["tokens_claude"]) for r in filas if r["tipo_tarea"] == t and r["ejecutor"] == "claude-base") if x is not None]
        dec = [r for r in rs if r["veredicto"] in ("ACEPTADO", "CORREGIDO", "RECHAZADO")]
        acep = sum(r["veredicto"] == "ACEPTADO" for r in dec)
        pct = f"{100*acep/len(dec):.0f}" if dec else "-"
        prom = lambda xs: (sum(xs) // len(xs)) if xs else "-"
        ta = prom([x for x in (entero(r["tokens_ejecutor"]) for r in rs) if x is not None])
        tc = prom([x for x in (entero(r["tokens_claude"]) for r in rs) if x is not None])
        base = prom(bs)
        ah = (base - tc) if isinstance(base, int) and isinstance(tc, int) else "-"
        print(f"{t:22} {len(rs):>3} {pct:>7} {ta:>9} {tc:>11} {base:>8} {ah:>8}")
        ult = dec[-5:]
        if len(ult) == 5 and sum(r["veredicto"] == "ACEPTADO" for r in ult) >= 4:
            print(f"   -> REGLA: {t} acepta >=80% en las ultimas 5: Claude puede revisar solo una MUESTRA")
        motivos = [r["motivo"].strip().lower() for r in dec if r["veredicto"] == "RECHAZADO"]
        for m in set(motivos):
            if motivos.count(m) >= 2:
                print(f"   -> REGLA: rechazo repetido ({m!r}): corregir la INSTRUCCION del agente")
        if isinstance(ah, int) and ah <= 0:
            print(f"   -> REGLA: {t} no ahorra (ahorro {ah}): no delegar o delegar solo una parte")
        if any(r["fuera_de_cerco"] not in ("", "0") for r in rs):
            print(f"   -> ALERTA: {t} tiene ejecuciones que escribieron FUERA de _TRABAJO_AGY (mirar: puede ser otra sesion)")


def base_claude(args):
    tipo, materia, tema = args[0], args[1], args[2]
    op = opciones(args[3:])
    n, c = tokens_claude(op["--desde"], op.get("--sesion"), op.get("--hasta"))
    r = agregar({"id": "BASE-" + datetime.datetime.now().strftime("%Y%m%d-%H%M"), "tipo_tarea": tipo, "materia": materia,
                 "tema": tema, "ejecutor": "claude-base", "modelo": "claude", "tokens_claude": n,
                 "tokens_claude_cache": c, "veredicto": "LINEA BASE"})
    print("linea base anotada:", r["id"], n, "tokens (+", c, "de cache)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd, resto = sys.argv[1], sys.argv[2:]
    if cmd == "veredicto":
        veredicto(resto)
    elif cmd == "claude":
        op = opciones(resto)
        print(tokens_claude(op["--desde"], op.get("--sesion"), op.get("--hasta")))
    elif cmd == "resumen":
        resumen()
    elif cmd == "base":
        base_claude(resto)
    else:
        print(__doc__)
