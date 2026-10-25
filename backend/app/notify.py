"""通知渠道（照搬 EasySub：14 种渠道、字段名、发送实现都和 EasySub 一致，磁贴选择、可用未保存的配置测试）。

配置保存在 settings 表 notify_config：{渠道: {enabled, ...字段}}；免打扰在 notify_prefs：{quiet_from, quiet_to}。
返回给前端时密钥类字段只显示开头并以“…”结尾，保存时以“…”结尾的值表示沿用原值。
"""
import base64
import hashlib
import hmac
import json
import re
import smtplib
import ssl
import threading
import time
import urllib.parse
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import httpx

from app import database
from app.models import Setting

APP_NAME = "ROS-DPI"

# 渠道与字段同 EasySub（顺序即磁贴顺序）
DEFAULTS: dict[str, dict] = {
    "telegram": {"bot_token": "", "chat_id": "", "admin_id": "", "api_base": "", "proxy": ""},
    "feishu": {"app_id": "", "app_secret": "", "chat_ids": ""},
    "qq": {"app_id": "", "app_secret": "", "group_ids": "", "user_ids": ""},
    "bark": {"urls": [], "group": APP_NAME, "level": "active", "icon": ""},
    "email": {"host": "", "port": 465, "ssl": True, "username": "", "password": "", "from": "", "to": ""},
    "pushplus": {"token": "", "topic": "", "channel": "wechat"},
    "serverchan": {"sendkey": ""},
    # 企业微信：mode=webhook 群机器人；mode=app 自建应用（企业ID + 应用ID + Secret，可走 API 代理）
    "wecom": {"mode": "webhook", "url": "", "corp_id": "", "agent_id": "", "secret": "", "proxy_base": "",
              "to_user": "@all", "to_party": "", "to_tag": "", "msg_type": "text", "card_url": ""},
    "dingtalk": {"url": "", "secret": ""},
    "discord": {"url": ""},
    "slack": {"url": ""},
    "ntfy": {"server": "https://ntfy.sh", "topic": "", "token": ""},
    "gotify": {"server": "", "token": "", "priority": 5},
    "webhook": {"urls": [], "secret": "", "headers": [], "template": "", "timeout_ms": 5000, "max_retries": 3},
}
CHANNEL_TYPES = tuple(DEFAULTS)
SECRET = {"url", "urls", "secret", "bot_token", "password", "token", "sendkey", "app_secret", "proxy"}
# 改了这些“发往哪里”的字段时，被遮住的密钥不能沿用旧值——否则把地址改成自己的服务器就能套出已保存的密钥
ADDRESS = {"api_base", "server", "host", "proxy_base", "proxy"}
REQUIRED = {"telegram": ["bot_token", "chat_id"], "feishu": ["app_id", "app_secret", "chat_ids"],
            "qq": ["app_id", "app_secret"], "bark": ["urls"], "email": ["host", "to"], "pushplus": ["token"],
            "serverchan": ["sendkey"], "dingtalk": ["url"], "discord": ["url"], "slack": ["url"],
            "ntfy": ["topic"], "gotify": ["server", "token"], "webhook": ["urls"]}
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


def _migrate(t: str, c: dict) -> dict:
    """0.5.x / 0.6.x 的字段名改成 EasySub 的"""
    c = dict(c)
    if t == "email":
        if "security" in c:
            c.setdefault("ssl", c.pop("security") == "ssl")
        if "from_addr" in c:
            c.setdefault("from", c.pop("from_addr"))
    elif t == "webhook" and "retries" in c:
        c.setdefault("max_retries", c.pop("retries"))
    elif t == "telegram" and c.get("api_base") == "https://api.telegram.org":
        c["api_base"] = ""
    return c


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
            elif t in ("bark", "webhook"):
                cfg[t] = {"urls": [c.get("url", "")]}
            elif t == "email":
                host, _, port = (c.get("url") or "").partition(":")
                cfg[t] = {"host": host, "port": int(port or 465), "ssl": c.get("security", "ssl") == "ssl",
                          "username": c.get("user", ""), "password": c.get("token", ""), "to": c.get("to", "")}
            elif t != "feishu":   # 飞书改成应用机器人，旧的群机器人地址用不上
                cfg[t] = {"url": c.get("url", "")}
            if t in cfg:
                cfg[t]["enabled"] = c.get("enabled", True)
    out = {}
    for t, d in DEFAULTS.items():
        saved = _migrate(t, cfg.get(t) or {})
        out[t] = {"enabled": bool(saved.get("enabled")), **d, **{k: v for k, v in saved.items() if k in d}}
    return out


def enabled_types() -> list[str]:
    return [t for t, c in load_config().items() if c.get("enabled") and missing(t, c) == []]


def missing(t: str, c: dict) -> list[str]:
    def empty(v):
        return not v or v == [] or v == [""]
    if t == "wecom":
        need = ["corp_id", "agent_id", "secret"] if c.get("mode") == "app" else ["url"]
    else:
        need = REQUIRED[t]
    out = [f for f in need if empty(c.get(f))]
    if t == "qq" and not out and empty(c.get("group_ids")) and empty(c.get("user_ids")):
        out.append("group_ids / user_ids")
    return out


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
    def mh(v):
        # webhook 自定义请求头的值常带 Authorization: Bearer …
        return [{**h, "value": m(h.get("value") or "") if len(h.get("value") or "") > 12 else
                 ("…" if h.get("value") else "")} if isinstance(h, dict) else h for h in (v or [])]
    return {t: {k: (m(v) if k in SECRET else mh(v) if k == "headers" else v) for k, v in c.items()}
            for t, c in cfg.items()}


def unmask(new: dict, old: dict) -> dict:
    """以“…”结尾的值（列表按位置）沿用原值；发送地址改了时不沿用（要求重新填写密钥）"""
    out = dict(new)
    masked = any((isinstance(new.get(k), str) and new[k].endswith("…")) or
                 (isinstance(new.get(k), list) and any(isinstance(x, str) and x.endswith("…") for x in new[k]))
                 for k in SECRET)
    if masked and any(str(new.get(k) or "").rstrip("…") != str(old.get(k) or "")[:len(str(new.get(k) or "").rstrip("…"))]
                      for k in ADDRESS if k in new and not str(new.get(k) or "").endswith("…")):
        raise ValueError("改了发送地址，请重新填写密钥 / 令牌")
    if isinstance(new.get("headers"), list):
        oh = old.get("headers") if isinstance(old.get("headers"), list) else []
        out["headers"] = [{**h, "value": oh[i].get("value", "")} if isinstance(h, dict) and str(h.get("value") or "").endswith("…")
                          and i < len(oh) and isinstance(oh[i], dict) else h for i, h in enumerate(new["headers"])]
    for k in SECRET & set(new):
        v, o = new[k], old.get(k)
        if isinstance(v, list):
            ol = o if isinstance(o, list) else []
            out[k] = [ol[i] if isinstance(x, str) and x.endswith("…") and i < len(ol) else x for i, x in enumerate(v)]
        elif isinstance(v, str) and v.endswith("…"):
            out[k] = o or ""
    return out


# ---------------- 发送（各渠道实现同 EasySub，失败抛异常） ----------------

def _split(csv: str) -> list[str]:
    return [x.strip() for x in (csv or "").replace("，", ",").split(",") if x.strip()]


def _body(subject: str, text: str) -> str:
    return f"{subject}\n\n{text}" if subject else text


def _tg_url(conf: dict, method: str) -> str:
    base = (conf.get("api_base") or "https://api.telegram.org").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return f"{base}/bot{conf.get('bot_token')}/{method}"


def _tg_client(conf: dict) -> httpx.Client:
    return httpx.Client(timeout=15, proxy=conf.get("proxy") or None)


def _tg_json(r: httpx.Response) -> dict:
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"HTTP {r.status_code}")
    return data


def _send_telegram(conf: dict, subject: str, text: str) -> None:
    if not conf.get("bot_token") or not conf.get("chat_id"):
        raise RuntimeError("Telegram 未配置 Bot Token 或 Chat ID")
    with _tg_client(conf) as c:
        _tg_json(c.post(_tg_url(conf, "sendMessage"), json={"chat_id": conf["chat_id"], "text": _body(subject, text)}))


def telegram_call(conf: dict, method: str) -> dict:
    """「验证机器人」（getMe）和「获取 Chat ID」（getUpdates）"""
    if not conf.get("bot_token"):
        raise RuntimeError("请先填写 Bot Token")
    with _tg_client(conf) as c:
        return _tg_json(c.get(_tg_url(conf, method)))


def _send_feishu(conf: dict, subject: str, text: str) -> None:
    app_id, secret = conf.get("app_id"), conf.get("app_secret")
    chat_ids = _split(conf.get("chat_ids", ""))
    if not app_id or not secret or not chat_ids:
        raise RuntimeError("飞书未配置 App ID / Secret / Chat IDs")
    with httpx.Client(timeout=15) as c:
        r = c.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                   json={"app_id": app_id, "app_secret": secret})
        r.raise_for_status()
        token = r.json().get("tenant_access_token")
        if not token:
            raise RuntimeError(f"飞书获取 token 失败：{r.text[:200]}")
        for cid in chat_ids:
            data = c.post("https://open.feishu.cn/open-apis/im/v1/messages", params={"receive_id_type": "chat_id"},
                          headers={"Authorization": f"Bearer {token}"},
                          json={"receive_id": cid, "msg_type": "text",
                                "content": json.dumps({"text": _body(subject, text)}, ensure_ascii=False)}).json()
            if data.get("code", 0) != 0:
                raise RuntimeError(f"飞书发送失败（{cid}）：{data.get('msg')}")


def _send_qq(conf: dict, subject: str, text: str) -> None:
    app_id, secret = conf.get("app_id"), conf.get("app_secret")
    groups, users = _split(conf.get("group_ids", "")), _split(conf.get("user_ids", ""))
    if not app_id or not secret:
        raise RuntimeError("QQ 未配置 App ID / Secret")
    if not groups and not users:
        raise RuntimeError("QQ 未填写任何群聊或私聊 OpenID")
    with httpx.Client(timeout=15) as c:
        r = c.post("https://bots.qq.com/app/getAppAccessToken", json={"appId": app_id, "clientSecret": secret})
        r.raise_for_status()
        token = r.json().get("access_token")
        if not token:
            raise RuntimeError(f"QQ 获取 access_token 失败：{r.text[:200]}")
        headers = {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}
        for kind, ids in (("groups", groups), ("users", users)):
            for oid in ids:
                resp = c.post(f"https://api.sgroup.qq.com/v2/{kind}/{oid}/messages", headers=headers,
                              json={"content": _body(subject, text), "msg_type": 0})
                if resp.status_code >= 300:
                    raise RuntimeError(f"QQ {'群' if kind == 'groups' else '用户'} {oid} 发送失败：{resp.text[:200]}")


def _send_bark(conf: dict, subject: str, text: str) -> None:
    urls = [u for u in (conf.get("urls") or []) if u]
    if not urls:
        raise RuntimeError("Bark 未配置任何目标 URL")
    payload = {"title": subject or APP_NAME, "body": text}
    for k in ("group", "level", "icon"):
        if conf.get(k):
            payload[k] = conf[k]
    with httpx.Client(timeout=15) as c:
        for url in urls:
            resp = c.post(url.rstrip("/"), json=payload)
            resp.raise_for_status()
            if resp.json().get("code", 200) not in (200, 0):
                raise RuntimeError(f"Bark 推送失败：{resp.text[:200]}")


def _send_email(conf: dict, subject: str, text: str) -> None:
    host = conf.get("host")
    to_list = [x.strip() for x in re.split(r"[,，;；]", conf.get("to") or "") if x.strip()]
    sender = (conf.get("from") or conf.get("username") or "").strip()
    if not host or not to_list or not sender:
        raise RuntimeError("Email 未配置 SMTP 主机 / 发件人 / 收件人")
    port = int(conf.get("port") or (465 if conf.get("ssl") else 587))
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(subject or f"{APP_NAME} 通知", "utf-8")
    msg["From"] = formataddr((APP_NAME, sender))
    msg["To"] = ", ".join(to_list)
    user, pwd = conf.get("username"), conf.get("password")
    if conf.get("ssl"):
        with smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) as s:
            if user:
                s.login(user, pwd)
            s.sendmail(sender, to_list, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            try:
                s.starttls(context=ssl.create_default_context())
            except smtplib.SMTPException:
                pass
            if user:
                s.login(user, pwd)
            s.sendmail(sender, to_list, msg.as_string())


def _send_pushplus(conf: dict, subject: str, text: str) -> None:
    if not conf.get("token"):
        raise RuntimeError("Pushplus 未配置 Token")
    body = {"token": conf["token"], "title": subject or f"{APP_NAME} 通知", "content": text, "template": "txt"}
    for k in ("topic", "channel"):
        if conf.get(k):
            body[k] = conf[k]
    with httpx.Client(timeout=15) as c:
        resp = c.post("https://www.pushplus.plus/send", json=body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"Pushplus 发送失败：{data.get('msg')}")


def _send_serverchan(conf: dict, subject: str, text: str) -> None:
    key = (conf.get("sendkey") or "").strip()
    if not key:
        raise RuntimeError("Server酱未配置 SendKey")
    m = re.match(r"^sctp(\d+)t", key)  # Server酱³ 的 SendKey 里带 uid
    url = f"https://{m.group(1)}.push.ft07.com/send/{key}.send" if m else f"https://sctapi.ftqq.com/{key}.send"
    with httpx.Client(timeout=15) as c:
        r = c.post(url, data={"title": subject or APP_NAME, "desp": text})
        r.raise_for_status()
        if r.json().get("code", 0) != 0:
            raise RuntimeError(f"Server酱发送失败：{r.text[:200]}")


# ---- 企业微信（群机器人 / 自建应用） ----
WECOM_DEFAULT_BASE = "https://qyapi.weixin.qq.com"
# 自建应用的 access_token 缓存：key -> (token, 过期时间戳)。gettoken 有频率限制，必须复用（有效期 7200s）
_WECOM_TOKENS: dict[str, tuple[str, float]] = {}
_WECOM_TOKEN_ERRS = {40014, 42001, 41001}   # 不合法 / 已过期 / 缺少 access_token：刷新后重试一次


def _trunc_bytes(text: str, limit: int) -> str:
    """按 UTF-8 字节数截断（text 上限 2048B、markdown 4096B、textcard 描述 512B）"""
    raw = (text or "").encode("utf-8")
    if len(raw) <= limit:
        return text or ""
    return raw[: limit - 3].decode("utf-8", "ignore") + "..."


def wecom_api_base(conf: dict) -> str:
    """API 代理地址；留空用官方域名。容忍把 /cgi-bin 一起粘进来"""
    base = (conf.get("proxy_base") or "").strip().rstrip("/")
    if not base:
        return WECOM_DEFAULT_BASE
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return base[: -len("/cgi-bin")] if base.endswith("/cgi-bin") else base


def wecom_token(conf: dict, force: bool = False) -> str:
    corp_id, secret = (conf.get("corp_id") or "").strip(), (conf.get("secret") or "").strip()
    if not corp_id or not secret:
        raise RuntimeError("企业微信自建应用未配置企业ID / 应用Secret")
    base = wecom_api_base(conf)
    key = f"{base}|{corp_id}|{hashlib.sha256(secret.encode()).hexdigest()[:16]}"
    hit = _WECOM_TOKENS.get(key)
    if hit and not force and hit[1] > time.time():
        return hit[0]
    with httpx.Client(timeout=15) as c:
        r = c.get(f"{base}/cgi-bin/gettoken", params={"corpid": corp_id, "corpsecret": secret})
        r.raise_for_status()
        data = r.json()
    token = data.get("access_token")
    if data.get("errcode", 0) != 0 or not token:
        raise RuntimeError(f"企业微信获取 access_token 失败：{data.get('errcode')} {data.get('errmsg')}"
                           "（请检查企业ID / 应用Secret，以及是否已在「企业可信IP」放行服务器出口 IP）")
    _WECOM_TOKENS[key] = (token, time.time() + max(60, int(data.get("expires_in") or 7200) - 200))
    return token


def wecom_agent_info(conf: dict) -> dict:
    """「检查应用」：读取自建应用名与可见范围"""
    agent_id = str(conf.get("agent_id") or "").strip()
    if not agent_id:
        raise RuntimeError("企业微信自建应用未配置应用ID（AgentId）")
    base = wecom_api_base(conf)
    for attempt in (0, 1):
        token = wecom_token(conf, force=bool(attempt))
        with httpx.Client(timeout=15) as c:
            r = c.get(f"{base}/cgi-bin/agent/get", params={"access_token": token, "agentid": agent_id})
            r.raise_for_status()
            data = r.json()
        code = data.get("errcode", 0)
        if code in _WECOM_TOKEN_ERRS and attempt == 0:
            continue
        if code != 0:
            raise RuntimeError(f"企业微信读取应用失败：{code} {data.get('errmsg')}")
        allow = data.get("allow_userinfos") or {}
        return {"agentid": data.get("agentid"), "name": data.get("name"),
                "users": len(allow.get("user") or []),
                "parties": len((data.get("allow_partys") or {}).get("partyid") or []),
                "tags": len((data.get("allow_tags") or {}).get("tagid") or [])}
    raise RuntimeError("企业微信读取应用失败：access_token 反复失效")


def _wecom_payload(conf: dict, subject: str, text: str) -> dict:
    msg_type = (conf.get("msg_type") or "text").strip()
    if msg_type == "markdown":
        return {"msgtype": "markdown", "markdown": {"content": _trunc_bytes(_body(subject, text), 4096)}}
    if msg_type == "textcard":
        return {"msgtype": "textcard", "textcard": {
            "title": _trunc_bytes(subject or APP_NAME, 128), "description": _trunc_bytes(text, 512),
            "url": conf.get("card_url") or "https://github.com/suyijun8182/ros-dpi", "btntxt": "查看详情"}}
    return {"msgtype": "text", "text": {"content": _trunc_bytes(_body(subject, text), 2048)}}


def _send_wecom_robot(conf: dict, subject: str, text: str) -> None:
    url = (conf.get("url") or "").strip()
    if not url:
        raise RuntimeError("企业微信未配置群机器人 Webhook")
    payload = _wecom_payload(conf, subject, text)
    if payload["msgtype"] == "textcard":  # 群机器人不支持 textcard，降级为 text
        payload = {"msgtype": "text", "text": {"content": _trunc_bytes(_body(subject, text), 2048)}}
    with httpx.Client(timeout=15) as c:
        r = c.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"企业微信群机器人发送失败：{data.get('errcode')} {data.get('errmsg')}")


def _send_wecom_app(conf: dict, subject: str, text: str) -> None:
    agent_id = str(conf.get("agent_id") or "").strip()
    if not agent_id:
        raise RuntimeError("企业微信自建应用未配置应用ID（AgentId）")
    to_user, to_party, to_tag = ((conf.get(k) or "").strip() for k in ("to_user", "to_party", "to_tag"))
    if not (to_user or to_party or to_tag):
        to_user = "@all"  # 三者全空则发给应用可见范围内全部成员
    payload = _wecom_payload(conf, subject, text)
    payload.update({"touser": to_user, "toparty": to_party, "totag": to_tag,
                    "agentid": int(agent_id) if agent_id.isdigit() else agent_id,
                    "safe": 0, "enable_duplicate_check": 0})
    base = wecom_api_base(conf)
    for attempt in (0, 1):
        token = wecom_token(conf, force=bool(attempt))
        with httpx.Client(timeout=15) as c:
            r = c.post(f"{base}/cgi-bin/message/send", params={"access_token": token}, json=payload)
            r.raise_for_status()
            data = r.json()
        code = data.get("errcode", 0)
        if code in _WECOM_TOKEN_ERRS and attempt == 0:
            continue
        if code != 0:
            hint = {81013: "（接收人不在应用可见范围内，请到「应用管理→可见范围」添加成员）",
                    60020: "（服务器 IP 未在「企业可信IP」白名单中，或需要配置 API 代理）",
                    301014: "（服务器 IP 未在「企业可信IP」白名单中，或需要配置 API 代理）",
                    40056: "（应用ID AgentId 不正确）"}.get(code, "")
            raise RuntimeError(f"企业微信发送失败：{code} {data.get('errmsg')}{hint}")
        # errcode=0 但接收人被剔除时，消息实际没人收到
        invalid = [v for v in (str(data.get(k) or "").strip("| ") for k in ("invaliduser", "invalidparty", "invalidtag")) if v]
        if invalid:
            raise RuntimeError(f"企业微信部分接收人无效：{' / '.join(invalid)}（请核对成员 UserID，并确认其在应用可见范围内）")
        return


def _send_wecom(conf: dict, subject: str, text: str) -> None:
    (_send_wecom_app if conf.get("mode") == "app" else _send_wecom_robot)(conf, subject, text)


def _send_dingtalk(conf: dict, subject: str, text: str) -> None:
    url = conf.get("url")
    if not url:
        raise RuntimeError("钉钉未配置机器人 Webhook")
    secret = conf.get("secret")
    if secret:
        ts = str(round(time.time() * 1000))
        sign = urllib.parse.quote_plus(base64.b64encode(
            hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()))
        url = f"{url}{'&' if '?' in url else '?'}timestamp={ts}&sign={sign}"
    with httpx.Client(timeout=15) as c:
        r = c.post(url, json={"msgtype": "text", "text": {"content": _body(subject, text)}})
        r.raise_for_status()
        if r.json().get("errcode", 0) != 0:
            raise RuntimeError(f"钉钉发送失败：{r.text[:200]}")


def _send_discord(conf: dict, subject: str, text: str) -> None:
    if not conf.get("url"):
        raise RuntimeError("Discord 未配置 Webhook URL")
    content = f"**{subject}**\n{text}" if subject else text
    with httpx.Client(timeout=15) as c:
        c.post(conf["url"], json={"content": content[:1900]}).raise_for_status()


def _send_slack(conf: dict, subject: str, text: str) -> None:
    if not conf.get("url"):
        raise RuntimeError("Slack 未配置 Webhook URL")
    with httpx.Client(timeout=15) as c:
        c.post(conf["url"], json={"text": f"*{subject}*\n{text}" if subject else text}).raise_for_status()


def _send_ntfy(conf: dict, subject: str, text: str) -> None:
    server = (conf.get("server") or "https://ntfy.sh").rstrip("/")
    if not conf.get("topic"):
        raise RuntimeError("ntfy 未配置 Topic")
    headers = {}
    if conf.get("token"):
        headers["Authorization"] = f"Bearer {conf['token']}"
    with httpx.Client(timeout=15) as c:
        c.post(f"{server}/{conf['topic']}", content=_body(subject, text).encode("utf-8"), headers=headers).raise_for_status()


def _send_gotify(conf: dict, subject: str, text: str) -> None:
    server = (conf.get("server") or "").rstrip("/")
    if not server or not conf.get("token"):
        raise RuntimeError("Gotify 未配置 Server / Token")
    with httpx.Client(timeout=15) as c:
        c.post(f"{server}/message", params={"token": conf["token"]},
               json={"title": subject or APP_NAME, "message": text,
                     "priority": int(conf.get("priority") or 5)}).raise_for_status()


def _render_template(tpl: str, ctx: dict) -> str:
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(ctx.get(m.group(1).strip(), m.group(0))), tpl)


def _send_webhook(conf: dict, subject: str, text: str, event: str = "audit") -> None:
    """POST JSON {text, subject, event, timestamp}；可选模板、HMAC 签名（X-ROSDPI-Signature）、自定义请求头、超时与重试"""
    urls = [u for u in (conf.get("urls") or []) if u]
    if not urls:
        raise RuntimeError("Webhook 未配置任何目标 URL")
    ts = int(time.time())
    ctx = {"text": text, "subject": subject, "event": event, "timestamp": ts}
    rendered = _render_template(conf["template"], ctx) if conf.get("template") else text
    raw = json.dumps({"text": rendered, "subject": subject, "event": event, "timestamp": ts, "source": "ros-dpi"},
                     ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    for h in conf.get("headers") or []:
        k, v = (h.get("key"), h.get("value")) if isinstance(h, dict) else (None, None)
        if k and k.lower() not in ("content-type", "x-rosdpi-signature"):
            headers[k] = v or ""
    if conf.get("secret"):
        headers["X-ROSDPI-Signature"] = hmac.new(conf["secret"].encode(), raw, hashlib.sha256).hexdigest()
    timeout = max(1, int(conf.get("timeout_ms") or 5000)) / 1000
    retries = max(0, min(10, int(conf.get("max_retries") or 0)))
    for url in urls:
        last_err = None
        for _ in range(retries + 1):
            try:
                with httpx.Client(timeout=timeout) as c:
                    c.post(url, content=raw, headers=headers).raise_for_status()
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        if last_err:
            raise RuntimeError(f"Webhook 发送失败（{url}）：{last_err}")


_SENDERS = {"telegram": _send_telegram, "feishu": _send_feishu, "qq": _send_qq, "bark": _send_bark,
            "email": _send_email, "pushplus": _send_pushplus, "serverchan": _send_serverchan, "wecom": _send_wecom,
            "dingtalk": _send_dingtalk, "discord": _send_discord, "slack": _send_slack, "ntfy": _send_ntfy,
            "gotify": _send_gotify, "webhook": _send_webhook}


def send_one(t: str, c: dict, title: str, text: str):
    fn = _SENDERS.get(t)
    if not fn:
        raise RuntimeError(f"未知渠道：{t}")
    fn(c, title, text)


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
                r = {"channel": t, "ok": False, "error": scrub_error(f"{type(e).__name__}: {str(e)[:300]}")[:200]}
            with _lock:
                _last[t] = {**r, "ts": int(time.time())}
            results.append(r)
    if wait:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
    return results


def scrub_error(s: str) -> str:
    """报错里常带完整 URL（Telegram 的 /bot<令牌>/、Server 酱的 /<SendKey>.send、?access_token=…），
    会随接口返回给前端：把这些密钥换成 ***"""
    import re
    s = re.sub(r"/bot[^/\s]+", "/bot***", s)
    s = re.sub(r"(?i)((?:access_)?token|key|secret|sendkey|sign)=[^&\s'\"]+", r"\1=***", s)
    s = re.sub(r"/[A-Za-z0-9_\-]{24,}(?=[./?\s'\"]|$)", "/***", s)
    s = re.sub(r"://[^/@\s]+@", "://***@", s)
    return s


def last_results() -> dict:
    with _lock:
        return dict(_last)
