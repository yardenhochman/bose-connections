'use strict';
// ---- machines:begin ---- Pure state machines (docs/state-machines.md, machines 2-5). No DOM here:
// tests/web_machines.cjs runs this block in node. Each machine is one state value and one transition function, its only
// writer; an event a state does not take returns the same state.
const IDLE=Object.freeze({kind:'idle'});
// 2. Interaction: idle | choosing{address} (Connect with both slots full: pick the slot) | offer{slots} (Use here was
// busy: Replace per slot) | mutating{action,address,replace,label,here} (an /api/override or /api/switch?wait in flight).
function interact(s,e){
 switch(e.type){
  case 'pick':if(s.kind==='mutating')return s;return s.kind==='choosing'&&s.address===e.address?IDLE:{kind:'choosing',address:e.address};
  case 'cancel':return s.kind==='choosing'||s.kind==='offer'?IDLE:s;
  case 'drop-choice':return s.kind==='choosing'?IDLE:s; // a refresh or a switch tap ends a slot choice, not a Use here offer
  case 'start':if(s.kind==='mutating')return s;return {kind:'mutating',action:e.action,address:e.address,replace:e.replace||null,label:e.label||null,here:!!e.here};
  case 'busy':return s.kind==='mutating'&&s.here?{kind:'offer',slots:Array.isArray(e.slots)?e.slots:[]}:s;
  case 'settled':return s.kind==='mutating'?IDLE:s;
 }
 return s;
}
// 3. Use-here tap on the shared state: idle | posting{tap} (shown at once until POST /api/switch answers) |
// refused{fail} (the controller never took it). A snapshot that carries an operation replaces a refusal.
function tapper(s,e){
 switch(e.type){
  case 'tap':return s.kind==='posting'?s:{kind:'posting',tap:e.tap};
  case 'answered':return s.kind==='posting'?IDLE:s;
  case 'refused':return s.kind==='posting'?{kind:'refused',fail:e.fail}:s;
  case 'operation':return s.kind==='refused'?IDLE:s;
 }
 return s;
}
// The operation a POST /api/switch reply carries, folded into the last snapshot, unless that snapshot is newer (higher
// seq) and already holds an operation started no earlier. A restarted controller counts seq from 0 again: start times
// still order its operations.
function foldAccepted(snap,snapSeq,reply){
 const o=reply?.operation,cur=snap?.operation;if(!o)return snap;
 if(cur&&reply.seq!=null&&snapSeq!=null&&reply.seq<snapSeq&&(cur.started_at||0)>=(o.started_at||0))return snap;
 return {...snap,operation:o};
}
// 4. Link to the controller's GET /api/state: boot | live | lost (long-poll failing, retried with backoff) | legacy
// (no /api/state: overview polling). Legacy is final; at boot any failure means legacy.
function linker(s,e){
 if(s==='legacy')return s;
 switch(e){
  case 'snapshot':return 'live';
  case 'error':return s==='boot'?'legacy':'lost';
  case 'gone':return 'legacy';
 }
 return s;
}
// 5. Noise writer: idle | waiting{queued} (throttle gap) | held{queued} (a connection change or switch runs: sent when it
// ends) | sending{sent,queued}. The newest input is always the one sent next; a failure, or a held value whose change
// ended with the headset out of reach (drop), falls back to the verified headset value.
function noiser(s,e){
 switch(e.type){
  case 'input':return s.kind==='sending'?{...s,queued:e.value}:s.kind==='held'?{kind:'held',queued:e.value}:{kind:'waiting',queued:e.value};
  case 'hold':return s.kind==='waiting'?{kind:'held',queued:s.queued}:s;
  case 'resume':return s.kind==='held'?{kind:'waiting',queued:s.queued}:s;
  case 'drop':return s.kind==='held'?IDLE:s;
  case 'send':return s.kind==='waiting'?{kind:'sending',sent:s.queued,queued:null}:s;
  case 'ok':return s.kind!=='sending'?s:s.queued?{kind:'waiting',queued:s.queued}:IDLE;
  case 'fail':return IDLE;
 }
 return s;
}
function noiseShown(s){return s.kind==='idle'?null:s.queued||s.sent;}
// 6. Intent queue: idle | queued{intent}. One connection intent ({action:'connect'|'disconnect'|'here'|'switch', address,
// replace, target}) held while other work runs. The latest wins; the same intent again cancels it; release hands it on.
function intentKey(i){return i?[i.action,i.address||'',i.replace||'',i.target||''].join('|'):'';}
function intents(s,e){
 switch(e.type){
  case 'hold':return s.kind==='queued'&&intentKey(s.intent)===intentKey(e.intent)?IDLE:{kind:'queued',intent:e.intent};
  case 'cancel':case 'release':return IDLE;
 }
 return s;
}
// What runs next. One request toward the controller at a time: a connection change or switch (change), else a noise
// write (sending). When both wait, the queued intent goes first; a noise value waiting behind it is held.
// w: {change, noise: noiser state, intent: intents state, live}. Returns wait | hold-noise | intent | resume-noise |
// drop-noise | noise | idle.
function schedule(w){
 if(w.change)return w.noise.kind==='waiting'?'hold-noise':'wait';
 if(w.noise.kind==='sending')return 'wait';
 if(w.intent.kind==='queued')return 'intent';
 if(w.noise.kind==='held')return w.live?'resume-noise':'drop-noise';
 if(w.noise.kind==='waiting')return 'noise';
 return 'idle';
}
// The intended result drawn over the verified slots: the change in flight (pend 'flight') and the queued intent (pend
// 'queued'). slots: [{address|null, st}] with st connected | free | a controller state. Pure: verified data is never
// changed here, so a late reply can only update the layer underneath.
function overlaySlots(slots,flight,queued){
 const out=slots.map(s=>({...s,address:s.address||null,was:s.address||null,pend:null,replacing:null,here:false}));
 for(const [a,how] of [[flight,'flight'],[queued,'queued']]){
  if(!a||!a.address)continue;
  if(a.action==='disconnect'){const s=out.find(s=>s.address===a.address&&s.st==='connected'&&!s.pend);if(s){s.st='disconnecting';s.pend=how;}continue;}
  if(a.action!=='connect'&&a.action!=='here')continue;
  if(out.some(s=>s.address===a.address&&(s.st==='connected'||s.st==='connecting')))continue; // already holds a slot
  let i=a.replace?out.findIndex(s=>s.address===a.replace&&s.st!=='free'):out.findIndex(s=>s.st==='free'&&!s.pend);
  if(i<0&&!a.replace)i=out.findIndex(s=>s.st==='disconnecting'); // the slot a pending disconnect frees
  if(i<0)continue;
  const old=out[i];out[i]={...old,address:a.address,st:'connecting',pend:how,here:!!a.here,replacing:a.replace||(old.st==='disconnecting'?old.address:null)};
 }
 return out;
}
// ---- machines:end ----
const $=id=>document.getElementById(id);
const labels={pc:'PC',phone:'Phone',mac:'Mac'};
const roleIds=['pc','phone','mac'];
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
const darkScheme=matchMedia('(prefers-color-scheme: dark)');
const popover=document.documentElement.classList.contains('popover'); // Mac menu-bar popover, set in index.html

// Confirmed state from the headset (or cache), plus client-side intent layered on top of it.
let state=null;          // last overview-shaped object we received
let ui=IDLE;             // the interaction machine (interact): written only by uiSend
function uiSend(e){ui=interact(ui,e);}
function mut(){return ui.kind==='mutating'?ui:null;}            // connect/disconnect or Use here in flight
function choosingAddr(){return ui.kind==='choosing'?ui.address:null;} // address waiting for a slot to replace
function offerSlots(){return ui.kind==='offer'?ui.slots:null;}     // Use here was busy: {address,label} per slot
let mutations=0;         // counts started changes: an overview reply requested before the latest one is stale
let refreshing=false;
let slotOrder=[null,null];
let receivedAt=0;
const anc={m:IDLE,lastStart:-1e9,timer:0,dragging:false}; // m: the noise writer machine (noiser)
let iq=IDLE;             // the intent queue (intents): written only by queueSend
function queueSend(e){iq=intents(iq,e);}
function queued(){return iq.kind==='queued'?iq.intent:null;}


// ---- Transport: Android bridge or fetch ----
// Every request has a deadline, so a hung one can never hold the queue: a connection change may wait out a switch on the
// controller (150 s), a noise write or a read answers in seconds.
const TIMED_OUT='Controller timed out. Refresh before trying again.';
function deadlineFor(path,data){return path==='/api/override'&&data?.action!=='noise'?160000:path==='/api/override'?20000:30000;}
let seq=0;const bridgeCalls=new Map();
window.finishRequest=(id,json)=>{const p=bridgeCalls.get(id);if(p){bridgeCalls.delete(id);p.resolve(JSON.parse(json));}};
function api(path,data,ms=deadlineFor(path,data)){
 if(window.Android){return new Promise((resolve,reject)=>{const id=String(++seq);const timer=setTimeout(()=>{bridgeCalls.delete(id);reject(new Error(TIMED_OUT));},ms);bridgeCalls.set(id,{resolve:r=>{clearTimeout(timer);if(r.error)reject(new Error(r.error));else resolve(r);}});Android.request(id,path,data?JSON.stringify(data):'');});}
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),ms);
 return fetch(path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined,signal:abort.signal})
  .then(async r=>{const d=await r.json();if(!r.ok||d.error)throw new Error(d.error||'Request failed');return d;})
  .catch(e=>{throw e.name==='AbortError'?new Error(TIMED_OUT):e;}).finally(()=>clearTimeout(timer));
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
// Older than today: say the day too, so a days-old slot view never reads as current.
function stamp(epoch){const d=new Date(epoch*1000);return d.toDateString()===new Date().toDateString()?clock(epoch):d.toLocaleDateString([],{weekday:'short',day:'numeric',month:'short'})+' '+clock(epoch);}
function clock(epoch){return new Date(epoch*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}
function ago(){const t=state?.observed?state.observed*1000:receivedAt;const s=Math.max(0,(Date.now()-t)/1000);if(s<60)return 'just now';const m=Math.round(s/60);return m<60?`${m} min ago`:`at ${clock(t/1000)}`;}

// ---- Slots: keep each connected device in the cup it already occupied ----
function settledSlots(){
 const connected=(state?.devices||[]).filter(d=>d.connected).map(d=>d.address);
 const next=slotOrder.map(a=>connected.includes(a)?a:null);
 for(const a of connected)if(!next.includes(a)){const i=next.indexOf(null);if(i>=0)next[i]=a;}
 slotOrder=next;return next.slice();
}
function slotView(){return overlaySlots(settledSlots().map(a=>({address:a,st:a?'connected':'free'})),mut(),queued());}
// Words for a slot drawn as an intended result: in flight (sent, waiting for the headset) or queued (not sent yet).
function pendWords(s){
 if(s.pend==='queued')return s.st==='disconnecting'?'Disconnects next':s.here?'Moves here next':'Connects next';
 return s.st==='disconnecting'?'Disconnecting…':s.st==='releasing'?'Releasing…':s.here?'Moving here…':'Connecting…';
}
// The pending part of a cup: a spinning pill while in flight, a dotted Cancel while queued (the same tap again cancels).
function pendControl(cup,s,name){
 if(s.pend==='queued'){
  cup.classList.add('queued');
  const b=node('button','pill queued');b.type='button';b.append(node('span','ring'),node('span','','Queued · cancel'));
  b.setAttribute('aria-label',`Cancel the queued ${s.st==='disconnecting'?'disconnect of':'connection of'} ${name}`);
  b.onclick=cancelQueued;cup.append(b);return;
 }
 cup.classList.add('pending');if(s.st!=='connecting')cup.classList.add('leaving');
 cup.append(pendingPill(pendWords(s)));
}

// ---- Render ----
function render(){
 if(stateMode())return renderState();
 if(!state)return;
 const r=roles();const reachable=!!state.reachable;
 // header
 const dot=$('live-dot');
 dot.className=!state.cached&&reachable?'led':'led idle';
 const count=$('slot-count');const occupied=(state.devices||[]).filter(d=>d.connected).length;
 count.hidden=!(state.cached||reachable)||!(state.devices||[]).length||unreachable();
 headerStatus(`${occupied} of 2`);
 renderBattery(state.battery);
 renderHere();renderChoice();renderCups(reachable);renderDevices(reachable);renderControllers();renderNoise();syncControls();reportSize();
}

function renderBattery(battery){
 $('battery-wrap').hidden=battery==null;
 if(battery!=null){$('battery').textContent=battery+'%';$('battery-wrap').setAttribute('aria-label',`Battery ${battery} percent`);$('battery-fill').setAttribute('width',String(Math.max(1,Math.round(11*battery/100))));}
}

// One line under the title: drop words (never the time) until it fits.
function headerStatus(slots){
 const count=$('slot-count'),status=$('headset-status'),sub=count.parentElement;
 const known='last known '+(state.observed?stamp(state.observed):'earlier');
 const forms=unreachable()?[['','Not reachable · '+known],['',known]]:state.cached?[[slots,known]]
  :state.reachable?[[slots+' connected','Live · '+ago()],[slots,'Live · '+ago()],[slots,'Live']]:[[slots,'Headset not reachable']];
 const line=parseFloat(getComputedStyle(sub).lineHeight)||18;
 for(const [c,t] of forms){count.textContent=c;status.textContent=t;if(sub.offsetHeight<line*1.5)break;}
}

function renderCups(reachable){
 const choosing=choosingAddr();
 const cups=$('cups');cups.replaceChildren();
 const slots=slotView();
 slots.forEach((s,i)=>{
  const d=s.address?deviceByAddress(s.address):null;
  const target=choosing&&s.st==='connected'&&!s.pend&&d;
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
  if(s.pend){
   led.className=s.pend==='queued'?'led queued':'led pending';label.textContent=pendWords(s);
   pendControl(cup,s,d.name);
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

function pendingPill(text){const p=node('div','pill pending');p.append(node('span','spin'),node('span','',text));p.setAttribute('aria-busy','true');return p;}
function renderChoice(){
 const choosing=choosingAddr(),busySlots=offerSlots();
 const target=choosing&&deviceByAddress(choosing),box=$('choose'),opts=$('choose-options');
 box.hidden=!target&&!busySlots;box.classList.toggle('slots',!!busySlots);opts.replaceChildren();
 if(busySlots){
  $('choose-text').textContent=MSG.busy;
  for(const s of busySlots){const b=node('button','btn connect',MSG.replace.replace('{label}',s.label));b.type='button';b.onclick=()=>useHere(s.address);opts.append(b);}
 }else if(target)$('choose-text').textContent=`Both slots are in use. Choose which connection ${target.name} replaces.`;
}
// The one-tap primary action. It works from cached state too: the controller reads the headset itself first.
function renderHere(){
 const op=mut();
 const here=hereAddress(),b=$('use-here');$('here').hidden=!here;if(!here)return;
 const mine=!!op?.here,waiting=queued()?.action==='here';
 b.classList.toggle('pressed',mine);b.classList.toggle('queued',waiting&&!mine);b.setAttribute('aria-busy',String(mine));
 b.textContent=mine?(op.replace?MSG.replacing.replace('{label}',op.label):MSG.pending):waiting?QUEUED_HERE:'Use here';
 b.setAttribute('aria-label',mine?b.textContent:waiting?'Cancel the queued Use here':'Use here: move the headphones to this '+(state.here==='phone'?'phone':labels[state.here]||'device'));
}
const QUEUED_HERE='Use here queued · tap to cancel';

function renderDevices(reachable){
 const op=mut(),choosing=choosingAddr();
 const list=$('devices');list.replaceChildren();
 const devices=state.devices||[];
 if(!devices.length){const empty=node('div','empty');empty.append(node('strong','',reachable?'No saved devices found':'Headset unavailable'),node('span','',reachable?'Pair your devices in the headset’s Bluetooth settings.':'Turn on the headset and keep it near one of your controllers.'));list.append(empty);return;}
 // a device being connected already shows in its cup as pending, so it leaves the list until the change settles or reverts
 const inCup=new Set(slotView().filter(s=>s.pend&&s.st==='connecting').map(s=>s.address));
 const saved=devices.filter(d=>!d.connected&&!(op?.action==='connect'&&op.address===d.address)&&!inCup.has(d.address));
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
function shownNoise(){return noiseShown(anc.m)||state?.noise||null;}
function renderNoise(){
 const n=shownNoise();$('noise-controls').hidden=!state?.noise;
 if(anc.dragging&&n){$('noise-enabled').checked=!!n.enabled;return;}
 const busy=anc.m.kind!=='idle';
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
 if(anc.m.kind==='held')sub.append(node('span','led queued'),document.createTextNode(`${n.enabled?'Level '+lvl:'Off'} · ${heldWords()}`));
 else if(busy){sub.append(node('span','led pending'),document.createTextNode(n.enabled?`Setting level ${lvl}…`:'Turning off…'));}
 else sub.textContent=n.enabled?`On · level ${lvl} of 10`:'Off · all through';
 ridges.set(n);
}
// A held noise value says what it waits for: a switch (Use here, Move to) or a Connect / Disconnect.
function heldWords(){const m=mut();return m&&!m.here?'applies when the change ends':'applies when the switch ends';}
const NOISE_DROPPED='Noise change not sent: the headphones aren’t reachable now';
function setFill(){const el=$('noise-level');el.style.setProperty('--pct',(Number(el.value)*10)+'%');}
function requestNoise(level,enabled){
 if(!state?.noise)return;
 if(!live()&&!changeRunning()){message(NOISE_DROPPED,true);renderNoise();return;}
 anc.m=noiser(anc.m,{type:'input',value:{level,enabled}});message('');pump();renderNoise();syncControls();
}
// A connection change or switch is running: this page's own request, or (shared state) an operation started anywhere.
function changeRunning(){return !!mut()||(stateMode()&&opRunning());}
// The one scheduler: called whenever work ends or input arrives (machines: schedule, intents, noiser).
function pump(){
 for(let n=0;n<4;n++){
  const d=schedule({change:changeRunning(),noise:anc.m,intent:iq,live:live()});
  if(d==='hold-noise'){anc.m=noiser(anc.m,{type:'hold'});clearTimeout(anc.timer);renderNoise();return;}
  if(d==='resume-noise'){anc.m=noiser(anc.m,{type:'resume'});continue;}
  if(d==='drop-noise'){anc.m=noiser(anc.m,{type:'drop'});message(NOISE_DROPPED,true);render();return;}
  if(d==='intent'){const i=queued();queueSend({type:'release'});runIntent(i);if(changeRunning()||anc.m.kind==='sending')return;continue;}
  if(d==='noise')pumpNoise();
  return;
 }
}
function pumpNoise(){
 if(anc.m.kind!=='waiting'||changeRunning())return;
 const wait=anc.lastStart+250-performance.now();
 if(wait>0){clearTimeout(anc.timer);anc.timer=setTimeout(pump,wait);return;}
 const v=anc.m.queued;anc.m=noiser(anc.m,{type:'send'});anc.lastStart=performance.now();renderNoise();syncControls();
 let ok=false;
 api('/api/override',{action:'noise',level:v.level,enabled:v.enabled}).then(async r=>{
  if(r.state)adoptNoise(r.state);
  if(!r.ok||!r.verified)throw new Error(r.message||r.error||'The headset didn’t confirm the noise setting. Refresh before trying again.');
  if(!r.state)adopt(await api('/api/overview'));
  ok=true;if(!anc.m.queued)message(r.message||'Noise cancellation updated');
 }).catch(e=>{clearTimeout(anc.timer);message(e.message,true);})
 .finally(()=>{anc.m=noiser(anc.m,{type:ok?'ok':'fail'});render();pump();});
}

// ---- Connections ----
function adopt(next){if(stateMode()){const m={};if(next&&'noise' in next)m.noise=next.noise;if(next?.battery!=null)m.battery=next.battery;state={...state,...m};return;}state=next;receivedAt=Date.now();}
// A noise response may carry an empty device list (Android without an earlier overview): merge only what it verified.
function adoptNoise(next){
 if(Array.isArray(next.devices)&&next.devices.length||stateMode())return adopt(next);
 const merged={...state};if('noise' in next)merged.noise=next.noise;if(next.battery!=null)merged.battery=next.battery;state=merged;
}
// Every connection input goes through act: it runs at once when nothing else does, else it becomes the one queued intent
// (latest wins; the same intent again cancels it), drawn as queued until the running work ends.
function workRunning(){return changeRunning()||anc.m.kind==='sending';}
function act(intent){
 if(workRunning()){uiSend({type:'drop-choice'});queueSend({type:'hold',intent});render();return;}
 if(queued())queueSend({type:'cancel'});
 runIntent(intent,false);
}
function cancelQueued(){queueSend({type:'cancel'});render();}
// fromQueue: released when the running work ended, so it is checked against the verified state first and keeps the
// result line of the work before it.
function runIntent(i,fromQueue=true){
 if(i.action==='switch')return startSwitchNow(i.target,i.replace,fromQueue);
 if(i.action==='here')return stateMode()?startSwitchNow(ST.here,i.replace,fromQueue):useHereNow(i.replace,i.label,fromQueue);
 const d=deviceByAddress(i.address);
 if(!d||!live()){if(fromQueue)message(`${i.action==='connect'?'Connect':'Disconnect'} not sent: the headphones aren’t reachable now`,true);return render();}
 if(i.action==='disconnect'){if(!d.connected){message(`${d.name} is already disconnected.`,'info');return render();}return performNow(i,fromQueue);}
 if(d.connected){message(`${d.name} is already connected.`,'info');return render();}
 const full=state.devices.filter(x=>x.connected).length>=2,replace=i.replace&&deviceByAddress(i.replace)?.connected?i.replace:null;
 if(full&&!replace){uiSend({type:'pick',address:i.address});message('');return render();} // the slots filled meanwhile: ask, never guess
 performNow({action:'connect',address:i.address,...(replace?{replace}:{})},fromQueue);
}
function perform(data){if(live()||changeRunning())act(data);}
async function performNow(data,fromQueue){
 const body={action:data.action,address:data.address,...(data.replace?{replace:data.replace}:{})};
 const opener=choosingAddr();mutations++;uiSend({type:'start',...body});if(!fromQueue)message('');render();
 data=body;
 try{
  const r=await api('/api/override',data);
  if(r.state)adopt(r.state);
  if(!r.ok||!r.verified)throw new Error(r.message||r.error||'The headset didn’t confirm the change. Refresh before trying again.');
  if(data.action==='connect'){const i=data.replace?slotOrder.indexOf(data.replace):slotOrder.indexOf(null);if(i>=0)slotOrder[i]=data.address;}
  if(!r.state)adopt(await api('/api/overview'));
  message(r.message||(data.action==='connect'?`${nameOf(data.address)} connected`:`${nameOf(data.address)} disconnected`));
 }catch(e){message(e.message,true);}
 finally{uiSend({type:'settled'});render();pump();if(opener)focusRow(opener);}
}
function connect(address){
 const target=deviceByAddress(address);if(!target||!live()&&!changeRunning())return;
 if(target.connected)return message(`${target.name} is already connected.`);
 // A slot that a Disconnect in flight frees counts as open: the connect queues behind it. (A queued Disconnect does not:
 // this connect replaces it, one queued intent at a time.)
 const leaving=[mut()].filter(a=>a?.action==='disconnect').map(a=>a.address);
 const connected=state.devices.filter(d=>d.connected&&!leaving.includes(d.address));
 if(connected.length<2)return perform({action:'connect',address});
 uiSend({type:'pick',address});message('');render();
 const first=document.querySelector('.cup.target');if(first)first.focus();
}
function cancelChoice(restoreFocus){const a=choosingAddr();uiSend({type:'cancel'});message('');render();if(restoreFocus&&a)focusRow(a);}
function focusRow(address){const b=document.querySelector(`.device[data-address="${CSS.escape(address)}"] button`);if(b&&!b.disabled)b.focus();}
$('cancel-replace').onclick=()=>cancelChoice(true);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&(ui.kind==='choosing'||ui.kind==='offer')&&!document.querySelector('dialog[open]'))cancelChoice(true);});

// ---- Use here: one tap moves the headset to this device (texts and flow: tests/switch-contract.json) ----
const MSG={pending:'Connecting…',replacing:'Replacing {label}…',ok:'Playing on Bose 700',busy:'Both slots busy · choose one to replace',replace:'Replace {label}',retry_hint:' · tap to retry',
 errors:{unreachable:'Couldn’t reach the headphones',timeout:'Took too long to switch',unverified:'The headphones didn’t confirm the switch',keep_one:'Can’t replace that one: keep a phone, PC or Mac connected',no_audio:'Connected, but no sound from the headphones',audio_not_moved:'Headphones connected, but PC audio didn’t switch',forgotten:'The headphones forgot this PC · hold their Bluetooth button until “Ready to connect”'}};
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
function useHere(replace){
 if(stateMode())return startSwitch(ST.here,replace);
 const here=hereAddress();if(!here||mut()?.here)return; // its own request in flight cannot be taken back
 if(!replace&&queued()?.action==='here')return cancelQueued(); // the same tap again cancels the queued Use here
 const label=replace?(offerSlots()?.find(s=>s.address===replace)?.label||'device'):null;
 act({action:'here',address:here,replace:replace||null,label,here:true});
}
async function useHereNow(replace,label,fromQueue){
 const here=hereAddress();if(!here)return;
 mutations++;uiSend({type:'start',action:'connect',address:here,replace,label,here:true});
 message(replace?MSG.replacing.replace('{label}',label):MSG.pending,'pending');render();
 const body={source:switchSource(),request_id:Math.random().toString(36).slice(2,10)};if(replace)body.replace=replace;
 let r;try{r=await switchCall(body);}catch(e){r=null;}
 uiSend(r&&r.busy?{type:'busy',slots:r.slots}:{type:'settled'});
 if(r&&r.ok&&r.verified){
  if(r.state)adopt(r.state);else try{adopt(await api('/api/overview'));}catch(e){}
  const i=replace?slotOrder.indexOf(replace):slotOrder.indexOf(null);if(i>=0&&!slotOrder.includes(here))slotOrder[i]=here;
  message(MSG.ok);
 }else if(r&&r.busy)message('');
 else message((MSG.errors[r?.error_key]||r?.error||MSG.errors.unreachable)+MSG.retry_hint,true);
 render();pump();
 if(offerSlots())document.querySelector('#choose-options .btn')?.focus();
}
$('use-here').onclick=()=>useHere();

// Input is never disabled for work in progress: a tap during other work queues (act), a noise value is held (pump).
// Only what cannot be done is disabled: no live headset, its own request in flight, a refresh while work runs.
function syncControls(){
 const ok=live(),work=workRunning(),noiseOk=!!state?.noise&&(ok||changeRunning());
 document.querySelectorAll('[data-live="true"]').forEach(el=>{
  if(el.id==='noise-enabled')el.disabled=!noiseOk;
  else if(el.id==='noise-level'){el.disabled=!noiseOk||!shownNoise()?.enabled;$('noise-slider').classList.toggle('off',el.disabled);}
  else el.disabled=!ok&&!changeRunning();
 });
 // Switch targets work from any state (the controller reads the headset itself first).
 document.querySelectorAll('[data-switch="true"]').forEach(el=>{el.disabled=false;});
 $('use-here').disabled=!!mut()?.here;
 const rb=$('refresh');rb.disabled=refreshing||work;rb.classList.toggle('spinning',refreshing);rb.setAttribute('aria-label',refreshing?'Checking':'Refresh');
}

async function refresh(){
 if(stateMode())return refreshState();
 if(refreshing||mut()||anc.m.kind==='sending')return;
 refreshing=true;uiSend({type:'drop-choice'});syncControls();const gen=mutations;
 try{const next=await api('/api/overview');if(gen===mutations)adopt(next);message(unreachable()?'No controller can reach the headset right now. Connect it to a phone, PC or Mac in Bluetooth settings, then refresh.':'',unreachable()?'info':false);}catch(e){message(e.message,true);}
 finally{refreshing=false;render();if(!state)syncControls();}
}

// ---- Shared state: GET /api/state long-poll (docs/state-machine.md §3). The page only renders it. ----
// ST.snap is the controller's last snapshot; ST.taps holds a tap whose POST has not answered yet (shown at once) or one
// the controller never took (network). Nothing here infers a connection state of its own.
// ST.link: the link machine (linker); ST.taps: the tap machine (tapper). Each is written only through its function.
const ST={link:'boot',snap:null,at:0,offset:0,seq:null,taps:IDLE,here:null};
function linkSend(e){ST.link=linker(ST.link,e);}
function tapSend(e){ST.taps=tapper(ST.taps,e);}
const STEP={reading:'Checking the headphones'}; // first step shown before the controller answers (contract steps.reading)
const DONE_LINGER=8;
function stateMode(){return ST.link==='live'||ST.link==='lost';}
function serverNow(){return Date.now()/1000+ST.offset;}
function since(){return Date.now()/1000-ST.at;}
function sleepMs(ms){return new Promise(r=>setTimeout(r,ms));}
function rid(){return Math.random().toString(36).slice(2,10);}
async function fetchState(after,wait){
 const q=after==null?'':`?after=${after}&wait=${wait}`;
 // The long-poll waits up to `wait` s on the controller; 10 s more means the link is gone (retried with backoff).
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),((wait||0)+10)*1000);
 const r=await fetch('/api/state'+q,{cache:'no-store',signal:abort.signal}).finally(()=>clearTimeout(timer));
 if(r.status===404)return null;
 if(!r.ok)throw new Error('state '+r.status);
 return r.json();
}
// The switch POST answers at once (an operation is accepted or refused); 15 s means the controller is not answering.
async function postJSON(path,body,ms=15000){
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),ms);
 try{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:abort.signal});return await r.json();}
 catch(e){return null;}finally{clearTimeout(timer);}
}
function enterState(s){linkSend('snapshot');applySnap(s);follow();setInterval(tick,1000);}
async function follow(){
 for(let backoff=1000;;){
  try{
   const s=await fetchState(ST.seq,25);
   if(s===null){linkSend('gone');refresh();return;} // the controller was replaced by an older one
   linkSend('snapshot');backoff=1000;applySnap(s);
  }catch(e){linkSend('error');stateHeader();await sleepMs(backoff);backoff=Math.min(backoff*2,8000);}
 }
}
function applySnap(s){
 ST.snap=s;ST.seq=s.seq;ST.at=Date.now()/1000;ST.offset=(s.now||ST.at)-ST.at;
 if(!ST.here)ST.here=s.here||s.headset?.controllers?.[0]?.id||'pc';
 if(s.operation)tapSend({type:'operation'});
 const prev=state;state=overviewFrom(s);
 if(prev&&noiseShown(anc.m))state.noise=prev.noise; // an ANC write in flight keeps its own pending value
 render();pump(); // an operation that just ended releases the queued intent or held noise value
}
// The legacy overview shape, so ANC, settings and per-row Connect keep their existing code.
function overviewFrom(s){
 const h=s.headset||{},slots=(s.slots||[]).filter(x=>x.address),seen=new Set(slots.map(x=>x.address));
 const all=[...slots,...(s.devices||[]).filter(d=>d.address&&!seen.has(d.address))];
 const roles={};for(const d of all)if(roleIds.includes(d.role))roles[d.role]=d.address;
 return {here:ST.here,reachable:!!h.reachable,cached:!h.reachable,battery:h.battery??null,noise:h.noise||null,roles,observed:null,
  devices:all.map(d=>({address:d.address,name:d.name||d.label||'Device',connected:d.state==='connected'||d.state==='releasing'})),controllers:[]};
}
function serverOp(){
 const o=ST.snap?.operation;if(!o)return null;
 // Done/failed linger 8 s on the controller; hide them here too even if no new state arrives.
 if(o.result&&serverNow()-((o.started_at||0)+(o.result.seconds||0))>DONE_LINGER+1)return null;
 return o;
}
function tapOp(){return ST.taps.kind==='posting'?ST.taps.tap:null;}
function shownOp(){const f=ST.taps.kind==='refused'?ST.taps.fail:null;return tapOp()||serverOp()||(f&&serverNow()-f.at<DONE_LINGER?f:null);}
function opRunning(){const o=tapOp()||serverOp();return !!o&&!o.result;}
function busy(){return !!mut()||(stateMode()&&opRunning());}
function agoText(sec){if(sec==null)return '';if(sec<3)return 'just now';if(sec<60)return `${Math.round(sec)} s ago`;if(sec<3600)return `${Math.round(sec/60)} min ago`;return 'at '+clock(Date.now()/1000-sec);}
function secs(v){return (Math.round(v*10)/10).toFixed(1)+' s';}
function the(role){return role===ST.here?'this '+(role==='phone'?'phone':labels[role]):role==='phone'?'the phone':'the '+(labels[role]||'device');}
const SOURCE_WORDS={desk:'the desk bar',couch:'the couch',web:'the dashboard','mac-popover':'the Mac','mac-menu':'the Mac','android-app':'the phone','android-tile':'the phone',omarchy:'the PC popup',repair:'a re-pair'};

function renderState(){
 stateHeader();renderBattery(state.battery);renderOp();renderStateCups();renderStateDevices();renderStateControllers();renderNoise();syncControls();reportSize();
}
function stateHeader(){
 if(!ST.snap)return;
 const s=ST.snap,h=s.headset||{},count=$('slot-count'),status=$('headset-status'),sub=count.parentElement;
 const n=(s.slots||[]).filter(x=>x.state==='connected').length,age=h.read_age==null?null:h.read_age+since();
 const via=h.via?(h.via===ST.here?'this '+(h.via==='phone'?'phone':labels[h.via]):labels[h.via]||h.via):'a controller';
 $('live-dot').className=ST.link==='lost'?'led checking':opRunning()?'led pending':h.reachable?'led':'led idle';
 const forms=ST.link==='lost'?[['','Reconnecting to the controller…']]
  :!h.reachable?[['','Not reachable'+(age!=null?' · last read '+agoText(age):'')],['','Not reachable']]
  :[[`${n} of 2 connected`,`Live via ${via} · read ${agoText(age)}`],[`${n} of 2`,`Live via ${via} · read ${agoText(age)}`],[`${n} of 2`,`via ${via} · read ${agoText(age)}`],[`${n} of 2`,`via ${via}`],[`${n} of 2`,'Live']];
 const line=parseFloat(getComputedStyle(sub).lineHeight)||18;
 for(const [c,t] of forms){count.textContent=c;count.hidden=!c;status.textContent=t;if(sub.offsetHeight<line*1.5)break;}
}

// Operation card: the steps of the one switch running anywhere (this page, the desk, the couch, the phone…).
function renderOp(){
 const box=$('op'),o=shownOp(),here=hereAddress();
 $('here').hidden=!here||!!o;
 const b=$('use-here'),q=queued(),waiting=q?.action==='switch'&&q.target===ST.here;
 b.classList.remove('pressed');b.classList.toggle('queued',waiting);b.removeAttribute('aria-busy');b.textContent=waiting?QUEUED_HERE:'Use here';
 b.setAttribute('aria-label',waiting?'Cancel the queued Use here':'Use here: move the headphones to '+the(ST.here));
 box.replaceChildren();box.hidden=!o;if(!o)return;
 const res=o.result,choosing=o.phase==='choose'&&!res;
 box.className='op '+(res?(res.ok?'ok':'failed'):choosing?'choosing':'run');
 const target=the(o.target);
 const title=res?(res.ok?'Moved to '+target:'Didn’t move to '+target):'Moving to '+target;
 const head=node('div','op-h');head.append(node('span','op-t',title));
 const time=node('span','op-time num');
 if(res){if(!res.ok)time.textContent=secs(res.seconds||0);}else if(o.started_at){time.dataset.since=String(o.started_at);time.textContent=secs(Math.max(0,serverNow()-o.started_at));}
 head.append(time);box.append(head);
 if(o.source&&o.source!==switchSource()&&SOURCE_WORDS[o.source])box.append(node('div','op-src','Started on '+SOURCE_WORDS[o.source]));
 const steps=(o.steps||[]).filter(x=>x.name!=='choose');
 const failedStep=res&&!res.ok?steps.find(x=>x.state==='failed'):null;
 if(steps.length){
  const ol=node('ol','steps');
  for(const x of steps){
   const li=node('li','step '+x.state);const mk=node('span','mk');
   if(x.state==='done')mk.append(icon('check'));else if(x.state==='failed')mk.append(icon('alert'));else mk.append(node('i',x.state==='active'?'led pending':''));
   const t=node('span','ss num');
   if(x.state==='done'||x.state==='failed'){if(x.seconds!=null)t.textContent=secs(x.seconds);}
   else if(x.state==='active'&&x.since){t.dataset.since=String(x.since);t.textContent=secs(Math.max(0,serverNow()-x.since));}
   li.append(mk,node('span','sl',x.label+(x.state==='active'?'…':'')),t);
   if(x===failedStep&&res.text)li.append(node('span','why',res.text));
   li.setAttribute('aria-label',`${x.label}: ${x.state}${x.seconds!=null?', '+secs(x.seconds):''}`);
   ol.append(li);
  }
  box.append(ol);
 }
 if(choosing){
  const c=node('div','op-choose');c.append(node('p','',MSG.busy));const opts=node('div','opts');
  for(const ch of o.choices||[]){const btn=node('button','btn connect',MSG.replace.replace('{label}',ch.label));btn.type='button';btn.onclick=()=>startSwitch(o.target,ch.address);opts.append(btn);}
  const cancel=node('button','btn ghost','Cancel');cancel.type='button';cancel.onclick=cancelSwitch;opts.append(cancel);
  c.append(opts);box.append(c);
 }else if(res){
  const r=node('div','op-r '+(res.ok?'good':'error'));r.append(icon(res.ok?'check':'alert'));
  if(res.ok)r.append(node('span','',`${res.text||MSG.ok} · ${secs(res.seconds||0)}`));
  else{
   // What the controller's state shows now, so the next move is obvious (the reason is on the failed step).
   const held=(ST.snap?.slots||[]).filter(x=>x.state==='connected').map(x=>x.role===ST.here?'this '+(x.role==='phone'?'phone':labels[x.role]):x.label||x.name);
   r.append(node('span','',failedStep?(held.length?'Still on '+held.join(' and '):'Not connected anywhere'):(res.text||MSG.errors[res.error_key]||MSG.errors.unreachable)));
   const again=node('button','btn connect','Try again');again.type='button';again.onclick=()=>startSwitch(o.target);r.append(again);
  }
  box.append(r);
 }
}
const CHIP={connected:['Connected','ok'],connecting:['Connecting…','pending'],releasing:['Releasing…','pending'],disconnecting:['Disconnecting…','pending'],free:['Free','idle'],unknown:['Unknown','idle'],disconnected:['Not connected','idle']};
function chip(stateName,age){
 const [word,tone]=CHIP[stateName]||CHIP.unknown;const c=node('span','chip '+tone);
 c.append(node('span','led'+(tone==='ok'?'':tone==='pending'?' pending':' idle')));
 const t=node('span','',word);c.append(t);
 if(stateName==='unknown'&&age!=null){const a=node('span','age',' · '+agoText(age+since()));a.dataset.age=String(age);c.append(a);}
 return c;
}
function renderStateCups(){
 const choosing=choosingAddr();
 const cups=$('cups');cups.replaceChildren();cups.classList.add('st');
 const raw=(ST.snap.slots||[]).slice(0,2);while(raw.length<2)raw.push({state:'free'});
 // This page's Connect / Disconnect in flight (POST /api/override) and its queued intent, drawn over the controller's slots.
 const slots=overlaySlots(raw.map(x=>({...x,st:x.state})),mut(),queued());
 slots.forEach((x,i)=>{
  const st=x.st,addr=x.address;
  // the controller's own connecting / releasing marks are in flight too
  const pend=x.pend||(st==='connecting'||st==='releasing'?'flight':null);
  const d=addr?{address:addr,name:addr===x.was?(x.name||x.label):nameOf(addr),role:addr===x.was?x.role:roleOf(addr)}:null;
  const target=choosing&&st==='connected'&&!pend&&d;
  const cup=node(target?'button':'div','cup');
  const head=node('div','state');head.append(pend?pendChip({...x,pend}):chip(st,x.age),node('span','slot',`Slot ${i+1}`));
  if(st==='unknown'&&x.age!=null){const a=node('span','slot-age',agoText(x.age+since()));a.dataset.age=String(x.age);a.dataset.prefix='';head.append(a);}
  cup.append(head);
  if(!d){
   const unk=st==='unknown';cup.classList.add(unk?'unknown':'open');
   const dev=node('div','dev');dev.append(icon('device'));
   cup.append(dev,node('div','name',unk?'Not known':'Open slot'),node('div','tag',unk?'Headset not reachable':'Connect a saved device'),node('div','spacer'));
   cups.append(cup);return;
  }
  const dev=node('div','dev');dev.append(icon(deviceIcon(d)));cup.append(dev,node('div','name',d.name||'Device'));
  if(x.replacing)cup.append(node('div','tag',`Replacing ${nameOf(x.replacing)}`));
  else if(d.role&&d.role===ST.here){const tag=node('div','tag here');tag.append(node('i'),document.createTextNode('This '+(d.role==='phone'?'phone':labels[d.role])));cup.append(tag);}
  else cup.append(node('div','tag',d.role?labels[d.role]||'':''));
  if(pend)pendControl(cup,{...x,pend},d.name);
  else if(target){
   cup.classList.add('target');cup.setAttribute('aria-label',`Replace ${d.name}`);cup.type='button';cup.dataset.live='true';
   cup.onclick=()=>perform({action:'connect',address:choosing,replace:d.address});cup.append(node('span','pill','Replace'));
  }else if(st==='connected'){
   const b=node('button','btn ghost','Disconnect');b.type='button';b.dataset.live='true';b.setAttribute('aria-label',`Disconnect ${d.name}`);
   b.onclick=()=>perform({action:'disconnect',address:d.address});cup.append(b);
  }else{cup.classList.add('stale');cup.append(node('div','spacer'));}
  cups.append(cup);
 });
}
// The chip of a slot drawn as an intended result: a pulsing light in flight, a hollow ring while queued.
function pendChip(x){
 const c=node('span','chip '+(x.pend==='queued'?'queued':'pending'));
 c.append(node('span','led '+(x.pend==='queued'?'queued':'pending')),node('span','',pendWords(x)));return c;
}
function renderStateDevices(){
 const op=mut(),choosing=choosingAddr();
 const list=$('devices');list.replaceChildren();
 const slots=ST.snap.slots||[],inSlot=new Set(slots.filter(x=>x.address).map(x=>x.address));
 const raw=slots.slice(0,2).map(x=>({...x,st:x.state})),inCup=new Set(overlaySlots(raw,op,queued()).filter(x=>x.pend&&x.st==='connecting').map(x=>x.address));
 const rows=(ST.snap.devices||[]).filter(d=>d.address&&!inSlot.has(d.address)&&!(op?.action==='connect'&&op.address===d.address)&&!inCup.has(d.address));
 const q=queued();
 if(!rows.length){
  const empty=node('div','empty');
  if(!inSlot.size)empty.append(node('strong','',ST.snap.headset?.reachable?'No saved devices found':'Headset unavailable'),node('span','',ST.snap.headset?.reachable?'Pair your devices in the headset’s Bluetooth settings.':'Turn on the headset and keep it near one of your controllers.'));
  else empty.append(node('strong','','Every saved device holds a slot'),node('span','','Disconnect one to free a slot.'));
  list.append(empty);return;
 }
 for(const d of rows){
  const row=node('div','device');row.dataset.address=d.address;row.append(icon(deviceIcon(d)));
  const info=node('div','device-info'),role=roleIds.includes(d.role)?d.role:null,choosingHere=choosing===d.address;
  const sub=node('div','s');
  const waiting=!!role&&(q?.action==='switch'&&q.target===role||q?.action==='here'&&role===ST.here);
  if(choosingHere){sub.textContent='Choose a slot above to replace';sub.classList.add('pend');}
  else if(waiting){sub.append(node('span','led queued'),node('span','','Queued · goes next'));sub.classList.add('pend','queued');}
  else if(d.state==='connecting'){sub.textContent='Connecting…';sub.classList.add('pend');}
  else if(d.state==='unknown'){sub.textContent='Unknown · '+agoText((d.age??0)+since());if(d.age!=null){sub.dataset.age=String(d.age);sub.dataset.prefix='Unknown · ';}}
  else sub.textContent=`Saved · not connected${role?' · '+labels[role]:''}`;
  info.append(node('div','n',d.name||d.label||'Device'),sub);row.append(info);
  const b=node('button','btn connect');b.type='button';
  if(role){
   // A role device is a switch target: the controller releases a slot if needed (keeping the phone) and connects it.
   b.textContent=role===ST.here?'Use here':'Move to '+(role==='phone'?'phone':labels[role]);b.dataset.switch='true';
   b.setAttribute('aria-label',`Move the headphones to ${the(role)}`);b.onclick=()=>startSwitch(role);
   if(waiting){b.className='btn connect queued';b.replaceChildren(node('span','ring'),node('span','','Queued · cancel'));b.setAttribute('aria-label',`Cancel the queued move to ${the(role)}`);}
  }else if(choosingHere){b.className='btn connect pressed';b.textContent='Connect';b.setAttribute('aria-pressed','true');b.setAttribute('aria-label',`Connect ${d.name}`);b.onclick=()=>cancelChoice(true);}
  else{b.textContent='Connect';b.dataset.live='true';b.setAttribute('aria-label',`Connect ${d.name}`);b.onclick=()=>connect(d.address);}
  row.append(b);list.append(row);
 }
}
// Per controller: whether it reads the headset now, or why not (state-machine.md §1 "unreachable": each controller's reason).
function reasonWord(reason){
 const e=String(reason||'');
 if(/ConnectionRefused/.test(e))return 'app not running';
 if(/Timeout|timed out/i.test(e))return 'no answer';
 if(!e||/^Controller unavailable/.test(e))return 'offline';
 return e;
}
function renderStateControllers(){
 const box=$('controllers');box.replaceChildren();box.classList.remove('list');
 const h=ST.snap.headset||{},list=(h.controllers||[]).filter(c=>roleIds.includes(c.id));if(!list.length)return;
 const word=c=>c.state==='here'?'reads the headset':c.state==='available'?'available':reasonWord(c.reason);
 if(h.reachable&&!list.some(c=>c.state==='offline'&&c.reason&&reasonWord(c.reason).length>16)){
  box.append(document.createTextNode('Controllers: '));
  list.forEach((c,i)=>{if(i)box.append(document.createTextNode(' · '));box.append(node('b','',labels[c.id]),document.createTextNode(' '+word(c)));});
 }else{
  box.classList.add('list');box.append(node('div','ctl-h',h.reachable?'Controllers':'No controller reaches the headset'));
  const ul=node('ul');for(const c of list){const li=node('li');li.append(node('b','',labels[c.id]),node('span','',word(c)));ul.append(li);}
  box.append(ul);
 }
}
// A tap on a switch target. A choice inside a running choose phase answers that phase; anything else is an intent.
function startSwitch(target,replace){
 if(!target)return;
 const o=tapOp()||serverOp();
 if(replace&&o&&!o.result&&o.phase==='choose'&&!mut()&&anc.m.kind!=='sending')return startSwitchNow(target,replace,false);
 const q=queued();
 if(!replace&&q&&(q.action==='switch'&&q.target===target||q.action==='here'&&target===ST.here))return cancelQueued(); // same tap again
 if(!replace&&o&&!o.result&&o.target===target)return; // that move is the one running
 act({action:'switch',target,replace:replace||null});
}
async function startSwitchNow(target,replace,fromQueue){
 uiSend({type:'drop-choice'});if(!fromQueue)message('');
 tapSend({type:'tap',tap:{target,phase:'reading',started_at:serverNow(),source:switchSource(),steps:[{name:'reading',label:STEP.reading,state:'active',since:serverNow()}],result:null}});
 render();
 const body={source:switchSource(),request_id:rid(),target};if(replace)body.replace=replace;
 const r=await postJSON('/api/switch',body);
 if(r&&r.operation){tapSend({type:'answered'});ST.snap=foldAccepted(ST.snap,ST.seq,r);}
 else if(!r||r.accepted!==true){const text=r?.error||MSG.errors.unreachable;tapSend({type:'refused',fail:{target,started_at:serverNow(),at:serverNow(),steps:[],result:{ok:false,text,seconds:0}}});}
 else tapSend({type:'answered'});
 render();pump();
}
async function cancelSwitch(){await postJSON('/api/switch/cancel',{source:switchSource()});}
async function refreshState(){
 // A fresh headset read: the controller folds it into the state the long-poll delivers.
 if(refreshing||busy())return;refreshing=true;syncControls();
 try{await api('/api/overview');}catch(e){message(e.message,true);}finally{refreshing=false;syncControls();}
}
function tick(){
 if(!stateMode()||!ST.snap)return;
 stateHeader();
 document.querySelectorAll('[data-since]').forEach(el=>{el.textContent=secs(Math.max(0,serverNow()-Number(el.dataset.since)));});
 document.querySelectorAll('[data-age]').forEach(el=>{const t=agoText(Number(el.dataset.age)+since());el.textContent=el.dataset.prefix!=null?el.dataset.prefix+t:' · '+t;});
 const shown=!$('op').hidden,want=!!shownOp();if(shown!==want)render();
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
setInterval(()=>{if(!stateMode()&&state&&live()&&!mut())headerStatus($('slot-count').textContent.split(' connected')[0]);},30000);
new ResizeObserver(()=>{if(stateMode())stateHeader();else if(state)headerStatus($('slot-count').textContent.split(' connected')[0]);}).observe(document.querySelector('.top'));

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
(async()=>{
 try{const cached=await api('/api/cached');if(cached?.here)ST.here=cached.here;if(cached&&cached.devices&&cached.devices.length){adopt(cached);render();}}catch(e){}
 // The shared state machine when the controller has it; the old overview polling only on a 404 (older controller) or Android's bridge.
 if(!window.Android){try{const s=await fetchState(null,0);if(s){enterState(s);return;}}catch(e){}}
 linkSend('gone');await refresh();
})();
