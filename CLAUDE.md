# brasilbanco – notas para Claude
Sistema de control y conciliacion de remesas Brasil-Bolivia (ver README.md).

## capturador/ (grabar la actividad de la persona para automatizar)
- `capturador.py` (PC + Android por adb/scrcpy), `generar_informe.py` (timeline.md + resumen.json). `.exe` en `capturador/dist/`.
- Para llevar a otra PC: `CARPETA_PARA_LLEVAR/CAPTURADOR/` (exe + herramientas/scrcpy + CAPTURAR.bat + LEEME.txt). Recompilar: `python -m PyInstaller --noconfirm --onefile --name capturador --hidden-import generar_informe --collect-all sounddevice capturador.py` y copiar el exe.
- Sesion = carpeta `sesiones/<fecha>/` (events.jsonl, frames/, audio.wav, android_video.mp4, timeline.md). F9 pausa, F10 termina.
- Probado: PC completa; Android (video, capturas con textos, app en primer plano, toques). No probado: app de banco real (puede salir negra por FLAG_SECURE).
- Datos sensibles de clientes: `sesiones/` y zips estan en .gitignore; nunca subirlos.
- Android: app en primer plano se lee con `dumpsys window | grep mFocusedApp` (mCurrentFocus falla con la barra de notificaciones).

## delegar/ (agy / Gemini para ahorrar tokens)
Skill `/delegar-agy` (`.claude/skills/delegar-agy`). Candado: Gemini solo escribe en `delegar/_TRABAJO_AGY/`. Usarlo para leer/analizar sesiones grandes, no para scripts cortos.

## Siguiente paso
Recibir el .zip de la primera sesion de la pareja, analizarlo (skill `analizar-sesion` via agy) y proponer que automatizar primero. Respetar: no automatizar login a bancos; usar extension de Chrome y fotos de extractos.
