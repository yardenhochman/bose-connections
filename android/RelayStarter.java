package local.bose.connections;
import android.content.*;

/** Keeps the relay ready for peer controllers (pairing mode, status, switches): starts it after boot and after an app update. */
public class RelayStarter extends BroadcastReceiver {
 public void onReceive(Context c,Intent intent){start(c);}
 /** Starts the relay only once a token is configured; a failure (e.g. a background-start limit) is retried by the next trigger. */
 static void start(Context c){try{if(Core.config(c).optString("token").isEmpty())return;c.startForegroundService(new Intent(c,RelayService.class));}catch(Exception e){android.util.Log.w("BoseRelay","Relay not started: "+e);}}
}
