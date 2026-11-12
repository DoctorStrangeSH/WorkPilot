import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from malenia import __version__
from malenia.cli import main
from malenia.config import data_directory, database_path
from malenia.server import create_server
from malenia.store import TaskStore


class AgentStartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = TaskStore(self.root / 'test.sqlite3')

    def tearDown(self):
        self.temporary.cleanup()

    def test_second_listener_cannot_take_over_the_first_endpoint(self):
        first = create_server('127.0.0.1', 0, self.store, 'test-only-token')
        try:
            with self.assertRaises(OSError):
                create_server('127.0.0.1', first.server_port, self.store, 'other-test-token')
            self.assertEqual(first.socket.getsockname()[1], first.server_port)
        finally:
            first.server_close()

    def test_busy_port_fails_before_announcing_readiness_or_printing_a_token(self):
        first = create_server('127.0.0.1', 0, self.store, 'test-only-token')
        output, errors = io.StringIO(), io.StringIO()
        try:
            with patch('sys.argv', ['malenia-agent', '--port', str(first.server_port)]), \
                 patch('malenia.cli.database_path', return_value=self.root / 'cli.sqlite3'), \
                 patch.dict(os.environ, {'MALENIA_API_TOKEN': 'test-token-must-not-print'}), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = main()
            self.assertEqual(code, 2)
            self.assertEqual(output.getvalue(), '')
            self.assertIn('occupied or unavailable', errors.getvalue())
            self.assertNotIn('test-token-must-not-print', errors.getvalue())
            self.assertEqual(first.socket.getsockname()[1], first.server_port)
        finally:
            first.server_close()

    def test_fresh_malenia_namespace_and_version(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.root), 'XDG_DATA_HOME': str(self.root)}):
            self.assertEqual(data_directory(), self.root / 'Malenia')
            self.assertEqual(database_path(), self.root / 'Malenia' / 'malenia.sqlite3')
        self.assertEqual(__version__, '0.2.0')
