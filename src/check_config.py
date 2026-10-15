#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置自检：配置里写的 csp_X，jar 的 dex 里必须真有 Lcom/github/catvod/spider/X;

这个坑踩过两次（api 写 csp_Quark4K 但 jar 里只有 Anime4KGuard → 影视仓导入即报错），
所以放进 Action，提交前跑一遍，不一致就直接失败。

用法: python3 src/check_config.py [配置...]   缺省检查 config/ 下所有 *.json
"""

from __future__ import annotations

import glob
import json
import os
import re
import struct
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAR = os.path.join(ROOT, "jar", "4k_anime_fty_merged.jar")

# 这些类是**我们**加的，缺了就是硬错误；饭太硬自家的 csp_*Guard 缺了只提示
# （官方配置里就有 csp_XPathGuard 而官方 jar 里也没有，app 会跳过那一条线）
OUR_CLASSES = {"Anime4KGuard"}


def dex_classes(blob: bytes) -> set:
    string_ids_size, string_ids_off, type_ids_size, type_ids_off = struct.unpack_from("<4I", blob, 56)
    class_defs_size, class_defs_off = struct.unpack_from("<2I", blob, 96)

    def s_at(i):
        off = struct.unpack_from("<I", blob, string_ids_off + 4 * i)[0]
        n, q = 0, off
        while True:
            b = blob[q]
            q += 1
            n = (n << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        return blob[q:q + n].decode("utf-8", "replace")

    types = [s_at(struct.unpack_from("<I", blob, type_ids_off + 4 * i)[0]) for i in range(type_ids_size)]
    return {types[struct.unpack_from("<I", blob, class_defs_off + 32 * i)[0]]
            for i in range(class_defs_size)}


def main(argv):
    if not os.path.exists(JAR):
        print("❌ 找不到 %s" % JAR)
        return 1
    have = dex_classes(zipfile.ZipFile(JAR).read("classes.dex"))
    files = argv[1:] or sorted(glob.glob(os.path.join(ROOT, "config", "*.json")))
    bad, warn, checked = [], [], 0
    for path in files:
        try:
            cfg = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError) as exc:
            bad.append("%s: 不是合法 JSON（%s）" % (path, exc))
            continue
        for site in cfg.get("sites") or []:
            m = re.fullmatch(r"csp_(\w+)", str(site.get("api", "")))
            if not m:
                continue
            cls = "Lcom/github/catvod/spider/%s;" % m.group(1)
            checked += 1
            if cls in have:
                continue
            msg = "%s: %s 需要 %s，但 jar 里没有" % (os.path.basename(path), site.get("api"), cls)
            (bad if m.group(1) in OUR_CLASSES else warn).append(msg)
    for w in warn:
        print("⚠️  " + w + "（饭太硬自家的线路，app 会跳过）")
    for b in bad:
        print("❌ " + b)
    if bad:
        return 1
    print("✅ 配置与 jar 一致（检查了 %d 个 csp_ 站点，jar 共 %d 个类）" % (checked, len(have)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
