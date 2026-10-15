#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 把同步结果导出成静态数据（数据站，不含任何解析）
============================================================
只做三件事，全部是「静态文件」：

  1. data/anime.json  ->  public/anime.json
     给每个条目补上封面地址（vod_pic）和详情字段
     （vod_year / vod_area / vod_director / vod_actor / vod_content），
     这样影视仓里的 4k动漫 线路取到这份 JSON，详情页就有年份/地区/导演/演员/简介。
  2. data/meta.json   ->  public/meta.json（网页索引用）
  3. 没有 Bangumi 封面的条目 -> public/cover/<id>.png 占位封面（纯色渐变，标准库生成）

配置地址不在这里生成：配置由 src/fetch_fty.py 抓饭太硬官方配置后插入 4k动漫 线路。

用法:
    python3 src/export_data.py
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
import urllib.request
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
PUBLIC_DIR = os.path.join(ROOT, "public")
COVER_DIR = os.path.join(PUBLIC_DIR, "cover", "bgm")      # 镜像下来的 Bangumi 封面

# 封面也走 gh-proxy 加速（国内直连 bgm.tv 的图常加载不出来）
GH = "https://gh-proxy.com/"
RAW = "https://raw.githubusercontent.com/huime180/4k_anime/main"
UA = "dsh-4k-anime/1.0 (https://github.com/huime180/4k_anime)"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from names import normalize_name  # noqa: E402


# --------------------------------------------------------------------------- #
# 占位封面（纯标准库写 PNG，不依赖 Pillow）
# --------------------------------------------------------------------------- #
def _png(width, height, pixel_rows):
    raw = b"".join(b"\x00" + row for row in pixel_rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def cover_png(seed, width=400, height=600):
    """由种子串决定配色的渐变占位封面"""
    digest = zlib.crc32(str(seed).encode("utf-8")) & 0xFFFFFF
    r0, g0, b0 = (digest >> 16) & 0xFF, (digest >> 8) & 0xFF, digest & 0xFF
    r1, g1, b1 = 255 - r0 // 2, 255 - g0 // 2, 255 - b0 // 2
    rows = []
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(r0 + (r1 - r0) * t)
        g = int(g0 + (g1 - g0) * t)
        b = int(b0 + (b1 - b0) * t)
        row = bytearray()
        for x in range(width):
            shade = 14 if ((x + y) // 26) % 2 == 0 else 0
            row += bytes((min(255, r + shade), min(255, g + shade), min(255, b + shade)))
        rows.append(bytes(row))
    return _png(width, height, rows)


# --------------------------------------------------------------------------- #
# data/ -> public/
# --------------------------------------------------------------------------- #
def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return default


def _mirror_cover(url):
    """把 Bangumi 封面下到 public/cover/bgm/ 里，返回走 gh-proxy 的地址

    国内直连 bgm.tv 的图经常加载不出来，所以**自己存一份**，
    再套 gh-proxy（和配置/jar 用的是同一个加速，已验证可用）。
    下载失败就退回原地址，不影响其它条目。
    """
    if not url:
        return ""
    name = hashlib.md5(url.encode("utf-8")).hexdigest()[:16] + ".jpg"
    path = os.path.join(COVER_DIR, name)
    if not os.path.exists(path):
        src = (url.replace("/pic/cover/l/", "/pic/cover/c/")
                  .replace("/pic/cover/s/", "/pic/cover/c/"))     # common 那档 ~12KB
        try:
            req = urllib.request.Request(src, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = resp.read()
            if data[:2] == b"\xff\xd8":                             # 真的是 JPEG
                os.makedirs(COVER_DIR, exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(data)
            else:
                return url
        except Exception:  # noqa: BLE001
            return url
    return GH + RAW + "/public/cover/bgm/" + name


def _fill_items(anime, meta, pages):
    """把封面 + 详情写进每个 item（spider 直接读这份 JSON）"""
    hit_cover = hit_detail = 0

    # 有多少条目共用同一个分享（>1 就是「一季一个大文件夹」的合集，
    # spider 据此只留本条目对应的那个目录）
    share_count = {}
    for item in anime.get("items", []):
        pwd = item.get("pwd_id") or ""
        share_count[pwd] = share_count.get(pwd, 0) + 1
    for item in anime.get("items", []):
        info = meta.get(normalize_name(item.get("name", ""))) or {}
        pic = _mirror_cover(info.get("image") or "")
        if pic:
            hit_cover += 1
        else:
            # 没有 Bangumi 封面的：用仓库里的占位图，同样套 gh-proxy
            pic = GH + RAW + "/public/cover/%s.png" % item["id"]
        item["vod_pic"] = pic

        # 详情四件套 + 简介：影视仓详情页直接显示这些字段
        item["vod_year"] = info.get("year") or (info.get("date") or "")[:4]
        item["vod_area"] = info.get("area") or ""
        item["vod_director"] = info.get("director") or ""
        item["vod_actor"] = info.get("actor") or ""
        item["vod_content"] = (info.get("summary") or "").strip()
        item["share_count"] = share_count.get(item.get("pwd_id") or "", 1)
        # 别名（Bangumi 的 别名/原名/中文名）：目录常写成英文/日文原名，spider 筛目录时一起比
        item["vod_alias"] = info.get("aliases") or ""
        if item["vod_director"] or item["vod_actor"] or item["vod_area"]:
            hit_detail += 1

    anime["_covers"] = {"bangumi": hit_cover, "total": len(anime.get("items", []))}
    anime["_details"] = {"filled": hit_detail, "total": len(anime.get("items", []))}
    return hit_cover, hit_detail


def _placeholder_covers(anime, meta):
    """给缺少封面的条目补占位 PNG 到 public/cover/，返回净生成数量"""
    out_dir = os.path.join(PUBLIC_DIR, "cover")
    os.makedirs(out_dir, exist_ok=True)
    made = 0
    wanted = set()
    for item in anime.get("items", []):
        info = meta.get(normalize_name(item.get("name", ""))) or {}
        if info.get("image"):
            continue                      # 已有 Bangumi 封面，不需要占位图
        wanted.add(item["id"] + ".png")
        path = os.path.join(out_dir, item["id"] + ".png")
        if os.path.exists(path):
            continue
        with open(path, "wb") as fh:
            fh.write(cover_png(item["id"]))
        made += 1

    # 清掉没人用的镜像封面
    if os.path.isdir(COVER_DIR):
        used = set()
        for item in anime.get("items", []):
            info = meta.get(normalize_name(item.get("name", ""))) or {}
            if info.get("image"):
                used.add(hashlib.md5(info["image"].encode("utf-8")).hexdigest()[:16] + ".jpg")
        for name in os.listdir(COVER_DIR):
            if name not in used:
                try:
                    os.remove(os.path.join(COVER_DIR, name))
                except OSError:
                    pass

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
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    anime = _load_json(os.path.join(DATA_DIR, "anime.json"), {})
    meta = _load_json(os.path.join(DATA_DIR, "meta.json"), {})
    if not anime.get("items"):
        print("[export] data/anime.json 还没有数据，先跑 src/sync_table.py")
        return 1

    pages = os.environ.get("PAGES_BASE",
                           "https://huime180.github.io/4k_anime").rstrip("/")
    cover, detail = _fill_items(anime, meta, pages)

    blob = json.dumps(anime, ensure_ascii=False)
    for path in (os.path.join(PUBLIC_DIR, "anime.json"),
                 os.path.join(DATA_DIR, "anime.json")):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(blob)

    meta_src = os.path.join(DATA_DIR, "meta.json")
    if os.path.exists(meta_src):
        with open(meta_src, encoding="utf-8") as fh:
            meta_blob = fh.read()
        with open(os.path.join(PUBLIC_DIR, "meta.json"), "w", encoding="utf-8") as fh:
            fh.write(meta_blob)

    made = _placeholder_covers(anime, meta)
    total = len(anime.get("items", []))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("[export] 条目 %d ｜ Bangumi 封面 %d ｜ 有详情 %d ｜ 新增占位封面 %d ｜ %s"
          % (total, cover, detail, made, stamp))
    print("[export] 静态数据 -> public/anime.json（配置由 src/fetch_fty.py 生成）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
