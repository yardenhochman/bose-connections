'use strict';
const $=id=>document.getElementById(id);
const labels={pc:'PC',phone:'Phone',mac:'Mac'};
const roleIds=['pc','phone','mac'];
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
const darkScheme=matchMedia('(prefers-color-scheme: dark)');
const popover=document.documentElement.classList.contains('popover'); // Mac menu-bar popover, set in index.html

// Confirmed state from the headset (or cache), plus client-side intent layered on top of it.
let state=null;          // last overview-shaped object we received
let op=null;             // connect/disconnect in flight: {action,address,replace?}
let choosing=null;       // address waiting for the user to pick a slot to replace
let busySlots=null;      // Use here: both slots busy, the controller's {address,label} per slot to offer as Replace
let refreshing=false;
let slotOrder=[null,null];
let receivedAt=0;
const anc={desired:null,queued:null,inFlight:false,lastStart:-1e9,timer:0,dragging:false};

// ---- Transport: Android bridge or fetch ----
let seq=0;const bridgeCalls=new Map();
window.finishRequest=(id,json)=>{const p=bridgeCalls.get(id);if(p){bridgeCalls.delete(id);p.resolve(JSON.parse(json));}};
function api(path,data){
 if(window.Android){return new Promise((resolve,reject)=>{const id=String(++seq);const timer=setTimeout(()=>{bridgeCalls.delete(id);reject(new Error('Controller timed out. Refresh before trying again.'));},120000);bridgeCalls.set(id,{resolve:r=>{clearTimeout(timer);if(r.error)reject(new Error(r.error));else resolve(r);}});Android.request(id,path,data?JSON.stringify(data):'');});}
 return fetch(path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined}).then(async r=>{const d=await r.json();if(!r.ok||d.error)throw new Error(d.error||'Request failed');return d;});
}

// ---- Small helpers ----
function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;}
function icon(name){const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('class','i');svg.setAttribute('aria-hidden','true');const use=document.createElementNS(ns,'use');use.setAttribute('href','#i-'+name);svg.append(use);return svg;}
function message(text,error=false){const m=$('message');m.replaceChildren();m.className='status'+(error===true?' error':error==='pending'?' pend':'');if(!text)return;if(error==='pending')m.append(node('span','led pending'));else if(error!=='info')m.append(icon(error?'alert':'check'));m.append(node('span','',text));}
function live(){return !!(state&&state.reachable&&!state.cached);}
// A live check just ran and no controller could read the headset: the slots shown are only last known.
function unreachable(){return !!(state&&state.cached&&state.checked);}
function roles(){return (state&&state.roles)||{};}
function roleOf(address){const r=roles();return roleIds.find(k=>r[k]===address);}
function deviceIcon(d){const role=roleOf(d.address);if(role==='pc')return 'desktop';if(role==='phone')return 'phone';if(role==='mac')return 'laptop';const n=(d.name||'').toLowerCase();if(/\btv\b|television/.test(n))return 'tv';if(/phone|pixel|galaxy|iphone/.test(n))return 'phone';if(/mac|book|laptop/.test(n))return 'laptop';if(/\bpc\b|desktop/.test(n))return 'desktop';return 'device';}
function deviceByAddress(a){return state?.devices?.find(d=>d.address===a);}
function nameOf(a){return deviceByAddress(a)?.name||'device';}
function clock(epoch){return new Date(epoch*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}
function ago(){const t=state?.observed?state.observed*1000:receivedAt;const s=Math.max(0,(Date.now()-t)/1000);if(s<60)return 'just now';const m=Math.round(s/60);return m<60?`${m} min ago`:`at ${clock(t/1000)}`;}

// ---- Slots: keep each connected device in the cup it already occupied ----
function settledSlots(){
 const connected=(state?.devices||[]).filter(d=>d.connected).map(d=>d.address);
 const next=slotOrder.map(a=>connected.includes(a)?a:null);
 for(const a of connected)if(!next.includes(a)){const i=next.indexOf(null);if(i>=0)next[i]=a;}
 slotOrder=next;return next.slice();
}
function slotView(){
 const slots=settledSlots().map(a=>a?{address:a,mode:'connected'}:{address:null,mode:'open'});
 if(op?.action==='disconnect'){const s=slots.find(s=>s.address===op.address);if(s)s.mode='disconnecting';}
 if(op?.action==='connect'){const i=op.replace?slots.findIndex(s=>s.address===op.replace):slots.findIndex(s=>!s.address);if(i>=0)slots[i]={address:op.address,mode:'connecting',replacing:op.replace||null};}
 return slots;
}

// ---- Render ----
function render(){
 if(!state)return;
 const r=roles();const reachable=!!state.reachable;
 // header
 const dot=$('live-dot');
 dot.className=!state.cached&&reachable?'led':'led idle';
 const count=$('slot-count');const occupied=(state.devices||[]).filter(d=>d.connected).length;
 count.hidden=!(state.cached||reachable)||!(state.devices||[]).length||unreachable();
 headerStatus(`${occupied} of 2`);
 const battery=state.battery;$('battery-wrap').hidden=battery==null;
 if(battery!=null){$('battery').textContent=battery+'%';$('battery-wrap').setAttribute('aria-label',`Battery ${battery} percent`);$('battery-fill').setAttribute('width',String(Math.max(1,Math.round(11*battery/100))));}
 renderHere();renderChoice();renderCups(reachable);renderDevices(reachable);renderControllers();renderNoise();syncControls();reportSize();
}

// One line under the title: drop words (never the time) until it fits.
function headerStatus(slots){
 const count=$('slot-count'),status=$('headset-status'),sub=count.parentElement;
 const known='last known '+(state.observed?clock(state.observed):'earlier');
 const forms=unreachable()?[['','Not reachable · '+known],['',known]]:state.cached?[[slots,known]]
  :state.reachable?[[slots+' connected','Live · '+ago()],[slots,'Live · '+ago()],[slots,'Live']]:[[slots,'Headset not reachable']];
 const line=parseFloat(getComputedStyle(sub).lineHeight)||18;
 for(const [c,t] of forms){count.textContent=c;status.textContent=t;if(sub.offsetHeight<line*1.5)break;}
}

function renderCups(reachable){
 const cups=$('cups');cups.replaceChildren();
 const slots=slotView();
 slots.forEach((s,i)=>{
  const d=s.address?deviceByAddress(s.address):null;
  const target=choosing&&s.mode==='connected'&&d;
  const cup=node(target?'button':'div','cup');
  const head=node('div','state');const led=node('span','led');const label=node('span');head.append(led,label,node('span','slot',`Slot ${i+1}`));cup.append(head);
  if(!d){
   const known=reachable&&!state.cached;const last=state.cached&&!unreachable();
   cup.classList.add(known?'open':'unknown');led.className='led idle';label.textContent=known?'Open':last?'Last known':'Unknown';
   const dev=node('div','dev');dev.append(icon('device'));cup.append(dev,node('div','name',known||last?'Open slot':'Not known'),node('div','tag',known?'Connect a saved device':last?'Refresh to check':'Headset not reachable'),node('div','spacer'));
   cups.append(cup);return;
  }
  const dev=node('div','dev');dev.append(icon(deviceIcon(d)));cup.append(dev,node('div','name',d.name));
  const role=roleOf(d.address);
  if(s.replacing)cup.append(node('div','tag',`Replacing ${nameOf(s.replacing)}`));
  else if(role&&role===state.here){const tag=node('div','tag here');tag.append(node('i'),document.createTextNode('This '+(role==='phone'?'phone':labels[role])));cup.append(tag);}
  else cup.append(node('div','tag',role?labels[role]:''));
  if(s.mode==='connecting'){
   cup.classList.add('pending');led.className='led pending';label.textContent='Connecting…';
   cup.append(pendingPill('Connecting…'));
  }else if(s.mode==='disconnecting'){
   cup.classList.add('pending','leaving');led.className='led pending';label.textContent='Disconnecting…';
   cup.append(pendingPill('Disconnecting…'));
  }else if(target){
   cup.classList.add('target');label.textContent=state.cached?'Last known':'Connected';
   cup.setAttribute('aria-label',`Replace ${d.name}`);cup.type='button';cup.dataset.live='true';
   cup.onclick=()=>perform({action:'connect',address:choosing,replace:d.address});
   cup.append(node('span','pill','Replace'));
  }else{
   label.textContent=state.cached?'Last known':'Connected';if(state.cached)led.className='led idle';
   const b=node('button','btn ghost','Disconnect');b.type='button';b.dataset.live='true';b.setAttribute('aria-label',`Disconnect ${d.name}`);
   b.onclick=()=>perform({action:'disconnect',address:d.address});cup.append(b);
  }
  cups.append(cup);
 });
}

function pendingPill(text){const p=node('div','pill pending',text);p.setAttribute('aria-busy','true');return p;}
function renderChoice(){
 const target=choosing&&deviceByAddress(choosing),box=$('choose'),opts=$('choose-options');
 box.hidden=!target&&!busySlots;box.classList.toggle('slots',!!busySlots);opts.replaceChildren();
 if(busySlots){
  $('choose-text').textContent=MSG.busy;
  for(const s of busySlots){const b=node('button','btn connect',MSG.replace.replace('{label}',s.label));b.type='button';b.onclick=()=>useHere(s.address);opts.append(b);}
 }else if(target)$('choose-text').textContent=`Both slots are in use. Choose which connection ${target.name} replaces.`;
}
// The one-tap primary action. It works from cached state too: the controller reads the headset itself first.
function renderHere(){
 const here=hereAddress(),b=$('use-here');$('here').hidden=!here;if(!here)return;
 const mine=!!op?.here;b.classList.toggle('pressed',mine);b.setAttribute('aria-busy',String(mine));
 b.textContent=mine?(op.replace?MSG.replacing.replace('{label}',op.label):MSG.pending):'Use here';
 b.setAttribute('aria-label',mine?b.textContent:'Use here: move the headphones to this '+(state.here==='phone'?'phone':labels[state.here]||'device'));
}

function renderDevices(reachable){
 const list=$('devices');list.replaceChildren();
 const devices=state.devices||[];
 if(!devices.length){const empty=node('div','empty');empty.append(node('strong','',reachable?'No saved devices found':'Headset unavailable'),node('span','',reachable?'Pair your devices in the headset’s Bluetooth settings.':'Turn on the headset and keep it near one of your controllers.'));list.append(empty);return;}
 // a device being connected already shows in its cup as pending, so it leaves the list until the change settles or reverts
 const saved=devices.filter(d=>!d.connected&&!(op?.action==='connect'&&op.address===d.address));
 if(!saved.length){const empty=node('div','empty');empty.append(node('strong','','Every saved device holds a slot'),node('span','','Disconnect one above to free a slot.'));list.append(empty);return;}
 for(const d of saved){
  const row=node('div','device');row.dataset.address=d.address;row.append(icon(deviceIcon(d)));
  const info=node('div','device-info');const role=roleOf(d.address);
  const choosingHere=choosing===d.address;
  const sub=node('div','s',choosingHere?'Choose a slot above to replace':`Saved · not connected${role?' · '+labels[role]:''}`);
  if(choosingHere)sub.classList.add('pend');
  info.append(node('div','n',d.name),sub);row.append(info);
  const b=node('button','btn');b.type='button';
  if(choosingHere){b.className='btn connect pressed';b.textContent='Connect';b.setAttribute('aria-pressed','true');b.setAttribute('aria-label',`Connect ${d.name}`);b.onclick=()=>cancelChoice(true);}
  else{b.className='btn connect';b.textContent='Connect';b.dataset.live='true';b.setAttribute('aria-label',`Connect ${d.name}`);b.onclick=()=>connect(d.address);}
  row.append(b);list.append(row);
 }
}

function renderControllers(){
 const box=$('controllers');box.replaceChildren();const list=state.controllers||[];
 // The controller serving this page is here whenever it just read the headset live, whatever its own list says.
 const hereLive=!!(state.here&&state.reachable&&!state.cached);
 if(!list.length&&!hereLive)return;
 box.append(document.createTextNode('Controllers: '));
 roleIds.forEach((id,i)=>{
  const s=list.find(c=>c.controller===id);
  const word=id===state.here&&(hereLive||s?.reachable!==false)?'here':controllerWord(id,s);
  if(i)box.append(document.createTextNode(' · '));box.append(node('b','',labels[id]),document.createTextNode(' '+word));
 });
}

// Why a controller cannot read the headset, in a word or two (not just "offline").
function controllerWord(id,s){
 if(!s)return 'not set up';
 if(s.reachable)return 'available';
 // A controller whose own device holds a slot is plainly connected, not "checking".
 if(s.checking)return deviceByAddress(roles()[id])?.connected?'connected':'checking…';
 if(s.link===false)return 'not connected';
 const e=String(s.error||'');
 if(/Controller unavailable: ConnectionRefused/.test(e))return 'app not running';
 if(/Controller unavailable: .*Timeout/i.test(e))return 'no answer';
 if(!e||/Controller unavailable/.test(e))return 'offline';
 return 'can’t reach headset';
}

// ---- Noise cancellation ----
function shownNoise(){return anc.desired||state?.noise||null;}
function renderNoise(){
 const n=shownNoise();$('noise-controls').hidden=!state?.noise;
 if(anc.dragging&&n){$('noise-enabled').checked=!!n.enabled;return;}
 const busy=anc.inFlight||anc.queued;
 const readout=$('noise-readout');readout.replaceChildren();
 if(!n){readout.textContent='—';$('plot').setAttribute('aria-label','Outside sound: unknown');ridges.set(null);return;}
 const lvl=Number(n.level);
 if(n.enabled){const b=node('b','',`Level ${lvl}`);if(busy)b.className='pend';readout.append(b,document.createTextNode(' / 10'));}
 else{const b=node('b','','Off');if(busy)b.className='pend';readout.append(b,document.createTextNode(' · all through'));}
 $('plot').setAttribute('aria-label',n.enabled?`Outside sound let through: noise cancellation level ${lvl} of 10`:'Outside sound let through: noise cancellation off, all of it');
 if(!anc.dragging){$('noise-level').value=String(lvl);}
 $('noise-enabled').checked=!!n.enabled;
 setFill();
 const sub=$('noise-current');sub.replaceChildren();sub.classList.toggle('pend',!!busy);
 if(busy){sub.append(node('span','led pending'),document.createTextNode(n.enabled?`Setting level ${lvl}…`:'Turning off…'));}
 else sub.textContent=n.enabled?`On · level ${lvl} of 10`:'Off · all through';
 ridges.set(n);
}
function setFill(){const el=$('noise-level');el.style.setProperty('--pct',(Number(el.value)*10)+'%');}
function requestNoise(level,enabled){
 if(!live()||op)return;
 anc.desired={level,enabled};anc.queued={level,enabled};message('');renderNoise();syncControls();pumpNoise();
}
function pumpNoise(){
 if(anc.inFlight||!anc.queued||op)return;
 const wait=anc.lastStart+250-performance.now();
 if(wait>0){clearTimeout(anc.timer);anc.timer=setTimeout(pumpNoise,wait);return;}
 const v=anc.queued;anc.queued=null;anc.inFlight=true;anc.lastStart=performance.now();renderNoise();syncControls();
 api('/api/override',{action:'noise',level:v.level,enabled:v.enabled}).then(async r=>{
  if(r.state)adoptNoise(r.state);
  if(!r.ok||!r.verified)throw new Error(r.message||r.error||'The headset didn’t confirm the noise setting. Refresh before trying again.');
  if(!r.state)adopt(await api('/api/overview'));
  if(!anc.queued){anc.desired=null;message(r.message||'Noise cancellation updated');}
 }).catch(e=>{clearTimeout(anc.timer);anc.queued=null;anc.desired=null;message(e.message,true);})
 .finally(()=>{anc.inFlight=false;render();pumpNoise();});
}

// ---- Connections ----
function adopt(next){state=next;receivedAt=Date.now();}
// A noise response may carry an empty device list (Android without an earlier overview): merge only what it verified.
function adoptNoise(next){
 if(Array.isArray(next.devices)&&next.devices.length)return adopt(next);
 const merged={...state};if('noise' in next)merged.noise=next.noise;if(next.battery!=null)merged.battery=next.battery;state=merged;
}
async function perform(data){
 if(op||!live()||anc.inFlight||anc.queued)return;
 const opener=choosing;choosing=null;op=data;message('');render();
 try{
  const r=await api('/api/override',data);
  if(r.state)adopt(r.state);
  if(!r.ok||!r.verified)throw new Error(r.message||r.error||'The headset didn’t confirm the change. Refresh before trying again.');
  if(data.action==='connect'){const i=data.replace?slotOrder.indexOf(data.replace):slotOrder.indexOf(null);if(i>=0)slotOrder[i]=data.address;}
  if(!r.state)adopt(await api('/api/overview'));
  message(r.message||(data.action==='connect'?`${nameOf(data.address)} connected`:`${nameOf(data.address)} disconnected`));
 }catch(e){message(e.message,true);}
 finally{op=null;render();pumpNoise();if(opener)focusRow(opener);}
}
function connect(address){
 const target=deviceByAddress(address);if(!target||!live()||op)return;
 if(target.connected)return message(`${target.name} is already connected.`);
 const connected=state.devices.filter(d=>d.connected);
 if(connected.length<2)return perform({action:'connect',address});
 choosing=address;message('');render();
 const first=document.querySelector('.cup.target');if(first)first.focus();
}
function cancelChoice(restoreFocus){const a=choosing;choosing=null;busySlots=null;message('');render();if(restoreFocus&&a)focusRow(a);}
function focusRow(address){const b=document.querySelector(`.device[data-address="${CSS.escape(address)}"] button`);if(b&&!b.disabled)b.focus();}
$('cancel-replace').onclick=()=>cancelChoice(true);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&(choosing||busySlots)&&!document.querySelector('dialog[open]'))cancelChoice(true);});

// ---- Use here: one tap moves the headset to this device (texts and flow: tests/switch-contract.json) ----
const MSG={pending:'Connecting…',replacing:'Replacing {label}…',ok:'Playing on Bose 700',busy:'Both slots busy · choose one to replace',replace:'Replace {label}',retry_hint:' · tap to retry',
 errors:{unreachable:'Couldn’t reach the headphones',timeout:'Took too long to switch',unverified:'The headphones didn’t confirm the switch',keep_one:'Can’t replace that one: keep a phone, PC or Mac connected',no_audio:'Connected, but no sound from the headphones',audio_not_moved:'Headphones connected, but PC audio didn’t switch'}};
function hereAddress(){return state?roles()[state.here]:null;}
function switchSource(){return window.Android?'android-app':state?.here==='mac'?'mac-popover':'web';}
// Resolves with the controller's reply whatever its outcome; busy and error replies are answers, not exceptions.
function switchCall(body){
 if(window.Android)return new Promise(resolve=>{const id=String(++seq);const timer=setTimeout(()=>{bridgeCalls.delete(id);resolve({ok:false,error_key:'timeout'});},160000);
  bridgeCalls.set(id,{resolve:r=>{clearTimeout(timer);resolve(r);}});const json=JSON.stringify(body);
  if(typeof Android.switchHere==='function')Android.switchHere(id,json);else Android.request(id,'/api/switch',json);});
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),160000);
 return fetch('/api/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:abort.signal}).then(r=>r.json())
  .catch(e=>({ok:false,error_key:e.name==='AbortError'?'timeout':'unreachable'})).finally(()=>clearTimeout(timer));
}
async function useHere(replace){
 const here=hereAddress();if(!here||op||anc.inFlight||anc.queued)return;
 const label=replace?(busySlots?.find(s=>s.address===replace)?.label||'device'):null;
 busySlots=null;choosing=null;op={action:'connect',address:here,replace:replace||undefined,label,here:true};
 message(replace?MSG.replacing.replace('{label}',label):MSG.pending,'pending');render();
 const body={source:switchSource(),request_id:Math.random().toString(36).slice(2,10)};if(replace)body.replace=replace;
 let r;try{r=await switchCall(body);}catch(e){r=null;}
 op=null;
 if(r&&r.ok&&r.verified){
  if(r.state)adopt(r.state);else try{adopt(await api('/api/overview'));}catch(e){}
  const i=replace?slotOrder.indexOf(replace):slotOrder.indexOf(null);if(i>=0&&!slotOrder.includes(here))slotOrder[i]=here;
  message(MSG.ok);
 }else if(r&&r.busy){busySlots=Array.isArray(r.slots)?r.slots:[];message('');}
 else message((MSG.errors[r?.error_key]||r?.error||MSG.errors.unreachable)+MSG.retry_hint,true);
 render();pumpNoise();
 if(busySlots)document.querySelector('#choose-options .btn')?.focus();
}
$('use-here').onclick=()=>useHere();

// One mutation at a time; the busy item stays legible, the rest just disables.
function syncControls(){
 const ok=live();const ancBusy=!!(anc.inFlight||anc.queued);
 document.querySelectorAll('[data-live="true"]').forEach(el=>{
  if(el.id==='noise-enabled')el.disabled=!ok||!!op||!state?.noise;
  else if(el.id==='noise-level'){el.disabled=!ok||!!op||!state?.noise||!shownNoise()?.enabled;$('noise-slider').classList.toggle('off',el.disabled);}
  else el.disabled=!ok||!!op||ancBusy;
 });
 $('use-here').disabled=!!op||ancBusy;
 const rb=$('refresh');rb.disabled=refreshing||!!op||ancBusy;rb.classList.toggle('spinning',refreshing);rb.setAttribute('aria-label',refreshing?'Checking':'Refresh');
}

async function refresh(){
 if(refreshing||op||anc.inFlight)return;
 refreshing=true;choosing=null;syncControls();
 try{adopt(await api('/api/overview'));message(unreachable()?'No controller can reach the headset right now. Connect it to a phone, PC or Mac in Bluetooth settings, then refresh.':'',unreachable()?'info':false);}catch(e){message(e.message,true);}
 finally{refreshing=false;render();if(!state)syncControls();}
}

// ---- Ridge plot: outside sound let through ----
const ridges=(()=>{
 const canvas=$('ridges');const ctx=canvas.getContext('2d');
 const LINES=15,KNOTS=9;
 // seeded PRNG so the landscape is the same on every render and device
 function mulberry(a){return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
 const rand=mulberry(0x24977df1);
 const field=[];for(let l=0;l<LINES;l++){const k=[];for(let j=0;j<=KNOTS;j++)k.push(rand());const fine=[];for(let j=0;j<=KNOTS*3;j++)fine.push(rand());field.push({k,fine,shift:(rand()-.5)*.12,gain:.75+rand()*.5});}
 function smooth(arr,x){const n=arr.length-1;const p=Math.min(n,Math.max(0,x*n));const i=Math.min(n-1,Math.floor(p));const f=p-i;const s=f*f*(3-2*f);return arr[i]*(1-s)+arr[i+1]*s;}
 function height(l,u){const f=field[l];const c=.5+f.shift;const env=Math.exp(-Math.pow((u-c)/.2,2))*.85+Math.exp(-Math.pow((u-c)/.42,2))*.15;const n=smooth(f.k,u)*.82+smooth(f.fine,u)*.18;return env*Math.pow(n,2.2)*f.gain*1.5;}
 let current=null,from=0,to=0,t0=0,raf=0,dashed=false,known=true;
 function amplitudeFor(n){if(!n)return .1;if(!n.enabled)return 1.18;return .06+.94*(10-Number(n.level))/10;}
 function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;
  const dpr=window.devicePixelRatio||1;const W=Math.round(w*dpr),H=Math.round(h*dpr);
  if(canvas.width!==W||canvas.height!==H){canvas.width=W;canvas.height=H;}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const css=getComputedStyle(document.documentElement);const v=k=>css.getPropertyValue(k).trim();
  const ground=v('--ground'),ridge=v('--ridge'),a0=parseFloat(v('--ridge-a0'))||.4,lw=parseFloat(v('--ridge-w'))||1.2;
  // ridges never climb into the caption row: displacement saturates smoothly below it
  const cap=canvas.previousElementSibling;const ceiling=cap?cap.offsetTop+cap.offsetHeight+6:h*.15;
  const top=Math.max(h*.25,ceiling+10),bottom=h*.96,gap=(bottom-top)/(LINES-1),peak=h*.25;
  const step=Math.max(4,w/90);const amp=current??.1;
  for(let l=0;l<LINES;l++){
   const base=top+l*gap;const pts=[];
   const room=base-ceiling;
   for(let x=0;x<=w+step;x+=step){const u=Math.min(1,x/w);pts.push([Math.min(x,w),base-room*Math.tanh(height(l,u)*peak*amp/room)]);}
   const line=new Path2D();line.moveTo(pts[0][0],pts[0][1]);
   for(let i=0;i<pts.length-1;i++){const p0=pts[Math.max(0,i-1)],p1=pts[i],p2=pts[i+1],p3=pts[Math.min(pts.length-1,i+2)];line.bezierCurveTo(p1[0]+(p2[0]-p0[0])/6,p1[1]+(p2[1]-p0[1])/6,p2[0]-(p3[0]-p1[0])/6,p2[1]-(p3[1]-p1[1])/6,p2[0],p2[1]);}
   // fill below the ridge so it hides the ones behind; only the ridge itself is stroked
   const below=new Path2D(line);below.lineTo(w,h);below.lineTo(0,h);below.closePath();ctx.fillStyle=ground;ctx.fill(below);
   ctx.globalAlpha=(a0+(1-a0)*l/(LINES-1))*(known?1:.4);ctx.strokeStyle=ridge;ctx.lineWidth=lw;ctx.lineJoin='round';
   ctx.setLineDash(dashed?[5,4]:[]);ctx.stroke(line);ctx.globalAlpha=1;
  }
  ctx.setLineDash([]);
 }
 function frame(now){const p=Math.min(1,(now-t0)/180);const e=1-Math.pow(1-p,3);current=from+(to-from)*e;draw();raf=p<1?requestAnimationFrame(frame):0;}
 function set(n){
  known=!!n;dashed=!!n&&!n.enabled;const target=amplitudeFor(n);
  if(current===null||reducedMotion.matches){cancelAnimationFrame(raf);raf=0;current=to=target;draw();return;}
  if(target===to&&raf)return;
  if(target===to&&current===target){draw();return;}
  from=current;to=target;t0=performance.now();if(!raf)raf=requestAnimationFrame(frame);
 }
 new ResizeObserver(()=>draw()).observe(canvas);
 darkScheme.addEventListener('change',()=>draw());
 return {set,draw};
})();

// ---- Mac popover: report the content height so the native popover fits it (no-op outside WKWebView) ----
let sizeFrame=0,lastSize=0;
function reportSize(){
 if(!popover||sizeFrame||!window.webkit?.messageHandlers?.boseSize)return;
 sizeFrame=requestAnimationFrame(()=>{
  sizeFrame=0;let h=document.querySelector('.shell').getBoundingClientRect().height;
  const d=$('settings-dialog');if(d.open)h=Math.max(h,d.offsetHeight+24);
  h=Math.ceil(h);if(h===lastSize)return;lastSize=h;
  window.webkit.messageHandlers.boseSize.postMessage({height:h});
 });
}
if(popover){new ResizeObserver(reportSize).observe(document.querySelector('.shell'));document.fonts.ready.then(reportSize);}

// ---- Wiring ----
const level=$('noise-level');
level.addEventListener('input',()=>{anc.dragging=true;setFill();const n=shownNoise();if(!n)return;const preview={level:Number(level.value),enabled:true};
 ridges.set(preview);const readout=$('noise-readout');readout.replaceChildren(node('b','',`Level ${preview.level}`),document.createTextNode(' / 10'));$('noise-current').textContent=`On · level ${preview.level} of 10`;});
level.addEventListener('change',()=>{anc.dragging=false;const lvl=Number(level.value);const cur=shownNoise();if(cur&&cur.enabled&&Number(cur.level)===lvl){renderNoise();return;}requestNoise(lvl,true);});
level.addEventListener('pointerup',()=>{if(anc.dragging){anc.dragging=false;}});
$('noise-enabled').addEventListener('change',e=>{const cur=shownNoise();const lvl=cur?Number(cur.level):Number(level.value);requestNoise(lvl,e.target.checked);});
$('refresh').onclick=refresh;
setInterval(()=>{if(state&&live()&&!op)headerStatus($('slot-count').textContent.split(' connected')[0]);},30000);
new ResizeObserver(()=>{if(state)headerStatus($('slot-count').textContent.split(' connected')[0]);}).observe(document.querySelector('.top'));

$('settings').onclick=()=>{
 if(!state&&window.Android){Android.settings();return;}if(!state)return;
 $('role-fields').replaceChildren();
 for(const id of roleIds){const label=node('label','',labels[id]);label.htmlFor='role-'+id;const select=node('select');select.id='role-'+id;const empty=node('option','','Not identified');empty.value='';select.append(empty);for(const d of state.devices||[]){const option=node('option','',d.name);option.value=d.address;select.append(option);}select.value=roles()[id]||'';$('role-fields').append(label,select);}
 $('native-settings').hidden=!window.Android;$('open-window').hidden=!(popover||window.webkit?.messageHandlers?.boseOpenWindow);$('settings-dialog').showModal();reportSize();
};
$('save-roles').onclick=async()=>{const next={};for(const id of roleIds)if($('role-'+id).value)next[id]=$('role-'+id).value;try{await api('/api/roles',{roles:next});$('settings-dialog').close();await refresh();}catch(e){message(e.message,true);}};
$('native-settings').onclick=()=>Android.settings();
$('open-window').onclick=()=>{$('settings-dialog').close();window.webkit?.messageHandlers?.boseOpenWindow?.postMessage(null);};
$('settings-dialog').addEventListener('close',()=>reportSize());

ridges.set(null);syncControls();
(async()=>{try{const cached=await api('/api/cached');if(cached&&cached.devices&&cached.devices.length){adopt(cached);render();}}catch(e){}await refresh();})();
