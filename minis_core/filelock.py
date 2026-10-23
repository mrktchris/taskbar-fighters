"""A small cross-process lock for read-modify-write of one JSON file (ux.json, collection.json): an O_EXCL lock file next to
it, taken with a short retry, a stale one (its holder died) reclaimed after STALE_S.  Two fighter processes and the CLI
share these files; without it, two writers that read the same version silently drop each other's change."""
from __future__ import annotations
import os, time, uuid
from contextlib import contextmanager
from pathlib import Path

STALE_S = 5.0


@contextmanager
def locked(path, timeout=1.0, retry_s=0.01):
    """`with locked(p) as ok:` - ok is True while this process holds p's lock, False when it could not be taken in
    `timeout` seconds (the caller leaves its state dirty and tries again later)."""
    lock = Path(path).with_name(Path(path).name + '.lock')
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            token = f'{os.getpid()}:{uuid.uuid4().hex}'.encode()     # who holds it: only this holder may delete it
            os.write(fd, token)
        except (FileExistsError, PermissionError):
            # PermissionError: on Windows a lock file that its holder just unlinked stays "delete pending" while anyone
            # still has a handle on it (a waiter's stat() below is enough), and O_EXCL on it fails with ACCESS_DENIED
            # instead of EEXIST.  It is the same "someone holds / just released it" as EEXIST: retry until the deadline.
            # (A directory we genuinely cannot write also lands here and gives up at the deadline, as before.)
            try:
                if time.time() - lock.stat().st_mtime > STALE_S:
                    lock.unlink()                         # its holder is gone: reclaim (a second reclaimer loses the O_EXCL race)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(retry_s)
        except OSError:
            yield False
            return
    try:
        yield True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        _release(lock, token)


def _release(lock, token):
    """Delete the lock only while it still carries this holder's token.  A holder that stalled past STALE_S has had its
    lock reclaimed by another process; deleting that newer lock would let a third writer in beside the second."""
    try:
        if lock.read_bytes() != token:
            return
        lock.unlink()
    except OSError:
        pass
