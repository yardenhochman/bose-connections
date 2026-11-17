package android.bluetooth;
import java.util.UUID;
/** Test-only stand-in. */
public class BluetoothDevice {public final String address;public BluetoothDevice(String a){address=a;}
 public BluetoothSocket createRfcommSocket(int channel){return new BluetoothSocket();}
 public BluetoothSocket createRfcommSocketToServiceRecord(UUID u){return new BluetoothSocket();}}
