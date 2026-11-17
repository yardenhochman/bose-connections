package android.util;
/** Test-only stand-in: log lines go to stdout prefixed LOG. */
public final class Log {private Log(){}public static int i(String tag,String m){System.out.println("LOG "+tag+" "+m);return 0;}public static int w(String tag,String m){System.out.println("LOG "+tag+" "+m);return 0;}}
