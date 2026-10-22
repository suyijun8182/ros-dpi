"""识别库自动更新：每天检查 v2fly/domain-list-community 的最新提交，有更新就下载、转换、自检，通过后热加载。

- 生成的规则写到数据目录（data/apps_v2fly.yaml），不改镜像里的文件；镜像升级后如果自带的更新，就用镜像里的。
- 自检：抽样域名必须识别正确，应用数不能比现在少很多；不通过就保留旧库，记录原因。
- 状态记在 data/rules_update.json，界面上的“识别库”面板显示来源、版本、上次检查结果。
"""
import json
import os
import threading
import time

from app.classify import V2FLY_FILE, Classifier, active_v2fly_file
from app.classify import v2fly

CHECK_EVERY = 24 * 3600
# 自检用的抽样：手工库和 v2fly 各几条，任何一条认错都不上线
SANITY = [("www.douyin.com", "douyin"), ("store.steampowered.com", "steam"), ("www.bilibili.com", "bilibili"),
          ("api.telegram.org", "telegram"), ("www.icbc.com.cn", "icbc"), ("x.kunlunsl.com", "aliyun")]


def _data_dir() -> str:
    return os.environ.get("DATA_DIR", "data")


def data_file() -> str:
    return os.path.join(_data_dir(), "apps_v2fly.yaml")


class RulesUpdater:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"checked": 0, "result": "", "error": "", "latest": None, "summary": None}
        self._load_state()

    def _state_path(self):
        return os.path.join(_data_dir(), "rules_update.json")

    def _load_state(self):
        try:
            with open(self._state_path(), encoding="utf-8") as f:
                self.state.update(json.load(f))
        except (OSError, ValueError):
            pass

    def _save_state(self):
        try:
            os.makedirs(_data_dir(), exist_ok=True)
            with open(self._state_path(), "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False)
        except OSError:
            pass

    def check(self, force: bool = False, reload=None) -> dict:
        """force=False 时一天最多检查一次。reload：新规则上线后调用（热加载识别器）"""
        if not self.lock.acquire(blocking=False):
            return self.state  # 已经在检查
        try:
            if not force and time.time() - self.state["checked"] < CHECK_EVERY:
                return self.state
            self.state.update(checked=int(time.time()), error="")
            try:
                latest = v2fly.latest_commit()
                self.state["latest"] = latest
                current = v2fly.read_source(active_v2fly_file()) or {}
                if latest["sha"] == current.get("sha"):
                    self.state["result"] = "uptodate"
                    return self.state
                files = v2fly.fetch(latest["sha"])
                doc, summary = v2fly.convert(files)
                tmp = data_file() + ".part"
                os.makedirs(_data_dir(), exist_ok=True)
                v2fly.write(doc, tmp, latest)
                problem = self._self_test(tmp)
                if problem:
                    os.remove(tmp)
                    self.state.update(result="rejected", error=problem)
                    return self.state
                os.replace(tmp, data_file())
                self.state.update(result="updated", summary={k: summary[k] for k in ("apps", "extend", "domains")})
                if reload:
                    reload()
            except Exception as e:  # noqa: BLE001  没有外网、GitHub 限流等：保留现有规则
                self.state.update(result="failed", error=f"{type(e).__name__}: {str(e)[:200]}")
            return self.state
        finally:
            self._save_state()
            self.lock.release()

    @staticmethod
    def _self_test(path: str) -> str:
        """返回问题描述；没问题返回空字符串"""
        try:
            new = Classifier(extra_file=path)
        except Exception as e:  # noqa: BLE001
            return f"新规则文件无法加载：{type(e).__name__}: {e}"
        for dom, want in SANITY:
            got = new.match_domain(dom)
            if got != want:
                return f"抽样检查失败：{dom} 应识别为 {want}，新规则识别为 {got}"
        old = Classifier()
        if len(new.apps) < len(old.apps) * 0.8:
            return f"应用数从 {len(old.apps)} 降到 {len(new.apps)}，可能是上游数据不完整"
        return ""

    def status(self) -> dict:
        path = active_v2fly_file()
        src = v2fly.read_source(path) or {}
        return {**self.state, "active": "data" if path != V2FLY_FILE else "bundled", "sha": src.get("sha"),
                "date": src.get("date"), "next": self.state["checked"] + CHECK_EVERY if self.state["checked"] else None}


updater = RulesUpdater()
