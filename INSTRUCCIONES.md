# Instalación — indicador MuJoCo integrado (G1 HMI Lab)

Este paquete ya contiene el directorio `web/` **completo y actualizado** a partir de
los cinco archivos originales enviados por el usuario. No es necesario insertar
manualmente `<script>` ni `<link>`: el indicador está integrado en `simulator.html`,
`simulator.js` y `styles.css`. `hmi.html` y `hmi.js` son copias idénticas de los originales.

## Aplicación, con copia de seguridad previa

1. Detener Uvicorn y el `puente_g1.py` anterior (no puede haber dos procesos en el puerto 8765).
2. En la carpeta del backend G1, reemplazar los archivos de la raíz por los de este ZIP;
   copiar **la carpeta `web/` completa** sobre la existente.
3. Copiar `mujoco/puente_g1.py` a la raíz de `unitree_mujoco/` (allí donde ya tenías el puente).
   El nuevo puente conserva `POST /intent` y agrega `GET /health`.
4. No instalar MuJoCo en el backend: solo lo necesita el equipo que ejecuta el Viewer.

## Arranque local: dos terminales, mismo equipo

Terminal 1 (desde `unitree_mujoco/`, con su entorno Python activado):

```bash
python puente_g1.py
```

En macOS puede ser necesario `mjpython puente_g1.py`.

Terminal 2 (desde la carpeta del backend, con su entorno activado):

```bash
MUJOCO_BRIDGE_URL=http://127.0.0.1:8765/intent uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

Abrir `http://localhost:8000/simulator`. Si se usa `SIMULATOR_TOKEN`, escribirlo
una sola vez en el campo **Token docente** y pulsar **Conectar**. El indicador
consulta el estado cada 5 segundos. La interfaz del alumno (`/`) no cambia.

## Comprobaciones

```bash
curl -i http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8000/api/simulator/g1/visualization/status
pytest -q
```

Para la segunda llamada, agregar `-H 'X-Simulator-Token: TU_TOKEN'` si hay token docente.
Probar también el botón *Saludar* desde la HMI: el comportamiento anterior permanece.
Después cerrar el Viewer: debería reflejarse *Desconectado* en el indicador,
sin desconectar artificialmente el G1 de la telemetría de estudiantes.

El indicador monitorea únicamente puente y Viewer, no confirma resultados de la física.
Sin `MUJOCO_BRIDGE_URL` el backend funciona en modo emulado habitual e indica
*No configurado*. El chequeo de salud se hace desde FastAPI y no desde el navegador.

**Redes y Docker:** `127.0.0.1` es local a cada proceso/contendor. Estas instrucciones
suponen ambos procesos nativos en la misma computadora. El puente escucha solo en
loopback; no debe exponerse a redes de terceros sin autenticación y protecciones.
