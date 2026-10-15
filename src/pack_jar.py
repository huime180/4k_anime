#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可复现地打包 jar（固定条目顺序 + 固定时间戳 + 固定压缩级别）。

为什么需要：配置里写的是 `jar 地址;md5;<md5>`，App 靠这个判断要不要重新下载。
而 `jar cf` 会把**当前时间**写进 zip 条目 —— 同样的内容每次构建 md5 都不一样，
于是「配置里的 md5」和「线上的 jar」稍有缓存差异就对不上，App 会判定校验失败、
拒绝加载 spider（表现就是所有线路没有分类）。这里改成确定性打包，内容不变 md5 就不变。

用法: python3 src/pack_jar.py <pack目录> <输出jar> [成员...]
"""

from __future__ import annotations

import os
import sys
import zipfile

FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def main(argv) -> int:
    if len(argv) < 3:
        print("用法: pack_jar.py <pack目录> <输出jar> [成员...]")
        return 2
    root, out = argv[1], argv[2]
    members = argv[3:]
    if not members:
        found = []
        for dirpath, _, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                found.append(os.path.relpath(p, root))
        members = sorted(found)
    members = sorted(set(members))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        for m in members:
            p = os.path.join(root, m)
            if not os.path.exists(p):
                print("⚠️ 跳过不存在的成员：%s" % m)
                continue
            zi = zipfile.ZipInfo(m.replace(os.sep, "/"), date_time=FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            with open(p, "rb") as fh:
                z.writestr(zi, fh.read())
    print("✅ %s（%d 个成员，%d 字节）" % (out, len(members), os.path.getsize(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
