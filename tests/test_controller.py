import unittest,re
import threading
import tempfile,json
from unittest.mock import patch
from contextlib import contextmanager
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from protocol import Client,ProtocolError,ActionUnconfirmed,parse_list,parse_info,mac_bytes,parse_noise
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
if __name__=='__main__':unittest.main()
