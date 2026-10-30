import unittest,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=json.loads((ROOT/'tests/switch-contract.json').read_text())
SOURCE=(ROOT/'mac/Launcher.m').read_text(encoding='utf-8')

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
  code=code_only(SOURCE)
  for a,b in ('()','[]','{}'):self.assertEqual(code.count(a),code.count(b),a+b)

if __name__=='__main__':unittest.main()
