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
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "config", "4k_anime_with_fty_cms.json")

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


def build_line(host: str) -> dict:
    host = host.rstrip("/")
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


def merge(cfg: dict, host: str) -> dict:
    sites = list(cfg.get("sites") or [])
    sites = [s for s in sites if s.get("key") != "4k_anime"]      # 幂等：先去掉旧的
    at = 1
    for i, s in enumerate(sites):
        if s.get("key") in ANCHOR_KEYS:
            at = i + 1
            break
    sites.insert(at, build_line(host))
    cfg["sites"] = sites
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
    args = ap.parse_args()

    try:
        cfg, src = load_base(args.source)
    except Exception as exc:  # noqa: BLE001
        if os.path.exists(args.out):
            print("[fty] ⚠️ 抓取失败（%s），**保留现有配置不覆盖**：%s" % (exc, args.out))
            return 0
        raise
    before = len(cfg.get("sites") or [])
    merge(cfg, args.host)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=1)

    keys = [s.get("key") for s in cfg["sites"][:5]]
    print("[fty] 来源: %s" % src)
    print("[fty] spider: %s" % str(cfg.get("spider"))[:78])
    print("[fty] 站点 %d -> %d，前五个: %s" % (before, len(cfg["sites"]), keys))
    print("[fty] 4k动漫接口: %s" % args.host.rstrip("/"))
    print("[fty] 输出: %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
