package local.bose.connections;
import java.util.*;

/** Relay listen-address choice (run by tests/test_android_contract.py). Prints PASS/FAIL lines; exits 1 on any failure. */
public class TailnetTest {
 static int failed=0;
 static void check(String name,String want,String got){boolean ok=Objects.equals(want,got);if(!ok)failed++;System.out.println((ok?"PASS ":"FAIL ")+name+": want "+want+" got "+got);}
 static List<String[]> l(String... s){List<String[]> out=new ArrayList<>();for(int i=0;i<s.length;i+=2)out.add(new String[]{s[i],s[i+1]});return out;}
 public static void main(String[] a){
  check("tunnel_beats_carrier_cgnat","100.77.27.16",Tailnet.pick(l("lo","127.0.0.1","wlan0","192.168.1.20","rmnet_data7","100.90.44.105","tun1","100.77.27.16")));
  check("carrier_cgnat_alone_is_not_tailscale",null,Tailnet.pick(l("rmnet_data7","100.90.44.105","wlan0","192.168.1.20")));
  check("other_interface_is_fallback","100.100.1.2",Tailnet.pick(l("wlan0","192.168.1.20","tailscale0","100.100.1.2")));
  check("outside_range_ignored",null,Tailnet.pick(l("tun0","10.0.0.2","tun1","100.128.0.1","tun2","100.63.255.255")));
  check("range_edges","true,true",Tailnet.is("100.64.0.0")+","+Tailnet.is("100.127.255.255"));
  System.exit(failed==0?0:1);
 }
}
