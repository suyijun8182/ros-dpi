import os

import yaml

from app.classify import V2FLY_FILE, Classifier, active_v2fly_file
from app.classify import updater as upd
from app.classify import v2fly


def _files():
    """一份极小的 v2fly data：一个分类 + 两个列表"""
    return {
        "category-games": "include:steam\ninclude:newgame\n",
        "steam": "steampowered.com\nsteamcontent.com\n",
        "newgame": "# 新游戏\nnewgame-example.com\n",
    }


def test_convert_and_source_header(tmp_path):
    doc, st = v2fly.convert(_files())
    assert any(a["name"] == "新游戏" and a["category"] == "game" for a in doc["apps"])
    p = tmp_path / "out.yaml"
    v2fly.write(doc, str(p), {"sha": "abc123", "date": "2030-01-01T00:00:00Z"})
    assert v2fly.read_source(str(p)) == {"sha": "abc123", "date": "2030-01-01T00:00:00Z"}
    assert yaml.safe_load(p.read_text(encoding="utf-8"))["apps"]


def test_updater_rejects_bad_data_and_keeps_old(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    u = upd.RulesUpdater()
    monkeypatch.setattr(v2fly, "latest_commit", lambda: {"sha": "f" * 40, "date": "2099-01-01T00:00:00Z"})
    monkeypatch.setattr(v2fly, "fetch", lambda ref: _files())  # 只有 3 个列表：应用数骤减，自检必须拒绝
    reloaded = []
    st = u.check(force=True, reload=lambda: reloaded.append(1))
    assert st["result"] == "rejected" and "应用数" in st["error"] and not reloaded
    assert not os.path.exists(tmp_path / "apps_v2fly.yaml") and active_v2fly_file() == V2FLY_FILE


def test_updater_installs_newer_rules(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    u = upd.RulesUpdater()
    # 用打包的完整规则 + 一个新应用模拟“上游有更新”
    full = yaml.safe_load(open(V2FLY_FILE, encoding="utf-8"))
    full["apps"].append({"id": "v2_brand_new", "name": "全新应用", "name_en": "Brand new", "category": "game",
                         "domains": ["brand-new-game.example"]})
    monkeypatch.setattr(v2fly, "latest_commit", lambda: {"sha": "e" * 40, "date": "2099-01-01T00:00:00Z"})
    monkeypatch.setattr(v2fly, "fetch", lambda ref: {})
    monkeypatch.setattr(v2fly, "convert", lambda files: (full, {"apps": len(full["apps"]), "extend": 1, "domains": 1}))
    reloaded = []
    st = u.check(force=True, reload=lambda: reloaded.append(1))
    assert st["result"] == "updated" and reloaded == [1]
    assert active_v2fly_file() == str(tmp_path / "apps_v2fly.yaml")
    assert Classifier().match_domain("brand-new-game.example") == "v2_brand_new"
    # 同一个提交再检查：已是最新
    assert u.check(force=True)["result"] == "uptodate"
