"""Puente visual del Unitree G1 (29 DoF) con una coreografía CUSTOM didáctica.

GET /health: diagnóstico opcional de Viewer.
POST /intent: saludar | reposo | high_five | release_arms | custom_demo.

'custom_demo' es una SECUENCIA CINEMÁTICA INVENTADA: levanta ambos brazos,
representa dos pasos (izquierdo/derecho) y termina con los brazos en V.
NO ES una acción del SDK/firmware, una marcha estabilizada ni una simulación
física de contacto: NO llama a mj_step, solo qpos + mj_forward.

Ejecutar desde la raíz de unitree_mujoco con su entorno MuJoCo activado.
"""

import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue

import mujoco
import mujoco.viewer

comandos = Queue()
viewer_active = threading.Event()
ACCIONES = {"saludar", "reposo", "high_five", "release_arms", "custom_demo"}


class Receptor(BaseHTTPRequestHandler):
    def responder(self, codigo, contenido):
        payload = json.dumps(contenido).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path != "/health":
            self.responder(404, {"error": "Ruta desconocida"})
            return
        running = viewer_active.is_set()
        self.responder(200 if running else 503, {
            "status": "ok" if running else "unavailable",
            "viewer_running": running,
        })

    def do_POST(self):
        if self.path != "/intent":
            self.responder(404, {"error": "Ruta desconocida"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024:
                raise ValueError("Longitud inválida")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Se requiere un objeto JSON")
            accion = payload.get("action")
        except (ValueError, TypeError, AttributeError):
            self.responder(400, {"error": "JSON inválido"})
            return
        if accion not in ACCIONES:
            self.responder(400, {"error": "Acción no implementada"})
            return
        if not viewer_active.is_set():
            self.responder(503, {"error": "Viewer no disponible"})
            return
        comandos.put(accion)
        # 202 solo significa que se recibió/encoló, NO que haya terminado.
        self.responder(202, {"status": "accepted", "action": accion})


def limitar(joint, value):
    """Respetar el rango del MJCF para las articulaciones de 1 DoF."""
    if joint.limited:
        lo, hi = joint.range
        margen = min(0.01, max(0.0, (float(hi) - float(lo)) / 10))
        return max(float(lo) + margen, min(float(hi) - margen, value))
    return value


def suavizar(p):
    p = max(0.0, min(p, 1.0))
    return p * p * (3.0 - 2.0 * p)


model = mujoco.MjModel.from_xml_path("unitree_robots/g1/scene_29dof.xml")
data = mujoco.MjData(model)

# Conservamos el saludo y High Five ya probados, añadiendo SOLO las
# articulaciones necesarias para una secuencia VISUAL de brazos y piernas.
HIGH_FIVE = {
    "left_shoulder_pitch_joint": -1.25,
    "left_shoulder_roll_joint": 0.45,
    "left_shoulder_yaw_joint": 0.25,
    "left_elbow_joint": 0.85,
    "left_wrist_roll_joint": 0.20,
    "left_wrist_pitch_joint": -0.35,
}
CUSTOM_JOINTS = {
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint", "right_elbow_joint",
    "right_wrist_roll_joint", "right_wrist_pitch_joint",
    "left_hip_pitch_joint", "left_knee_joint", "left_ankle_pitch_joint",
    "right_hip_pitch_joint", "right_knee_joint", "right_ankle_pitch_joint",
    "waist_yaw_joint",
}
NOMBRES = sorted(set(HIGH_FIVE) | CUSTOM_JOINTS)
articulaciones = {}
for nombre in NOMBRES:
    joint = model.joint(nombre)  # Error claro si cambia el nombre en el MJCF.
    idx = joint.qposadr[0]
    articulaciones[nombre] = (idx, joint, float(data.qpos[idx]))

base = model.joint("floating_base_joint")
if base.type != mujoco.mjtJoint.mjJNT_FREE:
    raise RuntimeError("Se requiere floating_base_joint de tipo free")
BASE_X = int(base.qposadr[0])
BASE_Z = BASE_X + 2  # Posición XYZ; NO tocamos el cuaternión de la base.
BASE_Z_REPOSO = float(data.qpos[BASE_Z])

reposo = {nombre: origen for nombre, (_, _, origen) in articulaciones.items()}


def pose(desplazamientos=None):
    """Pose a partir de la postura inicial, con offsets en radianes."""
    resultado = reposo.copy()
    for nombre, offset in (desplazamientos or {}).items():
        _, joint, origen = articulaciones[nombre]
        resultado[nombre] = limitar(joint, origen + offset)
    return resultado


saludo = pose({"left_shoulder_pitch_joint": -0.8})
high_five = pose(HIGH_FIVE)
poses_normales = {
    "saludar": saludo,
    "reposo": reposo,
    "high_five": high_five,
    "release_arms": reposo,
}

# Brazos levantados a la vista, no una trayectoria certificada.
BRAZOS_ABIERTOS = {
    "left_shoulder_pitch_joint": -1.35,
    "right_shoulder_pitch_joint": -1.35,
    "left_shoulder_roll_joint": 0.65,
    "right_shoulder_roll_joint": -0.65,
    "left_elbow_joint": 0.55,
    "right_elbow_joint": 0.55,
    "left_wrist_pitch_joint": -0.15,
    "right_wrist_pitch_joint": -0.15,
}
BRAZOS_V = {
    **BRAZOS_ABIERTOS,
    "left_shoulder_pitch_joint": -2.25,
    "right_shoulder_pitch_joint": -2.25,
    "left_shoulder_roll_joint": 0.55,
    "right_shoulder_roll_joint": -0.55,
    "left_elbow_joint": 0.25,
    "right_elbow_joint": 0.25,
}


def pasos_custom(x_inicial):
    """Secuencia (nombre, duración, pose, x de base, z de base).

    Los avances de la base y flexiones de las piernas son PANTOMIMA de dos
    pasos, no marcha con apoyo, dinámica ni compensación de equilibrio.
    """
    z = BASE_Z_REPOSO
    return deque([
        ("Abrir ambos brazos", 1.0, pose(BRAZOS_ABIERTOS), x_inicial, z),
        ("Paso 1: levantar pierna izquierda", 0.8, pose({
            **BRAZOS_ABIERTOS,
            "left_shoulder_pitch_joint": -1.7,
            "right_shoulder_pitch_joint": -0.9,
            "left_hip_pitch_joint": -0.48,
            "left_knee_joint": 0.85,
            "left_ankle_pitch_joint": -0.25,
            "waist_yaw_joint": 0.10,
        }), x_inicial + 0.04, z + 0.045),
        ("Paso 1: apoyar pierna izquierda", 0.85, pose({
            **BRAZOS_ABIERTOS,
            "left_hip_pitch_joint": -0.20,
            "left_knee_joint": 0.18,
            "left_ankle_pitch_joint": -0.08,
        }), x_inicial + 0.15, z),
        ("Paso 2: levantar pierna derecha", 0.8, pose({
            **BRAZOS_ABIERTOS,
            "left_shoulder_pitch_joint": -0.9,
            "right_shoulder_pitch_joint": -1.7,
            "right_hip_pitch_joint": -0.48,
            "right_knee_joint": 0.85,
            "right_ankle_pitch_joint": -0.25,
            "waist_yaw_joint": -0.10,
        }), x_inicial + 0.19, z + 0.045),
        ("Paso 2: apoyar pierna derecha", 0.85, pose({
            **BRAZOS_ABIERTOS,
            "right_hip_pitch_joint": -0.20,
            "right_knee_joint": 0.18,
            "right_ankle_pitch_joint": -0.08,
        }), x_inicial + 0.30, z),
        ("Celebración: ambos brazos en V", 1.0, pose(BRAZOS_V), x_inicial + 0.30, z),
        ("Mantener pose final", 1.0, pose(BRAZOS_V), x_inicial + 0.30, z),
        ("Volver a reposo", 1.2, reposo.copy(), x_inicial + 0.30, z),
    ])


def tomar_estado():
    """Llamar solamente desde el hilo que actualiza el Viewer."""
    return ({nombre: float(data.qpos[idx]) for nombre, (idx, _, _) in articulaciones.items()},
            float(data.qpos[BASE_X]), float(data.qpos[BASE_Z]))


servidor = ThreadingHTTPServer(("127.0.0.1", 8765), Receptor)
hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
hilo.start()
print("Puente G1 iniciado: http://127.0.0.1:8765/intent", flush=True)
print("Acciones:", ", ".join(sorted(ACCIONES)), flush=True)
print("CUSTOM: brazos + dos pasos coreografiados; NO es una función Unitree", flush=True)

pendientes = deque()
segmento = None


def siguiente_segmento():
    global segmento
    if not pendientes:
        segmento = None
        return
    nombre, duracion, destino, destino_x, destino_z = pendientes.popleft()
    # La pose de inicio es SIEMPRE la pose que aparece en pantalla, para
    # permitir interrumpir la coreografía desde reposo/release_arms.
    inicio_joints, inicio_x, inicio_z = tomar_estado()
    segmento = (time.monotonic(), duracion, inicio_joints, destino,
                inicio_x, destino_x, inicio_z, destino_z)
    print("  >", nombre, flush=True)


try:
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer_active.set()
        try:
            while viewer.is_running():
                try:
                    # Si llegan varias órdenes juntas, aplicar la más reciente.
                    accion = comandos.get_nowait()
                    while True:
                        try:
                            accion = comandos.get_nowait()
                        except Empty:
                            break
                    print("Intención recibida:", accion, flush=True)
                    if accion == "custom_demo":
                        pendientes = pasos_custom(float(data.qpos[BASE_X]))
                    else:
                        # Conservar el avance X de la representación custom.
                        pendientes = deque([(
                            accion, 2.0, poses_normales[accion].copy(),
                            float(data.qpos[BASE_X]), BASE_Z_REPOSO,
                        )])
                    siguiente_segmento()
                except Empty:
                    pass

                if segmento is not None:
                    (inicio, duracion, desde, hasta,
                     desde_x, hasta_x, desde_z, hasta_z) = segmento
                    fraccion = max(0.0, min((time.monotonic() - inicio) / duracion, 1.0))
                    p = suavizar(fraccion)
                    with viewer.lock():
                        for nombre, (idx, _, _) in articulaciones.items():
                            data.qpos[idx] = desde[nombre] + (hasta[nombre] - desde[nombre]) * p
                        data.qpos[BASE_X] = desde_x + (hasta_x - desde_x) * p
                        data.qpos[BASE_Z] = desde_z + (hasta_z - desde_z) * p
                        mujoco.mj_forward(model, data)
                    if fraccion >= 1.0:
                        siguiente_segmento()
                viewer.sync()
                time.sleep(0.03)
        finally:
            viewer_active.clear()
finally:
    viewer_active.clear()
    servidor.shutdown()
    servidor.server_close()
