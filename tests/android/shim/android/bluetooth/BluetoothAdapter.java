package android.bluetooth;
/** Test-only stand-in: an adapter that is on or off; dialling any device fails as if it were out of range. */
public class BluetoothAdapter {public boolean enabled;public BluetoothAdapter(boolean on){enabled=on;}public boolean isEnabled(){return enabled;}public BluetoothDevice getRemoteDevice(String a){return new BluetoothDevice(a);}}
