#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 表格同步
===================
从在线表格 (Luckysheet 结构) 拉取数据，解析成「分类 -> 子分类 -> 条目」的影视清单，
输出 data/anime.json。

表格结构说明（实测）:
  * sheets[0].celldata    : [{r, c, v}]，值为字符串；合并单元格只存锚点，其余格 v 为 {"mc":{...}}
  * sheets[0].config.merge: {"r_c": {r, c, rs, cs}} 合并区域，用于把空值回溯到锚点
  * sheets[0].hyperlink   : {"r_c": {linkAddress: ...}} 真正的网盘分享链接
  * 表格横向分 3 个数据块，每块 4 列: 资源名称 / 使用模型 / 分辨率 / 网盘链接
        列 0-3   -> 每周更新（整季合集，多部番共用一个分享链接）
        列 5-8   -> TV动画合集（每行独立链接）
        列 10-13 -> 其余群友资源合集（每行独立链接）
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlparse

TABLE_ID = os.environ.get("TABLE_ID", "ec61d240-3e96-4f2e-8ced-65b52608303e")
TABLE_API = os.environ.get("TABLE_API", "https://duhai.291277.xyz/api/sheets/" + TABLE_ID)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_FILE = os.path.join(DATA_DIR, "anime.json")

# 三个数据块的列偏移与分类名
BLOCKS = [
    {"base": 0, "link_col": 3, "category": "每周更新"},
    {"base": 5, "link_col": 8, "category": "TV动画合集"},
    {"base": 10, "link_col": 13, "category": "其余群友资源合集"},
]

# 首个数据行（第 9 行是表头「资源名称/使用模型/分辨率/夸克网盘」，第 10 行是块标题）
FIRST_DATA_ROW = 11

# 网盘类型识别
DRIVE_RULES = [
    ("quark", ("pan.quark.cn", "drive.quark.cn")),
    ("pikpak", ("mypikpak.com", "pikpak.com")),
    ("aliyun", ("aliyundrive.com", "alipan.com")),
    ("cloud189", ("cloud.189.cn",)),
    ("baidu", ("pan.baidu.com",)),
    ("uc", ("drive.uc.cn",)),
]
DRIVE_NAMES = {
    "quark": "夸克", "pikpak": "PikPak", "aliyun": "阿里云盘",
    "cloud189": "天翼云盘", "baidu": "百度网盘", "uc": "UC网盘", "other": "其他",
}

VIDEO_EXT = (".mp4", ".mkv", ".ts", ".m2ts", ".avi", ".flv", ".webm",
             ".mov", ".wmv", ".rmvb", ".mpg", ".mpeg", ".iso")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def http_get(url, timeout=40, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def detect_drive(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return "other"
    for drive, hosts in DRIVE_RULES:
        if any(h in host for h in hosts):
            return drive
    return "other"


def quark_pwd_id(url):
    """从 https://pan.quark.cn/s/xxxx 取出 pwd_id"""
    if not url:
        return ""
    m = re.search(r"/s/([0-9a-zA-Z]+)", url)
    return m.group(1) if m else ""


def make_id(*parts):
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# 表格解析
# --------------------------------------------------------------------------- #
class Sheet:
    """把 Luckysheet 的 celldata / merge / hyperlink 展开成二维可查询视图。"""

    def __init__(self, sheet):
        self.row_count = int(sheet.get("row") or 0)
        self.col_count = int(sheet.get("column") or 0)
        self._grid = {}
        self._anchor = {}
        self._merges = []
        self._links = {}

        for cell in sheet.get("celldata") or []:
            value = cell.get("v")
            if isinstance(value, dict):        # 合并单元格占位 {"mc": {...}}
                value = value.get("v")
            if value in (None, ""):
                continue
            self._grid[(int(cell["r"]), int(cell["c"]))] = str(value)

        merge_map = (sheet.get("config") or {}).get("merge") or {}
        for key in merge_map:
            m = merge_map[key]
            r0, c0 = int(m["r"]), int(m["c"])
            rs, cs = int(m.get("rs") or 1), int(m.get("cs") or 1)
            self._merges.append((r0, c0, rs, cs))
            for r in range(r0, r0 + rs):
                for c in range(c0, c0 + cs):
                    self._anchor[(r, c)] = (r0, c0)

        # hyperlink 的键是 "行_列" 字符串，统一转成 (r, c) 元组，与 _grid 的键型一致
        for key, hl in (sheet.get("hyperlink") or {}).items():
            addr = (hl or {}).get("linkAddress") or ""
            if not addr:
                continue
            try:
                parts = str(key).split("_")
                self._links[(int(parts[0]), int(parts[1]))] = addr
            except (ValueError, IndexError):
                continue

    def _lookup(self, table, r, c):
        anchor = self._anchor.get((r, c), (r, c))
        for key in ((r, c), anchor):
            if key in table:
                return table[key]
        return None

    def merge_span(self, r, c):
        """返回 (r,c) 所在合并区域的跨列数；未合并且单格返回 1"""
        for (r0, c0, rs, cs) in self._merges:
            if r0 <= r < r0 + rs and c0 <= c < c0 + cs:
                return cs
        return 1

    def value(self, r, c):
        return self._lookup(self._grid, r, c) or ""

    def link(self, r, c):
        return self._lookup(self._links, r, c) or ""


def parse_sheet(sheet):
    """把表格解析为分类清单。"""
    categories = []
    items = []
    seen = set()

    for block in BLOCKS:
        base, link_col = block["base"], block["link_col"]
        cat = {"name": block["category"], "groups": [], "count": 0}
        current_group = None

        for r in range(FIRST_DATA_ROW, sheet.row_count):
            name = sheet.value(r, base).strip()
            model = sheet.value(r, base + 1).strip()
            resolution = sheet.value(r, base + 2).strip()
            url = sheet.link(r, link_col).strip()

            if not name:
                continue
            # 整行横幅（横向合并 cs>=2）或「名称 == 使用模型」-> 该块内的小标题（子分类）
            if sheet.merge_span(r, base) >= 2 or (model and model == name):
                current_group = {"name": name, "items": []}
                cat["groups"].append(current_group)
                continue
            if not model:
                continue

            if not url:
                continue

            drive = detect_drive(url)
            gname = current_group["name"] if current_group else ""
            item_id = make_id(block["category"], gname, name, model, url)
            if item_id in seen:
                continue
            seen.add(item_id)

            resolution = re.sub(r"(?i)^4k$", "4K", resolution) or "未知"

            item = {
                "id": item_id,
                "name": re.sub(r"\s+", " ", name),
                "model": model,
                "resolution": resolution,
                "drive": drive,
                "drive_name": DRIVE_NAMES.get(drive, drive),
                "share_url": url,
                "pwd_id": quark_pwd_id(url) if drive == "quark" else "",
                "category": block["category"],
                "group": gname,
                "row": r,
                "block": base,
            }
            items.append(item)
            if current_group is None:
                current_group = {"name": "", "items": []}
                cat["groups"].append(current_group)
            current_group["items"].append(item_id)
            cat["count"] += 1

        categories.append(cat)

    # 分类 ID：先顶层分类，再各子分类
    classes = []
    for idx, cat in enumerate(categories, start=1):
        cat["type_id"] = idx
        classes.append({"type_id": idx, "type_name": cat["name"], "type_pid": 0})
    next_id = len(categories) + 1
    for cat in categories:
        for group in cat["groups"]:
            if not group["name"]:
                group["type_id"] = cat["type_id"]
                continue
            group["type_id"] = next_id
            classes.append({"type_id": next_id, "type_name": group["name"],
                            "type_pid": cat["type_id"]})
            next_id += 1

    by_id = {it["id"]: it for it in items}
    for cat in categories:
        for group in cat["groups"]:
            for iid in group["items"]:
                it = by_id.get(iid)
                if it:
                    it["type_id"] = group["type_id"]
                    it["type_id_top"] = cat["type_id"]

    return {"categories": categories, "classes": classes,
            "items": items, "item_index": by_id}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def sync(api=None):
    api = api or TABLE_API
    print("[sync] 拉取表格 " + api)
    raw = http_get(api)
    doc = json.loads(raw.decode("utf-8"))
    sheets = doc.get("sheets") or []
    if not sheets:
        raise RuntimeError("表格数据为空")

    parsed = parse_sheet(Sheet(sheets[0]))
    items = parsed["items"]

    stat = {}
    for it in items:
        stat[it["drive_name"]] = stat.get(it["drive_name"], 0) + 1

    return {
        "name": doc.get("name") or "4K动漫",
        "table_id": doc.get("id") or TABLE_ID,
        "table_api": api,
        "table_updated_at": doc.get("updatedAt"),
        "synced_at": int(time.time() * 1000),
        "total": len(items),
        "stat": stat,
        "classes": parsed["classes"],
        "categories": parsed["categories"],
        "items": items,
    }


def main():
    try:
        result = sync()
    except Exception as exc:
        print("[sync] 失败: %s" % exc, file=sys.stderr)
        return 1

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)

    print("[sync] 条目 %d 条 -> %s" % (result["total"], OUT_FILE))
    print("[sync] 分类 %d 个顶层 / %d 个类别"
          % (len(result["categories"]), len(result["classes"])))
    for cat in result["categories"]:
        print("       - %s: %d 条, %d 个子分类"
              % (cat["name"], cat["count"], len(cat["groups"])))
    print("[sync] 网盘分布: %s" % result["stat"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
