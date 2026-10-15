#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 生成 TVBox 配置地址
================================
把 data/ 下的同步结果导出到 public/，并生成可直接填进 TVBox 的配置 JSON。

用法:
    python3 src/build_config.py --base https://your-host:8787
    python3 src/build_config.py --base http://192.168.1.10:8787
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
PUBLIC_DIR = os.path.join(ROOT, "public")

WALLPAPER = "https://lain.bgm.tv/pic/cover/l/1a/43/567520_WvktT.jpg"
LOGO = "https://lain.bgm.tv/pic/cover/c/23/5d/43558_ECoSc.jpg"


def build(base, api_path="/api.php/provide/vod/"):
    base = base.rstrip("/")
    return {
        "name": "4K动漫（夸克）",
        "wallpaper": WALLPAPER,
        "logo": LOGO,
        "sites": [
            {
                "key": "4k_anime",
                "name": "🎬4K动漫┃夸克",
                "type": 1,
                "api": base + api_path,
                "searchable": 1,
                "quickSearch": 1,
                "filterable": 1,
                "ext": base + api_path,
            }
        ],
        "parses": [
            {
                "name": "4K动漫直链",
                "type": 0,
                "url": base + "/play?url=",
                "ext": {"flag": ["qq", "qiyi", "youku", "mgtv"]},
            }
        ],
        "flags": ["4k_anime"],
    }


def _make_placeholder_covers():
    """给缺少封面的条目补占位 PNG 到 public/cover/，返回生成数量"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from quark import normalize_name
    from server import cover_png

    anime_path = os.path.join(DATA_DIR, "anime.json")
    meta_path = os.path.join(DATA_DIR, "meta.json")
    if not os.path.exists(anime_path):
        return 0
    with open(anime_path, encoding="utf-8") as fh:
        anime = json.load(fh)
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)

    out_dir = os.path.join(PUBLIC_DIR, "cover")
    os.makedirs(out_dir, exist_ok=True)
    made = 0
    wanted = set()
    for item in anime.get("items", []):
        info = meta.get(normalize_name(item["name"])) or {}
        if info.get("image"):
            continue            # 已有 Bangumi 封面，不需要占位图
        wanted.add(item["id"] + ".png")
        path = os.path.join(out_dir, item["id"] + ".png")
        if os.path.exists(path):
            continue
        with open(path, "wb") as fh:
            fh.write(cover_png(item["id"]))
        made += 1

    # 清掉「后来配上 Bangumi 封面」而变得多余的占位图
    for name in os.listdir(out_dir):
        if name.endswith(".png") and name not in wanted:
            try:
                os.remove(os.path.join(out_dir, name))
                made -= 1
            except OSError:
                pass
    return made


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("PUBLIC_BASE", "http://127.0.0.1:8787"),
                        help="接口服务的对外地址，例如 https://anime.example.com")
    parser.add_argument("--out", default=os.path.join(PUBLIC_DIR, "4k_anime.json"))
    args = parser.parse_args()

    os.makedirs(PUBLIC_DIR, exist_ok=True)
    config = build(args.base)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)

    # 静态数据一并拷到 public/，供 GitHub Pages 浏览
    for name in ("anime.json", "meta.json"):
        src = os.path.join(DATA_DIR, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(PUBLIC_DIR, name))

    # 没有 Bangumi 封面的条目，生成占位封面，保证静态页面每个条目都有图
    made = _make_placeholder_covers()

    anime_path = os.path.join(DATA_DIR, "anime.json")
    total = 0
    if os.path.exists(anime_path):
        with open(anime_path, encoding="utf-8") as fh:
            total = len(json.load(fh).get("items", []))

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("[build] 配置地址 -> %s" % args.out)
    print("[build] 站点接口 -> %s" % args.base)
    print("[build] 条目 %d 条 ｜ 新增占位封面 %d 张 ｜ %s" % (total, made, stamp))
    print("[build] TVBox 里填写的配置地址：%s/4k_anime.json" % PUBLIC_DIR.rstrip("/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
