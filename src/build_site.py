#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 生成「玩偶哥哥式」静态站
==================================
目标：让饭太硬 jar 里的 csp_WoGGGuard 能直接抓我们这个站。

依据（来自公开的玩偶哥哥抓取配置 json/玩偶哥哥.json）：
    数组   : module-item-pic / module-item-cover
    链接   : href="..."
    副标题 : module-item-text
    分类url: /index.php/vodshow/{cateId}-{area}-{by}-{class}-{lang}-{letter}---{catePg}---{year}.html
    搜索url: /index.php/vodsearch/-------------.html?wd={wd}
    分类   : 电影$1#剧集$2#综艺$4#动漫$3#短剧$6#音乐$5

因为 WoGG 详情页的抽取规则是字符串加密的、无法直接读，所以详情页把夸克分享
链接放在**多个可能被识别的位置**（a[href] / data-* / 可见文本），提高命中率。

用法:
    python3 src/build_site.py            # 输出到 public/site/
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANIME = os.path.join(ROOT, "data", "anime.json")
META = os.path.join(ROOT, "data", "meta.json")
OUT = os.path.join(ROOT, "public", "site")

# 饭太硬那边的分类编号（对应它的 分类url 模板）
CATE_IDS = {"电影": 1, "剧集": 2, "动漫": 3, "综艺": 4, "音乐": 5, "短剧": 6}
PAGE_SIZE = 24


def esc(s):
    return html.escape(str(s or ""), quote=True)


def load_meta():
    try:
        with open(META, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def norm(s):
    s = str(s or "")
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"^\s*\d+[.\-_ ]*", "", s)
    s = re.sub(r"(?i)\bs\d{1,2}\b", "", s)
    return re.sub(r"[\s\-_·:：,，。.、]+", "", s).lower()


PAGE_HEAD = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head><body>
<div class="page">
<div class="poster-grid">
"""

PAGE_FOOT = """</div></div>
<div class="module-page">
{pager}
</div>
</body></html>
"""

# 【重要】样式必须走外链：内联 <style> 里的 .module-item-text{} 会被抓取规则
# 当成「副标题」抽出来（实测抽到空串），污染条目解析。
PAGE_CSS = '<link rel="stylesheet" href="/style.css">\n'

STYLE_CSS = """body{background:#12131a;color:#e8e8ef;font:14px/1.5 system-ui,sans-serif;margin:0;padding:12px}
a{color:#9fd0ff;text-decoration:none}
.poster-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:14px}
.poster-cell{background:#1b1d29;border-radius:10px;overflow:hidden}
.poster-cell img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block}
.poster-meta{padding:6px 8px;font-size:12px;color:#8b90a8}
"""


def item_html(it, meta):
    pic = (meta.get(norm(it["name"])) or {}).get("image") or "./cover.png"
    detail = "index.php/voddetail/%s.html" % it["id"]
    return (
        '<div class="module-item-pic module-item-cover">\n'
        '  <a class="module-item-cover" href="%s" title="%s">\n'
        '    <img class="lazyload" data-src="%s" src="%s" alt="%s">\n'
        '    <div class="module-item-text">%s</div>\n'
        '  </a>\n'
        '</div>\n' % (esc(detail), esc(it["name"]), esc(pic), esc(pic),
                      esc(it["name"]),
                      esc("%s · %s" % (it.get("resolution", ""), it.get("drive_name", ""))))
    )


def write(path, body):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(body)


def detail_html(it, eps, meta):
    """详情页：把夸克分享链接撒在多个可能被识别的位置"""
    share = it.get("share_url") or ""
    pic = (meta.get(norm(it["name"])) or {}).get("image") or "/cover.png"
    play_lines = []
    for i, ep in enumerate(eps or [], 1):
        nm = esc(ep.get("file_name") or ("第%02d集" % i))
        # 每个剧集都带上分享链接（饭太硬的 Cloud_quark 认 /s/xxx）
        play_lines.append(
            '<li class="module-play-list-item">'
            '<a href="%s" data-url="%s" data-play="%s" title="%s">%s</a></li>'
            % (esc(share), esc(share), esc(share), nm, nm))
    if not play_lines:
        play_lines.append(
            '<li class="module-play-list-item">'
            '<a href="%s" data-url="%s" data-play="%s">在线播放</a></li>'
            % (esc(share), esc(share), esc(share)))
    return (
        PAGE_HEAD.format(title=esc(it["name"]))
        + '<div class="module-info">\n'
        + '  <img class="module-item-pic" src="%s" alt="%s">\n' % (esc(pic), esc(it["name"]))
        + '  <div class="module-info-item"><span>片名</span>%s</div>\n' % esc(it["name"])
        + '  <div class="module-info-item"><span>画质</span>%s</div>\n' % esc(it.get("resolution", ""))
        + '  <div class="module-info-item"><span>分类</span>%s</div>\n'
          % esc("%s / %s" % (it.get("category", ""), it.get("group", "")))
        + '</div>\n'
        + '<div class="module-play-list"><ul>\n' + "\n".join(play_lines) + '\n</ul></div>\n'
        + '<!-- 供抓取：%s -->\n' % esc(share)
        + '<div class="module-play-url" data-url="%s">%s</div>\n' % (esc(share), esc(share))
        + PAGE_FOOT.format(pager="")
    )


def main():
    with open(ANIME, encoding="utf-8") as fh:
        data = json.load(fh)
    meta = load_meta()
    items = data.get("items") or []
    if not items:
        print("[site] anime.json 里没有条目，先跑 sync_table.py", file=sys.stderr)
        return 1

    os.makedirs(OUT, exist_ok=True)
    for d in ("index.php/vodshow", "index.php/voddetail", "index.php/vodsearch"):
        os.makedirs(os.path.join(OUT, d), exist_ok=True)

    # 顶层分类 -> 条目
    by_top = {}
    for it in items:
        by_top.setdefault(it.get("category") or "其他", []).append(it)

    made_cat = 0
    # 只有「动漫」有明确编号；其余按出现顺序借用空闲编号
    cate_map = {"动漫": 3}
    used = {3}
    for name in by_top:
        if name in cate_map:
            continue
        for cid in (1, 2, 4, 5, 6, 7, 8, 9):
            if cid not in used:
                cate_map[name] = cid
                used.add(cid)
                break

    for name, group in by_top.items():
        cid = cate_map.get(name, 3)
        pages = (len(group) + PAGE_SIZE - 1) // PAGE_SIZE
        for pg in range(1, pages + 1):
            chunk = group[(pg - 1) * PAGE_SIZE: pg * PAGE_SIZE]
            pager = " ".join(
                '<a href="index.php/vodshow/%d----------%d---.html">%d</a>' % (cid, p, p)
                for p in range(1, pages + 1))
            body = (PAGE_HEAD.format(title=esc(name))
                    + PAGE_CSS
                    + "".join(item_html(it, meta) for it in chunk)
                    + PAGE_FOOT.format(pager=pager))
            write("index.php/vodshow/%d----------%d---.html" % (cid, pg), body)
            made_cat += 1

    # 详情页（剧集列表从 data/cache 里取不到就留空，播放链接仍带上）
    made_det = 0
    for it in items:
        write("index.php/voddetail/%s.html" % it["id"], detail_html(it, [], meta))
        made_det += 1

    # 搜索页（静态兜底：列出全部，让搜索规则至少有东西可抓）
    allbody = (PAGE_HEAD.format(title="全部") + PAGE_CSS
               + "".join(item_html(it, meta) for it in items[:300])
               + PAGE_FOOT.format(pager=""))
    write("index.php/vodsearch/-------------.html", allbody)
    write("index.html", (PAGE_HEAD.format(title="4K动漫") + PAGE_CSS
                         + "".join(item_html(it, meta) for it in items[:120])
                         + PAGE_FOOT.format(pager="")))

    write("style.css", STYLE_CSS)
    print("[site] 分类页 %d 个（%d 个分类）" % (made_cat, len(by_top)))
    print("[site] 详情页 %d 个" % made_det)
    print("[site] 搜索页 + 首页")
    print("[site] 分类编号: %s" % cate_map)
    print("[site] 输出: %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
