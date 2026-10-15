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
import shutil
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
from quark import (Quark, QuarkAuthError, QuarkError,  # noqa: E402
                   clear_saved_cookie, client_from_env, normalize_name)
import quark_login  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
ANIME_FILE = os.path.join(DATA_DIR, "anime.json")
META_FILE = os.path.join(DATA_DIR, "meta.json")
CONFIG_FILE = os.path.join(ROOT, "config.json")

UA_PROXY = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) quark-cloud-drive/3.14.2 Chrome/112.0 Safari/537.36")
DEFAULT_LIMIT = 24
EPISODE_TTL = 600

# 「我的云盘┃配置」在 CMS 里的伪分类：不依赖网页，直接在影视仓里就能登录/清除
MYDRIVE_TYPE_ID = 9000
MYDRIVE_ITEMS = [
    {"id": "mydrive:status", "name": "① 夸克账号状态", "remark": "查看当前是否已登录"},
    {"id": "mydrive:login",  "name": "② 扫码登录夸克", "remark": "打开详情页，扫封面二维码"},
    {"id": "mydrive:clear",  "name": "③ 清除夸克账号", "remark": "删除已保存的 Cookie"},
    {"id": "mydrive:clean",  "name": "④ 清空转存缓存", "remark": "释放播放时占用的网盘空间"},
]


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
        self.qr_sessions = {}        # token -> {rid, created}
        self.qr_workers = {}         # token -> Thread
        self._by_type_top = {}
        self._by_type = {}
        self._by_id = {}
        self._reindex()
        self._start_janitor()

    def _start_janitor(self):
        """后台定期清理转存目录（原画档拿完即删，智能档转码需要文件留存）"""
        ttl = int(os.environ.get("SAVE_TTL", "7200"))

        def run():
            while True:
                time.sleep(1800)
                try:
                    if self.quark.cookie:
                        n = self.quark.purge_older_than(ttl)
                        if n:
                            print("[janitor] 清理 %d 个转存文件（超过 %ds）" % (n, ttl))
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True).start()

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

    def account_info(self):
        return self.quark.account_info()

    def clear_cookie(self):
        """清除已保存的夸克 Cookie，并立即生效"""
        removed = clear_saved_cookie()
        self.quark = client_from_env()
        return removed

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

    def play_url(self, item, ep, base, quality="raw"):
        q = urllib.parse.urlencode({
            "pwd": item.get("pwd_id", ""),
            "fid": ep["fid"],
            "ft": ep.get("share_fid_token", ""),
            "q": quality,
            "n": ep.get("file_name", ""),
            "z": ep.get("size", 0),
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
        """返回 原画$$$智能 两组播放列表（对齐玩偶哥哥的画质选择）"""
        eps = self.episodes(item)
        raw_rows, smart_rows = [], []
        for idx, ep in enumerate(eps):
            label = self.episode_label(ep, idx)
            raw_rows.append("%s$%s" % (label, self.play_url(item, ep, base, "raw")))
            smart_rows.append("%s$%s" % (label, self.play_url(item, ep, base, "smart")))
        return "%s$$$%s" % ("#".join(raw_rows), "#".join(smart_rows))


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
PAGE_TEMPLATE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
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
<div class="sub">共 <b>{{TOTAL}}</b> 条 ｜ 数据源：在线表格自动同步 ｜ 配置地址 <code>{{BASE}}/4k_anime.json</code>
｜ 夸克 Cookie：{{COOKIE}}</div><nav>{{NAV}}</nav></header>
<div class="grid">{{CARDS}}</div></body></html>"""


LOGIN_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>夸克扫码登录 · 4K动漫</title>
<style>
body{margin:0;background:#0f1017;color:#e9e9f2;font:14px/1.6 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
     display:flex;flex-direction:column;align-items:center;padding:26px 16px}
h1{font-size:18px;margin:0 0 4px}
.sub{color:#8b90a8;font-size:12.5px;text-align:center;margin-bottom:18px;max-width:420px}
#qr{display:grid;background:#fff;padding:10px;border-radius:12px;width:min(76vw,300px);aspect-ratio:1;gap:0}
#qr i{display:block;width:100%;aspect-ratio:1}
#status{margin-top:16px;font-size:14px;min-height:22px;text-align:center}
#nick{color:#7cc0ff}
button{margin-top:14px;background:#191b26;border:1px solid #282b3a;color:#e9e9f2;padding:9px 18px;border-radius:9px;cursor:pointer}
button:hover{border-color:#7cc0ff;color:#7cc0ff}
ol{color:#8b90a8;font-size:12.5px;max-width:430px;padding-left:20px}
code{background:#191b26;padding:2px 6px;border-radius:5px;border:1px solid #282b3a}
a{color:#7cc0ff}
.ok{color:#7ee787}.bad{color:#ff7b72}.dim{color:#8b90a8}
</style>
</head>
<body>
<h1>📱 夸克扫码登录</h1>
<div class="sub">当前状态：<b>{{STATE}}</b>　｜　登录成功后 Cookie 会写入 <code>config.json</code>，服务立即生效，无需重启</div>

<div id="qr"></div>
<div id="status">正在获取二维码…</div>
<button id="refresh">刷新二维码</button>

<ol>
  <li>打开手机 <b>夸克 App</b>，用首页右上角的「扫一扫」</li>
  <li>扫描上面的二维码，并在手机上点击「确认登录」</li>
  <li>本页会自动检测到登录成功，并保存 Cookie</li>
</ol>
<div class="dim" style="margin-top:10px;font-size:12px">
  扫不了？也可以在本机终端运行 <code>python3 src/quark_login.py</code>，二维码会直接画在终端里。
</div>

<script>
let token = '', rid = '', timer = null;
const statusEl = document.getElementById('status');
const setStatus = (html, cls) => { statusEl.className = cls || ''; statusEl.innerHTML = html; };

function renderQr(rows, size){
  const quiet = 4, n = size + quiet * 2, grid = document.getElementById('qr');
  grid.style.gridTemplateColumns = 'repeat(' + n + ',1fr)';
  const parts = [];
  for (let y = 0; y < n; y++){
    for (let x = 0; x < n; x++){
      const mx = x - quiet, my = y - quiet;
      const on = mx >= 0 && my >= 0 && mx < size && my < size && rows[my][mx];
      parts.push('<i style="background:' + (on ? '#000' : '#fff') + '"></i>');
    }
  }
  grid.innerHTML = parts.join('');
}

async function newQr(){
  if (timer) { clearInterval(timer); timer = null; }
  setStatus('正在获取二维码…');
  let data;
  try {
    data = await fetch('api/qr/new{{KEYQ}}').then(r => r.json());
  } catch (e) { setStatus('获取失败：' + e.message, 'bad'); return; }
  if (data.error){ setStatus('获取失败：' + data.error, 'bad'); return; }
  renderQr(data.rows, data.size);
  token = data.token; rid = data.rid;
  setStatus('请用夸克 App 扫描二维码', 'dim');
  timer = setInterval(pollOnce, 2000);
}

async function pollOnce(){
  if (!token) return;
  let data;
  try {
    data = await fetch('api/qr/poll?token=' + encodeURIComponent(token) +
                       '&rid=' + encodeURIComponent(rid) + '{{KEYQ}}').then(r => r.json());
  } catch (e) { return; }
  if (data.state === 'confirmed'){
    clearInterval(timer); timer = null;
    setStatus('✅ ' + (data.message || '登录成功') + (data.nick ? '（<span id="nick">' + data.nick + '</span>）' : ''), 'ok');
  } else if (data.state === 'failed'){
    clearInterval(timer); timer = null;
    setStatus('❌ ' + (data.message || '登录失败') + '，请刷新二维码重试', 'bad');
  } else if (data.state === 'expired'){
    clearInterval(timer); timer = null;
    setStatus('二维码已过期，正在刷新…', 'dim');
    newQr();
  }
}

document.getElementById('refresh').onclick = newQr;
window.addEventListener('beforeunload', () => { if (timer) clearInterval(timer); });
newQr();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "4k-anime/1.0"
    protocol_version = "HTTP/1.1"
    # 关键：关掉 Nagle。视频转发是小块连续写，不关 Nagle 会被攒包延迟，
    # 实测吞吐能从 2.4MB/s 掉到直连的 1/3。
    disable_nagle_algorithm = True
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
            if path == "/api/session":
                return self.session_info(query)
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
            if path == "/login":
                return self.page_login(query)
            if path in ("/proxy", "/proxy/"):
                return self.proxy_dispatch(query)
            if path == "/api/qr/new":
                return self.qr_new(query)
            if path in ("/mydrive.png", "/qr.png"):
                return self.mydrive_png(query)
            if path == "/mydrive/act":
                return self.mydrive_act(query)
            if path == "/api/qr/poll":
                return self.qr_poll(query)
            return self.send_json({"error": "not found", "path": path}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.log_message("handler error: %r", exc)
            try:
                self.send_json({"error": str(exc)}, 500)
            except Exception:
                pass

    # ---------------- proxy 分派（对齐玩偶哥哥的 proxy(type=)） ---------------- #
    def proxy_dispatch(self, query):
        """GET /proxy?type=302|play|sub|input

        对齐反编译出来的 csp_QuarkCloud.proxy() 结构：
          302   -> 直接把 CDN 直链 302 给播放器（需播放器带 header）
          play  -> 走本机转发（兼容不带 header 的播放器）
          sub   -> 返回会话/状态信息（对应它的 OB(map)）
          input -> 返回可用的取流地址清单（对应它的 o(map)）
        """
        base = self.base_url()
        qtype = (query.get("type") or "play").lower()
        pwd = query.get("pwd") or query.get("pwd_id") or ""
        fid = query.get("fid") or ""
        ft = query.get("ft") or ""
        quality = (query.get("q") or "raw").lower()
        if quality not in ("raw", "smart"):
            quality = "raw"

        if qtype == "sub":
            return self.send_json({
                "cookie": bool(self.app.quark.cookie),
                "account": self.app.quark.account_info() or {},
                "session": [c.name for c in self.app.quark._jar],
            })

        if not (pwd and fid):
            if qtype == "input":
                return self.send_json({"list": []})
            return self.send_json({"error": "missing pwd/fid"}, 400)

        try:
            url = self.app.quark.direct_url(pwd, fid, ft, quality=quality,
                                            file_name=query.get("n", ""),
                                            file_size=int(query.get("z") or 0))
        except QuarkAuthError as exc:
            return self.send_json({"error": str(exc)}, 401)
        except QuarkError as exc:
            return self.send_json({"error": str(exc)}, 502)

        if qtype == "302":
            # 带 header 信息的 302 说明（播放器按 spider 协议带 header 即可直连）
            self.send_response(302)
            self.send_header("Location", url)
            self.send_header("X-Play-Header", self.app.quark.session_header().replace("\n", " | "))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if qtype == "input":
            return self.send_json({"list": [{"url": url,
                                             "header": self.app.quark.session_header()}]})
        return self._proxy(url, int(query.get("z") or 0))

    def session_info(self, query):
        """供 spider 自动取用当前夸克会话（免得把 cookie 手写进配置）。

        默认只允许内网调用；若设了 ADMIN_TOKEN，则需要 ?key=<token>。
        """
        if not self.admin_ok(query):
            return self.send_json({"ok": False, "error": "需要正确的 key"}, 403)
        ck = self.app.quark.session_cookie() if self.app.quark.cookie else ""
        return self.send_json({
            "ok": bool(ck),
            "cookie": ck,
            "len": len(ck),
            "puus": "__puus" in ck,
            "hint": "把这个 cookie 交给 csp_Anime4KGuard（或让 jar 自己扫码登录）" if ck else "服务端未登录，请先扫码",
        })

    # ---------------- 我的云盘（纯接口，可在影视仓内完成） ---------------- #
    def _cookie_ok(self):
        """Cookie 是否还有效（能读到账号信息）"""
        try:
            return bool(self.app.quark.account_info())
        except Exception:
            return False

    def mydrive_brief(self, item, base):
        pic_key = item["id"].split(":")[1]
        ts = int(time.time())
        return {
            "vod_id": item["id"],
            "vod_name": item["name"],
            "vod_pic": "%s/mydrive.png?k=%s&t=%d" % (base, pic_key, ts),
            "vod_remarks": item["remark"],
            "type_id": MYDRIVE_TYPE_ID,
            "type_name": "🗂我的云盘┃配置",
            "vod_year": "",
        }

    def mydrive_detail(self, item, base):
        key = item["id"].split(":")[1]
        info = self.app.quark.account_info() if self.app.quark.cookie else {}
        self._qr_url_for_detail = ""
        nick = (info or {}).get("nickname") or ""
        member = (info or {}).get("member_type") or ""
        lines = []

        if key == "status":
            if info:
                lines.append("✅ 夸克已登录" + (("：%s" % nick) if nick else ""))
                lines.append("会员：%s" % (member or "未知"))
                cap = (info or {}).get("total_capacity") or 0
                if cap:
                    lines.append("容量：%.2f TB" % (cap / 1e12))
            else:
                lines.append("❌ 夸克未登录（或 Cookie 已失效）")
                lines.append("请进入「② 扫码登录夸克」，扫封面上的二维码。")
        elif key == "login":
            sess = self._new_qr_session()
            if sess:
                self._qr_url_for_detail = sess["url"]
                lines.append("请用【夸克 App → 扫一扫】扫描本页封面上的二维码。")
                lines.append("扫码并在手机上确认后，服务端会自动保存 Cookie，无需其他操作。")
                lines.append("码有效期约 5 分钟；过期就退出重进本页换一张。")
        elif key == "clear":
            removed = self.app.clear_cookie()
            lines.append("🗑 已清除夸克账号 Cookie。" if removed else "当前没有已保存的 Cookie。")
            lines.append("如需再次使用，进入「② 扫码登录夸克」重新扫码。")
        elif key == "clean":
            if not self.app.quark.cookie:
                lines.append("未登录夸克，无需清理。")
            else:
                try:
                    n = self.app.quark.clear_saved()
                    lines.append("🧹 已清空 4k_anime/ 转存目录，删除 %d 个文件。" % n)
                    lines.append("（播放时为了取转码流会把文件转存到这里，看完可以清理释放空间）")
                except QuarkError as exc:
                    lines.append("清理失败：%s" % exc)

        detail = self.mydrive_brief(item, base)
        if key == "login":
            qr = getattr(self, "_qr_url_for_detail", "")
            if qr:
                detail["vod_pic"] = "%s/mydrive.png?k=login&u=%s&t=%d" % (
                    base, urllib.parse.quote(qr, safe=""), int(time.time()))
        detail.update({
            "vod_content": "\n".join(lines),
            "vod_play_from": "mydrive",
            # 播放地址留成动作接口，误点也不会崩：返回一行文字
            "vod_play_url": "%s/play$%s/mydrive/act?do=%s" % (item["name"], base, key),
            "vod_area": "配置", "vod_lang": "", "vod_actor": "", "vod_director": "",
        })
        return detail

    def _new_qr_session(self):
        """申请二维码，并起一个后台线程自动等待登录完成"""
        try:
            session = quark_login.new_session()
        except quark_login.LoginError:
            return None
        self.app.qr_sessions[session["token"]] = {"rid": session["request_id"],
                                                  "created": time.time()}
        self._start_qr_worker(session["token"], session["request_id"])
        return session

    def _start_qr_worker(self, token, rid):
        app = self.app

        def run():
            deadline = time.time() + 300
            while time.time() < deadline:
                state, payload = quark_login.poll(token, rid)
                if state == quark_login.CONFIRMED:
                    try:
                        cookie, _info = quark_login.exchange_cookie(payload)
                        quark_login.save_cookie(cookie)
                        app.quark = client_from_env()
                    except Exception:
                        pass
                    app.qr_sessions.pop(token, None)
                    return
                if state == quark_login.FAILED:
                    app.qr_sessions.pop(token, None)
                    return
                time.sleep(2)

        # 每个 token 一个后台线程，扫码确认后自动落盘并热更新
        if app.qr_workers.get(token) and app.qr_workers[token].is_alive():
            return
        th = threading.Thread(target=run, daemon=True)
        app.qr_workers[token] = th
        th.start()

    def mydrive_png(self, query):
        key = query.get("k") or "status"
        if key == "login":
            # 详情页会把本次会话的二维码内容放在 u= 里，直接渲染，保证扫的和轮询的是同一个
            url = query.get("u") or ""
            if not url:
                return self.send_bytes(quark_login.status_png(False), "image/png")
            return self.send_bytes(quark_login.qr_png(url), "image/png",
                                   extra={"Cache-Control": "no-store"})
        ok = self._cookie_ok()
        return self.send_bytes(quark_login.status_png(ok), "image/png",
                               extra={"Cache-Control": "no-store"})

    def mydrive_act(self, query):
        return self.send_json({"ok": True, "do": query.get("do", ""),
                               "cookie": bool(self.app.quark.cookie)})

    # ---------------- 扫码登录 ---------------- #
    def admin_ok(self, query):
        """配置了 ADMIN_TOKEN 时，扫码登录相关接口需要带 ?key="""
        want = os.environ.get("ADMIN_TOKEN", "")
        if not want:
            return True
        return query.get("key") == want

    def page_login(self, query):
        if not self.admin_ok(query):
            return self.send_json({"error": "需要正确的 key"}, 403)
        key = query.get("key", "")
        html = (LOGIN_TEMPLATE
                .replace("{{KEYQ}}", ("&key=" + urllib.parse.quote(key)) if key else "")
                .replace("{{STATE}}", "已配置" if self.app.quark.cookie else "未配置"))
        self.send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")

    def qr_new(self, query):
        if not self.admin_ok(query):
            return self.send_json({"error": "需要正确的 key"}, 403)
        try:
            session = quark_login.new_session()
        except quark_login.LoginError as exc:
            return self.send_json({"error": str(exc)}, 502)
        size, rows = quark_login.qr_matrix(session["url"])
        if not size:
            return self.send_json({"error": "二维码生成失败（segno 不可用）"}, 500)
        self.app.qr_sessions[session["token"]] = {
            "rid": session["request_id"], "created": time.time(),
        }
        # 清掉 10 分钟前的旧会话
        now = time.time()
        for tk in [k for k, v in self.app.qr_sessions.items()
                   if now - v["created"] > 600]:
            self.app.qr_sessions.pop(tk, None)
        return self.send_json({
            "token": session["token"], "rid": session["request_id"],
            "url": session["url"], "size": size, "rows": rows,
        })

    def qr_poll(self, query):
        if not self.admin_ok(query):
            return self.send_json({"error": "需要正确的 key"}, 403)
        token = query.get("token") or ""
        sess = self.app.qr_sessions.get(token)
        if not sess:
            return self.send_json({"state": "expired", "message": "会话不存在或已过期"})
        state, payload = quark_login.poll(token, sess["rid"])
        if state != quark_login.CONFIRMED:
            return self.send_json({"state": state,
                                   "message": payload if state == quark_login.FAILED else ""})
        try:
            cookie, info = quark_login.exchange_cookie(payload)
            quark_login.save_cookie(cookie)
        except Exception as exc:  # noqa: BLE001
            return self.send_json({"state": "failed", "message": "换取 Cookie 失败：%s" % exc})
        self.app.quark = client_from_env()      # 热更新，无需重启
        self.app.qr_sessions.pop(token, None)
        nick = ((info.get("data") or {}).get("nickname")) or ""
        self.log_message("扫码登录成功：%s", nick or "(未知昵称)")
        return self.send_json({"state": "confirmed", "nick": nick,
                               "message": "登录成功，已保存 Cookie"})

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
        """首页直接吐 public/index.html —— 与 GitHub Pages 上完全同一份页面。

        模板由 src/build_web.py 生成；本机 / Pages 的差别交给页面里的 JS
        （探测同源 /health）自己判断，不再各维护一套 HTML。
        """
        static = os.path.join(ROOT, "public", "index.html")
        try:
            with open(static, "rb") as fh:
                body = fh.read()
            if body:
                self.send_bytes(body, "text/html; charset=utf-8")
                return
        except OSError:
            pass
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
        nav = "".join('<a href="#%s">%s (%d)</a>'
                      % (_esc(c["name"]), _esc(c["name"]), c["count"]) for c in cats)
        # 用占位符替换而不是 % 格式化：模板里的 CSS 含 100%，会撞上格式符
        html = (PAGE_TEMPLATE
                .replace("{{TOTAL}}", str(len(items)))
                .replace("{{BASE}}", _esc(base))
                .replace("{{COOKIE}}", "已配置 ✅" if self.app.quark.cookie
                         else '<a href="login" style="color:#7cc0ff">未配置 —— 点此扫码登录</a>')
                .replace("{{NAV}}", nav)
                .replace("{{CARDS}}", "".join(cards)))
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
        items = self.app.anime.get("items", [])
        # 「我的云盘┃配置」作为一个伪分类挂进来，影视仓里就能登录/清除
        classes = list(self.app.anime.get("classes", [])) + [
            {"type_id": MYDRIVE_TYPE_ID, "type_name": "🗂我的云盘┃配置", "type_pid": 0}]

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
            out = []
            for i in ids:
                if i.startswith("mydrive:"):
                    hit = next((m for m in MYDRIVE_ITEMS if m["id"] == i), None)
                    if hit:
                        out.append(self.mydrive_detail(hit, base))
                elif i in self.app._by_id:
                    out.append(self._vod_detail(self.app._by_id[i], base))
            return self.send_json({
                "class": classes, "list": out,
                "total": len(out), "page": 1, "limit": len(out), "pagecount": 1,
            })

        # 我的云盘伪分类的列表
        try:
            if t and int(t) == MYDRIVE_TYPE_ID:
                out = [self.mydrive_brief(m, base) for m in MYDRIVE_ITEMS]
                return self.send_json({"class": classes, "list": out,
                                       "total": len(out), "page": 1,
                                       "limit": len(out), "pagecount": 1})
        except ValueError:
            pass

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
            "vod_play_from": "原画$$$智能",
            "vod_play_url": self.app.play_list(it, base),
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

        classes = list(classes) + [
            {"type_id": MYDRIVE_TYPE_ID, "type_name": "🗂我的云盘┃配置", "type_pid": 0}]

        if action in ("home", ""):
            return self.send_json({"class": classes,
                                   "list": [self._vod_brief(it, base) for it in items[:20]]})

        if action == "homeVideo":
            return self.send_json({"list": [self._vod_brief(it, base) for it in items[:20]]})

        if action == "category":
            t = query.get("t") or query.get("type_id")
            page = max(1, int(query.get("pg") or 1))
            limit = max(1, min(100, int(query.get("limit") or DEFAULT_LIMIT)))
            try:
                if t and int(t) == MYDRIVE_TYPE_ID:
                    out = [self.mydrive_brief(m, base) for m in MYDRIVE_ITEMS]
                    return self.send_json({"page": 1, "pagecount": 1, "limit": len(out),
                                           "total": len(out), "class": classes, "list": out})
            except ValueError:
                pass
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
            out = []
            for i in ids:
                if i.startswith("mydrive:"):
                    hit = next((m for m in MYDRIVE_ITEMS if m["id"] == i), None)
                    if hit:
                        out.append(self.mydrive_detail(hit, base))
                elif i in self.app._by_id:
                    out.append(self._vod_detail(self.app._by_id[i], base))
            return self.send_json({"list": out})

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
        quality = (query.get("q") or "raw").lower()
        if quality not in ("raw", "smart"):
            quality = "raw"
        try:
            url = self.app.quark.direct_url(
                pwd, fid, ft, quality=quality,
                file_name=query.get("n", ""),
                file_size=int(query.get("z") or 0))
        except QuarkAuthError as exc:
            return self.send_json({"parse": 0, "url": "", "error": str(exc)}, 401)
        except QuarkError as exc:
            return self.send_json({"parse": 0, "url": "", "error": str(exc)}, 502)
        # 把会话 Cookie 作为 header 交给播放器 —— 它就能直连 CDN，
        # 不经过我们的转发，吞吐不受限。
        return self.send_json({"parse": 0, "url": url, "playUrl": url,
                               "header": self.app.quark.session_header()})

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
        quality = (query.get("q") or "raw").lower()
        if quality not in ("raw", "smart"):
            quality = "raw"
        try:
            url = self.app.quark.direct_url(
                pwd, fid, ft, quality=quality,
                file_name=query.get("n", ""),
                file_size=int(query.get("z") or 0))
        except QuarkAuthError as exc:
            return self.send_json({"error": str(exc)}, 401)
        except QuarkError as exc:
            return self.send_json({"error": str(exc)}, 502)

        # 默认走服务端代理：夸克 CDN 会校验取流时下发到会话里的 __pugs，
        # 少了它播放器直连必然 412 Precondition Failed。要 302 可显式传 direct=1。
        if query.get("direct") in ("1", "true", "yes"):
            return self._redirect(url)
        return self._proxy(url, int(query.get("z") or 0))

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _proxy(self, url, total_size=0):
        """把 CDN 流转发给播放器。

        实测依据：同一 CDN 主机解析出 8 个 alikunlun 节点，单节点被限到 1~2MB/s，
        玩偶哥哥抓包显示它同时连 8+ 个节点做并发。所以这里把请求的 Range 切成 N 段，
        **分发到不同节点**并发拉取，再按序写出 —— 而不是在同一 IP 上开多连接。
        """
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
            except OSError:
                pass
        except OSError:
            pass

        # 解析客户端的 Range
        rng = (self.headers.get("Range") or "").strip()
        start, end = 0, None
        is_range = False
        if rng.startswith("bytes="):
            part = rng[6:].split(",")[0].strip()
            a, _, b = part.partition("-")
            try:
                if a:
                    start, end = int(a), (int(b) if b else None)
                elif b:
                    start, end = None, int(b)
                is_range = True
            except ValueError:
                start, end, is_range = 0, None, False

        if end is None and total_size:
            end = total_size - 1 if start is not None else None

        headers = {"User-Agent": UA_PROXY, "Referer": "https://pan.quark.cn/"}

        # Range 无法确定终点时退回单连接（保持兼容）
        if not total_size or start is None or end is None or end < start:
            extra = {"Range": rng} if rng else {}
            try:
                with self.app.quark.open_stream(url, extra) as resp:
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() in ("content-type", "content-length", "content-range",
                                         "accept-ranges", "last-modified", "etag"):
                            self.send_header(k, v)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    shutil.copyfileobj(resp, self.wfile, 1024 * 1024)
            except urllib.error.HTTPError as exc:
                self.send_json({"error": "upstream %s" % exc.code}, 502)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        length = end - start + 1
        try:
            self.send_response(206 if is_range else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            if is_range:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, total_size))
            self.send_header("Content-Length", str(length))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            n = int(os.environ.get("PARALLEL_N", str(self.app.quark.PARALLEL_N)))
            sent = 0
            buf = []
            buflen = 0
            for chunk in self.app.quark.stream_ranges(url, start, end, headers, n=n):
                buf.append(chunk)
                buflen += len(chunk)
                sent += len(chunk)
                # 攒到 2MB 一次写出，减少系统调用次数
                if buflen >= 2 * 1024 * 1024:
                    self.wfile.write(b"".join(buf))
                    self.wfile.flush()
                    buf, buflen = [], 0
                if sent >= length:
                    break
            if buf:
                self.wfile.write(b"".join(buf))
                self.wfile.flush()

        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001
            self.log_message("proxy error: %r", exc)

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
