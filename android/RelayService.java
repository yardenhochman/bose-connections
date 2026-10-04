package local.bose.connections;
import android.app.*;
import android.content.*;
import android.os.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;
import java.security.MessageDigest;

public class RelayService extends Service{
 volatile boolean running;volatile ServerSocket server;Thread listener;ExecutorService workers=Executors.newFixedThreadPool(4);
 public void onCreate(){super.onCreate();NotificationManager manager=getSystemService(NotificationManager.class);manager.createNotificationChannel(new NotificationChannel("relay","Headphone control",NotificationManager.IMPORTANCE_LOW));Intent open=new Intent(this,ConnectionsActivity.class);PendingIntent pi=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_IMMUTABLE);startForeground(700,new Notification.Builder(this,"relay").setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).setContentTitle("Bose Connections").setContentText("Phone control is available. Tap to choose a device.").setContentIntent(pi).setOngoing(true).build());running=true;listener=new Thread(()->listen());listener.start();}
 String tailAddress()throws Exception{Enumeration<NetworkInterface> interfaces=NetworkInterface.getNetworkInterfaces();while(interfaces.hasMoreElements()){Enumeration<InetAddress> ips=interfaces.nextElement().getInetAddresses();while(ips.hasMoreElements()){String ip=ips.nextElement().getHostAddress();if(Core.tailnet(ip))return ip;}}return null;}
 void listen(){while(running){try{String ip=tailAddress();if(ip==null||Core.config(this).optString("token").isEmpty()){Thread.sleep(5000);continue;}server=new ServerSocket();server.setReuseAddress(true);server.bind(new InetSocketAddress(ip,8848));server.setSoTimeout(5000);while(running){try{Socket client=server.accept();workers.submit(()->handle(client));}catch(SocketTimeoutException e){if(!ip.equals(tailAddress()))break;}}}catch(Exception e){if(running)try{Thread.sleep(5000);}catch(InterruptedException ignored){}}finally{try{if(server!=null)server.close();}catch(Exception ignored){}}}}
 static String line(InputStream in)throws IOException{ByteArrayOutputStream b=new ByteArrayOutputStream();int c;while((c=in.read())!=-1){if(c=='\n')break;if(c!='\r')b.write(c);if(b.size()>4096)throw new IOException("Header too large");}return b.toString("UTF-8");}
 void handle(Socket socket){try(Socket client=socket){client.setSoTimeout(5000);if(!Core.tailnet(client.getInetAddress().getHostAddress()))return;InputStream in=client.getInputStream();String[] first=line(in).split(" ");if(first.length!=3)return;Map<String,String> headers=new HashMap<>();for(int i=0;i<64;i++){String l=line(in);if(l.isEmpty())break;int colon=l.indexOf(':');if(colon>0)headers.put(l.substring(0,colon).toLowerCase(Locale.ROOT),l.substring(colon+1).trim());}String token=Core.config(this).optString("token");boolean authorized=token.length()>=32&&MessageDigest.isEqual(("Bearer "+token).getBytes("UTF-8"),headers.getOrDefault("authorization","").getBytes("UTF-8"));JSONObject result;int status=200;
 if(!authorized){status=403;result=new JSONObject().put("error","Access denied");}
 else if(first[0].equals("GET")&&first[1].equals("/api/status"))result=Core.status(this);
 else if(first[0].equals("POST")&&first[1].equals("/api/action")){int size=Integer.parseInt(headers.getOrDefault("content-length","0"));if(size<=0||size>4096)throw new IOException("Invalid request size");byte[] b=new byte[size];new DataInputStream(in).readFully(b);try{result=Core.action(this,new JSONObject(new String(b,"UTF-8")));}catch(Exception e){status=400;result=Core.error(e);}}
 else{status=404;result=new JSONObject().put("error","Not found");}
 byte[] raw=result.toString().getBytes("UTF-8");OutputStream out=client.getOutputStream();out.write(("HTTP/1.1 "+status+" Result\r\nContent-Type: application/json\r\nContent-Length: "+raw.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));out.write(raw);out.flush();
 }catch(Exception ignored){}}
 public int onStartCommand(Intent intent,int flags,int startId){return START_STICKY;}
 public IBinder onBind(Intent intent){return null;}
 public void onDestroy(){running=false;try{if(server!=null)server.close();}catch(Exception ignored){}listener.interrupt();workers.shutdownNow();super.onDestroy();}
}
