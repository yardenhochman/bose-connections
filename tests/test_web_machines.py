"""The dashboard's pure state machines (web/app.js machines block) checked in node; skipped without node."""
import shutil, subprocess, unittest
from pathlib import Path

class WebMachines(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'node is not installed')
    def test_transition_tables(self):
        done=subprocess.run(['node',str(Path(__file__).with_name('web_machines.cjs'))],capture_output=True,text=True,timeout=60)
        self.assertEqual(done.returncode,0,done.stdout+done.stderr);self.assertIn('transitions checked',done.stdout)

if __name__=='__main__':unittest.main()
