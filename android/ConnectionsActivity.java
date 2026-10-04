package local.bose.connections;
import android.Manifest;
import android.app.*;
import android.os.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.webkit.*;
import android.widget.*;
import android.text.InputType;
import org.json.*;
import java.util.concurrent.*;

public class ConnectionsActivity extends Activity {
 WebView web;ExecutorService work=Executors.newFixedThreadPool(4);
 public void onCreate(Bundle state){super.onCreate(state);web=new WebView(this);setContentView(web);web.getSettings().setJavaScriptEnabled(true);web.getSettings().setAllowFileAccess(false);web.getSettings().setAllowContentAccess(false);
  web.setWebViewClient(new WebViewClient(){public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest request){String url=request.getUrl().toString();if(!url.startsWith("https://bose.local/"))return new WebResourceResponse("text/plain","UTF-8",403,"Blocked",new java.util.HashMap<>(),new java.io.ByteArrayInputStream(new byte[0]));String path=request.getUrl().getPath();String name=path.equals("/")?"index.html":path.substring(1);if(!name.equals("index.html")&&!name.equals("app.js")&&!name.equals("style.css"))return null;try{return new WebResourceResponse(name.endsWith(".js")?"text/javascript":name.endsWith(".css")?"text/css":"text/html","UTF-8",getAssets().open("web/"+name));}catch(Exception e){return null;}}public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){return !request.getUrl().toString().startsWith("https://bose.local/");}});
  web.addJavascriptInterface(new Bridge(),"Android");web.loadUrl("https://bose.local/");
  if(Build.VERSION.SDK_INT>=31&&checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)!=PackageManager.PERMISSION_GRANTED){requestPermissions(Build.VERSION.SDK_INT>=33?new String[]{Manifest.permission.BLUETOOTH_CONNECT,Manifest.permission.POST_NOTIFICATIONS}:new String[]{Manifest.permission.BLUETOOTH_CONNECT},1);}else startRelay();
 }
 void startRelay(){try{startForegroundService(new Intent(this,RelayService.class));}catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}}
 public void onRequestPermissionsResult(int code,String[] permissions,int[] grants){super.onRequestPermissionsResult(code,permissions,grants);if(code==1&&grants.length>0&&grants[0]==PackageManager.PERMISSION_GRANTED){startRelay();web.evaluateJavascript("refresh()",null);}}
 class Bridge{
  @JavascriptInterface public void request(String id,String path,String body){work.submit(()->{JSONObject result;try{result=Core.dispatch(ConnectionsActivity.this,path,body.isEmpty()?null:new JSONObject(body),false);}catch(Exception e){result=Core.error(e);}String script="window.finishRequest("+JSONObject.quote(id)+","+JSONObject.quote(result.toString())+")";runOnUiThread(()->web.evaluateJavascript(script,null));});}
  @JavascriptInterface public void settings(){runOnUiThread(()->setup());}
 }
 void setup(){try{
  JSONObject conf=Core.config(this);LinearLayout form=new LinearLayout(this);form.setOrientation(1);form.setPadding(40,16,40,12);
  TextView info=new TextView(this);info.setText("Link your controllers over Tailscale. Bluetooth control works without these links.");form.addView(info);
  EditText headset=new EditText(this);headset.setHint("Bose 700 Bluetooth address");headset.setText(conf.optString("headset"));form.addView(headset);
  EditText code=new EditText(this);code.setHint("Private connection code");code.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);code.setText(conf.optString("token"));form.addView(code);
  EditText pc=new EditText(this);pc.setHint("PC Tailscale IPv4 address");EditText mac=new EditText(this);mac.setHint("Mac Tailscale IPv4 address");JSONArray peers=conf.getJSONArray("peers");for(int i=0;i<peers.length();i++){JSONObject p=peers.getJSONObject(i);String host=new java.net.URL(p.getString("url")).getHost();if(p.getString("id").equals("pc"))pc.setText(host);if(p.getString("id").equals("mac"))mac.setText(host);}form.addView(pc);form.addView(mac);
  new AlertDialog.Builder(this).setTitle("Controller links").setView(form).setNegativeButton("Cancel",null).setNeutralButton("Stop background relay",(d,w)->stopService(new Intent(this,RelayService.class))).setPositiveButton("Save",(d,w)->{try{String p=pc.getText().toString().trim(),m=mac.getText().toString().trim();Core.address(headset.getText().toString().trim());if((!p.isEmpty()&&!Core.tailnet(p))||(!m.isEmpty()&&!Core.tailnet(m)))throw new Exception("Use Tailscale IPv4 addresses");String token=code.getText().toString().trim();if(!token.isEmpty()&&token.length()<32)throw new Exception("Use the private connection code from your controller setup");JSONArray links=new JSONArray();if(!p.isEmpty())links.put(new JSONObject().put("id","pc").put("name","PC").put("url","http://"+p+":8848"));if(!m.isEmpty())links.put(new JSONObject().put("id","mac").put("name","Mac").put("url","http://"+m+":8848"));conf.put("headset",headset.getText().toString().trim().toUpperCase(java.util.Locale.ROOT)).put("token",token).put("peers",links);Core.save(this,conf);startRelay();web.evaluateJavascript("refresh()",null);}catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}}).show();
 }catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}}
 protected void onDestroy(){work.shutdownNow();web.removeJavascriptInterface("Android");web.destroy();super.onDestroy();}
}
