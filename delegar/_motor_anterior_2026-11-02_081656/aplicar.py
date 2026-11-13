# -*- coding: utf-8 -*-
"""Aplica al material real lo que agy cambio en la COPIA, solo despues del OK de Claude (y del docente si es material).

Uso:  python aplicar.py <id>            -> muestra que copiaria (ensayo, no toca nada)
      python aplicar.py <id> --si       -> lo aplica

Seguridad:
- Solo copia los archivos que cambiaron en la copia.
- Se niega si el ORIGINAL cambio desde que se hizo la copia (otra sesion lo toco: REGLA 000).
- Respalda cada original en _TRABAJO_AGY\<id>\respaldo\ antes de pisarlo. Escribe .tmp + os.replace.
"""
import os, sys, json, shutil, hashlib, importlib.util

AQUI = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("metricas", os.path.join(AQUI, "metricas.py"))
metricas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metricas)
TRABAJO = os.path.join(metricas.RAIZ, "_TRABAJO_AGY")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    rid, si = sys.argv[1], "--si" in sys.argv
    carpeta = os.path.join(TRABAJO, rid)
    copias = json.load(open(os.path.join(carpeta, "COPIAS.json"), encoding="utf-8"))
    plan, bloqueos = [], []
    for c in copias:
        for rel in c.get("cambiados", []):
            orig = os.path.join(c["origen"], rel)
            nuevo = os.path.join(c["copia"], rel)
            h0 = c["hashes"].get(rel)
            if os.path.exists(orig) and h0 and sha(orig) != h0:
                bloqueos.append(orig)
            plan.append((nuevo, orig))
    if bloqueos:
        print("[!] NO SE APLICA: estos originales cambiaron despues de la copia (¿otra sesion?):")
        for b in bloqueos:
            print("   ", b)
        sys.exit(1)
    for nuevo, orig in plan:
        print(("[aplico] " if si else "[ensayo] ") + orig)
        if si:
            if os.path.exists(orig):
                resp = os.path.join(carpeta, "respaldo", os.path.relpath(orig, os.path.dirname(os.path.dirname(orig))))
                os.makedirs(os.path.dirname(resp), exist_ok=True)
                shutil.copy2(orig, resp)
            os.makedirs(os.path.dirname(orig), exist_ok=True)
            tmp = orig + ".tmp"
            shutil.copy2(nuevo, tmp)
            os.replace(tmp, orig)
    if not plan:
        print("(nada que aplicar)")
    elif not si:
        print("Ensayo. Para aplicar: python aplicar.py", rid, "--si")


if __name__ == "__main__":
    main()
