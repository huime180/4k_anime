#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 元数据补全（封面 / 简介 / 评分）
============================================
用 Bangumi(番组计划) 的公开搜索接口，按中文番名匹配条目，
取封面图、简介、评分、放送日期，写入 data/meta.json 作为长期缓存。

缓存键为归一化后的番名，因此重复运行不会重复请求。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quark import name_score, normalize_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
ANIME_FILE = os.path.join(DATA_DIR, "anime.json")
META_FILE = os.path.join(DATA_DIR, "meta.json")

BGM_SEARCH = "https://api.bgm.tv/search/subject/%s"
UA = "dsh-4k-anime/1.0 (https://github.com/huime180/4k_anime)"

# 番名里需要剥掉、但不利于搜索的尾巴
_TRIM = re.compile(
    r"(?i)(剧场版|总集篇|合集|TV动画|第\s*\d+\s*[期季部]|part\s*\d+|"
    r"\bs\d{1,2}\b|season\s*\d+|\b重制版\b|\bOVA\b|\bOAD\b|\bSP\b|\bBD\b|\b4K\b)"
)


def query_variants(title):
    """由粗到细分几档搜索词，提高命中率"""
    raw = str(title or "").strip()
    out = []

    def push(value):
        value = re.sub(r"\s+", " ", value).strip(" -_/·、")
        if value and value not in out:
            out.append(value)

    push(raw)
    push(_TRIM.sub(" ", raw))
    # 「A/B/C」这种并列名，先取最长的一段
    for piece in re.split(r"[/／|]", raw):
        if len(piece.strip()) >= 2:
            push(_TRIM.sub(" ", piece))
    push(re.sub(r"[（(].*?[)）]", " ", raw))
    if out:
        push(out[-1].split()[0] if out[-1].split() else out[-1])
    # 去掉副标题（空格或「～」之后的部分）
    push(re.split(r"[~～::]", out[0])[0] if out else raw)
    return out


def bgm_search(keyword, retries=3):
    url = (BGM_SEARCH % urllib.parse.quote(keyword)) + "?" + urllib.parse.urlencode(
        {"type": 2, "responseGroup": "large", "max_results": 5}
    )
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503):
                time.sleep(2.0 * (attempt + 1))
                continue
            return {}
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return {}


def pick_best(title, candidates):
    best, best_score = None, 0.0
    for cand in candidates or []:
        names = [cand.get("name_cn") or "", cand.get("name") or ""]
        names += [a for a in (cand.get("alias") or [])]
        score = max((name_score(title, n) for n in names if n), default=0.0)
        if score > best_score:
            best, best_score = cand, score
    return best, best_score


def resolve(title):
    """返回一条元数据字典，或 None"""
    for keyword in query_variants(title):
        payload = bgm_search(keyword)
        if not payload.get("list"):
            time.sleep(0.35)
            continue
        cand, score = pick_best(title, payload["list"])
        if cand and score >= 0.5:
            images = cand.get("images") or {}
            rating = cand.get("rating") or {}
            return {
                "bgm_id": cand.get("id"),
                "bgm_name": cand.get("name") or "",
                "name_cn": cand.get("name_cn") or "",
                "image": images.get("common") or images.get("medium") or images.get("large") or "",
                "image_large": images.get("large") or "",
                "summary": (cand.get("summary") or "").strip(),
                "score": rating.get("score"),
                "rank": rating.get("rank"),
                "date": cand.get("air_date") or "",
                "match": round(score, 3),
                "keyword": keyword,
            }
        time.sleep(0.35)
    return None


def main():
    argv = sys.argv[1:]
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    only_missing = "--all" not in argv

    with open(ANIME_FILE, encoding="utf-8") as fh:
        anime = json.load(fh)

    meta = {}
    if os.path.exists(META_FILE):
        try:
            with open(META_FILE, encoding="utf-8") as fh:
                meta = json.load(fh)
        except ValueError:
            meta = {}

    fresh = {}
    keys = {}
    for item in anime["items"]:
        key = normalize_name(item["name"])
        if not key:
            continue
        keys.setdefault(key, item["name"])

    todo = [k for k in keys if not (only_missing and meta.get(k))]
    if limit:
        todo = todo[:limit]
    print("[enrich] 待补全 %d / 共 %d 个番名" % (len(todo), len(keys)))

    hit = 0
    for idx, key in enumerate(todo, 1):
        title = keys[key]
        try:
            found = resolve(title)
        except Exception as exc:  # noqa: BLE001
            print("  [%d/%d] %s -> 异常 %s" % (idx, len(todo), title[:24], exc))
            found = None
        if found:
            meta[key] = found
            fresh[key] = found
            hit += 1
            print("  [%d/%d] %-28s -> %s (%.2f)" % (
                idx, len(todo), title[:28], (found["name_cn"] or found["bgm_name"])[:22],
                found["match"]))
        else:
            meta[key] = {"bgm_id": None, "image": "", "miss": True}
            print("  [%d/%d] %-28s -> 未匹配" % (idx, len(todo), title[:28]))
        if idx % 25 == 0:
            _save(meta)
        time.sleep(0.35)

    _save(meta)
    ok = sum(1 for v in meta.values() if v.get("image"))
    print("[enrich] 本轮命中 %d/%d；累计有封面 %d/%d"
          % (hit, len(todo), ok, len(meta)))
    return 0


def _save(meta):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(META_FILE, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    raise SystemExit(main())
