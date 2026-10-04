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
 static JSONObject error(Exception e){JSONObject o=new JSONObject();try{o.put("ok",false).put("reachable",false).put("error",e.getMessage()==null?e.getClass().getSimpleName():e.getMessage());}catch(Exception ignored){}return o;}
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
  byte[] request(int block,int func,int op,byte[] p,int wanted)throws Exception{
   out.write(new byte[]{(byte)block,(byte)func,(byte)op,(byte)p.length});out.write(p);out.flush();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
   for(int count=0;count<100;count++){
    byte[] h=exact(4,deadline);byte[] data=exact(h[3]&255,deadline);
    if((h[0]&255)!=block||(h[1]&255)!=func)continue;
    int kind=h[2]&15;
    if(kind==15)throw new IOException("Headset rejected command "+block+"."+func);
    if(kind==wanted)return data;
   }throw new IOException("No matching headset response");
  }
  byte[] get(int b,int f,byte[] p)throws Exception{return request(b,f,1,p,3);}
  JSONObject status()throws Exception{
   byte[] id=get(0,3,new byte[0]);if(id.length!=3||id[0]!=0x40||id[1]!=0x24)throw new IOException("This controller supports only the Bose NC700");
   byte[] list=get(4,4,new byte[0]);if(list.length<1||(list.length-1)%6!=0||list.length>49)throw new IOException("Unexpected device-list layout; refusing changes");
   JSONArray devices=new JSONArray();
   for(int i=1;i<list.length;i+=6){byte[] a=Arrays.copyOfRange(list,i,i+6),info=get(4,5,a);
    if(info.length<9||!Arrays.equals(a,Arrays.copyOfRange(info,0,6))||(info[6]!=0&&info[6]!=1&&info[6]!=3))throw new IOException("Unexpected device-info layout; refusing changes");
    String name=new String(info,9,info.length-9,"UTF-8").split("\u0000",2)[0];
    devices.put(new JSONObject().put("address",address(a)).put("name",name.isEmpty()?address(a):name).put("connected",info[6]!=0).put("current",info[6]==3));
   }
   Object battery=JSONObject.NULL;try{byte[] b=get(2,2,new byte[0]);if(b.length==1&&(b[0]&255)<=100)battery=b[0]&255;}catch(Exception ignored){}
   return new JSONObject().put("devices",devices).put("battery",battery).put("capacity",2).put("product","Bose 700");
  }
  void action(String action,String target)throws Exception{byte[] a=address(target);try{if(action.equals("connect")){byte[] p=new byte[7];System.arraycopy(a,0,p,1,6);request(4,1,5,p,7);}else if(action.equals("disconnect"))request(4,2,5,a,7);else throw new IOException("Unknown action");}catch(ReadTimeout unconfirmed){/* State verification is mandatory in Core.action. Do not resend. */}}
  public void close(){if(expiry!=null)expiry.cancel(false);timer.shutdownNow();try{if(socket!=null)socket.close();}catch(Exception ignored){}}
 }
 static JSONObject status(Context c){synchronized(LOCK){try(Client client=new Client(c)){return client.status().put("reachable",true).put("node","Phone").put("controller","phone").put("observed",System.currentTimeMillis()/1000.0);}catch(Exception e){JSONObject o=error(e);try{o.put("node","Phone").put("controller","phone").put("devices",new JSONArray());}catch(Exception ignored){}return o;}}}
 static JSONObject peer(Context c,JSONObject p,String path,JSONObject data){HttpURLConnection con=null;try{
  JSONObject conf=config(c);if(conf.optString("token").isEmpty())throw new IOException("Set up controller links to use the PC or Mac");
  URL url=new URL(p.getString("url")+path);if(!url.getProtocol().equals("http")||!tailnet(url.getHost()))throw new IOException("Controller must use its Tailscale IPv4 address");
  con=(HttpURLConnection)url.openConnection();con.setConnectTimeout(2000);con.setReadTimeout(data==null?35000:90000);con.setRequestProperty("Authorization","Bearer "+conf.getString("token"));
  if(data!=null){con.setRequestMethod("POST");con.setDoOutput(true);con.setRequestProperty("Content-Type","application/json");try(OutputStream out=con.getOutputStream()){out.write(data.toString().getBytes("UTF-8"));}}
  int code=con.getResponseCode();JSONObject result=new JSONObject(read(code>=400?con.getErrorStream():con.getInputStream(),65536));return result;
 }catch(Exception e){JSONObject o=error(e);try{o.put("controller",p.optString("id")).put("node",p.optString("name"));}catch(Exception ignored){}return o;}finally{if(con!=null)con.disconnect();}}
 static boolean tailnet(String ip){try{String[] p=ip.split("\\.");return p.length==4&&Integer.parseInt(p[0])==100&&Integer.parseInt(p[1])>=64&&Integer.parseInt(p[1])<=127;}catch(Exception e){return false;}}
 static JSONObject overview(Context c)throws Exception{
  JSONArray peers=config(c).optJSONArray("peers");ExecutorService pool=Executors.newFixedThreadPool(3);List<Future<JSONObject>> jobs=new ArrayList<>();
  try{jobs.add(pool.submit(()->status(c)));if(peers!=null)for(int i=0;i<peers.length();i++){final JSONObject p=peers.getJSONObject(i);jobs.add(pool.submit(()->peer(c,p,"/api/status",null)));}
   JSONArray states=new JSONArray(),devices=new JSONArray();JSONObject roles=new JSONObject(config(c).optJSONObject("roles")==null?"{}":config(c).getJSONObject("roles").toString());Object battery=JSONObject.NULL;boolean reachable=false;double freshest=0;
   for(Future<JSONObject> j:jobs){JSONObject s=j.get();states.put(s);if(s.optBoolean("reachable")){reachable=true;if(s.optDouble("observed")>=freshest){freshest=s.optDouble("observed");devices=s.getJSONArray("devices");battery=s.opt("battery");}JSONArray ds=s.getJSONArray("devices");for(int k=0;k<ds.length();k++){JSONObject d=ds.getJSONObject(k);if(d.optBoolean("current"))roles.put(s.getString("controller"),d.getString("address"));}}}
   JSONObject result=new JSONObject().put("controllers",states).put("devices",devices).put("roles",roles).put("reachable",reachable).put("battery",battery).put("capacity",2).put("here","phone").put("observed",freshest).put("cached",false);
   if(reachable)try(FileOutputStream out=new FileOutputStream(new File(c.getFilesDir(),"snapshot.json"))){out.write(result.toString().getBytes("UTF-8"));}
   return result;
  }finally{pool.shutdownNow();}
 }
 static Set<String> connected(JSONObject state)throws Exception{Set<String> set=new HashSet<>();JSONArray ds=state.getJSONArray("devices");for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);if(d.getBoolean("connected"))set.add(d.getString("address"));}return set;}
 static JSONObject action(Context c,JSONObject data)throws Exception{synchronized(LOCK){try(Client client=new Client(c)){
  String a=data.getString("action"),target=data.getString("address").toUpperCase(Locale.ROOT),replace=data.optString("replace").toUpperCase(Locale.ROOT);address(target);if(!a.equals("connect")&&!a.equals("disconnect"))throw new IOException("Unknown action");
  JSONObject before=client.status();JSONArray ds=before.getJSONArray("devices");Set<String> anchors=new HashSet<>(),current=new HashSet<>(),all=new HashSet<>();
  JSONObject roles=config(c).optJSONObject("roles");if(roles!=null){Iterator<String> it=roles.keys();while(it.hasNext())anchors.add(roles.getString(it.next()));}
  JSONArray supplied=data.optJSONArray("anchors");if(supplied!=null)for(int i=0;i<supplied.length();i++)anchors.add(supplied.getString(i));
  for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);all.add(d.getString("address"));if(d.optBoolean("current")){anchors.add(d.getString("address"));current.add(d.getString("address"));}}
  Set<String> conn=connected(before);if(!all.contains(target))throw new IOException("Select a saved device");
  if(a.equals("connect")&&conn.contains(target))return new JSONObject().put("ok",true).put("verified",true).put("message","Already connected");
  if(a.equals("connect")&&conn.size()>=2&&replace.isEmpty())throw new IOException("Both slots are occupied. Choose a device to replace.");
  String drop=a.equals("disconnect")?target:replace;
  if(!drop.isEmpty()){if(!conn.contains(drop))throw new IOException("Device no longer connected; refresh");Set<String> remaining=new HashSet<>(conn);remaining.remove(drop);remaining.retainAll(anchors);if(remaining.isEmpty())throw new IOException("Keep one phone, PC or Mac connected for control");if(current.contains(drop))throw new IOException("Use another controller to disconnect the device providing access");client.action("disconnect",drop);boolean verified=false;for(int i=0;i<6;i++){if(!connected(client.status()).contains(drop)){verified=true;break;}Thread.sleep(400);}if(!verified)throw new IOException("Disconnect not verified; no further commands sent");}
  if(a.equals("connect"))client.action("connect",target);
  for(int i=0;i<8;i++){JSONObject after=client.status();if(connected(after).contains(target)==a.equals("connect"))return new JSONObject().put("ok",true).put("verified",true).put("message","Connection updated").put("state",after);Thread.sleep(500);}throw new IOException("Change not verified. Refresh before trying again.");
 }}}
 static JSONObject override(Context c,JSONObject data)throws Exception{
  JSONObject view=overview(c);JSONArray anchors=new JSONArray();JSONObject roles=view.getJSONObject("roles");Iterator<String> it=roles.keys();while(it.hasNext())anchors.put(roles.getString(it.next()));data.put("anchors",anchors);
  String drop=data.getString("action").equals("connect")?data.optString("replace"):data.getString("address");JSONArray states=view.getJSONArray("controllers");
  for(int i=0;i<states.length();i++){JSONObject s=states.getJSONObject(i);if(!s.optBoolean("reachable"))continue;boolean dropping=false;JSONArray ds=s.getJSONArray("devices");for(int k=0;k<ds.length();k++){JSONObject d=ds.getJSONObject(k);if(d.optBoolean("current")&&d.getString("address").equals(drop))dropping=true;}if(dropping)continue;if(s.getString("controller").equals("phone"))return action(c,data);JSONArray ps=config(c).getJSONArray("peers");for(int k=0;k<ps.length();k++){JSONObject p=ps.getJSONObject(k);if(p.getString("id").equals(s.getString("controller")))return peer(c,p,"/api/action",data);}}
  throw new IOException("No controller can make this change while retaining access");
 }
 static JSONObject dispatch(Context c,String path,JSONObject data,boolean mesh)throws Exception{
  if(!mesh&&path.equals("/api/cached")){
   File f=new File(c.getFilesDir(),"snapshot.json");
   if(f.exists())try(FileInputStream in=new FileInputStream(f)){return new JSONObject(read(in,65536)).put("cached",true);}
   return new JSONObject().put("devices",new JSONArray()).put("roles",new JSONObject()).put("controllers",new JSONArray()).put("reachable",false).put("battery",JSONObject.NULL).put("here","phone").put("cached",true);
  }
  if(path.equals("/api/status"))return status(c);
  if(!mesh&&path.equals("/api/overview"))return overview(c);
  if(mesh&&path.equals("/api/action"))return action(c,data);
  if(!mesh&&path.equals("/api/override"))return override(c,data);
  if(!mesh&&path.equals("/api/roles")){JSONObject conf=config(c),roles=data.getJSONObject("roles");Iterator<String> keys=roles.keys();while(keys.hasNext()){String key=keys.next();if(!Arrays.asList("pc","mac","phone").contains(key))throw new IOException("Unknown controller");address(roles.getString(key));}conf.put("roles",roles);save(c,conf);return new JSONObject().put("ok",true);}
  throw new IOException("Unknown request");
 }
}
