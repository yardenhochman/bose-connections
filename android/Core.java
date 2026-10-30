package local.bose.connections;
import android.content.*;
import android.bluetooth.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;

public class Core {
 static final Object LOCK=new Object();
 static final long PRELUDE_TTL_MS=5000,POLL_MS=150,DISCONNECT_WAIT_MS=4000,CONNECT_WAIT_MS=10000,EXCLUDE_GRACE_MS=5000;
 static volatile JSONObject LAST_OVERVIEW;static volatile long LAST_OVERVIEW_AT=Long.MIN_VALUE;
 static volatile boolean IDENT_OK=false,LOCAL_OK=false;
 static class Unreachable extends IOException {Unreachable(Exception cause){super(cause.getMessage()==null?cause.getClass().getSimpleName():cause.getMessage(),cause);}}
 static void timing(String action,String outcome,String target,String mode,Map<String,Long> phases,long totalMs){
  StringBuilder s=new StringBuilder("action="+action+" outcome="+outcome+" target="+target);if(mode!=null)s.append(" prelude_mode="+mode);
  for(Map.Entry<String,Long> e:phases.entrySet())s.append(String.format(Locale.ROOT," %s=%.2fs",e.getKey(),e.getValue()/1000.0));s.append(String.format(Locale.ROOT," total=%.2fs",totalMs/1000.0));
  android.util.Log.i("BoseTiming",s.toString().replaceAll("(?i)\\b([0-9a-f]{2}[:-]){5}[0-9a-f]{2}\\b","device"));
 }
 static void add(Map<String,Long> m,String k,long startNs){m.merge(k,(System.nanoTime()-startNs)/1000000,Long::sum);}
 static final ExecutorService STATUS_POOL=Executors.newFixedThreadPool(3);
 static final Map<String,Future<JSONObject>> PROBES=new HashMap<>();
 static final String HEADSET="";
 static final UUID BMAP=UUID.fromString("00000000-deca-fade-deca-deafdecacaff");
 static JSONObject config(Context c)throws Exception{
  File f=new File(c.getFilesDir(),"config.json");
  if(f.exists())try(FileInputStream in=new FileInputStream(f)){return new JSONObject(read(in,65536));}
  return new JSONObject().put("id","phone").put("name","Phone").put("headset",HEADSET).put("token","").put("roles",new JSONObject()).put("peers",new JSONArray());
 }
 static synchronized void save(Context c,JSONObject config)throws Exception{
  File f=new File(c.getFilesDir(),"config.json"),tmp=new File(c.getFilesDir(),"config.tmp");
  try(FileOutputStream out=new FileOutputStream(tmp)){out.write(config.toString().getBytes("UTF-8"));}
  if(!tmp.renameTo(f))throw new IOException("Could not save settings");
 }
 static String read(InputStream in,int limit)throws IOException{ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[4096];int n;while((n=in.read(b))!=-1){out.write(b,0,n);if(out.size()>limit)throw new IOException("Response too large");}return out.toString("UTF-8");}
 static JSONObject error(Exception e){JSONObject o=new JSONObject();try{String detail=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();o.put("ok",false).put("reachable",false).put("error",detail);
  if(e instanceof Switcher.Fail){Switcher.Fail f=(Switcher.Fail)e;o.put("error_key",f.key).put("error",f.getMessage()).put("detail",f.detail==null?"":f.detail);}
  else if(e instanceof Unreachable)o.put("error_key","unreachable").put("error",Switcher.text("unreachable")).put("detail",detail);}catch(Exception ignored){}return o;}
 static String keyOf(Exception e){return e instanceof Switcher.Fail?((Switcher.Fail)e).key:"unreachable";}
 static byte[] address(String a)throws Exception{if(!a.matches("(?i)([0-9a-f]{2}:){5}[0-9a-f]{2}"))throw new IOException("Invalid Bluetooth address");String[] p=a.split(":");byte[] b=new byte[6];for(int i=0;i<6;i++)b[i]=(byte)Integer.parseInt(p[i],16);return b;}
 static String address(byte[] b){StringBuilder s=new StringBuilder();for(int i=0;i<6;i++){if(i>0)s.append(':');s.append(String.format(Locale.ROOT,"%02X",b[i]&255));}return s.toString();}
 static class Client implements AutoCloseable {
  BluetoothSocket socket;InputStream in;OutputStream out;ScheduledExecutorService timer=Executors.newSingleThreadScheduledExecutor();ScheduledFuture<?> expiry;
  Client(Context c)throws Exception{
   BluetoothAdapter a=((BluetoothManager)c.getSystemService(Context.BLUETOOTH_SERVICE)).getAdapter();
   if(a==null||!a.isEnabled())throw new IOException("Turn on Bluetooth on your phone");
   String headset=config(c).optString("headset",HEADSET);
   if(headset.isEmpty())throw new IOException("Choose your headset in Settings → Set up controller links");
   address(headset);BluetoothDevice d=a.getRemoteDevice(headset);
   socket=d.createRfcommSocketToServiceRecord(BMAP);
   expiry=timer.schedule(()->{try{socket.close();}catch(Exception ignored){}},10,TimeUnit.SECONDS);
   try{socket.connect();expiry.cancel(false);in=socket.getInputStream();out=socket.getOutputStream();}catch(Exception e){close();throw e;}
  }
  static class ReadTimeout extends IOException {ReadTimeout(){super("No acknowledgement; verify state without repeating the command");}}
  byte[] exact(int n,long deadline)throws Exception {
   byte[] b=new byte[n];int pos=0;
   while(pos<n){if(System.nanoTime()>deadline){if(pos==0)throw new ReadTimeout();throw new IOException("Incomplete Bluetooth response");}
    int available=in.available();if(available==0){Thread.sleep(10);continue;}int got=in.read(b,pos,Math.min(available,n-pos));if(got<0)throw new IOException("Headset closed the connection");pos+=got;
   }return b;
  }
  byte[] request(int block,int func,int op,byte[] p,int wanted)throws Exception{return request(block,func,op,p,wanted,5000);}
  byte[] request(int block,int func,int op,byte[] p,int wanted,int timeout)throws Exception{
   out.write(new byte[]{(byte)block,(byte)func,(byte)op,(byte)p.length});out.write(p);out.flush();long deadline=System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(timeout);
   for(int count=0;count<100;count++){
    byte[] h=exact(4,deadline);byte[] data=exact(h[3]&255,deadline);
    if((h[0]&255)!=block||(h[1]&255)!=func)continue;
    int kind=h[2]&15;
    if(kind==15)throw new IOException("Headset rejected command "+block+"."+func);
    if(kind==wanted)return data;
   }throw new IOException("No matching headset response");
  }
  byte[] get(int b,int f,byte[] p)throws Exception{return request(b,f,1,p,3);}
  JSONObject noise()throws Exception{
   byte[] p=get(1,5,new byte[0]);if(p.length!=3||p[0]!=11||(p[1]&255)>10||(p[2]!=0&&p[2]!=1))throw new IOException("Unknown NC700 noise-control layout; refusing changes");
   return new JSONObject().put("level",10-(p[1]&255)).put("enabled",p[2]!=0);
  }
  void writeNoise(int level,boolean enabled)throws Exception{try{request(1,5,2,new byte[]{(byte)(10-level),(byte)(enabled?1:0)},3,250);}catch(ReadTimeout ignored){}}
  JSONObject setNoise(int level,boolean enabled)throws Exception{
   if(level<0||level>10)throw new IOException("Noise level must be 0–10");JSONObject before=noise();
   writeNoise(level,enabled);JSONObject after=noise();
   if(!before.getBoolean("enabled")&&enabled&&after.getBoolean("enabled")&&after.getInt("level")!=level){writeNoise(level,true);after=noise();}
   if(after.getBoolean("enabled")!=enabled||(enabled&&after.getInt("level")!=level))throw new IOException("Noise-control change was not verified; refresh before retrying");return after;
  }
  JSONObject status()throws Exception{return status(true,true);}
  JSONObject status(boolean full,boolean checkIdent)throws Exception{
   if(checkIdent){byte[] id=get(0,3,new byte[0]);if(id.length!=3||id[0]!=0x40||id[1]!=0x24)throw new IOException("This controller supports only the Bose NC700");}
   byte[] list=get(4,4,new byte[0]);if(list.length<1||(list.length-1)%6!=0||list.length>49)throw new IOException("Unexpected device-list layout; refusing changes");
   JSONArray devices=new JSONArray();
   for(int i=1;i<list.length;i+=6){byte[] a=Arrays.copyOfRange(list,i,i+6),info=get(4,5,a);
    if(info.length<9||!Arrays.equals(a,Arrays.copyOfRange(info,0,6))||(info[6]!=0&&info[6]!=1&&info[6]!=3))throw new IOException("Unexpected device-info layout; refusing changes");
    String name=new String(info,9,info.length-9,"UTF-8").split("\u0000",2)[0];
    devices.put(new JSONObject().put("address",address(a)).put("name",name.isEmpty()?address(a):name).put("connected",info[6]!=0).put("current",info[6]==3));
   }
   if(!full)return new JSONObject().put("devices",devices).put("capacity",2);
   Object battery=JSONObject.NULL;try{byte[] b=get(2,2,new byte[0]);if(b.length==1&&(b[0]&255)<=100)battery=b[0]&255;}catch(Exception ignored){}
   Object noise=JSONObject.NULL;try{noise=noise();}catch(Exception ignored){}
   return new JSONObject().put("noise",noise).put("devices",devices).put("battery",battery).put("capacity",2).put("product","Bose 700");
  }
  void action(String action,String target)throws Exception{byte[] a=address(target);try{if(action.equals("connect")){byte[] p=new byte[7];System.arraycopy(a,0,p,1,6);request(4,1,5,p,7,1000);}else if(action.equals("disconnect"))request(4,2,5,a,7,250);else throw new IOException("Unknown action");}catch(ReadTimeout unconfirmed){/* State verification is mandatory in Core.action. Do not resend. */}}
  public void close(){if(expiry!=null)expiry.cancel(false);timer.shutdownNow();try{if(socket!=null)socket.close();}catch(Exception ignored){}}
 }
 static JSONObject status(Context c){synchronized(LOCK){try(Client client=new Client(c)){JSONObject s=client.status();IDENT_OK=true;LOCAL_OK=true;return s.put("reachable",true).put("node","Phone").put("controller","phone").put("observed",System.currentTimeMillis()/1000.0);}catch(Exception e){LOCAL_OK=false;IDENT_OK=false;JSONObject o=error(e);try{o.put("node","Phone").put("controller","phone").put("devices",new JSONArray());}catch(Exception ignored){}return o;}}}
 static JSONObject peer(Context c,JSONObject p,String path,JSONObject data){HttpURLConnection con=null;try{
  JSONObject conf=config(c);if(conf.optString("token").isEmpty())throw new IOException("Set up controller links to use the PC or Mac");
  URL url=new URL(p.getString("url")+path);if(!url.getProtocol().equals("http")||!tailnet(url.getHost()))throw new IOException("Controller must use its Tailscale IPv4 address");
  con=(HttpURLConnection)url.openConnection();con.setConnectTimeout(2000);con.setReadTimeout(data==null?35000:90000);con.setRequestProperty("Authorization","Bearer "+conf.getString("token"));
  if(data!=null){con.setRequestMethod("POST");con.setDoOutput(true);con.setRequestProperty("Content-Type","application/json");try(OutputStream out=con.getOutputStream()){out.write(data.toString().getBytes("UTF-8"));}}
  int code=con.getResponseCode();JSONObject result=new JSONObject(read(code>=400?con.getErrorStream():con.getInputStream(),65536));return result;
 }catch(Exception e){JSONObject o=error(data==null?e:new Switcher.Fail(e instanceof SocketTimeoutException?"timeout":"unreachable",e.getMessage()));try{o.put("controller",p.optString("id")).put("node",p.optString("name"));}catch(Exception ignored){}return o;}finally{if(con!=null)con.disconnect();}}
 static boolean tailnet(String ip){try{String[] p=ip.split("\\.");return p.length==4&&Integer.parseInt(p[0])==100&&Integer.parseInt(p[1])>=64&&Integer.parseInt(p[1])<=127;}catch(Exception e){return false;}}
 static JSONObject overview(Context c)throws Exception{return overview(c,"");}
 static boolean eligible(JSONObject state,String exclude)throws Exception{
  if(!state.optBoolean("reachable"))return false;JSONArray ds=state.optJSONArray("devices");
  if(ds!=null)for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);if(d.optBoolean("current")&&d.optString("address").equals(exclude))return false;}return true;
 }
 static JSONObject overview(Context c,String exclude)throws Exception{
  JSONObject conf=config(c);JSONArray peers=conf.optJSONArray("peers");Map<String,Future<JSONObject>> jobs=new LinkedHashMap<>();Map<String,String> names=new HashMap<>();
  synchronized(PROBES){
   Future<JSONObject> local=PROBES.get("phone");if(local==null||local.isDone())PROBES.put("phone",local=STATUS_POOL.submit(()->status(c)));jobs.put("phone",local);names.put("phone","Phone");
   if(peers!=null)for(int i=0;i<peers.length();i++){final JSONObject p=peers.getJSONObject(i);String id=p.getString("id");Future<JSONObject> job=PROBES.get(id);if(job==null||job.isDone())PROBES.put(id,job=STATUS_POOL.submit(()->peer(c,p,"/api/status",null)));jobs.put(id,job);names.put(id,p.optString("name",id));}
  }
  long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(35);
  boolean grace=false;
  while(System.nanoTime()<deadline){boolean all=true,ready=false,answered=false;for(Future<JSONObject> job:jobs.values()){if(!job.isDone())all=false;else{if(job.get().optBoolean("reachable"))answered=true;if(eligible(job.get(),exclude))ready=true;}}if(all||ready)break;if(answered&&!grace){grace=true;deadline=Math.min(deadline,System.nanoTime()+TimeUnit.MILLISECONDS.toNanos(EXCLUDE_GRACE_MS));}Thread.sleep(10);}
  JSONArray states=new JSONArray(),devices=new JSONArray();JSONObject roles=new JSONObject(conf.optJSONObject("roles")==null?"{}":conf.getJSONObject("roles").toString());Object battery=JSONObject.NULL,noise=JSONObject.NULL;boolean reachable=false;double freshest=0;
  for(Map.Entry<String,Future<JSONObject>> entry:jobs.entrySet()){
   Future<JSONObject> job=entry.getValue();JSONObject state=job.isDone()?job.get():new JSONObject().put("controller",entry.getKey()).put("node",names.get(entry.getKey())).put("reachable",false).put("checking",true).put("devices",new JSONArray());states.put(state);
   if(state.optBoolean("reachable")){reachable=true;if(state.optDouble("observed",0)>=freshest){freshest=state.optDouble("observed",0);devices=state.getJSONArray("devices");battery=state.opt("battery");noise=state.opt("noise");}JSONArray ds=state.getJSONArray("devices");for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);if(d.optBoolean("current"))roles.put(state.getString("controller"),d.getString("address"));}}
  }
  JSONObject result=new JSONObject().put("controllers",states).put("devices",devices).put("roles",roles).put("reachable",reachable).put("battery",battery).put("capacity",2).put("here","phone").put("observed",freshest).put("cached",false).put("noise",noise==null?JSONObject.NULL:noise);
  if(reachable){snapshot(c,result);LAST_OVERVIEW=result;LAST_OVERVIEW_AT=System.nanoTime();}
  else{
   // Nobody read the headset: keep showing the last known slots, marked cached, instead of "connected to nothing".
   File f=new File(c.getFilesDir(),"snapshot.json");
   if(f.exists())try(FileInputStream in=new FileInputStream(f)){JSONObject prev=new JSONObject(read(in,65536));JSONArray pd=prev.optJSONArray("devices");
    if(pd!=null&&pd.length()>0)result.put("devices",pd).put("observed",prev.opt("observed")).put("noise",prev.opt("noise")).put("cached",true);}catch(Exception ignored){}
   result.put("checked",System.currentTimeMillis()/1000.0);
  }
  return result;
 }
 static Set<String> connected(JSONObject state)throws Exception{Set<String> set=new HashSet<>();JSONArray ds=state.getJSONArray("devices");for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);if(d.getBoolean("connected"))set.add(d.getString("address"));}return set;}
 static void snapshot(Context c,JSONObject state)throws Exception{try(FileOutputStream out=new FileOutputStream(new File(c.getFilesDir(),"snapshot.json"))){out.write(state.toString().getBytes("UTF-8"));}}
 static String label(Context c,String address,JSONArray devices)throws Exception{
  JSONObject roles=config(c).optJSONObject("roles");if(roles!=null){Iterator<String> it=roles.keys();while(it.hasNext()){String k=it.next();if(roles.getString(k).equalsIgnoreCase(address))return k;}}
  if(devices!=null)for(int i=0;i<devices.length();i++)if(devices.getJSONObject(i).optString("address").equalsIgnoreCase(address))return "device#"+(i+1);return "device#?";
 }
 /** Overview-shaped state: a verified headset read merged with the latest known controllers and roles. */
 static JSONObject fullState(Context c,JSONObject read,String source,JSONObject view)throws Exception{
  JSONObject base=view!=null?view:LAST_OVERVIEW;if(base==null){File f=new File(c.getFilesDir(),"snapshot.json");if(f.exists())try(FileInputStream in=new FileInputStream(f)){base=new JSONObject(read(in,65536));}catch(Exception ignored){}}
  double observed=read.optDouble("observed",System.currentTimeMillis()/1000.0);if(Double.isNaN(observed)||observed==0)observed=System.currentTimeMillis()/1000.0;
  JSONObject entry=new JSONObject().put("controller",source).put("node",source.equals("phone")?"Phone":source).put("reachable",true).put("observed",observed).put("devices",read.getJSONArray("devices")).put("battery",read.has("battery")?read.get("battery"):JSONObject.NULL).put("noise",read.has("noise")?read.get("noise"):JSONObject.NULL);
  JSONArray controllers=new JSONArray();boolean replaced=false;JSONArray old=base==null?null:base.optJSONArray("controllers");
  if(old!=null)for(int i=0;i<old.length();i++){JSONObject s=old.getJSONObject(i);if(source.equals(s.optString("controller"))){controllers.put(entry);replaced=true;}else controllers.put(s);}
  if(!replaced)controllers.put(entry);
  if(LOCAL_OK&&!source.equals("phone")){boolean seen=false;for(int i=0;i<controllers.length();i++){JSONObject s=controllers.getJSONObject(i);if("phone".equals(s.optString("controller"))){s.put("reachable",true).remove("checking");s.remove("error");seen=true;}}if(!seen)controllers.put(new JSONObject().put("controller","phone").put("node","Phone").put("reachable",true).put("devices",new JSONArray()));}
  JSONObject roles=new JSONObject((base!=null&&base.optJSONObject("roles")!=null?base.getJSONObject("roles"):(config(c).optJSONObject("roles")==null?new JSONObject():config(c).getJSONObject("roles"))).toString());
  JSONArray ds=read.getJSONArray("devices");for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);if(d.optBoolean("current"))roles.put(source,d.getString("address"));}
  JSONObject known=config(c).optJSONObject("roles");
  JSONObject result=new JSONObject().put("controllers",controllers).put("devices",ds).put("roles",roles).put("reachable",true).put("battery",entry.get("battery")).put("capacity",2).put("here","phone").put("known_roles",known==null?new JSONObject():known).put("observed",observed).put("cached",false).put("noise",entry.get("noise"));
  snapshot(c,result);if(LAST_OVERVIEW==null)LAST_OVERVIEW_AT=Long.MIN_VALUE;LAST_OVERVIEW=result;
  return result;
 }
 static JSONObject awaitRead(Client client,String target,boolean wantConnected,long waitMs,long startNs)throws Exception{
  long deadline=startNs+TimeUnit.MILLISECONDS.toNanos(waitMs);
  while(true){JSONObject s=client.status(false,false);if(connected(s).contains(target)==wantConnected)return s;long left=TimeUnit.NANOSECONDS.toMillis(deadline-System.nanoTime());if(left<=0)return null;Thread.sleep(Math.min(POLL_MS,left));}
 }
 static Client open(Context c)throws Exception{try{return new Client(c);}catch(Exception e){IDENT_OK=false;throw new Unreachable(e);}}
 static JSONObject action(Context c,JSONObject data)throws Exception{return action(c,data,-1,null);}
 static JSONObject action(Context c,JSONObject data,long preludeMs,String mode)throws Exception{
  long start=System.nanoTime();Map<String,Long> t=new LinkedHashMap<>();if(preludeMs>=0)t.put("prelude",preludeMs);String outcome="ok",target="-";
  try{synchronized(LOCK){try(Client client=open(c)){
  if(data.getString("action").equals("noise")){
   Object level=data.get("level"),enabled=data.get("enabled");if(!(level instanceof Integer)||!(enabled instanceof Boolean))throw new IOException("Invalid noise-control values");
   JSONObject result;try{long s0=System.nanoTime();if(!IDENT_OK){byte[] id=client.get(0,3,new byte[0]);if(id.length!=3||id[0]!=0x40||id[1]!=0x24)throw new IOException("This controller supports only the Bose NC700");IDENT_OK=true;}add(t,"before",s0);
    long s1=System.nanoTime();result=client.setNoise((Integer)level,(Boolean)enabled);add(t,"command",s1);}catch(Exception e){IDENT_OK=false;throw e;}
   JSONObject fresh=null;try{fresh=client.status(false,false);}catch(Exception ignored){}
   JSONObject reply=new JSONObject().put("ok",true).put("verified",true).put("noise",result).put("message","Noise cancellation updated");
   if(fresh==null)return reply;
   return reply.put("state",fullState(c,fresh.put("noise",result).put("observed",System.currentTimeMillis()/1000.0),"phone",null));
  }
  String a=data.getString("action");target=data.getString("address").toUpperCase(Locale.ROOT);String replace=data.optString("replace").toUpperCase(Locale.ROOT);address(target);if(!a.equals("connect")&&!a.equals("disconnect"))throw new IOException("Unknown action");
  JSONObject before;try{long s0=System.nanoTime();before=client.status(true,!IDENT_OK);IDENT_OK=true;add(t,"before",s0);}catch(Exception e){IDENT_OK=false;throw e;}
  JSONArray ds=before.getJSONArray("devices");Set<String> anchors=new HashSet<>(),current=new HashSet<>(),all=new HashSet<>();
  JSONObject roles=config(c).optJSONObject("roles");if(roles!=null){Iterator<String> it=roles.keys();while(it.hasNext())anchors.add(roles.getString(it.next()));}
  JSONArray supplied=data.optJSONArray("anchors");if(supplied!=null)for(int i=0;i<supplied.length();i++)anchors.add(supplied.getString(i));
  for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);all.add(d.getString("address"));if(d.optBoolean("current")){anchors.add(d.getString("address"));current.add(d.getString("address"));}}
  target=label(c,target,ds);final String tgt=data.getString("address").toUpperCase(Locale.ROOT);
  Set<String> conn=connected(before);if(!all.contains(tgt))throw new IOException("Select a saved device");
  if(a.equals("connect")&&conn.contains(tgt)){outcome="already";return new JSONObject().put("ok",true).put("verified",true).put("message","Already connected").put("state",fullState(c,before,"phone",null));}
  if(a.equals("disconnect")&&!conn.contains(tgt)){outcome="already";return new JSONObject().put("ok",true).put("verified",true).put("message","Already disconnected").put("state",fullState(c,before,"phone",null));}
  if(a.equals("connect")&&conn.size()>=2&&replace.isEmpty())throw new Switcher.Fail("busy","Both slots are occupied");
  String drop=a.equals("disconnect")?tgt:replace;JSONObject interim=null;
  try{
   if(!drop.isEmpty()){if(!conn.contains(drop))throw new IOException("Device no longer connected; refresh");Set<String> remaining=new HashSet<>(conn);remaining.remove(drop);remaining.retainAll(anchors);if(remaining.isEmpty())throw new Switcher.Fail("keep_one","Keep one phone, PC or Mac connected for control");if(current.contains(drop))throw new Switcher.Fail("keep_one","Use another controller to disconnect the device providing access");
    long s0=System.nanoTime();client.action("disconnect",drop);add(t,"command",s0);long s1=System.nanoTime();interim=awaitRead(client,drop,false,DISCONNECT_WAIT_MS,s0);add(t,"verify",s1);if(interim==null)throw new Switcher.Fail("unverified","Disconnect not verified; no further commands sent");}
   JSONObject after;
   if(a.equals("connect")){long s0=System.nanoTime();client.action("connect",tgt);add(t,"command",s0);long s1=System.nanoTime();after=awaitRead(client,tgt,true,CONNECT_WAIT_MS,s0);add(t,"verify",s1);}else after=interim;
   if(after==null)throw new Switcher.Fail("unverified","Change not verified");
   after.put("battery",before.opt("battery")).put("noise",before.opt("noise")).put("observed",System.currentTimeMillis()/1000.0);
   return new JSONObject().put("ok",true).put("verified",true).put("message","Connection updated").put("state",fullState(c,after,"phone",null));
  }catch(Exception e){IDENT_OK=false;throw e;}
 }}}catch(Exception e){outcome="error:"+e.getClass().getSimpleName();throw e;}finally{timing(data.optString("action"),outcome,target,mode,t,(System.nanoTime()-start)/1000000+Math.max(preludeMs,0));}}
 static JSONObject adoptPeerState(Context c,JSONObject result,String source,JSONObject view)throws Exception{
  if(!result.optBoolean("ok")||!result.optBoolean("verified"))return result;
  JSONObject state=result.optJSONObject("state"),read;
  if(state!=null&&state.optJSONArray("devices")!=null)read=new JSONObject().put("devices",state.getJSONArray("devices")).put("battery",state.has("battery")?state.get("battery"):JSONObject.NULL).put("noise",state.has("noise")?state.get("noise"):JSONObject.NULL).put("observed",state.optDouble("observed",System.currentTimeMillis()/1000.0));
  else if(result.optJSONObject("noise")!=null)read=new JSONObject().put("devices",view.getJSONArray("devices")).put("battery",view.opt("battery")==null?JSONObject.NULL:view.opt("battery")).put("noise",result.getJSONObject("noise")).put("observed",System.currentTimeMillis()/1000.0);
  else return result.put("state",overview(c));
  return result.put("state",fullState(c,read,source,view));
 }
 static String role(Context c,String address)throws Exception{String l=label(c,address.toUpperCase(Locale.ROOT),null);return Switcher.LABELS.containsKey(l)?Switcher.LABELS.get(l):"-";}
 /** Logs one bose.switch line per connect/disconnect request; noise changes are not switches. */
 static JSONObject override(Context c,JSONObject data)throws Exception{
  String source=data.optString("source","android-app"),id=data.optString("request_id","-");
  boolean log=!data.optString("action").equals("noise");long start=System.nanoTime();String outcome="ok";
  try{JSONObject result=route(c,data);if(!result.optBoolean("ok")||!result.optBoolean("verified"))outcome="error:"+result.optString("error_key","unverified");return result;}
  catch(Exception e){outcome="error:"+keyOf(e);throw e;}
  finally{if(log){String t="-",r="-";try{t=role(c,data.optString("address"));r=data.optString("replace").isEmpty()?"-":role(c,data.optString("replace"));}catch(Exception ignored){}
   android.util.Log.i("BoseSwitch",Switcher.logLine(source,id,t,r,outcome,data.optString("via","local"),(System.nanoTime()-start)/1000000));}}
 }
 static JSONObject route(Context c,JSONObject data)throws Exception{
  long start=System.nanoTime();
  if(data.optString("action").equals("noise")&&LOCAL_OK){try{return action(c,data,0,"skipped");}catch(Unreachable ignored){LAST_OVERVIEW_AT=Long.MIN_VALUE;}}
  String drop=data.getString("action").equals("connect")?data.optString("replace"):data.optString("address");
  JSONObject view=null;String mode="fresh";JSONObject last=LAST_OVERVIEW;
  if(last!=null&&LAST_OVERVIEW_AT!=Long.MIN_VALUE&&(System.nanoTime()-LAST_OVERVIEW_AT)<=TimeUnit.MILLISECONDS.toNanos(PRELUDE_TTL_MS)&&usable(last,drop)){view=last;mode="reused";}
  if(view==null)view=overview(c,drop);
  long preludeMs=(System.nanoTime()-start)/1000000;
  JSONArray anchors=new JSONArray();JSONObject roles=view.getJSONObject("roles");Iterator<String> it=roles.keys();while(it.hasNext())anchors.put(roles.getString(it.next()));data.put("anchors",anchors);
  if(data.optString("action").equals("connect")&&data.optString("address").equals(roles.optString("pc"))){JSONArray ps=config(c).getJSONArray("peers");for(int i=0;i<ps.length();i++){JSONObject p=ps.getJSONObject(i);if(p.optString("id").equals("pc")){JSONObject prepared=peer(c,p,"/api/prepare-connect",new JSONObject().put("address",data.getString("address")));if(!prepared.optBoolean("ok"))throw new IOException(prepared.optString("error","PC Bluetooth unavailable"));}}}
  JSONArray states=view.getJSONArray("controllers");
  for(int i=0;i<states.length();i++){JSONObject s=states.getJSONObject(i);if(!s.optBoolean("reachable"))continue;boolean dropping=false;JSONArray ds=s.getJSONArray("devices");for(int k=0;k<ds.length();k++){JSONObject d=ds.getJSONObject(k);if(d.optBoolean("current")&&d.getString("address").equals(drop))dropping=true;}if(dropping)continue;if(s.getString("controller").equals("phone"))return action(c,data,preludeMs,mode);JSONArray ps=config(c).getJSONArray("peers");for(int k=0;k<ps.length();k++){JSONObject p=ps.getJSONObject(k);if(p.getString("id").equals(s.getString("controller"))){long sent=System.nanoTime();JSONObject result=peer(c,p,"/api/action",data);Map<String,Long> t=new LinkedHashMap<>();t.put("prelude",preludeMs);t.put("relay",(System.nanoTime()-sent)/1000000);timing(data.optString("action"),result.optBoolean("ok")?"ok":"error",label(c,data.optString("address").toUpperCase(Locale.ROOT),view.optJSONArray("devices")),mode,t,(System.nanoTime()-start)/1000000);data.put("via","peer:"+s.getString("controller"));return adoptPeerState(c,result,s.getString("controller"),view);}}}
  throw new Switcher.Fail("keep_one","No controller can make this change while retaining access");
 }
 /** One-tap "move the headset here" (here = this phone) per tests/switch-contract.json. Reply shape = POST /api/switch. */
 static final Object SWITCH_LOCK=new Object();
 static JSONObject switchHere(Context c,String source,String requestId,String replace){
  synchronized(SWITCH_LOCK){
   Switcher.Env env=new Switcher.Env(){
    public long millis(){return System.nanoTime()/1000000;}
    public void log(String line){android.util.Log.i("BoseSwitch",line);}
    public Map<String,String> roles()throws Exception{Map<String,String> m=new HashMap<>();JSONObject r=config(c).optJSONObject("roles");if(r!=null){Iterator<String> it=r.keys();while(it.hasNext()){String k=it.next();m.put(k,r.getString(k));}}return m;}
   };
   // Same prelude and controller choice as override(): the phone may hold no slot, so a PC or Mac controller may have to do the work.
   return Switcher.switchHere(new Switcher.Mesh(){
    public JSONObject overview(boolean reuse)throws Exception{JSONObject last=LAST_OVERVIEW;if(reuse&&last!=null&&LAST_OVERVIEW_AT!=Long.MIN_VALUE&&(System.nanoTime()-LAST_OVERVIEW_AT)<=TimeUnit.MILLISECONDS.toNanos(PRELUDE_TTL_MS)&&usable(last,""))return last;return Core.overview(c,"");}
    public JSONObject override(JSONObject data)throws Exception{return route(c,data);}
   },env,source,requestId,replace);
  }
 }
 /** Mesh /api/action from a peer controller: runs it here and logs one bose.switch line (source/request_id optional). */
 static JSONObject relayAction(Context c,JSONObject data)throws Exception{
  long start=System.nanoTime();String outcome="ok";boolean log=data.optString("action").matches("connect|disconnect");
  try{JSONObject result=action(c,data);if(!result.optBoolean("ok"))outcome="error:"+result.optString("error_key","unverified");return result;}
  catch(Exception e){outcome="error:"+keyOf(e);throw e;}
  finally{if(log){String t="-",r="-";try{t=role(c,data.optString("address"));r=data.optString("replace").isEmpty()?"-":role(c,data.optString("replace"));}catch(Exception ignored){}
   android.util.Log.i("BoseSwitch",Switcher.logLine(data.optString("source"),data.optString("request_id"),t,r,outcome,"local",(System.nanoTime()-start)/1000000));}}
 }
 static boolean usable(JSONObject view,String drop)throws Exception{JSONArray states=view.optJSONArray("controllers");if(states==null)return false;for(int i=0;i<states.length();i++)if(eligible(states.getJSONObject(i),drop))return true;return false;}
 static JSONObject dispatch(Context c,String path,JSONObject data,boolean mesh)throws Exception{
  if(!mesh&&path.equals("/api/cached")){
   File f=new File(c.getFilesDir(),"snapshot.json");
   if(f.exists())try(FileInputStream in=new FileInputStream(f)){return new JSONObject(read(in,65536)).put("cached",true);}
   return new JSONObject().put("devices",new JSONArray()).put("roles",new JSONObject()).put("controllers",new JSONArray()).put("reachable",false).put("battery",JSONObject.NULL).put("here","phone").put("cached",true);
  }
  if(path.equals("/api/status"))return status(c);
  if(!mesh&&path.equals("/api/overview"))return overview(c);
  if(mesh&&path.equals("/api/action"))return relayAction(c,data);
  if(!mesh&&path.equals("/api/switch")){String replace=data==null?"":data.optString("replace");return switchHere(c,"android-app",data==null?null:data.optString("request_id",null),replace);}
  if(!mesh&&path.equals("/api/override"))return override(c,data);
  if(!mesh&&path.equals("/api/roles")){JSONObject conf=config(c),roles=data.getJSONObject("roles");Iterator<String> keys=roles.keys();while(keys.hasNext()){String key=keys.next();if(!Arrays.asList("pc","mac","phone").contains(key))throw new IOException("Unknown controller");address(roles.getString(key));}conf.put("roles",roles);save(c,conf);return new JSONObject().put("ok",true);}
  throw new IOException("Unknown request");
 }
}
