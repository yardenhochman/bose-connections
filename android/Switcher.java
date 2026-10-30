package local.bose.connections;
import org.json.*;
import java.io.IOException;
import java.util.*;

/** Tap-to-switch rules of tests/switch-contract.json for "here" = this phone. No Android types, so a JVM test can drive it with a fake headset. */
public class Switcher {
 static final long DEADLINE_MS=150000,DISCONNECT_WAIT_MS=4000,CONNECT_WAIT_MS=10000,POLL_MS=150;
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
 interface Headset extends AutoCloseable {JSONObject read()throws Exception;void connect(String address)throws Exception;void disconnect(String address)throws Exception;}
 interface Opener {Headset open()throws Exception;}
 interface Env {long millis();void sleep(long ms)throws InterruptedException;void log(String line);Map<String,String> roles()throws Exception;JSONObject state(JSONObject read)throws Exception;}
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
 static JSONObject await(Headset h,Env env,String address,boolean wanted,long waitMs,long deadline)throws Exception{
  long end=Math.min(env.millis()+waitMs,deadline);
  while(true){JSONObject s=h.read();if(connected(s).contains(address)==wanted)return s;if(env.millis()>=end)return null;env.sleep(POLL_MS);}
 }
 static JSONObject ok(Env env,JSONObject read)throws Exception{
  JSONObject o=new JSONObject().put("ok",true).put("verified",true).put("message",MESSAGES.get("ok"));
  try{JSONObject state=env.state(read);if(state!=null)o.put("state",state);}catch(Exception ignored){}return o;
 }
 /** Moves the headset to this phone. Never throws: every outcome is a contract reply, logged once. */
 static JSONObject switchHere(Opener opener,Env env,String source,String requestId,String replace){
  long t0=env.millis();JSONObject reply;String outcome="ok",replaceLabel="-";
  try(Headset h=opener.open()){
   Map<String,String> roles=env.roles();Map<String,String> upper=new HashMap<>();for(Map.Entry<String,String> e:roles.entrySet())upper.put(e.getKey(),e.getValue().toUpperCase(Locale.ROOT));
   long deadline=t0+DEADLINE_MS;JSONObject read=h.read();JSONArray ds=read.getJSONArray("devices");
   String here=upper.get("phone");for(int i=0;here==null&&i<ds.length();i++)if(ds.getJSONObject(i).optBoolean("current"))here=ds.getJSONObject(i).getString("address").toUpperCase(Locale.ROOT);
   if(here==null)throw new Fail("unreachable","This phone is not among the headset's devices");
   Set<String> conn=connected(read);
   if(conn.contains(here))reply=ok(env,read);
   else{
    String drop=replace==null?"":replace.toUpperCase(Locale.ROOT);
    if(conn.size()>=2){
     if(!conn.contains(drop)){
      JSONArray slots=new JSONArray();for(String a:conn){String name=label(upper,a);if(name.equals("-")){name="Other";for(int i=0;i<ds.length();i++)if(ds.getJSONObject(i).getString("address").equalsIgnoreCase(a))name=ds.getJSONObject(i).optString("name",name);}slots.put(new JSONObject().put("address",a).put("label",name));}
      outcome="busy";return finish(env,source,requestId,replaceLabel,outcome,t0,new JSONObject().put("ok",false).put("busy",true).put("error_key","busy").put("error",MESSAGES.get("busy")).put("slots",slots));
     }
     Set<String> remaining=new HashSet<>(conn);remaining.remove(drop);Set<String> anchors=new HashSet<>(upper.values());for(int i=0;i<ds.length();i++)if(ds.getJSONObject(i).optBoolean("current"))anchors.add(ds.getJSONObject(i).getString("address").toUpperCase(Locale.ROOT));
     remaining.retainAll(anchors);if(remaining.isEmpty())throw new Fail("keep_one","Dropping "+label(upper,drop)+" would leave no phone, PC or Mac connected");
     replaceLabel=label(upper,drop);h.disconnect(drop);
     if(await(h,env,drop,false,DISCONNECT_WAIT_MS,deadline)==null)throw new Fail("unverified","Disconnect not verified");
    }
    reply=null;
    for(int attempt=0;reply==null;attempt++){
     h.connect(here);if(env.millis()>deadline)throw new Fail("timeout","No answer within "+DEADLINE_MS/1000+" s");
     JSONObject after=await(h,env,here,true,CONNECT_WAIT_MS,deadline);
     if(after!=null){reply=ok(env,after);break;}
     if(env.millis()>=deadline)throw new Fail("timeout","No confirmation within "+DEADLINE_MS/1000+" s");
     JSONObject fresh=h.read();Set<String> now=connected(fresh);
     if(now.contains(here)){reply=ok(env,fresh);break;}
     if(attempt>0||now.size()>=2)throw new Fail("unverified","Headset did not report this phone connected");
    }
   }
  }catch(Fail f){outcome="error:"+f.key;reply=failure(f.key,f.detail);}
  catch(Exception e){outcome="error:unreachable";reply=failure("unreachable",e.getMessage()==null?e.getClass().getSimpleName():e.getMessage());}
  return finish(env,source,requestId,replaceLabel,outcome,t0,reply);
 }
 static JSONObject finish(Env env,String source,String requestId,String replaceLabel,String outcome,long t0,JSONObject reply){
  env.log(logLine(source,requestId,"Phone",replaceLabel,outcome,"local",env.millis()-t0));return reply;
 }
}
