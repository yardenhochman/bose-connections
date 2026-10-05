#!/usr/bin/env python3
"""Local GUI and authenticated symmetric relay for the personal Bose controller."""
import argparse, concurrent.futures, hmac, http.client, ipaddress, json, os, queue, socket, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit
from protocol import connection, mac_bytes, ProtocolError, ActionUnconfirmed, validate_noise
ROOT=Path(__file__).resolve().parent
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
                    if status.stdout.strip()!='b true':raise ProtocolError('Headset is not connected to this PC')
                if sys.platform=='darwin':
                    from IOBluetooth import IOBluetoothDevice
                    device=IOBluetoothDevice.deviceWithAddressString_(self.config['headset'])
                    if not device or not device.isConnected():raise ProtocolError('Headset is not connected to this Mac')
                with connection(self.config['headset'],self.channel) as client:state=client.status()
                state.update(reachable=True,node=self.config['name'],controller=self.config['id'],observed=time.time())
                self.cache=state;self.last_error=None
                return state
            except Exception as e:
                self.last_error=str(e)
                return dict(node=self.config['name'],controller=self.config['id'],reachable=False,error=str(e),devices=self.cache.get('devices',[]),stale=True)
    def peer_call(self,peer,path,data=None):
        parts=urlsplit(peer['url'])
        host=ipaddress.ip_address(parts.hostname)
        if parts.scheme!='http' or host not in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError('Peers must use Tailscale IPv4 addresses')
        con=http.client.HTTPConnection(parts.hostname,parts.port or 8848,timeout=2)
        try:
            con.connect();con.sock.settimeout(90 if data is not None else 35)
            con.request('POST' if data is not None else 'GET',path,body=json.dumps(data) if data is not None else None,headers={'Authorization':'Bearer '+self.config['token'],'Content-Type':'application/json'})
            response=con.getresponse();raw=response.read(65537)
            if len(raw)>65536:raise ValueError('Oversized peer response')
            return json.loads(raw)
        except Exception as e:return dict(reachable=False,node=peer['name'],controller=peer['id'],error=f'Controller unavailable: {type(e).__name__}')
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
    def overview(self,wait_all=False,exclude_current=None):
        # Reuse unfinished probes; show a fresh successful controller immediately.
        sources=[(self.config['id'],self.config['name'],self.local_status)]+[
            (p['id'],p['name'],lambda p=p:self.peer_call(p,'/api/status')) for p in self.config.get('peers',[])]
        with self.probe_lock:
            jobs=[]
            for ident,name,probe in sources:
                old=self.probes.get(ident)
                job=old if old is not None and not old.done() else self.status_pool.submit(probe)
                self.probes[ident]=job;jobs.append((ident,name,job))
        remaining={job for _,_,job in jobs};deadline=time.monotonic()+35
        while remaining:
            done,remaining=concurrent.futures.wait(remaining,timeout=max(0,deadline-time.monotonic()),return_when=concurrent.futures.FIRST_COMPLETED)
            if (not wait_all and any(j.result().get('reachable') and not any(d.get('current') and d['address']==exclude_current for d in j.result().get('devices',[])) for j in done)) or not done:break
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
        if valid:self.store_snapshot(result)
        elif not wait_all:
            previous=self.cached_overview()
            result.update(devices=previous['devices'],observed=previous.get('observed'),cached=bool(previous['devices']),noise=previous.get('noise'))
        return result
    def local_action(self,data):
        if sys.platform=='darwin' and threading.current_thread()!=threading.main_thread():return on_main(lambda:self.local_action(data))
        if data.get('action')=='noise':
            level=data.get('level');enabled=data.get('enabled');validate_noise(level,enabled)
            with self.lock:
                with connection(self.config['headset'],self.channel) as client:
                    ident=client.request(0,3)
                    if len(ident)!=3 or ident[:2]!=b'\x40\x24':raise ProtocolError('This controller supports only the Bose NC700')
                    result=client.set_noise(level,enabled)
            return dict(ok=True,verified=True,noise=result,message='Noise cancellation updated')
        action=data.get('action');target=data.get('address','').upper();replace=data.get('replace','').upper()
        mac_bytes(target)
        if action not in ('connect','disconnect'):raise ValueError('Unknown action')
        if replace:mac_bytes(replace)
        with self.lock:
            with connection(self.config['headset'],self.channel) as client:
                before=client.status();devices={d['address']:d for d in before['devices']}
                if target not in devices:raise ValueError('Select a device already remembered by the headset')
                current={d['address'] for d in devices.values() if d['current']}
                anchors=set(self.config.get('roles',{}).values())|current|set(data.get('anchors',[]))
                connected={d['address'] for d in devices.values() if d['connected']}
                disconnect=target if action=='disconnect' else replace
                if action=='connect' and target in connected:return dict(ok=True,verified=True,state=before,message='Already connected')
                if action=='disconnect' and target not in connected:return dict(ok=True,verified=True,state=before,message='Already disconnected')
                if action=='connect' and len(connected)>=2 and not replace:
                    raise ValueError('Both slots are occupied. Choose which device to replace.')
                if disconnect:
                    if disconnect not in connected:raise ValueError('The device to disconnect is no longer connected; refresh')
                    if not ((connected-{disconnect})&anchors):
                        raise ValueError('Keep one phone, PC or Mac connected so control stays available. Replace the other device first.')
                    if disconnect in current:
                        raise ValueError('This controller is providing access. Use another connected controller to disconnect it.')
                    try:client.action('disconnect',disconnect)
                    except ActionUnconfirmed:pass
                    for _ in range(6):
                        interim=client.status()
                        if not any(d['address']==disconnect and d['connected'] for d in interim['devices']):break
                        time.sleep(.4)
                    else:raise ProtocolError('Disconnect was not verified; no further commands sent')
                if action=='connect':
                    try:client.action('connect',target)
                    except ActionUnconfirmed:pass
                for _ in range(8):
                    after=client.status()
                    wanted=action=='connect'
                    if any(d['address']==target and d['connected']==wanted for d in after['devices']):
                        self.cache=after
                        return dict(ok=True,verified=True,state=after,message='Connection updated')
                    time.sleep(.5)
                raise ProtocolError('Command acknowledged but connection change was not verified. Refresh before trying again.')
    def override(self,data):
        disconnect=data.get('replace') if data.get('action')=='connect' else data.get('address')
        overview=self.overview(exclude_current=disconnect)
        anchors=list(set(overview['roles'].values()))
        data={**data,'anchors':anchors}
        eligible=[s for s in overview['controllers'] if s.get('reachable')]
        # Prefer a controller that is not the one being disconnected.
        disconnect=data.get('replace') if data.get('action')=='connect' else data.get('address')
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
        state=eligible[0]
        if state['controller']==self.config['id']:return self.local_action(data)
        peer=next(p for p in self.config['peers'] if p['id']==state['controller'])
        # Never retry a mutation through another peer: a timed-out command may have succeeded.
        return self.peer_call(peer,'/api/action',data)

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
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
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
            if path=='/api/override' and not self.server.mesh:result=self.server.controller.override(data)
            elif path=='/api/prepare-connect':result=self.server.controller.prepare_connect(data)
            elif path=='/api/action' and self.server.mesh:result=self.server.controller.local_action(data)
            elif path=='/api/roles' and not self.server.mesh:
                roles=data.get('roles',{})
                if set(roles)-{'pc','phone','mac'}:raise ValueError('Unknown controller')
                for a in roles.values():mac_bytes(a)
                self.server.controller.config['roles']=roles
                save_config(self.server.controller.config,self.server.controller.config_path)
                result={'ok':True}
            else:return self.send(404,{'error':'Not found'})
            self.send(200,result)
        except (ValueError,KeyError,ProtocolError,OSError) as e:self.send(400,{'ok':False,'error':str(e)})
        except Exception as e:self.send(500,{'ok':False,'error':str(e)})

def save_config(config,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(config,indent=2));temp.chmod(0o600);temp.replace(path)

def main():
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
