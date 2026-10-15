#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 把合集里的条目改指到「二级目录」
==========================================
「每周更新」是**一季一个大文件夹**：一个夸克分享里装着几十部番
（10 个分享装了 216 条条目）。表格里每一行的链接都指向**整个分享**，
所以点开哪一部看到的都是整季的剧集。

这一步在同步之后跑一次，**只做一件事**：匿名列一次目录（申请分享令牌 + 列目录
都不需要登录），把每个条目对应的**二级目录**（分享根 -> 季度合集 -> **番剧目录**）
拼进链接：

    https://pan.quark.cn/s/<pwd>#/list/share/<二级目录的 fid>

再往下（三级目录 = 同一部的分季/分 Part）就**不再细分**了：同一系列放一起看就行。

注意：站点里只有数据，取流/转存/登录全部由 jar 里饭太硬那套负责。

用法:
    python3 src/subfolder.py            # 只处理还没改过的
    python3 src/subfolder.py --all      # 全部重算
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
PUBLIC_DIR = os.path.join(ROOT, "public")
TREE_DIR = os.path.join(PUBLIC_DIR, "tree")     # 目录树（静态数据）
SHARE_DIR = os.path.join(PUBLIC_DIR, "share")   # 每个合集的「目录 + 正片清单」（给播放用）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from names import normalize_name  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "quark-cloud-drive/3.14.2 Chrome/112.0.5615.165 Electron/24.4.1 Safari/537.36")
TOKEN_API = "https://drive-h.quark.cn/1/clouddrive/share/sharepage/token"
DETAIL_API = "https://drive-h.quark.cn/1/clouddrive/share/sharepage/detail"
SHARE_URL = "https://pan.quark.cn/s/%s#/list/share/%s"

_TRIM = re.compile(r"(?i)(合集|全系列|番剧合集|剧场版|总集篇)")
_TRAD2SIMP = str.maketrans({
    "長": "长", "黃": "黄", "銀": "银", "戰": "战", "雙": "双", "術": "术", "劍": "剑",
    "馬": "马", "鳥": "鸟", "島": "岛", "強": "强", "飛": "飞", "會": "会", "體": "体",
    "樂": "乐", "樣": "样", "魚": "鱼", "點": "点", "蟲": "虫", "夢": "梦", "覺": "觉",
    "讓": "让", "麗": "丽", "灣": "湾", "萬": "万", "與": "与", "為": "为", "亂": "乱",
    "爭": "争", "於": "于", "這": "这", "來": "来", "們": "们", "個": "个", "時": "时",
    "間": "间", "關": "关", "開": "开", "問": "问", "過": "过", "還": "还", "進": "进",
    "遠": "远", "運": "运", "達": "达", "邊": "边", "適": "适", "選": "选", "錢": "钱",
    "鐵": "铁", "錄": "录", "鐘": "钟", "陽": "阳", "陰": "阴", "難": "难", "雲": "云",
    "電": "电", "靜": "静", "項": "项", "順": "顺", "願": "愿", "類": "类", "風": "风",
    "飯": "饭", "驗": "验", "髮": "发", "鬥": "斗", "魯": "鲁", "鮮": "鲜", "鳴": "鸣",
    "鴻": "鸿", "齊": "齐", "齒": "齿", "龜": "龟", "龍": "龙", "宮": "宫", "國": "国",
    "學": "学", "對": "对", "將": "将", "師": "师", "帶": "带", "歸": "归", "氣": "气",
    "聲": "声", "書": "书", "葉": "叶", "語": "语", "說": "说", "讀": "读", "誰": "谁",
    "軍": "军", "農": "农", "輕": "轻", "轉": "转", "車": "车", "連": "连", "週": "周",
    "鋼": "钢", "鏡": "镜", "閉": "闭", "誰": "谁", "驗": "验",
})
_SEASON = re.compile(r"(?i)(?<![a-z0-9])(s\d{1,2}|season\s*\d{1,2})(?![0-9])"
                     r"|第\s*[0-9一二三四五六七八九十]{1,3}\s*[期季部]")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_SEASON_NUM = re.compile(r"第\s*([0-9一二三四五六七八九十]+)\s*[期季部]"
                         r"|(?<![a-z])(?:s|season)\s*([0-9]{1,2})(?![0-9])", re.I)


def _json(url, body=None, timeout=25, retries=3):
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            headers={"User-Agent": UA, "Accept": "application/json",
                     "Content-Type": "application/json"} if body is not None
            else {"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (attempt + 1))
    raise last if last else RuntimeError("请求失败: " + url)


def listdir(pwd_id, stoken, pdir_fid="0"):
    """列目录（每页最多 50 条，要翻页）"""
    out = []
    for page in range(1, 21):
        q = urllib.parse.urlencode({
            "pr": "ucpro", "fr": "pc", "pwd_id": pwd_id, "stoken": stoken,
            "pdir_fid": pdir_fid, "force": "0", "_page": page, "_size": 50,
            "__dt": 1, "__t": int(time.time() * 1000)})
        got = ((_json(DETAIL_API + "?" + q) or {}).get("data") or {}).get("list") or []
        out.extend(got)
        if len(got) < 50:
            break
    return out


# 这层有视频/压缩包 -> 是正片目录；一个都没有 -> 是合集，继续往里
MEDIA_EXT = (".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".rmvb", ".flv", ".wmv", ".mov",
             ".iso", ".mpg", ".mpeg", ".webm", ".zip", ".rar", ".7z", ".tar", ".gz")


def _is_media(name):
    return str(name or "").lower().endswith(MEDIA_EXT)


def collect_share(pwd_id, stoken, max_depth=8):
    """一次遍历同时收：目录树 + 每个目录里的正片

    返回 (dirs, files)：
      dirs  = {fid: {"n": 名字, "p": 上级 fid}}
      files = [{"fid","n","s","tk","p","t","c","d"}]  —— 就是夸克列目录给的
              fid / 文件名 / 大小 / share_fid_token / pdir_fid，外加所在目录名 d
    （共享链接下不需要登录：令牌 + 列目录都是匿名的）
    """
    dirs = {"0": {"n": "分享根目录", "p": ""}}
    files = []

    def walk(fid, depth, dir_name):
        if depth > max_depth:
            return
        try:
            entries = listdir(pwd_id, stoken, fid)
        except Exception:  # noqa: BLE001
            return
        dirs_here = [e for e in entries if e.get("dir")]
        if not (depth > 1 and any(_is_media(e.get("file_name")) for e in entries)):
            for entry in dirs_here:            # 没有正片 -> 这层是合集，继续往里
                child = entry.get("fid") or ""
                name = entry.get("file_name") or ""
                dirs[child] = {"n": name, "p": fid}
                walk(child, depth + 1, name)
        for entry in entries:
            if entry.get("dir") or not _is_media(entry.get("file_name")):
                continue
            files.append({"fid": entry.get("fid") or "", "n": entry.get("file_name") or "",
                          "s": entry.get("size") or 0, "tk": entry.get("share_fid_token") or "",
                          "p": entry.get("pdir_fid") or fid, "t": entry.get("format_type") or "",
                          "c": entry.get("created_at") or 0, "d": dir_name})

    walk("0", 1, "")
    return dirs, files


def second_level(pwd_id):
    """分享里的**二级目录**：分享根 -> 季度合集 -> 番剧目录（再往里不看）"""
    stoken = ((_json(TOKEN_API, {"pwd_id": pwd_id, "passcode": ""}) or {}).get("data") or {}).get("stoken") or ""
    roots = [e for e in listdir(pwd_id, stoken) if e.get("dir")]
    if len(roots) != 1:
        return roots and [(e.get("fid"), e.get("file_name") or "") for e in roots] or []
    kids = [e for e in listdir(pwd_id, stoken, roots[0].get("fid")) if e.get("dir")]
    return [(e.get("fid"), e.get("file_name") or "") for e in kids]


def _norm(text):
    s = _TRIM.sub("", str(text or ""))
    s = re.sub(r"[\[\(（【][^\]\)）】]*[\]\)）】]", "", s)
    s = re.sub(r"^\s*\d{1,4}\s*[.\-_、 ]\s*", "", s)
    s = _SEASON.sub("", s)
    s = re.sub(r"[\s\-_~·・:：,，。.、!！?？/\\|+&'’]+", "", s)
    return s.translate(_TRAD2SIMP).lower()


def _season(text):
    m = _SEASON_NUM.search(str(text or ""))
    if not m:
        return 0
    raw = m.group(1) or m.group(2) or ""
    return int(raw) if raw.isdigit() else _CN_NUM.get(raw, 0)


def _variants(item, entry):
    """表格名 + Bangumi 别名（目录常写成英文/日文原名）"""
    out = []
    aliases = (entry or {}).get("aliases") or ""
    for raw in [item.get("name") or "", aliases]:
        for piece in re.split(r"[、/／|]", raw):
            piece = piece.strip()
            for cand in (piece, _TRIM.sub("", piece)):
                n = _norm(cand)
                if len(n) >= 2 and n not in out:
                    out.append(n)
    return out


def _score(variants, folder, want_season=0):
    hay = _norm(folder)
    if not hay:
        return 0.0
    best = 0.0
    for v in variants:
        if v == hay:
            best = max(best, 3.0)
        elif v in hay or (hay in v and len(hay) >= 2):
            best = max(best, 1 + 0.4 * len(hay) / max(len(hay), len(v)))
        elif len(v) >= 6 and v[:6] in hay:
            best = max(best, 0.6)
    if best <= 0:
        return 0.0
    got = _season(folder)
    if want_season and got:
        best += 2 if got == want_season else -1
    return best


def pick(item, entry, folders):
    """在二级目录里挑本条目对应的那个（挑不到返回空）"""
    variants = _variants(item, entry)
    want = _season(item.get("name"))
    best, best_score = "", 0.0
    for fid, name in folders:
        score = _score(variants, name, want)
        if score > best_score:
            best, best_score = (fid, name), score
    if best_score >= 0.6:
        return best
    # 兜底：只差一两个字（表格写「章鱼哔」、目录写「章鱼噼」）
    import difflib
    best, best_score = ("", ""), 0.0
    for fid, name in folders:
        hay = _norm(name)
        if not hay:
            continue
        for v in variants:
            if len(v) < 4 or abs(len(hay) - len(v)) > 3:
                continue
            ratio = difflib.SequenceMatcher(None, v, hay).ratio()
            if ratio > best_score:
                best, best_score = (fid, name), ratio
    return best if best_score >= 0.85 else ("", "")


def _near(variants, want, name):
    """近似分（0 起，≥0.6 才算认出）

    三档：
      1) 整名/别名包含（括号、季度后缀、序号都已经在 _norm 里剥掉了）；
      2) 共享**中文**词（≥2 个两字词）+ 词重合度 ≥0.2
         —— 「打史莱姆300年 第二期」对上「打了300年的史莱姆，不知不觉就练到了满级」；
         纯英文的偶合（chiramune ↔ onepunchman）不算；
      3) 只差一两个字（difflib ≥0.7）—— 表格写错字那种。
    季数明确对不上就不猜。
    """
    best = _score(variants, name, want)
    hay = _norm(name)
    if not hay:
        return best
    got = _season(name)
    if want and got and got != want:
        return best

    def bigrams(t):
        return set(t[i:i + 2] for i in range(len(t) - 1))

    def has_cjk(t):
        return any("\u4e00" <= c <= "\u9fff" for c in t)

    hb = bigrams(hay)
    if hb:
        for v in variants:
            vb = bigrams(_norm(v))
            if not vb:
                continue
            shared = vb & hb
            shared_cjk = [x for x in shared if has_cjk(x)]
            ov = len(shared) / float(len(vb | hb))
            if len(shared_cjk) >= 2 and ov >= 0.2:
                best = max(best, ov * 3.2)
            if len(v) >= 4 and abs(len(hay) - len(v)) <= 3:
                import difflib
                ratio = difflib.SequenceMatcher(None, v, hay).ratio()
                if ratio >= 0.7:
                    best = max(best, ratio * 3.0)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全部重算（默认只处理没改过的）")
    args = ap.parse_args()

    anime_path = os.path.join(DATA_DIR, "anime.json")
    with open(anime_path, encoding="utf-8") as fh:
        anime = json.load(fh)
    meta_path = os.path.join(DATA_DIR, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)

    counts = {}
    for item in anime.get("items", []):
        pwd = item.get("pwd_id") or ""
        counts[pwd] = counts.get(pwd, 0) + 1
    groups = {}
    for item in anime.get("items", []):
        pwd = item.get("pwd_id") or ""
        if pwd and counts[pwd] > 1:
            groups.setdefault(pwd, []).append(item)

    print("[subfolder] 合集分享 %d 个，共 %d 条条目"
          % (len(groups), sum(len(v) for v in groups.values())))

    # ---------- 1) 先把每个合集的「目录 + 清单」收下来 ----------
    os.makedirs(TREE_DIR, exist_ok=True)
    os.makedirs(SHARE_DIR, exist_ok=True)
    data, failed = {}, 0
    for pwd, items in groups.items():
        if not args.all and all("#/list/share/" in (it.get("share_url") or "") for it in items):
            man_path = os.path.join(SHARE_DIR, pwd + ".json")
            if os.path.exists(man_path):
                man = json.load(open(man_path, encoding="utf-8"))
                data[pwd] = man
                continue
        try:
            tk = (_json(TOKEN_API, {"pwd_id": pwd, "passcode": ""}) or {}).get("data") or {}
            stoken = tk.get("stoken") or ""
            dirs_all, files = collect_share(pwd, stoken)
            tops = [f for f, v in dirs_all.items() if v.get("p") == "0" and f != "0"]
            if len(tops) == 1:                       # 拍平「季度合集」那层
                wrapper = tops[0]
                for info in dirs_all.values():
                    if info.get("p") == wrapper:
                        info["p"] = "0"
                dirs_all.pop(wrapper, None)
            dirs_all.setdefault("0", {"n": "分享根目录", "p": ""})
            man = {"pwd": pwd, "stoken": stoken, "author": tk.get("author") or "",
                   "title": tk.get("title") or "", "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "dirs": dirs_all, "files": files}
            with open(os.path.join(TREE_DIR, pwd + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"pwd": pwd, "synced_at": man["synced_at"], "dirs": dirs_all},
                          fh, ensure_ascii=False)
            with open(os.path.join(SHARE_DIR, pwd + ".json"), "w", encoding="utf-8") as fh:
                json.dump(man, fh, ensure_ascii=False)
            data[pwd] = man
        except Exception as exc:  # noqa: BLE001
            failed += len(items)
            print("  ! %s 列目录失败：%s（保留原链接）" % (pwd, exc))
        time.sleep(0.2)

    # 每个分享的二级目录（含上级是根的那些）
    level2 = {}
    for pwd, man in data.items():
        level2[pwd] = [(f, v["n"]) for f, v in man["dirs"].items()
                       if v.get("p") == "0" and f != "0"]

    # 独立分享（只有一个条目）里的同名条目：兜底改指过去用
    singles = {}
    for it in anime.get("items", []):
        pwd = it.get("pwd_id") or ""
        if pwd and counts[pwd] == 1:
            singles.setdefault(normalize_name(it.get("name") or ""), it)

    # ---------- 2) 匹配：本包精确 -> 本包近似（所有层级都算候选） ----------
    hit = miss = 0
    for pwd, items in groups.items():
        man = data.get(pwd)
        if not man:
            miss += len(items)
            continue
        # 候选：优先只认**二级目录**（分享根下面那一层）；二级目录都认不出来时，
        # 才往下一层看（有些番藏在「合集」里面，比如 148.银魂合集/3年Z班 银八老师）
        level2 = [(f, v["n"]) for f, v in man["dirs"].items() if v.get("p") == "0" and f != "0"]
        deeper = [(f, v["n"]) for f, v in man["dirs"].items()
                  if v.get("p") not in ("0", "") and f != "0"]
        for item in items:
            e = meta.get(normalize_name(item.get("name") or "")) or {}
            vs, want = _variants(item, e), _season(item.get("name"))
            best, got = -1.0, None
            for fid, name in level2:
                sc = _near(vs, want, name)
                if sc > best:
                    best, got = sc, (fid, name)
            if best < 0.6:
                for fid, name in deeper:
                    sc = _near(vs, want, name)
                    if sc > best:
                        best, got = sc, (fid, name)
            if got is not None and best >= 0.6:
                fid, name = got
                item["subfolder"] = name
                if fid:
                    item["subfolder_fid"] = fid
                item["share_url"] = SHARE_URL % (pwd, fid)
                item.pop("subfolder_fix", None)
                hit += 1
            else:
                item["share_url"] = "https://pan.quark.cn/s/" + pwd
                item.pop("subfolder", None)
                item.pop("subfolder_fid", None)
                miss += 1
                print("      · 没认出：%-30s（本包最高 %.2f %s）"
                      % (item["name"][:30], best if best > 0 else 0,
                         (got[1][:26] if got else "-")))
    with open(anime_path, "w", encoding="utf-8") as fh:
        json.dump(anime, fh, ensure_ascii=False)
    print("[subfolder] 定位到二级目录 %d ｜ 没认出 %d ｜ 列目录失败 %d" % (hit, miss, failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
