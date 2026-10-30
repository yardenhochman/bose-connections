#!/usr/bin/env python3
"""Local GUI and authenticated symmetric relay for the personal Bose controller."""
import argparse, concurrent.futures, contextlib, hmac, http.client, ipaddress, json, logging, os, queue, re, shutil, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
from protocol import connection, mac_bytes, ProtocolError, ActionUnconfirmed, validate_noise
ROOT=Path(__file__).resolve().parent
TIMING=logging.getLogger('bose.timing')
PRELUDE_TTL=5.0        # reuse an overview this young for connect/disconnect checks
EXCLUDE_GRACE=5.0      # after one controller answered, wait this long at most for the rest
POLL_INTERVAL=.15      # read-back poll spacing
DISCONNECT_WAIT=4.0    # was 6 polls x 0.4 s plus six full status reads
CONNECT_WAIT=10.0      # was 4 s ack + 8 polls x 0.5 s plus eight full status reads, from command send
MAC_TEXT=re.compile(r'(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b')
# Tap-to-switch contract (tests/switch-contract.json; a test keeps these equal to it).
SOURCES=('android-app','android-tile','omarchy','web','mac-menu','mac-popover','desk','couch')
LABELS={'phone':'Phone','mac':'Mac','pc':'PC'}
MESSAGES={'pending':'Connecting…','replacing':'Replacing {label}…','ok':'Playing on Bose 700','busy':'Both slots busy · choose one to replace',
    'replace':'Replace {label}','retry_hint':' · tap to retry','errors':{'unreachable':'Couldn’t reach the headphones','timeout':'Took too long to switch',
    'unverified':'The headphones didn’t confirm the switch','keep_one':'Can’t replace that one: keep a phone, PC or Mac connected',
    'no_audio':'Connected, but no sound from the headphones','audio_not_moved':'Headphones connected, but PC audio didn’t switch'}}
REQUEST_ID=re.compile(r'[A-Za-z0-9_-]{1,32}')
SWITCH_DEADLINE=150.0  # contract rules.deadline_seconds
PAGE_WAIT=45.0;PAGE_GAP=3.0;SINK_WAIT=6.0  # Linux: page BlueZ every 3 s for up to 45 s; wait up to 6 s for the sink per recovery step
RESEND_MIN=30.0  # start a resend only with this much of the deadline left (worst-case connect)
COST=dict(page=17,a2dp=12,relink=25,restart=17)  # worst-case seconds of a blocking step: start it only when it can finish in time
A2DP_SINK='0000110b-0000-1000-8000-00805f9b34fb'
class HeadsetUnreachable(ProtocolError):
    """Raised only before any command was sent, so another controller may safely be tried."""
class NotLinked(ProtocolError):
    """The OS reports no Bluetooth link to the headset: this controller certainly holds no slot."""
class SwitchError(Exception):
    """A switch failure with its contract error key; the message is the raw reason for the log."""
    def __init__(self,key,detail):super().__init__(detail);self.key=key
class ReplyError(Exception):
    """A refused request whose JSON reply is already in contract shape."""
    def __init__(self,reply):super().__init__(reply.get('detail',''));self.reply=reply
def error_key(error):
    """Contract error key for a raw controller reason."""
    if isinstance(error,SwitchError):return error.key
    if isinstance(error,HeadsetUnreachable):return 'unreachable'
    text=str(error).lower()
    if 'both slots' in text:return 'busy'
    if 'keep one' in text or 'retaining access' in text or 'providing access' in text:return 'keep_one'
    if 'timed out' in text or 'timeout' in text:return 'timeout'
    if 'no audio' in text:return 'no_audio'
    if 'not verified' in text or 'not confirm' in text or 'acknowledg' in text:return 'unverified'
    return 'unreachable'
def error_reply(key,detail):
    return dict(ok=False,error_key=key,error=MESSAGES['errors'][key],detail=str(detail))
def clean_id(value):
    """A request id cut down to the allowed pattern (an older phone sends 36-char UUIDs), or None."""
    value=re.sub(r'[^A-Za-z0-9_-]','',value)[:32] if isinstance(value,str) else '';return value or None
def clean_tags(data):
    """Relayed /api/action: keep source/request_id only in their valid form; never refuse the action for them."""
    data=dict(data);rid=clean_id(data.pop('request_id',None))
    if data.get('source') not in SOURCES:data.pop('source',None)
    return dict(data,request_id=rid) if rid else data
def request_tags(data,allowed=None):
    """Validate the optional source/request_id a front end sends; returns (source, id) for the switch log."""
    if allowed is not None and set(data)-allowed:raise ValueError('Unknown request field')
    source=data.get('source','unknown');rid=data.get('request_id','-')
    if 'source' in data and source not in SOURCES:raise ValueError('Unknown source')
    if 'request_id' in data and not (isinstance(rid,str) and REQUEST_ID.fullmatch(rid)):raise ValueError('Invalid request id')
    return source,rid

class Audio:
    """This PC's BlueZ link to the headset and its PipeWire sink (ported from the desk bar). Tests pass a fake with the same methods."""
    def __init__(self,headset,adapter='hci0'):
        self.headset=headset.upper();self.path='/org/bluez/'+adapter+'/dev_'+self.headset.replace(':','_')
    def run(self,argv,timeout=4):
        try:
            done=subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
            return done.returncode,done.stdout.strip(),done.stderr.strip()
        except (subprocess.TimeoutExpired,OSError):return 1,'','timed out'
    def bluez(self,method,*args,timeout=4):
        code,_,err=self.run(['busctl',f'--timeout={timeout}','call','org.bluez',self.path,'org.bluez.Device1',method,*args],timeout+2)
        return '' if code==0 else err or 'failed'
    def linked(self):return self.run(['busctl','get-property','org.bluez',self.path,'org.bluez.Device1','Connected'])[1]=='b true'
    def page(self):return self.bluez('Connect',timeout=15)
    def connect_a2dp(self):
        # A card stuck on a headset (HFP) profile only needs its profile switched; with no card, ask BlueZ for A2DP.
        if self.run(['pactl','set-card-profile','bluez_card.'+self.headset.replace(':','_'),'a2dp-sink'])[0]==0:return ''
        return self.bluez('ConnectProfile','s',A2DP_SINK,timeout=10)
    def drop(self):return self.bluez('Disconnect')  # only this PC's own link
    def sink(self):
        """The headset's A2DP sink only: an HFP node would play phone-call quality audio."""
        prefix='bluez_output.'+self.headset.replace(':','_')+'.'
        try:sinks=json.loads(self.run(['pactl','--format=json','list','sinks'])[1] or '[]')
        except ValueError:return None
        return next((s['name'] for s in sinks if isinstance(s,dict) and str(s.get('name','')).startswith(prefix)
                     and str((s.get('properties') or {}).get('api.bluez5.profile','')).startswith('a2dp')),None)
    def default(self):return self.run(['pactl','get-default-sink'])[1]
    def set_default(self,sink):self.run(['pactl','set-default-sink',sink])  # WirePlumber moves streams that follow the default
    def in_use(self):
        # Only an explicit "stopped" from the playback guard frees audio for a WirePlumber restart.
        try:return json.loads((Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'playback-state.json').read_text()).get('state')!='stopped'
        except (OSError,ValueError,AttributeError):return True
    def restart_audio(self):self.run(['systemctl','--user','restart','wireplumber'],15)
def page_until_linked(audio,end):
    """Page the headset from BlueZ every PAGE_GAP s for up to PAGE_WAIT s while this PC has no link."""
    stop=min(time.monotonic()+PAGE_WAIT,end);busy=False
    while True:
        if end-time.monotonic()<COST['page']:raise SwitchError('timeout','Deadline reached while paging the headset')
        error=audio.page()
        if audio.linked():return
        busy=busy or 'busy' in error.lower()
        if time.monotonic()+PAGE_GAP>stop or end-time.monotonic()<PAGE_GAP+COST['page']:
            raise SwitchError('unreachable','BlueZ paging failed: '+('both slots busy' if busy else error or 'not linked'))
        time.sleep(PAGE_GAP)
def await_sink(audio,end):
    stop=min(time.monotonic()+SINK_WAIT,end)
    while True:
        sink=audio.sink()
        if sink or time.monotonic()>=stop:return sink
        time.sleep(.5)
def ensure_sink(audio,end):
    """BlueZ can report Connected while the headset refused A2DP. Recover from the least disruptive step up:
    wait, select/ask for A2DP, reconnect this PC's link, and only when audio is stopped restart WirePlumber."""
    def relink():
        audio.drop();time.sleep(1.5);audio.page()
        if not audio.linked():raise SwitchError('unreachable','This PC lost its link while reconnecting audio')
    for name,step,cost in ((None,None,0),('a2dp',audio.connect_a2dp,COST['a2dp']),('relink',relink,COST['relink']),('restart',audio.restart_audio,COST['restart'])):
        if name=='restart' and audio.in_use():break
        if step:
            if end-time.monotonic()<cost+1:break
            step()
        sink=await_sink(audio,end)
        if sink:return sink
    raise SwitchError('no_audio','Connected, but no audio sink appeared')

MAIN_TASKS=queue.Queue()
def on_main(func):
    future=concurrent.futures.Future();MAIN_TASKS.put((future,func));return future.result(timeout=90)

class Controller:
    def __init__(self,config):
        self.config=config;self.lock=threading.Lock();self.channel=config.get('channel',2)
        self.cache={};self.last_error=None
        self.discovery_lock=threading.Lock();self.discovery_timer=None;self.discovery_restore=None
        self.status_pool=concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.probes={};self.probe_lock=threading.Lock();self.snapshot_lock=threading.Lock()
        self.last_overview=None;self.ident_ok=False
        self.switch_lock=threading.Lock()  # one switch or connection change at a time; a second one waits, then reads afresh
        self.audio=None  # Linux sink control for /api/switch: None = detect, False = none, or an Audio-like object (tests)
    def cached_overview(self):
        try:
            state=json.loads(Path(self.config_path).with_name('snapshot.json').read_text())
            state['cached']=True
            return state
        except (AttributeError,OSError,ValueError):
            return dict(controllers=[],devices=[],roles=self.config.get('roles',{}),reachable=False,battery=None,capacity=2,here=self.config['id'],cached=True)
    def store_snapshot(self,state):
        if hasattr(self,'config_path'):
            with self.snapshot_lock:save_config(state,Path(self.config_path).with_name('snapshot.json'))
    def local_status(self):
        if sys.platform=='darwin' and threading.current_thread()!=threading.main_thread():return on_main(self.local_status)
        with self.lock:
            try:
                if sys.platform.startswith('linux'):
                    mac_bytes(self.config['headset'])
                    adapter=self.config.get('adapter','hci0')
                    if not adapter.startswith('hci') or not adapter[3:].isdigit():raise ValueError('Invalid BlueZ adapter')
                    path='/org/bluez/'+adapter+'/dev_'+self.config['headset'].replace(':','_')
                    status=subprocess.run(['busctl','get-property','org.bluez',path,'org.bluez.Device1','Connected'],capture_output=True,text=True,timeout=2,check=True)
                    if status.stdout.strip()!='b true':raise NotLinked('Headset is not connected to this PC')
                if sys.platform=='darwin':
                    from IOBluetooth import IOBluetoothDevice
                    device=IOBluetoothDevice.deviceWithAddressString_(self.config['headset'])
                    if not device or not device.isConnected():raise NotLinked('Headset is not connected to this Mac')
                with connection(self.config['headset'],self.channel) as client:state=client.status()
                state.update(reachable=True,node=self.config['name'],controller=self.config['id'],observed=time.time())
                self.cache=state;self.last_error=None
                return state
            except Exception as e:
                self.last_error=str(e)
                state=dict(node=self.config['name'],controller=self.config['id'],reachable=False,error=str(e),devices=self.cache.get('devices',[]),stale=True)
                if isinstance(e,NotLinked):state['link']=False
                return state
    def peer_call(self,peer,path,data=None,timeout=None):
        parts=urlsplit(peer['url'])
        host=ipaddress.ip_address(parts.hostname)
        if parts.scheme!='http' or host not in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError('Peers must use Tailscale IPv4 addresses')
        con=http.client.HTTPConnection(parts.hostname,parts.port or 8848,timeout=2)
        try:
            con.connect();con.sock.settimeout(timeout or (90 if data is not None else 35))
            con.request('POST' if data is not None else 'GET',path,body=json.dumps(data) if data is not None else None,headers={'Authorization':'Bearer '+self.config['token'],'Content-Type':'application/json'})
            response=con.getresponse();raw=response.read(65537)
            if len(raw)>65536:raise ValueError('Oversized peer response')
            return json.loads(raw)
        # transport=True: no reply arrived, so the peer may still be acting on a mutation.
        except Exception as e:return dict(reachable=False,transport=True,node=peer['name'],controller=peer['id'],error=f'Controller unavailable: {type(e).__name__}')
        finally:con.close()
    def prepare_connect(self,data):
        # BlueZ can be powered but non-connectable when hidden. A short visibility
        # window permits the paired headset's incoming connection without root.
        target=data.get('address','').upper();mac_bytes(target)
        if target!=self.config.get('roles',{}).get(self.config['id']):
            raise ValueError('Only this controller can prepare its own Bluetooth connection')
        if not sys.platform.startswith('linux'):return dict(ok=True)
        adapter=self.config.get('adapter','hci0')
        if not adapter.startswith('hci') or not adapter[3:].isdigit():raise ValueError('Invalid BlueZ adapter')
        base=['busctl']
        path='/org/bluez/'+adapter
        with self.discovery_lock:
            if self.discovery_restore is None:
                value=subprocess.run(base+['get-property','org.bluez',path,'org.bluez.Adapter1','Discoverable'],capture_output=True,text=True,timeout=2,check=True).stdout.strip()
                self.discovery_restore=value=='b true'
            subprocess.run(base+['set-property','org.bluez',path,'org.bluez.Adapter1','Discoverable','b','true'],capture_output=True,timeout=2,check=True)
            if self.discovery_timer:self.discovery_timer.cancel()
            def restore():
                with self.discovery_lock:
                    try:subprocess.run(base+['set-property','org.bluez',path,'org.bluez.Adapter1','Discoverable','b',str(self.discovery_restore).lower()],capture_output=True,timeout=2,check=True)
                    finally:self.discovery_restore=None;self.discovery_timer=None
            self.discovery_timer=threading.Timer(30,restore);self.discovery_timer.daemon=True;self.discovery_timer.start()
        return dict(ok=True)
    def overview(self,wait_all=False,exclude_current=None,budget=None):
        # Reuse unfinished probes; show a fresh successful controller immediately.
        sources=[(self.config['id'],self.config['name'],self.local_status)]+[
            (p['id'],p['name'],lambda p=p:self.peer_call(p,'/api/status')) for p in self.config.get('peers',[])]
        with self.probe_lock:
            jobs=[]
            for ident,name,probe in sources:
                old=self.probes.get(ident)
                job=old if old is not None and not old.done() else self.status_pool.submit(probe)
                self.probes[ident]=job;jobs.append((ident,name,job))
        remaining={job for _,_,job in jobs};deadline=time.monotonic()+min(35,35 if budget is None else max(0,budget));grace=False
        while remaining:
            done,remaining=concurrent.futures.wait(remaining,timeout=max(0,deadline-time.monotonic()),return_when=concurrent.futures.FIRST_COMPLETED)
            if (not wait_all and any(j.result().get('reachable') and not any(d.get('current') and d['address']==exclude_current for d in j.result().get('devices',[])) for j in done)) or not done:break
            if not wait_all and not grace and any(j.result().get('reachable') for j in done):
                # One controller answered but cannot do the job (it holds the device being dropped);
                # an unreachable peer must not stall the request for the full probe timeout.
                grace=True;deadline=min(deadline,time.monotonic()+EXCLUDE_GRACE)
        states=[job.result() if job.done() else dict(controller=ident,node=name,reachable=False,checking=True,devices=[])
                for ident,name,job in jobs]
        valid=[s for s in states if s.get('reachable')]
        freshest=max(valid,key=lambda s:s.get('observed',0),default=None)
        devices=(freshest or {}).get('devices',[])
        roles=dict(self.config.get('roles',{}))
        for state in valid:
            for d in state.get('devices',[]):
                if d.get('current'):roles[state['controller']]=d['address']
        result=dict(controllers=states,devices=devices,roles=roles,reachable=bool(valid),battery=(freshest or {}).get('battery'),capacity=2,here=self.config['id'],known_roles=self.config.get('roles',{}),observed=(freshest or {}).get('observed'),cached=False,noise=(freshest or {}).get('noise'))
        if valid:self.store_snapshot(result);self.last_overview=(time.monotonic(),result)
        elif not wait_all:
            previous=self.cached_overview()
            devices=previous['devices']
            # A controller that knows it has no link to the headset holds no slot, whatever the snapshot says.
            unlinked={self.config.get('roles',{}).get(s['controller']) for s in states if s.get('link') is False}
            devices=[dict(d,connected=False,current=False) if d.get('address') in unlinked else d for d in devices]
            result.update(devices=devices,observed=previous.get('observed'),cached=bool(devices),noise=previous.get('noise'),checked=time.time())
        return result
    @contextlib.contextmanager
    def open_headset(self):
        with contextlib.ExitStack() as stack:
            try:client=stack.enter_context(connection(self.config['headset'],self.channel))
            except Exception as e:
                self.ident_ok=False
                raise HeadsetUnreachable(str(e)) from e
            yield client
    @contextlib.contextmanager
    def phase(self,timing,name):
        start=time.monotonic()
        try:yield
        finally:timing[name]=timing.get(name,0)+time.monotonic()-start
    def label(self,address,devices=None):
        for ident,value in self.config.get('roles',{}).items():
            if value==address:return ident
        for i,d in enumerate(devices or []):
            if d.get('address')==address:return f'device#{i+1}'
        return 'device#?'
    def log_timing(self,action,outcome,target,mode,timing,total,rid=None):
        parts=[f'action={action}',f'outcome={outcome}',f'target={target}']
        if isinstance(rid,str) and REQUEST_ID.fullmatch(rid):parts.append(f'id={rid}')  # same id as the origin's bose.switch line
        if mode:parts.append(f'prelude_mode={mode}')
        parts+=[f'{k}={v:.2f}s' for k,v in timing.items()]+[f'total={total:.2f}s']
        TIMING.info(MAC_TEXT.sub('device',' '.join(parts)))
    def full_state(self,read,source=None,view=None):
        """Overview-shaped state from a verified headset read merged with the latest known controllers and roles."""
        source=source or self.config['id']
        last=self.last_overview
        base=view or (last[1] if last else self.cached_overview())
        observed=read.get('observed') or time.time()
        names={p['id']:p['name'] for p in self.config.get('peers',[])};names[self.config['id']]=self.config['name']
        entry=dict(controller=source,node=names.get(source,source),reachable=True,observed=observed,devices=read['devices'],battery=read.get('battery'),noise=read.get('noise'))
        controllers=[dict(c) for c in base.get('controllers',[])]
        for i,c in enumerate(controllers):
            if c.get('controller')==source:controllers[i]=entry;break
        else:controllers.append(entry)
        roles=dict(base.get('roles') or self.config.get('roles',{}))
        for d in read['devices']:
            if d.get('current'):roles[source]=d['address']
        result=dict(controllers=controllers,devices=read['devices'],roles=roles,reachable=True,battery=read.get('battery'),capacity=2,here=self.config['id'],known_roles=self.config.get('roles',{}),observed=observed,cached=False,noise=read.get('noise'))
        self.store_snapshot(result)
        # Keep the old timestamp: peer entries merged in here are no fresher than the overview they came from.
        self.last_overview=(last[0] if last else float('-inf'),result)
        return result
    def local_action(self,data,prelude=None,mode=None):
        if sys.platform=='darwin' and threading.current_thread()!=threading.main_thread():return on_main(lambda:self.local_action(data,prelude,mode))
        timing={} if prelude is None else {'prelude':prelude}
        info=dict(outcome=None,target='-');start=time.monotonic()
        try:
            result=self.run_local_action(data,timing,info)
            info['outcome']=info['outcome'] or 'ok'
            return result
        except Exception as e:
            info['outcome']='error:'+type(e).__name__;raise
        finally:self.log_timing(str(data.get('action')),info['outcome'],info['target'],mode,timing,time.monotonic()-start+(prelude or 0),data.get('request_id'))
    def await_read(self,client,matches,wait,start=None):
        deadline=(start if start is not None else time.monotonic())+wait
        while True:
            read=client.status(full=False,check_ident=False)
            if matches(read):return read
            remaining=deadline-time.monotonic()
            if remaining<=0:return None
            time.sleep(min(POLL_INTERVAL,remaining))
    def run_local_action(self,data,timing,info):
        if data.get('action')=='noise':
            level=data.get('level');enabled=data.get('enabled');validate_noise(level,enabled)
            with self.lock:
                with self.open_headset() as client:
                    try:
                        with self.phase(timing,'before'):
                            if not self.ident_ok:
                                ident=client.request(0,3)
                                if len(ident)!=3 or ident[:2]!=b'\x40\x24':raise ProtocolError('This controller supports only the Bose NC700')
                                self.ident_ok=True
                        with self.phase(timing,'command'):result=client.set_noise(level,enabled)
                    except Exception:
                        self.ident_ok=False;raise
                    try:
                        with self.phase(timing,'verify'):fresh=client.status(full=False,check_ident=False)
                    except (ProtocolError,OSError):fresh=None
            last=self.last_overview
            known=self.cache if self.cache.get('devices') else (last[1] if last else self.cached_overview())
            if self.cache:self.cache['noise']=result
            if fresh is None:
                # No fresh device list: report only the noise change; clients re-read the overview.
                return dict(ok=True,verified=True,noise=result,message='Noise cancellation updated')
            battery=known.get('battery');observed=time.time()
            self.cache=dict(devices=fresh['devices'],battery=battery,noise=result,observed=observed)
            state=self.full_state(dict(self.cache))
            return dict(ok=True,verified=True,noise=result,state=state,message='Noise cancellation updated')
        action=data.get('action');target=data.get('address','').upper();replace=data.get('replace','').upper()
        mac_bytes(target)
        if action not in ('connect','disconnect'):raise ValueError('Unknown action')
        if replace:mac_bytes(replace)
        with self.lock:
            with self.open_headset() as client:
                try:
                    with self.phase(timing,'before'):
                        before=client.status(check_ident=not self.ident_ok);self.ident_ok=True
                    devices={d['address']:d for d in before['devices']}
                    info['target']=self.label(target,before['devices'])
                    if target not in devices:raise ValueError('Select a device already remembered by the headset')
                    current={d['address'] for d in devices.values() if d['current']}
                    anchors=set(self.config.get('roles',{}).values())|current|set(data.get('anchors',[]))
                    connected={d['address'] for d in devices.values() if d['connected']}
                    disconnect=target if action=='disconnect' else replace
                    if action=='connect' and target in connected:
                        info['outcome']='already';return dict(ok=True,verified=True,state=self.full_state(before),message='Already connected')
                    if action=='disconnect' and target not in connected:
                        info['outcome']='already';return dict(ok=True,verified=True,state=self.full_state(before),message='Already disconnected')
                    if action=='connect' and len(connected)>=2 and not replace:
                        raise ValueError('Both slots are occupied. Choose which device to replace.')
                    interim=None
                    if disconnect:
                        if disconnect not in connected:raise ValueError('The device to disconnect is no longer connected; refresh')
                        if not ((connected-{disconnect})&anchors):
                            raise ValueError('Keep one phone, PC or Mac connected so control stays available. Replace the other device first.')
                        if disconnect in current:
                            raise ValueError('This controller is providing access. Use another connected controller to disconnect it.')
                        sent=time.monotonic()
                        with self.phase(timing,'command'):
                            try:client.action('disconnect',disconnect)
                            except ActionUnconfirmed:pass
                        with self.phase(timing,'verify'):
                            interim=self.await_read(client,lambda s:not any(d['address']==disconnect and d['connected'] for d in s['devices']),DISCONNECT_WAIT,sent)
                        if interim is None:raise ProtocolError('Disconnect was not verified; no further commands sent')
                    if action=='connect':
                        sent=time.monotonic()
                        # An unacknowledged connect is never resent: wait for read-back instead.
                        with self.phase(timing,'command'):
                            try:client.action('connect',target)
                            except ActionUnconfirmed:pass
                        with self.phase(timing,'verify'):
                            after=self.await_read(client,lambda s:any(d['address']==target and d['connected'] for d in s['devices']),CONNECT_WAIT,sent)
                    else:after=interim
                    if after is None:raise ProtocolError('Command acknowledged but connection change was not verified. Refresh before trying again.')
                except ValueError:raise
                except Exception:
                    self.ident_ok=False;raise
                after=dict(after,battery=before.get('battery'),noise=before.get('noise'),observed=time.time())
                self.cache=after
                return dict(ok=True,verified=True,state=self.full_state(after),message='Connection updated')
    def prelude_overview(self,disconnect,budget=None):
        last=self.last_overview
        if last and time.monotonic()-last[0]<=PRELUDE_TTL and self.usable(last[1],disconnect):return last[1],'reused'
        return self.overview(exclude_current=disconnect,budget=budget),'fresh'
    @staticmethod
    def usable(view,disconnect):
        return any(s.get('reachable') and not any(d.get('current') and d['address']==disconnect for d in s.get('devices',[])) for s in view.get('controllers',[]))
    def adopt_peer_state(self,result,source,view):
        if not isinstance(result,dict) or not result.get('ok') or not result.get('verified'):return result
        state=result.get('state')
        if isinstance(state,dict) and isinstance(state.get('devices'),list):
            read=dict(devices=state['devices'],battery=state.get('battery'),noise=state.get('noise'),observed=state.get('observed'))
        elif result.get('noise'):read=dict(devices=view.get('devices',[]),battery=view.get('battery'),noise=result['noise'],observed=time.time())
        else:
            result['state']=self.overview(wait_all=False);return result  # older peer without a state: one fresh read
        return dict(result,state=self.full_state(read,source,view))
    def override(self,data,info=None,budget=None):
        """budget: seconds left of a switch deadline; bounds the prelude wait and the relay timeout."""
        start=time.monotonic();info=info if info is not None else {}
        if data.get('action')=='noise' and self.cache and self.last_error is None:
            # This controller already talks to the headset: no overview needed.
            try:return self.local_action(data,0.0,'skipped')
            except HeadsetUnreachable:self.last_overview=None  # a cached prelude would pick this failed controller again
        disconnect=data.get('replace') if data.get('action')=='connect' else data.get('address')
        overview,mode=self.prelude_overview(disconnect,budget)
        prelude=time.monotonic()-start
        anchors=list(set(overview['roles'].values()))
        data={**clean_tags(data),'anchors':anchors}
        eligible=[s for s in overview['controllers'] if s.get('reachable')]
        # Prefer a controller that is not the one being disconnected.
        eligible=[s for s in eligible if not any(d.get('current') and d['address']==disconnect for d in s.get('devices',[]))]
        if not eligible:raise ValueError('No controller can perform this change while retaining access. Refresh or connect a controller manually.')
        if data.get('action')=='connect':
            target=data.get('address','').upper()
            if target==overview['roles'].get(self.config['id']):self.prepare_connect(data)
            else:
                destination=next((p for p in self.config.get('peers',[]) if target==overview['roles'].get(p['id'])),None)
                if destination and destination['id']=='pc':
                    prepared=self.peer_call(destination,'/api/prepare-connect',{'address':target})
                    if not prepared.get('ok'):raise ValueError(prepared.get('error','Target controller unavailable'))
        state=eligible[0];info['via']='local' if state['controller']==self.config['id'] else 'peer:'+state['controller']
        if state['controller']==self.config['id']:return self.local_action(data,prelude,mode)
        peer=next(p for p in self.config['peers'] if p['id']==state['controller'])
        # Never retry a mutation through another peer: a timed-out command may have succeeded.
        timeout=None if budget is None else max(1.0,min(90.0,budget-(time.monotonic()-start)))  # a reply cut off by this counts as outstanding
        sent=time.monotonic();result=self.peer_call(peer,'/api/action',data,timeout);relay=time.monotonic()-sent
        outcome='ok' if isinstance(result,dict) and result.get('ok') else 'error'
        self.log_timing(str(data.get('action')),outcome,self.label(data.get('address','').upper(),overview.get('devices')),mode,dict(prelude=prelude,relay=relay),time.monotonic()-start,data.get('request_id'))
        return self.adopt_peer_state(result,state['controller'],overview)
    # ---- Tap to switch: one line per request, role labels only ----
    def role_label(self,address,devices=None):
        role=self.label(address,devices);return LABELS.get(role,role)
    def log_switch(self,source,rid,info,outcome,start):
        TIMING.info(MAC_TEXT.sub('device',f"bose.switch source={source} id={rid} target={info.get('target','-')} replace={info.get('replace','-')} outcome={outcome} via={info.get('via','local')} total={time.monotonic()-start:.2f}s"))
    def override_request(self,data):
        """POST /api/override from a front end. Connection changes take the switch lock, carry contract texts and log one bose.switch line."""
        if data.get('action') not in ('connect','disconnect'):request_tags(data);return self.override(data)  # noise: not a switch, no line
        start=time.monotonic();info=dict(via='local');outcome='error:invalid';source=rid='?'
        try:
            source,rid=request_tags(data)
            known=(self.last_overview or (0,{}))[1].get('devices')
            info['target']=self.role_label(str(data.get('address','')).upper(),known)
            if data.get('replace'):info['replace']=self.role_label(str(data['replace']).upper(),known)
            with self.switch_lock:
                try:result=self.override(data,info)
                except Exception as e:result=self.refusal(e,None)
                result=self.contract_result(result)
            outcome='ok' if result.get('ok') else 'busy' if result.get('busy') else 'error:'+result['error_key']
            if not result.get('ok'):raise ReplyError(result)
            return result
        finally:self.log_switch(source,rid,info,outcome,start)
    def relay_action(self,data):
        """Mesh /api/action from a peer: runs here; a connection change logs one bose.switch line with the origin's id (via=local)."""
        data=clean_tags(data)
        if data.get('action') not in ('connect','disconnect'):return self.local_action(data)
        start=time.monotonic();info=dict(via='local',target=self.role_label(str(data.get('address','')).upper()),replace=self.role_label(str(data['replace']).upper()) if data.get('replace') else '-')
        outcome='error:unreachable'
        try:
            try:result=self.local_action(data)
            except Exception as e:
                key=error_key(e);raise ReplyError(dict(ok=False,error_key=key,error=MESSAGES['busy'] if key=='busy' else MESSAGES['errors'][key],detail=str(e))) from e
            outcome='ok';return result
        except ReplyError as e:
            outcome='error:'+e.reply['error_key'];raise
        finally:self.log_switch(data.get('source','unknown'),data.get('request_id','-'),info,outcome,start)
    def refusal(self,error,view):
        """Contract reply for a refused connection change; full slots become a busy reply from a fresh read."""
        key=error_key(error)
        if key=='busy':return self.busy_reply(view or self.overview())
        return error_reply(key,error)
    def contract_result(self,result):
        if isinstance(result,dict) and (result.get('ok') and result.get('verified') or result.get('busy') or result.get('error_key') in MESSAGES['errors']):
            return result
        raw=str((result or {}).get('error') or (result or {}).get('message') or 'Change not verified')
        key=error_key(raw) if not (result or {}).get('transport') else ('timeout' if 'timeout' in raw.lower() else 'unreachable')
        return self.refusal(SwitchError(key,raw),None) if key=='busy' else error_reply(key,raw)
    def switch_request(self,data):
        """POST /api/switch: move the headset to this controller's own device. Always one bose.switch line.
        A second tap while one runs waits for it, then reads afresh (already here: no second connect)."""
        start=time.monotonic();info=dict(via='local');outcome='error:invalid';source=rid='?'
        try:
            source,rid=request_tags(data,{'source','request_id','replace'})
            if 'source' not in data:raise ValueError('Missing source')
            if 'replace' in data and not isinstance(data['replace'],str):raise ValueError('Invalid replace address')
            if data.get('replace'):mac_bytes(data['replace'])
            with self.switch_lock:
                try:result=self.switch(data,info)
                except Exception as e:result=error_reply(error_key(e) if error_key(e)!='busy' else 'unverified',e)
            outcome='ok' if result.get('ok') else 'busy' if result.get('busy') else 'error:'+result['error_key']
            return result
        finally:self.log_switch(source,rid,info,outcome,start)
    def switch_audio(self):
        if self.audio is None:
            self.audio=Audio(self.config['headset'],self.config.get('adapter','hci0')) if sys.platform.startswith('linux') and shutil.which('pactl') else False
        return self.audio or None
    @staticmethod
    def held(view):return [d for d in view.get('devices',[]) if d.get('connected')] if view.get('reachable') else []
    def busy_reply(self,view):
        connected=self.held(view)
        def label(d):
            role=self.label(d['address'],None);return LABELS.get(role) or d.get('name') or 'device'
        return dict(ok=False,busy=True,error_key='busy',error=MESSAGES['busy'],slots=[dict(address=d['address'],label=label(d)) for d in connected])
    def switch(self,data,info):
        """Move the headset to roles[config id] with a true status (tests/switch-contract.json).
        Never guesses a slot to drop; resends at most once, after a fresh read shows the target absent and a slot free."""
        end=time.monotonic()+SWITCH_DEADLINE;here=self.config['id'];audio=self.switch_audio()
        target=str(self.config.get('roles',{}).get(here,'')).upper()
        info.update(target=LABELS.get(here,here),replace='-',via='local')
        def left():return end-time.monotonic()
        def check_time(what):
            if left()<=0:raise SwitchError('timeout',what+' passed the switch deadline')
        def connected(view):return target in {d['address'] for d in self.held(view or {})}
        if not target:raise SwitchError('unreachable','This controller has no device role')
        view=self.overview(budget=left());check_time('First read')
        if not view.get('reachable') and audio:
            # No controller reaches the headset: this PC pages it from BlueZ, then reads again.
            page_until_linked(audio,end);view=self.overview(budget=left());check_time('Read after paging')
        if not view.get('reachable'):raise SwitchError('unreachable','No controller can read the headset')
        held={d['address'] for d in self.held(view)}
        if target in held:return self.switch_done(view,end)
        if target not in {d.get('address') for d in view['devices']}:raise SwitchError('unreachable','This device is not saved on the headset')
        replace=str(data.get('replace') or '').upper() or None
        if replace and (len(held)<2 or replace not in held):replace=None  # honoured only while both slots are still busy and it still holds one
        if len(held)>=2 and not replace:return self.busy_reply(view)
        if replace:info['replace']=self.role_label(replace,view['devices'])
        tags={k:data[k] for k in ('source','request_id') if k in data}
        for attempt in range(2):
            result=error=None
            try:result=self.override(dict(tags,action='connect',address=target,**({'replace':replace} if replace else {})),info,left())
            except Exception as e:error=e
            # A verified connect counts even when it lands after the deadline.
            if isinstance(result,dict) and result.get('ok') and result.get('verified') and connected(result.get('state')):
                return self.switch_done(result['state'],end)
            # A transport failure means the peer's reply may still be outstanding: never send another connect.
            raw=str(error) if error else str((result or {}).get('detail') or (result or {}).get('error') or (result or {}).get('message') or 'Connect not confirmed')
            if isinstance(result,dict) and result.get('transport'):
                raise SwitchError('timeout' if 'timeout' in raw.lower() else 'unreachable',raw)
            # Not confirmed: exactly one fresh read decides.
            fresh=self.overview(wait_all=False,budget=max(1.0,left()))
            if connected(fresh):return self.switch_done(fresh,end)
            check_time('Connect')
            if not fresh.get('reachable'):raise SwitchError('unreachable',raw)
            key=error_key(error) if error else (result or {}).get('error_key') or error_key(raw)
            if key=='busy':return self.busy_reply(fresh)
            if key in ('keep_one','no_audio','audio_not_moved'):raise SwitchError(key,raw)
            if attempt or len(self.held(fresh))>=2:raise SwitchError('unverified',raw)
            if left()<RESEND_MIN:raise SwitchError('timeout','Too little time left to resend: '+raw)
            replace=None  # the slot is free now
        raise SwitchError('unverified','Connect not confirmed')
    def switch_done(self,state,end):
        """The headset shows this device connected. On a Linux PC, also make its A2DP sink the default; macOS routes audio itself."""
        audio=self.switch_audio()
        if audio:
            if not audio.linked():page_until_linked(audio,end)
            sink=ensure_sink(audio,end)
            if audio.default()!=sink:
                audio.set_default(sink)
                if audio.default()!=sink:raise SwitchError('audio_not_moved','Default sink read-back differs')
        return dict(ok=True,verified=True,message=MESSAGES['ok'],state=state)

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,controller,mesh=False):
        self.controller=controller;self.mesh=mesh
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,data,kind='application/json'):
        raw=json.dumps(data).encode() if kind=='application/json' else data
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(raw)
    def allowed(self):
        if self.server.mesh:
            remote=ipaddress.ip_address(self.client_address[0])
            if remote not in ipaddress.ip_network('100.64.0.0/10'):return False
            return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.controller.config['token'])
        host=self.headers.get('Host','')
        if host not in ('127.0.0.1:8847','localhost:8847'):return False
        origin=self.headers.get('Origin')
        return not origin or origin in ('http://127.0.0.1:8847','http://localhost:8847')
    def do_GET(self):
        path=urlsplit(self.path).path
        if not self.allowed():return self.send(403,{'error':'Access denied'})
        if path=='/api/diagnostics' and sys.platform=='darwin':
            import objc
            from Foundation import NSBundle,NSRunLoop,NSDate,NSDefaultRunLoopMode
            from IOBluetooth import IOBluetoothDevice
            NSBundle.bundleWithPath_('/System/Library/Frameworks/CoreBluetooth.framework').load()
            dev=IOBluetoothDevice.deviceWithAddressString_(self.server.controller.config['headset'])
            dev.performSDPQuery_(None);end=time.monotonic()+1.5
            while time.monotonic()<end:NSRunLoop.currentRunLoop().runMode_beforeDate_(NSDefaultRunLoopMode,NSDate.dateWithTimeIntervalSinceNow_(.05))
            services=[]
            for service in dev.services() or []:
                try:services.append({'name':str(service.getServiceName()),'channel':str(service.getRFCOMMChannelID_(None))})
                except Exception as e:services.append({'error':str(e)})
            return self.send(200,dict(authorization=objc.lookUpClass('CBManager').authorization(),paired=bool(dev.isPaired()),connected=bool(dev.isConnected()),services=services))
        if path=='/api/status':return self.send(200,self.server.controller.local_status())
        if path=='/api/cached' and not self.server.mesh:return self.send(200,self.server.controller.cached_overview())
        if path=='/api/overview':return self.send(200,self.server.controller.overview())
        if self.server.mesh:return self.send(404,{'error':'Not found'})
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css'),'/favicon.svg':('favicon.svg','image/svg+xml'),'/fonts/jost-latin.woff2':('fonts/jost-latin.woff2','font/woff2'),'/fonts/jost-latin-ext.woff2':('fonts/jost-latin-ext.woff2','font/woff2')}
        if path not in files:return self.send(404,{'error':'Not found'})
        name,kind=files[path];self.send(200,(ROOT/'web'/name).read_bytes(),kind)
    def do_POST(self):
        if not self.allowed():return self.send(403,{'error':'Access denied'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=4096:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Invalid request')
            path=urlsplit(self.path).path
            if path=='/api/override' and not self.server.mesh:result=self.server.controller.override_request(data)
            elif path=='/api/switch' and not self.server.mesh:result=self.server.controller.switch_request(data)
            elif path=='/api/prepare-connect':result=self.server.controller.prepare_connect(data)
            elif path=='/api/action' and self.server.mesh:result=self.server.controller.relay_action(data)
            elif path=='/api/roles' and not self.server.mesh:
                roles=data.get('roles',{})
                if set(roles)-{'pc','phone','mac'}:raise ValueError('Unknown controller')
                for a in roles.values():mac_bytes(a)
                self.server.controller.config['roles']=roles
                save_config(self.server.controller.config,self.server.controller.config_path)
                result={'ok':True}
            else:return self.send(404,{'error':'Not found'})
            self.send(200,result)
        except ReplyError as e:self.send(400,e.reply)
        except (ValueError,KeyError,ProtocolError,OSError) as e:self.send(400,{'ok':False,'error':str(e)})
        except Exception as e:self.send(500,{'ok':False,'error':str(e)})

def save_config(config,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(config,indent=2));temp.chmod(0o600);temp.replace(path)

def main():
    logging.basicConfig(level=logging.INFO,format='%(message)s',stream=sys.stdout)
    parser=argparse.ArgumentParser();parser.add_argument('--config',default=str(Path.home()/'.local/state/bose-control/config.json'));parser.add_argument('--status',action='store_true')
    args=parser.parse_args();config=json.loads(Path(args.config).read_text());ctl=Controller(config);ctl.config_path=args.config
    if args.status:print(json.dumps(ctl.local_status(),indent=2));return
    for attempt in range(6):
        try:
            servers=[Server(('127.0.0.1',8847),ctl)];break
        except OSError as e:
            if not os.environ.get('BOSE_PARENT_PID') or e.errno not in (48,98) or attempt==5:raise
            time.sleep(.5)
    if config.get('mesh_bind'):servers.append(Server((config['mesh_bind'],8848),ctl,True))
    for server in servers:threading.Thread(target=server.serve_forever,daemon=True).start()
    print('Bose controller GUI: http://127.0.0.1:8847',flush=True)
    try:
        while True:
            try:
                future,func=MAIN_TASKS.get(timeout=.2)
                try:future.set_result(func())
                except Exception as error:future.set_exception(error)
            except queue.Empty:pass
            parent=os.environ.get('BOSE_PARENT_PID')
            if parent and os.getppid()!=int(parent):break
    except KeyboardInterrupt:pass
    finally:
        for server in servers:server.shutdown();server.server_close()
if __name__=='__main__':main()
