#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 接口服务
====================
一个只用标准库的 HTTP 服务，对外提供：

  1. TVBox 配置地址        GET /4k_anime.json
  2. 苹果CMS(type=1)接口   GET|POST /api.php/provide/vod/   ?ac=list / ?ac=detail
  3. 玩偶哥哥式 spider 接口 GET /spider/{home,homeVideo,category,detail,play}
  4. 夸克取流             GET /play?pwd=<pwd_id>&fid=<fid>&ft=<token>[&proxy=1]
  5. 网页浏览             GET /
  6. 数据 / 封面           GET /anime.json  /meta.json  /cover/<id>.png

启动： python3 src/server.py [--port 8787] [--host 0.0.0.0]
夸克 Cookie 从环境变量 QUARK_COOKIE 或 config.json 读取（不要提交到仓库）。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quark import (Quark, QuarkAuthError, QuarkError, client_from_env,  # noqa: E402
                   normalize_name)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
ANIME_FILE = os.path.join(DATA_DIR, "anime.json")
META_FILE = os.path.join(DATA_DIR, "meta.json")
CONFIG_FILE = os.path.join(ROOT, "config.json")

DEFAULT_LIMIT = 24
EPISODE_TTL = 600


# --------------------------------------------------------------------------- #
# 占位封面：无 PIL 也能生成 PNG（按番名取色的渐变图，保证每个条目都有封面）
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
        # 主渐变 + 轻微斜向条纹，避免整块纯色
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
# 应用状态
# --------------------------------------------------------------------------- #
class App:
    def __init__(self):
        self.lock = threading.Lock()
        self.anime = self._load(ANIME_FILE, {"items": [], "classes": [], "categories": []})
        self.meta = self._load(META_FILE, {})
        self.quark = client_from_env()
        self._episodes = {}          # item_id -> (ts, payload)
        self._cover_cache = {}
        self._by_type_top = {}
        self._by_type = {}
        self._by_id = {}
        self._reindex()

    @staticmethod
    def _load(path, default):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def _reindex(self):
        self._by_id = {it["id"]: it for it in self.anime.get("items", [])}
        self._by_type_top, self._by_type = {}, {}
        for it in self.anime.get("items", []):
            self._by_type.setdefault(it.get("type_id"), []).append(it["id"])
            self._by_type_top.setdefault(it.get("type_id_top"), []).append(it["id"])

    def reload(self):
        with self.lock:
            self.anime = self._load(ANIME_FILE, self.anime)
            self.meta = self._load(META_FILE, self.meta)
            self._episodes.clear()
            self._reindex()
        return len(self.anime.get("items", []))

    # ---------------- 元数据 ---------------- #
    def pic(self, item, base=""):
        info = self.meta.get(normalize_name(item["name"])) or {}
        return info.get("image") or "%s/cover/%s.png" % (base, item["id"])

    def summary(self, item):
        info = self.meta.get(normalize_name(item["name"])) or {}
        parts = []
        if info.get("summary"):
            parts.append(info["summary"])
        parts.append("画质：%s ｜ 修复：%s ｜ 网盘：%s"
                     % (item.get("resolution", ""), item.get("model", ""),
                        item.get("drive_name", "")))
        if item.get("category"):
            parts.append("分类：%s%s" % (item["category"],
                                     (" / " + item["group"]) if item.get("group") else ""))
        return "\n".join(p for p in parts if p)

    # ---------------- 剧集 ---------------- #
    def episodes(self, item, limit=600):
        """列出该条目在网盘里的视频文件（带内存缓存）"""
        if item.get("drive") != "quark" or not item.get("pwd_id"):
            return []
        now = time.time()
        hit = self._episodes.get(item["id"])
        if hit and now - hit[0] < EPISODE_TTL:
            return hit[1]
        try:
            res = self.quark.collect_episodes(item["pwd_id"], item_name=item["name"],
                                              limit=limit)
            eps = res.get("episodes") or []
        except QuarkError:
            eps = []
        self._episodes[item["id"]] = (now, eps)
        return eps

    def play_url(self, item, ep, base):
        q = urllib.parse.urlencode({
            "pwd": item.get("pwd_id", ""),
            "fid": ep["fid"],
            "ft": ep.get("share_fid_token", ""),
            "n": ep.get("file_name", ""),
        })
        return "%s/play?%s" % (base.rstrip("/"), q)

    def episode_label(self, ep, index):
        name = ep.get("file_name", "")
        m = re.search(r"\[(\d{1,3})\]", name)
        if m:
            return "第%02d集" % int(m.group(1))
        m = re.search(r"(?i)\bE(?:P)?(\d{1,3})\b", name)
        if m:
            return "第%02d集" % int(m.group(1))
        m = re.search(r"(?i)第\s*(\d{1,3})\s*[集话話]", name)
        if m:
            return "第%02d集" % int(m.group(1))
        return "第%02d集" % (index + 1)

    def play_list(self, item, base):
        eps = self.episodes(item)
        rows = []
        for idx, ep in enumerate(eps):
            rows.append("%s$%s" % (self.episode_label(ep, idx),
                                   self.play_url(item, ep, base)))
        return rows


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "4k-anime/1.0"
    protocol_version = "HTTP/1.1"
    app: App = None

    # ---------------- 小工具 ---------------- #
    def log_message(self, fmt, *args):
        sys.stderr.write("[http] %s - %s\n" % (self.address_string(), fmt % args))

    def base_url(self):
        scheme = self.headers.get("X-Forwarded-Proto") or "http"
        host = (self.headers.get("X-Forwarded-Host")
                or self.headers.get("Host") or "127.0.0.1")
        return "%s://%s" % (scheme, host)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, ctype, status=200, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    # ---------------- 路由 ---------------- #
    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def route(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        try:
            if path == "/":
                return self.page_index()
            if path in ("/4k_anime.json", "/config", "/config.json"):
                return self.send_json(self.build_config())
            if path == "/anime.json":
                return self.send_json(self.app.anime)
            if path == "/meta.json":
                return self.send_json(self.app.meta)
            if path == "/health":
                return self.send_json({
                    "ok": True,
                    "items": len(self.app.anime.get("items", [])),
                    "cookie": bool(self.app.quark.cookie),
                    "classes": len(self.app.anime.get("classes", [])),
                    "synced_at": self.app.anime.get("synced_at"),
                })
            if path.startswith("/cover/"):
                return self.cover(path.rsplit("/", 1)[-1])
            if path in ("/api.php/provide/vod", "/api.php/provide/vod/index.php",
                        "/vod", "/api.php/provide/vod/"):
                return self.cms(query)
            if path.startswith("/spider/"):
                return self.spider(path[len("/spider/"):], query)
            if path == "/play":
                return self.play(query)
            return self.send_json({"error": "not found", "path": path}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log_message("handler error: %r", exc)
            try:
                self.send_json({"error": str(exc)}, 500)
            except Exception:
                pass

    # ---------------- TVBox 配置 ---------------- #
    def build_config(self):
        base = self.base_url()
        return {
            "name": "4K动漫（夸克）",
            "wallpaper": "https://lain.bgm.tv/pic/cover/l/1a/43/567520_WvktT.jpg",
            "sites": [
                {
                    "key": "4k_anime",
                    "name": "🎬4K动漫┃夸克",
                    "type": 1,
                    "api": base + "/api.php/provide/vod/",
                    "searchable": 1,
                    "quickSearch": 1,
                    "filterable": 1,
                    "ext": base + "/api.php/provide/vod/",
                }
            ],
            "parses": [
                {"name": "4K动漫直链", "type": 0,
                 "url": base + "/play?url=", "ext": {"flag": ["qq", "qiyi", "youku", "mgtv"]}}
            ],
            "flags": ["4k_anime"],
        }

    # ---------------- 网页 ---------------- #
    def page_index(self):
        base = self.base_url()
        items = self.app.anime.get("items", [])
        cats = self.app.anime.get("categories", [])
        cards = []
        for it in items[:120]:
            pic = self.app.pic(it, base)
            cards.append(
                '<div class="c"><img loading="lazy" src="%s" alt=""><div class="t">%s</div>'
                '<div class="m">%s · %s</div></div>'
                % (_esc(pic), _esc(it["name"]), _esc(it.get("resolution", "")),
                   _esc(it.get("drive_name", ""))))
        nav = "".join('<a href="#%s">%s (%d)</a>' % (_esc(c["name"]), _esc(c["name"]), c["count"])
                      for c in cats)
        html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>4K动漫 · 夸克接口</title><style>
body{margin:0;background:#12131a;color:#e8e8ef;font:14px/1.5 system-ui,sans-serif}
header{padding:18px 20px;background:#1b1d29;border-bottom:1px solid #2b2e3d;position:sticky;top:0}
h1{margin:0 0 6px;font-size:18px}.sub{color:#8b90a8;font-size:12px}
nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
nav a{color:#9fd0ff;text-decoration:none;background:#232636;padding:3px 9px;border-radius:99px;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:14px;padding:18px 20px}
.c{background:#1b1d29;border-radius:10px;overflow:hidden}
.c img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block;background:#232636}
.t{padding:7px 8px 2px;font-size:12.5px;line-height:1.35;height:36px;overflow:hidden}
.m{padding:0 8px 8px;color:#8b90a8;font-size:11px}
code{background:#232636;padding:2px 6px;border-radius:5px}
</style></head><body>
<header><h1>🎬 4K动漫 · 夸克接口</h1>
<div class="sub">共 <b>%d</b> 条 ｜ 数据源：在线表格自动同步 ｜ 配置地址 <code>%s/4k_anime.json</code>
｜ 夸克 Cookie：%s</div><nav>%s</nav></header>
<div class="grid">%s</div></body></html>""" % (
            len(items), _esc(base), "已配置" if self.app.quark.cookie else "未配置（只能浏览，不能取流）",
            nav, "".join(cards))
        self.send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")

    def cover(self, filename):
        item_id = filename.split(".")[0]
        item = self.app._by_id.get(item_id)
        if not item:
            return self.send_json({"error": "no such item"}, 404)
        cached = self.app._cover_cache.get(item_id)
        if cached is None:
            cached = cover_png(item_id)
            self.app._cover_cache[item_id] = cached
        self.send_bytes(cached, "image/png", extra={"Cache-Control": "public, max-age=604800"})

    # ---------------- 苹果CMS (type=1) ---------------- #
    def cms(self, query):
        base = self.base_url()
        ac = (query.get("ac") or "list").lower()
        classes = self.app.anime.get("classes", [])
        items = self.app.anime.get("items", [])

        if ac == "list":
            sample = [self._vod_brief(it, base) for it in items[:20]]
            return self.send_json({"class": classes, "list": sample})

        # ac=detail
        ids = [x for x in (query.get("ids") or "").split(",") if x]
        wd = (query.get("wd") or query.get("q") or "").strip()
        t = query.get("t") or query.get("type_id")
        page = max(1, int(query.get("pg") or query.get("page") or 1))
        limit = max(1, min(100, int(query.get("limit") or DEFAULT_LIMIT)))

        if ids:
            picked = [self.app._by_id[i] for i in ids if i in self.app._by_id]
            return self.send_json({
                "class": classes,
                "list": [self._vod_detail(it, base) for it in picked],
                "total": len(picked), "page": 1, "limit": len(picked), "pagecount": 1,
            })

        pool = items
        if wd:
            pool = [it for it in items if wd.lower() in it["name"].lower()]
        elif t:
            try:
                tid = int(t)
            except ValueError:
                tid = None
            if tid in self.app._by_type_top:
                pool = [self.app._by_id[i] for i in self.app._by_type_top[tid]]
            elif tid in self.app._by_type:
                pool = [self.app._by_id[i] for i in self.app._by_type[tid]]

        total = len(pool)
        start = (page - 1) * limit
        window = pool[start:start + limit]
        # 列表页不解析网盘，播放列表留到详情页再取
        return self.send_json({
            "class": classes,
            "list": [self._vod_brief(it, base) for it in window],
            "total": total,
            "page": page,
            "limit": limit,
            "pagecount": (total + limit - 1) // limit,
        })

    def _vod_brief(self, it, base):
        return {
            "vod_id": it["id"],
            "vod_name": it["name"],
            "vod_pic": self.app.pic(it, base),
            "vod_remarks": "%s · %s" % (it.get("resolution", ""), it.get("drive_name", "")),
            "type_id": it.get("type_id"),
            "type_name": it.get("group") or it.get("category") or "",
            "vod_year": "",
        }

    def _vod_detail(self, it, base):
        detail = self._vod_brief(it, base)
        detail.update({
            "vod_content": self.app.summary(it),
            "vod_play_from": "4k_anime",
            "vod_play_url": "#".join(self.app.play_list(it, base)),
            "vod_area": it.get("category") or "",
            "vod_lang": "日语",
            "vod_director": "",
            "vod_actor": "",
        })
        return detail

    # ---------------- 玩偶哥哥式 spider 接口 ---------------- #
    def spider(self, action, query):
        base = self.base_url()
        classes = self.app.anime.get("classes", [])
        items = self.app.anime.get("items", [])

        if action in ("home", ""):
            return self.send_json({"class": classes,
                                   "list": [self._vod_brief(it, base) for it in items[:20]]})

        if action == "homeVideo":
            return self.send_json({"list": [self._vod_brief(it, base) for it in items[:20]]})

        if action == "category":
            t = query.get("t") or query.get("type_id")
            page = max(1, int(query.get("pg") or 1))
            limit = max(1, min(100, int(query.get("limit") or DEFAULT_LIMIT)))
            pool = items
            try:
                tid = int(t) if t else None
            except ValueError:
                tid = None
            if tid in self.app._by_type_top:
                pool = [self.app._by_id[i] for i in self.app._by_type_top[tid]]
            elif tid in self.app._by_type:
                pool = [self.app._by_id[i] for i in self.app._by_type[tid]]
            start = (page - 1) * limit
            return self.send_json({
                "page": page, "pagecount": (len(pool) + limit - 1) // limit,
                "limit": limit, "total": len(pool),
                "class": classes,
                "list": [self._vod_brief(it, base) for it in pool[start:start + limit]],
            })

        if action == "detail":
            ids = [x for x in (query.get("ids") or query.get("id") or "").split(",") if x]
            picked = [self.app._by_id[i] for i in ids if i in self.app._by_id]
            return self.send_json({"list": [self._vod_detail(it, base) for it in picked]})

        if action == "search":
            wd = (query.get("wd") or query.get("key") or "").strip()
            picked = [it for it in items if wd and wd.lower() in it["name"].lower()]
            return self.send_json({
                "list": [self._vod_brief(it, base) for it in picked[:60]],
                "total": len(picked),
            })

        if action == "play":
            return self._spider_play(query)

        return self.send_json({"error": "unknown spider action", "action": action}, 404)

    def _spider_play(self, query):
        pwd = query.get("pwd") or query.get("pwd_id") or ""
        fid = query.get("fid") or ""
        ft = query.get("ft") or query.get("token") or ""
        if not (pwd and fid):
            return self.send_json({"error": "missing pwd/fid"}, 400)
        try:
            url = self.app.quark.direct_url(pwd, fid, ft)
        except QuarkAuthError as exc:
            return self.send_json({"parse": 0, "url": "", "error": str(exc)}, 401)
        except QuarkError as exc:
            return self.send_json({"parse": 0, "url": "", "error": str(exc)}, 502)
        return self.send_json({"parse": 0, "url": url, "playUrl": url, "header": ""})

    # ---------------- 取流 ---------------- #
    def play(self, query):
        # 兼容 &url= 直接给分享链接的形式
        if query.get("url") and not query.get("fid"):
            return self.send_json({"error": "need pwd & fid", "hint": "先用 detail 拿剧集"},
                                  400)
        pwd = query.get("pwd") or ""
        fid = query.get("fid") or ""
        ft = query.get("ft") or ""
        if not (pwd and fid):
            return self.send_json({"error": "missing pwd/fid"}, 400)
        try:
            url = self.app.quark.direct_url(pwd, fid, ft)
        except QuarkAuthError as exc:
            return self.send_json({"error": str(exc)}, 401)
        except QuarkError as exc:
            return self.send_json({"error": str(exc)}, 502)

        if query.get("proxy") in ("1", "true", "yes"):
            return self._proxy(url)
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _proxy(self, url):
        """反代直链，支持 Range，兼容不跟随 302 的播放器"""
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"),
            "Referer": "https://pan.quark.cn/",
        }
        rng = self.headers.get("Range")
        if rng:
            headers["Range"] = rng
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() in ("content-type", "content-length", "content-range",
                                       "accept-ranges", "last-modified", "etag"):
                        self.send_header(key, value)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except urllib.error.HTTPError as exc:
            self.send_json({"error": "upstream %s" % exc.code}, 502)


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    args = parser.parse_args()

    Handler.app = App()
    count = len(Handler.app.anime.get("items", []))
    print("[server] 条目 %d 条；夸克 Cookie：%s"
          % (count, "已配置" if Handler.app.quark.cookie else "未配置（仅可浏览）"))
    if not count:
        print("[server] 提示：先执行 python3 src/sync_table.py 生成数据")
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    print("[server] 监听 http://%s:%d/" % (args.host, args.port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
