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

import http.cookiejar
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "cache")

PC = "https://drive-pc.quark.cn"
# 【实测关键】必须用夸克 PC 客户端的 UA：
#   用浏览器 UA 调 /file/download 会返回 400 "download file size limit"，
#   换成 quark-cloud-drive 后大文件（1.8GB）直接 200。
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) quark-cloud-drive/3.14.2 Chrome/112.0.5615.165 "
      "Electron/24.4.1 Safari/537.36")
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
# 转码档位优先级：raw=原画质流，low=低码率兜底
PLAY_RESOLUTIONS = ("raw", "low")

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

    def delete(self, key):
        try:
            os.remove(self._path(key))
        except OSError:
            pass

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
        # 【实测关键】必须复用会话 Cookie（__pugs）：取流地址由 CDN 校验会话，
        # 不带着它去请求会直接 412 Precondition Failed。
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))

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
                with self._opener.open(req, timeout=self.timeout) as resp:
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
    def _fid_is_file(self, own_fid, want_name=""):
        """判断 fid 是否真是 4k_anime/ 里的一个文件（不是文件夹）。

        实测 /1/clouddrive/file 的返回结构与文档不一致，用目录列表判断最稳。
        """
        if not own_fid:
            return False
        try:
            for f in self.list_saved():
                if f.get("fid") == own_fid:
                    return not f.get("dir")
        except QuarkError:
            return False
        return False

    def _find_saved(self, want_name, want_size=0):
        """在 4k_anime/ 里定位转存后的文件。

        优先按**精确大小**匹配（最可靠，文件名可能被改名/转义），大小对不上再退回名字比对。
        """
        files = self.list_saved()
        if want_size:
            for f in files:
                if f.get("size") == want_size:
                    return f.get("fid")
        if want_name:
            nal = re.sub(r"\s+", " ", str(want_name)).strip()
            for f in files:
                if re.sub(r"\s+", " ", str(f.get("file_name") or "")).strip() == nal:
                    return f.get("fid")
        return None

    def _is_dir_fid(self, own_fid):
        """判断任务返回的 fid 是不是目标文件夹。

        注意：目录列表有延迟，**列表里找不到 ≠ 是文件夹**，不能据此判死，
        只有明确是 dir 或等于保存目录本身才算。
        """
        if not own_fid:
            return True
        try:
            if self._saved_dir_fid and own_fid == self._saved_dir_fid:
                return True
            for f in self.list_saved():
                if f.get("fid") == own_fid:
                    return bool(f.get("dir"))
        except QuarkError:
            pass
        return False

    def _save_to_temp(self, pwd_id, fid, share_token, want_name="", want_size=0):
        """转存到一次性子目录，返回 (文件fid, 子目录fid)。

        为什么不用固定目录：夸克对「刚删又存同一个文件」有竞态 —— save 任务会返回
        已经删掉的那个死 fid（实测成功率只有 1/2）。每次换一个全新子目录就完全
        绕开去重，实测 4/4 成功。这就是玩偶哥哥敢「拿完就删」的原因。
        """
        root = self._ensure_dir()
        made = self._request("/1/clouddrive/file", {"pr": "ucpro", "fr": "pc"},
                             {"pdir_fid": root,
                              "file_name": "r%d" % int(time.time() * 1000),
                              "dir_path": "", "dir_init_lock": False})
        sub_fid = (made.get("data") or {}).get("fid")
        if not sub_fid:
            raise QuarkError("创建临时目录失败：%s" % made.get("message"))

        resp = self._request(
            "/1/clouddrive/share/sharepage/save",
            {"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
            {"fid_list": [fid],
             "fid_token_list": [share_token] if share_token else [],
             "to_pdir_fid": sub_fid, "pwd_id": pwd_id,
             "stoken": self.stoken(pwd_id)["stoken"], "pdir_fid": "0",
             "pdir_save_all": False, "exclude_fids": [], "scene": "link",
             "create_zip": False})
        if resp.get("status") != 200:
            raise QuarkError("转存失败：%s %s" % (resp.get("code"), resp.get("message")))
        task_id = (resp.get("data") or {}).get("task_id")
        if not task_id:
            raise QuarkError("转存未返回 task_id")

        new_fid = self._wait_task(task_id)
        if new_fid and self._is_dir_fid(new_fid):
            new_fid = None
        if not new_fid:
            for _ in range(10):
                got = self._request("/1/clouddrive/file/sort",
                                    {"pr": "ucpro", "fr": "pc", "pdir_fid": sub_fid,
                                     "_page": 1, "_size": 50, "_fetch_total": 1,
                                     "_sort": "file_type:asc,file_name:asc"})
                for f in ((got.get("data") or {}).get("list") or []):
                    if not f.get("dir"):
                        new_fid = f["fid"]
                        break
                if new_fid:
                    break
                time.sleep(1.0)
        if not new_fid:
            self._drop_temp(sub_fid)
            raise QuarkError("转存后未能定位到文件%s"
                             % (("（%s）" % want_name[:40]) if want_name else ""))
        return new_fid, sub_fid

    def _drop_temp(self, sub_fid):
        """删掉一次性子目录（连同里面的文件）"""
        if not sub_fid:
            return
        try:
            self._request("/1/clouddrive/file/delete", {"pr": "ucpro", "fr": "pc"},
                          {"action_type": 2, "filelist": [sub_fid],
                           "exclude_fids": []})
        except QuarkError:
            pass

    def _saved_fid(self, pwd_id, fid, share_token, want_name="", want_size=0):
        """把分享里的文件转存到自己网盘，返回转存后的文件 fid（带缓存）"""
        ck = "saved_%s_%s" % (pwd_id, fid)
        hit = self.cache.get(ck, 86400 * 7)
        if hit:
            try:
                info = self._request("/1/clouddrive/file",
                                     {"pr": "ucpro", "fr": "pc", "fids": hit})
                for ent in ((info.get("data") or {}).get("list") or []):
                    if not ent.get("dir"):
                        return hit
            except QuarkError:
                pass
            self.cache.delete(ck)

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
                "pdir_save_all": False,
                "exclude_fids": [],
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

        # 任务给的 fid 有时是目标文件夹，需要在 4k_anime/ 里按大小/名字重新定位
        if not (new_fid and self._fid_is_file(new_fid)):
            for _ in range(8):
                found = self._find_saved(want_name, want_size)
                if found:
                    new_fid = found
                    break
                time.sleep(1.0)
        if not (new_fid and self._fid_is_file(new_fid)):
            raise QuarkError("转存后未能定位到文件%s"
                             % (("（%s）" % want_name[:40]) if want_name else ""))
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
                save_as = data.get("save_as") or {}
                fids = (save_as.get("save_as_top_fids")
                        or save_as.get("save_as_select_top_fids") or [])
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
                                {"pdir_fid": parent, "file_name": target,
                                 "dir_path": "", "dir_init_lock": False})
        fid = (created.get("data") or {}).get("fid")
        if not fid:
            raise QuarkError("创建目录失败：%s" % created.get("message"))
        if parent == "0":
            self._saved_dir_fid = fid
        return fid

    def _play_stream(self, own_fid, resolution=None):
        """取夸克转码播放流；返回 (url, resolution)，失败返回 (None, 原因)"""
        reason = ""
        for res in ((resolution,) if resolution else PLAY_RESOLUTIONS):
            try:
                resp = self._request(
                    "/1/clouddrive/file/play",
                    {"pr": "ucpro", "fr": "pc", "fid": own_fid, "resolution": res},
                )
            except QuarkError as exc:
                reason = str(exc)
                continue
            data = resp.get("data") or {}
            for item in (data.get("video_list") or []):
                url = (item or {}).get("url")
                if url:
                    return url, res
            reason = str(resp.get("message") or resp.get("status"))
        return None, reason

    def _file_exists(self, own_fid):
        try:
            resp = self._request("/1/clouddrive/file",
                                 {"pr": "ucpro", "fr": "pc", "fids": own_fid})
        except QuarkError:
            return False
        return bool(((resp.get("data") or {}).get("list")))

    # 画质档位：原画=源文件直链（全分辨率）；智能=夸克转码流（更省带宽）
    QUALITY_RAW, QUALITY_SMART = "raw", "smart"

    def resolve_raw(self, own_fid, purge=True):
        """原画：file/download 直链，就是源文件本身（3840x2160 不会再被缩）。

        实测：转存后拿到直链，**把转存文件删掉链接依然有效**（玩偶哥哥就是这么做的），
        所以默认 purge=True，拿完就删，不占用户网盘空间。
        """
        resp = self._request("/1/clouddrive/file/download",
                             {"pr": "ucpro", "fr": "pc", "uc_param_str": ""},
                             {"fids": [own_fid]})
        url = ""
        for ent in (resp.get("data") or []):
            if ent.get("download_url"):
                url = ent["download_url"]
                break
        if not url:
            raise QuarkError("原画取链失败：%s" % (resp.get("message") or resp.get("status")))
        if purge:
            try:
                self._request("/1/clouddrive/file/delete",
                              {"pr": "ucpro", "fr": "pc"},
                              {"action_type": 2, "filelist": [own_fid],
                               "exclude_fids": []})
            except QuarkError:
                pass
        return url

    def resolve_smart(self, own_fid):
        """智能：夸克转码流。转码是异步的，需要文件在网盘里存在一会儿。"""
        url, reason = None, ""
        for attempt in range(8):
            url, reason = self._play_stream(own_fid)
            if url:
                return url
            time.sleep(1.5 if attempt < 4 else 3.0)
        raise QuarkError("智能档转码未就绪：%s" % (reason or "unknown"))

    # 解析结果缓存：玩偶哥哥反编译出来的字段就叫 lastQuarkPlayUrl / lastQuarkDownloadUrl，
    # 说明它会把上次解析到的地址留着复用，省掉每次 2 秒多的转存+取链。
    PLAY_CACHE_TTL = 1800

    def _cached_play(self, key):
        return self.cache.get("play_" + key, self.PLAY_CACHE_TTL)

    def _cache_play(self, key, url):
        self.cache.set("play_" + key, url)

    def direct_url(self, pwd_id, fid, share_token="", quality=QUALITY_RAW,
                   file_name="", file_size=0):
        """把分享里的某个文件解析成「播放器能拉」的地址。

        实测出的正确顺序（顺序错了大文件就播不了）:
          1. 先转存到自己网盘 —— /file/play 对分享文件直接 500，
             且 /file/download 对分享文件一律 400 download file size limit；
          2. GET /file/play?resolution=raw -> data.video_list[].url
             这是夸克自己转好的流，播放器最友好；
          3. 转码是异步的，刚转存完可能还没有 video_list，退回 /file/download
             （必须用 PC 客户端 UA，否则报大小限制）。
        """
        if not self.cookie:
            raise QuarkAuthError("未配置 QUARK_COOKIE，无法取流")
        ck = "%s_%s_%s" % (pwd_id, fid, quality)
        hit = self._cached_play(ck)
        if hit:
            return hit
        if quality == self.QUALITY_SMART:
            own = self._saved_fid(pwd_id, fid, share_token, file_name, file_size)
            for _ in range(10):
                if self._file_exists(own):
                    break
                time.sleep(0.8)
            return self.resolve_smart(own)

        # 原画档：一次性子目录 -> 取链 -> **立刻删**（玩偶哥哥的做法，不留空间）
        if quality == self.QUALITY_RAW:
            last = None
            for _ in range(3):
                sub = None
                try:
                    own_fid, sub = self._save_to_temp(pwd_id, fid, share_token,
                                                      file_name, file_size)
                    url = self.resolve_raw(own_fid, purge=False)
                    self._cache_play(ck, url)
                    return url
                except QuarkError as exc:
                    last = exc
                    time.sleep(0.8)
                finally:
                    self._drop_temp(sub)
            raise last or QuarkError("取流失败")

        last_error = None
        for round_no in range(2):
            own_fid = self._saved_fid(pwd_id, fid, share_token, file_name, file_size)

            # 转存刚完成时文件可能还不可见，先等它出现
            for _ in range(8):
                if self._file_exists(own_fid):
                    break
                time.sleep(0.8)
            else:
                self.cache.delete("saved_%s_%s" % (pwd_id, fid))
                last_error = QuarkError("转存文件不可见")
                continue

            # 原画优先：源文件直链，全分辨率。
            # 注：这里**不能**立刻删转存 —— 删了之后夸克去重会把已删除的 fid
            # 再返回给你，下次播放就 404。所以交给 janitor 按 SAVE_TTL 清理。
            try:
                return self.resolve_raw(own_fid, purge=False)
            except QuarkNotFound:
                self.cache.delete("saved_%s_%s" % (pwd_id, fid))
                last_error = QuarkError("转存记录已失效")
                continue
            except QuarkError as exc:
                last_error = exc

            # 退回转码流
            url, reason = self._play_stream(own_fid)
            if url:
                return url
            last_error = QuarkError("原画与转码都失败：%s / %s"
                                    % (last_error, reason or "-"))
            break
        raise last_error or QuarkError("取流失败")

    def list_saved(self):
        """列出自己网盘 4k_anime/ 里转存的文件"""
        fid = self._ensure_dir()
        resp = self._request("/1/clouddrive/file/sort",
                             {"pr": "ucpro", "fr": "pc", "pdir_fid": fid,
                              "_page": 1, "_size": 200,
                              "_fetch_total": 1,
                              "_sort": "file_type:asc,file_name:asc"})
        return [f for f in ((resp.get("data") or {}).get("list") or [])
                if not f.get("dir")]

    def purge_older_than(self, seconds):
        """删掉 4k_anime/ 里超过 seconds 秒的转存文件（智能档转码需要文件留存一会儿）"""
        files = self.list_saved()
        cutoff = time.time() * 1000 - seconds * 1000
        stale = [f for f in files if (f.get("created_at") or f.get("updated_at") or 0) < cutoff]
        if not stale:
            return 0
        self._request("/1/clouddrive/file/delete", {"pr": "ucpro", "fr": "pc"},
                      {"action_type": 2, "filelist": [f["fid"] for f in stale],
                       "exclude_fids": []})
        return len(stale)

    def clear_saved(self):
        """清空 4k_anime/ 转存目录，返回删除数量"""
        files = self.list_saved()
        if not files:
            return 0
        self._request("/1/clouddrive/file/delete", {"pr": "ucpro", "fr": "pc"},
                      {"action_type": 2, "filelist": [f["fid"] for f in files],
                       "exclude_fids": []})
        return len(files)

    def account_info(self):
        """读取账号信息（用于「我的云盘」状态显示；无 Cookie 返回 {}）"""
        if not self.cookie:
            return {}
        try:
            resp = self._request("/1/clouddrive/member",
                                 {"pr": "ucpro", "fr": "pc", "uc_param_str": ""})
        except QuarkError:
            return {}
        if resp.get("status") != 200:
            return {}
        return resp.get("data") or {}

    # 并发拉流节点数：实测 3 个不同 CDN 节点并发可达单节点 1.8x 吞吐
    # （玩偶哥哥抓包也是同时连 8+ 个 alikunlun 节点）
    PARALLEL_N = int(os.environ.get("PARALLEL_N", "4"))
    PARALLEL_CHUNK = 8 * 1024 * 1024

    def _host_ips(self, host):
        """解析出该 CDN 主机的全部 IPv4（用于多节点分发）"""
        try:
            infos = socket.getaddrinfo(host, 443, socket.AF_INET)
            return sorted({i[4][0] for i in infos})
        except OSError:
            return []

    def _fetch_range(self, host, ip, path, start, end, headers, sink):
        """从指定 IP 拉 [start,end]，边收边塞进 sink（queue），结束塞 None"""
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            raw = socket.create_connection((ip, 443), timeout=20)
            ss = ctx.wrap_socket(raw, server_hostname=host)
            req = ["GET %s HTTP/1.1" % path, "Host: " + host]
            for k, v in (headers or {}).items():
                req.append("%s: %s" % (k, v))
            req.append("Range: bytes=%d-%d" % (start, end))
            req.append("Accept-Encoding: identity")
            req.append("Connection: close")
            ss.sendall(("\r\n".join(req) + "\r\n\r\n").encode())
            head = b""
            while b"\r\n\r\n" not in head:
                d = ss.recv(4096)
                if not d:
                    break
                head += d
            body_start = head.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in head else b""
            if body_start:
                sink.put(body_start)
            while True:
                d = ss.recv(262144)
                if not d:
                    break
                sink.put(d)
            ss.close()
        except Exception:
            pass
        finally:
            sink.put(None)

    def stream_ranges(self, url, start, end, extra_headers=None, n=None):
        """并发从多个 CDN 节点拉 [start,end]，按序产出字节。

        实测依据：同一主机解析出 8 个 alikunlun 节点，单节点被限到 ~1-2MB/s，
        多节点并发可叠加（3 节点实测 1.83x）。所以不是「同一 IP 多连接」，
        而是**分发到不同节点**。
        """
        import queue
        import threading
        import urllib.parse as _up
        u = _up.urlsplit(url)
        host, path = u.hostname, u.path + (("?" + u.query) if u.query else "")
        headers = dict(extra_headers or {})
        headers.setdefault("User-Agent", UA)
        headers.setdefault("Referer", "https://pan.quark.cn/")
        pairs = ["%s=%s" % (c.name, c.value) for c in self._jar]
        if pairs:
            headers["Cookie"] = "; ".join(pairs)

        total = end - start + 1
        n = max(1, min(n or self.PARALLEL_N, max(1, total // (1024 * 1024))))
        if n <= 1:
            sink = queue.Queue(maxsize=64)
            threading.Thread(target=self._fetch_range,
                             args=(host, None, path, start, end, headers, sink),
                             daemon=True).start()
            yield from self._drain(sink)
            return

        ips = self._host_ips(host) or [host]
        step = total // n
        sinks, threads = [], []
        for i in range(n):
            b0 = start + i * step
            b1 = end if i == n - 1 else (b0 + step - 1)
            sink = queue.Queue(maxsize=32)
            t = threading.Thread(target=self._fetch_range,
                                 args=(host, ips[i % len(ips)], path, b0, b1, headers, sink),
                                 daemon=True)
            sinks.append(sink)
            threads.append(t)
        for t in threads:
            t.start()
        for sink in sinks:
            yield from self._drain(sink)

    @staticmethod
    def _drain(sink):
        while True:
            item = sink.get()
            if item is None:
                return
            yield item

    def session_header(self):
        """把取流必需的会话 Cookie 作为请求头返回。

        实测：CDN 对直链强校验会话 Cookie（__puus），缺了一律 412。
        但只要把 Cookie 放进请求头，**任何全新连接**都能拿到 206 ——
        所以可以让播放器直连 CDN（而不是我们转发），吞吐不再受代理限制。
        格式按 TVBox spider 约定：每行一个 "Key: Value"。
        """
        pairs = ["%s=%s" % (c.name, c.value) for c in self._jar]
        lines = []
        if pairs:
            lines.append("Cookie: " + "; ".join(pairs))
        lines.append("User-Agent: " + UA)
        lines.append("Referer: https://pan.quark.cn/")
        return "\n".join(lines)

    def open_stream(self, url, extra_headers=None):
        """带着会话 Cookie 打开取流地址。

        CDN 会校验取流时下发到会话里的 __pugs，缺了直接 412 Precondition
        Failed —— 所以播放必须由服务端代理，不能让播放器直连。
        """
        headers = {"User-Agent": UA, "Referer": "https://pan.quark.cn/",
                   "Accept": "*/*"}
        headers.update(extra_headers or {})
        return self._opener.open(urllib.request.Request(url, headers=headers),
                                 timeout=60)


def _brief(payload, n=120):
    return re.sub(r"\s+", " ", str(payload))[:n]


def clear_saved_cookie():
    """从 config.json 里删掉 quark_cookie（「清除夸克账号」用）"""
    cfg_path = os.path.join(ROOT, "config.json")
    if not os.path.exists(cfg_path):
        return False
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh) or {}
    except (OSError, ValueError):
        return False
    if not cfg.get("quark_cookie"):
        return False
    cfg.pop("quark_cookie", None)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    return True


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
