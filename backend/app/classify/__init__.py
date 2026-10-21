"""把一条流（远端 IP + 端口 + 域名）识别为应用。

优先级：自定义规则 > 域名后缀（先查询名再 CNAME，最长后缀优先）> CIDR > 端口 > other。
"""
import ipaddress
import os
from dataclasses import dataclass

import yaml

RULES_FILE = os.path.join(os.path.dirname(__file__), "apps.yaml")
UNKNOWN_APP = "other"
GENERIC_APPS = {"https", "quic", "http", UNKNOWN_APP}  # 这些应用下的域名算"未识别"


@dataclass
class App:
    id: str
    name: str
    name_en: str
    category: str
    custom: bool = False


def _parse_port(spec: str) -> tuple[int, int, int]:
    proto, rng = spec.lower().split("/")
    pnum = {"tcp": 6, "udp": 17}[proto]
    lo, _, hi = rng.partition("-")
    return pnum, int(lo), int(hi or lo)


class Classifier:
    def __init__(self, rules_file: str = RULES_FILE):
        with open(rules_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.categories: dict[str, dict] = data["categories"]
        self._base_apps = data["apps"]
        self.load_custom([])

    def load_custom(self, custom_rules: list):
        """custom_rules: CustomRule 行（或同字段的对象）。每次规则变更后整体重建。"""
        self.apps: dict[str, App] = {}
        self.domains: dict[str, str] = {}
        self.nets: list[tuple[ipaddress._BaseNetwork, str]] = []
        self.ports: list[tuple[int, int, int, str]] = []
        for a in self._base_apps:
            self.apps[a["id"]] = App(a["id"], a["name"], a.get("name_en", a["name"]), a["category"])
            self._add(a["id"], a.get("domains", []), a.get("cidrs", []), a.get("ports", []), first_wins=True)
        self.apps[UNKNOWN_APP] = App(UNKNOWN_APP, "其他", "Other", "unknown")

        custom_nets, custom_ports = [], []
        for r in custom_rules:
            if r.app_id not in self.apps:
                self.apps[r.app_id] = App(r.app_id, r.app_name or r.app_id, r.app_name or r.app_id,
                                          r.category or "web", custom=True)
            try:
                if r.kind == "domain":
                    self.domains[r.pattern.lower().strip(".")] = r.app_id
                elif r.kind == "cidr":
                    custom_nets.append((ipaddress.ip_network(r.pattern, strict=False), r.app_id))
                elif r.kind == "port":
                    p, lo, hi = _parse_port(r.pattern)
                    custom_ports.append((p, lo, hi, r.app_id))
            except (ValueError, KeyError):
                continue
        # 自定义的放前面，优先匹配
        self.nets = custom_nets + self.nets
        self.ports = custom_ports + self.ports
        self._cache: dict[tuple, str] = {}

    def _add(self, app_id, domains, cidrs, ports, first_wins):
        for d in domains:
            d = d.lower().strip(".")
            if first_wins and d in self.domains:
                continue
            self.domains[d] = app_id
        for c in cidrs:
            self.nets.append((ipaddress.ip_network(c, strict=False), app_id))
        for p in ports:
            proto, lo, hi = _parse_port(p)
            self.ports.append((proto, lo, hi, app_id))

    def match_domain(self, name: str | None) -> str | None:
        if not name:
            return None
        parts = name.lower().strip(".").split(".")
        for i in range(len(parts) - 1):
            hit = self.domains.get(".".join(parts[i:]))
            if hit:
                return hit
        return None

    def classify(self, remote_ip: str, proto: int, port: int, qname: str | None, cname: str | None) -> str:
        key = (remote_ip, proto, port, qname, cname)
        hit = self._cache.get(key)
        if hit:
            return hit
        app = self.match_domain(qname) or self.match_domain(cname)
        if app is None:
            try:
                addr = ipaddress.ip_address(remote_ip)
                for net, aid in self.nets:
                    if addr.version == net.version and addr in net:
                        app = aid
                        break
            except ValueError:
                pass
        if app is None:
            for p, lo, hi, aid in self.ports:
                if p == proto and lo <= port <= hi:
                    app = aid
                    break
        app = app or UNKNOWN_APP
        if len(self._cache) > 200_000:
            self._cache.clear()
        self._cache[key] = app
        return app

    def app_info(self, app_id: str) -> App:
        return self.apps.get(app_id) or App(app_id, app_id, app_id, "unknown")

    def category_info(self, cat: str) -> dict:
        return self.categories.get(cat) or {"name": cat, "name_en": cat}
