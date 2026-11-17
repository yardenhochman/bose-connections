// Transition tables of the dashboard's pure machines (web/app.js, the "machines" block; docs/state-machines.md 2-5).
// Run: node tests/web_machines.cjs (tests/test_web_machines.py runs it under unittest). No DOM, no network.
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const block=src.slice(src.indexOf('// ---- machines:begin'),src.indexOf('// ---- machines:end'));
assert(block.length>100,'machines block not found in web/app.js');
const M={};vm.runInNewContext(block+';Object.assign(M,{IDLE,interact,tapper,foldAccepted,linker,noiser,noiseShown,intents,intentKey,schedule,overlaySlots});',{M});
const {IDLE,interact,tapper,foldAccepted,linker,noiser,noiseShown,intents,intentKey,schedule,overlaySlots}=M;
const tables=JSON.parse(fs.readFileSync(path.join(__dirname,'machine-tables.json'),'utf8'));
// A shared table names values by key (tests/machine-tables.json); resolve them into objects.
function resolve(t,o){if(typeof o==='string'&&t.values&&o in t.values)return t.values[o];if(Array.isArray(o))return o.map(x=>resolve(t,x));if(o&&typeof o==='object'){const r={};for(const [k,v] of Object.entries(o))r[k]=resolve(t,v);return r;}return o;}
function runTable(name,fn){const t=tables[name];for(const [from,ev,to] of t.rows)eq(fn(resolve(t,t.states[from]),resolve(t,t.events[ev])),resolve(t,t.states[to]),`${name} ${from} --${ev}->`);}
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
runTable('interact',interact); // the shared table (also run against BoseModel.interactNext, Machines.java and Machines.h)
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

// 5. Noise writer: the shared table (also run against BoseModel.noiseNext by tests/bose_model.qml).
runTable('noiser',noiser);
const v3={level:3,enabled:true},v5={level:5,enabled:true};
const NS={idle:IDLE,waiting:{kind:'waiting',queued:v3},held:{kind:'held',queued:v3},sending:{kind:'sending',sent:v3,queued:null},sendingQ:{kind:'sending',sent:v3,queued:v5}};
eq([noiseShown(NS.idle),noiseShown(NS.waiting),noiseShown(NS.held),noiseShown(NS.sending),noiseShown(NS.sendingQ)],[null,v3,v3,v3,v5],'shown value: newest input, held included, null when idle');
// A burst of slider releases sends the first at once and only the last afterwards.
let s=IDLE;const sent=[];
for(const lvl of [6,5,4,3]){s=noiser(s,{type:'input',value:{level:lvl,enabled:true}});if(s.kind==='waiting'&&!sent.length){sent.push(s.queued.level);s=noiser(s,{type:'send'});}}
s=noiser(s,{type:'ok'});sent.push(s.queued.level);s=noiser(noiser(s,{type:'send'}),{type:'ok'});
eq([sent,s],[[6,3],IDLE],'coalesced burst: 6 then 3, then idle');

// 6. Intent queue: the shared table (also run against BoseModel.intentNext).
runTable('intents',intents);
eq(intentKey({action:'connect',address:'BB',label:'x',here:false}),intentKey({action:'connect',address:'BB'}),'the key ignores labels');
let q=IDLE;
q=intents(q,{type:'hold',intent:{action:'disconnect',address:'AA'}});q=intents(q,{type:'hold',intent:{action:'connect',address:'BB'}});
q=intents(q,{type:'hold',intent:{action:'switch',target:'mac'}});
eq(q,{kind:'queued',intent:{action:'switch',target:'mac'}},'latest wins: three taps leave only the last');
eq(intents(q,{type:'hold',intent:{action:'switch',target:'mac'}}),IDLE,'the same tap again cancels the queued intent');

// Scheduler: the shared table, then sequences.
for(const [change,noise,intent,live,want] of tables.schedule.rows)
 eq(schedule({change,noise:{kind:noise,queued:v3},intent:{kind:intent},live}),want,`schedule change=${change} noise=${noise} intent=${intent} live=${live}`);
// ANC queued behind a switch: input while a switch runs is held, the newest value wins, it goes when the switch ends.
{let m=IDLE,change=true;const step=()=>{const d=schedule({change,noise:m,intent:IDLE,live:true});if(d==='hold-noise')m=noiser(m,{type:'hold'});if(d==='resume-noise')m=noiser(m,{type:'resume'});return d;};
 m=noiser(m,{type:'input',value:v3});step();eq(m,{kind:'held',queued:v3},'ANC during a switch: held, not sent');
 m=noiser(m,{type:'input',value:v5});step();eq(m,{kind:'held',queued:v5},'ANC during a switch: newest held value wins');
 change=false;eq(step(),'resume-noise','switch ended: the held value resumes');eq(schedule({change,noise:m,intent:IDLE,live:true}),'noise','then it is sent');
 m=noiser(m,{type:'send'});eq(m,{kind:'sending',sent:v5,queued:null},'the final value is the one sent');}
// ANC held but the switch ended with the headset out of reach: revert (drop), never sent.
{let m=noiser(noiser(IDLE,{type:'input',value:v3}),{type:'hold'});eq(schedule({change:false,noise:m,intent:IDLE,live:false}),'drop-noise','held + unreachable: drop');
 m=noiser(m,{type:'drop'});eq([m,noiseShown(m)],[IDLE,null],'dropped: the display falls back to the verified value');}
// A queued intent goes before a waiting noise value, and that value is then held behind it.
{let m=noiser(IDLE,{type:'input',value:v3}),i={kind:'queued',intent:{action:'disconnect',address:'AA'}};
 eq(schedule({change:false,noise:m,intent:i,live:true}),'intent','intent first');i=intents(i,{type:'release'});
 eq(schedule({change:true,noise:m,intent:i,live:true}),'hold-noise','noise waits behind the released intent');}
// Stale reply after an optimistic change: an ok for an older value never replaces the newer queued one.
{let m=noiser(noiser(noiser(IDLE,{type:'input',value:v3}),{type:'send'}),{type:'input',value:v5});
 m=noiser(m,{type:'ok'});eq(noiseShown(m),v5,'late ok for 3 keeps 5 shown');}

// Overlay: the intended result over the verified slots.
const A2='AA',B2='BB',C2='CC';
const two=[{address:A2,st:'connected'},{address:B2,st:'connected'}],one=[{address:A2,st:'connected'},{address:null,st:'free'}];
const ov=(slots,f,qd)=>overlaySlots(slots,f,qd).map(s=>[s.address,s.st,s.pend,s.replacing]);
eq(ov(one,null,null),[[A2,'connected',null,null],[null,'free',null,null]],'nothing pending: verified as is');
eq(ov(one,{action:'connect',address:C2},null),[[A2,'connected',null,null],[C2,'connecting','flight',null]],'connect in flight fills the free slot');
eq(ov(two,{action:'disconnect',address:B2},null),[[A2,'connected',null,null],[B2,'disconnecting','flight',null]],'disconnect in flight');
eq(ov(two,{action:'disconnect',address:B2},{action:'connect',address:C2}),[[A2,'connected',null,null],[C2,'connecting','queued',B2]],'queued connect takes the slot a disconnect in flight frees');
eq(ov(two,{action:'connect',address:C2,replace:A2},{action:'disconnect',address:B2}),[[C2,'connecting','flight',A2],[B2,'disconnecting','queued',null]],'replace in flight plus a queued disconnect');
eq(ov(two,null,{action:'connect',address:C2}),[[A2,'connected',null,null],[B2,'connected',null,null]],'queued connect with no slot to take: nothing drawn (it asks on release)');
eq(ov(one,null,{action:'here',address:C2,here:true}).map(s=>s.slice(0,3)),[[A2,'connected',null],[C2,'connecting','queued']],'queued Use here into the free slot');
eq(ov(two,null,{action:'connect',address:A2}),ov(two,null,null),'a device already in a slot is not drawn twice');
eq(ov(one,null,{action:'switch',target:'mac'}),ov(one,null,null),'a queued switch target is not drawn in a cup (the controller picks the slot)');
// Stale reply after an optimistic change: the verified layer underneath changes, the queued intent stays drawn.
{const stale=[{address:A2,st:'connected'},{address:B2,st:'connected'}],fresh=[{address:A2,st:'connected'},{address:null,st:'free'}];const qd={action:'disconnect',address:A2};
 eq(ov(stale,null,qd)[0],[A2,'disconnecting','queued',null],'queued disconnect drawn');eq(ov(fresh,null,qd)[0],[A2,'disconnecting','queued',null],'a newer or older read underneath keeps it drawn');}
const verified=[{address:A2,st:'connected'}];overlaySlots(verified,{action:'disconnect',address:A2},null);eq(verified,[{address:A2,st:'connected'}],'overlay never writes the verified slots');
console.log(`web machines: ${n} transitions checked`);
