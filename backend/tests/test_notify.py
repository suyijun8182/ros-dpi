import hashlib
import hmac
import json
import time
import urllib.parse

import httpx
from fastapi.testclient import TestClient

from app import audit, notify
from app.engine import engine
from app.main import app
from app.models import Setting
from app import database
from tests.test_audit import _h, flow


class Recorder:
    """替换 notify 里的 httpx.Client，记录请求"""
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, content=None, headers=None, data=None, params=None):
        Recorder.calls.append({"url": str(url), "json": json, "content": content, "headers": headers or {}, "data": data})
        return httpx.Response(200, json={"errcode": 0, "code": 0, "ok": True}, request=httpx.Request("POST", str(url)))


def test_payloads_and_signatures(monkeypatch):
    monkeypatch.setattr(notify.httpx, "Client", Recorder)
    Recorder.calls = []
    cfg = {
        "dingtalk": {"url": "https://oapi.dingtalk.com/robot/send?access_token=x", "secret": "SECabc"},
        "webhook": {"urls": ["https://example.com/hook"], "secret": "s3", "headers": [{"key": "X-A", "value": "1"}],
                    "template": "[{{subject}}] {{text}}", "max_retries": 0},
        "bark": {"urls": ["https://api.day.app/KEY/"], "group": "ROS-DPI", "level": "timeSensitive"},
        "serverchan": {"sendkey": "sctp123tABC"},
    }
    res = notify.send("标题", "正文", wait=True, config={t: {**notify.DEFAULTS[t], **c} for t, c in cfg.items()})
    assert all(r["ok"] for r in res) and len(res) == 4
    by = {c["url"].split("?")[0]: c for c in Recorder.calls}
    d = next(c for c in Recorder.calls if "dingtalk" in c["url"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(d["url"]).query)
    assert "timestamp" in q and "sign" in q and d["json"]["text"]["content"] == "标题\n\n正文"
    w = by["https://example.com/hook"]
    body = json.loads(w["content"])
    assert body["text"] == "[标题] 正文" and w["headers"]["X-A"] == "1"
    assert w["headers"]["X-ROSDPI-Signature"] == hmac.new(b"s3", w["content"], hashlib.sha256).hexdigest()
    assert by["https://api.day.app/KEY"]["json"]["level"] == "timeSensitive"
    assert "https://123.push.ft07.com/send/sctp123tABC.send" in by


def test_legacy_channels_migrate():
    with database.session() as db:
        for k in ("notify_config",):
            row = db.get(Setting, k)
            if row:
                db.delete(row)
        row = db.get(Setting, "notify_channels") or Setting(key="notify_channels")
        row.value = json.dumps([{"type": "telegram", "token": "T", "chat_id": "42", "enabled": True},
                                {"type": "email", "url": "smtp.qq.com:465", "user": "a@qq.com", "token": "pw", "to": "b@x.com"}])
        db.merge(row)
        db.commit()
    cfg = notify.load_config()
    assert cfg["telegram"]["bot_token"] == "T" and cfg["telegram"]["chat_id"] == "42" and cfg["telegram"]["enabled"]
    assert cfg["email"]["host"] == "smtp.qq.com" and cfg["email"]["port"] == 465 and cfg["email"]["password"] == "pw"
    with database.session() as db:
        db.delete(db.get(Setting, "notify_channels"))
        db.commit()


def test_rule_channels_and_quiet_hours(monkeypatch):
    monkeypatch.setattr(notify.httpx, "Client", Recorder)
    Recorder.calls = []
    now = time.time()
    mac = "AA:00:00:00:0D:01"
    engine.dns.add("store.steampowered.com", [("203.0.113.101", 600)], [])
    with TestClient(app) as c:
        h = _h(c)
        c.put("/api/audit/notify", json={"config": {
            "wecom": {"enabled": True, "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=W"},
            "slack": {"enabled": True, "url": "https://hooks.slack.com/services/S"}},
            "quiet_from": "00:00", "quiet_to": "23:59"}, headers=h)
        assert c.post("/api/audit/rules", json={"name": "x", "kind": "new_host", "channels": ["nope"]}, headers=h).status_code == 400
        c.post("/api/audit/rules", json={"name": "只推 Slack", "kind": "app", "value": "steam", "channels": ["slack"]}, headers=h)
        audit.auditor.reload()
        monkeypatch.setattr(notify, "in_quiet", lambda ts=None: True)
        flow("192.168.88.101", "203.0.113.101", 7201, 3000, mac, now)
        engine.flush(now)
        ev = next(e for e in c.get("/api/audit/events?range=today", headers=h).json()["rows"]
                  if e["host"] == mac and e["rule"] == "只推 Slack")
        assert ev["notified"] == 2 and not Recorder.calls  # 免打扰：先记下
        monkeypatch.setattr(notify, "in_quiet", lambda ts=None: False)
        audit.auditor.flush_deferred()
        for _ in range(40):
            if Recorder.calls:
                break
            time.sleep(0.05)
        time.sleep(0.2)
        mine = [x for x in Recorder.calls if "只推 Slack" in json.dumps(x["json"], ensure_ascii=False)]
        assert {x["url"] for x in mine} == {"https://hooks.slack.com/services/S"}  # 只推规则选的渠道
        assert "免打扰" in mine[0]["json"]["text"]
        c.put("/api/audit/notify", json={"config": {"wecom": {"enabled": False}, "slack": {"enabled": False}},
                                         "quiet_from": "", "quiet_to": ""}, headers=h)


class Recorder2(Recorder):
    """在 Recorder 的基础上支持 GET，并按地址返回各家 API 的成功应答"""
    def post(self, url, json=None, content=None, headers=None, data=None, params=None):
        Recorder.calls.append({"url": str(url), "json": json, "content": content, "headers": headers or {}, "data": data, "params": params})
        body = {"errcode": 0, "code": 0, "ok": True}
        if "tenant_access_token" in str(url):
            body = {"code": 0, "tenant_access_token": "FT"}
        elif "getAppAccessToken" in str(url):
            body = {"access_token": "QT"}
        elif "pushplus" in str(url):
            body = {"code": 200}
        return httpx.Response(200, json=body, request=httpx.Request("POST", str(url)))

    def get(self, url, params=None):
        Recorder.calls.append({"url": str(url), "params": params})
        body = {"errcode": 0, "access_token": "WT", "expires_in": 7200} if "gettoken" in str(url) else \
            {"errcode": 0, "agentid": 1000002, "name": "ROS-DPI", "allow_userinfos": {"user": [{"userid": "a"}]}}
        return httpx.Response(200, json=body, request=httpx.Request("GET", str(url)))


def test_easysub_channels(monkeypatch):
    """照搬 EasySub 的渠道：飞书应用机器人、QQ 机器人、企业微信自建应用、Pushplus 渠道、Bark 图标"""
    monkeypatch.setattr(notify.httpx, "Client", Recorder2)
    notify._WECOM_TOKENS.clear()
    Recorder.calls = []
    cfg = {
        "feishu": {"app_id": "cli_1", "app_secret": "S", "chat_ids": "oc_a，oc_b"},
        "qq": {"app_id": "1", "app_secret": "S", "group_ids": "G1", "user_ids": ""},
        "wecom": {"mode": "app", "corp_id": "ww1", "agent_id": "1000002", "secret": "S", "to_user": "", "msg_type": "textcard"},
        "pushplus": {"token": "P", "channel": "mail"},
        "bark": {"urls": ["https://api.day.app/K"], "icon": "https://x/i.png"},
    }
    res = notify.send("标题", "正文", wait=True, config={t: {**notify.DEFAULTS[t], **c} for t, c in cfg.items()})
    assert [r for r in res if not r["ok"]] == [] and len(res) == 5
    urls = [c["url"] for c in Recorder.calls]
    assert sum("im/v1/messages" in u for u in urls) == 2                       # 两个飞书群
    assert any(u.endswith("/v2/groups/G1/messages") for u in urls)
    send = next(c for c in Recorder.calls if c["url"].endswith("/cgi-bin/message/send"))
    assert send["params"] == {"access_token": "WT"} and send["json"]["touser"] == "@all"
    assert send["json"]["msgtype"] == "textcard" and send["json"]["agentid"] == 1000002
    assert next(c for c in Recorder.calls if "pushplus" in c["url"])["json"]["channel"] == "mail"
    assert next(c for c in Recorder.calls if "day.app" in c["url"])["json"]["icon"] == "https://x/i.png"
    # token 缓存：再发一次不会再调 gettoken
    n = sum("gettoken" in c["url"] for c in Recorder.calls)
    notify.send("x", "y", wait=True, config={"wecom": {**notify.DEFAULTS["wecom"], **cfg["wecom"]}})
    assert sum("gettoken" in c["url"] for c in Recorder.calls) == n
    assert notify.wecom_agent_info({**notify.DEFAULTS["wecom"], **cfg["wecom"]})["users"] == 1
    # 必填项随模式变化
    assert notify.missing("wecom", {**notify.DEFAULTS["wecom"], "mode": "app"}) == ["corp_id", "agent_id", "secret"]
    assert notify.missing("wecom", dict(notify.DEFAULTS["wecom"])) == ["url"]
    assert notify.missing("qq", {"app_id": "1", "app_secret": "s"}) == ["group_ids / user_ids"]


def test_old_field_names_migrate():
    """0.6.x 存的 email.security / from_addr、webhook.retries 读出来改成 EasySub 的字段"""
    with database.session() as db:
        row = db.get(Setting, "notify_config") or Setting(key="notify_config")
        old = row.value
        row.value = json.dumps({"email": {"enabled": True, "host": "smtp.x", "security": "starttls", "from_addr": "a@x", "to": "b@x"},
                                "webhook": {"urls": ["https://h"], "retries": 1}})
        db.merge(row)
        db.commit()
    try:
        cfg = notify.load_config()
        assert cfg["email"]["ssl"] is False and cfg["email"]["from"] == "a@x" and "security" not in cfg["email"]
        assert cfg["webhook"]["max_retries"] == 1 and "retries" not in cfg["webhook"]
        assert list(cfg) == list(notify.DEFAULTS)[:] and list(cfg)[0] == "telegram"
    finally:
        with database.session() as db:
            row = db.get(Setting, "notify_config")
            if old is None:
                db.delete(row)
            else:
                row.value = old
            db.commit()


def test_notify_api_bool_and_helpers(monkeypatch):
    monkeypatch.setattr(notify.httpx, "Client", Recorder2)
    notify._WECOM_TOKENS.clear()
    with TestClient(app) as c:
        h = _h(c)
        r = c.put("/api/audit/notify", json={"config": {"email": {"enabled": False, "host": "smtp.x", "ssl": False, "to": "a@x"}}}, headers=h)
        assert r.status_code == 200 and r.json()["config"]["email"]["ssl"] is False
        r = c.post("/api/audit/notify/wecom/check", json={"channel": "wecom", "config": {"mode": "app", "corp_id": "ww", "agent_id": "1000002", "secret": "S"}}, headers=h)
        assert r.status_code == 200 and r.json()["agent"]["name"] == "ROS-DPI"
        assert c.post("/api/audit/notify/wecom/check", json={"channel": "wecom", "config": {"mode": "webhook"}}, headers=h).status_code == 400
        assert c.post("/api/audit/notify/telegram/nope", json={"channel": "telegram"}, headers=h).status_code == 404
