"""0.7.0 会话级站点过滤：ORM 查询自动加 site 条件，新对象自动填站点"""
from sqlalchemy import delete, func, select, update

from app import database
from app.models import Host, Person, TrafficDay
from app.scoping import set_site


def _seed():
    with database.session() as db:
        db.execute(delete(TrafficDay).where(TrafficDay.ts == 7))
        db.execute(delete(Host).where(Host.key.like("SC:%")))
        for site, up in (("default", 1), ("office", 10), ("lab", 100)):
            db.add(TrafficDay(site=site, ts=7, host="SC:H", app="a", up=up, down=0, flows=1))
            db.add(Host(site=site, key="SC:H", ip="192.168.88.7"))
        db.commit()


def test_queries_follow_session_site():
    _seed()
    for site, want in (("office", 10), ("default", 1), ("lab", 100), ("office", 10)):   # 顺序交替：lambda 缓存不能串
        with database.session() as db:
            set_site(db, site)
            assert db.scalar(select(func.sum(TrafficDay.up)).where(TrafficDay.ts == 7)) == want
            assert db.execute(select(TrafficDay.up).where(TrafficDay.ts == 7)).scalars().all() == [want]
            assert [h.site for h in db.scalars(select(Host).where(Host.key == "SC:H"))] == [site]
    with database.session() as db:       # 没设站点：不过滤
        assert db.scalar(select(func.sum(TrafficDay.up)).where(TrafficDay.ts == 7)) == 111
        set_site(db, "office")
        assert db.scalar(select(func.sum(TrafficDay.up)).where(TrafficDay.ts == 7),
                         execution_options={"all_sites": True}) == 111


def test_update_delete_and_insert_scoped():
    _seed()
    with database.session() as db:
        set_site(db, "office")
        db.execute(update(Host).where(Host.key == "SC:H").values(alias="x"))
        db.execute(delete(TrafficDay).where(TrafficDay.ts == 7))
        p = Person(name="张三")
        db.add(p)
        db.commit()
        pid = p.id
    with database.session() as db:
        assert {h.site: h.alias for h in db.scalars(select(Host).where(Host.key == "SC:H"))} == \
            {"default": None, "office": "x", "lab": None}
        assert sorted(db.execute(select(TrafficDay.site).where(TrafficDay.ts == 7)).scalars()) == ["default", "lab"]
        assert db.get(Person, pid).site == "office"
        db.execute(delete(Person).where(Person.id == pid))
        db.commit()


def test_get_by_id_respects_site():
    """Person / Department 用自增 id 做主键：另一个站点的 id 用 db.get 也拿不到"""
    with database.session() as db:
        set_site(db, "office")
        p = Person(name="李四")
        db.add(p)
        db.commit()
        pid = p.id
    with database.session() as db:
        set_site(db, "default")
        assert db.get(Person, pid) is None
    with database.session() as db:
        set_site(db, "office")
        assert db.get(Person, pid) is not None
        db.execute(delete(Person).where(Person.id == pid))
        db.commit()
