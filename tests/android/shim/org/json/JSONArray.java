package org.json;
import java.util.*;
/** Test-only stand-in for the Android org.json API surface the app uses (the real classes are stubs in android.jar). */
public class JSONArray {
 final List<Object> items=new ArrayList<>();
 public JSONArray(){}
 public JSONArray(Collection<?> c){if(c!=null)for(Object v:c)items.add(JSONObject.wrap(v));}
 public JSONArray(String json)throws JSONException{Object v=new JSONObject.Parser(json).value();if(!(v instanceof JSONArray))throw new JSONException("Not an array");items.addAll(((JSONArray)v).items);}
 public JSONArray put(Object v){items.add(v);return this;}
 public JSONArray put(int v){items.add(v);return this;}
 public JSONArray put(boolean v){items.add(v);return this;}
 public int length(){return items.size();}
 public Object opt(int i){return i>=0&&i<items.size()?items.get(i):null;}
 public Object get(int i)throws JSONException{Object v=opt(i);if(v==null)throw new JSONException("No value at "+i);return v;}
 public String getString(int i)throws JSONException{if(!(opt(i) instanceof String))throw new JSONException("No string at "+i);return (String)opt(i);}
 public String optString(int i){Object v=opt(i);return v==null||v==JSONObject.NULL?"":v.toString();}
 public boolean optBoolean(int i){return opt(i) instanceof Boolean&&(Boolean)opt(i);}
 public int optInt(int i){return opt(i) instanceof Number?((Number)opt(i)).intValue():0;}
 public JSONObject optJSONObject(int i){return opt(i) instanceof JSONObject?(JSONObject)opt(i):null;}
 public JSONArray optJSONArray(int i){return opt(i) instanceof JSONArray?(JSONArray)opt(i):null;}
 public JSONObject getJSONObject(int i)throws JSONException{JSONObject o=optJSONObject(i);if(o==null)throw new JSONException("No object at "+i);return o;}
 public JSONArray getJSONArray(int i)throws JSONException{JSONArray o=optJSONArray(i);if(o==null)throw new JSONException("No array at "+i);return o;}
 @Override public String toString(){StringBuilder s=new StringBuilder("[");for(int i=0;i<items.size();i++){if(i>0)s.append(',');Object v=items.get(i);if(v instanceof JSONObject||v instanceof JSONArray)s.append(v);else JSONObject.write(s,v);}return s.append(']').toString();}
}
