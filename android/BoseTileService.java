package local.bose.connections;

import android.animation.ValueAnimator;
import android.app.*;
import android.content.*;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.*;
import android.graphics.drawable.*;
import android.os.*;
import android.service.quicksettings.*;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.*;
import android.view.animation.DecelerateInterpolator;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;

/** Quick Settings tile and its compact native panel ("pulse" design, Mist sleeve tokens). */
public class BoseTileService extends TileService {
 final Handler main=new Handler(Looper.getMainLooper());
 final ExecutorService work=Executors.newSingleThreadExecutor();
 JSONObject snapshot=new JSONObject();
 Dialog dialog;Panel panel;int generation=0;long lastRead=0;boolean reading=false;
 // Connection mutation (one in flight per client).
 boolean mutating=false;String pendingAction,pendingAddress,pendingReplace;JSONObject replacing;
 // Noise writes: one in flight + the latest queued value, >=250 ms between write starts.
 boolean ancInFlight=false;int[] ancQueued;long ancLastStart=0;Integer shownLevel;Boolean shownEnabled;
 String notice="";boolean noticeError=false;

 int dp(float n){return Math.round(n*getResources().getDisplayMetrics().density);}
 int color(int id){return getColor(id);}

 // ---- Tile ----
 public void onStartListening(){
  super.onStartListening();
  boolean fresh=live()&&SystemClock.elapsedRealtime()-lastRead<30000;
  if(dialog==null&&!busy()&&!fresh)try{snapshot=Core.dispatch(this,"/api/cached",null,false);}catch(Exception e){snapshot=new JSONObject();}
  updateTile();
  if(dialog==null&&!busy()&&!reading&&SystemClock.elapsedRealtime()-lastRead>30000)refresh();
 }
 public void onClick(){super.onClick();if(isLocked())unlockAndRun(this::openPanel);else openPanel();}
 void updateTile(){
  Tile tile=getQsTile();if(tile==null)return;
  tile.setLabel("Bose");tile.setState(live()&&connectedCount()>=1?Tile.STATE_ACTIVE:Tile.STATE_INACTIVE);
  if(Build.VERSION.SDK_INT>=29)tile.setSubtitle(tileSubtitle());
  tile.updateTile();
 }
 String tileSubtitle(){
  if(mutating)return "connect".equals(pendingAction)?"Connecting…":"Disconnecting…";
  if(ancInFlight)return "Updating…";
  boolean cached=snapshot.optBoolean("cached");
  if(!cached&&!snapshot.optBoolean("reachable"))return snapshot.has("reachable")?"Unavailable":"Checking…";
  if(cached&&devices().length()==0)return reading?"Checking…":"Unavailable";
  JSONObject noise=snapshot.optJSONObject("noise");
  return connectedCount()+" of 2"+(noise==null?"":noise.optBoolean("enabled")?" · ANC "+noise.optInt("level"):" · ANC off");
 }

 // ---- State helpers ----
 boolean live(){return snapshot.optBoolean("reachable")&&!snapshot.optBoolean("cached");}
 boolean busy(){return mutating||ancInFlight;}
 JSONArray devices(){JSONArray list=snapshot.optJSONArray("devices");return list==null?new JSONArray():list;}
 int connectedCount(){int n=0;JSONArray ds=devices();for(int i=0;i<ds.length();i++){JSONObject d=ds.optJSONObject(i);if(d!=null&&d.optBoolean("connected"))n++;}return n;}
 JSONObject device(String address){JSONArray ds=devices();for(int i=0;i<ds.length();i++){JSONObject d=ds.optJSONObject(i);if(d!=null&&address!=null&&address.equals(d.optString("address")))return d;}return null;}
 String role(JSONObject device){
  JSONObject roles=snapshot.optJSONObject("roles");String address=device.optString("address");
  if(roles!=null)for(String r:new String[]{"phone","pc","mac"})if(address.equals(roles.optString(r)))return r;
  return "";
 }
 String name(JSONObject device){String n=device.optString("name");return n.isEmpty()?device.optString("address"):n;}
 String tag(JSONObject device){
  String r=role(device),here=snapshot.optString("here","phone");
  if(!r.isEmpty()&&r.equals(here))return r.equals("pc")?"This PC":r.equals("mac")?"This Mac":"This phone";
  return r.equals("pc")?"PC":r.equals("mac")?"Mac":r.equals("phone")?"Phone":"Other device";
 }
 int icon(JSONObject device){
  String r=role(device),n=name(device).toLowerCase(Locale.ROOT);
  if(r.equals("phone")||n.matches(".*\\b(phone|pixel|galaxy|iphone)\\b.*"))return R.drawable.ic_qs_phone;
  if(r.equals("mac")||n.matches(".*\\b(mac|macbook|laptop|notebook)\\b.*"))return R.drawable.ic_qs_laptop;
  if(n.matches(".*\\b(tv|television)\\b.*"))return R.drawable.ic_qs_tv;
  if(r.equals("pc")||n.matches(".*\\b(pc|desktop)\\b.*"))return R.drawable.ic_qs_desktop;
  return R.drawable.ic_qs_device;
 }
 static boolean overviewShaped(JSONObject s){return s!=null&&s.has("devices")&&s.has("reachable");}

 // ---- Transport (a build with BuildFlags.PREVIEW may simulate the headset from files/preview.json for offscreen review) ----
 File previewFile(){return BuildFlags.PREVIEW?new File(getFilesDir(),"preview.json"):null;}
 JSONObject readOverview()throws Exception{
  File f=previewFile();
  if(f!=null&&f.exists())try(FileInputStream in=new FileInputStream(f)){JSONObject s=new JSONObject(Core.read(in,65536));Thread.sleep(s.optLong("readDelay",400));return s.put("cached",false);}
  return Core.overview(this);
 }
 JSONObject override(JSONObject data)throws Exception{
  File f=previewFile();
  if(f==null||!f.exists())return Core.override(this,data);
  JSONObject s;try(FileInputStream in=new FileInputStream(f)){s=new JSONObject(Core.read(in,65536));}
  Thread.sleep(s.optLong("delay",1200));
  if(s.optBoolean("fail"))throw new IOException("The headset did not confirm the change");
  String action=data.getString("action");
  if(action.equals("noise"))s.put("noise",new JSONObject().put("level",data.getInt("level")).put("enabled",data.getBoolean("enabled")));
  else{JSONArray ds=s.getJSONArray("devices");for(int i=0;i<ds.length();i++){JSONObject d=ds.getJSONObject(i);
   if(d.getString("address").equals(data.getString("address")))d.put("connected",action.equals("connect"));
   if(d.getString("address").equals(data.optString("replace")))d.put("connected",false);}}
  try(FileOutputStream out=new FileOutputStream(f)){out.write(s.toString().getBytes("UTF-8"));}
  return new JSONObject().put("ok",true).put("verified",true).put("message",action.equals("noise")?"Noise cancellation updated":"Connection updated").put("state",s.put("cached",false));
 }

 // ---- Requests ----
 void refresh(){
  if(reading)return;reading=true;final int id=generation;if(panel!=null)panel.render();
  work.submit(()->{
   JSONObject state=null;String error=null;
   try{state=readOverview();}catch(Exception e){error=e.getMessage()==null?"Controller unavailable":e.getMessage();}
   final JSONObject read=state;final String problem=error;
   main.post(()->{reading=false;lastRead=SystemClock.elapsedRealtime();
    if(read!=null&&!busy())snapshot=read;
    if(id==generation&&panel!=null){if(problem!=null&&notice.isEmpty())setNotice(problem,true);panel.render();}
    updateTile();});
  });
 }
 void setNotice(String text,boolean error){notice=text==null?"":text;noticeError=error;}
 void connect(JSONObject device){
  if(!live()||busy())return;
  if(connectedCount()>=2){replacing=device;setNotice("",false);panel.render();return;}
  mutate("connect",device.optString("address"),null);
 }
 void mutate(String action,String address,String replace){
  if(!live()||busy())return;
  mutating=true;pendingAction=action;pendingAddress=address;pendingReplace=replace;replacing=null;setNotice("",false);
  if(panel!=null)panel.render();updateTile();final int id=generation;
  work.submit(()->{
   JSONObject state=null;String message,error=null;
   try{
    JSONObject data=new JSONObject().put("action",action).put("address",address);if(replace!=null)data.put("replace",replace);
    JSONObject result=override(data);
    if(!result.optBoolean("ok")||!result.optBoolean("verified"))throw new IOException(result.optString("error",result.optString("message","Change not verified; refresh before retrying")));
    message=result.optString("message","Connection updated");state=result.optJSONObject("state");
    if(!overviewShaped(state))state=readOverview();
   }catch(Exception e){message=null;error=e.getMessage()==null?"Controller unavailable":e.getMessage();}
   final JSONObject verified=state;final String ok=message,problem=error;
   main.post(()->{
    mutating=false;pendingAction=pendingAddress=pendingReplace=null;
    if(verified!=null){snapshot=verified;lastRead=SystemClock.elapsedRealtime();setNotice(ok,false);}else setNotice(problem,true);
    if(id==generation&&panel!=null)panel.render();updateTile();
    if(verified==null)refresh();
   });
  });
 }
 void requestNoise(int level,boolean enabled){
  if(!live()||mutating)return;
  shownLevel=level;shownEnabled=enabled;
  if(ancInFlight){ancQueued=new int[]{level,enabled?1:0};if(panel!=null)panel.render();return;}
  sendNoise(level,enabled);
 }
 void sendNoise(int level,boolean enabled){
  ancInFlight=true;setNotice("",false);if(panel!=null)panel.render();updateTile();
  long wait=Math.max(0,250-(SystemClock.elapsedRealtime()-ancLastStart));final int id=generation;
  main.postDelayed(()->{
   ancLastStart=SystemClock.elapsedRealtime();
   work.submit(()->{
    JSONObject result=null;String error=null;
    try{
     result=override(new JSONObject().put("action","noise").put("level",level).put("enabled",enabled));
     if(!result.optBoolean("ok")||!result.optBoolean("verified"))throw new IOException(result.optString("error","Noise cancellation not verified"));
    }catch(Exception e){result=null;error=e.getMessage()==null?"Controller unavailable":e.getMessage();}
    final JSONObject done=result;final String problem=error;
    main.post(()->noiseDone(id,done,problem));
   });
  },wait);
 }
 void noiseDone(int id,JSONObject result,String problem){
  ancInFlight=false;
  if(result==null){ancQueued=null;shownLevel=null;shownEnabled=null;setNotice(problem,true);}
  else{
   // Merge only noise/battery (and devices when present): a noise read-back may carry an empty device list.
   JSONObject state=result.optJSONObject("state");JSONObject noise=result.optJSONObject("noise");
   try{
    if(state!=null){if(state.optJSONObject("noise")!=null)noise=state.optJSONObject("noise");if(state.has("battery")&&!state.isNull("battery"))snapshot.put("battery",state.get("battery"));
     JSONArray ds=state.optJSONArray("devices");if(ds!=null&&ds.length()>0)snapshot.put("devices",ds);}
    if(noise!=null)snapshot.put("noise",noise);
   }catch(JSONException ignored){/* snapshot keys are plain strings; put cannot fail here */}
   int[] next=ancQueued;ancQueued=null;
   if(next!=null&&(noise==null||noise.optInt("level")!=next[0]||noise.optBoolean("enabled")!=(next[1]==1))){if(id==generation){sendNoise(next[0],next[1]==1);return;}}
   shownLevel=null;shownEnabled=null;setNotice(result.optString("message","Noise cancellation updated"),false);
  }
  if(id==generation&&panel!=null)panel.render();updateTile();
 }

 // ---- Panel ----
 void openPanel(){
  if(dialog!=null&&dialog.isShowing())return;
  generation++;setNotice("",false);replacing=null;shownLevel=null;shownEnabled=null;
  try{if(!mutating)snapshot=Core.dispatch(this,"/api/cached",null,false);}catch(Exception e){snapshot=new JSONObject();}
  buildDialog();
  // The shade may already be closing; the window token is then gone and the panel simply does not open.
  try{showDialog(dialog);}catch(WindowManager.BadTokenException e){dialog=null;panel=null;generation++;updateTile();return;}
  sizeWindow();refresh();
 }
 boolean night(){return (getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES;}
 void buildDialog(){
  dialog=new Dialog(this,night()?android.R.style.Theme_DeviceDefault_Dialog_NoActionBar:android.R.style.Theme_DeviceDefault_Light_Dialog_NoActionBar);
  panel=new Panel();dialog.setContentView(panel.root);
  final Dialog own=dialog;
  dialog.setOnDismissListener(d->{if(dialog==own){dialog=null;panel=null;generation++;replacing=null;}});
  panel.render();
 }
 void sizeWindow(){
  Window w=dialog.getWindow();if(w==null)return;
  w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
  int width=Math.min(dp(360),getResources().getDisplayMetrics().widthPixels-dp(32));
  w.setLayout(width,WindowManager.LayoutParams.WRAP_CONTENT);
 }
 public void onConfigurationChanged(Configuration config){
  super.onConfigurationChanged(config);
  // Light/dark switch while open: rebuild the content in the existing window (re-adding a QS dialog window can lose its token).
  if(dialog!=null&&dialog.isShowing()){panel=new Panel();dialog.setContentView(panel.root);panel.render();sizeWindow();}
 }
 void openApp(){
  Intent intent=new Intent(this,ConnectionsActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
  if(Build.VERSION.SDK_INT>=34)startActivityAndCollapse(PendingIntent.getActivity(this,0,intent,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT));else startActivityAndCollapse(intent);
 }

 class Panel {
  final Typeface regular=getResources().getFont(R.font.jost_regular),medium=getResources().getFont(R.font.jost_medium);
  final ScrollView root=new ScrollView(BoseTileService.this);
  final LinearLayout card=new LinearLayout(BoseTileService.this),cups=new LinearLayout(BoseTileService.this),rows=new LinearLayout(BoseTileService.this);
  final TextView sub,battery,notice,caption,ncSub,savedLabel;final Led subLed=new Led();
  final LinearLayout batteryBox,ncBox;final RidgeView ridges=new RidgeView();final Toggle anc=new Toggle();final SeekBar slider=new SeekBar(BoseTileService.this);
  final LinearLayout prompt=new LinearLayout(BoseTileService.this);TextView promptText;boolean rendering=false;String[] slotOrder=new String[2];

  Panel(){
   card.setOrientation(LinearLayout.VERTICAL);card.setPadding(dp(18),dp(18),dp(18),dp(12));
   card.setBackground(round(color(R.color.qs_ground),dp(28),0,0));card.setClipToOutline(true);card.setClipToPadding(false);
   root.addView(card);root.setVerticalScrollBarEnabled(false);
   // Header
   LinearLayout head=new LinearLayout(BoseTileService.this);head.setGravity(Gravity.TOP);card.addView(head);
   LinearLayout titles=new LinearLayout(BoseTileService.this);titles.setOrientation(LinearLayout.VERTICAL);head.addView(titles,new LinearLayout.LayoutParams(0,-2,1));
   TextView title=text("Bose 700",21,true,R.color.qs_ink);title.setIncludeFontPadding(false);titles.addView(title);
   LinearLayout subRow=new LinearLayout(BoseTileService.this);subRow.setGravity(Gravity.CENTER_VERTICAL);subRow.setPadding(0,dp(4),0,0);titles.addView(subRow);
   subRow.addView(subLed,new LinearLayout.LayoutParams(dp(13),dp(13)));
   sub=text("",13,false,R.color.qs_ink2);sub.setPadding(dp(5),0,0,0);subRow.addView(sub);
   batteryBox=new LinearLayout(BoseTileService.this);batteryBox.setGravity(Gravity.CENTER_VERTICAL);batteryBox.setPadding(0,dp(3),0,0);head.addView(batteryBox);
   ImageView batIcon=new ImageView(BoseTileService.this);batIcon.setImageResource(R.drawable.ic_qs_battery);batIcon.setImageTintList(ColorStateList.valueOf(color(R.color.qs_ink)));
   batteryBox.addView(batIcon,new LinearLayout.LayoutParams(dp(18),dp(18)));battery=text("",14,true,R.color.qs_ink);battery.setPadding(dp(5),0,0,0);batteryBox.addView(battery);
   notice=text("",13,false,R.color.qs_ink2);notice.setPadding(0,dp(6),0,0);card.addView(notice);
   // Outside-sound ridge band
   FrameLayout plot=new FrameLayout(BoseTileService.this);LinearLayout.LayoutParams pl=new LinearLayout.LayoutParams(-1,dp(84));pl.setMargins(-dp(18),dp(6),-dp(18),0);card.addView(plot,pl);
   plot.addView(ridges,new FrameLayout.LayoutParams(-1,-1));
   LinearLayout cap=new LinearLayout(BoseTileService.this);cap.setPadding(dp(18),0,dp(18),0);plot.addView(cap,new FrameLayout.LayoutParams(-1,-2));
   TextView capLeft=text("Outside sound",12,false,R.color.qs_ink2);cap.addView(capLeft,new LinearLayout.LayoutParams(0,-2,1));
   caption=text("",12,false,R.color.qs_ink2);cap.addView(caption);
   // Replace prompt (between ridge band and cups)
   prompt.setOrientation(LinearLayout.HORIZONTAL);prompt.setGravity(Gravity.CENTER_VERTICAL);prompt.setPadding(dp(12),dp(8),dp(8),dp(8));prompt.setVisibility(View.GONE);
   GradientDrawable pbg=round(0,dp(14),dp(1),color(R.color.qs_accent));pbg.setStroke(dp(1),color(R.color.qs_accent),dp(4),dp(3));prompt.setBackground(pbg);
   promptText=text("",13,false,R.color.qs_ink);prompt.addView(promptText,new LinearLayout.LayoutParams(0,-2,1));
   Button pc=button("Cancel",false);pc.setTextSize(14);pc.setPadding(dp(16),0,dp(16),0);pc.setOnClickListener(v->{replacing=null;setNotice("",false);render();});
   LinearLayout.LayoutParams pcl=new LinearLayout.LayoutParams(-2,dp(40));pcl.leftMargin=dp(10);prompt.addView(pc,pcl);
   LinearLayout.LayoutParams prl=new LinearLayout.LayoutParams(-1,-2);prl.topMargin=dp(6);card.addView(prompt,prl);
   // Slot cups
   cups.setOrientation(LinearLayout.HORIZONTAL);LinearLayout.LayoutParams cl=new LinearLayout.LayoutParams(-1,-2);cl.topMargin=dp(4);card.addView(cups,cl);
   // Noise cancellation
   ncBox=new LinearLayout(BoseTileService.this);ncBox.setOrientation(LinearLayout.VERTICAL);LinearLayout.LayoutParams nl=new LinearLayout.LayoutParams(-1,-2);nl.topMargin=dp(8);card.addView(ncBox,nl);
   LinearLayout swRow=new LinearLayout(BoseTileService.this);swRow.setGravity(Gravity.CENTER_VERTICAL);swRow.setMinimumHeight(dp(48));ncBox.addView(swRow);
   LinearLayout ncText=new LinearLayout(BoseTileService.this);ncText.setOrientation(LinearLayout.VERTICAL);swRow.addView(ncText,new LinearLayout.LayoutParams(0,-2,1));
   ncText.addView(text("Noise cancellation",16,true,R.color.qs_ink));ncSub=text("",13,false,R.color.qs_ink2);ncText.addView(ncSub);
   anc.setContentDescription("Noise cancellation");swRow.addView(anc,new LinearLayout.LayoutParams(dp(60),dp(48)));
   styleSlider();LinearLayout.LayoutParams sbl=new LinearLayout.LayoutParams(-1,dp(40));sbl.setMargins(-dp(12),dp(2),-dp(12),0);ncBox.addView(slider,sbl);
   LinearLayout ends=new LinearLayout(BoseTileService.this);ends.addView(text("Aware",12,false,R.color.qs_ink2),new LinearLayout.LayoutParams(0,-2,1));ends.addView(text("Max",12,false,R.color.qs_ink2));ncBox.addView(ends);
   anc.listener=on->{if(rendering)return;int level=shownLevel!=null?shownLevel:noiseLevel();requestNoise(level,on);};
   slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener(){
    public void onProgressChanged(SeekBar s,int value,boolean user){if(!user)return;shownLevel=value;showNoise(value,true,true);if(!touching)requestNoise(value,true);}
    public void onStartTrackingTouch(SeekBar s){touching=true;}
    public void onStopTrackingTouch(SeekBar s){touching=false;requestNoise(s.getProgress(),true);}
   });
   // Saved devices
   savedLabel=text("Saved devices",13,true,R.color.qs_ink2);LinearLayout.LayoutParams sl=new LinearLayout.LayoutParams(-2,-2);sl.topMargin=dp(14);sl.bottomMargin=dp(4);card.addView(savedLabel,sl);
   rows.setOrientation(LinearLayout.VERTICAL);card.addView(rows);
   // Footer
   LinearLayout foot=new LinearLayout(BoseTileService.this);foot.setGravity(Gravity.END|Gravity.CENTER_VERTICAL);foot.setPadding(0,dp(12),0,0);
   LinearLayout.LayoutParams fl=new LinearLayout.LayoutParams(-1,dp(1));fl.topMargin=dp(12);card.addView(hairline(),fl);card.addView(foot);
   Button settings=button("App settings",false);settings.setOnClickListener(v->openApp());foot.addView(settings,new LinearLayout.LayoutParams(-2,dp(44)));
   Button close=button("Close",false);close.setOnClickListener(v->dialog.dismiss());LinearLayout.LayoutParams xl=new LinearLayout.LayoutParams(-2,dp(44));xl.leftMargin=dp(8);foot.addView(close,xl);
   for(Button b:new Button[]{settings,close})b.setPadding(dp(20),0,dp(20),0);
  }
  int noiseLevel(){JSONObject n=snapshot.optJSONObject("noise");return n==null?7:n.optInt("level",7);}

  void render(){
   rendering=true;
   boolean live=live(),cached=snapshot.optBoolean("cached");int count=connectedCount();
   // Header status line
   if(live){sub.setText("Live · "+count+" of 2 connected");subLed.set(color(R.color.qs_ok),Led.SOLID,false);}
   else if(cached&&devices().length()>0){sub.setText((reading?"Checking… · ":"Last known · ")+count+" of 2 connected");subLed.set(color(R.color.qs_ink3),Led.HOLLOW,reading);}
   else if(reading){sub.setText("Checking headset…");subLed.set(color(R.color.qs_ink3),Led.HOLLOW,true);}
   else{sub.setText("Headset unavailable");subLed.set(color(R.color.qs_warn),Led.HOLLOW,false);}
   Object bat=snapshot.opt("battery");
   batteryBox.setVisibility(bat instanceof Number?View.VISIBLE:View.GONE);if(bat instanceof Number)battery.setText(((Number)bat).intValue()+"%");
   notice.setVisibility(notice().isEmpty()?View.GONE:View.VISIBLE);notice.setText(notice());notice.setTextColor(color(noticeError?R.color.qs_warn:R.color.qs_ink2));
   prompt.setVisibility(replacing!=null?View.VISIBLE:View.GONE);if(replacing!=null)promptText.setText("Both slots are in use. Choose which connection "+name(replacing)+" replaces.");
   renderCups(live);renderRows(live);
   // Noise
   JSONObject noise=snapshot.optJSONObject("noise");
   ncBox.setVisibility(noise==null?View.GONE:View.VISIBLE);
   if(noise==null){ridges.set(0.5f,false,!rendered);caption.setText("");}
   else{
    int level=shownLevel!=null?shownLevel:noise.optInt("level");boolean on=shownEnabled!=null?shownEnabled:noise.optBoolean("enabled");
    anc.setChecked(on);anc.setEnabled(live&&!mutating);slider.setProgress(level);slider.setEnabled(live&&on&&!mutating);
    float dim=live&&on?1f:.4f;slider.setAlpha(dim);((View)ncBox.getChildAt(2)).setAlpha(dim);anc.setAlpha(live?1f:.5f);
    showNoise(level,on,rendered);
   }
   rendering=false;rendered=true;
  }
  boolean rendered=false,touching=false;
  String notice(){return BoseTileService.this.notice;}
  void showNoise(int level,boolean on,boolean animate){
   ridges.set(on?(10-level)/10f:1f,!on,animate);
   android.text.SpannableStringBuilder s=new android.text.SpannableStringBuilder();
   if(on){s.append("Level "+level);s.setSpan(new android.text.style.ForegroundColorSpan(color(R.color.qs_ink)),0,s.length(),0);s.setSpan(new TypefaceSpanCompat(medium),0,s.length(),0);s.append(" / 10");}
   else{s.append("Off");s.setSpan(new android.text.style.ForegroundColorSpan(color(R.color.qs_ink)),0,s.length(),0);s.setSpan(new TypefaceSpanCompat(medium),0,s.length(),0);s.append(" · all through");}
   caption.setText(s);
   String state=!on?"Off · outside sound passes through":ancInFlight||ancQueued!=null?"Setting level "+level+"…":"On · level "+level+" of 10";
   ncSub.setText(state);
  }

  void renderCups(boolean live){
   cups.removeAllViews();
   String[] addr=new String[2];String[] mode=new String[2];int n=0;JSONArray ds=devices();
   // Keep each device in the cup it already occupies so a settle never swaps slots under the finger.
   List<String> on=new ArrayList<>();for(int i=0;i<ds.length();i++){JSONObject d=ds.optJSONObject(i);if(d!=null&&d.optBoolean("connected"))on.add(d.optString("address"));}
   for(int i=0;i<2;i++)if(slotOrder[i]!=null&&on.remove(slotOrder[i])){addr[i]=slotOrder[i];mode[i]="on";}
   for(int i=0;i<2&&!on.isEmpty();i++)if(addr[i]==null){addr[i]=on.remove(0);mode[i]="on";}
   if(mutating&&"connect".equals(pendingAction)){
    int slot=-1;if(pendingReplace!=null)for(int i=0;i<2;i++)if(pendingReplace.equals(addr[i]))slot=i;
    if(slot<0)for(int i=0;i<2;i++)if(addr[i]==null){slot=i;break;}
    if(slot>=0){addr[slot]=pendingAddress;mode[slot]="connecting";}
   }
   if(mutating&&"disconnect".equals(pendingAction))for(int i=0;i<2;i++)if(pendingAddress.equals(addr[i]))mode[i]="disconnecting";
   slotOrder=addr.clone();
   for(int i=0;i<2;i++){
    LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,-1,1);if(i==1)lp.leftMargin=dp(10);
    cups.addView(cup(i+1,addr[i]==null?null:device(addr[i]),mode[i],live),lp);
   }
  }
  View cup(int slot,JSONObject d,String mode,boolean live){
   boolean cached=!live,pending="connecting".equals(mode)||"disconnecting".equals(mode);
   LinearLayout c=new LinearLayout(BoseTileService.this);c.setOrientation(LinearLayout.VERTICAL);c.setPadding(dp(12),dp(12),dp(12),dp(10));
   c.setBackground(round(color(R.color.qs_surface),dp(22),pending?dp(1.5f):dp(1),color(pending?R.color.qs_accent:R.color.qs_cup_edge)));
   LinearLayout state=new LinearLayout(BoseTileService.this);state.setGravity(Gravity.CENTER_VERTICAL);c.addView(state);
   Led led=new Led();state.addView(led,new LinearLayout.LayoutParams(dp(13),dp(13)));
   String label=d==null?"Open":"connecting".equals(mode)?"Connecting…":"disconnecting".equals(mode)?"Disconnecting…":cached?"Last known":"Connected";
   TextView st=text(pending?label:label+" · Slot "+slot,12,false,R.color.qs_ink2);st.setPadding(dp(5),0,0,0);st.setSingleLine();st.setEllipsize(TextUtils.TruncateAt.END);state.addView(st);
   if(d==null)led.set(color(R.color.qs_ink3),Led.HOLLOW,false);
   else if(pending)led.set(color(R.color.qs_accent),Led.SOLID,true);
   else led.set(color(cached?R.color.qs_ink3:R.color.qs_ok),cached?Led.HOLLOW:Led.SOLID,false);
   TextView name=text(d==null?"Free slot":name(d),16,true,d==null?R.color.qs_ink3:R.color.qs_ink);name.setSingleLine();name.setEllipsize(TextUtils.TruncateAt.END);
   LinearLayout.LayoutParams nl=new LinearLayout.LayoutParams(-1,-2);nl.topMargin=dp(6);c.addView(name,nl);
   String tagText=d==null?"Connect a saved device":tag(d);boolean here=d!=null&&tagText.startsWith("This ");
   TextView tag=text(tagText,13,here,here?R.color.qs_accent_ink:R.color.qs_ink2);tag.setSingleLine();tag.setEllipsize(TextUtils.TruncateAt.END);
   if(here){LinearLayout t=new LinearLayout(BoseTileService.this);t.setGravity(Gravity.CENTER_VERTICAL);View bar=new View(BoseTileService.this);bar.setBackground(round(color(R.color.qs_accent),dp(1),0,0));
    LinearLayout.LayoutParams bl=new LinearLayout.LayoutParams(dp(12),dp(2));bl.rightMargin=dp(6);t.addView(bar,bl);t.addView(tag);c.addView(t);}
   else c.addView(tag);
   View spacer=new View(BoseTileService.this);c.addView(spacer,new LinearLayout.LayoutParams(1,0,1));
   LinearLayout.LayoutParams bl=new LinearLayout.LayoutParams(-1,dp(44));bl.topMargin=dp(8);
   if(d==null){View hold=new View(BoseTileService.this);c.addView(hold,bl);return c;}
   Button b;
   if(pending){b=button("connecting".equals(mode)?"Connecting…":"Disconnecting…",true);b.setEnabled(false);b.setAlpha(1f);fill(b);}
   else if(replacing!=null){final String drop=d.optString("address");final String target=replacing.optString("address");b=button("Replace",true);enable(b,live&&!busy());b.setOnClickListener(v->mutate("connect",target,drop));}
   else{final String a=d.optString("address");b=button("Disconnect",false);enable(b,live&&!busy());b.setOnClickListener(v->mutate("disconnect",a,null));}
   b.setTextSize(14);b.setPadding(dp(8),0,dp(8),0);c.addView(b,bl);return c;
  }
  void renderRows(boolean live){
   rows.removeAllViews();JSONArray ds=devices();int shown=0;
   for(int i=0;i<ds.length();i++){
    JSONObject d=ds.optJSONObject(i);if(d==null||d.optBoolean("connected"))continue;
    if(mutating&&"connect".equals(pendingAction)&&d.optString("address").equals(pendingAddress))continue;
    rows.addView(hairline(),new LinearLayout.LayoutParams(-1,dp(1)));rows.addView(row(d,live));shown++;
   }
   if(shown==0){TextView none=text(ds.length()==0?"No saved devices yet":"Every saved device is connected",13,false,R.color.qs_ink3);none.setPadding(0,dp(10),0,dp(10));rows.addView(hairline(),new LinearLayout.LayoutParams(-1,dp(1)));rows.addView(none);}
   rows.addView(hairline(),new LinearLayout.LayoutParams(-1,dp(1)));
  }
  View row(JSONObject d,boolean live){
   LinearLayout r=new LinearLayout(BoseTileService.this);r.setGravity(Gravity.CENTER_VERTICAL);r.setMinimumHeight(dp(58));
   ImageView icon=new ImageView(BoseTileService.this);icon.setImageResource(icon(d));icon.setImageTintList(ColorStateList.valueOf(color(R.color.qs_ink2)));
   LinearLayout.LayoutParams il=new LinearLayout.LayoutParams(dp(22),dp(22));il.rightMargin=dp(14);r.addView(icon,il);
   LinearLayout t=new LinearLayout(BoseTileService.this);t.setOrientation(LinearLayout.VERTICAL);r.addView(t,new LinearLayout.LayoutParams(0,-2,1));
   TextView name=text(name(d),15,true,R.color.qs_ink);name.setSingleLine();name.setEllipsize(TextUtils.TruncateAt.END);t.addView(name);
   boolean chosen=replacing!=null&&replacing.optString("address").equals(d.optString("address"));
   t.addView(text(chosen?"Choose a slot above to replace":"Saved · not connected",13,false,chosen?R.color.qs_accent_ink:R.color.qs_ink2));
   Button b;
   b=button("Connect",true);enable(b,live&&!busy()&&replacing==null);b.setOnClickListener(v->connect(d));
   b.setTextSize(14);b.setMinWidth(dp(104));LinearLayout.LayoutParams bl=new LinearLayout.LayoutParams(-2,dp(44));bl.leftMargin=dp(10);r.addView(b,bl);
   return r;
  }

  // ---- Widgets ----
  TextView text(String value,float sp,boolean bold,int colorId){TextView v=new TextView(BoseTileService.this);v.setText(value);v.setTextSize(TypedValue.COMPLEX_UNIT_SP,sp);v.setTypeface(bold?medium:regular);v.setTextColor(color(colorId));return v;}
  View hairline(){View v=new View(BoseTileService.this);v.setBackgroundColor(color(R.color.qs_hair));return v;}
  Button button(String label,boolean accent){
   Button b=new Button(BoseTileService.this);b.setText(label);b.setAllCaps(false);b.setTypeface(medium);b.setTextSize(TypedValue.COMPLEX_UNIT_SP,15);
   b.setStateListAnimator(null);b.setMinHeight(0);b.setMinimumHeight(0);b.setMinWidth(0);b.setMinimumWidth(0);b.setPadding(dp(18),0,dp(18),0);b.setSingleLine();b.setEllipsize(TextUtils.TruncateAt.END);
   int r=dp(22);
   if(accent){
    StateListDrawable s=new StateListDrawable();
    s.addState(new int[]{android.R.attr.state_pressed},round(color(R.color.qs_accent),r,0,0));
    s.addState(new int[]{},round(Color.TRANSPARENT,r,dp(1.5f),color(R.color.qs_accent)));
    b.setBackground(new RippleDrawable(ColorStateList.valueOf(color(R.color.qs_press)),s,null));
    b.setTextColor(new ColorStateList(new int[][]{{android.R.attr.state_pressed},{}},new int[]{color(R.color.qs_on_accent),color(R.color.qs_accent_ink)}));
   }else{
    b.setBackground(new RippleDrawable(ColorStateList.valueOf(color(R.color.qs_press)),round(Color.TRANSPARENT,r,dp(1),color(R.color.qs_line_strong)),null));
    b.setTextColor(color(R.color.qs_ink));
   }
   return b;
  }
  void enable(Button b,boolean on){b.setEnabled(on);b.setAlpha(on?1f:.45f);}
  void fill(Button b){b.setBackground(round(color(R.color.qs_accent),dp(22),0,0));b.setTextColor(color(R.color.qs_on_accent));}
  void styleSlider(){
   slider.setMax(10);slider.setPadding(dp(12),0,dp(12),0);slider.setSplitTrack(false);slider.setContentDescription("Noise cancellation level");
   GradientDrawable bg=round(color(R.color.qs_track),dp(2),0,0),fg=round(color(R.color.qs_fill),dp(2),0,0);
   LayerDrawable track=new LayerDrawable(new Drawable[]{bg,new ClipDrawable(fg,Gravity.START,ClipDrawable.HORIZONTAL)});
   track.setId(0,android.R.id.background);track.setId(1,android.R.id.progress);
   for(int i=0;i<2;i++){track.setLayerHeight(i,dp(4));track.setLayerGravity(i,Gravity.CENTER_VERTICAL|Gravity.FILL_HORIZONTAL);}
   slider.setProgressDrawable(track);
   GradientDrawable thumb=oval(color(R.color.qs_thumb),dp(24),dp(2),color(R.color.qs_fill));slider.setThumb(thumb);slider.setThumbOffset(dp(12));
  }
 }

 GradientDrawable round(int fill,int radius,int stroke,int strokeColor){GradientDrawable g=new GradientDrawable();g.setColor(fill);g.setCornerRadius(radius);if(stroke>0)g.setStroke(stroke,strokeColor);return g;}
 GradientDrawable oval(int fill,int size,int stroke,int strokeColor){GradientDrawable g=new GradientDrawable();g.setShape(GradientDrawable.OVAL);g.setColor(fill);g.setSize(size,size);if(stroke>0)g.setStroke(stroke,strokeColor);return g;}

 /** Typeface span for API 26-27 (TypefaceSpan(Typeface) is API 28+). */
 static class TypefaceSpanCompat extends android.text.style.MetricAffectingSpan {
  final Typeface face;TypefaceSpanCompat(Typeface face){this.face=face;}
  public void updateDrawState(android.text.TextPaint p){p.setTypeface(face);}
  public void updateMeasureState(android.text.TextPaint p){p.setTypeface(face);}
 }

 /** Status light: solid dot with halo, or hollow ring; breathes while pending. */
 class Led extends View {
  static final int SOLID=0,HOLLOW=1;
  final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);int tint;int style;boolean breathe;float phase=1f;ValueAnimator pulse;
  Led(){super(BoseTileService.this);}
  void set(int tint,int style,boolean breathe){this.tint=tint;this.style=style;if(this.breathe!=breathe){this.breathe=breathe;syncPulse();}invalidate();}
  void syncPulse(){
   if(pulse!=null){pulse.cancel();pulse=null;}phase=1f;
   if(breathe&&isAttachedToWindow()&&ValueAnimator.areAnimatorsEnabled()){pulse=ValueAnimator.ofFloat(1f,.3f);pulse.setDuration(900);pulse.setRepeatCount(ValueAnimator.INFINITE);pulse.setRepeatMode(ValueAnimator.REVERSE);pulse.addUpdateListener(a->{phase=(float)a.getAnimatedValue();invalidate();});pulse.start();}
  }
  protected void onAttachedToWindow(){super.onAttachedToWindow();syncPulse();}
  protected void onDetachedFromWindow(){if(pulse!=null)pulse.cancel();pulse=null;super.onDetachedFromWindow();}
  protected void onDraw(Canvas c){
   float cx=getWidth()/2f,cy=getHeight()/2f,r=dp(3.5f);
   if(style==SOLID){paint.setStyle(Paint.Style.FILL);paint.setColor(tint);paint.setAlpha(Math.round(46*phase));c.drawCircle(cx,cy,r+dp(3),paint);paint.setAlpha(Math.round(255*(.45f+.55f*phase)));c.drawCircle(cx,cy,r,paint);}
   else{paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(dp(1.4f));paint.setColor(tint);paint.setAlpha(Math.round(255*(.45f+.55f*phase)));c.drawCircle(cx,cy,r-dp(.7f),paint);}
  }
 }

 interface ToggleListener{void changed(boolean on);}
 /** Noise-cancellation switch drawn to the Mist sleeve spec (60x32 track, 24dp thumb); announces itself as a Switch. */
 class Toggle extends View implements Checkable {
  boolean checked;float pos=-1;ToggleListener listener;ValueAnimator anim;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
  Toggle(){super(BoseTileService.this);setClickable(true);setFocusable(true);setOnClickListener(v->{if(!isEnabled())return;setChecked(!checked);if(listener!=null)listener.changed(checked);});}
  public boolean isChecked(){return checked;}
  public void toggle(){setChecked(!checked);}
  public void setChecked(boolean on){
   if(on==checked&&pos>=0)return;checked=on;float to=on?1f:0f;if(anim!=null)anim.cancel();
   if(pos<0||!isAttachedToWindow()||!ValueAnimator.areAnimatorsEnabled()){pos=to;invalidate();}
   else{anim=ValueAnimator.ofFloat(pos,to);anim.setDuration(160);anim.setInterpolator(new DecelerateInterpolator(2f));anim.addUpdateListener(a->{pos=(float)a.getAnimatedValue();invalidate();});anim.start();}
   sendAccessibilityEvent(android.view.accessibility.AccessibilityEvent.TYPE_VIEW_CLICKED);
  }
  public CharSequence getAccessibilityClassName(){return Switch.class.getName();}
  public void onInitializeAccessibilityNodeInfo(android.view.accessibility.AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(info);info.setCheckable(true);info.setChecked(checked);}
  protected void onDraw(Canvas c){
   float w=dp(60),h=dp(32),top=(getHeight()-h)/2f,left=getWidth()-w,p=Math.max(0,pos);
   RectF track=new RectF(left,top,left+w,top+h);
   paint.setStyle(Paint.Style.FILL);paint.setColor(p>.5f?color(R.color.qs_fill):color(R.color.qs_track));c.drawRoundRect(track,h/2,h/2,paint);
   if(p<=.5f){paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(dp(2));paint.setColor(color(R.color.qs_ink3));RectF in=new RectF(track);in.inset(dp(1),dp(1));c.drawRoundRect(in,h/2-dp(1),h/2-dp(1),paint);}
   float r=dp(8)+dp(4)*p,cx=left+dp(16)+(w-dp(32))*p,cy=top+h/2;
   paint.setStyle(Paint.Style.FILL);paint.setColor(p>.5f?color(R.color.qs_thumb):color(R.color.qs_ink3));c.drawCircle(cx,cy,r,paint);
  }
 }

 /** "Outside sound" ridge band: stacked smooth ridges whose height is the outside sound let through. */
 class RidgeView extends View {
  static final int RIDGES=9,SAMPLES=31;
  final float[][] profile=new float[RIDGES][SAMPLES];
  final Paint fill=new Paint(Paint.ANTI_ALIAS_FLAG),line=new Paint(Paint.ANTI_ALIAS_FLAG);
  final Path path=new Path();float amp=-1,target;boolean dashed;ValueAnimator anim;
  RidgeView(){
   super(BoseTileService.this);
   fill.setStyle(Paint.Style.FILL);line.setStyle(Paint.Style.STROKE);line.setStrokeJoin(Paint.Join.ROUND);line.setStrokeCap(Paint.Cap.ROUND);
   for(int r=0;r<RIDGES;r++){
    Random rnd=new Random(41+r*977);int bumps=3+rnd.nextInt(2);float[] c=new float[bumps],w=new float[bumps],h=new float[bumps];
    for(int k=0;k<bumps;k++){c[k]=.3f+.4f*rnd.nextFloat();w[k]=.05f+.08f*rnd.nextFloat();h[k]=(.35f+.65f*rnd.nextFloat())*(rnd.nextFloat()<.18f?-.4f:1f);}
    float peak=0;
    for(int s=0;s<SAMPLES;s++){float x=s/(SAMPLES-1f),y=0;for(int k=0;k<bumps;k++){float d=(x-c[k])/w[k];y+=h[k]*(float)Math.exp(-d*d);}profile[r][s]=y;peak=Math.max(peak,Math.abs(y));}
    float scale=(.55f+.45f*r/(RIDGES-1f))/Math.max(peak,1e-3f);for(int s=0;s<SAMPLES;s++)profile[r][s]*=scale;
   }
  }
  void set(float amplitude,boolean off,boolean animate){
   if(off!=dashed){dashed=off;invalidate();}
   if(amplitude==target&&amp>=0)return;target=amplitude;
   if(anim!=null)anim.cancel();
   if(!animate||amp<0||!ValueAnimator.areAnimatorsEnabled()){amp=amplitude;invalidate();return;}
   anim=ValueAnimator.ofFloat(amp,amplitude);anim.setDuration(180);anim.setInterpolator(new DecelerateInterpolator(2f));anim.addUpdateListener(a->{amp=(float)a.getAnimatedValue();invalidate();});anim.start();
  }
  protected void onDraw(Canvas c){
   int w=getWidth(),h=getHeight();if(w==0||h==0)return;
   int ground=color(R.color.qs_ground),ridge=color(R.color.qs_ridge);boolean light=!night();
   int save=c.saveLayer(0,0,w,h,null);
   float top=dp(21),bottom=h-dp(6),step=(bottom-top)/(RIDGES-1),lift=dp(2)+dp(24)*Math.max(0,amp);
   fill.setColor(ground);line.setStrokeWidth(dp(light?1.3f:1.2f));line.setColor(ridge);
   line.setPathEffect(dashed?new DashPathEffect(new float[]{dp(4),dp(3)},0):null);
   for(int r=0;r<RIDGES;r++){
    float base=top+r*step;
    buildPath(r,base,lift*(r==0?.45f:r==1?.75f:1f),w);
    Path closed=new Path(path);closed.lineTo(w,h);closed.lineTo(0,h);closed.close();c.drawPath(closed,fill);
    float alpha=(light?.5f:.38f)+(1f-(light?.5f:.38f))*r/(RIDGES-1f);line.setAlpha(Math.round(255*alpha));c.drawPath(path,line);
   }
   c.restoreToCount(save);
  }
  /** Catmull-Rom through the sampled profile, emitted as cubic beziers. */
  void buildPath(int r,float base,float lift,int w){
   path.reset();float dx=w/(SAMPLES-1f);
   float[] ys=new float[SAMPLES];for(int s=0;s<SAMPLES;s++)ys[s]=Math.max(dp(2),base-profile[r][s]*lift);
   path.moveTo(0,ys[0]);
   for(int s=0;s<SAMPLES-1;s++){
    float y0=ys[Math.max(0,s-1)],y1=ys[s],y2=ys[s+1],y3=ys[Math.min(SAMPLES-1,s+2)],x1=s*dx,x2=(s+1)*dx;
    path.cubicTo(x1+dx/3f,y1+(y2-y0)/6f,x2-dx/3f,y2-(y3-y1)/6f,x2,y2);
   }
  }
 }

 public void onDestroy(){generation++;if(dialog!=null)dialog.dismiss();work.shutdown();super.onDestroy();}
}
