package android.content;
import java.io.File;
/** Test-only stand-in: the part of Context that Core.java uses. */
public abstract class Context {
 public static final String BLUETOOTH_SERVICE="bluetooth";
 public abstract File getFilesDir();
 public abstract Object getSystemService(String name);
}
