// Transition tables of the dashboard's pure machines (web/app.js, the "machines" block; docs/state-machines.md 2-5).
// Run: node tests/web_machines.cjs (tests/test_web_machines.py runs it under unittest). No DOM, no network.
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const block=src.slice(src.indexOf('// ---- machines:begin'),src.indexOf('// ---- machines:end'));
assert(block.length>100,'machines block not found in web/app.js');
const M={};vm.runInNewContext(block+';Object.assign(M,{IDLE,interact,tapper,foldAccepted,linker,noiser,noiseShown});',{M});
const {IDLE,interact,tapper,foldAccepted,linker,noiser,noiseShown}=M;
let n=0;const eq=(a,b,t)=>{assert.deepStrictEqual(JSON.parse(JSON.stringify(a)),JSON.parse(JSON.stringify(b)),t);n++;};

// 2. Interaction: every state x every event.
const A='AA:AA:AA:AA:AA:AA',B='BB:BB:BB:BB:BB:BB';
const S={idle:IDLE,choosing:{kind:'choosing',address:A},offer:{kind:'offer',slots:[{address:B,label:'Mac'}]},
 mutating:{kind:'mutating',action:'connect',address:A,replace:null,label:null,here:false},
 here:{kind:'mutating',action:'connect',address:A,replace:B,label:'Mac',here:true}};
const E={pickA:{type:'pick',address:A},pickB:{type:'pick',address:B},cancel:{type:'cancel'},drop:{type:'drop-choice'},
 start:{type:'start',action:'disconnect',address:B},busy:{type:'busy',slots:[{address:B,label:'Mac'}]},settled:{type:'settled'},junk:{type:'nope'}};
const started={kind:'mutating',action:'disconnect',address:B,replace:null,label:null,here:false};
const T={
 idle:{pickA:S.choosing,pickB:{kind:'choosing',address:B},cancel:IDLE,drop:IDLE,start:started,busy:IDLE,settled:IDLE,junk:IDLE},
 choosing:{pickA:IDLE,pickB:{kind:'choosing',address:B},cancel:IDLE,drop:IDLE,start:started,busy:S.choosing,settled:S.choosing,junk:S.choosing},
 offer:{pickA:S.choosing,pickB:{kind:'choosing',address:B},cancel:IDLE,drop:S.offer,start:started,busy:S.offer,settled:S.offer,junk:S.offer},
 mutating:{pickA:S.mutating,pickB:S.mutating,cancel:S.mutating,drop:S.mutating,start:S.mutating,busy:S.mutating,settled:IDLE,junk:S.mutating},
 here:{pickA:S.here,pickB:S.here,cancel:S.here,drop:S.here,start:S.here,busy:{kind:'offer',slots:[{address:B,label:'Mac'}]},settled:IDLE,junk:S.here}};
for(const [from,row] of Object.entries(T))for(const [ev,to] of Object.entries(row))eq(interact(S[from],E[ev]),to,`interact ${from} --${ev}->`);
eq(interact(S.here,{type:'busy'}),{kind:'offer',slots:[]},'busy without slots offers none');
// The contradiction the old flags allowed (a Use here offer and a slot choice at once) is unrepresentable:
eq(interact(S.offer,E.pickA).kind,'choosing','picking a device closes the Use here offer');

// 3. Tap on the shared state.
const tap={target:'pc'},fail={at:1};
const TS={idle:IDLE,posting:{kind:'posting',tap},refused:{kind:'refused',fail}};
const TE={tap:{type:'tap',tap},answered:{type:'answered'},refused:{type:'refused',fail},operation:{type:'operation'},junk:{type:'x'}};
const TT={idle:{tap:TS.posting,answered:IDLE,refused:IDLE,operation:IDLE,junk:IDLE},
 posting:{tap:TS.posting,answered:IDLE,refused:TS.refused,operation:TS.posting,junk:TS.posting},
 refused:{tap:TS.posting,answered:TS.refused,refused:TS.refused,operation:IDLE,junk:TS.refused}};
for(const [from,row] of Object.entries(TT))for(const [ev,to] of Object.entries(row))eq(tapper(TS[from],TE[ev]),to,`tapper ${from} --${ev}->`);

// foldAccepted: a POST /api/switch reply never replaces a newer snapshot's operation.
const opA={id:'a',started_at:100},opB={id:'b',started_at:200};
eq(foldAccepted({operation:null},5,{operation:opA,seq:4}).operation,opA,'no operation in the snapshot: show the reply');
eq(foldAccepted({operation:opA},5,{operation:opA,seq:6}).operation,opA,'reply newer: take it');
eq(foldAccepted({operation:opB},9,{operation:opA,seq:4}).operation,opB,'late reply for an older tap keeps the newer operation');
eq(foldAccepted({operation:opA},9,{operation:opB,seq:2}).operation,opB,'controller restarted (lower seq) but a newer operation: take it');
eq(foldAccepted({operation:opA},9,{operation:opA,seq:4}).operation,opA,'same operation, older reply: keep the snapshot');
eq(foldAccepted({operation:opA},5,{accepted:false}).operation,opA,'a reply without an operation changes nothing');

// 4. Link.
const LT={boot:{snapshot:'live',error:'legacy',gone:'legacy',junk:'boot'},live:{snapshot:'live',error:'lost',gone:'legacy',junk:'live'},
 lost:{snapshot:'live',error:'lost',gone:'legacy',junk:'lost'},legacy:{snapshot:'legacy',error:'legacy',gone:'legacy',junk:'legacy'}};
for(const [from,row] of Object.entries(LT))for(const [ev,to] of Object.entries(row))eq(linker(from,ev),to,`linker ${from} --${ev}->`);

// 5. Noise writer.
const v3={level:3,enabled:true},v5={level:5,enabled:true},v0={level:5,enabled:false};
const NS={idle:IDLE,waiting:{kind:'waiting',queued:v3},sending:{kind:'sending',sent:v3,queued:null},sendingQ:{kind:'sending',sent:v3,queued:v5}};
const NE={input:{type:'input',value:v0},send:{type:'send'},ok:{type:'ok'},fail:{type:'fail'},junk:{type:'x'}};
const NT={idle:{input:{kind:'waiting',queued:v0},send:IDLE,ok:IDLE,fail:IDLE,junk:IDLE},
 waiting:{input:{kind:'waiting',queued:v0},send:NS.sending,ok:NS.waiting,fail:IDLE,junk:NS.waiting},
 sending:{input:{kind:'sending',sent:v3,queued:v0},send:NS.sending,ok:IDLE,fail:IDLE,junk:NS.sending},
 sendingQ:{input:{kind:'sending',sent:v3,queued:v0},send:NS.sendingQ,ok:{kind:'waiting',queued:v5},fail:IDLE,junk:NS.sendingQ}};
for(const [from,row] of Object.entries(NT))for(const [ev,to] of Object.entries(row))eq(noiser(NS[from],NE[ev]),to,`noiser ${from} --${ev}->`);
eq([noiseShown(NS.idle),noiseShown(NS.waiting),noiseShown(NS.sending),noiseShown(NS.sendingQ)],[null,v3,v3,v5],'shown value: newest input, null when idle');
// A burst of slider releases sends the first at once and only the last afterwards.
let s=IDLE;const sent=[];
for(const lvl of [6,5,4,3]){s=noiser(s,{type:'input',value:{level:lvl,enabled:true}});if(s.kind==='waiting'&&!sent.length){sent.push(s.queued.level);s=noiser(s,{type:'send'});}}
s=noiser(s,{type:'ok'});sent.push(s.queued.level);s=noiser(noiser(s,{type:'send'}),{type:'ok'});
eq([sent,s],[[6,3],IDLE],'coalesced burst: 6 then 3, then idle');
console.log(`web machines: ${n} transitions checked`);
