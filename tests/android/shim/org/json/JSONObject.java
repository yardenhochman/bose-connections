package org.json;
import java.util.*;
/** Test-only stand-in for the Android org.json API surface Switcher uses (the real classes are stubs in android.jar). */
public class JSONObject {
 final Map<String,Object> map=new LinkedHashMap<>();
 public JSONObject put(String k,Object v)throws JSONException{map.put(k,v);return this;}
 public JSONObject put(String k,boolean v)throws JSONException{map.put(k,v);return this;}
 public boolean has(String k){return map.containsKey(k);}
 public Object opt(String k){return map.get(k);}
 public boolean optBoolean(String k){return map.get(k) instanceof Boolean&&(Boolean)map.get(k);}
 public String optString(String k){return optString(k,"");}
 public String optString(String k,String d){Object v=map.get(k);return v==null?d:v.toString();}
 public String getString(String k)throws JSONException{if(!(map.get(k) instanceof String))throw new JSONException("No string "+k);return (String)map.get(k);}
 public JSONArray getJSONArray(String k)throws JSONException{if(!(map.get(k) instanceof JSONArray))throw new JSONException("No array "+k);return (JSONArray)map.get(k);}
 public JSONObject optJSONObject(String k){return map.get(k) instanceof JSONObject?(JSONObject)map.get(k):null;}
}
