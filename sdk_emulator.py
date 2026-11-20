"""Small in-process adapters mirroring selected public G1 SDK2 Python method signatures.

Not a Unitree SDK, DDS endpoint, robot controller, or physics simulator. The
RPC stub returns synthetic codes; SDK method return semantics are preserved
where observable from the reviewed source revision (see SDK_CONTRACTS.md).
Only call these objects under the owning Emulator's asyncio lock.
"""
from dataclasses import dataclass
from typing import Any

AUDIO_API = {"TtsMaker": 1001, "GetVolume": 1005, "SetVolume": 1006, "LedControl": 1010}
LOCO_API = {"SetTaskId": 7106}
ARM_ACTION_API = {"ExecuteAction": 7106}
# Official G1 arm action_map subset, not a claim that any particular firmware supports it.
ARM_ACTIONS = {"high five": 18, "release arm": 99}
FAULTABLE = {
    "AudioClient.TtsMaker": 1001,
    "AudioClient.GetVolume": 1005,
    "AudioClient.SetVolume": 1006,
    "AudioClient.LedControl": 1010,
    "LocoClient.SetTaskId": 7106,
    "G1ArmActionClient.ExecuteAction": 7106,
}


@dataclass
class RpcTrace:
    client: str
    service: str
    method: str
    api_id: int
    parameters: dict[str, Any]
    code: int

    def as_json(self):
        return {"client": self.client, "service": self.service, "method": self.method, "api_id": self.api_id,
                "parameters": self.parameters.copy(), "rpc_code": self.code,
                "origin": "synthetic_rpc_stub"}


class RpcStub:
    def __init__(self):
        self.next_failure: dict[str, Any] | None = None
        self.last: RpcTrace | None = None

    def call(self, service: str, method: str, api_id: int, parameters: dict) -> int:
        key = f"{service}.{method}"
        code = 0
        if self.next_failure and self.next_failure["method"] == key:
            code = self.next_failure["code"]
            self.next_failure = None
        self.last = RpcTrace(service, {"AudioClient": "voice", "LocoClient": "sport", "G1ArmActionClient": "arm"}[service], method, api_id, parameters.copy(), code)
        return code

    def arm_failure(self, method: str, code: int):
        if method not in FAULTABLE or code == 0:
            raise ValueError("Invalid injected RPC failure")
        self.next_failure = {"method": method, "code": code}


class AudioClientEmulator:
    def __init__(self, rpc: RpcStub):
        self.rpc = rpc
        self.volume = 50
        self.led = {"r": 0, "g": 0, "b": 0}
        self.last_tts: dict | None = None
        # In the reviewed upstream Python source this starts at zero and the
        # expression `self.tts_index += self.tts_index` leaves it at zero.
        self.tts_index = 0

    def GetVolume(self):
        code = self.rpc.call("AudioClient", "GetVolume", 1005, {})
        return (code, {"volume": self.volume} if code == 0 else None)

    def SetVolume(self, volume: int):
        code = self.rpc.call("AudioClient", "SetVolume", 1006, {"volume": volume})
        if code == 0:
            self.volume = volume
        return code

    def LedControl(self, R: int, G: int, B: int):
        code = self.rpc.call("AudioClient", "LedControl", 1010, {"R": R, "G": G, "B": B})
        if code == 0:
            self.led = {"r": R, "g": G, "b": B}
        return code

    def TtsMaker(self, text: str, speaker_id: int):
        self.tts_index += self.tts_index  # upstream Python snapshot behavior; see contracts
        p = {"index": self.tts_index, "text": text, "speaker_id": speaker_id}
        code = self.rpc.call("AudioClient", "TtsMaker", 1001, p)
        if code == 0:
            self.last_tts = {"text": text, "speaker_id": speaker_id, "index": self.tts_index}
        return code


class LocoClientEmulator:
    def __init__(self, rpc: RpcStub):
        self.rpc = rpc
        self.first_shake_hand_stage_ = -1
        self.last_task_id: int | None = None

    def SetTaskId(self, task_id: float):
        code = self.rpc.call("LocoClient", "SetTaskId", 7106, {"data": task_id})
        if code == 0:
            self.last_task_id = task_id
        return code

    def WaveHand(self, turn_flag: bool = False):
        self.SetTaskId(1 if turn_flag else 0)
        # SDK Python wrapper does not return SetTaskId's code.

    def ShakeHand(self, stage: int = -1):
        if stage == 0:
            self.first_shake_hand_stage_ = False
            self.SetTaskId(2)
        elif stage == 1:
            self.first_shake_hand_stage_ = True
            self.SetTaskId(3)
        else:
            self.first_shake_hand_stage_ = not self.first_shake_hand_stage_
            return self.SetTaskId(3 if self.first_shake_hand_stage_ else 2)


class G1ArmActionClientEmulator:
    """Subset of the official ExecuteAction(action_id: int) wrapper.

    IDs 18 (high five) and 99 (release arm) come from upstream action_map.
    Availability on a physical robot is firmware/service dependent.
    """
    def __init__(self, rpc: RpcStub):
        self.rpc = rpc
        self.last_action_id: int | None = None

    def ExecuteAction(self, action_id: int):
        code = self.rpc.call("G1ArmActionClient", "ExecuteAction", 7106, {"data": action_id})
        if code == 0:
            self.last_action_id = action_id
        return code
