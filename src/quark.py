#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 夸克网盘解析
========================
只用标准库实现夸克公开分享的读取与取流。

实测结论（2026-10）:
  * 申请分享令牌   POST /1/clouddrive/share/sharepage/token   —— 匿名可调用
  * 列目录         GET  /1/clouddrive/share/sharepage/detail  —— 匿名可调用
  * 转存到自己网盘 POST /1/clouddrive/share/sharepage/save    —— 需要登录 Cookie
  * 取直链         POST /1/clouddrive/file/download           —— 需要登录 Cookie
    未登录返回: {"status":401,"code":31001,"message":"require login [guest]"}

因此「浏览/分类/封面/剧集列表」完全免登录；只有最后一步「取可播放直链」需要
用户自己的夸克 Cookie（__puus）。请把 Cookie 放在环境变量 QUARK_COOKIE 或
config.json 中，切勿提交到仓库。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "cache")

PC = "https://drive-pc.quark.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

VIDEO_EXT = (".mp4", ".mkv", ".ts", ".m2ts", ".avi", ".flv", ".webm",
             ".mov", ".wmv", ".rmvb", ".mpg", ".mpeg", ".iso", ".m4v")
SUB_EXT = (".ass", ".srt", ".ssa", ".sub", ".idx", ".sup", ".vtt")


class QuarkError(RuntimeError):
    """夸克接口错误基类"""


class QuarkAuthError(QuarkError):
    """需要登录（缺少或失效的 Cookie）"""


class QuarkNotFound(QuarkError):
    """分享不存在 / 已失效"""


# --------------------------------------------------------------------------- #
# 名称匹配（把表格里的番名对齐到网盘里的文件夹名）
# --------------------------------------------------------------------------- #
_NUM_PREFIX = re.compile(r"^\s*\d{1,4}\s*[.\-_、 ]\s*")
_BRACKET = re.compile(r"[\[\(（【][^\]\)）】]*[\]\)）】]")
_SEASON = re.compile(r"(?i)\b(s\d{1,2}|season\s*\d{1,2})\b|第\s*\d{1,3}\s*[期季部]")
_NOISE = re.compile(r"[\s\-_~·・:：,，。.、!！?？/\\|+&]+")


def normalize_name(name):
    """把番名压成便于比对的骨架"""
    s = str(name or "").strip()
    s = _BRACKET.sub("", s)
    s = _NUM_PREFIX.sub("", s)
    s = _SEASON.sub("", s)
    s = _NOISE.sub("", s)
    return s.lower()


def name_score(a, b):
    """0~1 的相似度；优先包含关系，其次编辑距离"""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
        return 0.75 + 0.25 * (len(short) / len(long_))
    import difflib
    return difflib.SequenceMatcher(None, na, nb).ratio()


def is_video(name):
    return str(name).lower().endswith(VIDEO_EXT)


def natural_key(text):
    """自然排序：第2集 < 第10集"""
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", str(text))]


# --------------------------------------------------------------------------- #
# 磁盘缓存
# --------------------------------------------------------------------------- #
class _Cache:
    def __init__(self, ttl_list=600, ttl_stoken=1800):
        self.ttl_list = ttl_list
        self.ttl_stoken = ttl_stoken
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, key):
        safe = re.sub(r"[^0-9a-zA-Z_.-]", "_", key)[:120]
        return os.path.join(CACHE_DIR, safe + ".json")

    def get(self, key, ttl):
        path = self._path(key)
        try:
            with open(path, encoding="utf-8") as fh:
                blob = json.load(fh)
            if time.time() - blob.get("_t", 0) <= ttl:
                return blob.get("v")
        except (OSError, ValueError):
            pass
        return None

    def set(self, key, value):
        path = self._path(key)
        try:
            with self._lock:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump({"_t": time.time(), "v": value}, fh, ensure_ascii=False)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
class Quark:
    def __init__(self, cookie="", timeout=25, cache=None, saved_dir="4k_anime"):
        self.cookie = (cookie or "").strip()
        self.timeout = timeout
        self.cache = cache or _Cache()
        self.saved_dir = saved_dir
        self._saved_dir_fid = None
        self._lock = threading.Lock()

    # ---------------- 底层请求 ---------------- #
    def _request(self, path, params=None, body=None, method=None, retries=2):
        url = PC + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        headers = {
            "User-Agent": UA,
            "Referer": "https://pan.quark.cn/",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://pan.quark.cn",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie

        last = None
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method=method or ("POST" if data else "GET"))
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                payload = exc.read().decode("utf-8", "replace")
                last = (exc.code, payload)
                if exc.code == 401:
                    raise QuarkAuthError(
                        "夸克要求登录（%s）。请配置 QUARK_COOKIE。" % _brief(payload)
                    )
                if exc.code == 404:
                    raise QuarkNotFound("夸克接口 404：%s" % path)
                if exc.code in (429, 500, 502, 503) and attempt < retries:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise QuarkError("夸克 HTTP %s：%s" % (exc.code, _brief(payload)))
            except (urllib.error.URLError, TimeoutError) as exc:
                last = ("net", str(exc))
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise QuarkError("夸克网络错误：%s" % exc)
        raise QuarkError("夸克请求失败：%s" % (last,))

    # ---------------- 分享令牌 ---------------- #
    def stoken(self, pwd_id, passcode=""):
        key = "stoken_%s_%s" % (pwd_id, passcode)
        hit = self.cache.get(key, self.cache.ttl_stoken)
        if hit:
            return hit
        resp = self._request(
            "/1/clouddrive/share/sharepage/token",
            {"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            {"pwd_id": pwd_id, "passcode": passcode or ""},
        )
        if resp.get("status") != 200 or not (resp.get("data") or {}).get("stoken"):
            code = resp.get("code")
            msg = resp.get("message") or ""
            if code in (41003, 41004, 41006) or "share" in msg.lower():
                raise QuarkNotFound("分享不可用（%s %s）" % (code, msg))
            raise QuarkError("申请令牌失败：%s %s" % (code, msg))
        data = resp["data"]
        value = {
            "stoken": data["stoken"],
            "title": data.get("title") or "",
            "author": (data.get("author") or {}).get("nick_name") or "",
            "expired_at": data.get("expired_at"),
        }
        self.cache.set(key, value)
        return value

    # ---------------- 列目录 ---------------- #
    def list_dir(self, pwd_id, pdir_fid="0", stoken=None, page=1, size=200):
        info = stoken if isinstance(stoken, dict) else self.stoken(pwd_id)
        resp = self._request(
            "/1/clouddrive/share/sharepage/detail",
            {
                "pr": "ucpro", "fr": "pc", "pwd_id": pwd_id,
                "stoken": info["stoken"], "pdir_fid": pdir_fid, "force": "0",
                "_page": page, "_size": size,
                "_fetch_banner": "1", "_fetch_share": "1", "_fetch_total": "1",
                "_sort": "file_type:asc,file_name:asc",
            },
        )
        if resp.get("status") != 200:
            raise QuarkError("列目录失败：%s %s" % (resp.get("code"), resp.get("message")))
        data = resp.get("data") or {}
        return data.get("list") or [], data.get("share") or {}

    def list_all(self, pwd_id, pdir_fid="0", stoken=None):
        """翻页取完一个目录"""
        info = stoken if isinstance(stoken, dict) else self.stoken(pwd_id)
        out, page = [], 1
        while page <= 20:
            chunk, _ = self.list_dir(pwd_id, pdir_fid, info, page=page)
            if not chunk:
                break
            out.extend(chunk)
            if len(chunk) < 200:
                break
            page += 1
        out.sort(key=lambda f: (not f.get("dir"), natural_key(f.get("file_name", ""))))
        return out

    def cached_list(self, pwd_id, pdir_fid="0"):
        key = "list_%s_%s" % (pwd_id, pdir_fid)
        hit = self.cache.get(key, self.cache.ttl_list)
        if hit is not None:
            return hit
        files = self.list_all(pwd_id, pdir_fid)
        self.cache.set(key, files)
        return files

    # ---------------- 递归找剧集 ---------------- #
    def _child_dirs(self, pwd_id, fid):
        return [f for f in self.cached_list(pwd_id, fid) if f.get("dir")]

    def _find_best_dir(self, pwd_id, fid, item_name, depth=0, max_depth=3, top=8):
        """在分享树里找与番名最匹配的子目录。

        分享通常有一到两层包装目录（分享根 -> 整季合集 -> 单部番），所以不能只
        看根目录：先在本层挑最像的；本层都不像时，单目录就继续下钻，多目录则
        每个各试一次，最后取全局最高分。
        """
        dirs = self._child_dirs(pwd_id, fid)
        if not dirs or depth > max_depth:
            return None, 0.0
        scored = sorted(((d, name_score(item_name, d.get("file_name", ""))) for d in dirs),
                        key=lambda x: x[1], reverse=True)
        best, best_score = scored[0]
        if best_score >= 0.45:
            return best, best_score
        if len(dirs) == 1:
            return self._find_best_dir(pwd_id, dirs[0]["fid"], item_name,
                                       depth + 1, max_depth, top)
        found = []
        for d, _ in scored[:top]:
            sub, sc = self._find_best_dir(pwd_id, d["fid"], item_name,
                                          depth + 1, max_depth, top)
            if sub is not None:
                found.append((sub, sc))
        if found:
            return max(found, key=lambda x: x[1])
        return None, 0.0

    def collect_episodes(self, pwd_id, item_name=None, max_depth=6, limit=600):
        """收集一个分享里的全部视频文件。

        item_name 非空时先按番名定位子目录（「每周更新」整季合集：一个分享里放了
        很多部番的文件夹），定位失败则退回整个分享。
        """
        info = self.stoken(pwd_id)
        start_fid, matched = "0", ""
        if item_name:
            best, _score = self._find_best_dir(pwd_id, "0", item_name)
            if best is not None:
                start_fid, matched = best["fid"], best.get("file_name", "")

        episodes, seen = [], set()

        def walk(fid, path, depth):
            if depth > max_depth or len(episodes) >= limit:
                return
            try:
                files = self.cached_list(pwd_id, fid)
            except QuarkError:
                return
            for f in files:
                if len(episodes) >= limit:
                    return
                name = f.get("file_name", "")
                if f.get("dir"):
                    walk(f["fid"], path + [name], depth + 1)
                elif is_video(name) and f["fid"] not in seen:
                    seen.add(f["fid"])
                    episodes.append({
                        "fid": f["fid"],
                        "file_name": name,
                        "size": f.get("size") or 0,
                        "share_fid_token": f.get("share_fid_token") or "",
                        "path": "/".join(path),
                        "duration": f.get("duration") or 0,
                    })

        walk(start_fid, [], 0)
        episodes.sort(key=lambda e: natural_key(e["file_name"]))
        return {
            "pwd_id": pwd_id,
            "title": info.get("title") or "",
            "author": info.get("author") or "",
            "matched_dir": matched,
            "episodes": episodes,
        }

    # ---------------- 取直链（需登录） ---------------- #
    def _saved_fid(self, pwd_id, fid, share_token):
        """把分享里的文件转存到自己网盘，返回转存后的 fid（带缓存）"""
        ck = "saved_%s_%s" % (pwd_id, fid)
        hit = self.cache.get(ck, 86400 * 7)
        if hit:
            return hit

        to_fid = self._ensure_dir()
        resp = self._request(
            "/1/clouddrive/share/sharepage/save",
            {"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            {
                "fid_list": [fid],
                "fid_token_list": [share_token] if share_token else [],
                "to_pdir_fid": to_fid,
                "pwd_id": pwd_id,
                "stoken": self.stoken(pwd_id)["stoken"],
                "pdir_fid": "0",
                "scene": "link",
                "create_zip": False,
            },
        )
        if resp.get("status") != 200:
            raise QuarkError("转存失败：%s %s" % (resp.get("code"), resp.get("message")))
        task_id = (resp.get("data") or {}).get("task_id")
        if not task_id:
            raise QuarkError("转存未返回 task_id")
        new_fid = self._wait_task(task_id)
        if not new_fid:
            raise QuarkError("转存任务未产出文件")
        self.cache.set(ck, new_fid)
        return new_fid

    def _wait_task(self, task_id, tries=15):
        for i in range(tries):
            resp = self._request(
                "/1/clouddrive/task",
                {"pr": "ucpro", "fr": "pc", "task_id": task_id, "retry_index": i},
            )
            data = resp.get("data") or {}
            if resp.get("status") != 200:
                raise QuarkError("查询任务失败：%s %s" % (resp.get("code"), resp.get("message")))
            if data.get("status") == 2:
                fids = ((data.get("save_as") or {}).get("save_as_top_fids")) or []
                if fids:
                    return fids[0]
            time.sleep(0.6)
        return None

    def _ensure_dir(self, name=None, parent="0"):
        """确保自己网盘里有 4k_anime 目录，返回其 fid"""
        if self._saved_dir_fid and parent == "0":
            return self._saved_dir_fid
        target = name or self.saved_dir
        resp = self._request("/1/clouddrive/file/sort",
                             {"pr": "ucpro", "fr": "pc", "pdir_fid": parent,
                              "_page": 1, "_size": 200,
                              "_fetch_total": 1, "_sort": "file_type:asc,file_name:asc"})
        for f in ((resp.get("data") or {}).get("list") or []):
            if f.get("dir") and f.get("file_name") == target:
                if parent == "0":
                    self._saved_dir_fid = f["fid"]
                return f["fid"]
        created = self._request("/1/clouddrive/file",
                                {"pr": "ucpro", "fr": "pc"},
                                {"pdir_fid": parent, "file_name": target, "dir_path": "",
                                 "file_type": 0, "dir": True})
        fid = (created.get("data") or {}).get("fid")
        if not fid:
            raise QuarkError("创建目录失败：%s" % created.get("message"))
        if parent == "0":
            self._saved_dir_fid = fid
        return fid

    def direct_url(self, pwd_id, fid, share_token=""):
        """返回可播放的直链（会先把分享文件转到自己网盘）"""
        if not self.cookie:
            raise QuarkAuthError("未配置 QUARK_COOKIE，无法取流")
        own_fid = self._saved_fid(pwd_id, fid, share_token)
        resp = self._request("/1/clouddrive/file/download",
                             {"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
                             {"fids": [own_fid]})
        if resp.get("status") != 200:
            raise QuarkError("取直链失败：%s %s" % (resp.get("code"), resp.get("message")))
        for ent in (resp.get("data") or []):
            if ent.get("download_url"):
                return ent["download_url"]
        raise QuarkError("未返回 download_url")


def _brief(payload, n=120):
    return re.sub(r"\s+", " ", str(payload))[:n]


def client_from_env():
    cookie = os.environ.get("QUARK_COOKIE", "")
    cfg_path = os.path.join(ROOT, "config.json")
    if not cookie and os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                cookie = (json.load(fh) or {}).get("quark_cookie", "")
        except (OSError, ValueError):
            pass
    return Quark(cookie=cookie)
