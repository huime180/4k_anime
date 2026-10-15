#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 元数据补全（封面 / 简介 / 评分）
============================================
用 Bangumi(番组计划) 的公开搜索接口，按中文番名匹配条目，
取封面图、简介、评分、放送日期，并**补全详情**：
年份 / 地区 / 导演 / 演员（声优）。写入 data/meta.json 作为长期缓存。

缓存键为归一化后的番名，因此重复运行不会重复请求。

    python3 src/enrich.py                 # 只补缺的（增量）
    python3 src/enrich.py --jobs 8        # 并发 8 路：请求本身很快，慢的是串行等待 + 失败重试
    python3 src/enrich.py --limit 20      # 只跑 20 个（调脚本时用）
    python3 src/enrich.py --all           # 全部重跑（忽略缓存）
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import name_score, normalize_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
ANIME_FILE = os.path.join(DATA_DIR, "anime.json")
META_FILE = os.path.join(DATA_DIR, "meta.json")

BGM_SEARCH = "https://api.bgm.tv/search/subject/%s"
BGM_API = "https://api.bgm.tv/v0"

# Bangumi 没有统一的「地区」字段：先看 infobox，再看 tags，最后靠放送电视台兜底
REGIONS = ("日本", "中国", "美国", "韩国", "中国香港", "中国台湾", "英国", "法国",
           "德国", "泰国", "印度", "加拿大", "澳大利亚", "意大利", "西班牙", "俄罗斯")
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


_PREFER_CURL = [False]      # urllib 一旦被掐断，后面直接走 curl（省一次白等的超时）


def _fetch_json(url, timeout=30):
    """取 JSON：先 urllib；被掐断就退到系统 curl（有就试）

    实测：某些网络/设备上 api.bgm.tv 的 HTTPS 响应会被 CDN 中途掐断
    （IncompleteRead / RemoteDisconnected，Python 的 HTTPS 栈几乎必失败），
    但同一台机器上 curl 稳定成功。CI 里 urllib 正常，走不到 curl 这一步。
    """
    if not _PREFER_CURL[0]:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept": "application/json",
                "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            _PREFER_CURL[0] = True      # 这个网络下 Python 的 HTTPS 栈不可用，别再试

    curl = shutil.which("curl")
    if not curl:
        return None
    try:
        out = subprocess.run(
            [curl, "-sS", "--http1.1", "-m", str(timeout),
             "-H", "User-Agent: " + UA, "-H", "Accept: application/json", url],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout + 10)
        if out.returncode == 0 and out.stdout:
            return json.loads(out.stdout.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        pass
    return None


def bgm_search(keyword, retries=3):
    url = (BGM_SEARCH % urllib.parse.quote(keyword)) + "?" + urllib.parse.urlencode(
        {"type": 2, "responseGroup": "large", "max_results": 5}
    )
    for attempt in range(retries):
        got = _fetch_json(url, timeout=25)
        if got is not None:
            return got
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


def _reachable(url):
    """把不可达的图片 CDN 域名换成主站域名"""
    if not url:
        return url
    return (url.replace("http://lain.bgm.tv", "https://bgm.tv")
               .replace("https://lain.bgm.tv", "https://bgm.tv"))


def bgm_get(path, retries=4):
    """调 Bangumi v0 接口（429/5xx/连接中断都退避重试）

    不开 gzip：部分网络下分块响应会被中途掐断（IncompleteRead），重试多半能成。
    """
    url = BGM_API + path
    for attempt in range(retries):
        got = _fetch_json(url, timeout=30)
        if got is not None:
            return got
        time.sleep(1.2 * (attempt + 1))
    print("    · v0 接口失败 %s（重试 %d 次）" % (path, retries))
    return {}


def infobox_map(detail):
    """把 infobox 拍平成 key -> 字符串"""
    out = {}
    for it in (detail or {}).get("infobox") or []:
        value = it.get("value")
        if isinstance(value, list):
            value = "、".join(str(x.get("v") if isinstance(x, dict) else x) for x in value)
        out[str(it.get("key") or "").strip()] = str(value or "").strip()
    return out


def pick_area(info, detail):
    for key in ("地区", "国家", "国家/地区", "制作国家"):
        if info.get(key):
            return info[key]
    for tag in (detail or {}).get("tags") or []:
        name = str(tag.get("name") or "")
        if name in REGIONS:
            return name
    if info.get("放送电视台") or info.get("播放电视台") or info.get("其他电视台"):
        return "日本"
    return ""


def pick_director(info, persons_list):
    exact = ("导演", "总导演", "监督", "系列监督", "动画导演", "副导演")
    for rel in exact:
        for p in persons_list or []:
            if str(p.get("relation") or "").strip() == rel:
                return str(p.get("name") or "")
    for p in persons_list or []:
        rel = str(p.get("relation") or "")
        if "导演" in rel or "监督" in rel:
            return str(p.get("name") or "")
    return info.get("导演") or info.get("监督") or ""


def pick_actors(chars, limit=12):
    names = []
    for c in chars or []:
        for a in c.get("actors") or []:
            nm = str(a.get("name") or "").strip()
            if nm and nm not in names:
                names.append(nm)
        if len(names) >= limit:
            break
    return "、".join(names[:limit])


def details_of(bgm_id):
    """详情四件套：年份 / 地区 / 导演 / 演员

    details=True 表示**三个接口都拿到了**（不是"问过了"）——
    被 CDN 掐断的那次不算数，下一轮还会重试，否则一次网络抖动就把这部的
    导演/演员永久留空了。
    """
    out = {"year": "", "area": "", "director": "", "actor": "",
           "details": False, "no_cast": False}
    if not bgm_id:
        return out
    detail = bgm_get("/subjects/%s" % bgm_id)
    info = infobox_map(detail)
    persons_list = bgm_get("/subjects/%s/persons" % bgm_id)
    chars = bgm_get("/subjects/%s/characters" % bgm_id)

    date = str((detail or {}).get("date") or "") if isinstance(detail, dict) else ""
    out["year"] = date[:4]
    out["area"] = pick_area(info, detail if isinstance(detail, dict) else {})
    out["director"] = pick_director(
        info, persons_list if isinstance(persons_list, list) else [])
    ac = chars if isinstance(chars, list) else []
    out["actor"] = pick_actors(ac)
    out["details"] = bool(detail) and isinstance(persons_list, list) and isinstance(chars, list)
    out["no_cast"] = isinstance(chars, list) and not chars      # 番组确实没有角色/声优
    return out


def resolve(title, want_details=True):
    """返回一条元数据字典，或 None；want_details=False 时只补封面/简介（快）"""
    for keyword in query_variants(title):
        payload = bgm_search(keyword)
        if not payload.get("list"):
            time.sleep(0.35)
            continue
        cand, score = pick_best(title, payload["list"])
        if cand and score >= 0.5:
            images = cand.get("images") or {}
            rating = cand.get("rating") or {}
            # lain.bgm.tv 在部分网络下不可达，改走主站域名（实测 20/20 可取）
            images = {k: _reachable(v) for k, v in images.items()}
            extra = details_of(cand.get("id")) if want_details else {}
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
                "year": extra.get("year") or (cand.get("air_date") or "")[:4],
                "area": extra.get("area", ""),
                "director": extra.get("director", ""),
                "actor": extra.get("actor", ""),
                "details": bool(extra.get("details")),
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

    def done(k):
        """封面 + 详情都拿过才算补全（details 标记见 details_of）"""
        e = meta.get(k) or {}
        if e.get("miss"):
            return True                      # 没匹配上的别反复试
        if not e.get("image"):
            return False
        if not e.get("bgm_id"):
            return True
        if not e.get("details"):
            return False
        # 拿到过详情，但演员是空的、而且这次不是「本来就没有声优」-> 值得再试一次
        return bool(e.get("actor")) or bool(e.get("no_cast"))

    def only_details(k):
        """已经匹配到番组、只差详情（年份/地区/导演/演员）"""
        e = meta.get(k) or {}
        return bool(e.get("bgm_id")) and not done(k)

    todo = [k for k in keys if not (only_missing and done(k))]
    if limit:
        todo = todo[:limit]
    print("[enrich] 待补全 %d / 共 %d 个番名" % (len(todo), len(keys)))

    jobs = 1
    if "--jobs" in argv:
        jobs = max(1, int(argv[argv.index("--jobs") + 1]))

    lock = threading.Lock()
    stat = {"hit": 0}

    def handle(idx, key):
        """补一个番名：番组已确定的走快路径（只补详情），否则先搜索再补详情"""
        title = keys[key]
        entry = None
        found = None
        if only_details(key):
            # 快路径：不重新搜索，也不重复下载封面/简介
            entry = dict(meta[key])
            try:
                entry.update(details_of(entry["bgm_id"]))
            except Exception as exc:  # noqa: BLE001
                entry["details"] = False          # 下一轮再试
                with lock:
                    print("  [%d/%d] %s -> 详情异常 %s" % (idx, len(todo), title[:24], exc))
            note = "详情 %s / %s / %s" % (entry.get("year") or "-", entry.get("area") or "-",
                                        (entry.get("director") or "-")[:12])
        else:
            try:
                found = resolve(title)
            except Exception as exc:  # noqa: BLE001
                found = None
                with lock:
                    print("  [%d/%d] %s -> 异常 %s" % (idx, len(todo), title[:24], exc))
            note = ("%s (%.2f)" % ((found["name_cn"] or found["bgm_name"])[:22], found["match"])
                    if found else "未匹配")

        with lock:
            if entry is not None:
                meta[key] = entry
                fresh[key] = entry
                stat["hit"] += 1
            elif found:
                meta[key] = found
                fresh[key] = found
                stat["hit"] += 1
            else:
                meta[key] = {"bgm_id": None, "image": "", "miss": True}
            print("  [%d/%d] %-28s -> %s" % (idx, len(todo), title[:28], note))
            if len(fresh) % 25 == 0:
                _save(meta)

    if jobs > 1:
        # Bangumi 单个请求只要几百毫秒，慢的是「失败重试 + 串行等待」，
        # 所以这里允许并发抓；每个 workers 各自独立，meta 写入用锁护住。
        print("[enrich] 并发 %d 路" % jobs)
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(lambda kv: handle(*kv), list(enumerate(todo, 1))))
    else:
        for idx, key in enumerate(todo, 1):
            handle(idx, key)
            time.sleep(0.35)

    _save(meta)
    hit = stat["hit"]
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
