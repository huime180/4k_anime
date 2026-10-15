#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「玩偶哥哥数据站」式静态站（纯 HTML，站点里没有任何解析）。

产出在 public/tvfan/ 下（URL 里带 tvfan 是必须的：饭太硬的 WoGG.playerContent
里有一道 `siteUrl.contains("wogg") || siteUrl.contains("tvfan")` 的校验）。

契约全部来自反编译 csp_WoGGGuard（WoGG.java）里解密出来的选择器，一个字都不改：

  首页    {site}                      必须含「玩偶」字样；卡片在 div.module-lines-list 里
  分类    {site}vodshow/{cid}-----------.html          （分页 {cid}-------{pg}---.html）
  详情    {site}voddetail/{id}.html
  搜索    {site}vodsearch/-------------.html?wd={kw}   （带 query，静态站照发同一页；
                                                       WoGG.searchContent 自己会用标题做 contains 过滤）

  列表卡片: div.module-item
            div.module-item-pic>a   -> href(含 /voddetail/N.html)、title
            img.lazyloaded          -> data-src
            div.module-item-caption span -> vod_year
            div.module-item-text    -> vod_remarks
  详情:     div.video-cover div.module-item-pic img.lazyload -> alt / data-src
            div.video-info-items + span.video-info-itemtitle + div.video-info-item
            p.sqjj_a、div.video-info-aux a、div.video-info-aux > div.tag-link a
            ★ div.module-row-info > a 的 data-clipboard-text = 网盘链接
              （用 https://pan.quark.cn/s/<pwd_id>，Pan.isQuark 认 pan.quark.cn；
                要精确到某个文件就写 .../s/<pwd>#/list/share/<fid>）
  搜索卡片: div.module-search-item
            div.module-item-pic img
            div.video-info-header  h3  a           -> 标题（它按这个 contains 关键词过滤）
            div.video-info-header a.video-serial   -> 备注
"""

from __future__ import annotations

import html
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
PUBLIC_DIR = os.path.join(ROOT, "public")
SITE_DIR = os.path.join(PUBLIC_DIR, "tvfan")      # 路径里带 tvfan（见文件头说明）
ANIME = os.path.join(DATA_DIR, "anime.json")
META = os.path.join(DATA_DIR, "meta.json")
PER_PAGE = 24
BASE_PREFIX = "/4k_anime/tvfan"                   # GitHub Pages 上的路径前缀（生成绝对链接用）

CSS = """body{margin:0;background:#0f1017;color:#e5e5ee;font:14px/1.6 system-ui,-apple-system,"PingFang SC",sans-serif}
header{padding:14px 18px;border-bottom:1px solid #262a38;color:#9fd0ff}
a{color:inherit;text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:14px;padding:16px 18px}
.module-item{background:#191b26;border:1px solid #262a38;border-radius:10px;overflow:hidden}
.module-item-pic img,.module-item-pic>a img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block;background:#232636}
.module-item-text,.module-item-caption{padding:2px 8px;color:#8b90a8;font-size:12px}
.module-item-title{padding:6px 8px 2px;font-size:12.5px}
.video-cover img{width:180px;border-radius:10px}
.video-info-items{padding:0 18px;color:#b9bed0;font-size:13px}
.video-info-itemtitle{color:#8b90a8;margin-right:6px}
p.sqjj_a{padding:0 18px;color:#b9bed0}
.module-row-info{padding:14px 18px}
.module-row-info a{display:inline-block;margin:4px 8px 0 0;padding:6px 12px;border:1px solid #2f3446;border-radius:8px;background:#191b26;color:#9fd0ff}
.module-search-item{display:flex;gap:12px;padding:12px 18px;border-bottom:1px solid #1e2130}
.module-search-item .module-item-pic img{width:96px;border-radius:8px}
.video-info-header h3{margin:0 0 6px;font-size:14px}
.video-serial{color:#8b90a8;font-size:12px}
"""


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def rel(url: str) -> str:
    """封面地址：远程图直接用，占位图落到 GitHub Pages 的 cover/ 下。"""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return url
    return "/4k_anime/" + url.lstrip("./")


def pic_of(item, meta) -> str:
    key = "".join(ch for ch in str(item.get("name", "")).lower() if ch.isalnum())
    info = (meta or {}).get(key) or {}
    return rel(info.get("image") or item.get("vod_pic") or ("cover/%s.png" % item.get("id", "")))


def nid_of(item) -> str:
    """WoGG 里提取 id 的正则是 /voddetail/(\\d+)\\.html —— 只能是数字！

    我们 anime.json 里的 id 是十六进制串，所以站点上用「序号」当 id（详情页本身没变）。
    """
    return str(item.get("_nid", ""))


def card(item, meta) -> str:
    """列表卡片：严格按 WoGG 的选择器来。"""
    return (
        '<div class="module-item">'
        '<div class="module-item-pic">'
        '<a href="%s/voddetail/%s.html" title="%s"><img class="lazyloaded" data-src="%s" alt="%s"></a>'
        '</div>'
        '<div class="module-item-title">%s</div>'
        '<div class="module-item-caption"><span>%s</span></div>'
        '<div class="module-item-text">%s</div>'
        '</div>'
    ) % (BASE_PREFIX, esc(nid_of(item)), esc(item.get("name")), esc(pic_of(item, meta)),
         esc(item.get("name")), esc(item.get("name")),
         esc(item.get("year", "")), esc(remarks(item)))


def remarks(item) -> str:
    return "%s · %s" % (item.get("resolution", ""), item.get("drive_name", ""))


def page(title: str, body: str) -> str:
    return ('<!doctype html><html lang="zh-cn"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><link rel="stylesheet" href="%s/style.css"></head><body>'
            '<header>玩偶哥哥数据站（4K动漫镜像）｜ %s</header>%s</body></html>'
            % (esc(title), BASE_PREFIX, esc(title), body))


def write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main() -> int:
    anime = json.load(open(ANIME, encoding="utf-8"))
    meta = {}
    try:
        meta = json.load(open(META, encoding="utf-8"))
    except OSError:
        pass
    items = anime.get("items", [])
    for i, it in enumerate(items, 1):
        it["_nid"] = i          # 站点上的数字 id（见 nid_of）
    classes = anime.get("classes", [])
    by_top, by_own = {}, {}
    for it in items:
        by_top.setdefault(str(it.get("type_id_top")), []).append(it)
        by_own.setdefault(str(it.get("type_id")), []).append(it)

    shutil.rmtree(SITE_DIR, ignore_errors=True)
    os.makedirs(SITE_DIR, exist_ok=True)

    # 首页：必须含「玩偶」，卡片放在 div.module-lines-list 里
    pick = items[:PER_PAGE]
    write(os.path.join(SITE_DIR, "index.html"),
          page("玩偶哥哥共享站 · 4K动漫",
               '<div class="module-lines-list"><div class="grid">%s</div></div>'
               % "".join(card(i, meta) for i in pick)))
    write(os.path.join(SITE_DIR, "style.css"), CSS)

    # 官方 csp_WoGGGuard 的**分类是写死在 jar 里的**（1电影/2剧集/44臻彩/6短漫剧/
    # 3动漫/4综艺/46纪录片/5音乐），它只会拿这些 id 来请求 vodshow/。所以这 8 个 id
    # 必须有页面（没有就是空白/404），这里把它们映射到我们的数据上。
    def by_rule(rule):
        if rule is None:
            return items
        return [it for it in items if rule(it)] or items      # 兜底给全部，宁可多不可空

    wogg_tabs = {
        "1": lambda it: any(k in str(it.get("category", "")) + str(it.get("group", "")) + str(it.get("name", ""))
                            for k in ("剧场", "电影", "映画")),
        "2": lambda it: any(k in str(it.get("category", "")) + str(it.get("group", ""))
                            for k in ("季", "合集", "TV")),
        "44": lambda it: "4K" in str(it.get("resolution", "")).upper(),
        "6": lambda it: any(k in str(it.get("name", "")) + str(it.get("category", "")) for k in ("短", "漫剧")),
        "3": None,      # 动漫 = 全部
        "4": None,      # 综艺（我们没有这类，兜底全部）
        "46": None,     # 纪录片（同上）
        "5": None,      # 音乐（同上）
    }

    # 分类页：两种横线形态都生成（分页参数可能为空、也可能是 1..N）
    for c in classes:
        cid = str(c.get("type_id"))
        rows = by_own.get(cid) or by_top.get(cid) or []
        pages = max(1, (len(rows) + PER_PAGE - 1) // PER_PAGE)
        for p in range(1, pages + 1):
            chunk = rows[(p - 1) * PER_PAGE: p * PER_PAGE]
            body = '<div class="module-lines-list"><div class="grid">%s</div></div>' % "".join(card(i, meta) for i in chunk)
            text = page(c.get("type_name", cid), body)
            write(os.path.join(SITE_DIR, "vodshow", "%s-------%d---.html" % (cid, p)), text)
            if p == 1:
                # 分页参数为空时 jar 请求的是 11 个横线那一版
                write(os.path.join(SITE_DIR, "vodshow", "%s-----------.html" % cid), text)

    # 官方分类 id（写死在 csp_WoGGGuard 里）也要有页面
    for cid, rule in wogg_tabs.items():
        rows = by_rule(rule)
        pages = max(1, (len(rows) + PER_PAGE - 1) // PER_PAGE)
        for p in range(1, pages + 1):
            chunk = rows[(p - 1) * PER_PAGE: p * PER_PAGE]
            body = '<div class="module-lines-list"><div class="grid">%s</div></div>' % "".join(card(i, meta) for i in chunk)
            text = page("分类 " + cid, body)
            write(os.path.join(SITE_DIR, "vodshow", "%s-------%d---.html" % (cid, p)), text)
            if p == 1:
                write(os.path.join(SITE_DIR, "vodshow", "%s-----------.html" % cid), text)

    # 详情页：播放链接写在 div.module-row-info > a 的 data-clipboard-text 里
    for it in items:
        share = "https://pan.quark.cn/s/%s" % it.get("pwd_id", "")
        info = ""
        for label, value in (("备注：", remarks(it)), ("年代：", it.get("year", "")),
                             ("类型：", it.get("group") or it.get("category", "")),
                             ("导演：", ""), ("主演：", "")):
            info += ('<div class="video-info-item"><span class="video-info-itemtitle">%s</span>%s</div>'
                     % (esc(label), esc(value)))
        aux = ('<div class="video-info-aux"><div class="tag-link"><a href="#">%s</a></div>'
               '<a class="tag-link" href="#">%s</a></div>'
               % (esc(it.get("category", "")), esc(it.get("group", ""))))
        body = (
            '<div class="video-cover"><div class="module-item-pic">'
            '<img class="lazyload" alt="%s" data-src="%s"></div></div>'
            '<h1>%s</h1>'
            '<div class="video-info-items">%s</div>%s'
            '<p class="sqjj_a">%s</p>'
            '<div class="module-row-info">'
            '<a href="#" data-clipboard-text="%s">复制夸克链接</a>'
            '</div>'
        ) % (esc(it.get("name")), esc(pic_of(it, meta)), esc(it.get("name")), info, aux,
             esc(it.get("summary", "")), esc(share))
        write(os.path.join(SITE_DIR, "voddetail", "%s.html" % nid_of(it)), page(it.get("name", ""), body))

    # 搜索页：静态站只能给同一页，WoGG.searchContent 会自己按标题 contains 过滤
    srows = "".join(
        '<div class="module-search-item"><div class="module-item-pic">'
        '<img data-src="%s" alt="%s"></div>'
        '<div class="video-info-header"><h3><a href="%s/voddetail/%s.html">%s</a></h3>'
        '<a class="video-serial">%s</a></div></div>'
        % (esc(pic_of(i, meta)), esc(i.get("name")), BASE_PREFIX, esc(nid_of(i)),
           esc(i.get("name")), esc(remarks(i)))
        for i in items)
    write(os.path.join(SITE_DIR, "vodsearch", "-------------.html"),
          page("搜索", '<div class="module-lines-list">%s</div>' % srows))

    n = sum(len(fs) for _, _, fs in os.walk(SITE_DIR))
    print("✅ 玩偶哥哥式静态站 -> %s（%d 个文件，%d 条）" % (SITE_DIR, n, len(items)))
    print("   站点地址示例： %s/  （ext.siteUrl 就填这个，路径里必须带 tvfan）" % BASE_PREFIX)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
