package org.json;
import java.util.*;
/** Test-only stand-in for the Android org.json API surface the app uses (the real classes are stubs in android.jar).
 Follows Android's behaviour where the app relies on it: put(k,null) removes k, optInt/optLong/optDouble coerce numbers,
 toString() writes compact JSON in insertion order, and NULL equals null for isNull. */
public class JSONObject {
 public static final Object NULL=new Object(){@Override public boolean equals(Object o){return o==this||o==null;}@Override public int hashCode(){return 0;}@Override public String toString(){return "null";}};
 final Map<String,Object> map=new LinkedHashMap<>();
 public JSONObject(){}
 public JSONObject(String json)throws JSONException{Object v=new Parser(json).value();if(!(v instanceof JSONObject))throw new JSONException("Not an object");map.putAll(((JSONObject)v).map);}
 public JSONObject(Map<String,?> m){if(m!=null)for(Map.Entry<String,?> e:m.entrySet())map.put(e.getKey(),wrap(e.getValue()));}
 static Object wrap(Object v){return v==null?NULL:v;}
 public JSONObject put(String k,Object v)throws JSONException{if(v==null)map.remove(k);else map.put(k,v);return this;}
 public JSONObject put(String k,boolean v)throws JSONException{map.put(k,v);return this;}
 public JSONObject put(String k,int v)throws JSONException{map.put(k,v);return this;}
 public JSONObject put(String k,long v)throws JSONException{map.put(k,v);return this;}
 public JSONObject put(String k,double v)throws JSONException{map.put(k,v);return this;}
 public Object remove(String k){return map.remove(k);}
 public Iterator<String> keys(){return map.keySet().iterator();}
 public int length(){return map.size();}
 public boolean has(String k){return map.containsKey(k);}
 public boolean isNull(String k){Object v=map.get(k);return v==null||v==NULL;}
 public Object opt(String k){return map.get(k);}
 public Object get(String k)throws JSONException{Object v=map.get(k);if(v==null)throw new JSONException("No value for "+k);return v;}
 public boolean optBoolean(String k){return optBoolean(k,false);}
 public boolean optBoolean(String k,boolean d){Object v=map.get(k);return v instanceof Boolean?(Boolean)v:"true".equals(v)?true:"false".equals(v)?false:d;}
 public boolean getBoolean(String k)throws JSONException{Object v=get(k);if(v instanceof Boolean)return (Boolean)v;throw new JSONException("No boolean "+k);}
 public int optInt(String k){return optInt(k,0);}
 public int optInt(String k,int d){Object v=map.get(k);return v instanceof Number?((Number)v).intValue():d;}
 public int getInt(String k)throws JSONException{Object v=get(k);if(v instanceof Number)return ((Number)v).intValue();throw new JSONException("No int "+k);}
 public long optLong(String k){return optLong(k,0);}
 public long optLong(String k,long d){Object v=map.get(k);return v instanceof Number?((Number)v).longValue():d;}
 public double optDouble(String k){return optDouble(k,Double.NaN);}
 public double optDouble(String k,double d){Object v=map.get(k);return v instanceof Number?((Number)v).doubleValue():d;}
 public String optString(String k){return optString(k,"");}
 public String optString(String k,String d){Object v=map.get(k);return v==null||v==NULL?d:v.toString();}
 public String getString(String k)throws JSONException{if(!(map.get(k) instanceof String))throw new JSONException("No string "+k);return (String)map.get(k);}
 public JSONArray optJSONArray(String k){return map.get(k) instanceof JSONArray?(JSONArray)map.get(k):null;}
 public JSONArray getJSONArray(String k)throws JSONException{if(!(map.get(k) instanceof JSONArray))throw new JSONException("No array "+k);return (JSONArray)map.get(k);}
 public JSONObject optJSONObject(String k){return map.get(k) instanceof JSONObject?(JSONObject)map.get(k):null;}
 public JSONObject getJSONObject(String k)throws JSONException{if(!(map.get(k) instanceof JSONObject))throw new JSONException("No object "+k);return (JSONObject)map.get(k);}
 @Override public String toString(){StringBuilder s=new StringBuilder("{");boolean first=true;for(Map.Entry<String,Object> e:map.entrySet()){if(!first)s.append(',');first=false;quote(s,e.getKey());s.append(':');write(s,e.getValue());}return s.append('}').toString();}
 static void quote(StringBuilder s,String v){s.append('"');for(char c:v.toCharArray()){if(c=='"'||c=='\\')s.append('\\').append(c);else if(c=='\n')s.append("\\n");else if(c<0x20)s.append(String.format("\\u%04x",(int)c));else s.append(c);}s.append('"');}
 static void write(StringBuilder s,Object v){
  if(v==null||v==NULL)s.append("null");else if(v instanceof String)quote(s,(String)v);
  else if(v instanceof Double&&((Double)v)==Math.rint((Double)v)&&!Double.isInfinite((Double)v))s.append(((Double)v).longValue());else s.append(v);
 }
 /** A small recursive-descent JSON reader: objects, arrays, strings with escapes, numbers (Integer when they fit, else Long or Double), true/false/null. */
 static class Parser {
  final String t;int i=0;Parser(String t){this.t=t;}
  void ws(){while(i<t.length()&&Character.isWhitespace(t.charAt(i)))i++;}
  JSONException err(String m){return new JSONException(m+" at "+i);}
  Object value()throws JSONException{
   ws();if(i>=t.length())throw err("End of input");char c=t.charAt(i);
   if(c=='{'){i++;JSONObject o=new JSONObject();ws();if(t.charAt(i)=='}'){i++;return o;}
    while(true){ws();String k=(String)value();ws();if(t.charAt(i++)!=':')throw err("Expected :");o.map.put(k,value());ws();char n=t.charAt(i++);if(n=='}')return o;if(n!=',')throw err("Expected , or }");}}
   if(c=='['){i++;JSONArray a=new JSONArray();ws();if(t.charAt(i)==']'){i++;return a;}
    while(true){a.items.add(value());ws();char n=t.charAt(i++);if(n==']')return a;if(n!=',')throw err("Expected , or ]");}}
   if(c=='"'){i++;StringBuilder s=new StringBuilder();while(true){char d=t.charAt(i++);if(d=='"')return s.toString();if(d!='\\'){s.append(d);continue;}char e=t.charAt(i++);
    switch(e){case 'n':s.append('\n');break;case 't':s.append('\t');break;case 'r':s.append('\r');break;case 'b':s.append('\b');break;case 'f':s.append('\f');break;case 'u':s.append((char)Integer.parseInt(t.substring(i,i+4),16));i+=4;break;default:s.append(e);}}}
   if(t.startsWith("true",i)){i+=4;return Boolean.TRUE;}if(t.startsWith("false",i)){i+=5;return Boolean.FALSE;}if(t.startsWith("null",i)){i+=4;return NULL;}
   int start=i;while(i<t.length()&&"+-0123456789.eE".indexOf(t.charAt(i))>=0)i++;String n=t.substring(start,i);if(n.isEmpty())throw err("Unexpected "+c);
   if(n.matches("-?\\d+")){long l=Long.parseLong(n);return l==(int)l?(Object)(int)l:(Object)l;}return Double.parseDouble(n);
  }
 }
}
