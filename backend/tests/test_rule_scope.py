import pytest
from sqlalchemy import create_engine, inspect, or_, select
from sqlalchemy.orm import Session

from app import database, reclass, stats
from app.models import HostDomainDay


@pytest.mark.parametrize("pattern,indexed", [("example.com", True), ("a.example.com", True), ("com.cn", False)])
def test_scope_preserves_matches(pattern, indexed):
    eng = create_engine("sqlite://")
    HostDomainDay.__table__.create(eng)
    with Session(eng) as db:
        domains = ["example.com", "a.example.com", "b.a.example.com", "other.com", "a.com.cn", "b.a.com.cn"]
        for dom in domains:
            db.add(HostDomainDay(ts=1, host="test", domain=dom, app="https", base=stats.base_domain(dom), bytes=1))
        db.commit()
        where, _ = reclass.rule_scope("domain", pattern)
        q = select(HostDomainDay.domain).where(*where)
        assert ("host_domain_day.base =" in str(q)) == indexed
        old = select(HostDomainDay.domain).where(or_(HostDomainDay.domain == pattern,
                                                   HostDomainDay.domain.like("%." + pattern)))
        assert set(db.scalars(q)) == set(db.scalars(old))


def test_existing_database_adds_index(monkeypatch):
    eng = create_engine("sqlite://")
    database.Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP INDEX ix_hdd_base_ts")
    monkeypatch.setattr(database, "engine", eng)
    database.add_missing_columns()
    assert "ix_hdd_base_ts" in {i["name"] for i in inspect(eng).get_indexes("host_domain_day")}
