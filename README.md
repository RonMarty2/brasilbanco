# Sistema Semi-Automático de Control y Conciliación de Remesas (Brasil ⇄ Bolivia)

> Sistema diseñado para back-office de mesas de cambio y remesas entre Brasil y Bolivia, con enfoque **Human-in-the-Loop**, visión por inteligencia artificial (Gemini Flash), base de datos SQLite y sincronización con Google Sheets.

---

## 🚀 Arquitectura del Proyecto

```text
brasilbanco/
├── backend/
│   ├── main.py                 # Servidor FastAPI con todos los endpoints REST
│   ├── database.py             # Motor SQLite con índices y soporte WAL
│   ├── ai_vision.py            # Extractor Gemini Flash para vouchers y extractos
│   ├── reconciler.py           # Motor de cruce (coincidencias, empates, fraude, fechas pasadas)
│   ├── sheets_sync.py          # Sincronización resiliente con Google Sheets (tolerante a fallos)
│   ├── requirements.txt        # Dependencias de Python
│   └── .env.example            # Variables de configuración
├── frontend_pwa/
│   ├── index.html              # App PWA Móvil completa (4 pestañas: Escaneo, Espera, Extractos, Historial)
│   ├── app.js                  # Lógica de cliente, edición táctil, desempate y confirmación
│   ├── manifest.json           # Web Share Target API para recibir vouchers desde WhatsApp
│   └── sw.js                   # Service Worker y modo offline
├── chrome_extension/
│   ├── manifest.json           # Extensión Manifest V3
│   ├── popup.html / popup.js   # Botón rápido para enviar extracto en pantalla al servidor
│   └── content.js              # Lector DOM seguro de tablas bancarias (Itaú, Bradesco, etc.)
├── storage/
│   └── Historial/              # Archivos organizados automáticamente por YYYY-MM-DD
├── Dockerfile & docker-compose.yml
└── README.md
```

---

## 🛠️ Reglas de Negocio Implementadas

1. **Origen Obligatorio:** Todo voucher debe asignarse a un Grupo de WhatsApp antes de procesar.
2. **Obtención de Extractos:**
   - **Vía A (PC):** Extensión de Chrome que lee la tabla del banco abierto sin bots de login.
   - **Vía B (Socio Brasil):** Subida de fotos/PDFs del extracto procesados con Gemini Flash.
3. **Semáforo Inteligente:**
   - 🟢 **VERDE (Match Exacto):** Coincidencia única confirmada con depósito libre -> Se bloquea depósito y marca 🟢 SÍ en Google Sheets.
   - 🟡 **AMARILLO (Colisión / Empate):** 2 o más depósitos con el mismo monto -> Lista interactiva para desempatar con 1 toque.
   - 🔴 **ROJO (Sin coincidencia):** Permite dejar "En Espera" (🔴 en Sheets) o botón de emergencia `🔓 Forzar SÍ Manual`.
   - 🚨 **ROJO CRÍTICO (Fraude / Duplicado):** Detecta si el voucher o ID PIX ya fue cobrado en otra fecha o por otro grupo.
4. **Fechas Pasadas:** Se tickea y bloquea en la fecha original del voucher y anota fecha de hoy y grupo.

---

## 💻 Puesta en Marcha Local

### 1. Backend Python
```bash
cd backend
python -m venv venv
# En Windows:
.\venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python main.py
```
El servidor arrancará en: `http://localhost:8000`  
La PWA móvil estará disponible en: `http://localhost:8000/pwa`

### 2. Instalar la Extensión de Chrome
1. Abre Google Chrome y ve a `chrome://extensions/`.
2. Activa el interruptor **"Modo de desarrollador"** (Developer mode) en la esquina superior derecha.
3. Haz clic en **"Cargar descomprimida"** (Load unpacked).
4. Selecciona la carpeta `chrome_extension` del repositorio.

---

## 📱 Instalar la PWA en el Móvil
1. Abre Chrome o Safari en tu teléfono conectado a la misma red Wi-Fi o mediante ngrok: `http://<IP_DE_TU_PC>:8000/pwa`.
2. Toca en el menú del navegador y selecciona **"Agregar a la pantalla principal"** o **"Instalar aplicación"**.
3. Ahora podrás compartir comprobantes directamente desde WhatsApp a la app.
