"""NC700 connection and ANC client. No firmware or pairing-list deletion."""
import errno, socket, time, sys
from contextlib import contextmanager

class ProtocolError(Exception): pass
class ActionUnconfirmed(Exception): pass

def mac_bytes(value):
    parts = value.split(':')
    if len(parts) != 6 or any(len(p) != 2 for p in parts):
        raise ValueError('Invalid Bluetooth address')
    return bytes(int(p,16) for p in parts)

def mac_text(value): return ':'.join(f'{x:02X}' for x in value)

def parse_list(payload):
    if not payload or (len(payload)-1)%6 or len(payload)>49:
        raise ProtocolError('Unexpected paired-device list layout; refusing changes')
    return [payload[i:i+6] for i in range(1,len(payload),6)]

def parse_info(payload, address):
    if len(payload)<9 or payload[:6]!=address or payload[6] not in (0,1,3):
        raise ProtocolError('Unexpected device information layout; refusing changes')
    return dict(address=mac_text(address),name=payload[9:].split(b'\0')[0].decode('utf-8','replace') or mac_text(address),connected=payload[6] in (1,3),current=payload[6]==3)

def parse_noise(payload):
    if len(payload)!=3 or payload[0]!=11 or payload[1]>10 or payload[2] not in (0,1):
        raise ProtocolError('Unknown NC700 noise-control layout; refusing changes')
    return dict(level=10-payload[1],enabled=bool(payload[2]))

def validate_noise(level,enabled):
    if type(level) is not int or not 0<=level<=10 or type(enabled) is not bool:
        raise ValueError('Noise level must be 0–10 and enabled must be boolean')

class Client:
    def __init__(self,sock): self.sock=sock; self.buf=bytearray()
    def request(self,block,func,op=1,payload=b'',expected=(3,),timeout=4):
        self.sock.sendall(bytes([block,func,op,len(payload)])+payload)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            while len(self.buf)>=4 and len(self.buf)>=4+self.buf[3]:
                n=4+self.buf[3]; packet=bytes(self.buf[:n]);del self.buf[:n]
                if packet[:2]!=bytes([block,func]):continue
                kind=packet[2]&15
                if kind==15: raise ProtocolError(f'Headset rejected {block}.{func}: {packet[4:].hex()}')
                if kind in expected:return packet[4:]
            if hasattr(self.sock,'settimeout'):self.sock.settimeout(max(.01,deadline-time.monotonic()))
            data=self.sock.recv(4096)
            if not data: raise ProtocolError('Headset closed the control connection')
            self.buf.extend(data)
            if len(self.buf)>16384:raise ProtocolError('Invalid oversized Bluetooth response')
        raise ProtocolError('Headset did not acknowledge the command')
    def noise(self):return parse_noise(self.request(1,5))
    def write_noise(self,level,enabled):
        try:self.request(1,5,2,bytes([10-level,int(enabled)]),timeout=.25)
        except Exception as e:
            if not (isinstance(e,socket.timeout) or type(e).__name__=='BmapTimeoutError' or (isinstance(e,ProtocolError) and 'acknowledge' in str(e))):raise
            # Some firmware applies SETGET without sending its STATUS reply.
            # Continue with a read, never repeat an ambiguous write.
    def set_noise(self,level,enabled):
        validate_noise(level,enabled)
        before=self.noise()
        self.write_noise(level,enabled)
        after=self.noise()
        # NC700 enabling from Off can reset to maximum. Correct only after a
        # confirmed read; never resend an unconfirmed write.
        if not before['enabled'] and enabled and after['enabled'] and after['level']!=level:
            self.write_noise(level,True);after=self.noise()
        if after['enabled']!=enabled or (enabled and after['level']!=level):
            raise ProtocolError('Noise-control change was not verified; refresh before retrying')
        return after
    def status(self):
        ident=self.request(0,3)
        if len(ident)!=3 or ident[:2]!=b'\x40\x24':
            raise ProtocolError('This controller supports only the Bose NC700')
        addresses=parse_list(self.request(4,4))
        devices=[parse_info(self.request(4,5,payload=a),a) for a in addresses]
        battery=None
        try:
            raw=self.request(2,2)
            if len(raw)==1 and raw[0]<=100:battery=raw[0]
        except ProtocolError:pass
        noise=None
        try:noise=self.noise()
        except Exception:pass
        return {'devices':devices,'battery':battery,'product':'Bose 700','capacity':2,'noise':noise}
    def action(self,action,address):
        a=mac_bytes(address)
        try:
            if action=='connect': self.request(4,1,5,b'\0'+a,expected=(7,))
            elif action=='disconnect':self.request(4,2,5,a,expected=(7,),timeout=.25)
            else:raise ValueError('Unknown action')
        except Exception as e:
            if isinstance(e,socket.timeout) or type(e).__name__=='BmapTimeoutError' or (isinstance(e,ProtocolError) and 'acknowledge' in str(e)):
                raise ActionUnconfirmed('No acknowledgement; verify the state without repeating the command') from e
            raise

class MacSocket:
    def __init__(self,address,channel):
        # Native IOBluetooth implementation from MIT-licensed upstream.
        sys.path.insert(0,str(__import__('pathlib').Path(__file__).parent/'vendor/bosectl/python'))
        from pybmap.transport import MacOsRfcommTransport
        self.transport=MacOsRfcommTransport(address,channel,timeout=4)
        self.transport.connect(); self.data=b'';self.timeout=4
    def sendall(self,data):
        status=self.transport.channel.writeSync_length_(data,len(data))
        if status!=0:raise ProtocolError(f'Bluetooth write failed: {status}')
    def settimeout(self,value):self.timeout=value
    def recv(self,n):
        from Foundation import NSRunLoop,NSDate,NSDefaultRunLoopMode
        deadline=time.monotonic()+self.timeout
        while time.monotonic()<deadline:
            if not self.transport.delegate.received_queue.empty():
                return bytes(self.transport.delegate.received_queue.get())
            if self.transport.delegate.closed_event.is_set():raise ProtocolError('Headset closed the control connection')
            NSRunLoop.currentRunLoop().runMode_beforeDate_(NSDefaultRunLoopMode,NSDate.dateWithTimeIntervalSinceNow_(.01))
        raise socket.timeout('Bluetooth response timed out')
    def close(self):self.transport.close()

@contextmanager
def connection(address,channel):
    sock=None
    try:
        if sys.platform=='darwin':sock=MacSocket(address,channel)
        else:
            sock=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_STREAM,socket.BTPROTO_RFCOMM)
            for attempt in range(12):
                sock.settimeout(4)
                try:sock.connect((address,channel));break
                except OSError as e:
                    if e.errno!=errno.EBUSY or attempt==11:raise
                    # RFCOMM close completes asynchronously. Retry only opening
                    # the socket, before sending any protocol command.
                    sock.close();time.sleep(.1)
                    sock=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_STREAM,socket.BTPROTO_RFCOMM)
        yield Client(sock)
    finally:
        if sock:sock.close()
