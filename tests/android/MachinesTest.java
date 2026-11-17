package local.bose.connections;
import org.json.*;
import java.nio.file.*;
import java.util.*;

/** Runs the shared transition tables (tests/machine-tables.json, path in args[0]) against android/Machines.java, as
 tests/web_machines.cjs does for the dashboard and tests/bose_model.qml for the popup. Prints PASS/FAIL lines. */
public class MachinesTest {
 static int failures=0,count=0;
 static void check(String name,boolean ok,String why){count++;if(!ok){failures++;System.out.println("FAIL "+name+": "+why);}}
 /** Canonical JSON: keys sorted, NULL as null, numbers as written. Two values are the same when these are equal. */
 static String canon(Object v){
  if(v==null||v==JSONObject.NULL)return "null";
  if(v instanceof JSONObject){JSONObject o=(JSONObject)v;List<String> keys=new ArrayList<>();for(Iterator<String> it=o.keys();it.hasNext();)keys.add(it.next());Collections.sort(keys);
   StringBuilder s=new StringBuilder("{");for(String k:keys){if(s.length()>1)s.append(',');s.append('"').append(k).append("\":").append(canon(o.opt(k)));}return s.append('}').toString();}
  if(v instanceof JSONArray){JSONArray a=(JSONArray)v;StringBuilder s=new StringBuilder("[");for(int i=0;i<a.length();i++){if(i>0)s.append(',');s.append(canon(a.opt(i)));}return s.append(']').toString();}
  if(v instanceof String)return "\""+v+"\"";
  return v.toString();
 }
 static Object resolve(JSONObject t,Object o)throws Exception{
  JSONObject values=t.optJSONObject("values");
  if(o instanceof String&&values!=null&&values.has((String)o))return values.get((String)o);
  if(o instanceof JSONArray){JSONArray a=(JSONArray)o,r=new JSONArray();for(int i=0;i<a.length();i++)r.put(resolve(t,a.opt(i)));return r;}
  if(o instanceof JSONObject){JSONObject src=(JSONObject)o,r=new JSONObject();for(Iterator<String> it=src.keys();it.hasNext();){String k=it.next();r.put(k,resolve(t,src.opt(k)));}return r;}
  return o;
 }
 interface Fn{JSONObject apply(JSONObject s,JSONObject e);}
 static void table(JSONObject tables,String name,Fn fn)throws Exception{
  JSONObject t=tables.getJSONObject(name);JSONArray rows=t.getJSONArray("rows");
  for(int i=0;i<rows.length();i++){JSONArray r=rows.getJSONArray(i);
   JSONObject from=(JSONObject)resolve(t,t.getJSONObject("states").get(r.getString(0))),ev=(JSONObject)resolve(t,t.getJSONObject("events").get(r.getString(1))),to=(JSONObject)resolve(t,t.getJSONObject("states").get(r.getString(2)));
   JSONObject got=fn.apply(from,ev);check(name+" "+r.getString(0)+" --"+r.getString(1)+"->",canon(got).equals(canon(to)),canon(got)+" != "+canon(to));}
 }
 static JSONObject o(Object... kv){return Machines.o(kv);}
 static List<JSONObject> slots(Object... addrSt){List<JSONObject> l=new ArrayList<>();for(int i=0;i<addrSt.length;i+=2)l.add(o("address",addrSt[i],"st",addrSt[i+1]));return l;}
 static String ov(List<JSONObject> l){StringBuilder s=new StringBuilder();for(JSONObject x:l)s.append(Machines.str(x,"address")).append(':').append(Machines.str(x,"st")).append(':').append(Machines.str(x,"pend")).append(':').append(Machines.str(x,"replacing")).append(' ');return s.toString().trim();}
 public static void main(String[] args)throws Exception{
  JSONObject tables=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),"UTF-8"));
  table(tables,"interact",Machines::interact);
  table(tables,"noiser",Machines::noiser);
  table(tables,"intents",Machines::intents);
  JSONArray rows=tables.getJSONObject("schedule").getJSONArray("rows");
  for(int i=0;i<rows.length();i++){JSONArray r=rows.getJSONArray(i);
   String got=Machines.schedule(r.optBoolean(0),o("kind",r.getString(1)),o("kind",r.getString(2)),r.optBoolean(3));check("schedule "+r,got.equals(r.getString(4)),got);}
  // Sequences beyond the tables (tests/web_machines.cjs).
  JSONObject v3=o("level",3,"enabled",true),v5=o("level",5,"enabled",true);
  JSONObject m=Machines.noiser(Machines.noiser(Machines.noiser(Machines.IDLE,o("type","input","value",v3)),o("type","send")),o("type","input","value",v5));
  m=Machines.noiser(m,o("type","ok"));check("late ok for 3 keeps 5 shown",canon(Machines.noiseShown(m)).equals(canon(v5)),canon(m));
  check("idle shows the verified value",Machines.noiseShown(Machines.IDLE)==null,"");
  JSONObject q=Machines.IDLE;q=Machines.intents(q,o("type","hold","intent",o("action","disconnect","address","AA")));q=Machines.intents(q,o("type","hold","intent",o("action","here","address","PC","label","x")));
  check("latest wins",Machines.str(q.optJSONObject("intent"),"action").equals("here"),canon(q));
  check("the same tap again cancels (labels ignored)",Machines.is(Machines.intents(q,o("type","hold","intent",o("action","here","address","PC"))),"idle"),"");
  // Overlay.
  check("nothing pending",ov(Machines.overlaySlots(slots("AA","connected",null,"free"),null,null)).equals("AA:connected:: :free::"),ov(Machines.overlaySlots(slots("AA","connected",null,"free"),null,null)));
  check("connect in flight fills the free slot",ov(Machines.overlaySlots(slots("AA","connected",null,"free"),o("action","connect","address","CC"),null)).equals("AA:connected:: CC:connecting:flight:"),"");
  check("queued connect takes the slot a disconnect frees",ov(Machines.overlaySlots(slots("AA","connected","BB","connected"),o("action","disconnect","address","BB"),o("action","connect","address","CC"))).equals("AA:connected:: CC:connecting:queued:BB"),
   ov(Machines.overlaySlots(slots("AA","connected","BB","connected"),o("action","disconnect","address","BB"),o("action","connect","address","CC"))));
  check("queued connect into full slots is not drawn",ov(Machines.overlaySlots(slots("AA","connected","BB","connected"),null,o("action","connect","address","CC"))).equals("AA:connected:: BB:connected::"),"");
  check("replace in flight plus a queued disconnect",ov(Machines.overlaySlots(slots("AA","connected","BB","connected"),o("action","connect","address","CC","replace","AA"),o("action","disconnect","address","BB"))).equals("CC:connecting:flight:AA BB:disconnecting:queued:"),"");
  check("queued Use here into the free slot",ov(Machines.overlaySlots(slots("AA","connected",null,"free"),null,o("action","here","address","PH","here",true))).equals("AA:connected:: PH:connecting:queued:"),"");
  List<JSONObject> verified=slots("AA","connected");Machines.overlaySlots(verified,o("action","disconnect","address","AA"),null);
  check("overlay never writes the verified slots",Machines.str(verified.get(0),"st").equals("connected"),"");
  System.out.println((failures==0?"PASS":"FAIL")+" android machines: "+count+" checks, "+failures+" failures");
  System.exit(failures==0?0:1);
 }
}
