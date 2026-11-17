package android.bluetooth;
import java.io.*;
/** Test-only stand-in: connect() is refused after a while, like a headset that is out of range. */
public class BluetoothSocket implements Closeable {
 public void connect()throws IOException{try{Thread.sleep(600);}catch(InterruptedException e){}throw new IOException("read failed, socket might closed or timeout");}
 public InputStream getInputStream(){return new ByteArrayInputStream(new byte[0]);}
 public OutputStream getOutputStream(){return new ByteArrayOutputStream();}
 public void close(){}
}
