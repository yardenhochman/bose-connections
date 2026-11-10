"""A simulated headset, BlueZ link and PipeWire sink shared by three real Controllers (pc, phone, mac), on a fake clock.

No real Bluetooth, D-Bus or PipeWire is touched: each controller's local_status/open_headset, the PC's peer_call,
prepare_connect and Audio are replaced. The PC hub gets BlueZ/PipeWire events directly from the world, as its
watchers would deliver them. Use `with world.running():` to patch time.monotonic/time.sleep to the fake clock."""
import contextlib, sys, threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import controller
from controller import Controller,HeadsetUnreachable,ReplyError
from protocol import ActionUnconfirmed,ProtocolError

PC='AA:AA:AA:AA:AA:AA';PHONE='BB:BB:BB:BB:BB:BB';TV='CC:CC:CC:CC:CC:CC';MAC='DD:DD:DD:DD:DD:DD'
ROLES={'pc':PC,'phone':PHONE,'mac':MAC}
NAMES={PC:'yarden-omarchy',PHONE:'Yarden’s S22 Ultra',MAC:'Yarden’s MacBook',TV:'Living room TV'}
SINK='bluez_output.AA_AA_AA_AA_AA_AA.1'
URLS={'phone':'http://100.64.0.2:8848','mac':'http://100.64.0.3:8848'}

class Clock:
    def __init__(self):self.now=1000.0;self.lock=threading.Lock()
    def monotonic(self):return self.now
    def sleep(self,seconds):
        with self.lock:self.now+=max(0,seconds)

class Client:
    """BMAP as seen by one controller."""
    def __init__(self,world,ident):self.w=world;self.ident=ident
    def status(self,full=True,check_ident=True):
        w=self.w;w.clock.sleep(w.read_time);w.reads+=1
        devices=[dict(address=d['address'],name=d['name'],connected=d['connected'],current=d['address']==ROLES[self.ident]) for d in w.devices]
        out={'devices':devices,'capacity':2}
        if full:out.update(battery=w.battery,product='Bose 700',noise=dict(level=10,enabled=True))
        return out
    def action(self,action,address):
        w=self.w;w.calls.append((action,address,self.ident))
        if action=='disconnect':
            w.clock.sleep(w.disconnect_time)
            if w.refuse_disconnect:raise ActionUnconfirmed('no ack')
            w.set_connected(address,False);return
        w.connects+=1;w.clock.sleep(w.connect_time)
        step=w.script.pop(0) if w.script else 'connect_ok'
        if step=='hang':w.clock.sleep(controller.SWITCH_DEADLINE+1);raise ActionUnconfirmed('no answer')
        if step=='connect_unconfirmed':raise ActionUnconfirmed('no ack')
        if len(w.held())>=2:raise ProtocolError('Headset rejected 4.1: 05')
        w.set_connected(address,True)
    def pairing_mode(self):pass

class Audio:
    """This PC's BlueZ link and PipeWire sink, derived from the world."""
    path='/org/bluez/hci0/dev_AA_AA_AA_AA_AA_AA'
    def __init__(self,world):self.w=world;self.current='alsa_output.speakers';self.pages=0;self.gate=None
    def linked(self):return not self.w.down and PC in self.w.held()
    def page(self):
        w=self.w;self.pages+=1
        if self.gate:self.gate.wait(10)
        w.clock.sleep(w.page_time)
        if w.down or not w.page_ok:return 'org.bluez.Error.Failed: Page Timeout'
        if len(w.held())>=2:return 'org.bluez.Error.Failed: busy'
        w.set_connected(PC,True);return ''
    def sink(self):return SINK if self.linked() and self.w.has_sink else None
    def default(self):return self.current
    def set_default(self,sink):self.current=sink;self.w.emit()
    def connect_a2dp(self):return ''
    def drop(self):self.w.set_connected(PC,False);return ''
    def in_use(self):return True
    def restart_audio(self):pass
    def key_refused(self,since):return False
    def transport(self):
        # flows: 'playing' (something already plays), 'chime' (idle until the chime plays), False (connected but silent)
        if not self.sink():return ''
        f=self.w.flows;return 'active' if f=='playing' or f=='chime' and getattr(self,'chimes',0) else 'idle'
    def chime(self,sink):self.chimes=getattr(self,'chimes',0)+1;return None

class World:
    def __init__(self,start,apps=('phone','mac'),page_ok=True,script=(),down=False,refuse_disconnect=False,has_sink=True,
                 read_time=.25,page_time=2.0,connect_time=1.0,disconnect_time=.4,watch=True,flows='playing'):
        self.clock=Clock();self.devices=[dict(address=a,name=NAMES[a],connected=a in start) for a in (PHONE,PC,MAC,TV)]
        self.apps=set(apps)|{'pc'};self.page_ok=page_ok;self.script=list(script);self.down=down;self.refuse_disconnect=refuse_disconnect
        self.flows=flows;self.has_sink=has_sink;self.read_time=read_time;self.page_time=page_time;self.connect_time=connect_time;self.disconnect_time=disconnect_time
        self.battery=40;self.reads=0;self.connects=0;self.calls=[];self.audio=Audio(self)
        self.pc=self.controller('pc',peers=True);self.phone=self.controller('phone');self.mac=self.controller('mac')
        self.peers={'phone':self.phone,'mac':self.mac}
        self.pc.audio=self.audio;self.pc.prepare_connect=lambda data:{'ok':True};self.pc.peer_call=self.peer_call
        self.hub=self.pc.hub
        if watch:  # what BluezWatcher / PactlWatcher deliver once started
            self.hub.link_watched=True;self.hub.audio_watched=True;self.hub.idle_wait=self.clock.sleep
        self.watch=watch;self.emit()
    def controller(self,ident,peers=False):
        config=dict(id=ident,name=ident.upper(),headset=PC,roles=dict(ROLES),token='t',
                    peers=[dict(id=i,name=i.title(),url=URLS[i]) for i in ('phone','mac')] if peers else [])
        c=Controller(config);c.local_status=lambda:self.status_of(ident)
        @contextlib.contextmanager
        def open_headset():
            if not self.can_read(ident):raise HeadsetUnreachable('no route')
            yield Client(self,ident)
        c.open_headset=open_headset
        return c
    # ---- world state ----
    def held(self):return [d['address'] for d in self.devices if d['connected']]
    def set_connected(self,address,value):
        for d in self.devices:
            if d['address']==address:d['connected']=value
        self.emit()
    def emit(self):
        """BlueZ PropertiesChanged and pactl sink events, delivered to the PC hub at once."""
        if getattr(self,'watch',False):
            self.hub.set_link(self.audio.linked());sink=self.audio.sink()
            self.hub.set_audio(sink,bool(sink) and self.audio.current==sink)
    def can_read(self,ident):return not self.down and ident in self.apps and ROLES[ident] in self.held()
    def status_of(self,ident):
        if ident not in self.apps:return dict(controller=ident,node=ident,reachable=False,transport=True,error='Controller unavailable: ConnectionRefusedError')
        if self.down:return dict(controller=ident,node=ident,reachable=False,error='Headset unreachable',devices=[])
        if ROLES[ident] not in self.held():
            return dict(controller=ident,node=ident,reachable=False,link=False,error='Headset is not connected to this '+ident.upper(),devices=[])
        state=Client(self,ident).status();state.update(reachable=True,controller=ident,node=ident,observed=self.clock.now)
        return state
    def peer_call(self,peer,path,data=None,timeout=None):
        ident=peer['id']
        if ident not in self.apps:return dict(reachable=False,transport=True,node=ident,controller=ident,error='Controller unavailable: ConnectionRefusedError')
        if path=='/api/status':return self.status_of(ident)
        if path=='/api/prepare-connect':return {'ok':True}
        try:return self.peers[ident].relay_action(data)
        except ReplyError as e:return e.reply
        except Exception as e:return {'ok':False,'error':str(e)}
    @contextlib.contextmanager
    def running(self):
        with patch('controller.time.monotonic',self.clock.monotonic),patch('controller.time.sleep',self.clock.sleep):
            try:yield self
            finally:
                for c in (self.pc,self.phone,self.mac):c.status_pool.shutdown(wait=True)
    def wait_done(self,timeout=10):
        """Follow the hub like a front end until the operation leaves its running phases; returns the last state."""
        state=self.hub.state()
        import time as t
        end=t.perf_counter()+timeout
        while t.perf_counter()<end:
            op=state['operation']
            if op and op['phase'] in ('done','failed','choose'):return state
            state=self.hub.state(state['seq'],1)
        raise AssertionError('operation did not finish: %r'%(state['operation'],))
