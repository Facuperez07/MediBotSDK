
import time
import mujoco
import mujoco.viewer

# Cargar el modelo G1
model = mujoco.MjModel.from_xml_path(
    "unitree_robots/g1/scene_29dof.xml"
)

data = mujoco.MjData(model)

# Identificar la articulación del hombro izquierdo
joint = model.joint("left_shoulder_pitch_joint")
idx = joint.qposadr[0]

posicion_inicial = float(data.qpos[idx])

with mujoco.viewer.launch_passive(model, data) as viewer:

    inicio = time.monotonic()

    while viewer.is_running():

        tiempo = time.monotonic() - inicio

        # Esperar 2 segundos y mover el brazo
        # progresivamente durante otros 2 segundos
        progreso = max(0.0, min((tiempo - 2) / 2, 1.0))

        with viewer.lock():
            data.qpos[idx] = posicion_inicial - 0.8 * progreso

            # Actualizar la geometría del robot
            mujoco.mj_forward(model, data)

        viewer.sync()
        time.sleep(0.03)

