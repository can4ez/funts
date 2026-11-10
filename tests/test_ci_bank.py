"""CI importer contract and source-manifest smoke tests."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestCIBank(unittest.TestCase):
    def test_ci_sources_and_generated_bank(self):
        config = json.loads((ROOT / 'data/sources.json').read_text(encoding='utf-8'))
        enabled = [source for source in config['sources'] if source.get('enabled', True)]
        self.assertGreaterEqual(len(enabled), 1)
        # Every approved external source must be explicitly opt-in, and carry provenance.
        for source in config['sources']:
            if source.get('url') and source.get('enabled'):
                self.assertTrue(source.get('approved'))
                self.assertTrue(source.get('license'))
                self.assertTrue(source.get('permission_note'))
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            out, report = d / 'bank.json', d / 'report.json'
            result = subprocess.run([
                sys.executable, str(ROOT / 'tools/question_importer.py'),
                '--config', str(ROOT / 'data/sources.json'),
                '--existing', str(ROOT / 'data/base-question-bank.json'),
                '--output', str(out), '--report', str(report), '--hold-review'
            ], cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
            cards = json.loads(out.read_text(encoding='utf-8'))['cards']
            stats = json.loads(report.read_text(encoding='utf-8'))['stats']
            self.assertEqual(len(cards), stats['accepted'])
            self.assertGreaterEqual(len(cards), 5)
            self.assertEqual(len({(c['type'], c['text'].casefold()) for c in cards}), len(cards))
            self.assertTrue(all(c['type'] in ('truth', 'dare') and c['level'] in (1, 2, 3) for c in cards))


if __name__ == '__main__':
    unittest.main()
