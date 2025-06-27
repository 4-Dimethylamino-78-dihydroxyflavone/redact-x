import subprocess
from pathlib import Path
import unittest

class CLIMissingOutputTest(unittest.TestCase):
    def test_missing_output(self):
        script = Path(__file__).resolve().parents[1] / 'redact_unified.py'
        result = subprocess.run(['python', str(script), 'input.pdf'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('output PDF required in CLI mode', result.stderr)

if __name__ == '__main__':
    unittest.main()
