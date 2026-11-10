"""Connection state machine on the PC hub (docs/state-machine.md): the reconciled device model every front end renders
(`GET /api/state`), the one-at-a-time operation record with per-step timing, and the BlueZ / PipeWire watchers.

The switch algorithm itself (which step runs when) lives in controller.Controller.switch; this module only records and
renders. Times: `time.monotonic()` (looked up at call time, so tests can patch it) for ages, step seconds and expiry;
`time.time()` for the wall-clock `now`, `started_at` and `since` fields; long-poll waits use the real clock."""
import contextlib, functools, json, re, secrets, shutil, subprocess, threading, time
from time import monotonic as _real_monotonic

# Step labels and the operation's own result texts (tests/switch-contract.json "steps"; a test keeps them equal).
STEPS={'reading':'Checking the headphones','choose':'Both slots busy · choose one to replace','releasing':'Releasing the {label}',
       'connecting':'Connecting the {label}','connecting_here':'Connecting this {label}','audio':'Starting audio',
       'release_failed':'The {label} didn’t let go of the headphones','connected':'{label} connected','disconnected':'{label} disconnected'}
ORDER=('reading','choose','releasing','connecting','audio')
READ_FRESH=60.0    # a headset read older than this, with no OS evidence, makes a device `unknown`
DONE_LINGER=8.0    # a finished operation stays visible this long (or until the next tap)
POLL_MAX=25.0      # longest long-poll wait
READ_ACTIVE=20.0   # headset read cadence while a client long-polled in the last CLIENT_ACTIVE s
READ_IDLE=120.0
CLIENT_ACTIVE=60.0
MAC_TEXT=re.compile(r'(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b')
LABELS={'phone':'Phone','mac':'Mac','pc':'PC'}

def _mono():return time.monotonic()
def _locked(method):
    """Operation changes run on the worker thread while long-polls render them: hold the hub's lock."""
    @functools.wraps(method)
    def wrapper(self,*args,**kwargs):
        with (self.hub.cond if self.hub else contextlib.nullcontext()):return method(self,*args,**kwargs)
    return wrapper

class Operation:
    """One switch or connection change: phase, ordered steps with timing, device marks and the final result."""
    def __init__(self,source,target,action='switch',op_id=None,deadline=150.0,hub=None):
        self.id=op_id or secrets.token_hex(3);self.source=source;self.target=target;self.action=action
        self.deadline=deadline;self.hub=hub;self.started_at=time.time();self.t0=_mono()
        self.steps=[];self.phase=None;self.result=None;self.choices=None;self.marks={};self.finished_at=None
    @property
    def running(self):return self.phase not in ('done','failed','choose')
    @property
    def finished(self):return self.phase in ('done','failed')
    def _changed(self):
        if self.hub:self.hub.touch()
    def _find(self,name):return next((s for s in self.steps if s['name']==name),None)
    def _close_active(self,state='done'):
        now=_mono()
        for s in self.steps:
            if s['state']=='active':
                s['state']=state;s['seconds']=round(s.get('seconds',0)+now-s.pop('_t'),2);s.pop('since',None)
    def _insert(self,name,label):
        step=dict(name=name,label=label,state='pending')
        rank=ORDER.index(name) if name in ORDER else len(ORDER)
        at=next((i for i,s in enumerate(self.steps) if (ORDER.index(s['name']) if s['name'] in ORDER else len(ORDER))>rank),len(self.steps))
        self.steps.insert(at,step);return step
    @_locked
    def plan(self,names):
        """Set the steps still to come: pending steps not named are dropped, missing ones added (labels: dict or name)."""
        names=dict(names) if isinstance(names,dict) else {n:STEPS.get(n,n) for n in names}
        self.steps=[s for s in self.steps if s['state']!='pending' or s['name'] in names]
        for name,label in names.items():
            if not self._find(name):self._insert(name,label)
            elif self._find(name)['state']=='pending':self._find(name)['label']=label
        self._changed()
    @_locked
    def step(self,name,label=None,marks=None):
        """Leave the active step (done, seconds recorded) and enter `name`; marks map addresses to releasing/connecting."""
        self._close_active()
        s=self._find(name) or self._insert(name,label or STEPS.get(name,name))
        if label:s['label']=label
        s['state']='active';s['since']=time.time();s['_t']=_mono()
        self.phase=name;self.marks=dict(marks or {});self._changed()
    @_locked
    def choose(self,choices):
        self._close_active();self.steps=[s for s in self.steps if s['state']!='pending']
        if not self._find('choose'):self._insert('choose',STEPS['choose'])
        c=self._find('choose');c['state']='active';c['since']=time.time();c['_t']=_mono()
        self.phase='choose';self.choices=[dict(address=x['address'],label=x['label']) for x in choices];self.marks={};self._changed()
    @_locked
    def finish(self,ok,text,error_key=None,detail=None):
        active=next((s['name'] for s in self.steps if s['state']=='active'),self.phase)
        self._close_active('done' if ok else 'failed')
        self.steps=[s for s in self.steps if s['state']!='pending']
        seconds=round(_mono()-self.t0,2)
        if ok:self.result=dict(ok=True,text=text,seconds=seconds)
        else:self.result=dict(ok=False,error_key=error_key,text=text,step=active,detail=MAC_TEXT.sub('device',str(detail or '')),seconds=seconds)
        self.phase='done' if ok else 'failed';self.marks={};self.choices=None;self.finished_at=_mono();self._changed()
    def timings(self):return {s['name']:s['seconds'] for s in self.steps if 'seconds' in s and s['name']!='choose'}
    @_locked
    def to_json(self):
        steps=[]
        for s in self.steps:
            out={k:v for k,v in s.items() if not k.startswith('_')}
            if s['state']=='active':out['since']=round(s['since'],2)
            steps.append(out)
        out=dict(id=self.id,source=self.source,target=self.target,action=self.action,phase=self.phase,started_at=round(self.started_at,2),
                 deadline=int(self.deadline) if float(self.deadline).is_integer() else self.deadline,steps=steps,result=self.result)
        if self.phase=='choose':out['choices']=self.choices
        return out

class Hub:
    """The reconciled view (spec §1) and its change counter. Inputs: headset reads (overviews), this controller's OS
    link (BlueZ watcher / local_status), peers' `link:false`, the PipeWire sink, and the current operation."""
    def __init__(self,config):
        self.config=config;self.cond=threading.Condition(threading.RLock());self.seq=0;self.digest=None
        self.read=None          # dict(devices, battery, noise, product, via, t)
        self.reachable=False;self.controllers=[];self.controllers_t=None
        self.own_link=None;self.link_t=None;self.link_watched=False
        self.audio=None;self.audio_watched=False
        self.operation=None;self.last_poll=None
        self.idle_wait=None     # tests: a fake-clock sleep used instead of a real wait for audio events
        self.listeners=[]       # called with ('link', value) on an own-link change (the read scheduler)
    # ---- inputs ----
    def ingest(self,view):
        """An overview-shaped result (Controller.overview / full_state)."""
        if not isinstance(view,dict):return
        with self.cond:
            now=_mono();states=[s for s in view.get('controllers') or [] if isinstance(s,dict)]
            self.controllers=states;self.controllers_t=now;self.reachable=bool(view.get('reachable'))
            if view.get('reachable') and isinstance(view.get('devices'),list) and not view.get('cached'):
                valid=[s for s in states if s.get('reachable')]
                fresh=max(valid,key=lambda s:s.get('observed') or 0,default={})
                self.read=dict(devices=[dict(d) for d in view['devices'] if isinstance(d,dict) and d.get('address')],battery=view.get('battery'),
                               noise=view.get('noise'),product=fresh.get('product') or 'Bose 700',via=fresh.get('controller'),t=now)
            self.touch()
    def set_link(self,value):
        if value is None:return
        value=bool(value)
        with self.cond:
            changed=value!=self.own_link
            if changed:self.own_link=value;self.link_t=_mono()
            self.touch()
        if changed:
            for listener in list(self.listeners):
                try:listener('link',value)
                except Exception:pass
    def set_audio(self,sink,default):
        with self.cond:
            value=dict(sink=sink or None,default=bool(sink) and bool(default))
            if value!=self.audio:self.audio=value
            self.touch()
    # ---- operation ----
    def begin(self,op):
        with self.cond:op.hub=self;self.operation=op;self.touch()
        return op
    def clear(self):
        with self.cond:self.operation=None;self.touch()
    def running(self):
        op=self.operation;return bool(op and op.running)
    # ---- model ----
    def roles(self):return {k:str(v).upper() for k,v in (self.config.get('roles') or {}).items()}
    def _expire(self):
        op=self.operation
        if op and (op.finished and _mono()-op.finished_at>DONE_LINGER or op.phase=='choose' and _mono()-op.t0>op.deadline):self.operation=None
    def device_state(self,address,read_connected,now):
        """Spec §1 rules. Deviation: an operation's mark comes first, so a device being connected shows `connecting`
        although its OS still reports no link (the spec example shows exactly that)."""
        roles=self.roles();own=roles.get(self.config['id']);op=self.operation
        if op and op.running and address in op.marks:return op.marks[address]
        if address==own and self.own_link is False:return 'disconnected'
        read_t=self.read['t'] if self.read else None
        for c in self.controllers:
            if c.get('link') is False and roles.get(c.get('controller'))==address and (read_t is None or self.controllers_t>=read_t):return 'disconnected'
        fresh=read_t is not None and now-read_t<=READ_FRESH
        if address==own and self.own_link and (not fresh or not read_connected and self.link_t is not None and self.link_t>=read_t):return 'connected'
        if fresh:return 'connected' if read_connected else 'disconnected'
        return 'unknown'
    def snapshot(self):
        with self.cond:
            self._expire();now=_mono();roles=self.roles();by_address={v:k for k,v in roles.items()}
            read=self.read or dict(devices=[],t=None);age=None if read.get('t') is None else round(now-read['t'],1)
            known=[dict(d) for d in read['devices']]
            for role,address in roles.items():
                if role in LABELS and not any(d['address'].upper()==address for d in known):known.append(dict(address=address,name=None,connected=False,missing=True))
            entries=[]
            for d in known:
                address=d['address'].upper();role=by_address.get(address)
                state=self.device_state(address,bool(d.get('connected')),now)
                e=dict(address=address,role=role,label=LABELS.get(role) or d.get('name') or 'Device',name=d.get('name'),state=state)
                if state=='unknown':e['age']=age
                entries.append((e,bool(d.get('connected'))))
            held=[e for e,c in entries if e['state'] in ('connected','releasing') or e['state']=='unknown' and c]
            held+=[e for e,_ in entries if e['state']=='connecting']
            slots=held[:2];others=[e for e,_ in entries if e not in slots]
            read_reachable=self.reachable and age is not None and age<=READ_FRESH
            # An open slot is `free` only on a fresh read; with no read (or a stale one) nobody knows what holds it.
            slots+=[dict(state='free') if read_reachable or age is not None and age<=READ_FRESH else dict(state='unknown',age=age)]*(2-len(slots))
            ids=[self.config['id']]+[p['id'] for p in self.config.get('peers',[])]
            seen={c.get('controller'):c for c in self.controllers}
            controllers=[]
            for ident in ids+[i for i in seen if i not in ids]:
                c=seen.get(ident)
                if c and c.get('reachable'):controllers.append(dict(id=ident,state='here' if ident==read.get('via') else 'available'))
                else:
                    reason='Not checked yet' if c is None else 'No answer yet' if c.get('checking') else MAC_TEXT.sub('device',str(c.get('error') or 'Not connected'))
                    controllers.append(dict(id=ident,state='offline',reason=reason))
            headset=dict(reachable=read_reachable,via=read.get('via') if read_reachable else None,read_age=age,battery=read.get('battery'),
                         noise=read.get('noise'),product=read.get('product') or 'Bose 700',controllers=controllers)
            op=self.operation
            return dict(seq=self.seq,now=round(time.time(),2),headset=headset,slots=slots,devices=others,
                        audio=dict(self.audio) if self.audio is not None else None,operation=op.to_json() if op else None)
    @staticmethod
    def material(snap):
        """The snapshot without fields that change by themselves (clock, ages)."""
        def strip(value):
            if isinstance(value,dict):return {k:strip(v) for k,v in value.items() if k not in ('now','seq','read_age','age','since')}
            if isinstance(value,list):return [strip(v) for v in value]
            return value
        return json.dumps(strip(snap),sort_keys=True,default=str)
    def touch(self):
        """Recompute the view; a material change bumps `seq` and wakes long-polls."""
        with self.cond:
            digest=self.material(self.snapshot())
            if digest!=self.digest:
                self.digest=digest;self.seq+=1;self.cond.notify_all()
    def state(self,after=None,wait=0.0):
        """GET /api/state: at once when seq > after (or no after), else wait up to `wait` s for the next change."""
        wait=max(0.0,min(POLL_MAX,float(wait or 0)))
        with self.cond:
            self.last_poll=_mono();self.touch()
            if after is not None:
                end=_real_monotonic()+wait
                while self.seq<=after:
                    left=end-_real_monotonic()
                    if left<=0:break
                    self.cond.wait(min(left,1.0));self.touch()  # 1 s ticks catch expiries (finished op, unknown ages)
            return self.snapshot()
    def wait_audio(self,timeout):
        """Block until the next change (a sink event) or `timeout`; replaces fixed polling while the PipeWire watcher runs."""
        if self.idle_wait:return self.idle_wait(timeout)
        with self.cond:
            seq=self.seq;end=_real_monotonic()+timeout
            while self.seq==seq and end>_real_monotonic():self.cond.wait(end-_real_monotonic())
    def clients_active(self):return self.last_poll is not None and _mono()-self.last_poll<=CLIENT_ACTIVE

# ---- Watchers (spec §4). Each runs one child process; it is restarted when it exits. ----
class LineWatcher:
    """Run the first available command of `commands`, feed each output line to on_line; restart after exit.
    `popen` and `which` are injectable for tests. Only this watcher's own child is ever terminated."""
    def __init__(self,commands,on_line,on_start=None,popen=subprocess.Popen,which=shutil.which,backoff=2.0,name='watcher'):
        self.commands=commands;self.on_line=on_line;self.on_start=on_start;self.popen=popen;self.which=which
        self.backoff=backoff;self.name=name;self.stopping=threading.Event();self.proc=None;self.starts=0;self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.run,name=self.name,daemon=True);self.thread.start();return self
    def command(self):return next((c for c in self.commands if self.which(c[0])),None)
    def run(self):
        while not self.stopping.is_set():
            argv=self.command()
            if not argv:self.stopping.wait(30);continue
            try:self.proc=self.popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
            except OSError:self.stopping.wait(self.backoff);continue
            self.starts+=1
            try:
                if self.on_start:self.on_start()
                for line in self.proc.stdout:
                    if self.stopping.is_set():break
                    try:self.on_line(line)
                    except Exception:pass
            finally:
                try:self.proc.terminate()
                except Exception:pass
                try:self.proc.wait(2)
                except Exception:pass
            self.stopping.wait(self.backoff)
    def stop(self):
        self.stopping.set()
        if self.proc:
            try:self.proc.terminate()
            except Exception:pass

class BluezWatcher(LineWatcher):
    """Device1.Connected of the headset from D-Bus PropertiesChanged. `gdbus monitor` needs no privileges (a plain match
    on org.bluez); dbus-monitor/busctl monitor are fallbacks. After each (re)start the link is read once, since events
    may have been missed. A Connected change that cannot be parsed triggers a fresh read."""
    GDBUS=re.compile(r"'Connected':\s*<(true|false)>")
    BOOL=re.compile(r'(?i)\bboolean\s+(true|false)\b')
    def __init__(self,hub,audio,path,**kw):
        self.hub=hub;self.audio=audio;self.pending=False;self.iface=None
        match=f"type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',path='{path}'"
        commands=[['gdbus','monitor','--system','--dest','org.bluez','--object-path',path],['dbus-monitor','--system',match],['busctl','--system','monitor','--match',match]]
        super().__init__(commands,self.line,self.resync,name='bose-bluez-watch',**kw)
    def resync(self):
        self.hub.link_watched=True;self.hub.set_link(self.audio.linked())
    def line(self,line):
        if 'PropertiesChanged' in line and 'org.bluez.Device1' not in line:self.iface=None
        found=re.search(r'"(org\.bluez\.[A-Za-z0-9]+)"',line)
        if found:self.iface=found.group(1)
        if 'org.bluez.Device1' in line:self.iface='org.bluez.Device1'
        value=self.GDBUS.search(line)
        if value:
            if 'org.bluez.Device1' in line:self.hub.set_link(value.group(1)=='true')
            elif 'org.bluez.' not in line:self.hub.set_link(self.audio.linked())
            return
        if '"Connected"' in line:self.pending=True
        if self.pending:
            value=self.BOOL.search(line)
            if value:
                self.pending=False
                if self.iface in (None,'org.bluez.Device1'):self.hub.set_link(value.group(1).lower()=='true')
                return
            if 'Connected' not in line and re.search(r'(?i)\bstring\b',line):self.pending=False;self.hub.set_link(self.audio.linked())

class PactlWatcher(LineWatcher):
    """`pactl subscribe`: on sink/server/card events re-read the headset sink and the default sink (coalesced)."""
    def __init__(self,hub,audio,**kw):
        self.hub=hub;self.audio=audio;self.kick=threading.Event()
        super().__init__([['pactl','subscribe']],self.line,self.started,name='bose-pactl-watch',**kw)
        self.refresher=None
    def started(self):
        self.hub.audio_watched=True
        if not self.refresher:self.refresher=threading.Thread(target=self.refresh_loop,name='bose-pactl-refresh',daemon=True);self.refresher.start()
        self.kick.set()
    def line(self,line):
        if re.search(r"on (sink|server|card)\b",line):self.kick.set()
    def refresh(self):
        sink=self.audio.sink();default=self.audio.default() if sink else None
        self.hub.set_audio(sink,bool(sink) and default==sink)
    def refresh_loop(self):
        while not self.stopping.is_set():
            if not self.kick.wait(1.0):continue
            self.kick.clear();self.stopping.wait(.05)  # coalesce a burst of events
            try:self.refresh()
            except Exception:pass

class ReadScheduler:
    """Headset reads (spec §4): on start, after every operation and on a link change (kick), every READ_ACTIVE s while a
    client long-polled in the last CLIENT_ACTIVE s, READ_IDLE s otherwise. Skips while an operation runs its own reads."""
    def __init__(self,hub,read):
        self.hub=hub;self.read=read;self.wake=threading.Event();self.stopping=threading.Event();self.thread=None
        hub.listeners.append(lambda kind,value:self.kick())
    def kick(self):self.wake.set()
    def start(self):
        self.thread=threading.Thread(target=self.run,name='bose-reads',daemon=True);self.thread.start();return self
    def interval(self):return READ_ACTIVE if self.hub.clients_active() else READ_IDLE
    def run(self):
        last=None;kicked=True
        while not self.stopping.is_set():
            due=kicked or last is None or _real_monotonic()-last>=self.interval()
            if due and not self.hub.running():
                try:self.read()
                except Exception:pass
                last=_real_monotonic()
            # Short waits: a client that starts long-polling during an idle wait gets the faster cadence at once.
            kicked=self.wake.wait(5.0);self.wake.clear()
            try:self.hub.touch()  # ages crossing READ_FRESH become `unknown` without another event
            except Exception:pass
    def stop(self):self.stopping.set();self.wake.set()
