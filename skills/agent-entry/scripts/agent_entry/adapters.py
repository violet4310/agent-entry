"""Backend contract and the initial Codex exec adapter."""
import json
import os
import signal
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Result:
    status: str
    remote_id: Optional[str]
    reply: bytes
    error: Optional[str] = None


class Adapter(ABC):
    name = ''
    capabilities = {}

    @abstractmethod
    def run(self, record, message, artifacts, timeout, schema=None):
        """Return a Result, keeping backend output and diagnostics in artifacts."""


class CodexExec(Adapter):
    name = 'codex'
    capabilities = {'resume': True, 'final_reply': True, 'read_only': True,
                    'interactive_approvals': False, 'streaming_ui': False,
                    'native_handoff': False}

    def __init__(self, executable='codex'):
        self.executable = executable

    def command(self, record, artifacts, schema=None):
        # Global options before `resume` also work on CLI versions whose resume
        # subcommand does not expose sandbox/cwd flags of its own.
        args = [self.executable, 'exec', '--json', '--color', 'never',
                '--sandbox', record['sandbox'], '--cd', record['cwd'],
                '--skip-git-repo-check', '-o', str(artifacts / 'final.txt')]
        if record.get('model'):
            args += ['--model', record['model']]
        if record.get('effort'):
            args += ['-c', 'model_reasoning_effort=' + json.dumps(record['effort'])]
        if schema is not None:
            schema_path = artifacts / 'schema.json'
            schema_path.write_text(json.dumps(schema), encoding='utf-8')
            args += ['--output-schema', str(schema_path)]
        if record.get('remote_id'):
            args += ['resume', record['remote_id']]
        # stdin preserves multiline input and keeps prompts out of process args.
        args += ['-']
        return args

    def run(self, record, message, artifacts, timeout, schema=None):
        command = self.command(record, artifacts, schema)
        remote_id = record.get('remote_id')
        status = 'failed'
        error = None
        with (artifacts / 'events.jsonl').open('wb') as events, (artifacts / 'stderr.log').open('wb') as stderr:
            try:
                environment = dict(os.environ, AGENT_ENTRY_WORKER='1')
                process = subprocess.Popen(command, cwd=record['cwd'], stdin=subprocess.PIPE,
                                           stdout=events, stderr=stderr, start_new_session=True,
                                           env=environment)
            except OSError as exc:
                return Result('failed', remote_id, b'', 'Cannot start Codex: ' + str(exc))
            try:
                process.communicate(message.encode('utf-8'), timeout=timeout)
                status = 'success' if process.returncode == 0 else 'failed'
                if process.returncode != 0:
                    error = 'Codex exited with code %s; inspect stderr.log and events.jsonl.' % process.returncode
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                status = 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'interrupted'
                error = 'Worker %s; partial filesystem changes may already exist.' % status
                self.stop(process)
        completed = False
        protocol_error = None
        try:
            with (artifacts / 'events.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    kind = event.get('type')
                    if kind == 'thread.started':
                        candidate = event.get('thread_id')
                        if not isinstance(candidate, str) or not candidate:
                            raise ValueError('Missing backend thread ID.')
                        if remote_id and candidate != remote_id:
                            raise ValueError('Backend resumed a different thread.')
                        remote_id = candidate
                    elif kind == 'turn.completed':
                        completed = True
                    elif kind in ('turn.failed', 'error'):
                        protocol_error = 'Backend reported %s; inspect events.jsonl.' % kind
        except (ValueError, UnicodeError, AttributeError) as exc:
            protocol_error = 'Invalid Codex event stream: ' + str(exc)
        final_path = artifacts / 'final.txt'
        reply = final_path.read_bytes() if final_path.is_file() else b''
        if status == 'success':
            if protocol_error or not completed or not remote_id or not reply:
                status = 'failed'
                error = protocol_error or 'Incomplete turn: missing completion, thread ID or final message.'
            else:
                try:
                    reply.decode('utf-8')
                except UnicodeError:
                    status, error = 'failed', 'Final reply is not UTF-8.'
        return Result(status, remote_id, reply, error)

    @staticmethod
    def stop(process):
        # Kill the process group, including shell/test subprocesses, after grace.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def adapter_for(name, executable='codex'):
    if name == 'codex':
        return CodexExec(executable)
    raise ValueError('Unsupported backend: ' + name)
