import unittest,json,os,shutil,subprocess,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=json.loads((ROOT/'tests/switch-contract.json').read_text())
JDK=Path(os.environ.get('BOSE_JDK','/data/agent-builds/android-tools/jdk'))
JAVAC=shutil.which('javac') or (str(JDK/'bin/javac') if (JDK/'bin/javac').exists() else None)
JAVA=shutil.which('java') or (str(JDK/'bin/java') if (JDK/'bin/java').exists() else None)

def flat_messages():
 m=CONTRACT['messages'];out={k:v for k,v in m.items() if k!='errors'}
 out.update({'errors.'+k:v for k,v in m['errors'].items()});return out

def scenario_lines():
 labels=CONTRACT['labels'];msgs=CONTRACT['messages'];others=['mac','pc'];lines=[]
 def label(role):return labels[others[int(role[-1])-1]]
 def text(ref):
  if ref.startswith('messages.errors.'):return msgs['errors'][ref.rsplit('.',1)[1]]
  return msgs[ref.split('.',1)[1]]
 for s in CONTRACT['scenarios']:
  e=s['expect']
  offered=[x.replace('{other1}',label('other1')).replace('{other2}',label('other2')) for x in e.get('offered',[])]
  lines.append('\t'.join(['scn',s['name'],','.join(s['start']),s.get('replace',''),','.join(s['headset']),e['outcome'],text(e['text']),e.get('error_key',''),str(e.get('connect_commands','')),','.join(e.get('connected',[])),','.join(offered)]))
 return lines

@unittest.skipUnless(JAVAC and JAVA,'JDK (javac/java) not available')
class AndroidContract(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(prefix='bose-android-test-');out=Path(cls.tmp.name)
  sources=[*sorted((ROOT/'tests/android/shim').rglob('*.java')),ROOT/'android/Switcher.java',ROOT/'tests/android/SwitcherTest.java']
  build=subprocess.run([JAVAC,'-encoding','UTF-8','-d',str(out/'classes'),*map(str,sources)],capture_output=True,text=True)
  if build.returncode:raise AssertionError('javac failed:\n'+build.stderr)
  (out/'contract.txt').write_text('\n'.join(['msg\t%s\t%s'%kv for kv in flat_messages().items()]+scenario_lines())+'\n',encoding='utf-8')
  run=subprocess.run([JAVA,'-Dfile.encoding=UTF-8','-cp',str(out/'classes'),'local.bose.connections.SwitcherTest',str(out/'contract.txt')],capture_output=True,text=True,encoding='utf-8')
  cls.returncode=run.returncode;cls.output=run.stdout+run.stderr
  cls.results={l.split(' ',2)[1].rstrip(':'):l.startswith('PASS') for l in run.stdout.splitlines() if l.startswith(('PASS ','FAIL '))}
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def test_messages_equal_contract(self):self.assertTrue(self.results.get('messages_equal_contract'),self.output)
 def test_every_contract_scenario(self):
  for s in CONTRACT['scenarios']:
   with self.subTest(s['name']):self.assertTrue(self.results.get(s['name']),self.output)
 def test_extra_cases_and_exit_status(self):
  self.assertEqual(self.returncode,0,self.output)
  for n in ('replace_ignored_when_slot_free','replace_not_held_offers_busy_again','no_controller_reads_headset_is_unreachable','overview_failure_is_unreachable','replace_must_leave_a_known_device','phone_holds_no_slot_both_busy_is_busy','replace_is_passed_to_override','first_unverified_second_succeeds_after_fresh_overview','executed_via_peer_logs_peer'):
   with self.subTest(n):self.assertTrue(self.results.get(n),self.output)
 def test_android_strings_use_contract_texts_only(self):
  core=(ROOT/'android/Core.java').read_text()
  for drifted in ('Both slots are occupied','Change not verified. Refresh','No controller can make this change','Keep one phone, PC or Mac connected for control"'):
   self.assertNotIn('new IOException("'+drifted,core)
  self.assertEqual(set(CONTRACT['sources'])>={'android-app','android-tile'},True)
  self.assertIn('"android-tile"',(ROOT/'android/BoseTileService.java').read_text())
  self.assertIn('bose.switch source=',(ROOT/'android/Switcher.java').read_text())

if __name__=='__main__':unittest.main()
