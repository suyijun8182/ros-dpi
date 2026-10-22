"""通知渠道（参照 EasySub：每种渠道一份配置，磁贴选择、可用未保存的配置测试）。

配置保存在 settings 表 notify_config：{渠道: {enabled, ...字段}}；免打扰在 notify_prefs：{quiet_from, quiet_to}。
返回给前端时密钥类字段只显示开头并以“…”结尾，保存时以“…”结尾的值表示沿用原值。
"""
import base64
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.parse
from datetime import datetime

import httpx

from app import database
from app.models import Setting

DEFAULTS: dict[str, dict] = {
    "wecom": {"url": "", "msg_type": "text"},                                   # 企业微信群机器人
    "dingtalk": {"url": "", "secret": ""},                                      # 钉钉群机器人，secret 为加签密钥
    "feishu": {"url": "", "secret": ""},                                        # 飞书群机器人，secret 为签名校验密钥
    "bark": {"urls": [], "group": "ROS-DPI", "level": "active"},
    "telegram": {"bot_token": "", "chat_id": "", "api_base": "https://api.telegram.org"},
    "email": {"host": "", "port": 465, "security": "ssl", "username": "", "password": "", "from_addr": "", "to": ""},
    "pushplus": {"token": "", "topic": ""},
    "serverchan": {"sendkey": ""},
    "ntfy": {"server": "https://ntfy.sh", "topic": "", "token": ""},
    "gotify": {"server": "", "token": "", "priority": 5},
    "discord": {"url": ""},
    "slack": {"url": ""},
    "webhook": {"urls": [], "secret": "", "headers": [], "template": "", "retries": 2},
}
CHANNEL_TYPES = tuple(DEFAULTS)
SECRET = {"url", "urls", "secret", "bot_token", "password", "token", "sendkey"}
REQUIRED = {"wecom": ["url"], "dingtalk": ["url"], "feishu": ["url"], "bark": ["urls"], "telegram": ["bot_token", "chat_id"],
            "email": ["host", "to"], "pushplus": ["token"], "serverchan": ["sendkey"], "ntfy": ["topic"],
            "gotify": ["server", "token"], "discord": ["url"], "slack": ["url"], "webhook": ["urls"]}
_last: dict[str, dict] = {}   # 渠道 -> 上次发送结果 {ok, error, ts}
_lock = threading.Lock()


def _get(key: str, default):
    if not database.is_configured():
        return default
    with database.session() as db:
        row = db.get(Setting, key)
    try:
        return json.loads(row.value) if row and row.value else default
    except ValueError:
        return default


def load_config() -> dict[str, dict]:
    """各渠道配置（补齐默认字段）。兼容 0.4.0 的通道列表格式 notify_channels"""
    cfg = _get("notify_config", None)
    if cfg is None:
        cfg = {}
        for c in _get("notify_channels", []) or []:
            t = c.get("type")
            if t not in DEFAULTS or t in cfg:
                continue
            if t == "telegram":
                cfg[t] = {"bot_token": c.get("token", ""), "chat_id": c.get("chat_id", "")}
            elif t == "bark":
                cfg[t] = {"urls": [c.get("url", "")]}
            elif t == "webhook":
                cfg[t] = {"urls": [c.get("url", "")]}
            elif t == "email":
                host, _, port = (c.get("url") or "").partition(":")
                cfg[t] = {"host": host, "port": int(port or 465), "security": c.get("security", "ssl"),
                          "username": c.get("user", ""), "password": c.get("token", ""), "to": c.get("to", "")}
            else:
                cfg[t] = {"url": c.get("url", "")}
            cfg[t]["enabled"] = c.get("enabled", True)
    return {t: {"enabled": False, **DEFAULTS[t], **(cfg.get(t) or {})} for t in DEFAULTS}


def enabled_types() -> list[str]:
    return [t for t, c in load_config().items() if c.get("enabled") and missing(t, c) == []]


def missing(t: str, c: dict) -> list[str]:
    return [f for f in REQUIRED[t] if not (c.get(f) and (c[f] != [] and c[f] != [""]))]


def prefs() -> dict:
    return {"quiet_from": "", "quiet_to": "", **(_get("notify_prefs", {}) or {})}


def in_quiet(ts: float | None = None) -> bool:
    p = prefs()
    a, b = p.get("quiet_from"), p.get("quiet_to")
    if not a or not b or a == b:
        return False
    from app.timeutil import tz
    hm = datetime.fromtimestamp(ts or time.time(), tz()).strftime("%H:%M")
    return a <= hm < b if a < b else (hm >= a or hm < b)


def mask(cfg: dict[str, dict]) -> dict[str, dict]:
    def m(v):
        if isinstance(v, list):
            return [m(x) for x in v]
        if isinstance(v, str) and len(v) > 12:
            return v[:12] + "…"
        return v
    return {t: {k: (m(v) if k in SECRET else v) for k, v in c.items()} for t, c in cfg.items()}


def unmask(new: dict, old: dict) -> dict:
    """以“…”结尾的值（列表按位置）沿用原值"""
    out = dict(new)
    for k in SECRET & set(new):
        v, o = new[k], old.get(k)
        if isinstance(v, list):
            ol = o if isinstance(o, list) else []
            out[k] = [ol[i] if isinstance(x, str) and x.endswith("…") and i < len(ol) else x for i, x in enumerate(v)]
        elif isinstance(v, str) and v.endswith("…"):
            out[k] = o or ""
    return out


# ---------------- 发送 ----------------

def _check(r: httpx.Response, ok_codes=(0, 200, None)):
    r.raise_for_status()
    try:
        j = r.json()
    except ValueError:
        return
    if isinstance(j, dict):
        code = j.get("errcode", j.get("code", j.get("StatusCode")))
        if code not in ok_codes:
            raise RuntimeError(str(j.get("errmsg") or j.get("msg") or j.get("message") or j)[:160])


def _sign_dingtalk(url: str, secret: str) -> str:
    ts = str(int(time.time() * 1000))
    sig = base64.b64encode(hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()).decode()
    return f"{url}{'&' if '?' in url else '?'}timestamp={ts}&sign={urllib.parse.quote_plus(sig)}"


def send_one(t: str, c: dict, title: str, text: str):
    body = f"{title}\n{text}"
    with httpx.Client(timeout=15) as h:
        if t == "wecom":
            if c.get("msg_type") == "markdown":
                _check(h.post(c["url"], json={"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{text}"[:4000]}}))
            else:
                _check(h.post(c["url"], json={"msgtype": "text", "text": {"content": body[:2000]}}))
        elif t == "dingtalk":
            url = _sign_dingtalk(c["url"], c["secret"]) if c.get("secret") else c["url"]
            _check(h.post(url, json={"msgtype": "text", "text": {"content": body}}))
        elif t == "feishu":
            p = {"msg_type": "text", "content": {"text": body}}
            if c.get("secret"):
                ts = str(int(time.time()))
                key = f"{ts}\n{c['secret']}".encode()
                p.update(timestamp=ts, sign=base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode())
            _check(h.post(c["url"], json=p))
        elif t == "bark":
            for u in [x for x in c.get("urls") or [] if x]:
                _check(h.post(u.rstrip("/"), json={"title": title, "body": text, "group": c.get("group") or "ROS-DPI",
                                                   "level": c.get("level") or "active"}))
        elif t == "telegram":
            base = (c.get("api_base") or "https://api.telegram.org").rstrip("/")
            r = h.post(f"{base}/bot{c['bot_token']}/sendMessage", json={"chat_id": c["chat_id"], "text": body})
            r.raise_for_status()
            if not r.json().get("ok"):
                raise RuntimeError(r.json().get("description", "Telegram 返回失败"))
        elif t == "email":
            _send_mail(c, title, text)
        elif t == "pushplus":
            p = {"token": c["token"], "title": title, "content": text, "template": "txt"}
            if c.get("topic"):
                p["topic"] = c["topic"]
            _check(h.post("https://www.pushplus.plus/send", json=p), (200,))
        elif t == "serverchan":
            key = c["sendkey"].strip()
            m = re.match(r"^sctp(\d+)t", key)  # Server酱³ 的 SendKey 里带 uid
            url = f"https://{m.group(1)}.push.ft07.com/send/{key}.send" if m else f"https://sctapi.ftqq.com/{key}.send"
            _check(h.post(url, data={"title": title, "desp": text}))
        elif t == "ntfy":
            hd = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Tags": "shield"}
            if c.get("token"):
                hd["Authorization"] = f"Bearer {c['token']}"
            h.post(f"{(c.get('server') or 'https://ntfy.sh').rstrip('/')}/{c['topic']}", content=body.encode(),
                   headers=hd).raise_for_status()
        elif t == "gotify":
            h.post(f"{c['server'].rstrip('/')}/message", params={"token": c["token"]},
                   json={"title": title, "message": text, "priority": int(c.get("priority") or 5)}).raise_for_status()
        elif t == "discord":
            h.post(c["url"], json={"content": body[:1900]}).raise_for_status()
        elif t == "slack":
            h.post(c["url"], json={"text": f"*{title}*\n{text}"}).raise_for_status()
        elif t == "webhook":
            _send_webhook(h, c, title, text)


def _send_mail(c: dict, title: str, text: str):
    import smtplib
    from email.header import Header
    from email.mime.text import MIMEText
    from email.utils import formataddr
    sec = c.get("security") or "ssl"
    port = int(c.get("port") or (465 if sec == "ssl" else 587 if sec == "starttls" else 25))
    sender = (c.get("from_addr") or c.get("username") or "").strip()
    to = [x.strip() for x in (c.get("to") or "").replace("；", ";").replace(",", ";").replace("，", ";").split(";") if x.strip()]
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = formataddr(("ROS-DPI", sender))
    msg["To"] = ", ".join(to)
    cls = smtplib.SMTP_SSL if sec == "ssl" else smtplib.SMTP
    with cls(c["host"], port, timeout=15) as s:
        if sec == "starttls":
            s.starttls()
        if c.get("username") and c.get("password"):
            s.login(c["username"], c["password"])
        s.sendmail(sender, to, msg.as_string())


def _send_webhook(h: httpx.Client, c: dict, title: str, text: str):
    """通用 Webhook：POST JSON {subject, text, event, timestamp}；可选模板替换 text、HMAC 签名、自定义请求头、重试"""
    ts = int(time.time())
    msg = text
    if c.get("template"):
        msg = c["template"].replace("{{text}}", text).replace("{{subject}}", title).replace("{{timestamp}}", str(ts))
    raw = json.dumps({"subject": title, "text": msg, "event": "audit", "timestamp": ts, "source": "ros-dpi"},
                     ensure_ascii=False).encode()
    hd = {"Content-Type": "application/json"}
    for x in c.get("headers") or []:
        k = (x.get("key") or "").strip()
        if k and k.lower() not in ("content-type", "x-rosdpi-signature"):
            hd[k] = x.get("value") or ""
    if c.get("secret"):
        hd["X-ROSDPI-Signature"] = hmac.new(c["secret"].encode(), raw, hashlib.sha256).hexdigest()
    for u in [x for x in c.get("urls") or [] if x]:
        err = None
        for _ in range(int(c.get("retries") or 0) + 1):
            try:
                h.post(u, content=raw, headers=hd).raise_for_status()
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(1)
        if err:
            raise err


def send(title: str, text: str, types: list[str] | None = None, wait: bool = False, config: dict | None = None) -> list[dict]:
    """推送到已启用的渠道（types 给了就只发这些）。返回 [{channel, ok, error}]（wait=False 时为空）"""
    cfg = config or load_config()
    todo = [t for t in (types or CHANNEL_TYPES) if t in cfg and (config or cfg[t].get("enabled")) and not missing(t, cfg[t])]
    results: list[dict] = []

    def run():
        for t in todo:
            try:
                send_one(t, cfg[t], title, text)
                r = {"channel": t, "ok": True, "error": ""}
            except Exception as e:  # noqa: BLE001
                r = {"channel": t, "ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            with _lock:
                _last[t] = {**r, "ts": int(time.time())}
            results.append(r)
    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
    return results


def last_results() -> dict:
    with _lock:
        return dict(_last)
