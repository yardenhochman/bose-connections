package local.bose.connections;
import android.content.Context;
import android.bluetooth.*;
import org.json.*;
import java.io.*;
import java.nio.file.*;

/** Core.java findings that are real bugs (docs/state-machines.md 8), driven in the JVM with stub Android types
 (tests/android/shim/android): a phone whose headset link is gone. Prints PASS/FAIL lines. */
public class CoreTest {
 static int failures=0,count=0;
 static void check(String name,boolean ok,String why){count++;System.out.println((ok?"PASS ":"FAIL ")+name+(ok?"":": "+why));if(!ok)failures++;}
 static Context context(File dir,boolean bluetoothOn){
  return new Context(){
   public File getFilesDir(){return dir;}
   public Object getSystemService(String name){return new BluetoothManager(new BluetoothAdapter(bluetoothOn));}
  };
 }
 public static void main(String[] args)throws Exception{
  File dir=Files.createTempDirectory("bose-core-test").toFile();
  Files.write(new File(dir,"config.json").toPath(),"{\"id\":\"phone\",\"headset\":\"AA:00:00:00:00:09\",\"token\":\"\",\"roles\":{\"pc\":\"AA:00:00:00:00:03\"},\"peers\":[]}".getBytes("UTF-8"));
  for(boolean on:new boolean[]{true,false}){
   // LOCAL_OK said "this phone read the headset". It was set by a good read and cleared only by a failed overview probe,
   // so after the link dropped every noise write still went to Bluetooth first, and fullState marked the phone as a
   // reachable controller in a peer's reply.
   Core.LOCAL_OK=true;Core.IDENT_OK=true;Context c=context(dir,on);
   String thrown="none";
   try{Core.action(c,new JSONObject().put("action","noise").put("level",5).put("enabled",true));}catch(Exception e){thrown=e.getClass().getSimpleName();}
   check("a local action that cannot open the headset is Unreachable (bluetooth "+(on?"on":"off")+")",thrown.equals("Unreachable"),thrown);
   check("and clears LOCAL_OK (bluetooth "+(on?"on":"off")+")",!Core.LOCAL_OK,"LOCAL_OK stayed true");
   JSONObject view=new JSONObject().put("controllers",new JSONArray()).put("roles",new JSONObject()).put("devices",new JSONArray());
   JSONObject read=new JSONObject().put("devices",new JSONArray()).put("observed",1.0);
   JSONObject state=Core.fullState(c,read,"pc",view);JSONArray cs=state.getJSONArray("controllers");boolean phoneShown=false;
   for(int i=0;i<cs.length();i++)if("phone".equals(cs.getJSONObject(i).optString("controller"))&&cs.getJSONObject(i).optBoolean("reachable"))phoneShown=true;
   check("a peer's reply no longer marks the phone reachable (bluetooth "+(on?"on":"off")+")",!phoneShown,state.toString());
  }
  System.out.println((failures==0?"PASS":"FAIL")+" android core: "+count+" checks, "+failures+" failures");
  System.exit(failures==0?0:1);
 }
}
