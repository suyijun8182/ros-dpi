"""Serial background jobs for historical rule reclassification."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app import database, oplog, reclass

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rule-reclass")
_lock = threading.Lock()
_latest = 0
_state = {"status": "done", "finished": None, "bytes_moved": 0}


def status():
    with _lock:
        return dict(_state)


def queue(items, user: str):
    global _latest
    items = tuple(items)
    with _lock:
        _latest += 1
        job = _latest
        _state.update(status="running", finished=None, bytes_moved=0, error=None)

    def work():
        from app.engine import engine
        result, error = {}, None
        try:
            with database.session() as db:
                result = reclass.reclassify_rules(engine, db, items)
                oplog.log(db, None, user, "rule_reclass", {"rules": len(items), **result})
        except Exception as exc:
            error = str(exc)[:200]
            logging.exception("Rule reclassification failed")
            try:
                with database.session() as db:
                    oplog.log(db, None, user, "rule_reclass", {"rules": len(items), "error": error}, ok=False)
            except Exception:
                logging.exception("Could not record rule reclassification failure")
        finally:
            with _lock:
                if job == _latest:
                    _state.update(status="error" if error is not None else "done", finished=time.time(),
                                  bytes_moved=result.get("bytes_moved", 0), error=error)
        return result

    return _pool.submit(work)
