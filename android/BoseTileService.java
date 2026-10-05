package local.bose.connections;

import android.app.*;
import android.content.*;
import android.graphics.drawable.Icon;
import android.os.*;
import android.service.quicksettings.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.concurrent.*;

/** A compact Quick Settings panel backed by the same controller and cache. */
public class BoseTileService extends TileService {
 final Handler main=new Handler(Looper.getMainLooper());
 final ExecutorService work=Executors.newSingleThreadExecutor();
 AlertDialog dialog;LinearLayout content;JSONObject snapshot=new JSONObject(),replacement;
 boolean busy=false;String notice="";int generation=0;
 int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
 public void onStartListening(){super.onStartListening();Tile tile=getQsTile();if(tile!=null){tile.setLabel("Bose");tile.setState(Tile.STATE_INACTIVE);if(Build.VERSION.SDK_INT>=29)tile.setSubtitle("Connections · ANC");tile.updateTile();}}
 public void onClick(){super.onClick();if(isLocked())unlockAndRun(this::openPanel);else openPanel();}
 void openPanel(){
  if(dialog!=null&&dialog.isShowing())return;
  generation++;busy=false;notice="";replacement=null;
  content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);content.setPadding(dp(20),dp(8),dp(20),dp(8));
  ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.addView(content);
  dialog=new AlertDialog.Builder(this,android.R.style.Theme_DeviceDefault_Dialog_Alert).setTitle("Bose 700").setView(scroll).setNegativeButton("Close",null).setNeutralButton("App settings",(d,w)->openApp()).create();
  dialog.setOnDismissListener(d->{dialog=null;generation++;});
  try{snapshot=Core.dispatch(this,"/api/cached",null,false);}catch(Exception e){snapshot=new JSONObject();}
  render();showDialog(dialog);
  dialog.getWindow().setLayout(dp(340),WindowManager.LayoutParams.WRAP_CONTENT);
  refresh();
 }
 void openApp(){
  Intent intent=new Intent(this,ConnectionsActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
  if(Build.VERSION.SDK_INT>=34)startActivityAndCollapse(PendingIntent.getActivity(this,0,intent,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT));else startActivityAndCollapse(intent);
 }
 boolean live(){return snapshot.optBoolean("reachable")&&!snapshot.optBoolean("cached");}
 TextView text(String value){TextView view=new TextView(this);view.setText(value);view.setTextSize(14);view.setPadding(0,dp(5),0,dp(5));content.addView(view);return view;}
 void button(String label,boolean enabled,Runnable action){Button button=new Button(this);button.setText(label);button.setAllCaps(false);button.setEnabled(enabled&&!busy);button.setOnClickListener(v->action.run());content.addView(button,new LinearLayout.LayoutParams(-1,-2));}
 String label(JSONObject device){
  JSONObject roles=snapshot.optJSONObject("roles");String address=device.optString("address");
  if(roles!=null)for(String role:new String[]{"pc","mac","phone"})if(address.equals(roles.optString(role)))return role.equals("pc")?"PC":role.equals("mac")?"Mac":"Phone";
  return device.optString("name",address);
 }
 JSONArray devices(){JSONArray list=snapshot.optJSONArray("devices");return list==null?new JSONArray():list;}
 void render(){
  if(content==null||dialog==null)return;content.removeAllViews();JSONArray devices=devices();int connected=0;
  for(int i=0;i<devices.length();i++)if(devices.optJSONObject(i).optBoolean("connected"))connected++;
  text(busy?"Checking…":snapshot.optBoolean("cached")?"Last known connections":live()?connected+" / 2 connected":"Headset unavailable");
  if(!notice.isEmpty())text(notice);
  if(replacement!=null)text("Connect "+label(replacement)+" — disconnect:");
  for(int i=0;i<devices.length();i++){
   JSONObject device=devices.optJSONObject(i);if(device==null)continue;boolean on=device.optBoolean("connected");
   if(replacement!=null&&!on)continue;
   button((replacement!=null?"Disconnect ":on?"✓  ":"")+label(device)+(replacement!=null?"":on?" — Disconnect":" — Connect"),live(),()->choose(device));
  }
  if(replacement!=null)button("Cancel",true,()->{replacement=null;render();});
  JSONObject noise=snapshot.optJSONObject("noise");
  if(noise!=null&&replacement==null){
   TextView level=text(noise.optBoolean("enabled")?"Noise cancellation: "+noise.optInt("level")+" / 10":"Noise cancellation: Off");
   SeekBar slider=new SeekBar(this);slider.setMax(10);slider.setProgress(noise.optInt("level",10));slider.setEnabled(live()&&!busy);content.addView(slider);
   slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){public void onProgressChanged(SeekBar s,int value,boolean user){if(user)level.setText("Noise cancellation: "+value+" / 10");}public void onStartTrackingTouch(SeekBar s){}public void onStopTrackingTouch(SeekBar s){}});
   text("0 = aware · 10 = maximum");
   button("Apply noise level",live(),()->noise(slider.getProgress(),true));button("Noise cancellation off",live(),()->noise(slider.getProgress(),false));
  }
  button("Refresh",true,this::refresh);
 }
 void choose(JSONObject device){
  try{
   JSONObject data=new JSONObject();String address=device.getString("address");
   if(replacement!=null){data.put("action","connect").put("address",replacement.getString("address")).put("replace",address);replacement=null;perform(data);return;}
   boolean on=device.optBoolean("connected");int count=0;JSONArray list=devices();for(int i=0;i<list.length();i++)if(list.getJSONObject(i).optBoolean("connected"))count++;
   if(!on&&count>=2){replacement=device;render();return;}
   perform(data.put("action",on?"disconnect":"connect").put("address",address));
  }catch(Exception e){notice=e.getMessage();render();}
 }
 void noise(int level,boolean enabled){try{perform(new JSONObject().put("action","noise").put("level",level).put("enabled",enabled));}catch(Exception e){notice=e.getMessage();render();}}
 void refresh(){if(busy)return;request(null);}
 void perform(JSONObject data){if(busy||!live())return;request(data);}
 void request(JSONObject action){
  busy=true;notice=action==null?"":"Updating…";render();final int id=generation;
  work.submit(()->{
   JSONObject state=null;String message="";
   try{
    if(action!=null){JSONObject result=Core.override(this,action);if(!result.optBoolean("ok")||!result.optBoolean("verified"))throw new Exception(result.optString("error","Change not verified; refresh before retrying"));message=result.optString("message","Updated");}
    state=Core.overview(this);
   }catch(Exception e){message=e.getMessage()==null?"Controller unavailable":e.getMessage();}
   final JSONObject result=state;final String note=message;
   main.post(()->{if(id!=generation||dialog==null)return;busy=false;notice=note;if(result!=null)snapshot=result;render();Tile tile=getQsTile();if(tile!=null){tile.setState(live()?Tile.STATE_ACTIVE:Tile.STATE_INACTIVE);tile.updateTile();}});
  });
 }
 public void onDestroy(){generation++;if(dialog!=null)dialog.dismiss();work.shutdown();super.onDestroy();}
}
