# 🔗 Guía de Integración Híbrida: MediBot Android ↔ Unitree G1 SDK

Esta guía explica cómo ejecutar y probar la integración entre la aplicación Android **MediBot** y el simulador local **FastAPI / SDK2 Unitree G1**.

---

## 🏗️ Arquitectura de la Integración (Opción C - Híbrida)

- **MediBot Android (Cerebro Operativo):**
  - Mantiene la máquina de estados de logística hospitalaria (10 estados), despacho de misiones (gases en sangre, hemoterapia, farmacia), cálculo de rutas por nodos, alertas críticas, auditoría en Room y seguridad operativa.
- **Unitree G1 SDK FastAPI (Cuerpo y Actuadores del Robot):**
  - Emula las APIs del SDK2 de Unitree (`AudioClient`, `LocoClient`, `G1ArmActionClient`, sensores IMU/BMS y puente 3D opcional MuJoCo).
  - Proporciona la consola HMI web para visualizar el estado físico en `http://localhost:8000/`.

### 🔄 Flujo de Sincronización en Tiempo Real

1. **LED RGB HRI:**
   Cuando MediBot cambia el color HRI (Cyan en tránsito `#00F5D4`, Ámbar en pausa `#FFAB00`, Rojo en detención `#FF1744`, Verde en entrega `#00E676`), se envía inmediatamente a `PUT /api/robots/g1/led`.
2. **Síntesis de Voz (TTS):**
   Cada mensaje sonoro de MediBot (*"Unidad médica en tránsito"*, *"Atención: pasillo bloqueado"*, etc.) se envía a `POST /api/robots/g1/audio/tts`, registrándose en el simulador G1.
3. **Gestos Sociales del G1:**
   - **Saludar (`WaveHand`):** Se dispara automáticamente cuando el robot llega a destino (`AWAITING_NFC_HANDOFF`) o manualmente desde la app.
   - **Chocar los cinco (`High Five` - ExecuteAction 18) y Liberar Brazos (99):** Se disparan automáticamente tras la entrega validada con éxito por NFC en la UTI.
4. **Telemetría y Estado de Misión:**
   MediBot informa a FastAPI sobre la misión en curso (`POST /api/robots/g1/medibot/status`). La pantalla web `http://localhost:8000/` refleja en vivo la misión hospitalaria, el nodo actual y el progreso del robot.

---

## 🚀 Pasos para Iniciar y Probar

### 1. Iniciar el Servidor del SDK FastAPI (PC)

Abrir una terminal en la carpeta raíz del SDK (`c:\Users\facup\Desktop\SDK`):

```powershell
py -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

*(O simplemente podés hacer doble clic en el archivo [`iniciar_simulador.bat`](file:///c:/Users/facup/Desktop/SDK/iniciar_simulador.bat))*

Verificar abriendo en el navegador:
- **HMI G1:** [http://localhost:8000/](http://localhost:8000/)
- **Documentación OpenAPI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Consola Docente:** [http://localhost:8000/simulator](http://localhost:8000/simulator)

---

### 2. Ejecutar MediBot en Android

Abrir la carpeta `TPO-MediBot` en **Android Studio**:

1. Sincronizar Gradle (`File -> Sync Project with Gradle Files`).
2. Ejecutar la app en un **Emulador de Android** o dispositivo físico.

#### Configuración de Red según el entorno:
- **En Emulador oficial de Android:**
  La app viene preconfigurada para conectarse a `http://10.0.2.2:8000` (el alias que utiliza el emulador para referenciar a `localhost` de tu PC).
- **En Dispositivo Físico conectado por Wi-Fi:**
  Asegurate de que el teléfono y la PC estén en la misma red Wi-Fi.
  1. Obtené la IP de tu PC (por ejemplo `ipconfig` -> `192.168.1.50`).
  2. En MediBot, tocá el botón violeta del **Panel de Ingeniería**.
  3. En la sección **PUENTE SDK G1 (FASTAPI)**, ingresá la URL: `http://192.168.1.50:8000`.

---

### 3. Verificar la Conexión

1. En el encabezado del **Dashboard** de MediBot verás el badge:
   `G1 SDK CONECTADO` (en color cian).
2. En el panel de ingeniería (botón flotante violeta), verás el estado en verde:
   `CONECTADO A FASTAPI (:8000)`.
3. Podés probar los botones rápidos de gestos:
   - **Saludar:** Verás en la consola web de FastAPI el evento `greeting.started` y `greeting.finished`.
   - **High Five:** Verás el evento `high_five.started` y el posterior retorno.
4. Despachá una misión desde la pestaña **Misiones**:
   - Al iniciar la marcha, el LED del G1 en la web pasa a color cian y el mensaje de voz aparece en la pantalla del simulador.
   - En la sección **SUPERVISIÓN MEDIBOT · LOGÍSTICA HOSPITALARIA** de la HMI web verás el nombre de la misión, nodo actual y porcentaje de avance.
   - Al llegar a destino (UTI), el robot saluda (`WaveHand`), y al validar la entrega se ejecuta el High Five (`ExecuteAction 18`).
