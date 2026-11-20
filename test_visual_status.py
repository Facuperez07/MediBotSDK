"""Bridge health is independent of synthetic SDK and teacher-only."""
import json
import main
from fastapi.testclient import TestClient

URL = "/api/simulator/g1/visualization/status"


def test_health_not_configured_skips_probe(monkeypatch):
    monkeypatch.delenv("SIMULATOR_TOKEN", raising=False)
    monkeypatch.setattr(main, "MUJOCO_BRIDGE_URL", "")
    monkeypatch.setattr(main, "_check_visual_bridge_health", lambda: (_ for _ in ()).throw(AssertionError("must not probe")))
    with TestClient(main.app) as client:
        body = client.get(URL).json()
        assert body["status"] == "not_configured"
        assert body["connected"] is False
        assert body["viewer_running"] is False
        assert body["last_successful_check_at"] is None


def test_health_connected_then_disconnected_retains_last_success(monkeypatch):
    monkeypatch.delenv("SIMULATOR_TOKEN", raising=False)
    monkeypatch.setattr(main, "MUJOCO_BRIDGE_URL", "http://127.0.0.1:8765/intent")
    monkeypatch.setattr(main, "_check_visual_bridge_health", lambda: True)
    with TestClient(main.app) as client:
        first = client.get(URL).json()
        assert first["status"] == "connected" and first["viewer_running"] is True
        assert first["last_successful_check_at"] is not None
        # Virtual-robot reset must not erase the bridge's observed history.
        assert client.post("/api/simulator/g1/reset").status_code == 200
        monkeypatch.setattr(main, "_check_visual_bridge_health", lambda: False)
        second = client.get(URL).json()
        assert second["status"] == "disconnected"
        assert second["last_successful_check_at"] == first["last_successful_check_at"]
        # Status does not contaminate public G1 telemetry / SDK states.
        t = client.get("/api/robots/g1/telemetry").json()
        assert "visualization" not in t and "viewer_running" not in t


def test_health_requires_teacher_token(monkeypatch):
    monkeypatch.setenv("SIMULATOR_TOKEN", "secreto")
    monkeypatch.setattr(main, "MUJOCO_BRIDGE_URL", "http://127.0.0.1:8765/intent")
    monkeypatch.setattr(main, "_check_visual_bridge_health", lambda: True)
    with TestClient(main.app) as client:
        assert client.get(URL).status_code == 401
        assert client.get(URL, headers={"X-Simulator-Token": "mala"}).status_code == 401
        assert client.get(URL, headers={"X-Simulator-Token": "secreto"}).json()["status"] == "connected"


def test_health_bad_response_is_disconnected(monkeypatch):
    monkeypatch.delenv("SIMULATOR_TOKEN", raising=False)
    monkeypatch.setattr(main, "MUJOCO_BRIDGE_URL", "http://127.0.0.1:8765/intent")
    monkeypatch.setattr(main, "_check_visual_bridge_health", lambda: (_ for _ in ()).throw(ValueError("bad json")))
    with TestClient(main.app) as client:
        assert client.get(URL).json()["status"] == "disconnected"


def test_health_parser_requires_active_viewer(monkeypatch):
    monkeypatch.setattr(main, "MUJOCO_BRIDGE_URL", "http://127.0.0.1:8765/intent")
    calls=[]
    class Response:
        status=200
        def __init__(self, viewer_running): self.viewer_running=viewer_running
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps({"status":"ok", "viewer_running":self.viewer_running}).encode()
    monkeypatch.setattr(main, "urlopen", lambda req, timeout: (calls.append((req.full_url, timeout)) or Response(False)))
    assert main._check_visual_bridge_health() is False
    assert calls == [("http://127.0.0.1:8765/health", 0.8)]
    monkeypatch.setattr(main, "urlopen", lambda req, timeout: Response(True))
    assert main._check_visual_bridge_health() is True


def test_teacher_panel_embeds_status_and_student_hmi_keeps_separation(monkeypatch):
    monkeypatch.delenv("SIMULATOR_TOKEN", raising=False)
    monkeypatch.setattr(main, "MUJOCO_BRIDGE_URL", "")
    with TestClient(main.app) as client:
        teacher = client.get('/simulator').text
        teacher_js = client.get('/static/simulator.js').text
        teacher_css = client.get('/static/styles.css').text
        student = client.get('/').text
        student_js = client.get('/static/hmi.js').text
        assert 'id="visual-indicator"' in teacher
        assert 'id="visual-last"' in teacher
        assert 'visualization/status' in teacher_js
        assert "setInterval(refreshVisualStatus,5000)" in teacher_js
        assert "headers()" in teacher_js  # reuses the teacher token already in the page
        assert '.teacher .visual-chip' in teacher_css
        assert 'visual-indicator' not in student
        assert '/api/simulator/' not in student_js
