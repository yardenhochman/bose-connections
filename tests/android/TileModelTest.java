package local.bose.connections;
import org.json.*;
import java.util.*;

/** The tile and panel model (android/TileModel.java) driven through a fake Host: requests are held until the test
 answers them, the clock and timers are manual. Mirrors runInstant in tests/bose_model.qml for the popup and the
 instant-input checks of tests/gui-fixtures.cjs for the dashboard. Prints PASS/FAIL lines. */
public class TileModelTest {
 static int failures=0,count=0;
 static void check(String name,boolean ok,String why){count++;if(!ok){failures++;System.out.println("FAIL "+name+": "+why);}}
 static final String PC="AA:AA:AA:AA:AA:AA",PH="CC:CC:CC:CC:CC:CC",MAC="BB:BB:BB:BB:BB:BB",TV="DD:DD:DD:DD:DD:DD";
 static final Map<String,String> NAMES=new LinkedHashMap<>();
 static{NAMES.put(PC,"Desktop PC");NAMES.put(PH,"Android phone");NAMES.put(MAC,"MacBook Pro");NAMES.put(TV,"Living room TV");}
 static JSONObject o(Object... kv){return Machines.o(kv);}
 static JSONObject overview(List<String> on,int level,boolean enabled){
  JSONArray ds=new JSONArray();for(Map.Entry<String,String> e:NAMES.entrySet())ds.put(o("address",e.getKey(),"name",e.getValue(),"connected",on.contains(e.getKey())));
  return o("here","phone","reachable",true,"cached",false,"battery",80,"noise",o("level",level,"enabled",enabled),"roles",o("pc",PC,"phone",PH,"mac",MAC),"devices",ds);
 }
 static class Held{final String path;final JSONObject body;final TileModel.Reply reply;Held(String p,JSONObject b,TileModel.Reply r){path=p;body=b;reply=r;}}
 static class Fake implements TileModel.Host {
  final Deque<Held> writes=new ArrayDeque<>(),reads=new ArrayDeque<>();final List<String> sent=new ArrayList<>();
  final Map<Object,Long> timers=new LinkedHashMap<>();final Map<Object,Runnable> jobs=new HashMap<>();
  long now=1_000_000;int open=0,maxOpen=0,changed=0,panels=0,cancelled=0;
  public void request(String path,JSONObject body,TileModel.Reply reply){
   sent.add(path+(body==null?"":" "+body.optString("action")+(body.has("replace")?" replace":"")));
   if(path.equals("/api/overview")){reads.add(new Held(path,body,reply));return;}
   open++;maxOpen=Math.max(maxOpen,open);writes.add(new Held(path,body,(j,e)->{open--;reply.done(j,e);}));
  }
  public Object later(Runnable r,long ms){Object h=new Object();timers.put(h,now+ms);jobs.put(h,r);return h;}
  public void cancel(Object h){if(timers.remove(h)!=null)cancelled++;jobs.remove(h);}
  public long now(){return now;}
  public void changed(){changed++;}
  public void openPanel(){panels++;}
  /** Advance the clock and run the timers that are due, in order. */
  void advance(long ms){now+=ms;while(true){Object due=null;for(Map.Entry<Object,Long> e:timers.entrySet())if(e.getValue()<=now&&(due==null||e.getValue()<timers.get(due)))due=e.getKey();if(due==null)return;timers.remove(due);jobs.remove(due).run();}}
 }
 static String slots(TileModel m,String[] order){StringBuilder s=new StringBuilder();for(JSONObject x:m.slots(order)){String a=Machines.str(x,"address");s.append(a.isEmpty()?"-":NAMES.get(a)).append(':').append(Machines.str(x,"st"));if(!Machines.str(x,"pend").isEmpty())s.append(':').append(Machines.str(x,"pend"));s.append(',');}return s.toString();}

 /** The tile's state as one value: a fresh model on a live snapshot. */
 static TileModel live(Fake f,List<String> on){TileModel m=new TileModel(f);m.snapshot=overview(on,7,true);return m;}
 /** Answers the oldest write as a controller would: applies it to the overview and replies verified. */
 static JSONObject[] cur=new JSONObject[1];
 static void answer(Fake f){
  Held h=f.writes.poll();if(h==null)throw new AssertionError("nothing to answer");
  JSONObject b=h.body;List<String> on=new ArrayList<>();JSONArray ds=cur[0].optJSONArray("devices");for(int i=0;i<ds.length();i++)if(ds.optJSONObject(i).optBoolean("connected"))on.add(ds.optJSONObject(i).optString("address"));
  JSONObject n=cur[0].optJSONObject("noise");int level=n.optInt("level");boolean en=n.optBoolean("enabled");
  if(h.path.equals("/api/switch")){on.remove(b.optString("replace"));if(!on.contains(PH))on.add(PH);cur[0]=overview(on,level,en);h.reply.done(o("ok",true,"verified",true,"message",Switcher.MESSAGES.get("ok"),"state",cur[0]),null);return;}
  String a=b.optString("action");
  if(a.equals("noise")){cur[0]=overview(on,b.optInt("level"),b.optBoolean("enabled"));h.reply.done(o("ok",true,"verified",true,"message","Noise cancellation updated","noise",cur[0].optJSONObject("noise"),"state",o("noise",cur[0].optJSONObject("noise"),"devices",new JSONArray())),null);return;}
  if(a.equals("disconnect"))on.remove(b.optString("address"));else{on.remove(b.optString("replace"));on.add(b.optString("address"));}
  cur[0]=overview(on,level,en);h.reply.done(o("ok",true,"verified",true,"message","Connection updated","state",cur[0]),null);
 }

 public static void main(String[] args)throws Exception{
  String[] order={PC,PH};
  // Latest wins; a held noise value; queued work runs in order, one request at a time.
  {Fake f=new Fake();cur[0]=overview(Arrays.asList(PC,PH),7,true);TileModel m=live(f,Arrays.asList(PC,PH));
   m.disconnect(m.device(PH));
   check("a disconnect runs at once",f.writes.size()==1&&m.pending()!=null&&PH.equals(m.pending().optString("address")),f.sent.toString());
   check("controls stay usable during a change",m.canMutate()&&m.canNoise(),"");
   m.disconnect(m.device(PC));
   check("a second tap queues, nothing sent",f.writes.size()==1&&m.queued()!=null&&PC.equals(m.queued().optString("address")),f.sent.toString());
   check("queued drawn apart from in flight",slots(m,order).equals("Desktop PC:disconnecting:queued,Android phone:disconnecting:flight,"),slots(m,order));
   m.setNoise(4,true);
   check("noise during a change is held and shown",Machines.is(m.anc,"held")&&m.noiseShown().optInt("level")==4&&f.writes.size()==1,Machines.kind(m.anc));
   m.connect(m.device(MAC));
   check("latest wins: the connect replaces the queued disconnect",m.queued()!=null&&"connect".equals(m.queued().optString("action"))&&MAC.equals(m.queued().optString("address")),String.valueOf(m.queued()));
   check("the queued connect takes the slot the disconnect frees",slots(m,order).equals("Desktop PC:connected,MacBook Pro:connecting:queued,"),slots(m,order));
   answer(f);
   check("the queued intent goes when the change ends",f.writes.size()==1&&"connect".equals(f.writes.peek().body.optString("action"))&&m.queued()==null,f.sent.toString());
   check("noise still held behind the released connect",Machines.is(m.anc,"held"),Machines.kind(m.anc));
   answer(f);
   check("then the held noise value is sent",f.writes.size()==1&&f.writes.peek().body.optInt("level")==4,f.sent.toString());
   f.advance(300);answer(f);
   check("settled; one request at a time",Machines.is(m.anc,"idle")&&m.snapshot.optJSONObject("noise").optInt("level")==4&&f.maxOpen==1&&m.connectedCount()==2,"max open "+f.maxOpen);}
  // Tile tap while busy: feedback at once, a second tap cancels, sent when the work ends.
  {Fake f=new Fake();cur[0]=overview(Arrays.asList(PC,MAC),7,true);TileModel m=live(f,Arrays.asList(PC,MAC));
   m.setNoise(3,true);
   check("noise write in flight",f.writes.size()==1,f.sent.toString());
   int before=f.changed;m.tileTap();
   check("a tile tap during a noise write queues with feedback",m.queuedHere()&&f.writes.size()==1&&m.tileSubtitle().equals("Moves here next · tap to cancel")&&f.changed>before,m.tileSubtitle());
   m.tileTap();
   check("a second tile tap cancels it",!m.queuedHere()&&!m.tileSubtitle().startsWith("Moves here next"),m.tileSubtitle());
   m.tileTap();f.advance(300);answer(f);
   check("the queued tap is sent after the write",f.writes.size()==1&&f.writes.peek().path.equals("/api/switch")&&m.tileSubtitle().equals(Switcher.MESSAGES.get("pending")),f.sent+" "+m.tileSubtitle());
   m.tileTap();
   check("a tile tap during its own switch changes nothing",f.writes.size()==1&&m.queued()==null,f.sent.toString());
   m.setNoise(5,true);m.setNoise(6,false);
   check("ANC during a switch is held, newest value wins (requestNoise respects a running switch)",Machines.is(m.anc,"held")&&!m.anc.optJSONObject("queued").optBoolean("enabled")&&f.writes.size()==1,String.valueOf(m.anc));
   answer(f);
   check("switch ok: note, then the held value goes",m.tileSubtitle().equals(Switcher.MESSAGES.get("ok"))&&f.writes.size()==1&&"noise".equals(f.writes.peek().body.optString("action"))&&!f.writes.peek().body.optBoolean("enabled"),m.tileSubtitle()+" "+f.sent);
   answer(f);
   check("one request at a time",f.maxOpen==1,"max "+f.maxOpen);}
  // A busy switch offers Replace per slot; Replace sends it; the note's stale tile refresh is cancelled.
  {Fake f=new Fake();cur[0]=overview(Arrays.asList(PC,MAC),7,true);TileModel m=live(f,Arrays.asList(PC,MAC));
   m.tileTap();
   f.writes.poll().reply.done(o("ok",false,"busy",true,"error_key","busy","error",Switcher.MESSAGES.get("busy"),"slots",new JSONArray().put(o("address",PC,"label","PC")).put(o("address",MAC,"label","Mac"))),null);
   check("busy: an offer, the panel opens, the busy note",m.offer()!=null&&m.offer().length()==2&&f.panels==1&&m.tileSubtitle().equals(Switcher.MESSAGES.get("busy")),m.tileSubtitle());
   int timers=f.timers.size();
   m.connect(m.device(TV));
   check("picking a device closes the offer (one interaction value)",m.offer()==null&&m.replacing()!=null&&TV.equals(m.replacing().optString("address")),String.valueOf(m.ui));
   m.cancelChoice();m.tileTap();m.tileTap();
   check("tile tap with an offer open: the plain switch again",f.writes.size()==1&&!f.writes.peek().body.has("replace"),f.sent.toString());
   f.writes.poll().reply.done(o("ok",false,"busy",true,"error_key","busy","error",Switcher.MESSAGES.get("busy"),"slots",new JSONArray().put(o("address",PC,"label","PC")).put(o("address",MAC,"label","Mac"))),null);
   check("each note cancels the previous note's tile refresh",f.timers.size()==timers&&f.cancelled>=1,"timers "+f.timers.size()+" cancelled "+f.cancelled);
   m.switchHere(MAC);
   check("Replace Mac sends the replace and says Replacing Mac…",f.writes.size()==1&&MAC.equals(f.writes.peek().body.optString("replace"))&&m.tileSubtitle().equals("Replacing Mac…"),m.tileSubtitle());
   answer(f);
   check("replaced: phone and PC",m.connectedCount()==2&&m.device(PH).optBoolean("connected")&&!m.device(MAC).optBoolean("connected"),"");
   f.advance(TileModel.NOTE_OK_MS+100);
   int t0=f.timers.size();m.note("first",30000);m.note("second",8000);
   check("a newer note cancels the older note's pending tile refresh (no stale updateTile)",f.timers.size()==t0+1,"timers "+f.timers.size());
   f.advance(TileModel.NOTE_OK_MS+100);
   check("the note expires and the tile refreshes once",!m.tileSubtitle().equals(Switcher.MESSAGES.get("ok"))&&f.timers.isEmpty(),m.tileSubtitle());}
  // A connect into full slots during a change queues, then asks for the slot (never guesses); a failure reverts.
  {Fake f=new Fake();cur[0]=overview(Arrays.asList(PC,MAC),7,true);TileModel m=live(f,Arrays.asList(PC,MAC));
   m.connect(m.device(PH));
   check("both full and idle: the slot choice opens",m.replacing()!=null&&f.writes.isEmpty(),String.valueOf(m.ui));
   m.replaceSlot(MAC);
   check("replace runs",f.writes.size()==1&&MAC.equals(f.writes.peek().body.optString("replace")),f.sent.toString());
   m.connect(m.device(TV));
   check("connect into full slots during a change: queued, not dropped",m.queued()!=null&&TV.equals(m.queued().optString("address"))&&m.replacing()==null,String.valueOf(m.queue));
   answer(f);
   check("released into full slots it asks which to replace and sends nothing",m.replacing()!=null&&TV.equals(m.replacing().optString("address"))&&f.writes.isEmpty(),String.valueOf(m.ui));
   m.cancelChoice();
   m.disconnect(m.device(PC));
   f.writes.poll().reply.done(o("ok",false,"error_key","keep_one","error",Switcher.MESSAGES.get("errors.keep_one")),null);
   check("a failed change reverts and says so",m.pending()==null&&m.noticeError&&m.notice.equals(Switcher.MESSAGES.get("errors.keep_one"))&&m.device(PC).optBoolean("connected"),m.notice);
   check("and re-reads the headset once",f.reads.size()==1,f.sent.toString());
   f.reads.poll().reply.done(cur[0],null);
   check("the re-read keeps the error line",m.notice.equals(Switcher.MESSAGES.get("errors.keep_one")),m.notice);}
  // Refresh during work is deferred; a read in flight when a change starts is dropped.
  {Fake f=new Fake();cur[0]=overview(Arrays.asList(PC,PH),7,true);TileModel m=live(f,Arrays.asList(PC,PH));
   m.refresh();
   check("refresh with nothing running reads at once",f.reads.size()==1&&m.reading,"");
   m.disconnect(m.device(PH));
   check("a write does not wait behind a read",f.writes.size()==1,f.sent.toString());
   answer(f);
   f.reads.poll().reply.done(overview(Arrays.asList(PC,PH),7,true),null);
   check("a read sent before the change and answered after it is dropped",!m.device(PH).optBoolean("connected"),"");
   m.disconnect(m.device(PC));m.refresh();m.refresh();
   check("refresh during a change: wanted, not sent",m.refreshWanted&&f.reads.isEmpty(),f.sent.toString());
   answer(f);
   check("one read once the change ends",f.reads.size()==1&&!m.refreshWanted,f.sent.toString());}
  // A held value whose change ends with the headset out of reach is dropped, and says so.
  {Fake f=new Fake();cur[0]=overview(Arrays.asList(PC,PH),7,true);TileModel m=live(f,Arrays.asList(PC,PH));
   m.disconnect(m.device(PH));m.setNoise(2,true);
   JSONObject off=overview(Arrays.asList(PC,PH),7,true);Machines.put(off,"reachable",false);Machines.put(off,"cached",true);
   f.writes.poll().reply.done(o("ok",true,"verified",true,"message","x","state",off),null);
   check("held noise dropped when unreachable",Machines.is(m.anc,"idle")&&m.notice.equals(TileModel.NOISE_DROPPED)&&f.writes.isEmpty(),m.notice);
   m.setNoise(3,true);
   check("noise while unreachable says so",m.notice.equals(TileModel.NOISE_DROPPED)&&f.writes.isEmpty(),"");}
  // Noise burst: first value at once, then only the last after the gap.
  {Fake f=new Fake();cur[0]=overview(Arrays.asList(PC,PH),7,true);TileModel m=live(f,Arrays.asList(PC,PH));
   m.setNoise(6,true);m.setNoise(5,true);m.setNoise(4,true);m.setNoise(3,true);
   check("burst: the first value goes at once",f.writes.size()==1&&f.writes.peek().body.optInt("level")==6,f.sent.toString());
   answer(f);
   check("then nothing before the gap",f.writes.isEmpty(),f.sent.toString());
   f.advance(300);
   check("after the gap only the last value",f.writes.size()==1&&f.writes.peek().body.optInt("level")==3,f.sent.toString());
   answer(f);
   check("burst sent 6 then 3",f.sent.stream().filter(s->s.contains("noise")).count()==2&&m.snapshot.optJSONObject("noise").optInt("level")==3,f.sent.toString());}
  System.out.println((failures==0?"PASS":"FAIL")+" android tile model: "+count+" checks, "+failures+" failures");
  System.exit(failures==0?0:1);
 }
}
