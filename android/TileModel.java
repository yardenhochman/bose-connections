package local.bose.connections;
import org.json.*;
import java.util.*;

/** The Quick Settings tile and panel without Android types (docs/state-machines.md 7): the verified snapshot plus the
 machines of Machines.java, and the one scheduler (drain) that decides what goes to the controller next. BoseTileService
 draws it and supplies the Host; tests/android/TileModelTest.java drives it with a fake Host. Every method runs on one
 thread (the main looper); replies come back on it too.

 The input rule: an input changes the model at once and never waits for work in progress. A connection tap during other
 work becomes the one queued intent (latest wins, the same tap again cancels it); a noise value is held behind a change
 and written one at a time, 250 ms apart, newest value last; Refresh during work reads once it ends; a failure reverts
 to the verified state and says so. At most one /api/override or /api/switch request is open at a time. */
final class TileModel {
 interface Reply{void done(JSONObject json,String error);}
 interface Host{
  /** path: /api/override, /api/switch (the tile's one-tap switch) or /api/overview. Writes and reads run on separate
   threads, so a read never waits behind a switch of up to 150 s. The reply arrives on the main thread. */
  void request(String path,JSONObject body,Reply reply);
  Object later(Runnable r,long ms);
  void cancel(Object handle);
  long now();
  void changed();
  /** A busy one-tap switch from the tile offers Replace per slot in the panel. */
  void openPanel();
 }
 static final String NOISE_DROPPED="Noise change not sent: the headphones aren’t reachable now";
 static final long NOISE_GAP_MS=250,NOTE_OK_MS=8000,NOTE_ERROR_MS=30000;
 final Host host;
 JSONObject snapshot=new JSONObject();
 JSONObject ui=Machines.IDLE;      // interact: written only by uiSend
 JSONObject anc=Machines.IDLE;     // noiser: written only by noiseSend
 JSONObject queue=Machines.IDLE;   // intents: written only by queueSend
 boolean reading=false,refreshWanted=false;
 int changes=0;                    // changes started or ended: a read sent before the latest one is stale
 long lastRead=0,ancLastStart=-NOISE_GAP_MS;
 String notice="";boolean noticeError=false;
 String tileNote="";long tileNoteUntil=0;Object noteTimer,gapTimer;
 TileModel(Host host){this.host=host;}

 // ---- Machines ----
 void uiSend(JSONObject e){ui=Machines.interact(ui,e);}
 void noiseSend(JSONObject e){anc=Machines.noiser(anc,e);}
 void queueSend(JSONObject e){queue=Machines.intents(queue,e);}
 static JSONObject ev(Object... kv){return Machines.o(kv);}

 // ---- Readers ----
 boolean live(){return snapshot.optBoolean("reachable")&&!snapshot.optBoolean("cached");}
 JSONArray devices(){JSONArray l=snapshot.optJSONArray("devices");return l==null?new JSONArray():l;}
 int connectedCount(){int n=0;JSONArray ds=devices();for(int i=0;i<ds.length();i++){JSONObject d=ds.optJSONObject(i);if(d!=null&&d.optBoolean("connected"))n++;}return n;}
 JSONObject device(String address){JSONArray ds=devices();for(int i=0;i<ds.length();i++){JSONObject d=ds.optJSONObject(i);if(d!=null&&address!=null&&address.equals(d.optString("address")))return d;}return null;}
 static String name(JSONObject d){if(d==null)return "";String n=d.optString("name");return n.isEmpty()?d.optString("address"):n;}
 String hereAddress(){JSONObject roles=snapshot.optJSONObject("roles");return roles==null?"":roles.optString(snapshot.optString("here","phone"));}
 /** The change in flight (interact mutating), or null. */
 JSONObject pending(){return Machines.is(ui,"mutating")?ui:null;}
 /** The saved device waiting for a slot choice (interact choosing), or null. */
 JSONObject replacing(){if(!Machines.is(ui,"choosing"))return null;JSONObject d=device(Machines.str(ui,"address"));return d!=null?d:Machines.o("address",Machines.str(ui,"address"),"name",Machines.str(ui,"address"));}
 /** Use here was busy: [{address,label}] to replace (interact offer), or null. */
 JSONArray offer(){return Machines.is(ui,"offer")?ui.optJSONArray("slots"):null;}
 JSONObject queued(){return Machines.is(queue,"queued")?queue.optJSONObject("intent"):null;}
 boolean queuedHere(){JSONObject q=queued();return q!=null&&"here".equals(q.optString("action"));}
 boolean switching(){JSONObject p=pending();return p!=null&&p.optBoolean("here");}
 boolean changeRunning(){return pending()!=null;}
 boolean workRunning(){return changeRunning()||Machines.is(anc,"sending");}
 /** The noise value on screen: the newest input while one is pending, else the verified headset value. */
 JSONObject noiseShown(){JSONObject v=Machines.noiseShown(anc);return v!=null?v:snapshot.optJSONObject("noise");}
 /** Controls stay usable during work: a tap then queues. Only no live headset with nothing running disables them. */
 boolean canMutate(){return live()||changeRunning();}
 boolean canNoise(){return snapshot.optJSONObject("noise")!=null&&(live()||changeRunning());}
 /** The verified slots in their cups (order: slotOrder), with the change in flight and the queued intent drawn over. */
 List<JSONObject> slots(String[] order){
  List<JSONObject> base=new ArrayList<>();
  for(int i=0;i<2;i++){JSONObject d=order[i]==null?null:device(order[i]);base.add(d!=null&&d.optBoolean("connected")?Machines.o("address",order[i],"st","connected"):Machines.o("address",null,"st","free"));}
  return Machines.overlaySlots(base,pending(),queued());
 }

 // ---- Tile ----
 String tileSubtitle(){
  JSONObject p=pending();
  if(p!=null&&p.optBoolean("here"))return Machines.str(p,"label").isEmpty()?Switcher.MESSAGES.get("pending"):Switcher.MESSAGES.get("replacing").replace("{label}",Machines.str(p,"label"));
  if(!tileNote.isEmpty()&&host.now()<tileNoteUntil)return tileNote;
  if(queuedHere())return "Moves here next · tap to cancel";
  if(p!=null)return "disconnect".equals(p.optString("action"))?"Disconnecting…":"Connecting…";
  if(Machines.is(anc,"held"))return "ANC change waits for the switch";
  if(!Machines.is(anc,"idle"))return "Updating…";
  boolean cached=snapshot.optBoolean("cached");
  if(!cached&&!snapshot.optBoolean("reachable"))return snapshot.has("reachable")?"Unavailable":"Checking…";
  if(cached&&devices().length()==0)return reading?"Checking…":"Unavailable";
  JSONObject noise=snapshot.optJSONObject("noise");
  return connectedCount()+" of 2"+(noise==null?"":noise.optBoolean("enabled")?" · ANC "+noise.optInt("level"):" · ANC off");
 }
 /** The tile's subtitle note until it expires; a newer note cancels the older one's refresh. */
 void note(String text,long ms){
  tileNote=text;tileNoteUntil=host.now()+ms;
  if(noteTimer!=null)host.cancel(noteTimer);
  noteTimer=host.later(()->{noteTimer=null;host.changed();},ms+50);
 }
 void clearNote(){tileNote="";tileNoteUntil=0;if(noteTimer!=null){host.cancel(noteTimer);noteTimer=null;}}
 /** A tile tap: move the headset to this phone. During other work it queues, and the subtitle says so at once; a second
  tap cancels it. During its own switch it changes nothing: the subtitle already says Connecting…. */
 void tileTap(){if(switching())return;switchHere(null);}

 // ---- Inputs ----
 void say(String text,boolean error){notice=text==null?"":text;noticeError=error;}
 /** Every connection input goes through act: at once when nothing else runs, else the one queued intent. */
 void act(JSONObject intent){
  if(workRunning()){uiSend(ev("type","drop-choice"));queueSend(ev("type","hold","intent",intent));host.changed();return;}
  if(queued()!=null)queueSend(ev("type","cancel"));
  runIntent(intent,false);
 }
 void cancelQueued(){queueSend(ev("type","cancel"));host.changed();}
 void connect(JSONObject d){
  if(d==null||!canMutate())return;
  say("",false);
  // A slot that a disconnect in flight frees counts as open. With both full and a change running, the connect queues and
  // asks for the slot when it is released (the slots may change meanwhile).
  JSONObject p=pending();int leaving=p!=null&&"disconnect".equals(p.optString("action"))?1:0;
  if(connectedCount()-leaving>=2&&!changeRunning()){uiSend(ev("type","pick","address",d.optString("address")));host.changed();return;}
  act(ev("action","connect","address",d.optString("address"),"name",name(d)));
 }
 void replaceSlot(String slotAddress){
  JSONObject d=replacing();uiSend(ev("type","cancel"));
  if(d==null||slotAddress==null||!canMutate()){host.changed();return;}
  act(ev("action","connect","address",d.optString("address"),"name",name(d),"replace",slotAddress,"replaceName",name(device(slotAddress))));
 }
 void cancelChoice(){uiSend(ev("type","cancel"));say("",false);host.changed();}
 void disconnect(JSONObject d){
  if(d==null||!canMutate())return;
  say("",false);uiSend(ev("type","drop-choice"));
  act(ev("action","disconnect","address",d.optString("address"),"name",name(d)));
 }
 /** Use here (tile or panel): one tap moves the headset to this phone; replace is a slot from a busy offer. */
 void switchHere(String replace){
  if(switching())return; // its own request cannot be taken back
  if(replace==null&&queuedHere()){queueSend(ev("type","cancel"));clearNote();host.changed();return;}
  String label="";JSONArray slots=offer();
  if(replace!=null&&slots!=null)for(int i=0;i<slots.length();i++){JSONObject s=slots.optJSONObject(i);if(s!=null&&replace.equals(s.optString("address")))label=s.optString("label");}
  uiSend(ev("type","cancel"));clearNote();
  act(ev("action","here","address",hereAddress(),"replace",replace,"label",label.isEmpty()?null:label,"here",true));
  host.changed();
 }
 void setNoise(int level,boolean enabled){
  if(snapshot.optJSONObject("noise")==null)return;
  if(!canNoise()){say(NOISE_DROPPED,true);host.changed();return;}
  say("",false);noiseSend(ev("type","input","value",ev("level",Math.max(0,Math.min(10,level)),"enabled",enabled)));
  drain();host.changed();
 }
 /** Refresh while work runs is not sent then (it would read a half-made change): it shows at once and runs when the
  work ends. deferred: that later read, which keeps the result line of the work before it. */
 void refresh(){refresh(false);}
 void refresh(boolean deferred){
  if(reading)return;
  if(workRunning()||queued()!=null){refreshWanted=true;host.changed();return;}
  refreshWanted=false;reading=true;final int gen=changes;host.changed();
  host.request("/api/overview",null,(json,error)->{
   reading=false;lastRead=host.now();
   if(json!=null&&gen==changes&&!workRunning())snapshot=json;
   if(error!=null&&(notice.isEmpty()||!deferred))say(error,true);
   host.changed();
  });
 }

 // ---- The scheduler ----
 /** Called whenever work ends or input arrives: the queued intent first, then the noise writer, then a deferred read. */
 void drain(){
  for(int n=0;n<4;n++){
   String d=Machines.schedule(changeRunning(),anc,queue,live());
   if(d.equals("hold-noise")){noiseSend(ev("type","hold"));if(gapTimer!=null){host.cancel(gapTimer);gapTimer=null;}return;}
   if(d.equals("resume-noise")){noiseSend(ev("type","resume"));continue;}
   if(d.equals("drop-noise")){noiseSend(ev("type","drop"));say(NOISE_DROPPED,true);return;}
   if(d.equals("intent")){JSONObject i=queued();queueSend(ev("type","release"));runIntent(i,true);if(workRunning())return;continue;}
   if(d.equals("noise")){pumpNoise();return;}
   if(d.equals("idle")&&refreshWanted)refresh(true);
   return;
  }
 }
 /** A released intent is checked against the verified state first: the slots may have changed while it waited. */
 void runIntent(JSONObject i,boolean fromQueue){
  String action=i.optString("action");
  if(action.equals("here")){switchNow(Machines.str(i,"replace"),Machines.str(i,"label"));return;}
  JSONObject d=device(i.optString("address"));
  if(d==null||!live()){if(fromQueue)say((action.equals("connect")?"Connect":"Disconnect")+" not sent: the headphones aren’t reachable now",true);host.changed();return;}
  if(action.equals("disconnect")){
   if(!d.optBoolean("connected")){say(name(d)+" is already disconnected",false);host.changed();return;}
   mutate(ev("action","disconnect","address",d.optString("address")));return;
  }
  if(d.optBoolean("connected")){say(name(d)+" is already connected",false);host.changed();return;}
  String rep=Machines.str(i,"replace");JSONObject r=rep.isEmpty()?null:device(rep);
  boolean keep=r!=null&&r.optBoolean("connected");
  if(connectedCount()>=2&&!keep){uiSend(ev("type","pick","address",d.optString("address")));host.changed();return;} // ask, never guess
  mutate(keep?ev("action","connect","address",d.optString("address"),"replace",rep):ev("action","connect","address",d.optString("address")));
 }
 void mutate(JSONObject body){
  changes++;say("",false);
  uiSend(ev("type","start","action",body.optString("action"),"address",body.optString("address"),"replace",Machines.val(body,"replace")));
  host.changed();
  JSONObject data=ev("action",body.optString("action"),"address",body.optString("address"),"source","android-tile");
  if(!Machines.str(body,"replace").isEmpty())Machines.put(data,"replace",Machines.str(body,"replace"));
  host.request("/api/override",data,(json,error)->{
   changes++;uiSend(ev("type","settled"));
   if(json!=null&&json.optBoolean("ok")&&json.optBoolean("verified")){
    JSONObject state=json.optJSONObject("state");if(state!=null){snapshot=state;lastRead=host.now();}
    say(json.optString("message","Connection updated"),false);
   }else{say(error!=null?error:json==null?"Controller unavailable":json.optString("error",json.optString("message","Change not verified; refresh before retrying")),true);refreshWanted=true;} // re-read once the queue is done
   host.changed();drain();
  });
 }
 /** One-tap switch (tests/switch-contract.json) through Core.switchHere; busy offers Replace per slot, never guesses. */
 void switchNow(String replace,String label){
  changes++;clearNote();say("",false);
  uiSend(ev("type","start","action","connect","address",hereAddress(),"replace",replace.isEmpty()?null:replace,"label",label.isEmpty()?null:label,"here",true));
  host.changed();
  JSONObject body=replace.isEmpty()?new JSONObject():ev("replace",replace);
  host.request("/api/switch",body,(json,error)->{
   changes++;
   boolean busy=json!=null&&json.optBoolean("busy");
   uiSend(busy?ev("type","busy","slots",json.optJSONArray("slots")==null?new JSONArray():json.optJSONArray("slots")):ev("type","settled"));
   if(json!=null&&json.optBoolean("ok")){JSONObject state=json.optJSONObject("state");if(state!=null&&state.has("devices")&&state.has("reachable")){snapshot=state;lastRead=host.now();}note(Switcher.MESSAGES.get("ok"),NOTE_OK_MS);}
   else if(busy){note(Switcher.MESSAGES.get("busy"),NOTE_ERROR_MS);host.openPanel();}
   else note((json!=null?json.optString("error",Switcher.text("unreachable")):Switcher.text("unreachable"))+Switcher.MESSAGES.get("retry_hint"),NOTE_ERROR_MS);
   host.changed();drain();
  });
 }
 void pumpNoise(){
  if(!Machines.is(anc,"waiting")||changeRunning())return;
  long wait=ancLastStart+NOISE_GAP_MS-host.now();
  if(wait>0){if(gapTimer!=null)host.cancel(gapTimer);gapTimer=host.later(()->{gapTimer=null;drain();host.changed();},wait);return;}
  JSONObject v=anc.optJSONObject("queued"),verified=snapshot.optJSONObject("noise");
  noiseSend(ev("type","send"));
  if(verified!=null&&verified.optBoolean("enabled")==v.optBoolean("enabled")&&(!v.optBoolean("enabled")||verified.optInt("level")==v.optInt("level"))){noiseSend(ev("type","ok"));drain();return;} // already so
  ancLastStart=host.now();changes++;host.changed();
  host.request("/api/override",ev("action","noise","level",v.optInt("level"),"enabled",v.optBoolean("enabled")),(json,error)->{
   changes++;
   boolean ok=json!=null&&json.optBoolean("ok")&&json.optBoolean("verified");
   if(ok)mergeNoise(json);
   noiseSend(ev("type",ok?"ok":"fail"));
   if(!ok)say(error!=null?error:json==null?"Controller unavailable":json.optString("error","Noise cancellation not verified"),true);
   else if(Machines.is(anc,"idle"))say(json.optString("message","Noise cancellation updated"),false);
   host.changed();drain();
  });
 }
 /** Merge only noise/battery (and devices when present): a noise read-back may carry an empty device list. */
 void mergeNoise(JSONObject result){
  JSONObject state=result.optJSONObject("state"),noise=result.optJSONObject("noise");
  try{
   JSONObject next=new JSONObject(snapshot.toString());
   if(state!=null){if(state.optJSONObject("noise")!=null)noise=state.optJSONObject("noise");if(state.has("battery")&&!state.isNull("battery"))next.put("battery",state.get("battery"));
    JSONArray ds=state.optJSONArray("devices");if(ds!=null&&ds.length()>0)next.put("devices",ds);}
   if(noise!=null)next.put("noise",noise);
   snapshot=next;
  }catch(JSONException ignored){/* snapshot keys are plain strings; put cannot fail here */}
 }
}
