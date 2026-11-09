package local.bose.connections;
import java.util.*;

/** Which local address the relay listens on. No Android types, so a JVM test can drive it. */
public class Tailnet {
 /** Tailscale's CGNAT range 100.64.0.0/10. */
 static boolean is(String ip){try{String[] p=ip.split("\\.");return p.length==4&&Integer.parseInt(p[0])==100&&Integer.parseInt(p[1])>=64&&Integer.parseInt(p[1])<=127;}catch(Exception e){return false;}}
 /** Carriers give mobile data CGNAT addresses from the same range (seen on the Galaxy: rmnet_data7 100.90.44.105), so the VPN
  tunnel (tun*) wins, mobile data (rmnet*) never counts, and any other interface is a fallback. Entries are {interface, address}. */
 static String pick(List<String[]> addresses){
  String fallback=null;
  for(String[] a:addresses){if(!is(a[1]))continue;if(a[0].startsWith("tun"))return a[1];if(fallback==null&&!a[0].startsWith("rmnet"))fallback=a[1];}
  return fallback;
 }
}
