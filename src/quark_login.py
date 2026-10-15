#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
4k_anime · 夸克扫码登录
========================
复刻「夸克 App 扫码登录」，拿到 Cookie（含 __puus）后写入 config.json，
之后 /play 就能取直链了。

协议（实测可用）:
  1. 取二维码 token
     GET https://uop.quark.cn/cas/ajax/getTokenForQrcodeLogin
         ?client_id=532&v=1.2&request_id=<uuid>
     -> data.members.token
  2. 二维码内容（夸克 App 扫这个）
     https://su.quark.cn/4_eMHBJ?token=<token>&client_id=532&ssb=weblogin&...
  3. 轮询是否已扫 / 已确认
     GET https://uop.quark.cn/cas/ajax/getServiceTicketByQrcodeToken
         ?client_id=532&v=1.2&token=<token>&request_id=<uuid>
     50004001 等待扫码 / 50004002~4 失败 / 2000000 成功(带 service_ticket)
  4. 用 service_ticket 换 Cookie
     GET https://pan.quark.cn/account/info?st=<service_ticket>&lw=scan
     -> Set-Cookie: __puus / __pus / ...

命令行用法（终端里直接扫）:
    python3 src/quark_login.py
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "_vendor"))

ROOT = os.path.dirname(_HERE)
CONFIG_FILE = os.path.join(ROOT, "config.json")

CLIENT_ID = "532"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TOKEN_API = "https://uop.quark.cn/cas/ajax/getTokenForQrcodeLogin"
TICKET_API = "https://uop.quark.cn/cas/ajax/getServiceTicketByQrcodeToken"
ACCOUNT_API = "https://pan.quark.cn/account/info"
QR_TARGET = "https://su.quark.cn/4_eMHBJ"

# 轮询状态
WAITING, CONFIRMED, FAILED, EXPIRED = "waiting", "confirmed", "failed", "expired"


class LoginError(RuntimeError):
    pass


def _get_json(url, opener=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://pan.quark.cn/",
        "Accept": "application/json, text/plain, */*",
    })
    open_fn = opener.open if opener else urllib.request.urlopen
    with open_fn(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
# 协议实现
# --------------------------------------------------------------------------- #
def new_session():
    """申请一个二维码会话"""
    request_id = str(uuid.uuid4())
    url = TOKEN_API + "?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "v": "1.2", "request_id": request_id,
    })
    data = _get_json(url)
    if data.get("status") != 2000000:
        raise LoginError("申请二维码失败：%s" % data.get("message"))
    token = (data.get("data") or {}).get("members", {}).get("token")
    if not token:
        raise LoginError("申请二维码失败：响应里没有 token")

    qr_url = QR_TARGET + "?" + urllib.parse.urlencode({
        "token": token,
        "client_id": CLIENT_ID,
        "ssb": "weblogin",
        "uc_param_str": "",
        "uc_biz_str": "S:custom|OPT:SAREA@0|OPT:IMMERSIVE@1|OPT:BACK_BTN_STYLE@0",
    })
    return {"token": token, "request_id": request_id, "url": qr_url,
            "created_at": int(time.time() * 1000)}


def poll(token, request_id):
    """查询扫码状态；成功时返回 (CONFIRMED, service_ticket)"""
    url = TICKET_API + "?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "v": "1.2",
        "token": token, "request_id": request_id,
    })
    try:
        data = _get_json(url)
    except urllib.error.HTTPError as exc:
        return FAILED, "HTTP %s" % exc.code

    status = data.get("status")
    if status == 2000000:
        ticket = (data.get("data") or {}).get("members", {}).get("service_ticket")
        if ticket:
            return CONFIRMED, ticket
        return WAITING, None
    if status == 50004001:
        return WAITING, None
    if status in (50004002, 50004003, 50004004):
        return FAILED, data.get("message") or "登录被拒绝"
    return WAITING, None


def exchange_cookie(service_ticket):
    """用 service_ticket 换取 Cookie 串"""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    url = ACCOUNT_API + "?" + urllib.parse.urlencode({
        "st": service_ticket, "lw": "scan", "fr": "pc", "platform": "pc",
    })
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://pan.quark.cn/",
        "Accept": "application/json, text/plain, */*",
    })
    with opener.open(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))

    pairs = ["%s=%s" % (c.name, c.value) for c in jar]
    if not pairs:
        raise LoginError("换取 Cookie 失败：服务端没有下发 Cookie")
    return "; ".join(pairs), body


# --------------------------------------------------------------------------- #
# 二维码矩阵 / 保存
# --------------------------------------------------------------------------- #
def qr_matrix(text):
    """返回 (size, rows)，rows 是 0/1 二维列表；失败返回 (0, [])"""
    try:
        import segno
        qr = segno.make(text, error="m")
        rows = [[1 if cell else 0 for cell in row] for row in qr.matrix]
        return len(rows), rows
    except Exception:
        return 0, []


def save_cookie(cookie):
    """把 Cookie 写进 config.json（该文件已被 .gitignore 忽略）"""
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                cfg = json.load(fh) or {}
        except ValueError:
            cfg = {}
    cfg["quark_cookie"] = cookie
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass
    return CONFIG_FILE


# --------------------------------------------------------------------------- #
# 命令行：在终端里直接显示二维码
# --------------------------------------------------------------------------- #
def run_cli(timeout=180):
    session = new_session()
    print("[login] 二维码内容：%s\n" % session["url"])
    try:
        import segno
        segno.make(session["url"], error="m").terminal(compact=True)
    except Exception as exc:
        print("[login] 终端二维码渲染失败（%s），请手动复制上面的链接生成二维码" % exc)
    print("\n[login] 请用【夸克 App】扫上面的码并确认登录…")

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        state, payload = poll(session["token"], session["request_id"])
        if state != last:
            print("[login] 状态：%s" % state)
            last = state
        if state == CONFIRMED:
            cookie, info = exchange_cookie(payload)
            path = save_cookie(cookie)
            nick = ((info.get("data") or {}).get("nickname")) or "?"
            print("[login] ✅ 登录成功：%s" % nick)
            print("[login] Cookie 已写入 %s（%d 字符）" % (path, len(cookie)))
            print("[login] 重启服务即可生效：python3 src/server.py --port 8787")
            return 0
        if state == FAILED:
            print("[login] ❌ 登录失败：%s" % payload)
            return 1
        time.sleep(2)

    print("[login] ⏰ 二维码已过期，请重新执行")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(run_cli())
    except LoginError as exc:
        print("[login] %s" % exc, file=sys.stderr)
        raise SystemExit(1)
