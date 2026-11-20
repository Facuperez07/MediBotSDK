'use strict';
const el = id => document.getElementById(id);
let lastData = null, socket = null, reconnectTimer = null, commandPending = false, socketOnline = false;
const DEG=180/Math.PI;
const signed=(v,n=1)=>Number(v).toFixed(n);
function drawSensors(d){const v=d.sensors;if(!v)return;
 const imu=v.low_state.imu_state,bms=v.bms_state,ok=v.valid&&d.connected;
 el('sensor-validity').textContent=ok?'Lectura emulada disponible':'Sin enlace · lectura retenida';
 el('sensor-age').textContent='N.º '+v.sensor_seq+' · '+new Date(v.sensor_updated_at).toLocaleTimeString('es-AR');
 el('bms-soc').textContent=bms.soc+' %';el('bms-soh').textContent=bms.soh+' %';
 el('soh-meter').style.width=bms.soh+'%';el('bms-current').textContent=String(bms.current);
 const [roll,pitch,yaw]=imu.rpy.map(n=>n*DEG);
 el('imu-roll').textContent=signed(roll)+'°';el('imu-pitch').textContent=signed(pitch)+'°';el('imu-yaw').textContent=signed(yaw)+'°';
 el('imu-gyro').textContent=imu.gyroscope.map(n=>signed(n,2)).join(' / ');
 el('imu-accel').textContent=imu.accelerometer.map(n=>signed(n,2)).join(' / ');
 el('attitude-world').style.transform=`translateY(${Math.max(-65,Math.min(65,pitch))*1.1}px) rotate(${-roll}deg)`;
 el('attitude-world').parentNode.classList.toggle('offline',!ok);

}
const hex = rgb => '#' + [rgb.r,rgb.g,rgb.b].map(n=>n.toString(16).padStart(2,'0')).join('').toUpperCase();
function feedback(message,kind=''){const n=el('feedback');n.textContent=message;n.className='feedback '+kind;}
function channel(connected){socketOnline=connected;const n=el('transport');n.className='chip '+(connected?'':'off');n.innerHTML='<span class="dot"></span> '+(connected?'Canal de datos activo':'Sin canal de datos');updateButtons();}
function updateButtons(){const ready=Boolean(lastData?.connected)&&socketOnline&&!commandPending;
 for(const id of ['send-led','led-input','send-volume','get-volume','volume-input','send-tts','tts-text','speaker-input'])el(id).disabled=!ready;
 for(const id of ['send-greeting','send-handshake','send-high-five','shake-stage','wave-turn'])el(id).disabled=!ready||lastData?.mode==='busy';
 el('send-release').disabled=!ready||(lastData?.mode==='busy'&&lastData?.action!=='high_five');}
function draw(d){lastData=d;el('battery').textContent=d.battery_percent+' %';el('battery-meter').style.width=d.battery_percent+'%';el('battery-meter').style.background=d.battery_percent<=20?'#ed9267':'var(--accent)';el('battery-hint').textContent=d.battery_percent<=20?'Nivel bajo de batería':'Nivel informado';el('temperature').textContent=Number(d.temperature_c).toFixed(1)+' °C';el('temp-hint').textContent='Indicador legado; no es campo de LowState_';el('robot-status').textContent=d.connected?'Conectado':'Sin enlace';el('robot-status').style.fontSize='clamp(24px,3vw,32px)';el('mode').textContent={idle:'En espera',busy:'Ocupado',offline:'Desconectado'}[d.mode]||d.mode;
 el('action').textContent=d.action==='greeting'?'Saludo en curso':d.action==='handshake'?'Apretón en curso':d.action==='high_five'?'High Five en curso':'Ninguna';el('last-task').textContent=d.last_task_id??'—';
 const color=hex(d.led);el('led-hex').textContent=color;el('led-preview').style.background=color;el('led-preview').style.setProperty('--led-color',color);
 el('volume-readout').textContent=d.volume+' / 100'; if(document.activeElement!==el('volume-input'))el('volume-input').value=d.volume;
 el('tts-last').textContent=d.last_tts?.text??'Ninguna';
 if(d.medibot){
  el('medibot-mission').textContent=d.medibot.mission_name||'Sin misión activa';
  el('medibot-state').textContent=d.medibot.operational_state||'En espera';
  el('medibot-node').textContent=d.medibot.current_node||'Base';
  el('medibot-progress').textContent=(d.medibot.progress_pct||0)+' %';
  el('medibot-voice').textContent=d.medibot.hri_voice||'—';
 }
 drawSensors(d);el('last-seen').textContent=new Date(d.timestamp).toLocaleTimeString('es-AR');updateButtons();}
async function readTelemetry(){try{const r=await fetch('/api/robots/g1/telemetry',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);draw(await r.json());}catch{ /* WebSocket status governs live presentation. */ }}
const labels={'led.updated':'LED actualizado','audio.volume.read':'Volumen consultado','audio.volume.changed':'Volumen cambiado','audio.tts.requested':'TTS solicitado','greeting.started':'Saludo iniciado','greeting.finished':'Saludo (temporizador finalizado)','handshake.started':'Apretón iniciado','handshake.finished':'Apretón (temporizador finalizado)','high_five.started':'High Five solicitado','high_five.finished':'High Five (temporizador finalizado)','arms.release_requested':'Liberación de brazos solicitada','sdk.rpc.rejected':'RPC simulado rechazado','medibot.status_updated':'MediBot: Estado actualizado'};
async function readEvents(){try{const r=await fetch('/api/robots/g1/events',{cache:'no-store'});if(!r.ok)return;const events=(await r.json()).slice(-6).reverse();const container=el('events');container.replaceChildren();if(!events.length){const li=document.createElement('li');li.textContent='Aún no hay comandos';container.append(li);return;}for(const evt of events){const li=document.createElement('li'),name=document.createElement('span'),time=document.createElement('time');name.textContent=labels[evt.event]||evt.event;time.textContent=new Date(evt.timestamp).toLocaleTimeString('es-AR');li.append(name,time);container.append(li);}}catch{}}
async function send(url,method,payload,label){commandPending=true;updateButtons();try{const options={method,headers:{'Content-Type':'application/json'}};if(payload!==undefined)options.body=JSON.stringify(payload);const r=await fetch(url,options);const result=await r.json();if(!r.ok)throw Error(typeof result.detail==='string'?result.detail:'HTTP '+r.status);const code=result.sdk?.rpc?.rpc_code;if(code!==undefined && code!==0){feedback(label+': RPC simulado devolvió '+code+'; no se modificó el estado.','error');}else{feedback(label+': solicitud aceptada (RPC sintético 0; NO confirma ejecución física).','ok');}await readTelemetry();await readEvents();}catch(e){feedback('No se pudo ejecutar: '+e.message,'error');}finally{commandPending=false;updateButtons();}}
el('send-led').addEventListener('click',()=>{const c=el('led-input').value;send('/api/robots/g1/led','PUT',{r:parseInt(c.slice(1,3),16),g:parseInt(c.slice(3,5),16),b:parseInt(c.slice(5,7),16)},'LED');});
el('send-volume').addEventListener('click',()=>send('/api/robots/g1/audio/volume','PUT',{volume:Number(el('volume-input').value)},'SetVolume'));
el('get-volume').addEventListener('click',()=>send('/api/robots/g1/audio/volume','GET',undefined,'GetVolume'));
el('send-tts').addEventListener('click',()=>{const text=el('tts-text').value.trim(),n=el('speaker-input');if(!text){feedback('El texto TTS no puede estar vacío.','error');return;}if(!n.reportValidity())return;send('/api/robots/g1/audio/tts','POST',{text,speaker_id:Number(n.value)},'TtsMaker');});
el('send-greeting').addEventListener('click',()=>send('/api/robots/g1/commands/greeting','POST',{turn_flag:el('wave-turn').value==='true'},'WaveHand'));
el('send-handshake').addEventListener('click',()=>send('/api/robots/g1/commands/handshake','POST',{stage:Number(el('shake-stage').value)},'ShakeHand'));
el('send-high-five').addEventListener('click',()=>send('/api/robots/g1/commands/high-five','POST',undefined,'ExecuteAction(18) · High Five'));
el('send-release').addEventListener('click',()=>send('/api/robots/g1/commands/release-arms','POST',undefined,'ExecuteAction(99) · Release Arm'));
function connect(){if(reconnectTimer){clearTimeout(reconnectTimer);reconnectTimer=null;}const scheme=location.protocol==='https:'?'wss:':'ws:';socket=new WebSocket(scheme+'//'+location.host+'/ws/robots/g1/telemetry');socket.onopen=()=>{channel(true);feedback('Canal de telemetría establecido','ok');readEvents();};socket.onmessage=e=>{try{draw(JSON.parse(e.data));}catch{feedback('Telemetría inválida','error');}};socket.onclose=()=>{channel(false);feedback('Sin canal de telemetría; reconectando…','error');reconnectTimer=setTimeout(connect,2000);};socket.onerror=()=>socket.close();}
readTelemetry();readEvents();connect();setInterval(readEvents,4000);
