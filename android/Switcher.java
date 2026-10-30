package local.bose.connections;
import org.json.*;
import java.io.IOException;
import java.util.*;

/** Tap-to-switch rules of tests/switch-contract.json for "here" = this phone. No Android types, so a JVM test can drive it with a fake mesh. */
public class Switcher {
 static final long DEADLINE_MS=150000;
 static final List<String> SOURCES=Arrays.asList("android-app","android-tile","omarchy","web","mac-menu","mac-popover","desk","couch");
 static final Map<String,String> MESSAGES=new LinkedHashMap<>();
 static{
  MESSAGES.put("pending","Connecting…");MESSAGES.put("replacing","Replacing {label}…");MESSAGES.put("ok","Playing on Bose 700");
  MESSAGES.put("busy","Both slots busy · choose one to replace");MESSAGES.put("replace","Replace {label}");MESSAGES.put("retry_hint"," · tap to retry");
  MESSAGES.put("errors.unreachable","Couldn’t reach the headphones");MESSAGES.put("errors.timeout","Took too long to switch");
  MESSAGES.put("errors.unverified","The headphones didn’t confirm the switch");MESSAGES.put("errors.keep_one","Can’t replace that one: keep a phone, PC or Mac connected");
  MESSAGES.put("errors.no_audio","Connected, but no sound from the headphones");MESSAGES.put("errors.audio_not_moved","Headphones connected, but PC audio didn’t switch");
 }
 static final Map<String,String> LABELS=new HashMap<>();
 static{LABELS.put("phone","Phone");LABELS.put("mac","Mac");LABELS.put("pc","PC");}
 /** The mesh as Core.override sees it: a phone+peers overview (optionally a recent one) and the peer-aware connect/replace machinery. override sets data.via to "local" or "peer:<id>". */
 interface Mesh {JSONObject overview(boolean reuse)throws Exception;JSONObject override(JSONObject data)throws Exception;}
 interface Env {long millis();void log(String line);Map<String,String> roles()throws Exception;}
 /** A failure with a contract error_key; the message is the contract text and detail the raw reason. */
 static class Fail extends IOException {
  final String key,detail;
  Fail(String key,String detail){super(text(key));this.key=key;this.detail=detail;}
 }
 static String text(String key){return key.equals("busy")?MESSAGES.get("busy"):MESSAGES.get("errors."+key);}
 static JSONObject failure(String key,String detail){JSONObject o=new JSONObject();try{o.put("ok",false).put("error_key",key).put("error",text(key)).put("detail",detail==null?"":detail);}catch(JSONException ignored){}return o;}
 static String label(Map<String,String> roles,String address){for(Map.Entry<String,String> e:roles.entrySet())if(address.equalsIgnoreCase(e.getValue()))return LABELS.containsKey(e.getKey())?LABELS.get(e.getKey()):"-";return "-";}
 static String clean(String s,String fallback){return s!=null&&s.matches("[A-Za-z0-9_-]{1,32}")?s:fallback;}
 static String logLine(String source,String id,String target,String replace,String outcome,String via,long ms){
  return String.format(Locale.ROOT,"bose.switch source=%s id=%s target=%s replace=%s outcome=%s via=%s total=%.2fs",SOURCES.contains(source)?source:"-",clean(id,"-"),target,replace,outcome,via,ms/1000.0);
 }
 static Set<String> connected(JSONObject read)throws Exception{Set<String> set=new LinkedHashSet<>();JSONArray ds=read.getJSONArray("devices");for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);if(d.optBoolean("connected"))set.add(d.getString("address").toUpperCase(Locale.ROOT));}return set;}
 static JSONObject ok(JSONObject state)throws Exception{
  JSONObject o=new JSONObject().put("ok",true).put("verified",true).put("message",MESSAGES.get("ok"));if(state!=null)o.put("state",state);return o;
 }
 static boolean known(String key){return key.equals("busy")||MESSAGES.containsKey("errors."+key);}
 /** Moves the headset to this phone through the mesh. Never throws: every outcome is a contract reply, logged once. */
 static JSONObject switchHere(Mesh mesh,Env env,String source,String requestId,String replace){
  long t0=env.millis(),deadline=t0+DEADLINE_MS;JSONObject reply=null;String outcome="ok",replaceLabel="-",via="local";
  try{
   Map<String,String> configured=new HashMap<>();for(Map.Entry<String,String> e:env.roles().entrySet())configured.put(e.getKey(),e.getValue().toUpperCase(Locale.ROOT));
   for(int attempt=0;reply==null;attempt++){
    JSONObject ov=mesh.overview(attempt==0);if(!ov.optBoolean("reachable"))throw new Fail("unreachable","No controller could read the headset");
    JSONArray ds=ov.getJSONArray("devices");Map<String,String> roles=new HashMap<>(configured);JSONObject seen=ov.optJSONObject("roles");
    if(seen!=null)for(Iterator<String> it=seen.keys();it.hasNext();){String k=it.next();if(!roles.containsKey(k))roles.put(k,seen.getString(k).toUpperCase(Locale.ROOT));}
    String here=roles.get("phone");if(here==null)throw new Fail("unreachable","This phone's headset address is not known");
    Set<String> conn=connected(ov);
    if(conn.contains(here)){reply=ok(ov);break;}
    if(attempt>=2)throw new Fail("unverified","Headset did not report this phone connected");
    JSONObject data=new JSONObject().put("action","connect").put("address",here).put("source",source);if(requestId!=null)data.put("request_id",requestId);
    if(conn.size()>=2){
     if(attempt>0)throw new Fail("unverified","Both slots filled while retrying");
     String drop=replace==null?"":replace.toUpperCase(Locale.ROOT);
     if(!conn.contains(drop)){
      JSONArray slots=new JSONArray();for(String a:conn){String name=label(roles,a);if(name.equals("-")){name="Other";for(int i=0;i<ds.length();i++)if(ds.getJSONObject(i).getString("address").equalsIgnoreCase(a))name=ds.getJSONObject(i).optString("name",name);}slots.put(new JSONObject().put("address",a).put("label",name));}
      return finish(env,source,requestId,replaceLabel,"busy",via,t0,new JSONObject().put("ok",false).put("busy",true).put("error_key","busy").put("error",MESSAGES.get("busy")).put("slots",slots));
     }
     Set<String> remaining=new HashSet<>(conn);remaining.remove(drop);Set<String> anchors=new HashSet<>(roles.values());for(int i=0;i<ds.length();i++)if(ds.getJSONObject(i).optBoolean("current"))anchors.add(ds.getJSONObject(i).getString("address").toUpperCase(Locale.ROOT));
     remaining.retainAll(anchors);if(remaining.isEmpty())throw new Fail("keep_one","Dropping "+label(roles,drop)+" would leave no phone, PC or Mac connected");
     replaceLabel=label(roles,drop);data.put("replace",drop);
    }
    JSONObject r=null;
    try{r=mesh.override(data);}catch(Fail f){if(!f.key.equals("unverified")&&!f.key.equals("busy"))throw f;}
    via=data.optString("via","local");
    if(env.millis()>deadline)throw new Fail("timeout","No answer within "+DEADLINE_MS/1000+" s");
    if(r!=null&&r.optBoolean("ok")&&r.optBoolean("verified")){JSONObject state=r.optJSONObject("state");if(state!=null&&state.optJSONArray("devices")!=null&&connected(state).contains(here)){reply=ok(state);break;}}
    else if(r!=null){String key=r.optString("error_key","");if(known(key)&&!key.equals("unverified")&&!key.equals("busy"))throw new Fail(key,r.optString("detail",r.optString("error")));}
   }
  }catch(Fail f){outcome="error:"+f.key;reply=failure(f.key,f.detail);}
  catch(Exception e){outcome="error:unreachable";reply=failure("unreachable",e.getMessage()==null?e.getClass().getSimpleName():e.getMessage());}
  return finish(env,source,requestId,replaceLabel,outcome,via,t0,reply);
 }
 static JSONObject finish(Env env,String source,String requestId,String replaceLabel,String outcome,String via,long t0,JSONObject reply){
  env.log(logLine(source,requestId,"Phone",replaceLabel,outcome,via,env.millis()-t0));return reply;
 }
}
