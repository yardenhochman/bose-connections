import os,shutil,subprocess,unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
class OmarchyContract(unittest.TestCase):
 """Runs tests/bose_model.qml offscreen: the Omarchy popup model through every switch-contract scenario."""
 @unittest.skipUnless(shutil.which('qml6'),'qml6 (Qt 6 declarative tools) not installed')
 def test_bose_model_follows_switch_contract(self):
  env={k:v for k,v in os.environ.items() if k not in ('DISPLAY','WAYLAND_DISPLAY')}
  env.update(QT_QPA_PLATFORM='offscreen',QML_XHR_ALLOW_FILE_READ='1',QT_FORCE_STDERR_LOGGING='1')
  run=subprocess.run(['qml6',str(HERE/'bose_model.qml')],cwd=HERE,env=env,capture_output=True,text=True,timeout=120)
  out=run.stdout+run.stderr
  self.assertEqual(run.returncode,0,out);self.assertIn('PASS omarchy contract',out);self.assertNotIn('FAIL',out)
if __name__=='__main__':unittest.main()
