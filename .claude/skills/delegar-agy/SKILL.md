---
name: delegar-agy
description: "Delega a Gemini (agy / Antigravity) trabajo mecanico o de lectura masiva (analizar sesiones capturadas, revisar muchos archivos) para ahorrar tokens de Claude. Usar al decir «usa agy», «delega» o «ahorra tokens»."
argument-hint: "<tipo> <nivel: mecanico | lectura | criterio | criterio-alto>"
---
# delegar-agy (brasilbanco)
Claude NO hace el trabajo pesado: encarga, revisa barato (DIFF + CONTROLES + ENTREGA) y decide. Todo vive en `delegar/`.

**Candado:** Gemini solo escribe en `delegar/_TRABAJO_AGY/<id>/`, no usa terminal salvo la lista blanca (`delegar/controles/verificar_*.py|revisar_*.py` y `py_compile` dentro de `_TRABAJO_AGY`), sin navegador. Log: `_TRABAJO_AGY/_candado_log.jsonl`. Nunca correr agy delegado fuera de `delegar/_agy_candado` (agy_run.py ya lo hace).

## Flujo
1. Escribir el pedido en `delegar/_TRABAJO_AGY/_pedidos/<nombre>.md` (tarea COMPLETA; cada llamada arrastra ~10 mil tokens fijos). Si hay skill de Gemini aplicable (`delegar/skills/*`), el pedido dice "usa la skill X".
2. Lanzar desde `delegar/` (Bash, `run_in_background: true`):
   `python agy_run.py --tipo analizar-sesion --nivel criterio --pedido "<pedido.md>" --copiar "<carpeta de la sesion>" [--leer <carpeta>] [--despues "<comando con {copia} / {proyecto}>"] [--solo-texto]`
3. Revisar SOLO `ENTREGA.json`, `DIFF.txt`, `CONTROLES.txt` (y los .md que Gemini produjo). El «SUCCESS» de agy no es evidencia.
4. Corregir en la misma conversacion: `python agy_run.py --seguir <id> --pedido "<correccion.md>"` (max 3 vueltas).
5. Veredicto: `python metricas.py veredicto <id> ACEPTADO|CORREGIDO|RECHAZADO "<motivo>" --desde <ISO> --hasta <ISO> --sesion <id>`.
6. Si es codigo/material del proyecto: `python aplicar.py <id>` (ensayo) y luego `--si`, con OK del usuario.

## Niveles → modelo
mecanico = Flash Low · lectura = Flash Medium · criterio = Argon Medium · criterio-alto = Argon High.

## Cuando conviene
Muchos archivos o imagenes que leer (sesiones grabadas, logs, extractos). NO conviene para scripts de ~100 lineas: escribirlos cuesta menos que delegarlos.

## Lecciones (se agregan con cada corrección)
- **01-11 primera prueba (generar_informe.py, 78 mil tokens, 4 min):** Gemini dijo SUCCESS pero escribió un script que no sirvió; ni siquiera pudo leer `delegar/skills/analizar-sesion/SKILL.md` (permiso negado). Claude lo reescribió. Un script de ~100 lineas NO conviene delegarlo: cuesta mas que escribirlo.
- **Que SI delegar:** leer muchas capturas/logs (sesiones del capturador) y devolver un resumen. Para eso hay que darle la sesion en `--copiar` y pedirle FLUJO.md / REPETITIVO.md / PREGUNTAS.md.
- Antes de delegar con un skill de Gemini, verificar que agy puede leerlo (el pedido debe traer el texto, o poner la carpeta en `--leer`).
- `escribio_fuera` en ENTREGA.json puede ser Claude u otra sesion trabajando a la vez; no prueba nada.
- No cerrar `agy.exe` a la fuerza: hay otras sesiones que lo usan.
