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


def _inject_covers():
    """把封面 URL 写进 anime.json 的每个 item（vod_pic）

    优先 Bangumi 封面；没有的用 GitHub Pages 上的占位封面。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from quark import normalize_name

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

    pages = os.environ.get("PAGES_BASE",
                           "https://huime180.github.io/4k_anime").rstrip("/")
    hit = 0
    for item in anime.get("items", []):
        info = meta.get(normalize_name(item["name"])) or {}
        pic = info.get("image") or ""
        if not pic:
            pic = "%s/cover/%s.png" % (pages, item["id"])
        else:
            hit += 1
        item["vod_pic"] = pic
    anime["_covers"] = {"bangumi": hit, "total": len(anime.get("items", []))}

    with open(os.path.join(PUBLIC_DIR, "anime.json"), "w", encoding="utf-8") as fh:
        json.dump(anime, fh, ensure_ascii=False)
    # 同步回 data/，让服务端与静态页看到同一份
    with open(anime_path, "w", encoding="utf-8") as fh:
        json.dump(anime, fh, ensure_ascii=False)
    print("[build] 封面已写入 anime.json：Bangumi %d / %d" % (hit, len(anime.get("items", []))))
    return hit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("PUBLIC_BASE", "http://127.0.0.1:8787"),
                        help="接口服务的对外地址，例如 https://anime.example.com")
    parser.add_argument("--out", default=os.path.join(ROOT, "config", "4k_anime.json"))
    args = parser.parse_args()

    os.makedirs(PUBLIC_DIR, exist_ok=True)
    config = build(args.base)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)

    # 静态数据：anime.json 里补上 vod_pic
    # 原因：spider 读的是这份静态数据，而封面原本只在服务端运行时由 meta.json 算出，
    # 静态文件里没有 -> 客户端就没图。这里把封面 URL 直接写进每个 item。
    _inject_covers()

    for name in ("meta.json",):
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
