'use strict';
const el=id=>document.getElementById(id);let latest=null;let pending=false;
function headers(){const h={};if(el('token').value)h['X-Simulator-Token']=el('token').value;return h;}
function report(msg,type=''){const n=el('feedback');n.textContent=msg;n.className='feedback '+type;}
async function call(path, method='GET',body){const h=headers();if(body!==undefined)h['Content-Type']='application/json';const r=await fetch(path,{method,headers:h,cache:'no-store',body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'HTTP '+r.status);return data;}
function updateView(s){latest=s;const r=s.robot,t=r.telemetry;el('actual-connected').textContent=r.connected?'Conectado':'Desconectado';el('actual-battery').textContent=t.battery_percent+' %';el('actual-temp').textContent=Number(t.temperature_c).toFixed(1)+' °C';el('actual-drain').textContent=s.simulation.drain_enabled?'Activada':'Desactivada';el('actual-mode').textContent=r.mode;el('actual-seq').textContent=t.sample_seq;el('raw').textContent=JSON.stringify(s,null,2);const sensor=s.latest_sample.sensors;
if(document.activeElement!==el('soc-input'))el('soc-input').value=sensor.bms_state.soc;
if(document.activeElement!==el('soh-input'))el('soh-input').value=sensor.bms_state.soh;
el('actual-rpc-failure').textContent=s.simulation.next_rpc_failure?JSON.stringify(s.simulation.next_rpc_failure):'Ninguno';
const active=document.activeElement;if(active!==el('battery-input')&&active!==el('battery-range')){el('battery-input').value=t.battery_percent;el('battery-range').value=t.battery_percent;}if(active!==el('temp-input'))el('temp-input').value=t.temperature_c;if(active!==el('online-input'))el('online-input').checked=r.connected;if(active!==el('drain-input'))el('drain-input').checked=s.simulation.drain_enabled;}
async function refresh(){if(pending)return;try{const [s,events]=await Promise.all([call('/api/simulator/g1/state'),call('/api/simulator/g1/events')]);updateView(s);const list=el('events');list.replaceChildren();for(const item of events.slice(-9).reverse()){const li=document.createElement('li'),label=document.createElement('span'),time=document.createElement('time');label.textContent=item.event;time.textContent=new Date(item.timestamp).toLocaleTimeString('es-AR');li.append(label,time);list.append(li);}}catch(err){report('No se pudo leer la consola: '+err.message,'error');}}
async function change(data){pending=true;try{const result=await call('/api/simulator/g1/telemetry','PATCH',data);updateView(result.simulation);report('Cambio aplicado a la fuente de telemetría. La HMI recibirá la nueva lectura.','ok');}catch(err){report('No se pudo aplicar: '+err.message,'error');}finally{pending=false;await refresh();}}
el('connect').addEventListener('click',()=>{refresh();refreshVisualStatus();});
el('battery-range').addEventListener('input',()=>el('battery-input').value=el('battery-range').value);
el('battery-input').addEventListener('input',()=>{if(el('battery-input').checkValidity())el('battery-range').value=el('battery-input').value;});
el('battery-apply').addEventListener('click',()=>{const n=el('battery-input');if(!n.reportValidity())return;change({battery_percent:Number(n.value)});});
el('temp-apply').addEventListener('click',()=>{const n=el('temp-input');if(!n.reportValidity())return;change({temperature_c:Number(n.value)});});
el('online-apply').addEventListener('click',()=>change({connected:el('online-input').checked}));
el('drain-apply').addEventListener('click',()=>change({drain_enabled:el('drain-input').checked}));
el('reset').addEventListener('click',async()=>{if(!confirm('¿Restaurar el estado inicial del G1 virtual?'))return;pending=true;try{const result=await call('/api/simulator/g1/reset','POST');updateView(result.simulation);report('Simulación restaurada.','ok');}catch(err){report('No se pudo restaurar: '+err.message,'error');}finally{pending=false;await refresh();}});
// Diagnóstico exclusivo del docente: consulta la misma autenticación que el resto de esta página.
function renderVisualStatus(state,label,message,last){
  el('visual-indicator').dataset.state=state;
  el('visual-label').textContent=label;
  el('visual-message').textContent=message;
  el('visual-last').textContent=last||'—';
}
let visualCheckPending=false;
async function refreshVisualStatus(){
  if(visualCheckPending||document.hidden)return;
  visualCheckPending=true;
  try{
    const data=await call('/api/simulator/g1/visualization/status');
    const date=data.last_successful_check_at?new Date(data.last_successful_check_at):null;
    const last=date&&!Number.isNaN(date.getTime())?date.toLocaleString('es-AR'):'—';
    if(data.status==='connected'&&data.viewer_running===true){
      renderVisualStatus('connected','Conectado','El puente respondió y el Viewer está activo.',last);
    }else if(data.status==='not_configured'){
      renderVisualStatus('neutral','No configurado','Establezca MUJOCO_BRIDGE_URL al iniciar FastAPI.',last);
    }else{
      renderVisualStatus('disconnected','Desconectado','El puente no respondió o el Viewer no está activo.',last);
    }
  }catch(error){
    const unauth=error.message.includes('401')||error.message.includes('X-Simulator-Token');
    renderVisualStatus('neutral',unauth?'Autenticación requerida':'Sin verificación',
      unauth?'Ingrese el token docente arriba y pulse Conectar.':'No se pudo consultar el diagnóstico desde FastAPI.',null);
  }finally{visualCheckPending=false;}
}
refresh();setInterval(refresh,2000);
refreshVisualStatus();setInterval(refreshVisualStatus,5000);

el('rpc-apply').addEventListener('click',async()=>{const n=el('rpc-code');if(!n.reportValidity() || Number(n.value)===0){report('Indique un código entero diferente de cero.','error');return;}pending=true;try{const result=await call('/api/simulator/g1/next-rpc-failure','POST',{method:el('rpc-method').value,code:Number(n.value)});updateView(result.simulation);report('Próximo fallo sintético preparado para el método indicado.','ok');}catch(err){report('No se pudo preparar el fallo: '+err.message,'error');}finally{pending=false;await refresh();}});

// Inputs in the teacher surface only; API receives native IDL-like radians.
function values(ids){const nodes=ids.map(el);if(!nodes.every(n=>n.reportValidity()&&n.value.trim()!==''))return null;const a=nodes.map(n=>Number(n.value));if(!a.every(Number.isFinite)){report('Se requieren números finitos.','error');return null;}return a;}
const rad=Math.PI/180;
async function changeSensors(patch){pending=true;try{const out=await call('/api/simulator/g1/sensors','PATCH',patch);updateView(out.simulation);report('Lectura de sensor inyectada (no es una medición física).','ok');}catch(e){report('No se pudo inyectar: '+e.message,'error');}finally{pending=false;await refresh();}}
el('imu-apply').addEventListener('click',()=>{const v=values(['roll-input','pitch-input','yaw-input']);if(v)changeSensors({imu_state:{rpy:v.map(x=>x*rad)}});});
el('gyro-apply').addEventListener('click',()=>{const v=values(['gyro-x','gyro-y','gyro-z']);if(v)changeSensors({imu_state:{gyroscope:v}});});
el('accel-apply').addEventListener('click',()=>{const v=values(['accel-x','accel-y','accel-z']);if(v)changeSensors({imu_state:{accelerometer:v}});});
el('current-apply').addEventListener('click',()=>{const v=values(['current-input']);if(v)changeSensors({bms_state:{current:v[0]}});});
el('bms-apply').addEventListener('click',()=>{const v=values(['soc-input','soh-input']);if(v)changeSensors({bms_state:{soc:v[0],soh:v[1]}});});
