#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检 public/tvfan/ 是否符合 csp_WoGGGuard 的抓取契约（选择器全部来自反编译结果）。

为什么要这个：A 线路不再用我们自己的 jar，而是让**官方的 csp_WoGGGuard** 直接抓我们
这个静态站（siteUrl 指过来）。页面结构一旦和它的选择器不一致，线路就会「有分类没内容」
或者干脆空白，而且 App 里看不出原因 —— 所以放进 CI，每次生成后自检。
"""

from __future__ import annotations

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "public", "tvfan")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def need(cond, msg):
    print(("✅ " if cond else "❌ ") + msg)
    return bool(cond)


def main() -> int:
    ok = True
    if not os.path.isdir(SITE):
        print("❌ 找不到 %s，先跑 python3 src/build_site.py" % SITE)
        return 1

    # 1) 首页：WoGG.homeContent 会检查响应里有没有「玩偶」两个字
    home = read(os.path.join(SITE, "index.html"))
    ok &= need("玩偶" in home, "首页含「玩偶」字样（homeContent 的校验）")
    ok &= need('class="module-lines-list"' in home, "首页有 div.module-lines-list")
    cards = re.findall(r'<div class="module-item">.*?</div>\s*</div>', home, re.S)
    ok &= need(len(cards) >= 1, "首页 div.module-item 卡片 %d 个" % len(cards))
    ok &= need(re.search(r'class="module-item-pic">\s*<a href="[^"]*/voddetail/(\d+)\.html" title="[^"]+"', home) is not None,
               "卡片里有 div.module-item-pic>a（href 含 /voddetail/N.html + title）")
    ok &= need(re.search(r'<img class="lazyloaded" data-src="[^"]+"', home) is not None,
               "卡片里有 img.lazyloaded[data-src]")
    ok &= need('class="module-item-caption"><span>' in home and 'class="module-item-text"' in home,
               "卡片里有 div.module-item-caption span / div.module-item-text")

    # 2) 分类页：两种横线形态都要在（分页参数可能为空、也可能是 1..N）
    for name in ("vodshow/1-----------.html", "vodshow/1-------1---.html"):
        p = os.path.join(SITE, name)
        if not os.path.exists(p):
            ok &= need(False, "分类页存在：%s" % name)
            continue
        t = read(p)
        n = len(re.findall(r'<div class="module-item">', t))
        ok &= need(n >= 1, "分类页 %s 有 %d 张卡片（div.module-item）" % (name, n))
    listed = sorted(glob.glob(os.path.join(SITE, "vodshow", "*.html")))
    ok &= need(len(listed) >= 20, "分类页共 %d 个（含分页）" % len(listed))

    # 3) 详情页：封面/简介/分类标签 + 最关键的 data-clipboard-text 网盘链接
    details = sorted(glob.glob(os.path.join(SITE, "voddetail", "*.html")))
    ok &= need(len(details) >= 100, "详情页 %d 个" % len(details))
    d = read(details[0])
    ok &= need(re.search(r'div class="video-cover".*?<img class="lazyload" alt="[^"]+" data-src="[^"]+"', d, re.S) is not None,
               "详情页封面：div.video-cover ... img.lazyload[alt][data-src]")
    ok &= need('class="video-info-items"' in d and 'class="video-info-itemtitle"' in d and 'class="video-info-item"' in d,
               "详情页信息块：div.video-info-items / span.video-info-itemtitle / div.video-info-item")
    ok &= need('class="sqjj_a"' in d, "详情页简介 p.sqjj_a")
    ok &= need('class="video-info-aux"' in d, "详情页分类标签 div.video-info-aux")
    m = re.search(r'<div class="module-row-info">\s*<a href="#" data-clipboard-text="([^"]+)"', d)
    ok &= need(m is not None and "pan.quark.cn" in (m.group(1) if m else ""),
               "详情页播放链接：div.module-row-info > a[data-clipboard-text] 且含 pan.quark.cn")

    # 4) 搜索页：Static 站给同一页，WoGG 自己按标题 contains 过滤
    sp = os.path.join(SITE, "vodsearch", "-------------.html")
    if not os.path.exists(sp):
        ok &= need(False, "搜索页存在：vodsearch/-------------.html（13 个横线）")
    else:
        s = read(sp)
        items = len(re.findall(r'<div class="module-search-item">', s))
        ok &= need(items >= 100, "搜索页 div.module-search-item %d 个" % items)
        ok &= need(re.search(r'<div class="video-info-header">\s*<h3>\s*<a href="[^"]*/voddetail/\d+\.html">[^<]+</a>', s) is not None,
                   "搜索卡片：[div.video-info-header] h3 a 标题")
        ok &= need('class="video-serial"' in s, "搜索卡片：a.video-serial 备注")
        ok &= need(re.search(r'<div class="module-item-pic">\s*<img data-src="[^"]+"', s) is not None,
                   "搜索卡片：div.module-item-pic img[data-src]")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
