# G1 HMI Lab v0.7 — Matriz de contratos SDK2 y límites de fidelidad

Esta versión selecciona **interacción de servicio** (audio, gestos e indicadores IMU/BMS). No implementa DDS, firmware, cinemática, motores, síntesis audible ni actuaciones físicas. Los nombres y parámetros reflejan una selección documentada del SDK2 Python G1; la REST API, el WebSocket, sus eventos y los códigos RPC generados son propios del laboratorio.

**Fuentes oficiales consultadas el 14-10-2026** (rama `master`; **no se inmovilizó/verificó un SHA**):

- [AudioClient](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/g1/audio/g1_audio_client.py) y [audio API](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/g1/audio/g1_audio_api.py)
- [LocoClient](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/g1/loco/g1_loco_client.py) y [loco API](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/g1/loco/g1_loco_api.py)
- [G1ArmActionClient y `action_map`](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/g1/arm/g1_arm_action_client.py), [arm API](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/g1/arm/g1_arm_action_api.py) y [ejemplo oficial](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/g1/high_level/g1_arm_action_example.py)
- [IDL HG LowState_](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/idl/hg/LowState_.hpp), [IMUState_](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/idl/hg/IMUState_.hpp) y [BmsState_](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/idl/hg/BmsState_.hpp)

## Operaciones de servicio emuladas

| Cliente y método oficial | Servicio / API ID | JSON de parámetros internos | Retorno del wrapper Python revisado | Fachada REST |
|---|---|---|---|---|
| `AudioClient.GetVolume()` | `voice` / `1005` | `{}` | `(code, parsed_data)` si éxito, `(code, None)` en error | `GET /api/robots/g1/audio/volume` |
| `AudioClient.SetVolume(volume)` | `voice` / `1006` | `{"volume":n}` | `code` | `PUT /api/robots/g1/audio/volume` |
| `AudioClient.TtsMaker(text,speaker_id)` | `voice` / `1001` | `{"index":n,"text":...,"speaker_id":n}` | `code` | `POST /api/robots/g1/audio/tts` |
| `AudioClient.LedControl(R,G,B)` | `voice` / `1010` | `{"R":n,"G":n,"B":n}` | `code` | `PUT /api/robots/g1/led` |
| `LocoClient.SetTaskId(task_id)` | `sport` / `7106` | `{"data":n}` | `code` | llamada interna de los gestos loco |
| `LocoClient.WaveHand(turn_flag=False)` | delega a `SetTaskId` | `data=0` o `1` | `None` (el wrapper no devuelve el RPC) | `POST /api/robots/g1/commands/greeting` |
| `LocoClient.ShakeHand(stage=-1)` | delega a `SetTaskId` | `data=2` o `3` | `None` para etapa explícita, `code` al alternar etapa | `POST /api/robots/g1/commands/handshake` |
| `G1ArmActionClient.ExecuteAction(action_id)` | **`arm` / `7106`** | `{"data":n}` | `code` | `POST /api/robots/g1/commands/high-five` (18), `POST /api/robots/g1/commands/release-arms` (99) |

La coincidencia numérica del API ID `7106` entre `LocoClient.SetTaskId()` y `G1ArmActionClient.ExecuteAction()` **no los hace equivalentes**: el nombre del servicio, el cliente y el contrato determinan qué se invoca. Se preservan ambas trazas por separado en `sdk.rpc`.

La fuente oficial `action_map` asigna `"high five" → 18` y `"release arm" → 99`. El ejemplo oficial llama explícitamente a `release arm` tras esperar después de `high five`. En el laboratorio, el estudiante dispone de **dos botones separados**; cuando libera durante el temporizador virtual de High Five, se cancela solo ese temporizador. Un `ExecuteAction(99)` aceptado **no confirma liberación física, y no es un mecanismo de parada de emergencia**. El emulador no ofrece los demás valores del catálogo ni asegura que un G1 físico concreto tenga el servicio `arm`, sus acciones o el firmware apropiados; la lista real puede consultarse mediante `GetActionList()` en el SDK, que este laboratorio aún no implementa.

`TtsMaker()` registra el texto sin sonido. En el Python oficial revisado, `tts_index` empieza en 0 y la expresión `self.tts_index += self.tts_index` lo deja en 0; el adaptador lo refleja exclusivamente para esta instantánea revisada.

## Sensores observables (subconjunto de IDL, no DDS)

`GET /api/robots/g1/sensors` y el campo `sensors` de la telemetría pública contienen:

- `low_state.imu_state`: `rpy[3]`, `quaternion[4]`, `gyroscope[3]`, `accelerometer[3]`. RPY y giroscopio se expresan en radianes/rad/s y el acelerómetro en m/s². El cuaternión se **calcula matemáticamente** desde el RPY inyectado, no proviene de un sensor físico.
- `bms_state`: `soc`, `soh`, `current`, `bmsvoltage[3]`, `temperature[12]`. Los campos eléctricos/temperaturas que no se escalan/verifican se mantienen como **raw** ficticio; `soc` se sincroniza con el alias legado `battery_percent`.
- `low_state.mode_pr`, `mode_machine`, `tick` son valores iniciales ficticios (cero); **no** reproducen una FSM ni un reloj del robot.
- `source`, `valid`, `sensor_seq`, `sensor_updated_at` son metadatos **propios del emulador**. La desconexión marca lecturas retenidas como no válidas; un tick del WebSocket sin cambio de sensor no fabrica una nueva medida.

**Cambio intencional de v0.6 a v0.7:** ya no se representa `MotorState_`, no hay `motor_state`, `profile`, `joint_names`, selección de articulación ni inyección de articulaciones en esta API. Aunque `LowState_` oficial contiene estados de motor, aquí se expone explícitamente un **subconjunto IMU**; no se anuncia ni devuelve una estructura LowState_ completa. La inyección de `motor_state` recibe HTTP `422` por contrato estricto.

`PATCH /api/simulator/g1/sensors` permite al docente inyectar únicamente `imu_state` y `bms_state`. Como simplificación didáctica, restringe SOC/SOH a 0–100, vectores IMU a tres números finitos con magnitud ≤1000, `volume` a 0–100, TTS a 1–200 caracteres y `speaker_id` a 0–255. **No son límites certificados del firmware**.

## Respuestas, temporalidad y seguridad

Las respuestas de comandos exponen `sdk.rpc` (`client`, `service`, `api_id`, `parameters`, `rpc_code`, `origin=synthetic_rpc_stub`) y `sdk.sdk_return` más una envoltura HTTP propia. `rpc_code=0` denota **aceptación sintética**, jamás la confirmación de completar un movimiento real. El docente puede inyectar un fallo arbitrario no nulo de un solo uso también en `G1ArmActionClient.ExecuteAction`. Si falla, la acción no se inicia ni se altera `last_arm_action_id`.

`idle`, `busy`, `offline`, HTTP 409 por ocupación, HTTP 503 por desconexión, el temporizador virtual de 3 s y los eventos `high_five.started`/`.finished` o `arms.release_requested` **son semántica propia del laboratorio**. No corresponden a estados FSM ni a una telemetría de ejecución de Unitree. En especial, `.finished` indica fin del temporizador, no observación del brazo.

El docente modifica las fuentes ficticias en `/simulator` mediante `/api/simulator/g1/...`; es posible proteger esas APIs con `SIMULATOR_TOKEN`. Los alumnos ven `/` y consumen únicamente `/api/robots/g1/...` y `/ws/robots/g1/telemetry`. Estado y muestreo son compartidos en memoria de **un solo proceso/worker**. Para conectarlo a un G1 físico habrá que desarrollar un adaptador validado contra la versión de SDK y firmware de ese dispositivo, con controles de seguridad apropiados.


## Estado de visualización local (extensión opcional, fuera del SDK)

`GET /api/simulator/g1/visualization/status` informa al docente si responde el
puente HTTP local y si su Viewer está activo (`connected`, `viewer_running`),
además de `checked_at` y `last_successful_check_at`. Es metadato **del laboratorio**:
no representa estado operativo DDS/SDK2, conexión física del G1, estado IMU/BMS,
confirmación de un gesto ni una lectura de MuJoCo. La ruta docente admite el
mismo token `X-Simulator-Token` que las restantes rutas `/api/simulator/g1/*`.
