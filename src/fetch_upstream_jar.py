#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把饭太硬官方 jar 同步到 work/merge/fty，供 build_spider.sh 合并我们的类。

饭太硬官方配置里的 "spider" 字段就是 jar 地址，而且**伪装成 .jpg**
（`https://xxx/posters/xxxx.jpg;md5;<md5>`）——下载下来其实是标准 zip/jar。

用法:
    python3 src/fetch_upstream_jar.py            # 从官方配置里取地址并同步
    python3 src/fetch_upstream_jar.py --url <jar[;md5;xx]> [--dest work/merge/fty]

失败时**不覆盖**已有目录（构建脚本会继续用现有 jar），退出码 1。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_fty  # noqa: E402

DEST_DEFAULT = os.path.join(ROOT, "work", "merge", "fty")
INFO = os.path.join(ROOT, "data", "upstream.json")


def split_md5(spec: str):
    """'url;md5;xxxx' -> (url, 'xxxx')"""
    parts = spec.split(";md5;")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip().lower()
    return spec.strip(), ""


def download(url: str, timeout=120) -> bytes:
    groups = [None, {"http": fetch_fty.LOCAL_PROXY, "https": fetch_fty.LOCAL_PROXY}]
    last = None
    for proxy in groups:
        opener = (urllib.request.build_opener(urllib.request.ProxyHandler(proxy))
                  if proxy else urllib.request.build_opener())
        for hdr in ({"User-Agent": fetch_fty.UA, "Accept": "*/*"}, None):
            try:
                req = urllib.request.Request(url, headers=hdr or {})
                with opener.open(req, timeout=timeout) as resp:
                    return resp.read()
            except Exception as exc:  # noqa: BLE001
                last = "%s: %s" % (type(exc).__name__, str(exc)[:80])
            time.sleep(0.5)
    raise RuntimeError("下载失败（最后一次：%s）" % last)


def upstream_spec(source="official") -> str:
    try:
        cfg, src = fetch_fty.load_base(source)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("拿不到官方配置（%s）" % exc)
    spec = str(cfg.get("spider") or "")
    if not spec:
        raise RuntimeError("官方配置里没有 spider 字段")
    print("[up] 官方配置来源: %s" % src)
    return spec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="直接给 jar 地址（可带 ;md5;xx），默认从官方配置里取")
    ap.add_argument("--dest", default=DEST_DEFAULT)
    ap.add_argument("--source", default="official", choices=["auto", "official", "mirror"])
    args = ap.parse_args()

    try:
        spec = args.url or upstream_spec(args.source)
        url, want = split_md5(spec)
        print("[up] jar: %s" % url)
        raw = download(url)
        got = hashlib.md5(raw).hexdigest()
        if want and got != want:
            raise RuntimeError("md5 不符：期望 %s，实际 %s" % (want, got))
        if raw[:2] != b"PK":
            raise RuntimeError("不是 zip/jar（前 4 字节 %r）" % raw[:4])
        tmp = args.dest + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        open(os.path.join(tmp, "upstream.jar"), "wb").write(raw)
        with zipfile.ZipFile(os.path.join(tmp, "upstream.jar")) as z:
            names = z.namelist()
            if "classes.dex" not in names:
                raise RuntimeError("jar 里没有 classes.dex：%s" % names)
            z.extractall(tmp)
        os.remove(os.path.join(tmp, "upstream.jar"))
        shutil.rmtree(args.dest, ignore_errors=True)
        os.makedirs(os.path.dirname(args.dest), exist_ok=True)
        shutil.move(tmp, args.dest)
    except Exception as exc:  # noqa: BLE001
        print("[up] ⚠️ 同步失败（%s）——保留现有 work/merge/fty，不重建 jar" % exc)
        return 1

    guard = os.path.join(args.dest, "assets", "ftyshinidie.guard")
    info = {
        "url": url, "md5": got, "bytes": len(raw),
        "classes_dex_bytes": os.path.getsize(os.path.join(args.dest, "classes.dex")),
        "guard_md5": hashlib.md5(open(guard, "rb").read()).hexdigest() if os.path.exists(guard) else "",
        "guard_bytes": os.path.getsize(guard) if os.path.exists(guard) else 0,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }
    os.makedirs(os.path.dirname(INFO), exist_ok=True)
    with open(INFO, "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    print("[up] ✅ 同步到 %s（%d 字节，guard %d 字节）" % (args.dest, len(raw), info["guard_bytes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
