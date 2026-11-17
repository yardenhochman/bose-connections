import unittest,json,re,subprocess,sys,shutil,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=json.loads((ROOT/'tests/switch-contract.json').read_text())
SOURCE=(ROOT/'mac/Launcher.m').read_text(encoding='utf-8')
HEADER=(ROOT/'mac/Machines.h').read_text(encoding='utf-8') if (ROOT/'mac/Machines.h').exists() else ''

def code_only(text):
 text=re.sub(r'@?"(?:\\.|[^"\\])*"','""',text);return re.sub(r'//[^\n]*','',text)

class MacContract(unittest.TestCase):
 """Static checks: Objective-C cannot be compiled on the Linux bench, so the menu's contract usage is asserted from source."""
 def test_every_contract_text_is_verbatim(self):
  m=CONTRACT['messages']
  texts=[v for k,v in m.items() if k!='errors']+list(m['errors'].values())
  for t in texts:
   with self.subTest(t):self.assertIn('@"%s"'%t,SOURCE)
 def test_posts_switch_with_contract_body(self):
  self.assertIn('@"/api/switch"',SOURCE)
  api=CONTRACT['api']['switch']
  self.assertEqual(api['path'],'/api/switch');self.assertEqual(api['method'],'POST')
  for key in api['body']:self.assertIn('@"%s"'%key,SOURCE)
  self.assertIn('@"mac-menu"',SOURCE);self.assertIn('mac-menu',CONTRACT['sources'])
 def test_menu_item_and_replace_flow(self):
  self.assertIn('@"Use on this Mac"',SOURCE)
  self.assertIn('BoseReplace stringByReplacingOccurrencesOfString:@"{label}"',SOURCE)
  self.assertIn('BoseReplacing stringByReplacingOccurrencesOfString:@"{label}"',SOURCE)
  self.assertIn('self.switchText=label?',SOURCE)
  self.assertIn('BosePending',SOURCE)
 def test_handles_busy_slots_and_error_key(self):
  for token in ('@"busy"','@"slots"','@"error_key"','@"label"','@"address"','@"verified"'):self.assertIn(token,SOURCE)
  for key in CONTRACT['messages']['errors']:self.assertIn('@"%s":BoseErr'%key,SOURCE.replace(' ',''))
  self.assertIn('BoseRetryHint',SOURCE)
 def test_no_raw_errors_or_short_timeout(self):
  self.assertNotIn('Change failed',SOURCE);self.assertNotIn('Change not verified',SOURCE)
  self.assertNotIn('?120:40',SOURCE)
  self.assertIn('?160:40',SOURCE)  # above the contract's 150 s deadline, so the controller's own timeout reply arrives first
  self.assertGreater(160,CONTRACT['rules']['deadline_seconds'])
 def test_existing_device_items_kept(self):
  for token in ('deviceClicked:','@"/api/override"','Noise cancellation','Open full window'):self.assertIn(token,SOURCE)
 def test_brackets_balance(self):
  for name,text in (('Launcher.m',SOURCE),('Machines.h',HEADER)):
   code=code_only(text)
   for a,b in ('()','[]','{}'):self.assertEqual(code.count(a),code.count(b),name+' '+a+b)
 def test_machines_header_is_pure_and_imported(self):
  self.assertIn('#import "Machines.h"',SOURCE)
  self.assertTrue(HEADER,'mac/Machines.h is missing')
  self.assertNotIn('AppKit',HEADER);self.assertNotIn('Cocoa',HEADER);self.assertIn('#import <Foundation/Foundation.h>',HEADER)
  for fn in ('BoseNoiser','BoseNoiseShown','BoseIntents','BoseIntentKey','BoseSchedule','BoseReleaseCheck'):
   self.assertIn(fn,HEADER)
   if fn!='BoseIntentKey':self.assertIn(fn,SOURCE)  # the key is used inside BoseIntents
 def test_menu_items_stay_enabled_while_changing(self):
  item=SOURCE[SOURCE.index('- (NSMenuItem *)item:'):SOURCE.index('- (NSMenuItem *)sectionHeader:')]
  self.assertNotIn('self.changing',item)
  can=SOURCE[SOURCE.index('- (BOOL)canChange'):SOURCE.index('- (NSString *)clock:')]
  self.assertNotIn('!self.changing',can)
  self.assertNotIn('use.enabled=!self.changing',SOURCE);self.assertNotIn('row.enabled=!self.changing',SOURCE)
  for fn in ('deviceClicked:','switchHere:','refreshMenu'):
   body=SOURCE[SOURCE.index('- (void)'+fn):];body=body[:body.index('\n}\n')]
   self.assertNotIn('if(self.changing)return',body.replace(' ',''),fn)
 def test_menu_follows_the_input_rule(self):
  for token in ('Connects next','Disconnects next','Moves here next','Queued · cancel','Setting level','applies when','Noise change not sent: the headphones aren’t reachable now','- (void)pump','self.changes','BoseSchedule(','Refreshing…','Refreshing after the change…','refreshWanted'):
   self.assertIn(token,SOURCE,token)
  self.assertEqual(SOURCE.count('@"/api/override"'),2)  # the intent runner and the noise writer: only pump starts either
  self.assertIn('menuMessageUntil',SOURCE)
class MacMachines(unittest.TestCase):
 @unittest.skipUnless(sys.platform=='darwin' and shutil.which('xcrun'),'Objective-C machines run on macOS only')
 def test_machines_run_the_shared_tables(self):
  with tempfile.TemporaryDirectory() as d:
   exe=Path(d)/'MachinesTest'
   subprocess.run(['xcrun','clang','-fobjc-arc','-Wall','-framework','Foundation','-I',str(ROOT/'mac'),str(ROOT/'tests/mac/MachinesTest.m'),'-o',str(exe)],check=True)
   r=subprocess.run([str(exe),str(ROOT/'tests/machine-tables.json')],capture_output=True,text=True)
   self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('0 failed',r.stdout)

if __name__=='__main__':unittest.main()
