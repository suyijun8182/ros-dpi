from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import database, reclass
from app.models import Setting


def test_retry_replays_all_groups_after_transaction_rollback(monkeypatch):
    eng = create_engine("sqlite://")
    database.Base.metadata.create_all(eng)
    calls = []

    def scan(engine, db, *args):
        calls.append(1)
        if len(calls) == 2:
            raise OperationalError("scan", {}, Exception("database is locked"))
        key = "first" if args[2][0].right.value == "old-a" else "second"
        db.add(Setting(key=key, value="reclassified"))
        db.flush()
        return dict(bytes_moved=1, rows_moved=1, scanned=1)

    monkeypatch.setattr(reclass, "_reclassify_once", scan)
    monkeypatch.setattr(reclass.time, "sleep", lambda seconds: None)
    with Session(eng) as db:
        result = reclass.reclassify_rules(None, db, [("domain", "example.com", "old-a"),
                                                   ("domain", "other.com", "old-b")])
        db.commit()
        assert db.get(Setting, "first") is not None
        assert db.get(Setting, "second") is not None
        assert len(calls) == 4 and result["bytes_moved"] == 2
