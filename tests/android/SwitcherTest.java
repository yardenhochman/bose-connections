package local.bose.connections;
import local.bose.connections.Switcher;
import org.json.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Runs the shared tap-to-switch scenarios (exported by tests/test_android_contract.py) against Switcher with a fake headset and clock. */
public class SwitcherTest {
 static final Map<String,String> ADDR=new LinkedHashMap<>();
 static{ADDR.put("phone","AA:00:00:00:00:01");ADDR.put("mac","AA:00:00:00:00:02");ADDR.put("pc","AA:00:00:00:00:03");}
 static final Map<String,String> LABEL=new HashMap<>();
 static{LABEL.put("phone","Phone");LABEL.put("mac","Mac");LABEL.put("pc","PC");}
 static class Fake implements Switcher.Mesh,Switcher.Env {
  final Set<String> connected=new LinkedHashSet<>();final Deque<String> script=new ArrayDeque<>();final List<String> logs=new ArrayList<>();final List<JSONObject> calls=new ArrayList<>();
  long now=1_000_000;int connects=0,overviews=0;boolean reachable=true,reused=false;long budget=-1;
  JSONObject devices()throws Exception{JSONArray ds=new JSONArray();for(Map.Entry<String,String> e:ADDR.entrySet())ds.put(new JSONObject().put("address",e.getValue()).put("name",e.getKey()+"-device").put("connected",connected.contains(e.getValue())).put("current",false));return new JSONObject().put("devices",ds);}
  public JSONObject overview(boolean reuse,long budgetMs)throws Exception{overviews++;reused|=reuse;JSONObject o=devices().put("reachable",reachable);JSONObject roles=new JSONObject();for(Map.Entry<String,String> e:ADDR.entrySet())if(!e.getKey().equals("phone"))roles.put(e.getKey(),e.getValue());return o.put("roles",roles);}
  public JSONObject override(JSONObject data)throws Exception{
   connects++;calls.add(data);budget=data.opt("budget_ms") instanceof Long?(Long)data.opt("budget_ms"):-1;String step=script.poll();if(step==null)throw new AssertionError("unscripted connect");
   if(step.equals("transport"))return new JSONObject().put("ok",false).put("reachable",false).put("transport",true).put("error_key","timeout").put("error","x").put("detail","SocketTimeoutException");
   if(step.equals("late_ok")){now+=200_000;step="connect_ok";}
   if(step.equals("slow_unconfirmed")){now+=125_000;step="connect_unconfirmed";}
   if(step.startsWith("connect_ok")){if(step.endsWith("_via_pc"))data.put("via","peer:pc");connected.remove(data.optString("replace"));connected.add(data.getString("address"));return new JSONObject().put("ok",true).put("verified",true).put("state",devices());}
   if(step.equals("unreachable"))throw new IOException("RFCOMM refused");
   if(step.equals("hang"))now+=200_000;
   if(step.equals("hang")||step.equals("connect_unconfirmed"))return new JSONObject().put("ok",false).put("error_key","unverified").put("error","x");
   throw new AssertionError(step);
  }
  public long millis(){return now;}
  public void log(String line){logs.add(line);}
  public Map<String,String> roles(){return ADDR;}
 }
 static int failures=0,count=0;
 static void check(String name,boolean ok,String why){count++;if(ok)System.out.println("PASS "+name);else{failures++;System.out.println("FAIL "+name+": "+why);}}
 static List<String> split(String s){return s.isEmpty()?new ArrayList<String>():Arrays.asList(s.split(","));}
 static String address(String role,String here,List<String> others){return role.equals("here")?ADDR.get(here):role.equals("other1")?ADDR.get(others.get(0)):ADDR.get(others.get(1));}
 static String roleOf(String addr){for(Map.Entry<String,String> e:ADDR.entrySet())if(e.getValue().equals(addr))return e.getKey();return "?";}
 public static void main(String[] args)throws Exception{
  Map<String,String> contract=new LinkedHashMap<>();List<String[]> scenarios=new ArrayList<>();
  for(String line:Files.readAllLines(Paths.get(args[0]))){String[] f=line.split("\t",-1);if(f[0].equals("msg"))contract.put(f[1],f[2]);else scenarios.add(f);}
  check("messages_equal_contract",contract.equals(Switcher.MESSAGES),contract+" != "+Switcher.MESSAGES);
  String here="phone";List<String> others=new ArrayList<>(Arrays.asList("mac","pc"));
  for(String[] f:scenarios){
   // f: scn, name, start, replace, headset, outcome, text, error_key, connect_commands, connected, offered
   String name=f[1];Fake fake=new Fake();for(String r:split(f[2]))fake.connected.add(address(r,here,others));fake.script.addAll(split(f[4]));
   String replace=f[3].isEmpty()?null:address(f[3],here,others);
   JSONObject reply=Switcher.switchHere(fake,fake,"android-app","req-"+name.length(),replace);
   String outcome=reply.optBoolean("ok")?"ok":reply.optBoolean("busy")?"busy":"error";String why="";
   if(!outcome.equals(f[5]))why+="outcome "+outcome+"; ";
   String text=reply.optBoolean("ok")?reply.optString("message"):reply.optString("error");
   if(!text.equals(f[6]))why+="text '"+text+"'; ";
   if(!f[7].isEmpty()&&!f[7].equals(reply.optString("error_key")))why+="error_key "+reply.optString("error_key")+"; ";
   if(!f[8].isEmpty()&&Integer.parseInt(f[8])!=fake.connects)why+="connect commands "+fake.connects+"; ";
   if(!f[9].isEmpty()){Set<String> want=new HashSet<>();for(String r:split(f[9]))want.add(address(r,here,others));if(!want.equals(fake.connected))why+="connected "+fake.connected+"; ";}
   if(outcome.equals("busy")){
    List<String> offered=new ArrayList<>();JSONArray slots=reply.getJSONArray("slots");for(int i=0;i<slots.length();i++)offered.add(Switcher.MESSAGES.get("replace").replace("{label}",slots.getJSONObject(i).getString("label")));
    if(!offered.equals(split(f[10])))why+="offered "+offered+"; ";
    for(int i=0;i<slots.length();i++)if(!LABEL.get(roleOf(slots.getJSONObject(i).getString("address"))).equals(slots.getJSONObject(i).getString("label")))why+="slot label mismatch; ";
   }
   if(outcome.equals("error")&&reply.optString("detail").isEmpty())why+="no detail; ";
   String want="error".equals(outcome)?"error:"+f[7]:outcome;
   String re="bose\\.switch source=android-app id=req-\\d+ target=Phone replace="+(name.equals("both_busy_replace")?"PC":"-")+" outcome="+java.util.regex.Pattern.quote(want)+" via=local total=\\d+\\.\\d\\ds";
   if(fake.logs.size()!=1||!fake.logs.get(0).matches(re))why+="log "+fake.logs+"; ";
   if(fake.logs.toString().matches("(?s).*([0-9A-F]{2}:){5}.*"))why+="address in log; ";
   check(name,why.isEmpty(),why);
  }
  // Beyond the shared scenarios.
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.script.add("connect_ok");
   JSONObject r=Switcher.switchHere(f,f,"android-tile","t1",ADDR.get("pc"));
   check("replace_ignored_when_slot_free",r.optBoolean("ok")&&f.connects==1&&!f.calls.get(0).has("replace")&&f.logs.get(0).contains("replace=- ")&&f.logs.get(0).contains("source=android-tile"),r+" "+f.logs);}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.connected.add(ADDR.get("pc"));
   JSONObject r=Switcher.switchHere(f,f,"android-app","t2","AA:00:00:00:00:99");
   check("replace_not_held_offers_busy_again",r.optBoolean("busy")&&f.connects==0,r.toString());}
  {Fake f=new Fake();f.reachable=false;
   JSONObject r=Switcher.switchHere(f,f,"android-app",null,null);
   check("no_controller_reads_headset_is_unreachable",r.optString("error_key").equals("unreachable")&&r.optString("error").equals(Switcher.MESSAGES.get("errors.unreachable"))&&f.logs.get(0).contains("id=- ")&&f.connects==0,r+" "+f.logs);}
  {Fake f=new Fake();
   Switcher.Mesh broken=new Switcher.Mesh(){public JSONObject overview(boolean r,long b)throws Exception{throw new IOException("Turn on Bluetooth on your phone");}public JSONObject override(JSONObject d){return null;}};
   JSONObject r=Switcher.switchHere(broken,f,"android-app","t3",null);
   check("overview_failure_is_unreachable",r.optString("error_key").equals("unreachable")&&r.optString("detail").contains("Bluetooth"),r.toString());}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.connected.add(ADDR.get("pc"));f.script.add("connect_ok");
   Map<String,String> roles=new HashMap<>();roles.put("phone",ADDR.get("phone"));roles.put("mac","AA:00:00:00:00:77");
   Switcher.Env env=new Switcher.Env(){public long millis(){return f.now;}public void log(String l){f.logs.add(l);}public Map<String,String> roles(){return roles;}};
   Switcher.Mesh mesh=new Switcher.Mesh(){public JSONObject overview(boolean r,long b)throws Exception{JSONObject o=f.devices().put("reachable",true);return o;}public JSONObject override(JSONObject d)throws Exception{return f.override(d);}};
   JSONObject r=Switcher.switchHere(mesh,env,"android-app","t4",ADDR.get("pc"));
   check("replace_must_leave_a_known_device",r.optString("error_key").equals("keep_one")&&f.connects==0,r.toString());}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.connected.add(ADDR.get("pc"));
   JSONObject r=Switcher.switchHere(f,f,"android-app","t5",null);
   check("phone_holds_no_slot_both_busy_is_busy",r.optBoolean("busy")&&r.getJSONArray("slots").length()==2&&f.connects==0,r.toString());}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.connected.add(ADDR.get("pc"));f.script.add("connect_ok");
   JSONObject r=Switcher.switchHere(f,f,"android-app","t6",ADDR.get("mac"));
   check("replace_is_passed_to_override",r.optBoolean("ok")&&f.calls.get(0).optString("replace").equals(ADDR.get("mac"))&&f.calls.get(0).optString("address").equals(ADDR.get("phone"))&&f.calls.get(0).optString("source").equals("android-app")&&f.calls.get(0).optString("request_id").equals("t6")&&f.logs.get(0).contains("replace=Mac"),r+" "+f.calls);}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.script.add("connect_unconfirmed");f.script.add("connect_ok");
   JSONObject r=Switcher.switchHere(f,f,"android-app","t7",null);
   check("first_unverified_second_succeeds_after_fresh_overview",r.optBoolean("ok")&&f.connects==2&&f.overviews==2,r+" "+f.overviews);}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.script.add("connect_ok_via_pc");
   JSONObject r=Switcher.switchHere(f,f,"android-app","t8",null);
   check("executed_via_peer_logs_peer",r.optBoolean("ok")&&f.logs.get(0).contains("via=peer:pc "),r+" "+f.logs);}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.script.add("transport");f.script.add("connect_ok");
   JSONObject r=Switcher.switchHere(f,f,"android-app","t9",null);
   check("transport_failure_is_never_resent",r.optString("error_key").equals("timeout")&&f.connects==1,r+" "+f.connects);}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.script.add("late_ok");
   JSONObject r=Switcher.switchHere(f,f,"android-app","t10",null);
   check("verified_connect_after_deadline_is_ok",r.optBoolean("ok"),r.toString());}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.script.add("slow_unconfirmed");f.script.add("connect_ok");
   JSONObject r=Switcher.switchHere(f,f,"android-app","t11",null);
   check("no_resend_without_time_left",r.optString("error_key").equals("timeout")&&f.connects==1,r+" "+f.connects);}
  {Fake f=new Fake();f.connected.add(ADDR.get("phone"));f.connected.add(ADDR.get("mac"));
   JSONObject r=Switcher.switchHere(f,f,"android-app","t12",null);
   check("already_here_comes_from_a_fresh_read",r.optBoolean("ok")&&!f.reused&&f.overviews==1&&f.connects==0,r+" reused="+f.reused);}
  {Fake f=new Fake();f.connected.add(ADDR.get("mac"));f.script.add("connect_ok");
   JSONObject r=Switcher.switchHere(f,f,"android-app","0f8e7d6c-1234-5678-9abc-def012345678",null);
   check("request_id_cleaned_and_budget_passed",r.optBoolean("ok")&&f.calls.get(0).optString("request_id").equals("0f8e7d6c-1234-5678-9abc-def01234")&&f.budget>0&&f.budget<=90000,f.calls+" "+f.budget);}
  System.out.println(count+" checks, "+failures+" failures");
  System.exit(failures==0?0:1);
 }
}
