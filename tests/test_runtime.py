import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills' / 'agent-entry' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from agent_entry.evidence import extract
from agent_entry.routing import discover
from agent_entry.state import Store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / '项目 with spaces'
        self.project.mkdir()
        (self.project / 'source.txt').write_text('irrelevant\n原文第二行\n第三行\nend\n', encoding='utf-8')
        self.state = self.base / 'state'
        self.fake = self.base / 'fake codex'
        self.fake.write_text('#!' + sys.executable + '\n' + (ROOT / 'tests/fake_codex.py').read_text(), encoding='utf-8')
        self.fake.chmod(0o700)
        self.environment = dict(os.environ, FAKE_CODEX_STATE=str(self.base / 'fake-state'))
        self.environment.pop('AGENT_ENTRY_WORKER', None)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, data=None, environment=None):
        return subprocess.run([sys.executable, str(ROOT / 'cli.py'), '--state-dir', str(self.state),
                               '--codex-bin', str(self.fake), *args], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=environment or self.environment, timeout=8)

    def begin(self, mode='relay', message='hello', *options):
        result = self.cli(mode, '--cwd', str(self.project), '--message', message, *options)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return json.loads(result.stdout)

    def calls(self):
        return [json.loads(line) for line in (self.base / 'fake-state/calls.jsonl').read_text().splitlines()]

    def test_relay_resume_preserves_exact_bytes_and_thread(self):
        first = self.begin()
        message = '换行\n`touch /tmp/should-not-run` $(echo nope)\n'
        reply = self.cli('send', first['session_id'], '--raw', data=message.encode())
        self.assertEqual(reply.returncode, 0, reply.stderr)
        self.assertEqual(reply.stdout, ('  回复：' + message + '\n\n').encode())
        calls = self.calls()
        self.assertEqual(calls[1]['prompt'], message)
        self.assertIn(first['remote_id'], calls[1]['args'])
        self.assertNotIn('--last', calls[1]['args'])
        self.assertEqual(calls[1]['cwd'], str(self.project))
        state = json.loads(self.cli('show', first['session_id']).stdout)
        self.assertEqual(state['remote_id'], first['remote_id'])
        self.assertEqual(len(list(self.state.glob('*/session.json'))), 1)

    def test_relay_preserves_crlf_input_from_file_and_stdin(self):
        first = self.begin()
        message = b'line one\r\nline two\r\n'
        request = self.base / 'request.txt'
        request.write_bytes(message)
        for options, data in [(['--message-file', str(request)], None), ([], message)]:
            result = self.cli('send', first['session_id'], '--raw', *options, data=data)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls()[-1]['prompt'].encode(), message)
            self.assertEqual(result.stdout, '  回复：'.encode() + message + b'\n\n')

    def test_delegate_settings_persist_on_resume(self):
        first = self.begin('delegate', 'inspect', '--allow-writes', '--model', 'explicit-model', '--effort', 'high')
        result = self.cli('send', first['session_id'], '--message', 'continue')
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.calls():
            self.assertEqual(call['args'][call['args'].index('--sandbox') + 1], 'workspace-write')
            self.assertIn('explicit-model', call['args'])
            self.assertIn('model_reasoning_effort="high"', call['args'])
            self.assertEqual(call['nested'], '1')

    def test_retrieval_reads_actual_source_and_remains_read_only(self):
        first = self.begin('retrieve', 'find passage')
        evidence = first['evidence']['findings'][0]
        self.assertEqual(evidence['excerpt'], '原文第二行\n第三行\n')
        self.assertEqual(len(evidence['sha256']), 64)
        self.assertNotIn('reply', first)
        call = self.calls()[0]
        self.assertIn('read-only', call['args'])
        self.assertIn('--output-schema', call['args'])
        followup = self.cli('send', first['session_id'], '--message', 'again')
        self.assertEqual(followup.returncode, 0, followup.stderr)
        self.assertEqual(json.loads(followup.stdout)['evidence']['findings'][0]['excerpt'], evidence['excerpt'])

    def test_retrieval_escape_fails_without_returning_unverified_reply(self):
        (self.base / 'secret.txt').write_text('private')
        result = self.cli('retrieve', '--cwd', str(self.project), '--message', 'EVIDENCE_ESCAPE')
        self.assertEqual(result.returncode, 1)
        envelope = json.loads(result.stdout)
        self.assertIn('escapes', envelope['error'])
        self.assertNotIn('reply', envelope)
        self.assertNotIn('evidence', envelope)

    def test_failed_raw_turn_has_no_stdout_or_automatic_retry(self):
        first = self.begin()
        result = self.cli('send', first['session_id'], '--message', 'FAIL', '--raw')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b'')
        self.assertIn(b'failed', result.stderr)
        self.assertEqual(len(self.calls()), 2)
        self.assertEqual(json.loads(self.cli('show', first['session_id']).stdout)['status'], 'failed')

    def test_invalid_or_incomplete_protocol_is_not_success(self):
        for message in ('MALFORMED', 'NO_FINAL', 'INCOMPLETE'):
            with self.subTest(message=message):
                result = self.cli('relay', '--cwd', str(self.project), '--message', message)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)['status'], 'failed')

    def test_thread_mismatch_is_detected(self):
        first = self.begin()
        result = self.cli('send', first['session_id'], '--message', 'WRONG_THREAD')
        self.assertEqual(result.returncode, 1)
        self.assertIn('different thread', json.loads(result.stdout)['error'])

    def test_timeout_stops_worker_group_and_records_resumable_id(self):
        result = self.cli('relay', '--cwd', str(self.project), '--message', 'TIMEOUT', '--timeout', '1.5')
        self.assertEqual(result.returncode, 1)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope['status'], 'timeout')
        self.assertTrue(envelope['remote_id'])
        time.sleep(4.2)
        self.assertFalse((self.base / 'fake-state/orphan.txt').exists())
        resumed = self.cli('send', envelope['session_id'], '--message', 'after timeout')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)

    def test_state_wide_lock_prevents_another_worker(self):
        with Store(self.state).locked():
            result = self.cli('relay', '--cwd', str(self.project), '--message', 'hello')
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'Another worker', result.stderr)
        self.assertFalse((self.base / 'fake-state').exists())

    def test_nested_runtime_is_rejected(self):
        env = dict(self.environment, AGENT_ENTRY_WORKER='1')
        result = self.cli('relay', '--cwd', str(self.project), '--message', 'hello', environment=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'Nested', result.stderr)
        self.assertFalse((self.base / 'fake-state').exists())

    def test_read_only_default_and_no_forced_model(self):
        self.begin()
        args = self.calls()[0]['args']
        self.assertIn('read-only', args)
        self.assertNotIn('--model', args)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)

    def test_chat_forwards_same_session_and_keeps_prompts_on_stderr(self):
        first = self.begin()
        result = self.cli('chat', first['session_id'], data='接着说\n/quit\n'.encode())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '  回复：接着说\n\n\n'.encode())
        self.assertIn(b'You>', result.stderr)
        self.assertIn(first['remote_id'], self.calls()[1]['args'])

    def test_copied_skill_is_self_contained(self):
        copied = self.base / 'installed-skill'
        shutil.copytree(ROOT / 'skills/agent-entry', copied)
        result = subprocess.run([sys.executable, str(copied / 'scripts/agent-entry.py'), 'capabilities'],
                                cwd=str(self.project), capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['capabilities']['resume'])

    def test_recover_preserves_thread_without_running_another_turn(self):
        first = self.begin()
        store = Store(self.state)
        record = store.get(first['session_id'])
        record.update(status='running', remote_id=None)
        store.save(record)
        result = self.cli('recover', first['session_id'])
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record['remote_id'], first['remote_id'])
        self.assertEqual(record['status'], 'interrupted')
        self.assertEqual(len(self.calls()), 1)

    def test_rejects_empty_prompt_and_bad_session_id(self):
        self.assertEqual(self.cli('relay', '--cwd', str(self.project), data=b'').returncode, 2)
        self.assertEqual(self.cli('show', '../../escape').returncode, 2)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()
        (self.root / 'source').write_text('one\ntwo\n')

    def tearDown(self):
        self.temp.cleanup()

    def data(self, path='source', start=1, end=1):
        return json.dumps({'summary': 's', 'unresolved': [], 'findings': [
            {'path': path, 'start_line': start, 'end_line': end, 'reason': 'r'}]})

    def test_rejects_symlink_escape(self):
        outside = self.root.parent / 'outside'
        outside.write_text('secret')
        (self.root / 'link').symlink_to(outside)
        with self.assertRaises(ValueError):
            extract(self.root, self.data('link'))

    def test_rejects_invalid_ranges_binary_and_byte_overflow(self):
        for start, end in [(0, 1), (1, 3), (2, 1), (1, 41), (True, 1)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                extract(self.root, self.data(start=start, end=end))
        (self.root / 'source').write_bytes(b'binary\x00data')
        with self.assertRaises(ValueError):
            extract(self.root, self.data())
        (self.root / 'source').write_text('abc\n')
        with self.assertRaises(ValueError):
            extract(self.root, self.data(), max_bytes=2)


class DiscoveryTests(unittest.TestCase):
    def test_bounded_discovery_excludes_generated_dirs_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ['app', 'node_modules', '.worktrees', 'docs']:
                (root / name).mkdir()
            (root / 'link').symlink_to(root / 'app')
            (root / 'app/pyproject.toml').write_text('')
            result = discover(root)
            paths = {Path(item['path']).name for item in result['candidates']}
            self.assertIn('app', paths)
            self.assertNotIn('node_modules', paths)
            self.assertNotIn('link', paths)
            self.assertLessEqual(len(discover(root, limit=1)['candidates']), 1)
            self.assertTrue(discover(root, limit=1)['truncated'])
            self.assertLessEqual(discover(root, max_entries=1)['entries_examined'], 1)


if __name__ == '__main__':
    unittest.main()
