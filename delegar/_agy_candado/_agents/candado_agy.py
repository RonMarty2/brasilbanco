# -*- coding: utf-8 -*-
"""CANDADO de agy (PLAN_DELEGACION, paso 2, 01-11-2026). Hook PreToolUse: decide ANTES de que la herramienta corra.

Vive en delegar\_agy_candado\_agents\ : agy solo lo carga si ARRANCA en _agy_candado\, y eso lo hace agy_run.py.
Por eso esta SIEMPRE activo. La raiz de delegar queda sin hook: el uso manual de agy alli no se toca.
(Probado 01-11: para agy, una respuesta vacia o {} del hook cuenta como DENY; no hay forma de «no opinar».
 Por eso el candado no puede vivir en la raiz con un interruptor: bloquearia el uso manual.)

Reglas:
  - Escribir, editar, borrar o mover: SOLO dentro de _TRABAJO_AGY\. Fuera -> deny.
  - Leer, listar, buscar, buscar en la web: permitido.
  - Terminal (run_command): solo la LISTA BLANCA (controles de delegar/controles, py_compile y compilar dentro de _TRABAJO_AGY),
    sin encadenar (; & | > < ` $( ). Todo lo demas -> deny.
  - Navegador (browser_*): deny.
  - Si el propio candado falla -> deny (falla cerrado).
Todo pedido queda en _TRABAJO_AGY\_candado_log.jsonl (para ver que intento agy y que se le nego).
"""
import sys, os, json, re, datetime

AQUI = os.path.dirname(os.path.abspath(__file__))              # ...\delegar\_agy_candado\_agents
RAIZ = os.path.dirname(os.path.dirname(AQUI))   # ...\brasilbanco\delegar
TRABAJO = os.path.join(RAIZ, "_TRABAJO_AGY")
CONTROLES = os.path.join(RAIZ, "controles")
LOG = os.path.join(TRABAJO, "_candado_log.jsonl")
MARCA = "REGLAS FIJAS (no negociables)"

LECTURA = re.compile(r"(read|view|list|grep|find|search|glob|fetch|outline|ls$|stat)", re.I)
ESCRITURA = re.compile(r"(write|edit|replace|create|delete|remove|move|rename|copy|patch|code_action|mkdir|save|apply)", re.I)
CLAVE_RUTA = re.compile(r"(path|file|target|dir|uri|cwd|dest|source|folder)", re.I)
RUTA_ABS = re.compile(r"^([a-zA-Z]:[\\/]|\\\\|/|~)")

# Terminal: lista blanca. Scripts de control de delegar/controles (leen y reportan) y compilar LaTeX dentro de _TRABAJO_AGY.
SCRIPTS_OK = re.compile(r"^(verificar_[\w ()-]*|revisar_[\w-]*|medir_[\w-]*)\.py$", re.I)
COMPILAR = re.compile(r"^(pdflatex|xelatex|lualatex|latexmk|bibtex|biber)(\.exe)?$", re.I)
ENCADENA = re.compile(r"[;&|<>`]|\$\(")
# Sin rutas y sin riesgo (control del propio agente): se permiten.
SIEMPRE_OK = {"finish", "wait", "wait_5_seconds", "command_status", "task_boundary", "notify_user", "ask_question",
              "ask_permission", "ask_custom_permission", "list_permissions", "view_file_outline"}
# Lanzan trabajo fuera de este control o tocan cosas fuera del disco: siempre deny.
NUNCA = {"run_workflow", "schedule", "invoke_subagent", "define_subagent", "manage_subagents", "send_command_input",
         "send_message", "manage_inbox", "manage_task", "delete_knowledge", "generate_image", "call_mcp_tool",
         "execute_browser_javascript", "open_browser_url", "click_browser_pixel", "search_marketplace"}


def dentro(ruta, base):
    try:
        r = os.path.normcase(os.path.realpath(ruta))
        b = os.path.normcase(os.path.realpath(base))
        return os.path.commonpath([r, b]) == b
    except Exception:
        return False


def absoluta(v, cwd):
    v = os.path.expanduser(v.strip().strip('"').strip("'"))
    if v.lower().startswith("file:///"):
        v = v[8:]
    return v if os.path.isabs(v) else os.path.join(cwd, v)


def rutas_de(args, cwd):
    """Toda ruta que aparezca en los argumentos (por nombre de clave o porque parece ruta absoluta)."""
    out = []

    def rec(k, v):
        if isinstance(v, dict):
            for kk, vv in v.items():
                rec(kk, vv)
        elif isinstance(v, list):
            for x in v:
                rec(k, x)
        elif isinstance(v, str) and v.strip():
            if (CLAVE_RUTA.search(k or "") and len(v) < 600 and "\n" not in v) or RUTA_ABS.match(v.strip()):
                out.append(absoluta(v, cwd))
    rec("", args)
    return out


def tokens(cmd):
    return [t.strip('"').strip("'") for t in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', cmd)]


def juzgar_comando(args, cwd):
    cmd = str(args.get("CommandLine") or args.get("command") or args.get("Command") or "").strip()
    cwd_cmd = str(args.get("Cwd") or args.get("cwd") or cwd)
    if not cmd:
        return "deny", "Comando vacio."
    if ENCADENA.search(cmd):
        return "deny", "Candado: no se permite encadenar ni redirigir (; & | > < ` $( ). Usa herramientas de archivos."
    t = tokens(cmd)
    prog = os.path.basename(t[0]).lower()
    if prog in ("python", "python.exe", "py", "python3"):
        resto = [x for x in t[1:] if not x.startswith("-")]
        if len(resto) >= 2 and resto[0] == "py_compile":
            if all(dentro(absoluta(f, cwd_cmd), TRABAJO) for f in resto[1:]):
                return "allow", "Candado: comprobar sintaxis dentro de _TRABAJO_AGY."
            return "deny", "Candado: py_compile solo sobre archivos de _TRABAJO_AGY."
        if resto:
            script = absoluta(resto[0], cwd_cmd)
            if dentro(script, CONTROLES) and SCRIPTS_OK.match(os.path.basename(script)):
                return "allow", "Candado: control de delegar/controles en la lista blanca."
        return "deny", ("Candado: solo se permiten los controles de delegar/controles (verificar_*.py, revisar_*.py) o py_compile en _TRABAJO_AGY. "
                        "Para lo demas usa herramientas de archivos.")
    if COMPILAR.match(prog):
        if dentro(cwd_cmd, TRABAJO):
            return "allow", "Candado: compilar dentro de _TRABAJO_AGY."
        return "deny", "Candado: solo se compila con la carpeta de trabajo (Cwd) dentro de _TRABAJO_AGY."
    return "deny", ("Candado: la terminal esta bloqueada salvo la lista blanca (controles de delegar/controles, py_compile en _TRABAJO_AGY). "
                    "Usa herramientas de archivos: list_dir, find_by_name, grep_search, view_file, write_to_file, replace_file_content.")


def juzgar(nombre, args, cwd):
    n = (nombre or "").lower()
    if n == "run_command" or "command" in n and "terminal" not in n and n.startswith("run"):
        return juzgar_comando(args, cwd)
    if n.startswith("browser"):
        return "deny", "Candado: navegador bloqueado en el trabajo delegado."
    if n in NUNCA or n.startswith(("browser", "subagent")) or "subagent" in n or "mcp" in n:
        return "deny", f"Candado: la herramienta {nombre} no se usa en el trabajo delegado."
    if n in SIEMPRE_OK:
        return "allow", ""
    rutas = rutas_de(args, cwd)
    if ESCRITURA.search(n) or not LECTURA.search(n):
        if not rutas:
            # Estricto: algo que no es lectura y no dice donde escribe no se puede controlar -> deny
            return "deny", f"Candado: la herramienta {nombre} no esta permitida (no se puede comprobar donde escribe)."
        fuera = [r for r in rutas if not dentro(r, TRABAJO)]
        if fuera:
            return "deny", f"Candado: solo puedes escribir dentro de {TRABAJO}. Bloqueado: {fuera[0]}"
        return "allow", ""     # escribe dentro de _TRABAJO_AGY
    return "allow", ""         # lectura
    # OJO (probado 01-11): para agy una decision VACIA cuenta como DENY; por eso lo permitido es "allow".


def main():
    crudo = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    datos, decision, motivo, activo = {}, "", "", False
    try:
        datos = json.loads(crudo or "{}")
        activo = True          # siempre (ver arriba)
        if activo:
            tc = datos.get("toolCall") or {}
            cwd = (datos.get("workspacePaths") or [RAIZ])[0]
            decision, motivo = juzgar(tc.get("name", ""), tc.get("args") or {}, cwd)
    except Exception as e:                       # falla cerrado
        decision, motivo = "deny", f"Candado: error interno ({e}); por seguridad se niega."
        activo = True
    # Candado apagado (uso manual de agy): {} = sin opinion del hook. Nunca "" (= deny, probado 01-11).
    salida = {"decision": decision} if activo else {}
    if motivo:
        salida["reason"] = motivo
    # Nota (01-11): agy sin pantalla niega toda terminal aunque este hook diga "allow" (no sirvieron permissionOverrides,
    # --settings ni settings.json de proyecto). La unica via seria saltarse los permisos de agy: decision PENDIENTE
    # del docente (PLAN_DELEGACION paso 4). El candado ya es estricto (herramienta desconocida = deny) por si se decide.
    if activo:
        try:
            os.makedirs(TRABAJO, exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"hora": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "conv": datos.get("conversationId"), "tool": (datos.get("toolCall") or {}).get("name"),
                                    "args": {k: (v[:300] if isinstance(v, str) else v) for k, v in
                                             ((datos.get("toolCall") or {}).get("args") or {}).items()},
                                    "decision": decision, "motivo": motivo}, ensure_ascii=False) + "\n")
        except Exception:
            pass
    sys.stdout.write(json.dumps(salida, ensure_ascii=False))


if __name__ == "__main__":
    main()
