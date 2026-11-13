# -*- coding: utf-8 -*-
"""Genera timeline.md y resumen.json a partir de events.jsonl de una sesion."""
import json
import sys
from collections import defaultdict
from pathlib import Path


def _leer(carpeta):
    evs = []
    with open(carpeta / "events.jsonl", encoding="utf-8", errors="replace") as f:
        for linea in f:
            try:
                evs.append(json.loads(linea))
            except Exception:
                pass
    evs.sort(key=lambda e: e.get("t", 0))
    return evs


def _dur(seg):
    seg = int(seg)
    return f"{seg // 3600}h {seg % 3600 // 60}m {seg % 60}s" if seg >= 3600 else f"{seg // 60}m {seg % 60}s"


def _corto(txt, n=300):
    txt = str(txt).replace("\n", " ⏎ ")
    return txt if len(txt) <= n else txt[:n] + "…"


def generar(carpeta):
    carpeta = Path(carpeta)
    evs = _leer(carpeta)
    if not evs:
        (carpeta / "timeline.md").write_text("# Sesion vacia\n", encoding="utf-8")
        return
    total = evs[-1].get("t", 0)

    # tiempo por programa / app
    tiempo = defaultdict(float)
    cambios = [(e["t"], e.get("programa") or e.get("titulo", ""), "pc") for e in evs
               if e.get("tipo") == "ventana"]
    cambios += [(e["t"], e.get("app", ""), "android") for e in evs if e.get("tipo") == "app"]
    for src in ("pc", "android"):
        c = [x for x in cambios if x[2] == src]
        for i, (t, nombre, _) in enumerate(c):
            fin = c[i + 1][0] if i + 1 < len(c) else total
            tiempo[f"{src}: {nombre}"] += max(0, fin - t)

    def n(tipo, src=None):
        return sum(1 for e in evs if e.get("tipo") == tipo and (src is None or e.get("src") == src))

    resumen = {
        "duracion_seg": total,
        "clics_pc": n("click"), "toques_android": n("toque"),
        "textos_escritos": n("texto_escrito"), "atajos": n("atajo"),
        "copiados": n("portapapeles"), "archivos_nuevos": n("archivo_nuevo"),
        "capturas_pc": n("captura", "pc"), "capturas_android": n("captura", "android"),
        "tiempo_por_programa_seg": {k: round(v) for k, v in sorted(tiempo.items(), key=lambda x: -x[1])},
    }
    (carpeta / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")

    ini = next((e for e in evs if e.get("tipo") == "inicio"), {})
    dev = next((e for e in evs if e.get("tipo") == "dispositivo"), None)
    L = [f"# Sesion de captura – {carpeta.name}", "",
         f"- Equipo: {ini.get('equipo', '?')} · Usuario: {ini.get('usuario', '?')}",
         f"- Duracion: {_dur(total)}",
         f"- Android: {dev.get('modelo') if dev else 'no conectado'}",
         f"- Audio: {'audio.wav (narracion)' if (carpeta / 'audio.wav').exists() else 'no hay'}",
         f"- Video Android: {'android_video.mp4' if (carpeta / 'android_video.mp4').exists() else 'no hay'}",
         "", "## Resumen", ""]
    for k in ("clics_pc", "toques_android", "textos_escritos", "atajos", "copiados", "archivos_nuevos"):
        L.append(f"- {k.replace('_', ' ')}: {resumen[k]}")
    L += ["", "### Tiempo por programa / app", ""]
    for k, v in resumen["tiempo_por_programa_seg"].items():
        L.append(f"- {k}: {_dur(v)}")
    L += ["", "## Linea de tiempo", ""]

    ult_img_ventana = None
    clic_buf = None  # (ventana, cantidad, hora)

    def vaciar_clics():
        nonlocal clic_buf
        if clic_buf:
            L.append(f"- `{clic_buf[2]}` 🖱️ {clic_buf[1]} clic(s) en «{_corto(clic_buf[0], 80)}»")
            clic_buf = None

    for e in evs:
        tp, h, src = e.get("tipo"), e.get("hora", ""), e.get("src", "")
        if tp == "click":
            v = e.get("ventana", "")
            if clic_buf and clic_buf[0] == v:
                clic_buf = (v, clic_buf[1] + 1, clic_buf[2])
            else:
                vaciar_clics()
                clic_buf = (v, 1, h)
            continue
        if tp != "captura":
            vaciar_clics()
        if tp == "ventana":
            L.append(f"- `{h}` 🪟 **{e.get('programa', '')}** – {_corto(e.get('titulo', ''), 120)}")
        elif tp == "app":
            L.append(f"- `{h}` 📱 App en el celular: **{e.get('app', '')}**")
        elif tp == "toque":
            L.append(f"- `{h}` 👆 Toque en el celular ({e.get('x_rel')}, {e.get('y_rel')})")
        elif tp == "texto_escrito":
            L.append(f"- `{h}` ⌨️ Escribio en «{_corto(e.get('ventana', ''), 60)}»: `{_corto(e.get('texto', ''), 200)}`")
        elif tp == "atajo":
            L.append(f"- `{h}` ⌨️ {e.get('atajo')} en «{_corto(e.get('ventana', ''), 60)}»")
        elif tp == "portapapeles":
            L.append(f"- `{h}` 📋 Copio: `{_corto(e.get('texto', ''))}`  _(en {e.get('programa', '')})_")
        elif tp in ("archivo_nuevo", "archivo_renombrado"):
            L.append(f"- `{h}` 📄 Archivo: `{e.get('ruta')}` ({e.get('tamano')} bytes)"
                     + (f" → copia: `{e.get('copia')}`" if e.get("copia") else ""))
        elif tp == "control":
            L.append(f"- `{h}` ⏸️ {e.get('detalle')}")
        elif tp == "error":
            L.append(f"- `{h}` ⚠️ error: {e.get('detalle')}")
        elif tp == "captura":
            mot = e.get("motivo")
            clave = (src, e.get("ventana") or e.get("textos", "")[:30])
            if src == "android" and e.get("pantalla_negra"):
                vaciar_clics()
                L.append(f"- `{h}` ⬛ Pantalla del celular NEGRA (app protegida): sin contenido visible")
                continue
            if mot == "periodica" and clave == ult_img_ventana:
                continue
            ult_img_ventana = clave
            vaciar_clics()
            L.append(f"- `{h}` 🖼️ captura ({src}, {mot})")
            L.append(f"  ![]({e['archivo']})")
            if e.get("textos"):
                L.append(f"  > Textos en pantalla: {_corto(e['textos'], 400)}")
    vaciar_clics()

    tr = carpeta / "transcripcion.txt"
    if tr.exists():
        L += ["", "## Transcripcion de la narracion", "", tr.read_text(encoding="utf-8", errors="replace")]
    (carpeta / "timeline.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    generar(sys.argv[1])
