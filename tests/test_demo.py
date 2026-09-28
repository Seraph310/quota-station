"""The public demo must not depend on the user's live account files."""
import json
import unittest

import app
from demo import demo_state


class DemoIsolationTests(unittest.TestCase):
    def test_demo_uses_a_temporary_cache_and_restores_state(self):
        original = app.STATE
        with demo_state():
            temporary = app.STATE
            self.assertNotEqual(temporary, original)
            data = json.loads((temporary / 'balances.json').read_text('utf-8'))
            self.assertEqual([data[str(i)]['balance'] for i in range(3)], [78, 620, 1280.5])
            self.assertTrue(all('演示数据' in value['details'][0]['value'] for value in data.values()))
        self.assertEqual(app.STATE, original)
        self.assertFalse(temporary.exists())

    def test_state_restored_even_if_demo_raises(self):
        original = app.STATE
        with self.assertRaises(RuntimeError):
            with demo_state():
                raise RuntimeError('synthetic failure')
        self.assertEqual(app.STATE, original)


if __name__ == '__main__':
    unittest.main()
