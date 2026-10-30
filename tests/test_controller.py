import unittest,re
import threading
import tempfile,json
from unittest.mock import patch
from contextlib import contextmanager
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from protocol import Client,ProtocolError,ActionUnconfirmed,parse_list,parse_info,mac_bytes,parse_noise
import controller
from controller import Controller

PC='AA:AA:AA:AA:AA:AA';PHONE='BB:BB:BB:BB:BB:BB';TV='CC:CC:CC:CC:CC:CC';MAC='DD:DD:DD:DD:DD:DD'
def device(a,connected,current=False):return dict(address=a,connected=connected,current=current,name=a)
def state(devices):return {'devices':devices,'battery':80}
class Fake:
 def __init__(self,devices,apply=True):self.devices=devices;self.calls=[];self.apply=apply
 def status(self,**kwargs):self.status_calls=getattr(self,'status_calls',[])+[kwargs];return state([dict(d) for d in self.devices])
 def action(self,action,a):
  self.calls.append((action,a))
  if self.apply:
   for d in self.devices:
    if d['address']==a:d['connected']=action=='connect'
@contextmanager
def fake_connect(fake):yield fake
class Socket:
 def __init__(self,parts):self.parts=iter(parts);self.sent=[]
 def sendall(self,data):self.sent.append(data)
 def recv(self,n):return next(self.parts,b'')
class Tests(unittest.TestCase):
 def ctl(self):return Controller(dict(id='pc',name='PC',headset=PC,roles={'pc':PC,'phone':PHONE},peers=[]))
 def run_action(self,fake,data):
  with patch('controller.connection',return_value=fake_connect(fake)),patch('controller.time.sleep'):return self.ctl().local_action(data)
 def test_overview_returns_fresh_status_without_waiting_for_slow_peer(self):
  c=self.ctl();c.config['peers']=[dict(id='phone',name='Phone',url='http://100.64.0.2:8848')]
  release=threading.Event();started=threading.Event()
  def slow(*args):
   started.set();release.wait(2);return dict(controller='phone',reachable=False)
  try:
   with patch.object(c,'local_status',return_value=dict(controller='pc',reachable=True,observed=1,devices=[device(PC,True,True)])),patch.object(c,'peer_call',side_effect=slow):
    view=c.overview();self.assertTrue(view['reachable']);self.assertEqual(view['devices'][0]['address'],PC)
    self.assertTrue(view['controllers'][1].get('checking'));self.assertFalse(release.is_set())
  finally:release.set();c.status_pool.shutdown(wait=True)
 def test_action_does_not_wait_for_unavailable_peer(self):
  c=self.ctl();c.config['peers']=[dict(id='phone',name='Phone',url='http://100.64.0.2:8848')]
  release=threading.Event()
  def slow(*args):
   release.wait(2);return dict(controller='phone',reachable=False)
  try:
   with patch.object(c,'local_status',return_value=dict(controller='pc',reachable=True,observed=1,devices=[device(PC,True,True),device(TV,True)])),patch.object(c,'peer_call',side_effect=slow),patch.object(c,'local_action',return_value={'ok':True}) as action:
    self.assertTrue(c.override(dict(action='disconnect',address=TV))['ok']);action.assert_called_once();self.assertFalse(release.is_set())
  finally:release.set();c.status_pool.shutdown(wait=True)
 def test_disconnect_current_waits_for_another_eligible_controller(self):
  c=self.ctl();c.config['peers']=[dict(id='phone',name='Phone',url='http://100.64.0.2:8848')]
  with patch.object(c,'local_status',return_value=dict(controller='pc',reachable=True,observed=1,devices=[device(PC,True,True)])),patch.object(c,'peer_call',return_value=dict(controller='phone',reachable=True,observed=2,devices=[device(PHONE,True,True),device(PC,True)])):
   view=c.overview(exclude_current=PC);self.assertTrue(any(s['controller']=='phone' and s['reachable'] for s in view['controllers']))
  c.status_pool.shutdown(wait=True)
 def test_prepare_rejects_other_controller_before_touching_adapter(self):
  with patch('controller.subprocess.run') as run:
   with self.assertRaisesRegex(ValueError,'Only this'):self.ctl().prepare_connect({'address':PHONE})
   run.assert_not_called()
 def test_snapshot_persists_without_token_and_is_marked_cached(self):
  c=self.ctl();c.config['token']='private-token'
  with tempfile.TemporaryDirectory() as folder:
   c.config_path=str(Path(folder)/'config.json')
   with patch.object(c,'local_status',return_value=dict(controller='pc',reachable=True,observed=123,devices=[device(PC,True,True)])):
    fresh=c.overview();cached=c.cached_overview()
   self.assertFalse(fresh['cached']);self.assertTrue(cached['cached'])
   self.assertEqual(cached['devices'],fresh['devices']);self.assertEqual(cached['observed'],123)
   path=Path(folder)/'snapshot.json';self.assertEqual(path.stat().st_mode & 0o777,0o600)
   self.assertNotIn('private-token',path.read_text())
  c.status_pool.shutdown(wait=True)
 def test_disconnected_linux_probe_does_not_start_radio_connection(self):
  c=self.ctl()
  with patch('controller.sys.platform','linux'),patch('controller.subprocess.run') as run,patch('controller.connection') as connect:
   run.return_value.stdout='b false';result=c.local_status();self.assertFalse(result['reachable']);connect.assert_not_called()
   self.assertIs(result['link'],False)
 def test_unreachable_overview_drops_unlinked_slot_and_marks_live_check(self):
  c=self.ctl();c.config['peers']=[dict(id='phone',name='Phone',url='http://100.64.0.2:8848')]
  with tempfile.TemporaryDirectory() as folder:
   c.config_path=str(Path(folder)/'config.json')
   (Path(folder)/'snapshot.json').write_text(json.dumps(dict(devices=[device(PC,True,True),device(PHONE,False)],observed=5,roles={})))
   with patch.object(c,'local_status',return_value=dict(controller='pc',reachable=False,link=False,error='Headset is not connected to this PC',devices=[])),patch.object(c,'peer_call',return_value=dict(controller='phone',reachable=False,error='Controller unavailable: ConnectionRefusedError')):
    view=c.overview()
  self.assertFalse(view['reachable']);self.assertTrue(view['cached']);self.assertIn('checked',view);self.assertEqual(view['observed'],5)
  self.assertEqual([(d['address'],d['connected'],d['current']) for d in view['devices']],[(PC,False,False),(PHONE,False,False)])
  c.status_pool.shutdown(wait=True)
 def test_disconnect_already_disconnected_is_verified_without_write(self):
  fake=Fake([device(PC,True,True),device(PHONE,False)])
  self.assertTrue(self.run_action(fake,dict(action='disconnect',address=PHONE))['verified']);self.assertEqual(fake.calls,[])
 def test_prepare_temporarily_enables_and_restores_visibility(self):
  c=self.ctl()
  class Timer:
   def __init__(self,interval,callback):self.callback=callback;self.interval=interval
   def start(self):pass
   def cancel(self):pass
  with patch('controller.sys.platform','linux'),patch('controller.subprocess.run') as run,patch('controller.threading.Timer',Timer):
   run.return_value.stdout='b false'
   self.assertTrue(c.prepare_connect({'address':PC})['ok']);timer=c.discovery_timer
   self.assertEqual(timer.interval,30);self.assertEqual(run.call_args.args[0][-1],'true')
   timer.callback();self.assertEqual(run.call_args.args[0][-1],'false');self.assertIsNone(c.discovery_restore)
 def test_disconnect_uses_short_ack_window(self):
  client=Client(None)
  with patch.object(client,'request',return_value=b'') as req:
   client.action('disconnect',PHONE);self.assertEqual(req.call_args.kwargs['timeout'],.25)
 def test_noise_parse_and_unknown_layout(self):
  self.assertEqual(parse_noise(bytes([11,3,1])),dict(level=7,enabled=True))
  for payload in (b'',bytes([10,3,1]),bytes([11,11,1]),bytes([11,3,2])):
   with self.assertRaises(ProtocolError):parse_noise(payload)
 def test_noise_set_uses_inverted_level_and_verifies(self):
  client=Client(None)
  with patch.object(client,'request',side_effect=[bytes([11,0,1]),bytes([11,3,1]),bytes([11,3,1])]) as req:
   self.assertEqual(client.set_noise(7,True),dict(level=7,enabled=True))
   self.assertEqual(req.call_args_list[1].args,(1,5,2,bytes([3,1])))
 def test_noise_enable_from_off_corrects_only_confirmed_default(self):
  client=Client(None)
  with patch.object(client,'request',side_effect=[bytes([11,3,0]),bytes([11,0,1]),bytes([11,0,1]),bytes([11,3,1]),bytes([11,3,1])]) as req:
   self.assertEqual(client.set_noise(7,True)['level'],7);self.assertEqual(req.call_count,5)
 def test_noise_timeout_does_not_resend(self):
  client=Client(None)
  with patch.object(client,'request',side_effect=[bytes([11,0,1]),ProtocolError('No acknowledgement'),ProtocolError('Read failed')]) as req:
   with self.assertRaises(ProtocolError):client.set_noise(7,True)
   self.assertEqual(req.call_count,3)
 def test_noise_missing_ack_is_verified_without_resend(self):
  client=Client(None)
  with patch.object(client,'request',side_effect=[bytes([11,0,1]),__import__('socket').timeout(),bytes([11,1,1])]) as req:
   self.assertEqual(client.set_noise(9,True)['level'],9)
   self.assertEqual(sum(call.args[2:3]==(2,) for call in req.call_args_list),1)
 def test_noise_rejects_invalid_values_before_io(self):
  client=Client(None)
  with patch.object(client,'request') as req:
   for level,enabled in [(11,True),(-1,True),(True,True),(5,1)]:
    with self.assertRaises(ValueError):client.set_noise(level,enabled)
   req.assert_not_called()
 def test_fragmentation_and_unrelated_notifications(self):
  sock=Socket([b'\x02\x02\x03\x01\x50\x00',b'\x03\x03',b'\x03\x40\x24\x01'])
  self.assertEqual(Client(sock).request(0,3),bytes.fromhex('402401'))
 def test_headset_error_is_not_success(self):
  with self.assertRaises(ProtocolError):Client(Socket([bytes.fromhex('04010f0105')])).request(4,1,5,b'',(7,))
 def test_unknown_layout_refuses_changes(self):
  with self.assertRaises(ProtocolError):parse_list(b'\x01\x02')
  with self.assertRaises(ProtocolError):parse_info(bytes.fromhex('aaaaaaaaaaaa040000')+b'name',mac_bytes(PC))
 def test_saturated_requires_explicit_replacement(self):
  f=Fake([device(PC,True,True),device(TV,True),device(PHONE,False)])
  with self.assertRaisesRegex(ValueError,'Both slots'):self.run_action(f,dict(action='connect',address=PHONE))
  self.assertEqual(f.calls,[])
 def test_replace_other_device_and_verify(self):
  f=Fake([device(PC,True,True),device(TV,True),device(PHONE,False)])
  r=self.run_action(f,dict(action='connect',address=PHONE,replace=TV))
  self.assertTrue(r['verified']);self.assertEqual(f.calls,[('disconnect',TV),('connect',PHONE)])
 def test_cannot_drop_last_anchor(self):
  f=Fake([device(PC,True,True),device(TV,True)])
  with self.assertRaisesRegex(ValueError,'Keep one'):self.run_action(f,dict(action='disconnect',address=PC))
  self.assertEqual(f.calls,[])
 def test_current_controller_must_relay_disconnect(self):
  f=Fake([device(PC,True,True),device(PHONE,True)])
  with self.assertRaisesRegex(ValueError,'providing access'):self.run_action(f,dict(action='disconnect',address=PC))
  self.assertEqual(f.calls,[])
 def test_failed_disconnect_never_connects_target(self):
  f=Fake([device(PC,True,True),device(TV,True),device(PHONE,False)],apply=False)
  with self.assertRaisesRegex(ProtocolError,'Disconnect was not verified'):self.run_action(f,dict(action='connect',address=PHONE,replace=TV))
  self.assertEqual(f.calls,[('disconnect',TV)])
 def test_unknown_target_not_sent(self):
  f=Fake([device(PC,True,True)])
  with self.assertRaisesRegex(ValueError,'remembered'):self.run_action(f,dict(action='connect',address=MAC))
  self.assertEqual(f.calls,[])
 def test_no_ack_is_verified_without_resending(self):
  class NoAck(Fake):
   def action(self,action,a):
    super().action(action,a)
    if action=='disconnect':raise ActionUnconfirmed('no ack')
  f=NoAck([device(PC,True,True),device(TV,True),device(PHONE,False)])
  self.assertTrue(self.run_action(f,dict(action='connect',address=PHONE,replace=TV))['verified'])
  self.assertEqual(f.calls,[('disconnect',TV),('connect',PHONE)])
 def test_explicit_rejection_stops_remaining_commands(self):
  class Rejected(Fake):
   def action(self,action,a):
    self.calls.append((action,a));raise ProtocolError('Headset rejected command')
  f=Rejected([device(PC,True,True),device(TV,True),device(PHONE,False)])
  with self.assertRaises(ProtocolError):self.run_action(f,dict(action='connect',address=PHONE,replace=TV))
  self.assertEqual(f.calls,[('disconnect',TV)])
 def test_no_retry_after_ambiguous_remote_action(self):
  c=self.ctl();c.config['peers']=[dict(id='phone',name='Phone',url='http://100.64.0.2:8848')]
  view=dict(roles={'pc':PC,'phone':PHONE},controllers=[dict(controller='phone',reachable=True,devices=[device(PC,True),device(PHONE,True,True)])])
  with patch.object(c,'overview',return_value=view),patch.object(c,'peer_call',return_value={'error':'timeout'}) as call:
   self.assertEqual(c.override(dict(action='disconnect',address=PC)),{'error':'timeout'});self.assertEqual(call.call_count,1)
 def test_stale_state_not_used_to_offer_actions(self):
  c=self.ctl()
  with patch.object(c,'local_status',return_value=dict(controller='pc',reachable=False,devices=[device(PC,True)],stale=True)):
   self.assertFalse(c.overview()['reachable']);self.assertEqual(c.overview()['devices'],[])

class Clock:
 def __init__(self):self.now=1000.;self.slept=0.
 def monotonic(self):return self.now
 def sleep(self,s):self.now+=s;self.slept+=s
MAC_RE=re.compile(r'(?i)([0-9a-f]{2}:){5}[0-9a-f]{2}')
class SpeedTests(unittest.TestCase):
 def ctl(self,peers=False):
  c=Controller(dict(id='pc',name='PC',headset=PC,roles={'pc':PC,'phone':PHONE},peers=[dict(id='phone',name='Phone',url='http://100.64.0.2:8848')] if peers else []))
  return c
 def act(self,c,fake,data,clock=None):
  clock=clock or Clock()
  with patch('controller.connection',return_value=fake_connect(fake)),patch('controller.time.sleep',clock.sleep),patch('controller.time.monotonic',clock.monotonic):return c.local_action(data)
 def test_connect_returns_full_overview_state_and_updates_snapshot(self):
  c=self.ctl()
  with tempfile.TemporaryDirectory() as folder:
   c.config_path=str(Path(folder)/'config.json')
   f=Fake([device(PC,True,True),device(TV,False)])
   r=self.act(c,f,dict(action='connect',address=TV));s=r['state']
   for key in ('here','reachable','cached','observed','battery','noise','roles','devices','controllers'):self.assertIn(key,s)
   self.assertFalse(s['cached']);self.assertTrue(next(d for d in s['devices'] if d['address']==TV)['connected'])
   self.assertEqual(s['here'],'pc');self.assertEqual(c.cached_overview()['devices'],s['devices'])
 def test_already_connected_and_noise_return_full_state(self):
  c=self.ctl();f=Fake([device(PC,True,True),device(TV,True)])
  self.assertIn('controllers',self.act(c,f,dict(action='connect',address=TV))['state'])
  class NoiseClient(Fake):
   def request(self,*a,**k):return b'\x40\x24\x01'
   def set_noise(self,level,enabled):return dict(level=level,enabled=enabled)
  n=NoiseClient([device(PC,True,True)]);c.cache=state(n.devices)
  r=self.act(c,n,dict(action='noise',level=4,enabled=True))
  self.assertEqual(r['state']['noise'],dict(level=4,enabled=True));self.assertEqual(r['state']['devices'][0]['address'],PC)
  self.assertTrue(c.ident_ok)
 def test_noise_skips_prelude_when_local_and_caches_identity(self):
  c=self.ctl();c.cache=state([device(PC,True,True)])
  class NoiseClient(Fake):
   idents=0
   def request(self,*a,**k):NoiseClient.idents+=1;return b'\x40\x24\x01'
   def set_noise(self,level,enabled):return dict(level=level,enabled=enabled)
  n=NoiseClient([device(PC,True,True)])
  with patch('controller.connection',return_value=fake_connect(n)),patch.object(c,'overview') as ov:
   c.override(dict(action='noise',level=3,enabled=True))
   with patch('controller.connection',return_value=fake_connect(n)):c.override(dict(action='noise',level=5,enabled=True))
   ov.assert_not_called()
  self.assertEqual(NoiseClient.idents,1)
 def test_noise_falls_back_when_headset_unreachable_before_any_command(self):
  c=self.ctl(True);c.cache=state([device(PC,True,True)])
  @contextmanager
  def broken(*a):raise OSError('no route');yield
  view=dict(roles={},controllers=[dict(controller='phone',reachable=True,devices=[device(PHONE,True,True)])],devices=[],battery=1)
  with patch('controller.connection',broken),patch.object(c,'overview',return_value=view) as ov,patch.object(c,'peer_call',return_value=dict(ok=True,verified=True,noise=dict(level=2,enabled=True))) as call:
   r=c.override(dict(action='noise',level=2,enabled=True))
  ov.assert_called_once();call.assert_called_once();self.assertFalse(c.ident_ok)
  self.assertEqual(r['state']['noise'],dict(level=2,enabled=True))
 def test_noise_reply_uses_fresh_device_read_and_snapshot(self):
  c=self.ctl();c.cache=state([device(PC,True,True),device(TV,True)])
  class NoiseClient(Fake):
   def request(self,*a,**k):return b'\x40\x24\x01'
   def set_noise(self,level,enabled):return dict(level=level,enabled=enabled)
  n=NoiseClient([device(PC,True,True),device(TV,False)])
  with tempfile.TemporaryDirectory() as folder:
   c.config_path=str(Path(folder)/'config.json')
   r=self.act(c,n,dict(action='noise',level=4,enabled=True))
   self.assertEqual(n.status_calls[-1],dict(full=False,check_ident=False))
   self.assertFalse(next(d for d in r['state']['devices'] if d['address']==TV)['connected'])
   self.assertEqual(c.cached_overview()['devices'],r['state']['devices'])
 def test_noise_without_fresh_read_returns_no_stale_state_or_snapshot(self):
  c=self.ctl();c.cache=state([device(PC,True,True),device(TV,True)])
  class NoiseClient(Fake):
   def request(self,*a,**k):return b'\x40\x24\x01'
   def set_noise(self,level,enabled):return dict(level=level,enabled=enabled)
   def status(self,**kwargs):raise ProtocolError('read failed')
  n=NoiseClient([device(PC,True,True)])
  with tempfile.TemporaryDirectory() as folder:
   c.config_path=str(Path(folder)/'config.json')
   r=self.act(c,n,dict(action='noise',level=4,enabled=True))
   self.assertNotIn('state',r);self.assertEqual(r['noise'],dict(level=4,enabled=True))
   self.assertFalse((Path(folder)/'snapshot.json').exists())
 def test_fresh_overview_forced_after_headset_unreachable(self):
  c=self.ctl(True);c.cache=state([device(PC,True,True)]);clock=Clock()
  stale=dict(roles={},controllers=[dict(controller='pc',reachable=True,devices=[device(PC,True,True)])],devices=[],battery=1)
  fresh=dict(roles={},controllers=[dict(controller='phone',reachable=True,devices=[device(PHONE,True,True)])],devices=[],battery=1)
  c.last_overview=(clock.now,stale)
  @contextmanager
  def broken(*a):raise OSError('no route');yield
  with patch('controller.time.monotonic',clock.monotonic),patch('controller.connection',broken),patch.object(c,'overview',return_value=fresh) as ov,patch.object(c,'peer_call',return_value=dict(ok=True,verified=True,noise=dict(level=2,enabled=True))) as call:
   c.override(dict(action='noise',level=2,enabled=True))
  ov.assert_called_once();call.assert_called_once()
 def test_prelude_reused_within_ttl_and_refreshed_after(self):
  c=self.ctl();clock=Clock()
  view=dict(roles={'pc':PC},controllers=[dict(controller='pc',reachable=True,devices=[device(PC,True,True),device(TV,True)])],devices=[],battery=1)
  c.last_overview=(clock.now-2,view)
  with patch('controller.time.monotonic',clock.monotonic),patch.object(c,'overview',return_value=view) as ov,patch.object(c,'local_action',return_value={'ok':True}):
   c.override(dict(action='disconnect',address=TV));ov.assert_not_called()
   c.last_overview=(clock.now-6,view);c.override(dict(action='disconnect',address=TV));ov.assert_called_once()
 def test_stale_prelude_not_used_when_it_has_no_eligible_controller(self):
  c=self.ctl();clock=Clock()
  view=dict(roles={},controllers=[dict(controller='pc',reachable=True,devices=[device(PC,True,True)])])
  c.last_overview=(clock.now,view)
  with patch('controller.time.monotonic',clock.monotonic),patch.object(c,'overview',return_value=view) as ov:
   with self.assertRaises(ValueError):c.override(dict(action='disconnect',address=PC))
  ov.assert_called_once()
 def test_overview_stops_waiting_for_hung_peer_after_excluded_holder_answers(self):
  c=self.ctl(True);release=threading.Event()
  def slow(*a):release.wait(3);return dict(controller='phone',reachable=False)
  try:
   with patch('controller.EXCLUDE_GRACE',.2),patch.object(c,'local_status',return_value=dict(controller='pc',reachable=True,observed=1,devices=[device(PC,True,True)])),patch.object(c,'peer_call',side_effect=slow):
    import time as t;start=t.monotonic();view=c.overview(exclude_current=PC);self.assertLess(t.monotonic()-start,1.5)
    self.assertTrue(view['controllers'][1].get('checking'))
  finally:release.set();c.status_pool.shutdown(wait=True)
 def test_poll_deadline_not_shorter_than_before(self):
  clock=Clock();c=self.ctl()
  f=Fake([device(PC,True,True),device(TV,True),device(PHONE,False)],apply=False)
  with self.assertRaisesRegex(ProtocolError,'Disconnect was not verified'):self.act(c,f,dict(action='connect',address=PHONE,replace=TV),clock)
  self.assertGreaterEqual(clock.slept,6*.4)
  clock=Clock();f=Fake([device(PC,True,True),device(PHONE,False)],apply=False)
  with self.assertRaisesRegex(ProtocolError,'not verified'):self.act(c,f,dict(action='connect',address=PHONE),clock)
  self.assertGreaterEqual(clock.slept,4+8*.5)
  self.assertLessEqual(clock.slept,12)
 def test_polls_are_light_and_fast(self):
  clock=Clock();c=self.ctl();f=Fake([device(PC,True,True),device(TV,True)],apply=False)
  with self.assertRaises(ProtocolError):self.act(c,f,dict(action='disconnect',address=TV),clock)
  self.assertEqual(f.status_calls[0],dict(check_ident=True));self.assertTrue(all(k==dict(full=False,check_ident=False) for k in f.status_calls[1:]))
  self.assertLessEqual(clock.slept/ (len(f.status_calls)-2),.16)
 def test_connect_ack_window_is_short_and_never_resent(self):
  client=Client(None)
  with patch.object(client,'request',side_effect=ProtocolError('Headset did not acknowledge the command')) as req:
   with self.assertRaises(ActionUnconfirmed):client.action('connect',PHONE)
   self.assertEqual(req.call_count,1);self.assertEqual(req.call_args.kwargs['timeout'],1)
  class NoAck(Fake):
   def action(self,action,a):
    self.calls.append((action,a));raise ActionUnconfirmed('no ack')
  f=NoAck([device(PC,True,True),device(PHONE,False)],apply=False);clock=Clock()
  with self.assertRaises(ProtocolError):self.act(self.ctl(),f,dict(action='connect',address=PHONE),clock)
  self.assertEqual(f.calls,[('connect',PHONE)])
 def test_timing_log_has_no_addresses(self):
  c=self.ctl();f=Fake([device(PC,True,True),device(TV,False)])
  with self.assertLogs('bose.timing',level='INFO') as logs:
   self.act(c,f,dict(action='connect',address=TV))
   with self.assertRaises(ValueError):self.act(c,f,dict(action='connect',address=MAC))
  text=' '.join(logs.output)
  self.assertIn('action=connect',text);self.assertIn('outcome=ok',text);self.assertIn('before=',text);self.assertIn('verify=',text)
  self.assertIn('target=device#2',text);self.assertIsNone(MAC_RE.search(text));self.assertNotIn(TV,text)
 def test_peer_state_is_remerged_with_local_controllers(self):
  c=self.ctl(True)
  view=dict(roles={'pc':PC,'phone':PHONE},devices=[],controllers=[dict(controller='pc',reachable=True,devices=[device(PC,True,True)]),dict(controller='phone',reachable=True,devices=[device(PHONE,True,True),device(PC,True)])])
  peer_state=dict(here='phone',devices=[device(PHONE,True,True),device(TV,False)],battery=50,noise=None,observed=9,controllers=[],roles={})
  with patch.object(c,'overview',return_value=view),patch.object(c,'peer_call',return_value=dict(ok=True,verified=True,state=peer_state)):
   s=c.override(dict(action='disconnect',address=PC))['state']
  self.assertEqual(s['here'],'pc');self.assertEqual(len(s['controllers']),2);self.assertEqual(s['battery'],50)

# ---- Tap to switch: every scenario of tests/switch-contract.json, on the Linux PC (fake sink) and without a sink step (macOS) ----
CONTRACT=json.loads((Path(__file__).with_name('switch-contract.json')).read_text())
ROLE={'pc':PC,'phone':PHONE,'mac':MAC}
def text(key):
 value=CONTRACT
 for part in key.split('.'):value=value[part]
 return value
class Headset:
 "Fake NC700 shared by every controller; `script` answers each connect command in turn (contract 'headset' scripts)."
 def __init__(self,start,script,clock):
  self.devices=[device(a,a in start) for a in (PC,PHONE,MAC,TV)];self.script=list(script);self.clock=clock;self.reader=None;self.connects=0;self.calls=[]
 def down(self):return bool(self.script) and self.script[0]=='unreachable'
 def held(self):return [d['address'] for d in self.devices if d['connected']]
 def read(self,reader):return [dict(d,current=d['address']==reader) for d in self.devices]
 def status(self,**kwargs):return state(self.read(self.reader))
 def action(self,action,a):
  self.calls.append((action,a))
  if action=='disconnect':
   for d in self.devices:
    if d['address']==a:d['connected']=False
   return
  self.connects+=1;step=self.script.pop(0) if self.script else 'connect_unconfirmed'
  if step=='hang':self.clock.now+=controller.SWITCH_DEADLINE+1;raise ActionUnconfirmed('no answer')
  if step=='connect_unconfirmed':raise ActionUnconfirmed('no ack')
  for d in self.devices:
   if d['address']==a:d['connected']=True
 def status_of(self,ident):
  # A controller reads the headset only while its own device holds a slot.
  if self.down():return dict(controller=ident,reachable=False,error='Headset unreachable',devices=[])
  if ROLE[ident] not in self.held():return dict(controller=ident,reachable=False,link=False,error='not linked',devices=[])
  return dict(controller=ident,reachable=True,observed=self.clock.now,devices=self.read(ROLE[ident]),battery=80)
class FakeAudio:
 "This PC's BlueZ link and PipeWire sink, derived from the fake headset."
 def __init__(self,headset,sticky=True,sink=True):self.h=headset;self.current='alsa_output.speakers';self.sticky=sticky;self.has_sink=sink;self.pages=0;self.defaults=[]
 def linked(self):return not self.h.down() and PC in self.h.held()
 def page(self):self.pages+=1;return 'org.bluez.Error.Failed: busy'
 def sink(self):return 'bluez_output.AA_AA_AA_AA_AA_AA.1' if self.linked() and self.has_sink else None
 def default(self):return self.current
 def set_default(self,sink):
  self.defaults.append(sink)
  if self.sticky:self.current=sink
 def connect_a2dp(self):return ''
 def drop(self):return ''
 def in_use(self):return True
 def restart_audio(self):pass
class SwitchTests(unittest.TestCase):
 def setUp(self):
  self.clock=Clock()
  self.patches=[patch('controller.time.sleep',self.clock.sleep),patch('controller.time.monotonic',self.clock.monotonic)]
  for item in self.patches:item.start()
 def tearDown(self):
  for item in self.patches:item.stop()
 def rig(self,start,script,audio=True,peer_reply=None):
  h=Headset(start,script,self.clock);roles=dict(ROLE)
  pc=Controller(dict(id='pc',name='PC',headset=PC,roles=roles,peers=[dict(id='phone',name='Phone',url='http://100.64.0.2:8848')]))
  phone=Controller(dict(id='phone',name='Phone',headset=PC,roles=roles,peers=[]))
  pc.audio=FakeAudio(h) if audio else False
  pc.local_status=lambda:h.status_of('pc');phone.local_status=lambda:h.status_of('phone')
  @contextmanager
  def connect(*a):
   if h.down():raise OSError('no route')
   yield h
  def act(ctl,reader,data):
   h.reader=reader
   with patch('controller.connection',connect):return ctl.local_action(data)
  self.relayed=[]
  def peer_call(peer,path,data=None):
   if path=='/api/status':return phone.local_status()
   self.relayed.append(data)
   if peer_reply:return peer_reply
   try:return act(phone,PHONE,data)
   except Exception as e:return {'ok':False,'error':str(e)}
  pc.peer_call=peer_call;pc.prepare_connect=lambda data:{'ok':True}
  orig=pc.local_action
  def local(data,prelude=None,mode=None):
   h.reader=PC
   with patch('controller.connection',connect):return orig(data,prelude,mode)
  pc.local_action=local
  return pc,phone,h
 def run_switch(self,pc,body):
  with self.assertLogs('bose.timing',level='INFO') as logs:result=pc.switch_request(body)
  lines=[l.split(':',2)[2] for l in logs.output];switch=[l for l in lines if l.startswith('bose.switch ')]
  self.assertEqual(len(switch),1,lines);self.assertIsNone(MAC_RE.search(' '.join(lines)),lines)
  for name in ('Desktop','Android'):self.assertNotIn(name,' '.join(lines))
  return result,switch[0],lines
 def abstract(self):return {'here':'pc','other1':'phone','other2':'mac'}
 def scenario(self,sc,audio):
  roles=self.abstract();start=[ROLE[roles[r]] for r in sc['start']]
  pc,phone,h=self.rig(start,sc['headset'],audio)
  body={'source':'web','request_id':'r'+sc['name'].replace('_','')[:20]}
  if sc.get('replace'):body['replace']=ROLE[roles[sc['replace']]]
  try:result,line,lines=self.run_switch(pc,body)
  finally:pc.status_pool.shutdown(wait=True)
  exp=sc['expect'];outcome=exp['outcome']
  fields=dict(part.split('=',1) for part in line.split()[1:])
  self.assertEqual((fields['source'],fields['id'],fields['target']),('web',body['request_id'],'PC'))
  self.assertEqual(fields['replace'],CONTRACT['labels'][roles[sc['replace']]] if sc.get('replace') else '-')
  self.assertRegex(fields['total'],r'^\d+\.\d\ds$')
  if outcome=='ok':
   self.assertEqual(result['ok'],True);self.assertTrue(result['verified']);self.assertEqual(result['message'],text(exp['text']));self.assertEqual(fields['outcome'],'ok')
   self.assertIn('devices',result['state'])
   if audio:self.assertEqual(pc.audio.current,'bluez_output.AA_AA_AA_AA_AA_AA.1')
  elif outcome=='busy':
   self.assertEqual({k:result[k] for k in ('ok','busy','error_key','error')},dict(ok=False,busy=True,error_key='busy',error=text(exp['text'])));self.assertEqual(fields['outcome'],'busy')
   offered=[CONTRACT['messages']['replace'].format(label=s['label']) for s in result['slots']]
   self.assertEqual(sorted(offered),sorted(o.replace('{other1}',CONTRACT['labels'][roles['other1']]).replace('{other2}',CONTRACT['labels'][roles['other2']]) for o in exp['offered']))
   self.assertEqual(sorted(s['address'] for s in result['slots']),sorted(start))
  else:
   self.assertEqual((result['ok'],result['error_key'],result['error']),(False,exp['error_key'],text(exp['text'])));self.assertIn('detail',result)
   self.assertEqual(fields['outcome'],'error:'+exp['error_key'])
  if 'connect_commands' in exp:self.assertEqual(h.connects,exp['connect_commands'])
  self.assertLessEqual(h.connects,2,'at most one resend')
  if 'connected' in exp:self.assertEqual(sorted(h.held()),sorted(ROLE[roles[r]] for r in exp['connected']))
  if h.connects:self.assertEqual(fields['via'],'peer:phone')
  if self.relayed:
   self.assertTrue(all(d['source']=='web' and d['request_id']==body['request_id'] for d in self.relayed))
   self.assertTrue(any('id='+body['request_id'] in l and 'action=connect' in l for l in lines),lines)
  return result,h,pc
 def test_contract_scenarios_linux_pc(self):
  for sc in CONTRACT['scenarios']:
   with self.subTest(sc['name']):self.scenario(sc,True)
 def test_contract_scenarios_without_sink_step(self):
  for sc in CONTRACT['scenarios']:
   with self.subTest(sc['name']):self.scenario(sc,False)
 def test_messages_sources_and_labels_match_contract(self):
  self.assertEqual(controller.MESSAGES,CONTRACT['messages']);self.assertEqual(list(controller.SOURCES),CONTRACT['sources'])
  self.assertEqual(controller.LABELS,CONTRACT['labels']);self.assertEqual(controller.SWITCH_DEADLINE,CONTRACT['rules']['deadline_seconds'])
 def test_outstanding_peer_reply_is_never_resent(self):
  pc,phone,h=self.rig([PHONE],[],peer_reply={'reachable':False,'controller':'phone','error':'Controller unavailable: TimeoutError'})
  result,line,_=self.run_switch(pc,{'source':'omarchy'});pc.status_pool.shutdown(wait=True)
  self.assertEqual((result['error_key'],len(self.relayed)),('timeout',1));self.assertIn('outcome=error:timeout via=peer:phone',line)
 def test_stale_replace_is_ignored_when_a_slot_is_free(self):
  pc,phone,h=self.rig([PHONE],['connect_ok'])
  result,line,_=self.run_switch(pc,{'source':'web','replace':MAC});pc.status_pool.shutdown(wait=True)
  self.assertTrue(result['ok']);self.assertNotIn(('disconnect',MAC),h.calls);self.assertIn('replace=-',line)
 def test_linux_pages_until_linked_then_needs_default_sink(self):
  pc,phone,h=self.rig([PC,PHONE],[]);linked=iter([False,False,True])
  pc.audio.linked=lambda:next(linked,True)
  result,_,_=self.run_switch(pc,{'source':'desk'});pc.status_pool.shutdown(wait=True)
  self.assertTrue(result['ok']);self.assertEqual(pc.audio.pages,2);self.assertEqual(h.connects,0)
  pc,phone,h=self.rig([PC,PHONE],[]);pc.audio.sticky=False
  result,line,_=self.run_switch(pc,{'source':'omarchy'});pc.status_pool.shutdown(wait=True)
  self.assertEqual((result['error_key'],result['error']),('audio_not_moved',controller.MESSAGES['errors']['audio_not_moved']));self.assertIn('outcome=error:audio_not_moved',line)
  pc,phone,h=self.rig([PC,PHONE],[]);pc.audio.has_sink=False
  result,_,_=self.run_switch(pc,{'source':'omarchy'});pc.status_pool.shutdown(wait=True)
  self.assertEqual(result['error_key'],'no_audio');self.assertLessEqual(self.clock.now-1000,controller.SWITCH_DEADLINE)
 def test_unreachable_headset_is_paged_for_45_seconds(self):
  pc,phone,h=self.rig([PHONE],['unreachable'])
  result,_,_=self.run_switch(pc,{'source':'web'});pc.status_pool.shutdown(wait=True)
  self.assertEqual(result['error_key'],'unreachable');self.assertGreaterEqual(pc.audio.pages,10);self.assertLessEqual(self.clock.now-1000,controller.PAGE_WAIT+1)
 def test_invalid_switch_requests_are_refused_and_logged_once(self):
  pc,phone,h=self.rig([PHONE],[])
  for body in ({},{'source':'tv'},{'source':'web','extra':1},{'source':'web','request_id':'has space'},{'source':'web','replace':5},{'source':'web','replace':'nope'}):
   with self.subTest(body),self.assertLogs('bose.timing',level='INFO') as logs:
    with self.assertRaises(ValueError):pc.switch_request(body)
   self.assertEqual(len(logs.output),1);self.assertIn('outcome=error:invalid',logs.output[0])
  self.assertEqual(h.calls,[]);pc.status_pool.shutdown(wait=True)
 def test_override_errors_use_contract_texts_and_log_one_line(self):
  pc,phone,h=self.rig([PC,PHONE],[])
  with self.assertLogs('bose.timing',level='INFO') as logs:
   with self.assertRaises(controller.ReplyError) as caught:pc.override_request({'action':'connect','address':MAC,'source':'web','request_id':'abc'})
  reply=caught.exception.reply;pc.status_pool.shutdown(wait=True)
  self.assertEqual((reply['error_key'],reply['error']),('busy',controller.MESSAGES['busy']))
  lines=[l for l in logs.output if 'bose.switch' in l];self.assertEqual(len(lines),1)
  self.assertIn('source=web id=abc target=Mac replace=- outcome=error:busy via=local',lines[0]);self.assertIsNone(MAC_RE.search(' '.join(logs.output)))
  pc,phone,h=self.rig([PC,PHONE],[])
  with self.assertLogs('bose.timing',level='INFO') as logs:
   r=pc.override_request({'action':'disconnect','address':PHONE})
  pc.status_pool.shutdown(wait=True)
  self.assertTrue(r['ok']);self.assertIn('bose.switch source=unknown id=- target=Phone replace=- outcome=ok via=local',' '.join(logs.output))
  with self.assertRaises(ValueError):pc.override_request({'action':'noise','level':3,'enabled':True,'source':'nowhere'})
if __name__=='__main__':unittest.main()
