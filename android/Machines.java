package local.bose.connections;
import org.json.*;
import java.util.*;

/** The input machines of web/app.js (the "machines" block) for the Quick Settings tile and panel (docs/state-machines.md
 2, 5, 6b). Pure: every function takes values and returns a value, no Android types, so tests/android/MachinesTest.java
 runs the shared tables of tests/machine-tables.json against them. A state is a small JSONObject with a "kind", as in the
 dashboard; an event a state does not take returns the same state. */
final class Machines {
 private Machines(){}
 static final JSONObject IDLE=o("kind","idle");
 /** An object from key/value pairs; a null value leaves the key out unless it is kept as JSON null by the caller. */
 static JSONObject o(Object... kv){JSONObject r=new JSONObject();try{for(int i=0;i<kv.length;i+=2)r.put((String)kv[i],kv[i+1]==null?JSONObject.NULL:kv[i+1]);}catch(JSONException e){throw new IllegalStateException(e);}return r;}
 static String kind(JSONObject s){return s==null?"idle":s.optString("kind","idle");}
 static boolean is(JSONObject s,String kind){return kind(s).equals(kind);}
 static Object val(JSONObject s,String key){Object v=s==null?null:s.opt(key);return v==JSONObject.NULL?null:v;}
 static String str(JSONObject s,String key){Object v=val(s,key);return v==null?"":v.toString();}

 /** 2. Interaction: idle | choosing{address} (both slots full: pick one to replace) | offer{slots} (Use here was busy:
  Replace per slot) | mutating{action,address,replace,label,here} (the change in flight). */
 static JSONObject interact(JSONObject s,JSONObject e){
  String k=kind(s);
  switch(e.optString("type")){
   case "pick":if(k.equals("mutating"))return s;return k.equals("choosing")&&str(s,"address").equals(e.optString("address"))?IDLE:o("kind","choosing","address",e.optString("address"));
   case "cancel":return k.equals("choosing")||k.equals("offer")?IDLE:s;
   case "drop-choice":return k.equals("choosing")?IDLE:s;
   case "start":if(k.equals("mutating"))return s;
    return o("kind","mutating","action",e.optString("action"),"address",e.optString("address"),"replace",nonEmpty(val(e,"replace")),"label",nonEmpty(val(e,"label")),"here",e.optBoolean("here"));
   case "busy":return k.equals("mutating")&&s.optBoolean("here")?o("kind","offer","slots",e.optJSONArray("slots")==null?new JSONArray():e.optJSONArray("slots")):s;
   case "settled":return k.equals("mutating")?IDLE:s;
  }
  return s;
 }
 static Object nonEmpty(Object v){return v==null||"".equals(v)?null:v;}

 /** 5. Noise writer: idle | waiting{queued} (throttle gap) | held{queued} (a change runs: sent when it ends) |
  sending{sent,queued}. The newest input is always the one sent next. */
 static JSONObject noiser(JSONObject s,JSONObject e){
  String k=kind(s);
  switch(e.optString("type")){
   case "input":return k.equals("sending")?o("kind","sending","sent",val(s,"sent"),"queued",val(e,"value")):o("kind",k.equals("held")?"held":"waiting","queued",val(e,"value"));
   case "hold":return k.equals("waiting")?o("kind","held","queued",val(s,"queued")):s;
   case "resume":return k.equals("held")?o("kind","waiting","queued",val(s,"queued")):s;
   case "drop":return k.equals("held")?IDLE:s;
   case "send":return k.equals("waiting")?o("kind","sending","sent",val(s,"queued"),"queued",null):s;
   case "ok":if(!k.equals("sending"))return s;return val(s,"queued")!=null?o("kind","waiting","queued",val(s,"queued")):IDLE;
   case "fail":return IDLE;
  }
  return s;
 }
 /** The newest noise input ({level, enabled}), or null when idle: then the verified headset value shows. */
 static JSONObject noiseShown(JSONObject s){if(is(s,"idle"))return null;Object v=val(s,"queued");if(v==null)v=val(s,"sent");return v instanceof JSONObject?(JSONObject)v:null;}

 /** 6b. Intent queue: idle | queued{intent}. Latest wins; the same intent again cancels it; release hands it on. */
 static String intentKey(JSONObject i){return i==null?"":str(i,"action")+"|"+str(i,"address")+"|"+str(i,"replace")+"|"+str(i,"target");}
 static JSONObject intents(JSONObject s,JSONObject e){
  switch(e.optString("type")){
   case "hold":return is(s,"queued")&&intentKey(s.optJSONObject("intent")).equals(intentKey(e.optJSONObject("intent")))?IDLE:o("kind","queued","intent",e.optJSONObject("intent"));
   case "cancel":case "release":return IDLE;
  }
  return s;
 }
 /** What runs next, one request toward the controller at a time: wait | hold-noise | intent | resume-noise | drop-noise |
  noise | idle. change: a connection change or switch of this client is in flight. */
 static String schedule(boolean change,JSONObject noise,JSONObject intent,boolean live){
  String n=kind(noise);
  if(change)return n.equals("waiting")?"hold-noise":"wait";
  if(n.equals("sending"))return "wait";
  if(is(intent,"queued"))return "intent";
  if(n.equals("held"))return live?"resume-noise":"drop-noise";
  if(n.equals("waiting"))return "noise";
  return "idle";
 }

 /** The intended result drawn over the verified slots: the change in flight (pend "flight") and the queued intent (pend
  "queued"). slots: [{address|null, st}] with st connected | free. Pure: the verified list is never changed. */
 static List<JSONObject> overlaySlots(List<JSONObject> slots,JSONObject flight,JSONObject queued){
  List<JSONObject> out=new ArrayList<>();
  for(JSONObject s:slots)out.add(o("address",val(s,"address"),"st",str(s,"st"),"was",val(s,"address"),"pend",null,"replacing",null,"here",false));
  Object[][] layers={{flight,"flight"},{queued,"queued"}};
  for(Object[] layer:layers){
   JSONObject a=(JSONObject)layer[0];String how=(String)layer[1];
   if(a==null||str(a,"address").isEmpty())continue;String addr=str(a,"address"),action=str(a,"action");
   if(action.equals("disconnect")){for(JSONObject s:out)if(addr.equals(str(s,"address"))&&str(s,"st").equals("connected")&&val(s,"pend")==null){put(s,"st","disconnecting");put(s,"pend",how);break;}continue;}
   if(!action.equals("connect")&&!action.equals("here"))continue;
   boolean holds=false;for(JSONObject s:out)if(addr.equals(str(s,"address"))&&(str(s,"st").equals("connected")||str(s,"st").equals("connecting")))holds=true;
   if(holds)continue;
   String replace=str(a,"replace");int i=-1;
   for(int j=0;j<out.size()&&i<0;j++){JSONObject s=out.get(j);if(replace.isEmpty()?str(s,"st").equals("free")&&val(s,"pend")==null:replace.equals(str(s,"address"))&&!str(s,"st").equals("free"))i=j;}
   for(int j=0;j<out.size()&&i<0&&replace.isEmpty();j++)if(str(out.get(j),"st").equals("disconnecting"))i=j;
   if(i<0)continue;
   JSONObject old=out.get(i);
   out.set(i,o("address",addr,"st","connecting","was",val(old,"was"),"pend",how,"here",a.optBoolean("here"),"replacing",!replace.isEmpty()?replace:str(old,"st").equals("disconnecting")?val(old,"address"):null));
  }
  return out;
 }
 static void put(JSONObject o,String k,Object v){try{o.put(k,v);}catch(JSONException e){throw new IllegalStateException(e);}}
}
