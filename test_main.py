"""End-to-end checks for operator/teacher separation and selected G1 SDK2 adapter semantics."""
import time

import pytest
from fastapi.testclient import TestClient

from main import app
from sdk_emulator import AudioClientEmulator, LocoClientEmulator, G1ArmActionClientEmulator, RpcStub


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('SIMULATOR_TOKEN', raising=False)
    with TestClient(app) as c:
        yield c


def test_pages_and_public_surface_separated(client):
    assert 'Panel de operación' in client.get('/').text
    assert 'Consola de simulación' in client.get('/simulator').text
    hmi_js = client.get('/static/hmi.js').text
    teacher_js = client.get('/static/simulator.js').text
    assert '/api/simulator/' not in hmi_js
    assert '/api/simulator/g1/next-rpc-failure' in teacher_js
    assert 'Go'+'2' not in client.get('/').text
    assert client.get('/docs').status_code == 200
    assert len(client.get('/api/robots').json()) == 1
    assert client.get('/api/robots/unknown/state').status_code == 404
    assert client.patch('/api/robots/g1/simulation', json={'battery_percent': 2}).status_code == 404
    assert client.post('/api/reset').status_code == 404


def test_original_led_and_greeting_endpoints(client):
    led = client.put('/api/robots/g1/led', json={'r': 12, 'g': 34, 'b': 56})
    assert led.status_code == 200 and led.json()['ok']
    assert led.json()['sdk']['rpc']['api_id'] == 1010
    assert led.json()['sdk']['rpc']['service'] == 'voice'
    assert led.json()['sdk']['rpc']['parameters'] == {'R': 12, 'G': 34, 'B': 56}
    assert client.get('/api/robots/g1/telemetry').json()['led'] == {'r': 12, 'g': 34, 'b': 56}
    assert client.put('/api/robots/g1/led', json={'r': 256, 'g': 0, 'b': 0}).status_code == 422
    greet = client.post('/api/robots/g1/commands/greeting', json={'turn_flag': True})
    assert greet.status_code == 202 and greet.json()['accepted']
    assert greet.json()['sdk']['rpc']['parameters'] == {'data': 1}
    assert greet.json()['sdk']['rpc']['api_id'] == 7106
    assert greet.json()['sdk']['rpc']['service'] == 'sport'
    assert greet.json()['sdk']['sdk_return'] is None  # upstream WaveHand wrapper discards SetTaskId return
    assert client.post('/api/robots/g1/commands/greeting', json={}).status_code == 409
    assert client.get('/api/robots/g1/telemetry').json()['last_task_id'] == 1


def test_audio_volume_sdk_returns_and_state(client):
    g = client.get('/api/robots/g1/audio/volume')
    assert g.status_code == 200 and g.json()['volume'] == 50
    assert g.json()['sdk']['sdk_return'] == [0, {'volume': 50}]
    assert g.json()['sdk']['rpc']['api_id'] == 1005
    s = client.put('/api/robots/g1/audio/volume', json={'volume': 77})
    assert s.status_code == 200 and s.json()['ok']
    assert s.json()['sdk']['sdk_return'] == 0
    assert s.json()['sdk']['rpc']['parameters'] == {'volume': 77}
    assert s.json()['sdk']['rpc']['api_id'] == 1006
    assert client.get('/api/robots/g1/telemetry').json()['volume'] == 77
    for v in (-1,101,'illegal'):
        assert client.put('/api/robots/g1/audio/volume', json={'volume': v}).status_code == 422


def test_tts_contract_and_validation(client):
    t = client.post('/api/robots/g1/audio/tts', json={'text': 'Hola, estudiantes', 'speaker_id': 0})
    assert t.status_code == 200 and t.json()['ok']
    assert t.json()['sdk']['rpc']['api_id'] == 1001
    assert t.json()['sdk']['rpc']['parameters'] == {'index': 0, 'text': 'Hola, estudiantes', 'speaker_id': 0}
    assert t.json()['sdk']['sdk_return'] == 0
    assert client.get('/api/robots/g1/telemetry').json()['last_tts']['text'] == 'Hola, estudiantes'
    for text in ('', 'x'*201):
        assert client.post('/api/robots/g1/audio/tts', json={'text': text, 'speaker_id':0}).status_code == 422
    assert client.post('/api/robots/g1/audio/tts', json={'text':'Hola', 'speaker_id':256}).status_code == 422
    assert client.post('/api/robots/g1/audio/tts', json={'text':'Hola','unknown':1}).status_code == 422


def test_shakehand_stage_semantics_with_adapter():
    rpc=RpcStub(); loco=LocoClientEmulator(rpc)
    assert loco.ShakeHand() == 0 and loco.last_task_id == 2
    assert loco.ShakeHand() == 0 and loco.last_task_id == 3
    assert loco.ShakeHand(0) is None and loco.last_task_id == 2
    assert loco.ShakeHand(1) is None and loco.last_task_id == 3
    assert loco.WaveHand() is None and loco.last_task_id == 0
    assert loco.WaveHand(True) is None and loco.last_task_id == 1
    assert rpc.last.api_id == 7106 and rpc.last.parameters == {'data': 1}


def test_shakehand_http(client):
    one=client.post('/api/robots/g1/commands/handshake', json={})
    assert one.status_code == 202 and one.json()['accepted']
    assert one.json()['sdk']['sdk_return'] == 0
    assert one.json()['sdk']['rpc']['parameters'] == {'data': 2}
    assert client.post('/api/robots/g1/commands/handshake', json={'stage':1}).status_code == 409
    assert client.post('/api/simulator/g1/reset').status_code == 200
    explicit=client.post('/api/robots/g1/commands/handshake', json={'stage':1})
    assert explicit.json()['sdk']['sdk_return'] is None
    assert explicit.json()['sdk']['rpc']['parameters'] == {'data':3}
    assert client.post('/api/robots/g1/commands/handshake', json={'stage':2}).status_code == 422


def test_teacher_injection_and_reconnection(client):
    response=client.patch('/api/simulator/g1/telemetry',json={'battery_percent':12,'temperature_c':45.5,'connected':True})
    assert response.status_code==200
    t=client.get('/api/robots/g1/telemetry').json()
    assert t['battery_percent']==12 and t['temperature_c']==45.5
    assert client.get('/api/robots/g1/events').json()==[]
    assert client.patch('/api/simulator/g1/telemetry',json={'unknown':1}).status_code==422
    client.patch('/api/simulator/g1/telemetry',json={'connected':False})
    assert client.get('/api/robots/g1/telemetry').json()['mode']=='offline'
    for url, method, payload in [('/api/robots/g1/audio/tts','post',{'text':'hola'}),('/api/robots/g1/audio/volume','get',None),('/api/robots/g1/commands/handshake','post',{})]:
        assert getattr(client,method)(url,**({'json':payload} if payload is not None else {})).status_code==503
    client.patch('/api/simulator/g1/telemetry',json={'connected':True})
    assert client.get('/api/robots/g1/telemetry').json()['mode']=='idle'


def test_teacher_token_covers_new_fault_endpoint(monkeypatch,client):
    monkeypatch.setenv('SIMULATOR_TOKEN','secret-teacher')
    root='/api/simulator/g1'
    for path in ('state','events'):
        assert client.get(f'{root}/{path}').status_code==401
    assert client.post(f'{root}/next-rpc-failure',json={'method':'AudioClient.SetVolume','code':-42}).status_code==401
    assert client.patch(f'{root}/telemetry',json={'battery_percent':1}).status_code==401
    assert client.post(f'{root}/reset').status_code==401
    headers={'X-Simulator-Token':'secret-teacher'}
    assert client.post(f'{root}/next-rpc-failure',json={'method':'AudioClient.SetVolume','code':-42},headers=headers).status_code==200
    assert client.get(f'{root}/state',headers=headers).json()['simulation']['next_rpc_failure']['code']==-42
    assert client.post(f'{root}/reset',headers=headers).status_code==200


def test_teacher_rpc_one_shot_no_state_mutation_and_no_false_unitree_error_mapping(client):
    path='/api/simulator/g1/next-rpc-failure'
    assert client.post(path,json={'method':'AudioClient.SetVolume','code':0}).status_code==422
    assert client.post(path,json={'method':'AudioClient.SetVolume','code':-42}).status_code==200
    # An unrelated API request must not consume the fault.
    assert client.get('/api/robots/g1/audio/volume').json()['sdk']['rpc']['rpc_code']==0
    failed=client.put('/api/robots/g1/audio/volume',json={'volume':23}).json()
    assert not failed['ok'] and failed['sdk']['rpc']['rpc_code']==-42
    assert failed['sdk']['sdk_return']==-42
    assert client.get('/api/robots/g1/telemetry').json()['volume']==50
    assert client.put('/api/robots/g1/audio/volume',json={'volume':23}).json()['ok']
    assert client.get('/api/robots/g1/telemetry').json()['volume']==23
    assert client.get('/api/simulator/g1/state').json()['simulation']['next_rpc_failure'] is None


def test_failed_gesture_retains_python_wrapper_return_and_no_busy(client):
    client.post('/api/simulator/g1/next-rpc-failure',json={'method':'LocoClient.SetTaskId','code':-123})
    r=client.post('/api/robots/g1/commands/greeting',json={})
    assert r.status_code==202 and r.json()['accepted'] is False
    assert r.json()['sdk']['rpc']['rpc_code']==-123
    assert r.json()['sdk']['sdk_return'] is None
    assert client.get('/api/robots/g1/state').json()['mode']=='idle'
    assert client.get('/api/robots/g1/state').json()['loco']['last_task_id'] is None
    assert client.post('/api/robots/g1/commands/greeting',json={}).json()['accepted']


def test_failed_getvolume_semantic_tuple(client):
    client.post('/api/simulator/g1/next-rpc-failure',json={'method':'AudioClient.GetVolume','code':-5})
    data=client.get('/api/robots/g1/audio/volume').json()
    assert data['ok'] is False and data['volume'] is None
    assert data['sdk']['sdk_return']==[-5,None]


def test_canonical_sample_ws_rest_and_reset(client):
    initial=client.get('/api/robots/g1/telemetry').json()
    assert client.get('/api/robots/g1/telemetry').json()['sample_seq']==initial['sample_seq']
    with client.websocket_connect('/ws/robots/g1/telemetry') as a:
        first=a.receive_json()
        with client.websocket_connect('/ws/robots/g1/telemetry') as b:
            second=b.receive_json()
            assert first['sample_seq']==second['sample_seq']
            changed=client.put('/api/robots/g1/audio/volume',json={'volume':14}).json()['state']['telemetry']['sample_seq']
            assert client.get('/api/robots/g1/telemetry').json()['sample_seq']==changed
            for ws in (a,b):
                until=time.monotonic()+4
                while True:
                    received=ws.receive_json()
                    if received['sample_seq']>=changed:
                        assert received['volume']==14
                        break
                    assert time.monotonic()<until
    client.post('/api/simulator/g1/reset')
    t=client.get('/api/robots/g1/telemetry').json()
    assert t['volume']==50 and t['led']=={'r':0,'g':0,'b':0} and t['last_tts'] is None


def test_global_drain(client):
    client.patch('/api/simulator/g1/telemetry',json={'battery_percent':4,'drain_enabled':True})
    before=client.get('/api/robots/g1/telemetry').json()
    time.sleep(1.25)
    after=client.get('/api/robots/g1/telemetry').json()
    assert after['sample_seq']>before['sample_seq']
    assert 0<before['battery_percent']-after['battery_percent']<=2


def test_gesture_finishes_without_hmi_polling(client):
    assert client.post('/api/robots/g1/commands/handshake',json={'stage':0}).json()['accepted']
    time.sleep(3.2)
    state=client.get('/api/robots/g1/state').json()
    assert state['mode']=='idle' and state['action'] is None
    names=[e['event'] for e in client.get('/api/robots/g1/events').json()]
    assert names==['handshake.started','handshake.finished']

# v0.6 physical-sensor-shaped messages: exact selected names/shapes, not DDS.
def test_sensor_contract_defaults_are_hg_and_copy_isolation(client):
    t=client.get('/api/robots/g1/telemetry').json()
    ss=client.get('/api/robots/g1/sensors').json()
    assert t['sensors']==ss
    assert ss['source']=='synthetic_default'
    assert ss['bms_state']['soc']==t['battery_percent']==85
    assert 'motor_state' not in ss['low_state']
    assert 'profile' not in ss
    assert ss['low_state']['imu_state']['rpy']==[0,0,0]
    ss['low_state']['imu_state']['rpy'][0]=200
    assert client.get('/api/robots/g1/sensors').json()['low_state']['imu_state']['rpy'][0]==0


def test_teacher_injects_imu_and_hmi_observes_same_values(client):
    import math
    before=client.get('/api/robots/g1/sensors').json()['sensor_seq']
    inp={'imu_state':{'rpy':[0.3,-0.2,1.0],'gyroscope':[0.1,0.2,0.3],
                      'accelerometer':[0,0,9.81]}}
    r=client.patch('/api/simulator/g1/sensors',json=inp)
    assert r.status_code==200
    sensors=client.get('/api/robots/g1/sensors').json()
    assert sensors['sensor_seq']==before+1
    imu=sensors['low_state']['imu_state']
    assert imu['rpy']==inp['imu_state']['rpy']
    assert imu['gyroscope']==inp['imu_state']['gyroscope']
    assert math.isclose(sum(x*x for x in imu['quaternion']),1,abs_tol=1e-8)
    assert client.get('/api/robots/g1/telemetry').json()['sensors']==sensors


def test_sensor_bms_link_legacy_drain_and_reset(client):
    assert client.patch('/api/simulator/g1/sensors',json={'bms_state':{'soc':12,'soh':88,'current':-123}}).status_code==200
    t=client.get('/api/robots/g1/telemetry').json()
    assert t['battery_percent']==t['sensors']['bms_state']['soc']==12
    assert t['sensors']['bms_state']['soh']==88
    client.patch('/api/simulator/g1/telemetry',json={'battery_percent':9})
    assert client.get('/api/robots/g1/sensors').json()['bms_state']['soc']==9
    client.patch('/api/simulator/g1/telemetry',json={'drain_enabled':True})
    time.sleep(1.2)
    t=client.get('/api/robots/g1/telemetry').json()
    assert t['battery_percent']==t['sensors']['bms_state']['soc']
    client.post('/api/simulator/g1/reset')
    assert client.get('/api/robots/g1/sensors').json()['bms_state']['soc']==85


def test_joint_telemetry_no_longer_exposed_or_injectable(client):
    path='/api/simulator/g1/sensors'
    assert client.patch(path,json={'motor_state':{'index':3,'q':1.25}}).status_code==422
    sensor=client.get('/api/robots/g1/sensors').json()
    assert 'motor_state' not in sensor['low_state']
    assert 'profile' not in sensor
    assert 'Articulación seleccionada' not in client.get('/simulator').text
    assert 'Estados articulares' not in client.get('/').text
    assert 'motor-select' not in client.get('/static/hmi.js').text
    assert 'motor-apply' not in client.get('/static/simulator.js').text


def test_arm_action_sdk_signature_service_and_trace():
    rpc=RpcStub(); arm=G1ArmActionClientEmulator(rpc)
    assert arm.ExecuteAction(18)==0
    assert arm.last_action_id==18
    assert rpc.last.client=='G1ArmActionClient'
    assert rpc.last.service=='arm'
    assert rpc.last.api_id==7106
    assert rpc.last.parameters=={'data':18}
    assert arm.ExecuteAction(99)==0
    assert arm.last_action_id==99


def test_high_five_and_release_are_explicit_operator_commands(client):
    path='/api/robots/g1/commands/'
    high=client.post(path+'high-five')
    assert high.status_code==202 and high.json()['accepted']
    sdk=high.json()['sdk']
    assert sdk['sdk_return']==0
    assert sdk['rpc']['service']=='arm' and sdk['rpc']['api_id']==7106
    assert sdk['rpc']['parameters']=={'data':18}
    assert client.get('/api/robots/g1/telemetry').json()['last_arm_action_id']==18
    assert client.get('/api/robots/g1/telemetry').json()['action']=='high_five'
    assert client.post(path+'high-five').status_code==409
    release=client.post(path+'release-arms')
    assert release.status_code==202 and release.json()['accepted']
    assert release.json()['sdk']['rpc']['parameters']=={'data':99}
    t=client.get('/api/robots/g1/telemetry').json()
    assert t['last_arm_action_id']==99 and t['action'] is None and t['mode']=='idle'
    events=[e['event'] for e in client.get('/api/robots/g1/events').json()]
    assert events==['high_five.started','arms.release_requested']


def test_high_five_fault_one_shot_and_no_false_action(client):
    f=client.post('/api/simulator/g1/next-rpc-failure',json={
        'method':'G1ArmActionClient.ExecuteAction','code':-42})
    assert f.status_code==200
    r=client.post('/api/robots/g1/commands/high-five')
    assert r.status_code==202 and not r.json()['accepted']
    assert r.json()['sdk']['sdk_return']==-42
    assert r.json()['sdk']['rpc']['service']=='arm'
    t=client.get('/api/robots/g1/telemetry').json()
    assert t['mode']=='idle' and t['last_arm_action_id'] is None
    assert client.post('/api/robots/g1/commands/high-five').json()['accepted']


def test_high_five_timer_and_offline_rejection(client):
    client.patch('/api/simulator/g1/telemetry',json={'connected':False})
    for endpoint in ('high-five','release-arms'):
        assert client.post('/api/robots/g1/commands/'+endpoint).status_code==503
    client.patch('/api/simulator/g1/telemetry',json={'connected':True})
    assert client.post('/api/robots/g1/commands/high-five').json()['accepted']
    time.sleep(3.2)
    t=client.get('/api/robots/g1/telemetry').json()
    assert t['mode']=='idle' and t['action'] is None and t['last_arm_action_id']==18
    events=[e['event'] for e in client.get('/api/robots/g1/events').json()]
    assert events==['high_five.started','high_five.finished']


def test_sensor_visibility_offline_and_teacher_auth(client,monkeypatch):
    monkeypatch.setenv('SIMULATOR_TOKEN','docente')
    path='/api/simulator/g1/sensors'
    assert client.patch(path,json={'bms_state':{'soc':10}}).status_code==401
    assert client.patch(path,json={'bms_state':{'soc':10}},headers={'X-Simulator-Token':'docente'}).status_code==200
    assert client.get('/api/robots/g1/sensors').json()['bms_state']['soc']==10
    client.patch('/api/simulator/g1/telemetry',json={'connected':False},headers={'X-Simulator-Token':'docente'})
    t=client.get('/api/robots/g1/sensors').json()
    assert t['valid'] is False and t['bms_state']['soc']==10
    assert client.get('/api/robots/g1/events').json()==[]


def test_sensor_ws_observes_same_canonical_sample(client):
    with client.websocket_connect('/ws/robots/g1/telemetry') as ws:
        first=ws.receive_json()
        res=client.patch('/api/simulator/g1/sensors',json={'imu_state':{'rpy':[0.4,0,0]}})
        assert res.status_code==200
        seq=client.get('/api/robots/g1/telemetry').json()['sample_seq']
        deadline=time.monotonic()+4
        while True:
            msg=ws.receive_json()
            if msg['sample_seq']>=seq:
                assert msg['sensors']['low_state']['imu_state']['rpy'][0]==0.4
                break
            assert time.monotonic()<deadline


def test_failed_release_does_not_cancel_active_virtual_high_five(client):
    assert client.post('/api/robots/g1/commands/high-five').json()['accepted']
    assert client.post('/api/simulator/g1/next-rpc-failure',json={
        'method':'G1ArmActionClient.ExecuteAction','code':-9}).status_code==200
    rejected=client.post('/api/robots/g1/commands/release-arms').json()
    assert not rejected['accepted'] and rejected['sdk']['sdk_return']==-9
    active=client.get('/api/robots/g1/telemetry').json()
    assert active['mode']=='busy' and active['action']=='high_five' and active['last_arm_action_id']==18
    assert client.post('/api/robots/g1/commands/release-arms').json()['accepted']
    assert client.get('/api/robots/g1/telemetry').json()['mode']=='idle'


def test_arm_action_ws_matches_rest_and_teacher_fault_is_protected(monkeypatch,client):
    monkeypatch.setenv('SIMULATOR_TOKEN','onlyteacher')
    fault={'method':'G1ArmActionClient.ExecuteAction','code':-12}
    assert client.post('/api/simulator/g1/next-rpc-failure',json=fault).status_code==401
    with client.websocket_connect('/ws/robots/g1/telemetry') as ws:
        ws.receive_json()
        high=client.post('/api/robots/g1/commands/high-five')
        assert high.json()['accepted']
        final=client.get('/api/robots/g1/telemetry').json()
        deadline=time.monotonic()+4
        while True:
            frame=ws.receive_json()
            if frame['sample_seq']>=final['sample_seq']:
                assert frame['last_arm_action_id']==18 and frame['action']=='high_five'
                assert frame['sample_seq']>=final['sample_seq']
                break
            assert time.monotonic()<deadline
