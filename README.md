# Unitree G1 HMI Lab v0.7 — Interacción de servicio

Un servidor **FastAPI autocontenido** para prácticas de HMI móvil de Unitree G1. No necesita instalar `unitree_sdk2py`, MuJoCo, CycloneDDS ni un gemelo digital. La fachada REST/WebSocket representa contratos **seleccionados** del SDK2; no es un dispositivo DDS ni puede controlar un G1 físico.

La versión v0.7 prioriza la interacción con personas: **IMU, BMS, conectividad, LED RGB, volumen, solicitud TTS y gestos**. Se retira totalmente el selector de articulaciones y su inyección; el campo `motor_state` ya no forma parte de la API de este laboratorio. Se añade **High Five** y una orden explícita de **Release Arm** mediante `G1ArmActionClient.ExecuteAction(18|99)`, provenientes del `action_map` oficial. Su disponibilidad real es dependiente del firmware. Consultar `SDK_CONTRACTS.md`.

## Iniciar

Python 3.11+ recomendado:

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Con Docker:

```bash
docker build -t g1-hmi-lab:0.7 .
docker run --rm -p 8000:8000 -e SIMULATOR_TOKEN='clave-docente' g1-hmi-lab:0.7
```

| Página | Dirección | Usuarios |
|---|---|---|
| HMI G1 | `http://localhost:8000/` | Estudiantes: ver sensores y enviar comandos |
| Consola de simulación | `http://localhost:8000/simulator` | Docente: inyectar valores ficticios y un fallo RPC de un solo uso |
| OpenAPI/Swagger | `http://localhost:8000/docs` | Referencia de los endpoints REST del emulador |

`SIMULATOR_TOKEN` es opcional en modo local. Si se define, las rutas `/api/simulator/g1/...` exigen la cabecera `X-Simulator-Token`; no publicar la consola docente abierta en una red no confiable. Un solo `--workers 1`, ya que el estado y reloj de muestras son en memoria.

## Endpoints de operador

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/robots`, `/api/robots/g1/state` | Estado virtual |
| GET | `/api/robots/g1/telemetry`, `/api/robots/g1/sensors` | Muestra global y sensores IMU/BMS |
| GET | `/api/robots/g1/events` | Eventos operativos |
| PUT | `/api/robots/g1/led` | `LedControl(R,G,B)` |
| GET/PUT | `/api/robots/g1/audio/volume` | `GetVolume` / `SetVolume` |
| POST | `/api/robots/g1/audio/tts` | `TtsMaker` sin audio físico |
| POST | `/api/robots/g1/commands/greeting` | `WaveHand` |
| POST | `/api/robots/g1/commands/handshake` | `ShakeHand` |
| POST | `/api/robots/g1/commands/high-five` | `G1ArmActionClient.ExecuteAction(18)` |
| POST | `/api/robots/g1/commands/release-arms` | `G1ArmActionClient.ExecuteAction(99)` |
| WS | `/ws/robots/g1/telemetry` | Actualizaciones aproximadas de 1/s |

Ejemplo rápido:

```bash
curl -s -X POST http://localhost:8000/api/robots/g1/commands/high-five
curl -s -X POST http://localhost:8000/api/robots/g1/commands/release-arms
curl -s http://localhost:8000/api/robots/g1/sensors
```

El segundo comando puede interrumpir **solo el temporizador virtual High Five**. No es parada de emergencia física. Las respuestas separan HTTP, código RPC **sintético** y estado actual; ver `SDK_CONTRACTS.md`.

## Endpoints docentes

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/simulator/g1/state`, `/api/simulator/g1/events` | Estado/trazas completas |
| PATCH | `/api/simulator/g1/telemetry` | Conexión, batería/alias de `soc`, temperatura virtual heredada, descarga sintética |
| PATCH | `/api/simulator/g1/sensors` | Inyectar `imu_state` y `bms_state` (no `motor_state`) |
| POST | `/api/simulator/g1/next-rpc-failure` | Fallo de un solo uso, incluyendo `G1ArmActionClient.ExecuteAction` |
| POST | `/api/simulator/g1/reset` | Reiniciar robot, sensores, adaptadores, temporizadores y fallos |

Ejemplo de inyección de orientación (radianes) y estado de carga:

```bash
curl -s -X PATCH http://localhost:8000/api/simulator/g1/sensors \
 -H 'Content-Type: application/json' -H 'X-Simulator-Token: clave-docente' \
 -d '{"imu_state":{"rpy":[0.2,-0.1,0]},"bms_state":{"soc":19,"soh":91}}'
```

La interfaz docente introduce RPY en grados y convierte a radianes antes de llamar a la API. La HMI muestra horizonte artificial, SOC/SOH, corriente raw y vigencia de lecturas. Una nueva muestra WebSocket no implica nueva medición física: `sensor_seq` cambia solo cuando cambia un sensor inyectado, el alias `soc` o la descarga sintética.

## Propuesta de práctica

El docente fija SOC bajo, inclina la IMU y luego desconecta virtualmente al G1. El estudiante debe comunicar estado de datos, batería baja e inclinación, y permitir ejecutar `WaveHand`, `ShakeHand`, `High Five` y liberación de brazos, distinguiendo aceptación RPC ficticia de finalización física. El docente puede provocar un fallo único de `ExecuteAction` y evaluar cómo lo refleja la HMI.

## Estructura y pruebas

```text
main.py           API, autorización, estados y reloj central
sdk_emulator.py   AudioClient, LocoClient y G1ArmActionClient emulados
sensors.py        Subconjunto JSON de campos HG IMU/BMS (sin motores)
web/              HMI del alumno y consola del docente, independientes
SDK_CONTRACTS.md  Matriz y límites de fidelidad frente al SDK2 oficial
test_main.py      Pruebas de contratos, sensores, regresión y WebSocket
```

```bash
pip install -r requirements-dev.txt
pytest -q
```

No distribuir como SDK2 compatible binario, servidor DDS ni simulador del movimiento real. Comprobar versión del SDK, catálogo de acciones y firmware antes de conectar un robot físico.


## Visualización opcional MuJoCo (extensión docente)

No cambia los contratos REST/WebSocket del operador ni convierte los datos IMU/BMS
sintéticos en lecturas de MuJoCo. La instalación de MuJoCo sigue siendo **opcional**
para el laboratorio, y se realiza solo en el equipo que ejecuta el Viewer.

1. Desde la raíz de `unitree_mujoco` y en su entorno, ejecutar `python puente_g1.py`.
2. Desde la raíz del backend, ejecutar:

   ```bash
   MUJOCO_BRIDGE_URL=http://127.0.0.1:8765/intent uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
   ```

3. La consola `/simulator` ya incluye el indicador dentro de `simulator.html`,
   `simulator.js` y `styles.css`: no hay que modificar etiquetas a mano ni instalar
   scripts adicionales. Comparte el campo `Token docente` existente. Pulsar
   **Conectar** para actualizar ambos diagnósticos con ese token.
4. El indicador muestra **Conectado**, **Desconectado** o **No configurado**,
   con la última verificación exitosa, y se consulta cada cinco segundos.

`GET /health` del puente devuelve HTTP 200 exclusivamente mientras el Viewer
pasivo está activo; devuelve 503 en otro caso. El puente solo escucha en
`127.0.0.1:8765`. Su `POST /intent` conserva el comportamiento anterior.
`GET /api/simulator/g1/visualization/status` es exclusivo del docente y respeta
`X-Simulator-Token`. La marca `last_successful_check_at` indica la última
comprobación HTTP satisfactoria, **no** el éxito físico de un gesto ni el estado
del robot real. El estado del puente no afecta `connected` en la telemetría G1.

Si se ejecuta el backend en Docker, `127.0.0.1` designa el contenedor: se necesita
configurar una dirección alcanzable desde él. No publicar el puente en interfaces
externas sin controles de acceso adecuados.
