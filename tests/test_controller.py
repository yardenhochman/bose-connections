import unittest
import threading
import tempfile,json
from unittest.mock import patch
from contextlib import contextmanager
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from protocol import Client,ProtocolError,ActionUnconfirmed,parse_list,parse_info,mac_bytes
from controller import Controller

PC='AA:AA:AA:AA:AA:AA';PHONE='BB:BB:BB:BB:BB:BB';TV='CC:CC:CC:CC:CC:CC';MAC='DD:DD:DD:DD:DD:DD'
def device(a,connected,current=False):return dict(address=a,connected=connected,current=current,name=a)
def state(devices):return {'devices':devices,'battery':80}
class Fake:
 def __init__(self,devices,apply=True):self.devices=devices;self.calls=[];self.apply=apply
 def status(self):return state(self.devices)
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
if __name__=='__main__':unittest.main()
