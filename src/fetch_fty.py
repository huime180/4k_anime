#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 自动解析饭太硬配置并插入 4k_anime 线路
=================================================
饭太硬的 /tv 接口是把配置藏在图片里的（前端看起来就是一张图）：

    前 N 字节 : 一张真 JPEG（FF D8 ... FF D9）
    EOI 之后  : base64 文本 -> 解码即配置 JSON
    该 JSON   : 还带 // 注释，必须用宽松 JSON 解析

本脚本抓它 -> 解码 -> 在「🗂我的云盘┃配置」后面插入 4k_anime -> 输出
config/4k_anime_with_fty_cms.json，供 GitHub Actions 定时自动更新。

用法：
    python3 src/fetch_fty.py                      # 默认官方地址
    python3 src/fetch_fty.py --source mirror      # 用 GitHub 镜像兜底
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "config", "4k_anime_with_fty_cms.json")          # 旧：type 1，走本机解析服务
OUT_SPIDER = os.path.join(ROOT, "config", "4k_anime_with_fty.json")        # 配置 A：解析用饭太硬 jar 自带的夸克实现
OUT_OWN = os.path.join(ROOT, "config", "4k_anime_own.json")                # 配置 B：解析用我们自己那套

# 数据源站点（只放 anime.json/meta.json/cover，不含任何解析）：默认 GitHub Pages，
# 换 Cloudflare Pages 时把它设成 https://<项目>.pages.dev 即可（Action 里来自 vars.DATA_BASE）
DATA_BASE = (os.environ.get("DATA_BASE") or "https://huime180.github.io/4k_anime").rstrip("/")

# 饭太硬官方配置里的 jar 也是套了 gh-proxy（国内直连 raw 常被墙），我们照做
RAW_BASE = "https://raw.githubusercontent.com/huime180/4k_anime/main"
GH = "https://gh-proxy.com/"
DATA_RAW = GH + RAW_BASE + "/public/anime.json"
MERGED_JAR = GH + RAW_BASE + "/jar/4k_anime_fty_merged.jar"
ONLY_JAR = GH + RAW_BASE + "/jar/4k_anime_only.jar"           # 只含我们两个类的小 jar（诊断用）
UPSTREAM_INFO = os.path.join(ROOT, "data", "upstream.json")   # 上游官方 jar 的地址+md5
JAR_DIR = os.path.join(ROOT, "jar")


def jar_spec(url: str, filename: str) -> str:
    """给 jar 地址带上 `;md5;<md5>`。

    App 靠这个 md5 判断缓存是否过期：jar 内容一变（我们每次重建都会变），
    带上新的 md5 它才会重新下载 —— 否则一直用旧的缓存 jar
    （表现就是「线路表里还是旧的名字，比如 夸父原1/夸父智1」）。
    """
    path = os.path.join(JAR_DIR, filename)
    try:
        with open(path, "rb") as fh:
            return url + ";md5;" + hashlib.md5(fh.read()).hexdigest()
    except OSError:
        return url


def official_jar() -> str:
    """官方 jar 的地址（`spider` 字段用）——和官方配置一样形如 `地址;md5;xx`，外面套 gh-proxy。

    官方 55 条线路全都依赖这个 jar（loader dex + assets/*.so + 加密 guard），
    所以我们**不再用自己的合并 jar 去顶替它**：一条官方线路都不动，
    我们那条线改用自己的 jar（见 build_line 里的 "jar" 字段）。
    """
    try:
        with open(UPSTREAM_INFO, encoding="utf-8") as fh:
            info = json.load(fh)
        url, md5 = str(info.get("url", "")), str(info.get("md5", ""))
        if url:
            spec = url + (";md5;" + md5 if md5 else "")
            return spec if spec.startswith(GH) else GH + spec      # 官方也套 gh-proxy
    except (OSError, ValueError):
        pass
    return GH + "https://raw.githubusercontent.com/youhunwl/TVBox/master/jar/饭太硬.jar"
OUT_MIN = os.path.join(ROOT, "config", "4k_anime_min.json")   # 最小诊断配置

# 玩偶哥哥式静态数据站的地址（public/tvfan/）：WoGG.playerContent 会校验
# siteUrl 里必须含 "wogg" 或 "tvfan"，所以路径里保留了 tvfan
SITE_URL = (os.environ.get("SITE_URL") or (DATA_BASE + "/tvfan/"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 官方：www.饭太硬.cc/tv （punycode）
OFFICIAL = "http://www.xn--sss604efuw.cc/tv"
# 镜像兜底（同一份配置的明文版）
MIRRORS = [
    "https://raw.githubusercontent.com/youhunwl/TVBox/master/tvbox.json",
    "https://gh-proxy.com/https://raw.githubusercontent.com/youhunwl/TVBox/master/tvbox.json",
]

# 4k_anime 线路的接口地址（服务端）。同机/跨设备都可用局域网 IP。
DEFAULT_HOST = os.environ.get("PUBLIC_BASE", "http://192.168.1.102:8787")
ANCHOR_KEYS = ("MDrive",)          # 插到这个站点后面


# /tv 对头部敏感：实测带 Referer 才给图；Chrome UA 有时被回网站 HTML。
# 所以按「最像 curl」优先的顺序逐个试，且只接受看起来是伪装配置的响应。
HEADER_SETS = [
    {"User-Agent": "curl/8.0.1", "Accept": "*/*",
     "Referer": "http://www.xn--sss604efuw.cc/"},
    {"User-Agent": UA, "Accept": "*/*",
     "Referer": "http://www.xn--sss604efuw.cc/"},
    {"User-Agent": UA, "Accept": "image/avif,image/webp,*/*",
     "Referer": "http://www.xn--sss604efuw.cc/tv"},
    {"User-Agent": UA, "Accept": "*/*"},
]


def looks_like_disguised(raw: bytes) -> bool:
    """伪装配置的两种形态：JPEG 打头（尾部藏 base64）或直接就是明文 JSON"""
    if not raw:
        return False
    if raw[:2] == b"\xff\xd8":
        return raw.rfind(b"\xff\xd9") > 0
    head = raw.lstrip()[:1]
    return head in (b"{", b"\xef")          # JSON / UTF-8 BOM


LOCAL_PROXY = os.environ.get("HTTP_PROXY_LOCAL", "http://127.0.0.1:7890")


def http_get(url, timeout=40, headers=None, tries=None, use_proxy=False):
    """带重试与多头部组合的 GET；返回首个「像样」的响应。

    饭太硬站点是 Cloudflare，国内直连常被 reset；必要时可走本机代理
    （boxproxy 的 http 入口，默认 127.0.0.1:7890）。
    """
    last = None
    sets = [headers] if headers else (tries or HEADER_SETS)
    openers = []
    if use_proxy:
        openers.append(urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": LOCAL_PROXY, "https": LOCAL_PROXY})))
    openers.append(urllib.request.build_opener())
    for op in openers:
        for hdr in sets:
            for attempt in range(2):
                req = urllib.request.Request(url, headers=hdr)
                try:
                    with op.open(req, timeout=timeout) as resp:
                        raw = resp.read()
                    if looks_like_disguised(raw):
                        return raw
                    last = "响应不像配置(%d 字节, 头 %r)" % (len(raw), raw[:12])
                except Exception as exc:  # noqa: BLE001
                    last = "%s: %s" % (type(exc).__name__, str(exc)[:70])
                time.sleep(0.6)
    raise RuntimeError("拿不到有效响应（最后一次：%s）" % last)


def decode_fanty(raw: bytes) -> dict:
    """饭太硬 /tv：JPEG + 尾部 base64 配置"""
    end = raw.rfind(b"\xff\xd9")
    tail = raw[end + 2:] if end >= 0 else raw
    b64 = re.sub(rb"\s+", b"", tail)
    if len(b64) < 16:
        raise ValueError("响应里没有 base64 配置段")
    dec = base64.b64decode(b64 + b"=" * (-len(b64) % 4))
    return _lenient_json(dec)


def _lenient_json(blob: bytes) -> dict:
    s = blob[blob.find(b"{"):].decode("utf-8", "replace")
    s = re.sub(r"^\s*//.*$", "", s, flags=re.M)        # 去掉整行 // 注释
    s = re.sub(r",(\s*[}\]])", r"\1", s)               # 去掉尾逗号
    return json.loads(s)


def load_base(source: str) -> tuple[dict, str]:
    """返回 (配置, 来源说明)"""
    if source in ("auto", "official"):
        try:
            try:
                raw = http_get(OFFICIAL)
            except Exception:                      # 直连不行就走本机代理
                print("[fty] 官方直连失败，改走 %s" % LOCAL_PROXY)
                raw = http_get(OFFICIAL, use_proxy=True)
            d = decode_fanty(raw)
            if d.get("sites"):
                return d, "official(饭太硬 /tv 解码)"
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            if source == "official":
                raise
            print("[fty] 官方地址失败(%s)，转镜像兜底" % exc)
    for url in MIRRORS:
        try:
            raw = http_get(url)
            if raw[:2] == b"\xff\xd8":
                return decode_fanty(raw), "mirror(图片解码) " + url
            return _lenient_json(raw), "mirror(明文) " + url
        except Exception as exc:  # noqa: BLE001
            print("[fty] 镜像失败 %s: %s" % (url, exc))
    raise RuntimeError("所有来源都拿不到饭太硬配置")


def build_line(host: str, kind: str = "cms") -> dict:
    """两种线路写法：

    cms    —— type 1，苹果CMS：api 指到本机 server.py 的 /api.php/provide/vod/
              （分类/列表/详情/播放全在服务端算，服务端必须在线）
    spider —— type 3，csp_Anime4KGuard：跑在我们合并进饭太硬 jar 的那个类里，
              ext 就写饭太硬自己的网盘配置字段 Cloud-drive，
              解析/cookie/扫码登录都交给 jar 里饭太硬原生的夸克实现。
    """
    host = host.rstrip("/")
    if kind == "spider":
        # 配置 A：解析用饭太硬 jar 自己的夸克实现（csp_Anime4KGuard）。
        # Cloud-drive 保持官方占位写法（这个键全线路共用，不乱塞地址）；
        # 想免扫码的话，把 "session" 填成返回 {"quarkCookie": ...} 的地址即可。
        return {
            "key": "4k_anime",
            "name": "🎬4K动漫┃夸克",
            "type": 3,
            "api": "csp_Anime4KGuard",
            "timeout": 30,
            "jar": jar_spec(MERGED_JAR, "4k_anime_fty_merged.jar"),   # 只给这一条线用（带 md5，jar 一变就会重下）
            "searchable": 1,
            "quickSearch": 1,
            "changeable": 0,
            "ext": {
                "Cloud-drive": "tvfan/Cloud-drive.txt",
                "data": DATA_BASE + "/anime.json",
                "data2": DATA_RAW,
            },
        }
    if kind == "wogg":
        # 配置 A：**一行自己的代码都不用** —— 用官方 csp_WoGGGuard，siteUrl 指到我们的静态数据站。
        # 它按固定选择器抓列表/详情（见 src/build_site.py 的契约注释），
        # 播放链接就写在详情页 div.module-row-info > a 的 data-clipboard-text 里，
        # 取流/登录依旧由 jar 里的网盘引擎负责。
        return {
            "key": "4k_anime",
            "name": "🎬4K动漫A┃官方玩偶解析",
            "type": 3,
            "api": "csp_WoGGGuard",
            "timeout": 30,
            "searchable": 1,
            "quickSearch": 1,
            "changeable": 0,
            "ext": {
                "siteUrl": SITE_URL,
                "from": "4k|auto",
                "Cloud-drive": "tvfan/Cloud-drive.txt",
            },
        }
    if kind == "own":
        # 配置 B：解析用我们自己那套（csp_Quark4K）。cookie 可以手填，也可以留空——
        # 留空时会先反射读饭太硬那套的登录态（「我的云盘」扫码后就有），
        # 最后才去本机 server.py 兜底。
        return {
            "key": "4k_anime",
            "name": "🎬4K动漫B┃自带解析",
            "type": 3,
            "api": "csp_Quark4K",
            "timeout": 30,
            "jar": jar_spec(ONLY_JAR, "4k_anime_only.jar"),           # 自带解析不依赖 loader/guard
            "searchable": 1,
            "quickSearch": 1,
            "changeable": 0,
            "ext": {
                "cookie": "",
                "data": DATA_BASE + "/anime.json",
                "data2": DATA_RAW,
            },
        }
    return {
        "key": "4k_anime",
        "name": "🎬4K动漫┃夸克",
        "type": 1,
        "api": host + "/api.php/provide/vod/",
        "searchable": 1,
        "quickSearch": 1,
        "filterable": 1,
        "ext": host + "/api.php/provide/vod/",
    }


def merge(cfg: dict, host: str, kind: str = "cms") -> dict:
    sites = list(cfg.get("sites") or [])
    sites = [s for s in sites if s.get("key") != "4k_anime"]      # 幂等：先去掉旧的
    at = 1
    for i, s in enumerate(sites):
        if s.get("key") in ANCHOR_KEYS:
            at = i + 1
            break
    sites.insert(at, build_line(host, kind))
    cfg["sites"] = sites
    # `spider` 一律保持**官方 jar**：官方 46 条 csp_*Guard 全依赖它，换了它一旦加载失败
    # 所有官方线路会一起消失（用户遇到的「线路都识别不到」）。我们那条线用自己的 jar，
    # 写在站点自己的 "jar" 字段里（TVBox/影视仓 的站点级 jar）。
    cfg["spider"] = official_jar()
    if kind in ("spider", "own", "wogg"):
        cfg["_说明"] = ("饭太硬官方配置（自动解析） + 4k_anime 线路"
                        "（插在「我的云盘」之后，自带 jar 字段）")
        cfg["_4k动漫"] = ("数据站 " + SITE_URL + "（纯静态，公开/tvfan/，站点里没有任何解析）；"
                          "线路直接用官方 csp_WoGGGuard 抓它，spider 保持官方 jar 不动，"
                          "条目也不需要自带 jar。夸克登录见「我的云盘」。"
                          "本文件由 src/fetch_fty.py 自动生成。")
    else:
        cfg["_说明"] = ("饭太硬官方配置（自动解析） + 4k_anime 线路"
                        "（插在「我的云盘」之后）")
        cfg["_4k动漫"] = ("由 huime180/4k_anime 维护：表格定时自动同步 -> anime.json；"
                          "解析取流由本项目服务提供。本文件由 src/fetch_fty.py 自动生成。")
    cfg["_generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="auto", choices=["auto", "official", "mirror"])
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--out-spider", default=OUT_SPIDER)
    ap.add_argument("--out-own", default=OUT_OWN)
    ap.add_argument("--out-min", default=OUT_MIN)
    args = ap.parse_args()

    try:
        cfg, src = load_base(args.source)
    except Exception as exc:  # noqa: BLE001
        # 兜底：拿本地已有的配置当底稿（里面本来就是饭太硬那套站点，只是我们插过一条线，
        # merge() 会先把旧的那条删掉再插），这样站点抽风时也能把三份配置刷出来
        base_path = args.out_spider if os.path.exists(args.out_spider) else args.out
        if not os.path.exists(base_path):
            print("[fty] ⚠️ 抓取失败（%s），且本地没有可用底稿，保留现有配置" % exc)
            return 0
        with open(base_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        src = "local(现有配置当底稿，抓取失败: %s)" % exc
        print("[fty] ⚠️ %s" % src)
    before = len(cfg.get("sites") or [])

    outs = []
    for kind, path in (("cms", args.out), ("wogg", args.out_spider), ("own", args.out_own)):
        cfg_v = copy.deepcopy(cfg)
        merge(cfg_v, args.host, kind)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg_v, fh, ensure_ascii=False, indent=1)
        outs.append((kind, path, cfg_v))

    # 最小诊断配置：只有一个站点，且用「只含我们两个类」的小 jar（不含饭太硬 loader/guard）。
    # 用它来判断「线路识别不到」是出在哪一环：
    #   能识别 -> 我们的类和 App 加载都没问题，问题在合并 jar / 大配置；
    #   识别不到 -> 先查配置地址本身（json、网络），再看 App 版本。
    min_cfg = {
        "spider": jar_spec(ONLY_JAR, "4k_anime_only.jar"),
        "_说明": ("最小诊断配置：只有一个 4k动漫 站点，用 jar/4k_anime_only.jar"
                  "（不含饭太硬 loader/guard）。由 src/fetch_fty.py 生成。"),
        "sites": [build_line(args.host, "own")],
    }
    os.makedirs(os.path.dirname(args.out_min), exist_ok=True)
    with open(args.out_min, "w", encoding="utf-8") as fh:
        json.dump(min_cfg, fh, ensure_ascii=False, indent=1)
    print("[fty] min    api=%s -> %s" % (min_cfg["sites"][0]["api"], args.out_min))
    print("[fty] 来源: %s" % src)
    print("[fty] 站点 %d -> %d，前五个: %s"
          % (before, len(outs[0][2]["sites"]), [s.get("key") for s in outs[0][2]["sites"][:5]]))
    for kind, path, cfg_v in outs:
        line = [s for s in cfg_v["sites"] if s.get("key") == "4k_anime"][0]
        print("[fty] %-6s api=%-18s -> %s" % (kind, line.get("api"), path))
        if kind in ("spider", "own"):
            print("[fty] spider jar: %s" % cfg_v.get("spider"))
        print("[fty] data: %s" % DATA_BASE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
