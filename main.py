"""Unitree G1 HMI Lab v0.7 — separated operator/teacher surfaces.



HTTP/WS façade and selected Python SDK2-like adapter semantics; NO DDS or physics.

Run with one process/worker: all state and the global telemetry ticker are in memory.

"""

import asyncio

import os

from copy import deepcopy

from collections import deque

from contextlib import asynccontextmanager

from datetime import datetime, timezone

from hmac import compare_digest

from pathlib import Path

from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from urllib.parse import urlsplit, urlunsplit
import json



from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse

from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, ConfigDict, Field



from sdk_emulator import AudioClientEmulator, LocoClientEmulator, G1ArmActionClientEmulator, RpcStub

from sensors import default_sensors, snapshot, quaternion_from_rpy



ROOT = Path(__file__).parent

# Internal bridge only; when unset, the v0.7 emulator works as before.
MUJOCO_BRIDGE_URL = os.getenv("MUJOCO_BRIDGE_URL", "").strip()


def _post_visual_intent(action: Literal["saludar", "reposo", "high_five", "release_arms"]) -> None:
    payload = json.dumps({"action": action}).encode("utf-8")
    request = UrlRequest(
        MUJOCO_BRIDGE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        if response.status != 202:
            raise RuntimeError("El puente no confirmó la recepción de la intención")


async def send_visual_intent(action: Literal["saludar", "reposo", "high_five", "release_arms"]) -> None:
    if not MUJOCO_BRIDGE_URL:
        return
    try:
        # Keep the Uvicorn event loop responsive while calling the local bridge.
        await asyncio.to_thread(_post_visual_intent, action)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="No se pudo entregar la intención al puente visual de MuJoCo",
        ) from exc







# Teacher-only bridge health check. This is independent of the synthetic G1 state.
def _check_visual_bridge_health() -> bool:
    parsed = urlsplit(MUJOCO_BRIDGE_URL)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    # Current internal bridge exposes /intent and /health as siblings.
    base_path = parsed.path.rstrip("/").rsplit("/", 1)[0]
    health_url = urlunsplit((parsed.scheme, parsed.netloc, base_path + "/health", "", ""))
    request = UrlRequest(health_url, method="GET")
    with urlopen(request, timeout=0.8) as response:
        if response.status != 200:
            return False
        payload = json.loads(response.read(4096))
    return (isinstance(payload, dict)
            and payload.get("status") == "ok"
            and payload.get("viewer_running") is True)


def utc_now() -> str:

    return datetime.now(timezone.utc).isoformat()





class StrictModel(BaseModel):

    model_config = ConfigDict(extra="forbid")





class RGB(StrictModel):

    r: int = Field(ge=0, le=255)

    g: int = Field(ge=0, le=255)

    b: int = Field(ge=0, le=255)





class GreetingOptions(StrictModel):

    turn_flag: bool = False





class HandshakeOptions(StrictModel):

    # -1 = upstream default: toggle stage; 0 and 1 are explicit stages.

    stage: Literal[-1, 0, 1] = -1





class VolumeOptions(StrictModel):

    # Educational HMI bound, NOT an asserted hardware-side Unitree SDK validation.

    volume: int = Field(ge=0, le=100)





class TTSOptions(StrictModel):

    # Educational cap to keep the public lab bounded; upstream has no such Pydantic model.

    text: str = Field(min_length=1, max_length=200)

    speaker_id: int = Field(default=0, ge=0, le=255)





class TelemetryInjection(StrictModel):

    connected: bool | None = None

    battery_percent: int | None = Field(default=None, ge=0, le=100)

    temperature_c: float | None = Field(default=None, ge=-20, le=100)

    drain_enabled: bool | None = None





class BmsInjection(StrictModel):

    # Selected native HG BmsState_ fields; current/voltage/temp are raw IDL values.

    soc: int | None = Field(default=None, ge=0, le=100)

    soh: int | None = Field(default=None, ge=0, le=100)

    current: int | None = Field(default=None, ge=-2147483648, le=2147483647)





class ImuInjection(StrictModel):

    # In IDL these are arrays of float. rpy, gyro: radians/rad/s; acceleration: m/s².

    rpy: tuple[float, float, float] | None = None

    gyroscope: tuple[float, float, float] | None = None

    accelerometer: tuple[float, float, float] | None = None





class SensorInjection(StrictModel):

    bms_state: BmsInjection | None = None

    imu_state: ImuInjection | None = None





class MediBotStatusUpdate(StrictModel):
    operational_state: str
    mission_name: str | None = None
    current_node: str | None = None
    progress_pct: int = Field(default=0, ge=0, le=100)
    hri_voice: str | None = None
    tamper_alert: bool = False


class NextRpcFailure(StrictModel):

    method: Literal[

        "AudioClient.TtsMaker", "AudioClient.GetVolume", "AudioClient.SetVolume",

        "AudioClient.LedControl", "LocoClient.SetTaskId",

        "G1ArmActionClient.ExecuteAction",

    ]

    # Arbitrary, instructor-supplied synthetic nonzero value, not Unitree errno catalog.

    code: int = Field(ge=-99999, le=99999)





OPERATOR_EVENTS = {

    "led.updated", "audio.volume.read", "audio.volume.changed", "audio.tts.requested",

    "greeting.started", "greeting.finished", "handshake.started", "handshake.finished",

    "high_five.started", "high_five.finished", "arms.release_requested",

    "sdk.rpc.rejected", "visualization.sync_failed", "medibot.status_updated",

}





class Emulator:

    def __init__(self):

        self.lock = asyncio.Lock()

        self.action_task: asyncio.Task | None = None

        self.generation = 0

        self.events: deque[dict] = deque(maxlen=100)

        # Last successful *health probe*, retained across virtual robot resets.
        self.visual_last_success_at: str | None = None

        self._initialize()



    def _initialize(self):

        self.rpc = RpcStub()

        self.audio = AudioClientEmulator(self.rpc)

        self.loco = LocoClientEmulator(self.rpc)

        self.arm = G1ArmActionClientEmulator(self.rpc)

        self.connected = True

        self.mode = "idle"  # HMI façade state, NOT firmware FSM ID

        self.action = None

        self.medibot_status = None

        self.sensors = default_sensors()

        self.sensor_seq = 1

        self.sensor_updated_at = utc_now()

        self.battery_percent = self.sensors["bms_state"]["soc"]

        self.temperature_c = 32.0

        self.drain_enabled = False

        self.sample_seq = 0

        self.event_seq = 0

        self.updated_at = utc_now()

        self._record("reset", {})

        self._sample()



    def _record(self, event: str, details: dict):

        self.event_seq += 1

        self.updated_at = utc_now()

        item = {"seq": self.event_seq, "timestamp": self.updated_at, "event": event,

                "details": details.copy()}

        self.events.append(item)

        return item.copy()



    def _sample(self):

        self.sample_seq += 1

        self.sampled_at = utc_now()

        self.sensors["valid"] = self.connected

        self.last_sample = {

            "type": "telemetry", "robot_id": "g1", "timestamp": self.sampled_at,

            "sample_seq": self.sample_seq, "connected": self.connected,

            "mode": self.mode, "action": self.action,

            "battery_percent": self.battery_percent,

            "temperature_c": self.temperature_c, "led": self.audio.led.copy(),

            "volume": self.audio.volume,

            "last_tts": self.audio.last_tts.copy() if self.audio.last_tts else None,

            "last_task_id": self.loco.last_task_id,

            "last_arm_action_id": self.arm.last_action_id,

            "medibot": self.medibot_status.copy() if self.medibot_status else None,

            "sensors": {**snapshot(self.sensors), "sensor_seq": self.sensor_seq,

                        "sensor_updated_at": self.sensor_updated_at},

        }



    def telemetry(self):

        return deepcopy(self.last_sample)



    def state(self):

        return {

            "id": "g1", "model": "G1", "connected": self.connected,

            "mode": self.mode, "action": self.action, "led": self.audio.led.copy(),

            "audio": {"volume": self.audio.volume,

                      "last_tts": self.audio.last_tts.copy() if self.audio.last_tts else None},

            "loco": {"last_task_id": self.loco.last_task_id},

            "arm": {"last_action_id": self.arm.last_action_id},

            "medibot": self.medibot_status.copy() if self.medibot_status else None,

            "updated_at": self.updated_at,

            "telemetry": {"battery_percent": self.battery_percent,

                          "temperature_c": self.temperature_c,

                          "sample_seq": self.sample_seq, "sampled_at": self.sampled_at,

                          "sensors": {**snapshot(self.sensors), "sensor_seq": self.sensor_seq,

                                      "sensor_updated_at": self.sensor_updated_at}},

        }



    def simulator_state(self):

        return {"robot": self.state(),

                "simulation": {"drain_enabled": self.drain_enabled,

                               "next_rpc_failure": self.rpc.next_failure.copy() if self.rpc.next_failure else None},

                "latest_sample": self.telemetry(), "event_count": self.event_seq,

                "last_rpc": self.rpc.last.as_json() if self.rpc.last else None}



    def _cancel_action(self):

        task = self.action_task

        self.action_task = None

        if task and not task.done():

            task.cancel()



    async def reset(self):

        async with self.lock:

            self._cancel_action()

            self.generation += 1

            self.events.clear()

            self._initialize()

            return self.simulator_state()



    def _require_connected(self):

        if not self.connected:

            raise HTTPException(503, detail="No hay conexión con el G1 virtual")



    def _sdk(self, method: str, sdk_return):

        trace = self.rpc.last

        return {"client": trace.client, "method": method,

                "rpc": trace.as_json(), "sdk_return": sdk_return}



    def _respond(self, method: str, sdk_return, success_event: str, details: dict, *, record_success=True):

        sdk = self._sdk(method, sdk_return)

        ok = sdk["rpc"]["rpc_code"] == 0

        event = self._record(success_event if ok else "sdk.rpc.rejected",

                             {**details, "sdk": sdk}) if (ok or record_success) else None

        if ok:

            self._sample()

        return {"ok": ok, "sdk_equivalent": f"{sdk['client']}.{method}", "sdk": sdk,

                "event": event, "state": self.state()}



    async def led_command(self, rgb: RGB):

        async with self.lock:

            self._require_connected()

            ret = self.audio.LedControl(rgb.r, rgb.g, rgb.b)

            return self._respond("LedControl", ret, "led.updated", {"rgb": rgb.model_dump()})



    async def get_volume(self):

        async with self.lock:

            self._require_connected()

            ret = self.audio.GetVolume()

            result = self._respond("GetVolume", [ret[0], ret[1]], "audio.volume.read", {})

            result["volume"] = ret[1]["volume"] if ret[1] is not None else None

            return result



    async def set_volume(self, value: VolumeOptions):

        async with self.lock:

            self._require_connected()

            ret = self.audio.SetVolume(value.volume)

            return self._respond("SetVolume", ret, "audio.volume.changed", {"volume": value.volume})



    async def tts(self, value: TTSOptions):

        async with self.lock:

            self._require_connected()

            ret = self.audio.TtsMaker(value.text, value.speaker_id)

            return self._respond("TtsMaker", ret, "audio.tts.requested",

                                 {"text": value.text, "speaker_id": value.speaker_id})



    async def gesture(self, name: Literal["greeting", "handshake"], options):

        async with self.lock:

            self._require_connected()

            if self.mode == "busy":

                raise HTTPException(409, detail="G1 virtual ocupado ejecutando un gesto")

            if name == "greeting":

                ret = self.loco.WaveHand(options.turn_flag)

                method = "WaveHand"

            else:

                ret = self.loco.ShakeHand(options.stage)

                method = "ShakeHand"

            sdk = self._sdk(method, ret)

            code = sdk["rpc"]["rpc_code"]

            if code != 0:

                event = self._record("sdk.rpc.rejected", {"gesture": name, "sdk": sdk})

                return {"accepted": False, "sdk_equivalent": f"LocoClient.{method}",

                        "sdk": sdk, "event": event, "state": self.state()}

            # Deliver the visual intention only if the SDK-like RPC was accepted.
            # A failed bridge must not produce a false "greeting.started" state.
            if name == "greeting":
                await send_visual_intent("saludar")

            self.mode = "busy"

            self.action = name

            self.generation += 1

            generation = self.generation

            event = self._record(f"{name}.started", {"sdk": sdk})

            self._sample()

            self.action_task = asyncio.create_task(self._finish_gesture(name, generation))

            return {"accepted": True, "sdk_equivalent": f"LocoClient.{method}",

                    "sdk": sdk, "event": event, "state": self.state()}



    async def arm_action(self, name: Literal["high_five", "release_arms"], action_id: Literal[18, 99]):

        async with self.lock:

            self._require_connected()

            if self.mode == "busy" and not (name == "release_arms" and self.action == "high_five"):

                raise HTTPException(409, detail="G1 virtual ocupado ejecutando un gesto")

            previous_action_id = self.arm.last_action_id
            ret = self.arm.ExecuteAction(action_id)

            sdk = self._sdk("ExecuteAction", ret)

            if sdk["rpc"]["rpc_code"] != 0:

                event = self._record("sdk.rpc.rejected", {"gesture": name, "sdk": sdk})

                return {"accepted": False, "sdk_equivalent": "G1ArmActionClient.ExecuteAction",

                        "sdk": sdk, "event": event, "state": self.state()}

            # The visual bridge is optional. If enabled, deliver only an accepted
            # synthetic SDK action. HTTP 202 means queued, not motion completed.
            # Bridge health /health is deliberately NOT a prerequisite here.
            if MUJOCO_BRIDGE_URL:
                try:
                    await send_visual_intent(name)
                except HTTPException:
                    # Avoid exposing an arm action as accepted when its visual
                    # intention could not be delivered. Preserve the RPC trace.
                    self.arm.last_action_id = previous_action_id
                    raise

            if name == "release_arms":

                # This only cancels the virtual high-five timer. It is NOT a safety

                # command or a physical acknowledgment from a real G1.

                if self.action == "high_five":

                    self._cancel_action()

                    self.generation += 1

                    self.mode = "idle"

                    self.action = None

                event = self._record("arms.release_requested", {"sdk": sdk, "origin": "virtual_command_ack"})

            else:

                self.mode = "busy"

                self.action = name

                self.generation += 1

                generation = self.generation

                event = self._record("high_five.started", {"sdk": sdk})

                self.action_task = asyncio.create_task(self._finish_gesture(name, generation))

            self._sample()

            return {"accepted": True, "sdk_equivalent": "G1ArmActionClient.ExecuteAction",

                    "sdk": sdk, "event": event, "state": self.state()}



    async def _finish_gesture(self, name: str, generation: int):

        try:

            await asyncio.sleep(3)  # purely pedagogical duration, not G1 physical timing

            # For this first visual prototype, show the G1 returning to rest.
            # /intent returns 202 (queued), not a physical movement acknowledgment.
            visual_warning = False
            if name == "greeting" and MUJOCO_BRIDGE_URL:
                async with self.lock:
                    active = (generation == self.generation and self.connected and self.action == name)
                if not active:
                    return
                try:
                    await send_visual_intent("reposo")
                    await asyncio.sleep(2.1)  # viewer's current 2-second interpolation
                except HTTPException:
                    visual_warning = True

            async with self.lock:

                if generation == self.generation and self.connected and self.action == name:

                    if visual_warning:
                        self._record("visualization.sync_failed", {"gesture": name, "intent": "reposo"})

                    self.mode = "idle"

                    self.action = None

                    self._record(f"{name}.finished", {"origin": "virtual_timer_not_hardware_ack"})

                    self._sample()

                    self.action_task = None

        except asyncio.CancelledError:

            return



    async def inject(self, payload: TelemetryInjection):

        changes = payload.model_dump(exclude_none=True)

        if not changes:

            raise HTTPException(422, detail="Indique al menos un valor de simulación")

        async with self.lock:

            if "connected" in changes:

                self.connected = changes["connected"]

                if not self.connected:

                    self._cancel_action()

                    self.generation += 1

                    self.mode = "offline"

                    self.action = None

                elif self.mode == "offline":

                    self.mode = "idle"

            for field in ("battery_percent", "temperature_c", "drain_enabled"):

                if field in changes:

                    setattr(self, field, changes[field])

            if "battery_percent" in changes:

                self.sensors["bms_state"]["soc"] = self.battery_percent

                self.sensor_seq += 1

                self.sensor_updated_at = utc_now()

                self.sensors["source"] = "teacher_injected"

            if self.battery_percent == 0:

                self.drain_enabled = False

            event = self._record("simulation.changed", changes)

            self._sample()

            return {"ok": True, "simulation": self.simulator_state(), "event": event}



    async def inject_sensors(self, payload: SensorInjection):

        changes = payload.model_dump(exclude_none=True)

        if not changes or all(not value for value in changes.values()):

            raise HTTPException(422, detail="Indique al menos un campo de sensor")

        # Validate the whole operation before changing the internal state.

        if "imu_state" in changes:

            for name, values in changes["imu_state"].items():

                if any(not (-1000 <= x <= 1000) for x in values):

                    raise HTTPException(422, detail=f"Valor fuera del límite didáctico: {name}")

        async with self.lock:

            if "bms_state" in changes:

                self.sensors["bms_state"].update(changes["bms_state"])

                self.battery_percent = self.sensors["bms_state"]["soc"]

                if self.battery_percent == 0: self.drain_enabled = False

            if "imu_state" in changes:

                imu = self.sensors["low_state"]["imu_state"]

                imu.update({k:list(v) for k,v in changes["imu_state"].items()})

                if "rpy" in changes["imu_state"]:

                    imu["quaternion"] = quaternion_from_rpy(imu["rpy"])

            self.sensor_seq += 1

            self.sensor_updated_at = utc_now()

            self.sensors["source"] = "teacher_injected"

            event = self._record("simulation.sensors.changed", changes)

            self._sample()

            return {"ok": True, "simulation": self.simulator_state(), "event": event}



    async def arm_rpc_failure(self, payload: NextRpcFailure):

        if payload.code == 0:

            raise HTTPException(422, detail="El código inyectado debe ser distinto de cero")

        async with self.lock:

            self.rpc.arm_failure(payload.method, payload.code)

            event = self._record("simulation.rpc_failure_armed", self.rpc.next_failure)

            return {"ok": True, "simulation": self.simulator_state(), "event": event}



    async def ticker(self):

        while True:

            await asyncio.sleep(1)

            async with self.lock:

                if self.connected and self.drain_enabled and self.battery_percent > 0:

                    self.battery_percent -= 1

                    self.sensors["bms_state"]["soc"] = self.battery_percent

                    self.sensor_seq += 1

                    self.sensor_updated_at = utc_now()

                    self.sensors["source"] = "synthetic_drain"

                    if self.battery_percent == 0:

                        self.drain_enabled = False

                        self._record("battery.empty", {})

                self._sample()



    async def shutdown(self):

        async with self.lock:

            self._cancel_action()





@asynccontextmanager

async def lifespan(app: FastAPI):

    emulator = Emulator()

    app.state.emulator = emulator

    ticker = asyncio.create_task(emulator.ticker())

    try:

        yield

    finally:

        ticker.cancel()

        await asyncio.gather(ticker, return_exceptions=True)

        await emulator.shutdown()





app = FastAPI(

    title="Unitree G1 HMI Lab", version="0.7.0", lifespan=lifespan,

    description=("Fachada didáctica REST/WebSocket para G1 con adaptadores de firmas "

                 "SDK2 Python seleccionadas. No implementa DDS ni simulación física."),

)

# Allow CORS by default so web clients and mobile apps (MediBot) can connect seamlessly
allowed_origins = [v.strip() for v in os.getenv("HMI_CORS_ORIGINS", "*").split(",") if v.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in allowed_origins else allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False
)

app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")





def emulator_from_request(request: Request) -> Emulator:

    return request.app.state.emulator





def instructor_auth(x_simulator_token: str | None = Header(default=None, alias="X-Simulator-Token")):

    configured = os.getenv("SIMULATOR_TOKEN", "")

    if configured and (x_simulator_token is None or not compare_digest(configured, x_simulator_token)):

        raise HTTPException(401, detail="Se requiere X-Simulator-Token válido")





@app.get("/", include_in_schema=False)

async def hmi_page():

    return FileResponse(ROOT / "web" / "hmi.html")





@app.get("/simulator", include_in_schema=False)

async def simulator_page():

    return FileResponse(ROOT / "web" / "simulator.html")





@app.get("/api/robots", tags=["HMI | G1"])

async def list_robots(emu: Emulator = Depends(emulator_from_request)):

    async with emu.lock:

        return [emu.state()]





@app.get("/api/robots/g1/state", tags=["HMI | G1"])

async def robot_state(emu: Emulator = Depends(emulator_from_request)):

    async with emu.lock:

        return emu.state()





@app.get("/api/robots/g1/telemetry", tags=["HMI | G1"])

async def telemetry(emu: Emulator = Depends(emulator_from_request)):

    async with emu.lock:

        return emu.telemetry()





@app.get("/api/robots/g1/events", tags=["HMI | G1"])

async def operator_events(emu: Emulator = Depends(emulator_from_request)):

    async with emu.lock:

        return [item.copy() for item in emu.events if item["event"] in OPERATOR_EVENTS]





@app.put("/api/robots/g1/led", tags=["HMI | G1"])

async def set_led(rgb: RGB, emu: Emulator = Depends(emulator_from_request)):

    return await emu.led_command(rgb)





@app.get("/api/robots/g1/audio/volume", tags=["HMI | G1"])

async def get_volume(emu: Emulator = Depends(emulator_from_request)):

    return await emu.get_volume()





@app.put("/api/robots/g1/audio/volume", tags=["HMI | G1"])

async def set_volume(value: VolumeOptions, emu: Emulator = Depends(emulator_from_request)):

    return await emu.set_volume(value)





@app.post("/api/robots/g1/audio/tts", tags=["HMI | G1"])

async def tts(value: TTSOptions, emu: Emulator = Depends(emulator_from_request)):

    return await emu.tts(value)





@app.post("/api/robots/g1/commands/greeting", status_code=202, tags=["HMI | G1"])

async def greeting(options: GreetingOptions | None = None, emu: Emulator = Depends(emulator_from_request)):

    return await emu.gesture("greeting", options or GreetingOptions())





@app.post("/api/robots/g1/commands/handshake", status_code=202, tags=["HMI | G1"])

async def handshake(options: HandshakeOptions | None = None, emu: Emulator = Depends(emulator_from_request)):

    return await emu.gesture("handshake", options or HandshakeOptions())





@app.post("/api/robots/g1/commands/high-five", status_code=202, tags=["HMI | G1"])

async def high_five(emu: Emulator = Depends(emulator_from_request)):

    return await emu.arm_action("high_five", 18)





@app.post("/api/robots/g1/commands/release-arms", status_code=202, tags=["HMI | G1"])

async def release_arms(emu: Emulator = Depends(emulator_from_request)):

    return await emu.arm_action("release_arms", 99)


@app.post("/api/robots/g1/medibot/status", tags=["MediBot Integration"])
async def update_medibot_status(payload: MediBotStatusUpdate, emu: Emulator = Depends(emulator_from_request)):
    async with emu.lock:
        emu.medibot_status = payload.model_dump()
        emu._record("medibot.status_updated", emu.medibot_status)
        emu._sample()
        return {"ok": True, "medibot": emu.medibot_status}


@app.get("/api/robots/g1/medibot/status", tags=["MediBot Integration"])
async def get_medibot_status(emu: Emulator = Depends(emulator_from_request)):
    async with emu.lock:
        return {"ok": True, "medibot": emu.medibot_status}






@app.websocket("/ws/robots/g1/telemetry")

async def telemetry_ws(ws: WebSocket):

    await ws.accept()

    emu: Emulator = ws.app.state.emulator

    try:

        while True:

            async with emu.lock:

                message = emu.telemetry()

            await ws.send_json(message)

            await asyncio.sleep(1)

    except (WebSocketDisconnect, OSError, RuntimeError):

        pass

    except asyncio.CancelledError:

        raise





@app.get("/api/simulator/g1/state", tags=["Docente | Simulación"], dependencies=[Depends(instructor_auth)])

async def simulator_state(emu: Emulator = Depends(emulator_from_request)):

    async with emu.lock:

        return emu.simulator_state()





@app.get("/api/simulator/g1/visualization/status", tags=["Docente | Visualización"],
         dependencies=[Depends(instructor_auth)])
async def visualization_status(emu: Emulator = Depends(emulator_from_request)):
    """Status of the OPTIONAL local viewer bridge; not a G1 SDK/sensor field."""
    configured = bool(MUJOCO_BRIDGE_URL)
    connected = False
    if configured:
        try:
            connected = await asyncio.to_thread(_check_visual_bridge_health)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError):
            connected = False

    checked_at = utc_now()
    async with emu.lock:
        if connected:
            emu.visual_last_success_at = checked_at
        last_successful_check_at = emu.visual_last_success_at

    return {
        "configured": configured,
        "connected": connected,
        "status": "not_configured" if not configured else ("connected" if connected else "disconnected"),
        "viewer_running": connected,
        "checked_at": checked_at,
        "last_successful_check_at": last_successful_check_at,
    }


@app.get("/api/simulator/g1/events", tags=["Docente | Simulación"], dependencies=[Depends(instructor_auth)])

async def simulator_events(emu: Emulator = Depends(emulator_from_request)):

    async with emu.lock:

        return [item.copy() for item in emu.events]





@app.patch("/api/simulator/g1/telemetry", tags=["Docente | Simulación"], dependencies=[Depends(instructor_auth)])

async def inject_telemetry(payload: TelemetryInjection, emu: Emulator = Depends(emulator_from_request)):

    return await emu.inject(payload)





@app.patch("/api/simulator/g1/sensors", tags=["Docente | Sensores"], dependencies=[Depends(instructor_auth)])

async def inject_sensor_values(payload: SensorInjection, emu: Emulator = Depends(emulator_from_request)):

    return await emu.inject_sensors(payload)





@app.get("/api/robots/g1/sensors", tags=["HMI | G1"])

async def sensor_values(emu: Emulator = Depends(emulator_from_request)):

    async with emu.lock:

        return deepcopy(emu.telemetry()["sensors"])





@app.post("/api/simulator/g1/next-rpc-failure", tags=["Docente | Simulación"], dependencies=[Depends(instructor_auth)])

async def next_rpc_failure(payload: NextRpcFailure, emu: Emulator = Depends(emulator_from_request)):

    return await emu.arm_rpc_failure(payload)





@app.post("/api/simulator/g1/reset", tags=["Docente | Simulación"], dependencies=[Depends(instructor_auth)])

async def simulator_reset(emu: Emulator = Depends(emulator_from_request)):

    return {"ok": True, "simulation": await emu.reset()}
