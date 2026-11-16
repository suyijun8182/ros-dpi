"""抓包采样（0.6.29）：把 TZSP 镜像包原样存成 pcap，同时记下 ROS-DPI 对每条连接的识别结果。

用途是离线对照：拿 nDPI（scripts/ndpi_eval.py）等工具分析同一份 pcap，看 ROS-DPI 认不出来的连接，
按包内容能不能认出来、认成什么。这一步不改变任何统计。

- 只有管理员能开、能下载；单次最长 30 分钟、最大 200MB，到了自动停；文件 48 小时后自动删除。
- pcap 里是每条连接开头的几个包（取决于 RouterOS 的嗅探规则），可能含明文 HTTP 内容，下载后注意保管。
- 识别结果来自实时连接表，每 20 秒取一次快照合并（连接空闲 5 分钟会被移出实时表，只在结束时取会漏）。
"""
import csv
import json
import os
import re
import struct
import threading
import time

MAX_MINUTES = 30
MAX_BYTES = 200 * 1024 * 1024
KEEP_SECONDS = 48 * 3600
SNAP_EVERY = 20
_NAME_RE = re.compile(r"^capture-\d{8}-\d{6}$")
LABEL_FIELDS = ("client_ip", "client_port", "remote_ip", "remote_port", "proto", "app", "domain", "source", "up", "down",
                "category", "vague")


def capture_dir() -> str:
    return os.path.join(os.environ.get("DATA_DIR", "data"), "captures")


class Capture:
    def __init__(self):
        self._lock = threading.Lock()
        self._snap_lock = threading.Lock()   # 快照合并和结束时写识别结果互斥（收包线程可能同时在取快照）
        self.active = False
        self._f = None
        self._timer: threading.Timer | None = None
        self.name: str | None = None
        self.started = 0.0
        self.deadline = 0.0
        self.packets = 0
        self.size = 0
        self.last: dict | None = None    # 上一次采样的结果（停止后显示）
        self._labels: dict[tuple, list] = {}
        self._next_snap = 0.0
        self._engine = None
        self.user: str | None = None

    # ---------- 开始 / 停止 ----------
    def start(self, engine, minutes: int, user: str | None = None) -> dict:
        minutes = max(1, min(int(minutes), MAX_MINUTES))
        os.makedirs(capture_dir(), exist_ok=True)
        cleanup()
        with self._lock:
            if self.active:
                raise RuntimeError("已经在采样中")
            now = time.time()
            self.name = time.strftime("capture-%Y%m%d-%H%M%S", time.localtime(now))
            f = open(os.path.join(capture_dir(), self.name + ".pcap"), "wb")
            # pcap 全局头：微秒时间戳，snaplen 65535，链路类型 1（以太网）
            f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
            self._f, self._engine = f, engine
            self.started, self.deadline = now, now + minutes * 60
            self.packets, self.size = 0, 24
            self._labels, self._next_snap = {}, 0.0
            self.user = user
            self.active = True
            self._timer = threading.Timer(minutes * 60 + 1, self.stop)
            self._timer.daemon = True
            self._timer.start()
        return self.status()

    def stop(self) -> dict:
        with self._lock:
            if not self.active:
                return self.status()
            self.active = False
            f, self._f = self._f, None
            if self._timer:
                self._timer.cancel()
        f.close()
        self._snapshot()
        path = os.path.join(capture_dir(), self.name)
        eng = self._engine
        with self._snap_lock, open(path + ".labels.csv", "w", newline="", encoding="utf-8") as out:
            w = csv.writer(out)
            w.writerow(LABEL_FIELDS)
            for k, v in self._labels.items():
                w.writerow((*k, *v, *_judge(eng, v[0])))
        meta = {"name": self.name, "started": int(self.started), "ended": int(time.time()), "packets": self.packets,
                "bytes": self.size, "connections": len(self._labels), "by": self.user,
                "lan": [str(n) for n in (eng.lan_nets + eng.auto_nets)] if eng else []}
        with open(path + ".json", "w", encoding="utf-8") as out:
            json.dump(meta, out, ensure_ascii=False)
        self.last = meta
        self._labels, self._engine = {}, None
        return self.status()

    # ---------- 收包（采集线程调用） ----------
    def write(self, frame: bytes):
        now = time.time()
        stop = snap = False
        with self._lock:
            if not self.active or self._f is None:
                return
            if now >= self.deadline or self.size + 16 + len(frame) > MAX_BYTES:
                stop = True
            else:
                sec = int(now)
                self._f.write(struct.pack("<IIII", sec, int((now - sec) * 1e6), len(frame), len(frame)))
                self._f.write(frame)
                self.packets += 1
                self.size += 16 + len(frame)
                if now >= self._next_snap:
                    self._next_snap = now + SNAP_EVERY
                    snap = True
        if stop:
            self.stop()
        elif snap:
            self._snapshot()

    def _snapshot(self):
        """把实时连接表里每条连接的识别结果并进来（同一连接取最新的应用、最大的字节数）"""
        eng = self._engine
        if eng is None:
            return
        with eng.lock:
            rows = [((s[0], hport, remote, rport, proto), s[1], s[2] or "", s[3] or "", s[4], s[5])
                    for (_key, remote, rport, proto, hport), s in eng.sessions.items()]
        with self._snap_lock:
            self._merge(rows)

    def _merge(self, rows):
        for k, app, dom, src, up, down in rows:
            old = self._labels.get(k)
            if old is None:
                self._labels[k] = [app, dom, src, up, down]
            else:
                old[0] = app
                old[1] = dom or old[1]
                old[2] = src or old[2]
                old[3], old[4] = max(old[3], up), max(old[4], down)

    def status(self) -> dict:
        now = time.time()
        return {"active": self.active, "name": self.name if self.active else None,
                "started": int(self.started) if self.active else None,
                "remaining": max(0, int(self.deadline - now)) if self.active else 0,
                "packets": self.packets if self.active else 0, "bytes": self.size if self.active else 0,
                "last": self.last}


def _judge(eng, app: str) -> tuple[str, int]:
    """(小类, 是否笼统)：笼统 = HTTPS / 国内网络 / 未识别这类没说出具体应用的，和重算、识别校验同一口径"""
    if eng is None:
        return "", 0
    from app.reclass import _vague
    try:
        return eng.classifier.app_info(app).category, int(_vague(eng.classifier, app))
    except Exception:
        return "", 1


capture = Capture()


# ---------- 文件 ----------
def files() -> list[dict]:
    cleanup()
    d = capture_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d), reverse=True):
        if not fn.endswith(".json"):
            continue
        name = fn[:-5]
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        if capture.active and name == capture.name:
            continue
        out.append(meta)
    return out


def path_of(name: str, kind: str) -> str | None:
    """下载 / 删除前校验名字，防路径穿越"""
    if not _NAME_RE.match(name) or kind not in ("pcap", "labels.csv", "json"):
        return None
    p = os.path.join(capture_dir(), f"{name}.{kind}")
    return p if os.path.isfile(p) else None


def delete(name: str) -> bool:
    if not _NAME_RE.match(name) or (capture.active and name == capture.name):
        return False
    hit = False
    for kind in ("pcap", "labels.csv", "json"):
        p = os.path.join(capture_dir(), f"{name}.{kind}")
        if os.path.isfile(p):
            os.remove(p)
            hit = True
    return hit


def cleanup(now: float | None = None):
    d = capture_dir()
    if not os.path.isdir(d):
        return
    now = time.time() if now is None else now
    for fn in os.listdir(d):
        name = fn.split(".", 1)[0]
        if not _NAME_RE.match(name) or (capture.active and name == capture.name):
            continue
        p = os.path.join(d, fn)
        try:
            if now - os.path.getmtime(p) > KEEP_SECONDS:
                os.remove(p)
        except OSError:
            pass
