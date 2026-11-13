# -*- coding: utf-8 -*-
"""
CAPTURADOR DE ACTIVIDAD (PC + Android)
Registra todo lo que se hace para despues analizarlo y automatizarlo.

  F9  = pausar / reanudar (usar al escribir contrasenas)
  F10 = terminar y generar el informe

Todo se guarda en  sesiones/<fecha_hora>/
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import mss
from pynput import keyboard, mouse
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

try:
    import sounddevice as sd
except Exception:  # sin microfono / driver
    sd = None

# ----------------------------------------------------------------- rutas
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).parent
ADB = BASE / "herramientas" / "scrcpy" / "adb.exe"
SCRCPY = BASE / "herramientas" / "scrcpy" / "scrcpy.exe"

ts_inicio = datetime.now()
SES = BASE / "sesiones" / ts_inicio.strftime("%Y-%m-%d_%H%M%S")
FR = SES / "frames"
FILES = SES / "archivos_descargados"
for d in (SES, FR, FILES):
    d.mkdir(parents=True, exist_ok=True)

T0 = time.time()
STOP = threading.Event()
PAUSED = threading.Event()
_lock = threading.Lock()
_ev = open(SES / "events.jsonl", "a", encoding="utf-8", buffering=1)
_fcount = {"pc": 0, "android": 0}
_current = {"title": "", "proc": ""}

PALABRAS_SECRETAS = re.compile(
    r"senha|password|contrase|clave|login|entrar|acessar|iniciar sesi|pin\b|token|c[oó]digo de",
    re.I)


def log(src, tipo, **datos):
    if PAUSED.is_set() and tipo != "control":
        return
    rec = {"t": round(time.time() - T0, 2),
           "hora": datetime.now().strftime("%H:%M:%S"),
           "src": src, "tipo": tipo}
    rec.update(datos)
    with _lock:
        _ev.write(json.dumps(rec, ensure_ascii=False) + "\n")


def p(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------- ventana activa (PC)
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = wt.HWND
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]


def ventana_activa():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    proc = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)
    if h:
        sz = wt.DWORD(520)
        pb = ctypes.create_unicode_buffer(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, pb, ctypes.byref(sz)):
            proc = os.path.basename(pb.value)
        kernel32.CloseHandle(h)
    return buf.value, proc


def hilo_ventana():
    last = None
    while not STOP.is_set():
        try:
            t, pr = ventana_activa()
            _current["title"], _current["proc"] = t, pr
            if (t, pr) != last:
                last = (t, pr)
                log("pc", "ventana", titulo=t, programa=pr)
        except Exception:
            pass
        time.sleep(0.4)


# ------------------------------------------------------------ portapapeles
def leer_portapapeles():
    try:
        if not user32.OpenClipboard(None):
            return None
        try:
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            user32.GetClipboardData.restype = ctypes.c_void_p
            h = user32.GetClipboardData(13)  # CF_UNICODETEXT
            if not h:
                return None
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                return None
            txt = ctypes.wstring_at(ptr)
            kernel32.GlobalUnlock(h)
            return txt
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def hilo_portapapeles():
    seq = user32.GetClipboardSequenceNumber()
    while not STOP.is_set():
        time.sleep(0.5)
        s = user32.GetClipboardSequenceNumber()
        if s != seq:
            seq = s
            txt = leer_portapapeles()
            if txt:
                log("pc", "portapapeles", texto=txt[:2000],
                    ventana=_current["title"], programa=_current["proc"])
            else:
                log("pc", "portapapeles", texto="(imagen/archivo)",
                    ventana=_current["title"], programa=_current["proc"])


# ------------------------------------------------------------ capturas PC
_ult_thumb = {"v": None}
_ult_shot = {"t": 0}


def capturar_pc(motivo, click=None, forzar=False):
    if PAUSED.is_set():
        return
    now = time.time()
    if not forzar and motivo == "click" and now - _ult_shot["t"] < 0.35:
        return
    try:
        with mss.mss() as sct:
            mon = sct.monitors[0]  # todos los monitores juntos
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        if click:
            x, y = click[0] - mon["left"], click[1] - mon["top"]
            d = ImageDraw.Draw(img)
            r = 22
            d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 0, 0), width=5)
        th = np.asarray(img.resize((48, 27)).convert("L"), dtype=np.int16)
        if motivo == "periodica" and _ult_thumb["v"] is not None:
            if np.abs(th - _ult_thumb["v"]).mean() < 1.5:
                return  # pantalla sin cambios
        _ult_thumb["v"] = th
        _ult_shot["t"] = now
        w = 1600
        if img.width > w:
            img = img.resize((w, int(img.height * w / img.width)), Image.LANCZOS)
        _fcount["pc"] += 1
        nombre = f"pc_{_fcount['pc']:05d}.jpg"
        img.save(FR / nombre, quality=60)
        log("pc", "captura", archivo=f"frames/{nombre}", motivo=motivo,
            ventana=_current["title"], programa=_current["proc"])
    except Exception as e:
        log("pc", "error", detalle=f"captura: {e}")


def hilo_periodico():
    while not STOP.is_set():
        capturar_pc("periodica")
        time.sleep(2.5)


# ------------------------------------------------------- mouse y teclado
_txt = {"buf": "", "t": 0, "win": ""}


def vaciar_texto():
    if _txt["buf"]:
        log("pc", "texto_escrito", texto=_txt["buf"], ventana=_txt["win"])
        _txt["buf"] = ""


def on_click(x, y, boton, pressed):
    if not pressed or PAUSED.is_set():
        return
    vaciar_texto()
    log("pc", "click", x=x, y=y, boton=str(boton).split(".")[-1],
        ventana=_current["title"], programa=_current["proc"])
    threading.Thread(target=capturar_pc, args=("click", (x, y)), daemon=True).start()


def on_scroll(x, y, dx, dy):
    pass


_mods = {"ctrl": False, "alt": False}
ESPECIALES = {keyboard.Key.enter: "[ENTER]", keyboard.Key.tab: "[TAB]",
              keyboard.Key.esc: "[ESC]", keyboard.Key.delete: "[SUPR]",
              keyboard.Key.up: "[ARRIBA]", keyboard.Key.down: "[ABAJO]"}


def on_press(key):
    if key == keyboard.Key.f9:
        if PAUSED.is_set():
            PAUSED.clear()
            log("pc", "control", detalle="reanudado")
            p(">>> REANUDADO")
        else:
            vaciar_texto()
            log("pc", "control", detalle="pausado")
            PAUSED.set()
            p(">>> PAUSADO (F9 para reanudar)")
        return
    if key == keyboard.Key.f10:
        STOP.set()
        return False
    if PAUSED.is_set():
        return
    if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        _mods["ctrl"] = True
        return
    if key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr):
        _mods["alt"] = True
        return
    win = _current["title"]
    secreto = bool(PALABRAS_SECRETAS.search(win))
    try:
        ch = key.char
    except AttributeError:
        ch = None
    if _mods["ctrl"] and ch is not None:
        vaciar_texto()
        # ctrl+c / ctrl+v llegan como caracteres de control
        letra = chr(ord(ch) + 96) if ord(ch) < 32 else ch
        log("pc", "atajo", atajo=f"Ctrl+{letra.upper()}", ventana=win)
        return
    if ch is not None:
        if _txt["win"] != win:
            vaciar_texto()
            _txt["win"] = win
        _txt["buf"] += "*" if secreto else ch
    elif key == keyboard.Key.space:
        _txt["buf"] += " "
    elif key == keyboard.Key.backspace:
        _txt["buf"] = _txt["buf"][:-1]
    elif key in ESPECIALES:
        _txt["buf"] += ESPECIALES[key]
        if key == keyboard.Key.enter:
            vaciar_texto()
    _txt["win"] = win
    _txt["t"] = time.time()


def on_release(key):
    if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        _mods["ctrl"] = False
    if key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr):
        _mods["alt"] = False


def hilo_vaciar_texto():
    while not STOP.is_set():
        time.sleep(1.5)
        if _txt["buf"] and time.time() - _txt["t"] > 1.5:
            vaciar_texto()


# ------------------------------------------------------------ archivos
EXT_COPIAR = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".xlsx", ".xls", ".csv",
              ".txt", ".ofx", ".docx", ".heic"}


class Manejador(FileSystemEventHandler):
    def _reg(self, tipo, path):
        if PAUSED.is_set() or path.endswith((".tmp", ".crdownload", ".part")):
            return
        try:
            if os.path.isdir(path):
                return
            size = os.path.getsize(path) if os.path.exists(path) else 0
            copia = ""
            ext = os.path.splitext(path)[1].lower()
            if ext in EXT_COPIAR and 0 < size < 15 * 1024 * 1024 and tipo != "archivo_borrado":
                time.sleep(0.8)
                dest = FILES / f"{datetime.now():%H%M%S}_{os.path.basename(path)}"
                shutil.copy2(path, dest)
                copia = f"archivos_descargados/{dest.name}"
            log("pc", tipo, ruta=path, tamano=size, copia=copia)
        except Exception as e:
            log("pc", "error", detalle=f"archivo: {e}")

    def on_created(self, e):
        self._reg("archivo_nuevo", e.src_path)

    def on_moved(self, e):
        self._reg("archivo_renombrado", e.dest_path)


def hilo_archivos():
    obs = Observer()
    home = Path.home()
    for carpeta in ("Downloads", "Descargas", "Desktop", "Escritorio", "Documents", "Pictures"):
        d = home / carpeta
        if d.exists():
            obs.schedule(Manejador(), str(d), recursive=False)
            p(f"Vigilando carpeta: {d}")
    obs.start()
    while not STOP.is_set():
        time.sleep(0.5)
    obs.stop()


# ----------------------------------------------------------------- audio
def hilo_audio():
    if sd is None:
        p("(!) Sin audio disponible: no se grabara la voz")
        return
    try:
        wf = wave.open(str(SES / "audio.wav"), "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        q = queue.Queue()

        def cb(indata, frames, tm, status):
            if not PAUSED.is_set():
                q.put(bytes(indata))

        with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", callback=cb):
            p("Microfono grabando (hablar mientras trabaja ayuda mucho)")
            while not STOP.is_set():
                try:
                    wf.writeframes(q.get(timeout=0.5))
                except queue.Empty:
                    pass
        wf.close()
    except Exception as e:
        p(f"(!) Audio no disponible: {e}")


# --------------------------------------------------------------- Android
def adb(*args, timeout=15, binario=False):
    try:
        r = subprocess.run([str(ADB), *args], capture_output=True, timeout=timeout,
                           creationflags=0x08000000)
        return r.stdout if binario else r.stdout.decode("utf-8", "ignore")
    except Exception:
        return b"" if binario else ""


def hay_android():
    if not ADB.exists():
        return None
    out = adb("devices")
    for linea in out.splitlines()[1:]:
        if linea.strip().endswith("device"):
            return linea.split()[0]
    return None


_adb_lock = threading.Lock()
_adb_ult = {"t": 0}


def captura_android(motivo, toque=None):
    if PAUSED.is_set():
        return
    if not _adb_lock.acquire(blocking=False):
        return
    try:
        png = adb("exec-out", "screencap", "-p", timeout=20, binario=True)
        if not png:
            return
        from io import BytesIO
        img = Image.open(BytesIO(png)).convert("RGB")
        negra = np.asarray(img.resize((32, 32)).convert("L")).mean() < 3
        th = np.asarray(img.resize((48, 27)).convert("L"), dtype=np.int16)
        prev = _ult_thumb.get("a")
        if motivo == "periodica" and prev is not None and np.abs(th - prev).mean() < 1.5:
            return
        _ult_thumb["a"] = th
        if toque:
            d = ImageDraw.Draw(img)
            x, y = toque[0] * img.width, toque[1] * img.height
            r = max(28, img.width // 25)
            d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 0, 0), width=6)
        if img.height > 1400:
            img = img.resize((int(img.width * 1400 / img.height), 1400), Image.LANCZOS)
        _fcount["android"] += 1
        nombre = f"android_{_fcount['android']:05d}.jpg"
        img.save(FR / nombre, quality=60)
        # textos de la pantalla (si la app lo permite)
        textos = ""
        if not negra:
            adb("shell", "uiautomator", "dump", "/sdcard/_cap.xml", timeout=15)
            xml = adb("exec-out", "cat", "/sdcard/_cap.xml", timeout=10)
            textos = " | ".join(dict.fromkeys(
                t.strip() for t in re.findall(r'text="([^"]+)"', xml) if t.strip()))[:1500]
        log("android", "captura", archivo=f"frames/{nombre}", motivo=motivo,
            pantalla_negra=bool(negra), textos=textos)
    except Exception as e:
        log("android", "error", detalle=f"captura: {e}")
    finally:
        _adb_lock.release()


def hilo_android_app():
    last = None
    while not STOP.is_set():
        out = adb("shell", "dumpsys window | grep -E 'mFocusedApp|mCurrentFocus'")
        m = re.search(r"mFocusedApp=.*? u\d+ ([\w.]+)/", out) or re.search(r"mCurrentFocus=.*? u\d+ ([\w.]+)/", out)
        app = m.group(1) if m else ""
        if app and app != last:
            last = app
            log("android", "app", app=app)
        time.sleep(1.2)


def hilo_android_periodico():
    while not STOP.is_set():
        captura_android("periodica")
        time.sleep(3)


def hilo_android_toques():
    # maximos de coordenadas del panel tactil
    info = adb("shell", "getevent", "-lp")
    mx = re.search(r"ABS_MT_POSITION_X.*?max (\d+)", info)
    my = re.search(r"ABS_MT_POSITION_Y.*?max (\d+)", info)
    maxx = int(mx.group(1)) if mx else 1
    maxy = int(my.group(1)) if my else 1
    proc = subprocess.Popen([str(ADB), "shell", "getevent", "-lt"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000)
    x = y = None
    ult = 0
    while not STOP.is_set():
        linea = proc.stdout.readline().decode("utf-8", "ignore")
        if not linea:
            break
        if "ABS_MT_POSITION_X" in linea:
            x = int(linea.split()[-1], 16)
        elif "ABS_MT_POSITION_Y" in linea:
            y = int(linea.split()[-1], 16)
        elif "BTN_TOUCH" in linea and "DOWN" in linea:
            if x is not None and y is not None and not PAUSED.is_set():
                nx, ny = x / maxx, y / maxy
                log("android", "toque", x_rel=round(nx, 3), y_rel=round(ny, 3))
                if time.time() - ult > 1.2:
                    ult = time.time()
                    threading.Thread(target=captura_android, args=("toque", (nx, ny)),
                                     daemon=True).start()
    proc.terminate()


def iniciar_android():
    dev = hay_android()
    if not dev:
        if ADB.exists():
            p("Android: NO detectado (cable USB + Depuracion USB activada + aceptar el aviso en el telefono)")
        return None
    p(f"Android detectado: {dev}")
    modelo = adb("shell", "getprop", "ro.product.model").strip()
    log("android", "dispositivo", id=dev, modelo=modelo)
    procs = []
    if SCRCPY.exists():
        try:
            pr = subprocess.Popen(
                [str(SCRCPY), f"--record={SES / 'android_video.mp4'}", "--no-playback",
                 "--no-audio"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000)
            procs.append(pr)
            p("Android: grabando video de la pantalla")
        except Exception as e:
            p(f"(!) scrcpy no inicio: {e}")
    for f in (hilo_android_app, hilo_android_periodico, hilo_android_toques):
        threading.Thread(target=f, daemon=True).start()
    return procs


# ------------------------------------------------------------------ main
def main():
    os.system("title CAPTURADOR DE ACTIVIDAD")
    print("=" * 60)
    print("  CAPTURADOR DE ACTIVIDAD  -  grabando...")
    print("  F9  = pausar/reanudar   (usar al escribir contrasenas)")
    print("  F10 = TERMINAR y generar informe")
    print("  Carpeta:", SES)
    print("=" * 60)
    log("pc", "inicio", equipo=os.environ.get("COMPUTERNAME", ""),
        usuario=os.environ.get("USERNAME", ""))

    for f in (hilo_ventana, hilo_portapapeles, hilo_periodico, hilo_vaciar_texto,
              hilo_archivos, hilo_audio):
        threading.Thread(target=f, daemon=True).start()
    procs = iniciar_android() or []

    ml = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
    kl = keyboard.Listener(on_press=on_press, on_release=on_release)
    ml.start()
    kl.start()
    try:
        while not STOP.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        STOP.set()
    print("\nTerminando y guardando...")
    vaciar_texto()
    log("pc", "fin")
    ml.stop()
    for pr in procs:
        try:
            pr.terminate()
            pr.wait(timeout=8)
        except Exception:
            pass
    time.sleep(1.5)
    _ev.close()
    try:
        import generar_informe
        generar_informe.generar(SES)
    except Exception as e:
        print("(!) No se pudo generar el informe:", e)
    # comprimir para enviar
    try:
        zip_path = shutil.make_archive(str(SES), "zip", str(SES))
        print("\nLISTO. Archivo para enviar:\n  ", zip_path)
    except Exception as e:
        print("(!) No se pudo comprimir:", e)
    os.startfile(str(SES.parent))
    input("\nPresiona ENTER para cerrar...")


if __name__ == "__main__":
    main()
