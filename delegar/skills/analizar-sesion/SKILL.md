---
name: analizar-sesion
description: "Analiza una sesion grabada por capturador (events.jsonl + frames) y escribe el flujo de trabajo paso a paso, lo repetitivo y que se puede automatizar."
---
# analizar-sesion
Entrada: una copia de `capturador/sesiones/<fecha>/` (events.jsonl, timeline.md, frames/*.jpg, archivos_descargados/, transcripcion.txt si existe).

Haz esto, en orden:
1. Lee `timeline.md` y `events.jsonl`. Mira las capturas (`frames/`) de los momentos clave: cada cambio de aplicacion, cada copia al portapapeles y cada archivo nuevo.
2. Escribe `FLUJO.md` con los pasos reales, numerados, cada uno con: hora, donde (programa/ventana o app del celular), que hizo, que dato movio (monto, ID PIX, nombre, fecha) y de donde a donde.
3. Escribe `REPETITIVO.md`: pasos que se repiten, copiar/pegar entre sistemas, busquedas manuales, comparaciones a ojo, re-tipeos. Para cada uno: cuantas veces, cuanto tarda aprox. y como se podria automatizar (OCR/Gemini, extension de Chrome, API, script).
4. Escribe `PREGUNTAS.md`: lo que no se entiende y debe aclarar la persona (decisiones que toma, reglas implicitas, casos raros).
5. Si hay capturas con `pantalla_negra: true` (apps bloqueadas), dilo y apoyate en los textos y en la transcripcion.
No inventes pasos: cada afirmacion cita la hora o el archivo de captura de donde sale.
