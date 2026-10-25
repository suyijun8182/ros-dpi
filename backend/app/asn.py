"""IP → ASN（自治系统，即 IP 段属于哪家公司 / 运营商）与国家。

数据来自 iptoasn.com 的 ip2asn-combined.tsv.gz（公有领域 PDDL v1.0，每小时更新）。
不打包进镜像：容器运行时下载到数据目录，每天更新一次；下载失败时继续用已有的文件，没有文件就不启用。

用途：没有域名可查的流量（加密 DNS、直连 IP、隧道），至少能按 IP 归属认出是哪家公司（腾讯、阿里、苹果、Netflix……），
以及在实时连接 / 访问目标里显示远端 IP 的归属和国家。
"""
import gzip
import ipaddress
import os
import threading
import time
from array import array
from bisect import bisect_right

import httpx

URL = "https://iptoasn.com/data/ip2asn-combined.tsv.gz"
MAX_AGE = 86400


class AsnDb:
    def __init__(self):
        self.lock = threading.Lock()
        self._v4 = (array("Q"), array("Q"), array("I"), [])  # starts, ends, asn, 国家
        self._v6 = ([], [], array("I"), [])
        self.names: dict[int, str] = {}
        self.rows = 0
        self.updated = 0
        self.error = ""
        self._cache: dict[str, tuple | None] = {}

    @staticmethod
    def path() -> str:
        return os.path.join(os.environ.get("DATA_DIR", "data"), "ip2asn-combined.tsv.gz")

    def load(self, path: str | None = None) -> bool:
        path = path or self.path()
        if not os.path.exists(path):
            return False
        v4 = (array("Q"), array("Q"), array("I"), [])
        v6 = ([], [], array("I"), [])
        names: dict[int, str] = {}
        n = 0
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) < 5:
                    continue
                asn = int(p[2]) if p[2].isdigit() else 0
                if asn == 0:  # 未分配 / 未通告的地址段
                    continue
                try:
                    a, b = ipaddress.ip_address(p[0]), ipaddress.ip_address(p[1])
                except ValueError:
                    continue
                t = v4 if a.version == 4 else v6
                t[0].append(int(a))
                t[1].append(int(b))
                t[2].append(asn)
                t[3].append(p[3])
                names.setdefault(asn, p[4])
                n += 1
        with self.lock:
            self._v4, self._v6, self.names, self.rows = v4, v6, names, n
            self.updated = int(os.path.getmtime(path))
            self._cache = {}
            self.version = getattr(self, "version", 0) + 1   # 分类结果缓存按它失效（加载前缓存的都是没有 ASN 的结论）
        return True

    def lookup(self, ip: str) -> tuple[int, str, str] | None:
        """返回 (ASN, 国家代码, 名称)；查不到返回 None"""
        if not self.rows:
            return None
        hit = self._cache.get(ip, False)
        if hit is not False:
            return hit
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return None
        t = self._v4 if a.version == 4 else self._v6
        x = int(a)
        i = bisect_right(t[0], x) - 1
        res = None
        if i >= 0 and x <= t[1][i]:
            asn = t[2][i]
            res = (asn, t[3][i], self.names.get(asn, ""))
        if len(self._cache) > 200_000:
            self._cache = {}
        self._cache[ip] = res
        return res

    def update(self, force: bool = False) -> bool:
        """文件超过一天就重新下载（先写临时文件，成功后替换）。返回是否有新数据。"""
        path = self.path()
        if not force and os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE:
            if not self.rows:
                self.load(path)
            return False
        tmp = path + ".part"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with httpx.stream("GET", URL, timeout=120, follow_redirects=True) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
            with gzip.open(tmp, "rt") as f:  # 校验是完整的 gzip
                f.readline()
            os.replace(tmp, path)
            self.error = ""
        except Exception as e:  # noqa: BLE001  没有外网时保留旧数据
            self.error = f"{type(e).__name__}: {str(e)[:160]}"
            if os.path.exists(tmp):
                os.remove(tmp)
            if not self.rows:
                self.load(path)
            return False
        return self.load(path)

    def status(self) -> dict:
        return {"rows": self.rows, "updated": self.updated, "error": self.error, "asns": len(self.names)}


asndb = AsnDb()
