package org.json;
import java.util.*;
/** Test-only stand-in for the Android org.json API surface Switcher uses (the real classes are stubs in android.jar). */
public class JSONArray {
 final List<Object> items=new ArrayList<>();
 public JSONArray put(Object v){items.add(v);return this;}
 public int length(){return items.size();}
 public JSONObject optJSONObject(int i){return i>=0&&i<items.size()&&items.get(i) instanceof JSONObject?(JSONObject)items.get(i):null;}
 public JSONObject getJSONObject(int i)throws JSONException{JSONObject o=optJSONObject(i);if(o==null)throw new JSONException("No object at "+i);return o;}
}
