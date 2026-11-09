"""Private, atomic session records with a state-wide execution lock."""
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path


class BusyError(RuntimeError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def locked(self):
        # macOS/Linux: the OS releases this lock even after a process crash.
        import fcntl
        fd = os.open(str(self.root / '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, 'w') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BusyError('Another worker is active in this state directory.') from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def path(self, session_id):
        # Validate before building paths from CLI or backend data.
        if str(uuid.UUID(session_id)) != session_id:
            raise ValueError('Invalid local session ID.')
        return self.root / session_id / 'session.json'

    def save(self, record):
        path = self.path(record['id'])
        path.parent.mkdir(mode=0o700, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(str(temporary), str(path))

    def get(self, session_id):
        return json.loads(self.path(session_id).read_text(encoding='utf-8'))

    def records(self):
        return [json.loads(p.read_text(encoding='utf-8'))
                for p in sorted(self.root.glob('*/session.json'))]

    def run_dir(self, session_id):
        root = self.path(session_id).parent / 'runs'
        root.mkdir(mode=0o700, exist_ok=True)
        path = root / str(uuid.uuid4())
        path.mkdir(mode=0o700)
        return path
