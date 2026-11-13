# -*- coding: utf-8 -*-
"""Ejecutor unico: delega una tarea a agy (Gemini), corre lo mecanico por script y deja a Claude solo el DIFF y los CONTROLES.

Uso:
  python agy_run.py --tipo <tipo> --nivel mecanico|lectura|criterio|criterio-alto --pedido <archivo.md>
                    [--materia X] [--tema Y] [--leer <carpeta>]... [--copiar <carpeta>]...
                    [--despues "<comando>"]... [--solo-texto] [--timeout 900]

MODO COPIA (el que ahorra): --copiar <carpeta del tema> copia esa carpeta a _TRABAJO_AGY\<id>\copia\<nombre>\.
  agy edita SOLO la copia. Despues el script (sin gastar modelo) corre cada --despues dentro de la copia
  (regenerar, compilar, controles; {copia} se reemplaza por la ruta de la copia), y escribe:
    DIFF.txt       lineas cambiadas, ENTERAS (un diff que trunca no es un diff)
    CONTROLES.txt  salida de cada --despues
  Claude revisa ENTREGA.json + DIFF.txt + CONTROLES.txt. Si acepta: python aplicar.py <id>.
"""
import argparse, os, sys, json, time, subprocess, datetime, importlib.util, shutil, hashlib, difflib, re

AQUI = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("metricas", os.path.join(AQUI, "metricas.py"))
metricas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metricas)

RAIZ = metricas.RAIZ   # ...\brasilbanco\delegar
TRABAJO = os.path.join(RAIZ, "_TRABAJO_AGY")
ARRANQUE = os.path.join(RAIZ, "_agy_candado")                         # agy arranca aqui: agentes + reglas + candado
PROYECTO = os.path.dirname(RAIZ)   # brasilbanco
AGY = os.path.join(os.path.expanduser("~"), "AppData", "Local", "agy", "bin", "agy.exe")
VIGILAR = [PROYECTO]
IGNORAR_DIRS = {"node_modules", "_TRABAJO_AGY", "venv", "sesiones", "Historial", "__pycache__", "herramientas", "frames"}
TEXTO_EXT = {".md", ".py", ".txt", ".csv", ".json", ".jsonl", ".html", ".js", ".bat"}

MODELOS = {"mecanico": "Gemini 3.8 Flash (Low)",
           "lectura": "Gemini 3.8 Flash (Medium)",
           "criterio": "Gemini 4 Argon (Medium)",
           "criterio-alto": "Gemini 4 Argon (High)"}

REGLAS_AGY = """
REGLAS FIJAS (no negociables):
1. Solo puedes crear o editar archivos dentro de: {carpeta}
   {regla_copia}Las carpetas de referencia se pueden LEER, nunca modificar.
   LA TERMINAL ESTA BLOQUEADA: no uses run_command (ni PowerShell, ni Get-ChildItem, ni python).
   Usa SOLO herramientas de archivos: list_dir, find_by_name, grep_search, view_file, write_to_file, replace_file_content.
   Si una accion es denegada, NO te detengas: sigue con las herramientas de archivos hasta terminar.
2. Espanol neutro, trato de tu.
3. No inventes datos, cifras ni fuentes. Si no sabes algo, escribe "NO SE" o "NO VERIFICADO".
4. Haz SOLO lo que pide la tarea. No reformatees, no reordenes ni "mejores" lo que no se pidio.
5. Al terminar, escribe ENTREGA_AGY.md en {carpeta} con: (a) que hiciste, (b) archivos que cambiaste,
   (c) que comprobaste y como, (d) dudas o lo que no pudiste hacer. Breve.
"""


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def copiar_tema(origen, destino):
    """Copia la carpeta (sin __pycache__) y registra el hash de cada archivo original (para que aplicar.py no pise cambios ajenos)."""
    # Sin audio/video/zip: en Proyectos II eran 1,2 GB de 1,2 GB. Se copia el nivel que contiene lo que el
    # generador importa (01-11: S6 importa calc_s5 de la carpeta vecina; copiar solo S6 rompio el generador).
    shutil.copytree(origen, destino, ignore=shutil.ignore_patterns(
        "__pycache__", "*.tmp", "_VIEJO", "*.mp3", "*.mp4", "*.wav", "*.m4a", "*.webm", "*.zip", "*.exe", "*.db", "venv", "sesiones", "herramientas"))
    hashes = {}
    for raiz, dirs, archivos in os.walk(origen):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for a in archivos:
            p = os.path.join(raiz, a)
            hashes[os.path.relpath(p, origen)] = sha(p)
    return hashes


def diff_copia(origen, copia):
    """Lista de archivos cambiados/nuevos y diff completo (sin truncar) de los de texto."""
    cambiados, partes = [], []
    for raiz, dirs, archivos in os.walk(copia):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for a in archivos:
            pc = os.path.join(raiz, a)
            rel = os.path.relpath(pc, copia)
            po = os.path.join(origen, rel)
            if os.path.exists(po) and sha(po) == sha(pc):
                continue
            cambiados.append(rel)
            if os.path.splitext(a)[1].lower() in TEXTO_EXT:
                vo = open(po, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(po) else []
                vn = open(pc, encoding="utf-8", errors="replace").read().splitlines()
                partes.append("\n".join(difflib.unified_diff(vo, vn, "ORIGINAL/" + rel, "COPIA/" + rel, n=1, lineterm="")))
            else:
                partes.append(f"--- binario cambiado o nuevo: {rel}")
    return cambiados, "\n\n".join(partes)


def cambios_fuera(desde_ts, carpeta_propia):
    malos = []
    for base in VIGILAR:
        for raiz, dirs, archivos in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in IGNORAR_DIRS]
            for a in archivos:
                p = os.path.join(raiz, a)
                try:
                    if os.path.getmtime(p) > desde_ts and not p.startswith(carpeta_propia):
                        malos.append(p)
                except OSError:
                    pass
    return malos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tipo", default="")
    ap.add_argument("--nivel", default="", choices=[""] + list(MODELOS))
    ap.add_argument("--pedido", required=True)
    ap.add_argument("--materia", default="")
    ap.add_argument("--tema", default="")
    ap.add_argument("--leer", action="append", default=[])
    ap.add_argument("--copiar", action="append", default=[])
    ap.add_argument("--despues", action="append", default=[])
    ap.add_argument("--solo-texto", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--seguir", default="", help="id de una entrega: corrige en LA MISMA conversacion de agy (paso 3)")
    a = ap.parse_args()

    previo, vuelta = None, 1
    if a.seguir:
        # PASO 3 (01-11): la correccion va en la MISMA conversacion (--conversation): agy ya tiene el pedido, las reglas,
        # lo que leyo y lo que hizo. El pedido nuevo es solo lo que hay que corregir. Misma carpeta, misma copia.
        carpeta = os.path.join(TRABAJO, a.seguir)
        previo = json.load(open(os.path.join(carpeta, "ENTREGA.json"), encoding="utf-8"))
        if not previo.get("conversation_id"):
            sys.exit("ALTO: esa entrega no guardo conversation_id (es anterior al paso 3). Haz un pedido nuevo.")
        vuelta = len(previo.get("vueltas") or []) + 2
        rid = f"{a.seguir}_v{vuelta}"
        a.leer = a.leer or previo.get("leer") or []
        a.solo_texto = a.solo_texto or previo.get("solo_texto", False)
        a.despues = a.despues or previo.get("despues") or []
        a.materia, a.tema = a.materia or previo.get("materia", ""), a.tema or previo.get("tema", "")
        a.tipo = a.tipo or previo.get("tipo", "")
    else:
        if not a.tipo or not a.nivel:
            sys.exit("Falta --tipo y --nivel (solo se pueden omitir con --seguir).")
        rid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "_" + a.tipo
        carpeta = os.path.join(TRABAJO, rid)
        os.makedirs(carpeta, exist_ok=True)
    suf = f"_v{vuelta}" if vuelta > 1 else ""

    # --- modo copia
    copias = []
    if previo and os.path.exists(os.path.join(carpeta, "COPIAS.json")):
        copias = json.load(open(os.path.join(carpeta, "COPIAS.json"), encoding="utf-8"))   # hashes del ORIGINAL, de la 1.a vuelta
    for origen in ([] if previo else a.copiar):
        origen = os.path.abspath(origen)
        destino = os.path.join(carpeta, "copia", os.path.basename(origen))
        hashes = copiar_tema(origen, destino)
        copias.append({"origen": origen, "copia": destino, "hashes": hashes})
    regla_copia = ""
    if copias:
        regla_copia = ("EDITA SOLO LAS COPIAS: " + "; ".join(c["copia"] for c in copias) +
                       ". Son copias exactas del material: trabaja sobre ellas como si fueran el original.\n   ")

    pedido = open(a.pedido, encoding="utf-8").read()
    # 02-11-2026 (igual que el motor de UNIFRANZ): en --solo-texto agy corre en modo plan y NO puede escribir.
    # La regla 5 le pedia escribir ENTREGA_AGY.md -> se le negaba -> respuesta VACIA. En solo-texto el informe va en la respuesta.
    SOLO_TEXTO_FIN = ("NO escribas ningun archivo (no tienes permiso de escritura). Entrega TODO tu informe "
                      "completo como texto en tu respuesta final.")
    if previo:
        fin = SOLO_TEXTO_FIN if a.solo_texto else (
            f"Al terminar, actualiza ENTREGA_AGY.md (agrega una seccion 'Vuelta {vuelta}' con lo que corregiste).")
        texto = ("CORRECCION de Claude sobre tu entrega anterior (misma tarea, mismas reglas, misma carpeta "
                 f"{carpeta}). Corrige SOLO esto:\n\n{pedido}\n\n{fin}")
    else:
        reglas = REGLAS_AGY.format(carpeta=carpeta, regla_copia=regla_copia)
        if a.solo_texto:
            reglas = re.sub(r"5\. Al terminar, escribe ENTREGA_AGY\.md.*?Breve\.", "5. " + SOLO_TEXTO_FIN, reglas, flags=re.S)
        texto = pedido + "\n" + reglas
        if a.leer:
            texto += "\nCarpetas de referencia (solo leer):\n" + "\n".join("- " + p for p in a.leer)
    with open(os.path.join(carpeta, f"PEDIDO{suf}.md"), "w", encoding="utf-8") as f:
        f.write(texto)

    modelo = previo["modelo"] if previo and not a.nivel else MODELOS[a.nivel]
    cmd = [AGY, "--sandbox", "--model", modelo, "--mode", "plan" if a.solo_texto else "accept-edits",
           "--output-format", "stream-json", "--print-timeout", f"{a.timeout}s", "-p", texto]
    if previo:
        cmd[1:1] = ["--conversation", previo["conversation_id"]]
    for p in a.leer + [carpeta]:          # la carpeta de la tarea va al espacio de trabajo: ahi si escribe
        cmd[1:1] = ["--add-dir", p]
    if not os.path.exists(os.path.join(ARRANQUE, "_agents", "hooks.json")):
        sys.exit("ALTO: falta el candado (_agy_candado\\_agents\\hooks.json). No se corre agy sin candado.")

    t0 = time.time()

    def correr(cmd_, archivo):
        # cwd = ARRANQUE (_agy_candado\): ahi agy descubre _agents\skills.json (nuestros agentes), GEMINI.md (incluye las
        # reglas de la raiz) y _agents\hooks.json = el CANDADO REAL (PLAN_DELEGACION paso 2, 01-11): agy NO PUEDE escribir
        # fuera de _TRABAJO_AGY ni usar la terminal fuera de la lista blanca. Registro: _TRABAJO_AGY\_candado_log.jsonl
        with open(archivo, "w", encoding="utf-8") as out:
            p = subprocess.run(cmd_, cwd=ARRANQUE, stdout=out, stderr=subprocess.STDOUT)
        r_, errs = {}, []
        for linea in open(archivo, encoding="utf-8", errors="replace"):
            try:
                e = json.loads(linea)
            except Exception:
                continue
            if e.get("event") == "result":
                r_ = e.get("result", {})
            su = e.get("step_update") or {}
            for err in (su.get("error"), (su.get("tool_info") or {}).get("error")):
                if isinstance(err, dict):     # el error de herramienta viene dentro de tool_info (01-11)
                    errs.append(err.get("message", "")[:200])
        return p, r_, errs

    def no_hizo_nada():
        if a.solo_texto:
            return False
        if copias and any(diff_copia(c["origen"], c["copia"])[0] for c in copias):
            return False
        return not [x for x in os.listdir(carpeta) if x not in ("PEDIDO.md", "run.jsonl", "copia")]

    jl = os.path.join(carpeta, f"run{suf}.jsonl")
    proc, res, errores = correr(cmd, jl)
    tokens_total = (res.get("usage") or {}).get("total_tokens") or 0
    reintento = False
    if not previo and no_hizo_nada() and errores:
        # Reintento automatico UNA vez (gasta cuota de Gemini, no de Claude)
        reintento = True
        aviso = ("\n\nATENCION: en tu intento anterior usaste la terminal, fue BLOQUEADA y te detuviste sin hacer la tarea. "
                 "Errores: " + " | ".join(errores[:2]) + "\nHazla ahora usando SOLO herramientas de archivos.")
        cmd2 = cmd[:-1] + [cmd[-1] + aviso]
        proc, res, errores2 = correr(cmd2, os.path.join(carpeta, "run2.jsonl"))
        errores += ["[reintento] " + x for x in errores2]
        tokens_total += (res.get("usage") or {}).get("total_tokens") or 0
    t_fin_agy = time.time()                 # lo que cambie despues (los --despues compilan) no es de agy
    minutos = round((t_fin_agy - t0) / 60, 1)
    usage = dict(res.get("usage") or {})
    usage["total_tokens"] = tokens_total
    with open(os.path.join(carpeta, f"RESPUESTA{suf}.md"), "w", encoding="utf-8") as f:
        f.write(res.get("response", "(sin respuesta: ver run.jsonl)"))
    fuera = cambios_fuera(t0, carpeta)

    # --- lo mecanico, por script (cero modelo)
    controles = []
    for c in a.despues:
        base = copias[0]["copia"] if copias else carpeta
        comando = c.replace("{copia}", base).replace("{proyecto}", PROYECTO)
        r = subprocess.run(comando, cwd=base, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        controles.append(f"$ {comando}\n[codigo {r.returncode}]\n{(r.stdout + r.stderr)[-4000:]}")
    if controles:
        with open(os.path.join(carpeta, "CONTROLES.txt"), "w", encoding="utf-8") as f:
            f.write("\n\n".join(controles))

    cambiados_total = []
    if copias:
        todos = []
        for c in copias:
            cambiados, d = diff_copia(c["origen"], c["copia"])
            c["cambiados"] = cambiados
            cambiados_total += cambiados
            todos.append(d)
        with open(os.path.join(carpeta, "DIFF.txt"), "w", encoding="utf-8") as f:
            f.write("\n\n".join(todos) or "(sin cambios)")
        with open(os.path.join(carpeta, "COPIAS.json"), "w", encoding="utf-8") as f:
            json.dump(copias, f, ensure_ascii=False, indent=1)

    propios = ("PEDIDO", "run", "RESPUESTA", "ENTREGA.json", "CONTROLES.txt", "DIFF.txt", "COPIAS.json", "copia")
    creados = sorted(x for x in os.listdir(carpeta) if not x.startswith(propios))
    tocado_ahora = []                       # en una vuelta de correccion: que toco agy EN ESTA vuelta
    for raiz_, dirs_, archs_ in os.walk(carpeta):
        for x in archs_:
            px = os.path.join(raiz_, x)
            if t0 < os.path.getmtime(px) <= t_fin_agy + 1 and not x.startswith(propios):
                tocado_ahora.append(os.path.relpath(px, carpeta))
    estado = res.get("status", f"SIN RESULTADO (codigo {proc.returncode})")
    if res.get("finished_reason"):          # print_timeout / interrupted / error = respuesta CORTADA
        estado += " CORTADA: " + str(res["finished_reason"])
    if res.get("denied_actions"):           # agy se freno por un permiso (p. ej. terminal sin pantalla): no es exito
        estado += " CON ACCIONES NEGADAS: " + ", ".join(str(x.get("action")) for x in res["denied_actions"])
    if not (res.get("response") or "").strip():
        estado += " RESPUESTA VACIA"
    if not a.solo_texto and not tocado_ahora:
        estado += " PERO NO CREO NI CAMBIO NADA" + (" EN ESTA VUELTA" if previo else "")
    vueltas = list((previo or {}).get("vueltas") or [])
    if previo:
        vueltas.append({"id": rid, "estado_agy": estado, "tokens_agy": usage.get("total_tokens"), "minutos": minutos,
                        "tocado": tocado_ahora, "errores_agy": errores})
    entrega = {"id": a.seguir or rid, "estado_agy": estado, "reintento": reintento, "errores_agy": errores, "modelo": modelo,
               "minutos": minutos, "tokens_agy": usage.get("total_tokens"), "archivos_creados": creados,
               "archivos_cambiados_en_copia": cambiados_total, "tocado_en_esta_vuelta": tocado_ahora, "escribio_fuera": fuera,
               "revisar": [x for x in ("DIFF.txt", "CONTROLES.txt", "ENTREGA_AGY.md") if os.path.exists(os.path.join(carpeta, x))],
               "veredicto": "NO VERIFICADO (falta revision de Claude)",
               # para --seguir (paso 3):
               "conversation_id": res.get("conversation_id") or (previo or {}).get("conversation_id"),
               "tipo": a.tipo, "materia": a.materia, "tema": a.tema, "leer": a.leer, "despues": a.despues,
               "solo_texto": a.solo_texto, "vuelta": vuelta, "vueltas": vueltas}
    if previo:
        entrega["tokens_agy_primera_vuelta"] = previo.get("tokens_agy_primera_vuelta", previo.get("tokens_agy"))
    tmp = os.path.join(carpeta, "ENTREGA.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entrega, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(carpeta, "ENTREGA.json"))

    metricas.agregar({"id": rid, "tipo_tarea": a.tipo + (f" (correccion v{vuelta})" if previo else ""), "materia": a.materia, "tema": a.tema, "ejecutor": "agy",
                      "modelo": modelo, "tokens_ejecutor": usage.get("total_tokens", ""), "minutos": minutos,
                      "chequeo_auto": "ver CONTROLES.txt" if controles else "", "veredicto": "PENDIENTE",
                      "carpeta": carpeta, "fuera_de_cerco": len(fuera)})
    print(json.dumps(entrega, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
