"""The PC connection state machine (docs/state-machine.md) driven through a simulated headset/BlueZ/PipeWire world."""
import io, json, re, sys, threading, time, unittest
from pathlib import Path
from urllib.request import Request, urlopen
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import controller, statemachine
from statemachine import Hub, Operation, BluezWatcher, PactlWatcher, ReadScheduler, STEPS
from fakeworld import World, PC, PHONE, MAC, TV, SINK, ROLES

CONTRACT=json.loads((Path(__file__).with_name('switch-contract.json')).read_text())
MAC_RE=re.compile(r'(?i)([0-9a-f]{2}:){5}[0-9a-f]{2}')
REAL_SLEEP=time.sleep  # the fake world patches time.sleep

def names(state):return [s['name'] for s in state['operation']['steps']]
def slot_states(state):return {s.get('role') or s['state']:s['state'] for s in state['slots']}

class Http:
    """The real HTTP server on a random loopback port."""
    def __init__(self,ctl,mesh=False):
        self.server=controller.Server(('127.0.0.1',0),ctl,mesh);self.port=self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever,kwargs=dict(poll_interval=.05),daemon=True).start()
    def call(self,path,body=None):
        data=None if body is None else json.dumps(body).encode()
        req=Request(f'http://127.0.0.1:{self.port}{path}',data=data,method='POST' if body is not None else 'GET',headers={'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=30) as r:return r.status,json.loads(r.read())
        except Exception as e:
            if hasattr(e,'code'):
                with e:return e.code,json.loads(e.read())
            raise
    def close(self):self.server.shutdown();self.server.server_close()

class OperationTests(unittest.TestCase):
    def setUp(self):self.logs=self.assertLogs('bose.timing',level='INFO');self.cm=self.logs.__enter__()
    def tearDown(self):self.logs.__exit__(None,None,None)
    def lines(self,prefix):return [l.split(':',2)[2] for l in self.cm.output if l.split(':',2)[2].startswith(prefix)]
    def check_logs(self,n=1):
        # The peers run in this process too, so their relayed bose.switch lines (via=local) are here as well.
        switch=self.lines('bose.switch ');timing=self.lines('bose.timing ')
        self.assertEqual(len(timing),n,self.cm.output);self.assertGreaterEqual(len(switch),n)
        self.assertTrue(all(re.search(r' id=[A-Za-z0-9_-]+ ',t) and ' id=- ' not in t for t in timing),timing)
        self.assertIsNone(MAC_RE.search(' '.join(self.cm.output)))
        return switch,timing
    def test_mac_and_phone_to_pc_releases_the_mac_pages_and_starts_audio(self):
        w=World([PHONE,MAC])
        with w.running():
            reply=w.pc.switch_start({'source':'desk','request_id':'mac2pc'});self.assertTrue(reply['accepted'])
            self.assertEqual(reply['operation']['id'],'mac2pc');state=w.wait_done()
        op=state['operation'];self.assertEqual(op['phase'],'done',op)
        self.assertEqual(names(state),['reading','releasing','connecting','audio'])
        self.assertEqual([s['label'] for s in op['steps']],['Checking the headphones','Releasing the Mac','Connecting this PC','Starting audio'])
        self.assertTrue(all(s['state']=='done' and isinstance(s['seconds'],float) for s in op['steps']))
        self.assertEqual(op['result']['text'],controller.MESSAGES['ok']);self.assertLessEqual(op['result']['seconds'],5.0)
        self.assertEqual(sorted(w.held()),sorted([PHONE,PC]));self.assertEqual(w.audio.current,SINK);self.assertEqual(w.audio.pages,1)
        self.assertEqual(w.connects,0,'the PC paged itself; no BMAP connect');self.assertIn(('disconnect',MAC,'phone'),w.calls)
        self.assertEqual(slot_states(state),{'phone':'connected','pc':'connected'});self.assertEqual(state['devices'][0]['role'],'mac')
        self.assertEqual(state['audio'],{'sink':SINK,'default':True})
        switch,timing=self.check_logs()
        self.assertIn('bose.switch source=desk id=mac2pc target=PC replace=Mac outcome=ok via=peer:phone',' '.join(switch))
        self.assertRegex(timing[0],r'^bose\.timing id=mac2pc reading=\d+\.\d\ds releasing=\d+\.\d\ds connecting=\d+\.\d\ds audio=\d+\.\d\ds total=\d+\.\d\ds$')
    def test_pc_page_fails_then_bmap_connect_through_the_phone(self):
        w=World([PHONE],page_ok=False)
        with w.running():w.pc.switch_start({'source':'omarchy'});state=w.wait_done()
        self.assertEqual(state['operation']['phase'],'done');self.assertEqual(names(state),['reading','connecting','audio'])
        self.assertEqual((w.audio.pages,w.connects),(1,1));self.assertIn(('connect',PC,'phone'),w.calls);self.assertEqual(w.audio.current,SINK)
        self.check_logs()
    def test_release_refused_without_a_controller_that_keeps_access(self):
        # The phone app is not running: only the Mac reads, and it cannot drop itself.
        w=World([PHONE,MAC],apps=('mac',))
        with w.running():w.pc.switch_start({'source':'desk'});state=w.wait_done()
        op=state['operation'];self.assertEqual(op['phase'],'failed')
        self.assertEqual((op['result']['step'],op['result']['error_key']),('releasing','keep_one'))
        self.assertEqual(op['result']['text'],STEPS['release_failed'].format(label='Mac'))
        self.assertEqual([s['state'] for s in op['steps']],['done','failed']);self.assertEqual((w.connects,w.audio.pages),(0,0))
        self.check_logs()
    def test_release_not_confirmed_stops_before_connecting(self):
        w=World([PHONE,MAC],refuse_disconnect=True)
        with w.running():w.pc.switch_start({'source':'desk'});state=w.wait_done()
        r=state['operation']['result'];self.assertEqual((r['step'],r['error_key']),('releasing','unverified'))
        self.assertEqual(r['text'],'The Mac didn’t let go of the headphones');self.assertEqual((w.connects,w.audio.pages),(0,0))
        self.assertEqual([c[0] for c in w.calls],['disconnect'],'one disconnect, never resent')
    def test_choose_then_replace_moves_the_headset_to_the_phone(self):
        w=World([PC,MAC])
        with w.running():
            w.pc.switch_start({'source':'web','target':'phone'});state=w.wait_done()
            op=state['operation'];self.assertEqual(op['phase'],'choose');self.assertIsNone(op['result'])
            self.assertEqual(sorted(c['label'] for c in op['choices']),['Mac','PC']);self.assertEqual(w.connects,0)
            self.assertEqual(names(state),['reading','choose'])
            w.pc.switch_start({'source':'web','target':'phone','replace':MAC});state=w.wait_done()
        op=state['operation'];self.assertEqual(op['phase'],'done',op);self.assertEqual(names(state),['reading','releasing','connecting'])
        self.assertEqual([s['label'] for s in op['steps']][1:],['Releasing the Mac','Connecting the Phone'])
        self.assertEqual(sorted(w.held()),sorted([PC,PHONE]));self.assertEqual(op['target'],'phone')
        self.check_logs(2)
    def test_choose_is_cancelled(self):
        w=World([PC,MAC])
        with w.running():
            self.assertFalse(w.pc.switch_cancel()['ok'])
            w.pc.switch_start({'source':'web','target':'phone'});state=w.wait_done();self.assertEqual(state['operation']['phase'],'choose')
            reply=w.pc.switch_cancel();self.assertTrue(reply['ok'])
            after=w.hub.state();self.assertIsNone(after['operation']);self.assertGreater(after['seq'],state['seq'])
        self.assertEqual(sorted(w.held()),sorted([PC,MAC]))
    def test_phone_target_with_pc_and_mac_never_guesses(self):
        w=World([PC,MAC])
        with w.running():w.pc.switch_start({'source':'desk','target':'phone'});state=w.wait_done()
        self.assertEqual(state['operation']['phase'],'choose');self.assertEqual(w.calls,[])
    def test_mac_target_releases_this_pc_through_its_own_link(self):
        w=World([PHONE,PC],apps=('phone',))
        with w.running():w.pc.switch_start({'source':'desk','target':'mac'});state=w.wait_done()
        self.assertEqual(state['operation']['phase'],'done',state['operation']);self.assertEqual(sorted(w.held()),sorted([PHONE,MAC]))
        self.assertEqual(names(state),['reading','releasing','connecting']);self.assertIn(('connect',MAC,'phone'),w.calls)
    def test_already_on_pc_is_the_fast_path(self):
        w=World([PC,PHONE]);w.audio.current=SINK;w.emit()
        with w.running():
            t0=w.clock.now;reply=w.pc.switch_start({'source':'desk'});state=w.wait_done()
        op=state['operation'];self.assertEqual(op['phase'],'done');self.assertEqual(names(state),['reading','audio'])
        self.assertLessEqual(w.clock.now-t0,.5);self.assertLessEqual(op['result']['seconds'],.5);self.assertEqual((w.reads,w.connects,w.audio.pages),(0,0,0))
    def test_idle_transport_plays_a_chime_and_then_counts_as_flowing(self):
        w=World([PHONE,MAC],flows='chime')
        with w.running():w.pc.switch_start({'source':'desk'});state=w.wait_done()
        self.assertEqual(state['operation']['phase'],'done',state['operation']);self.assertEqual(w.audio.chimes,1)
        self.assertEqual(state['operation']['result']['text'],controller.MESSAGES['ok'])
    def test_something_already_playing_needs_no_chime(self):
        w=World([PC,PHONE]);w.audio.current=SINK;w.emit()
        with w.running():w.pc.switch_start({'source':'desk'});state=w.wait_done()
        self.assertEqual(state['operation']['phase'],'done');self.assertEqual(getattr(w.audio,'chimes',0),0)
    def test_connected_but_silent_fails_with_no_audio(self):
        # 2026-11-10 17:3x: linked, A2DP sink default, nothing reaching the headphones. Never report "Playing".
        for start in ([PHONE,MAC],[PC,PHONE]):
            with self.subTest(start=start):
                w=World(start,flows=False)
                if PC in start:w.audio.current=SINK;w.emit()
                with w.running():t0=w.clock.now;w.pc.switch_start({'source':'desk'});state=w.wait_done()
                op=state['operation'];self.assertEqual(op['phase'],'failed',op)
                self.assertEqual(op['result']['error_key'],'no_audio');self.assertEqual(op['result']['step'],'audio')
                self.assertEqual(op['result']['text'],'Connected, but no sound from the headphones')
                self.assertEqual(w.audio.chimes,1);self.assertLessEqual(w.clock.now-t0,10)
    def test_concurrent_tap_is_rejected_with_the_running_operation(self):
        w=World([PHONE]);w.audio.gate=threading.Event()
        with w.running():
            first=w.pc.switch_start({'source':'desk','request_id':'first'})
            for _ in range(200):
                if (w.hub.operation.phase=='connecting'):break
                REAL_SLEEP(.01)
            second=w.pc.switch_start({'source':'web','request_id':'second'})
            self.assertFalse(second['accepted']);self.assertEqual(second['operation']['id'],'first');self.assertEqual(second['operation']['phase'],'connecting')
            st=w.hub.state();self.assertEqual(slot_states(st)['pc'],'connecting')
            w.audio.gate.set();state=w.wait_done()
        self.assertTrue(first['accepted']);self.assertEqual(state['operation']['id'],'first');self.assertEqual(state['operation']['phase'],'done')
        self.assertIn('outcome=rejected',' '.join(self.lines('bose.switch')))
    def test_deadline_ends_a_hung_connect(self):
        w=World([PHONE],page_ok=False,script=['hang'])
        with w.running():t0=w.clock.now;w.pc.switch_start({'source':'web'});state=w.wait_done()
        r=state['operation']['result'];self.assertEqual((state['operation']['phase'],r['error_key'],r['step']),('failed','timeout','connecting'))
        self.assertEqual(w.connects,1,'never resent');self.assertEqual(r['text'],controller.MESSAGES['errors']['timeout'])
        self.assertEqual(state['operation']['deadline'],150)
    def test_unconfirmed_connects_page_then_fail_within_the_deadline(self):
        w=World([PHONE],page_ok=False,script=['connect_unconfirmed','connect_unconfirmed'])
        with w.running():t0=w.clock.now;w.pc.switch_start({'source':'web'});state=w.wait_done();spent=w.clock.now-t0
        r=state['operation']['result'];self.assertEqual((r['error_key'],r['step']),('unverified','connecting'))
        self.assertEqual(w.connects,2);self.assertGreaterEqual(w.audio.pages,10);self.assertLessEqual(spent,controller.SWITCH_DEADLINE)
    def test_finished_operation_goes_idle_after_eight_seconds_or_next_tap(self):
        w=World([PC,PHONE]);w.audio.current=SINK;w.emit()
        with w.running():
            w.pc.switch_start({'source':'desk'});state=w.wait_done();self.assertIsNotNone(state['operation'])
            w.clock.sleep(statemachine.DONE_LINGER+.1);self.assertIsNone(w.hub.state()['operation'])
    def test_override_shows_its_steps_in_state(self):
        w=World([PC,PHONE,]);seen=[]
        orig=w.pc.override
        def spy(data,info=None,budget=None):
            seen.append(w.hub.state());return orig(data,info,budget)
        w.pc.override=spy
        with w.running():
            r=w.pc.override_request({'action':'disconnect','address':PHONE,'source':'web'})
            after=w.hub.state()['operation']
        self.assertTrue(r['ok']);during=seen[0]
        self.assertEqual((during['operation']['action'],during['operation']['phase']),('disconnect','releasing'))
        self.assertEqual(slot_states(during)['phone'],'releasing')
        self.assertEqual((after['phase'],after['result']['text']),('done','Phone disconnected'))
        self.check_logs()

class ApiTests(unittest.TestCase):
    def test_http_switch_accepts_at_once_and_state_follows_to_done(self):
        w=World([PHONE,MAC])
        with w.running(),self.assertLogs('bose.timing',level='INFO'):
            http=Http(w.pc)
            try:
                code,reply=http.call('/api/switch',{'source':'web','request_id':'h1'})
                self.assertEqual((code,reply['accepted'],reply['operation']['id']),(200,True,'h1'));seq=reply['seq']
                while True:
                    code,state=http.call(f'/api/state?after={seq}&wait=5');seq=state['seq']
                    if state['operation'] and state['operation']['phase'] in ('done','failed'):break
            finally:http.close()
        self.assertEqual(state['operation']['phase'],'done');self.assertEqual(len(state['slots']),2)
        for key in ('seq','now','headset','slots','devices','audio','operation'):self.assertIn(key,state)
        for key in ('reachable','via','read_age','battery','noise','product','controllers'):self.assertIn(key,state['headset'])
    def test_wait_1_keeps_the_old_blocking_replies(self):
        roles={'here':'pc','other1':'phone','other2':'mac'}
        for sc in CONTRACT['scenarios']:
            with self.subTest(sc['name']):
                start=[ROLES[roles[r]] for r in sc['start']]
                w=World(start,page_ok=False,script=[s for s in sc['headset'] if s!='unreachable'],down='unreachable' in sc['headset'],watch=False)
                body={'source':'web'}
                if sc.get('replace'):body['replace']=ROLES[roles[sc['replace']]]
                with w.running(),self.assertLogs('bose.timing',level='INFO'):
                    http=Http(w.pc)
                    try:code,reply=http.call('/api/switch?wait=1',body)
                    finally:http.close()
                exp=sc['expect']
                if exp['outcome']=='ok':self.assertEqual((reply['ok'],reply['verified'],reply['message']),(True,True,controller.MESSAGES['ok']));self.assertIn('devices',reply['state'])
                elif exp['outcome']=='busy':self.assertEqual((reply['busy'],reply['error_key'],len(reply['slots'])),(True,'busy',2))
                else:self.assertEqual((reply['ok'],reply['error_key']),(False,exp['error_key']))
                if 'connected' in exp:self.assertEqual(sorted(w.held()),sorted(ROLES[roles[r]] for r in exp['connected']))
                if 'connect_commands' in exp:self.assertEqual(w.connects,exp['connect_commands'])
    def test_wait_1_from_the_desk_keeps_the_phone(self):
        sc=next(s for s in CONTRACT['scenarios'] if s['name']=='both_busy')
        w=World([PHONE,MAC],page_ok=False,watch=False)
        with w.running(),self.assertLogs('bose.timing',level='INFO'):reply=w.pc.switch_request({'source':'desk'})
        self.assertEqual((reply['ok'],reply['message']),(True,CONTRACT['messages'][sc['expect_desk']['text'].split('.')[1]]))
        self.assertEqual(sorted(w.held()),sorted([PHONE,PC]))
    def test_long_poll_wakes_on_change_and_times_out(self):
        w=World([PHONE],watch=False);http=Http(w.pc)
        try:
            _,first=http.call('/api/state');seq=first['seq'];self.assertIsNone(first['operation'])
            got={}
            t=threading.Thread(target=lambda:got.update(r=http.call(f'/api/state?after={seq}&wait=10')));start=time.perf_counter();t.start()
            time.sleep(.2);w.hub.set_link(True);t.join(5);woke=time.perf_counter()-start
            self.assertGreater(got['r'][1]['seq'],seq);self.assertLess(woke,1.5)
            seq=got['r'][1]['seq'];start=time.perf_counter();_,same=http.call(f'/api/state?after={seq}&wait=0.4')
            self.assertGreaterEqual(time.perf_counter()-start,.38);self.assertEqual(same['seq'],seq)
            self.assertEqual(http.call('/api/state?wait=abc')[0],400)
            _,quick=http.call('/api/state?after=0&wait=25');self.assertEqual(quick['seq'],seq)  # seq > after: at once
        finally:http.close();w.pc.status_pool.shutdown(wait=True)
    def test_mesh_serves_state_to_authenticated_peers_only(self):
        w=World([PHONE],watch=False)
        class Fake:  # a Handler driven without sockets: mesh checks need a tailnet source address
            pass
        handler=controller.Handler.__new__(controller.Handler)
        handler.server=type('S',(),{'mesh':True,'controller':w.pc,'server_address':('100.64.0.1',8848)})()
        handler.client_address=('100.64.0.2',5000);handler.path='/api/state';sent=[]
        handler.send=lambda status,data,kind='application/json':sent.append((status,data))
        handler.headers={'Authorization':'Bearer t'};handler.do_GET()
        handler.headers={'Authorization':'Bearer wrong'};handler.do_GET()
        self.assertEqual(sent[0][0],200);self.assertIn('slots',sent[0][1]);self.assertEqual(sent[1][0],403)
        w.pc.status_pool.shutdown(wait=True)
    def test_cancel_accepts_an_empty_body(self):
        w=World([PHONE],watch=False);http=Http(w.pc)
        try:
            req=Request(f'http://127.0.0.1:{http.port}/api/switch/cancel',data=b'',method='POST')
            with urlopen(req,timeout=5) as r:self.assertEqual(json.loads(r.read())['ok'],False)
        finally:http.close();w.pc.status_pool.shutdown(wait=True)
    def test_invalid_target_is_refused_and_logged_once(self):
        w=World([PHONE],watch=False)
        for body in ({'source':'web','target':'tv'},{'source':'web','target':5}):
            with self.subTest(body),self.assertLogs('bose.timing',level='INFO') as logs:
                with self.assertRaises(ValueError):w.pc.switch_start(body)
            self.assertEqual(len(logs.output),1);self.assertIn('outcome=error:invalid',logs.output[0])
        w.pc.status_pool.shutdown(wait=True)

class ModelTests(unittest.TestCase):
    def hub(self):return Hub(dict(id='pc',roles=dict(ROLES),peers=[dict(id='phone'),dict(id='mac')]))
    def view(self,held,via='phone',link_false=()):
        devices=[dict(address=a,name=a,connected=a in held,current=False) for a in (PHONE,PC,MAC)]
        controllers=[dict(controller=via,reachable=True,observed=1,devices=devices)]+[dict(controller=c,reachable=False,link=False,error='Headset is not connected to this Mac') for c in link_false]
        return dict(reachable=True,devices=devices,controllers=controllers,battery=40,noise=None)
    def state(self,hub,address):
        s=hub.snapshot();return next(e['state'] for e in s['slots']+s['devices'] if e.get('address')==address)
    def test_stale_read_showing_the_pc_loses_to_bluez_no_link(self):
        h=self.hub();h.ingest(self.view([PC,PHONE],via='pc'));self.assertEqual(self.state(h,PC),'connected')
        h.set_link(False);self.assertEqual(self.state(h,PC),'disconnected')
        s=h.snapshot();self.assertEqual([x['state'] for x in s['slots']],['connected','free'])
    def test_bluez_link_newer_than_a_read_without_the_pc_wins(self):
        clock=[100.0]
        from unittest.mock import patch
        with patch('statemachine.time.monotonic',lambda:clock[0]):
            h=self.hub();h.set_link(False);h.ingest(self.view([PHONE]));self.assertEqual(self.state(h,PC),'disconnected')
            clock[0]+=1;h.set_link(True);self.assertEqual(self.state(h,PC),'connected')
            clock[0]+=1;h.ingest(self.view([PHONE]));self.assertEqual(self.state(h,PC),'disconnected')  # a newer read decides again
    def test_peer_no_link_wins_over_the_read(self):
        h=self.hub();h.ingest(self.view([PHONE,MAC],link_false=('mac',)));self.assertEqual(self.state(h,MAC),'disconnected')
    def test_no_read_for_a_minute_is_unknown_with_its_age(self):
        clock=[100.0]
        from unittest.mock import patch
        with patch('statemachine.time.monotonic',lambda:clock[0]):
            h=self.hub();h.ingest(self.view([PHONE,MAC]));clock[0]+=61
            s=h.snapshot();phone=next(e for e in s['slots'] if e.get('address')==PHONE)
            self.assertEqual((phone['state'],phone['age']),('unknown',61.0));self.assertFalse(s['headset']['reachable'])
            before=h.seq;h.touch();self.assertGreater(h.seq,before,'crossing into unknown is a change')
    def test_unreachable_controllers_carry_reasons(self):
        h=self.hub();h.ingest(self.view([PHONE],link_false=('mac',)))
        c={x['id']:x for x in h.snapshot()['headset']['controllers']}
        self.assertEqual(c['phone']['state'],'here');self.assertEqual(c['mac'],dict(id='mac',state='offline',reason='Headset is not connected to this Mac'))
        self.assertEqual(c['pc']['state'],'offline')
    def test_seq_moves_only_on_material_change(self):
        h=self.hub();h.ingest(self.view([PHONE]));seq=h.seq;h.ingest(self.view([PHONE]));self.assertEqual(h.seq,seq)
        h.set_audio(SINK,False);self.assertEqual(h.seq,seq+1)
    def test_steps_match_the_contract(self):
        self.assertEqual(STEPS,CONTRACT['steps'])

class FakeProc:
    def __init__(self,lines):self.stdout=io.StringIO(''.join(l+'\n' for l in lines));self.terminated=False
    def terminate(self):self.terminated=True
    def wait(self,timeout=None):return 0

class WatcherTests(unittest.TestCase):
    def run_watcher(self,make,runs,until):
        procs=[FakeProc(lines) for lines in runs];argvs=[]
        def popen(argv,**kw):
            argvs.append(argv)
            if not procs:raise OSError('no more')
            return procs.pop(0)
        watcher=make(popen);watcher.start()
        try:
            end=time.perf_counter()+5
            while not until() and time.perf_counter()<end:time.sleep(.01)
        finally:watcher.stop()
        return watcher,argvs
    def test_bluez_watcher_parses_gdbus_and_dbus_monitor_and_restarts(self):
        hub=Hub(dict(id='pc',roles=dict(ROLES),peers=[]));values=[]
        hub.listeners.append(lambda kind,value:values.append(value))
        class A:linked=lambda self:True
        gdbus=["/org/bluez/hci0/dev_AA_AA_AA_AA_AA_AA: org.freedesktop.DBus.Properties.PropertiesChanged ('org.bluez.MediaControl1', {'Connected': <false>}, @as [])",
               "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_AA: org.freedesktop.DBus.Properties.PropertiesChanged ('org.bluez.Device1', {'Connected': <false>}, @as [])"]
        w,argvs=self.run_watcher(lambda popen:BluezWatcher(hub,A(),'/org/bluez/hci0/dev_AA_AA_AA_AA_AA_AA',popen=popen,which=lambda n:n=='gdbus',backoff=.01),[gdbus,[]],lambda:len(values)>=3)
        self.assertEqual(values[:3],[True,False,True]);self.assertTrue(hub.link_watched)  # resync, event, resync after the restart
        self.assertEqual(argvs[0][:3],['gdbus','monitor','--system']);self.assertGreaterEqual(w.starts,2)
        hub=Hub(dict(id='pc',roles=dict(ROLES),peers=[]));values=[];hub.listeners.append(lambda kind,value:values.append(value))
        monitor=['signal time=1.0 sender=:1.5 -> destination=(null destination) serial=9 path=/org/bluez/hci0/dev_AA_AA_AA_AA_AA_AA; interface=org.freedesktop.DBus.Properties; member=PropertiesChanged',
                 '   string "org.bluez.Device1"','   array [','      dict entry(','         string "Connected"','         variant             boolean false','      )','   ]']
        self.run_watcher(lambda popen:BluezWatcher(hub,A(),'/org/bluez/hci0/dev_AA',popen=popen,which=lambda n:n=='dbus-monitor',backoff=.01),[monitor],lambda:len(values)>=2)
        self.assertEqual(values[:2],[True,False])
    def test_pactl_watcher_updates_audio_on_sink_events(self):
        hub=Hub(dict(id='pc',roles=dict(ROLES),peers=[]))
        class A:
            def sink(self):return SINK
            def default(self):return SINK
        w,_=self.run_watcher(lambda popen:PactlWatcher(hub,A(),popen=popen,which=lambda n:True,backoff=5),[["Event 'change' on client #1","Event 'new' on sink #57"]],
                             lambda:hub.audio=={'sink':SINK,'default':True})
        self.assertEqual(hub.audio,{'sink':SINK,'default':True});self.assertTrue(hub.audio_watched)
    def test_read_scheduler_reads_on_start_and_on_a_link_change_but_not_during_an_operation(self):
        hub=Hub(dict(id='pc',roles=dict(ROLES),peers=[]));reads=[]
        s=ReadScheduler(hub,lambda:reads.append(1)).start()
        try:
            end=time.perf_counter()+3
            while not reads and time.perf_counter()<end:time.sleep(.01)
            self.assertEqual(len(reads),1);self.assertEqual(s.interval(),statemachine.READ_IDLE)
            hub.state();self.assertEqual(s.interval(),statemachine.READ_ACTIVE)
            hub.begin(Operation('desk','pc')).step('reading');hub.set_link(True);time.sleep(.2);self.assertEqual(len(reads),1)
            hub.clear();hub.set_link(False)
            end=time.perf_counter()+3
            while len(reads)<2 and time.perf_counter()<end:time.sleep(.01)
            self.assertEqual(len(reads),2)
        finally:s.stop()

class SlotTests(unittest.TestCase):
    def test_open_slots_are_unknown_until_a_fresh_read(self):
        hub=Hub(dict(id='pc',roles=dict(ROLES),peers=[]))
        self.assertEqual([x['state'] for x in hub.snapshot()['slots']],['unknown','unknown'])

if __name__=='__main__':unittest.main()
