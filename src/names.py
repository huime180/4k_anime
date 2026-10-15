#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""番名归一化与相似度（从原来的 quark.py 里抽出来，站点只做数据后这里还留着用）。"""

from __future__ import annotations

import re

_BRACKET = re.compile(r"[\[\(（【][^\]\)）】]*[\]\)）】]")
_NUM_PREFIX = re.compile(r"^\s*\d{1,4}\s*[.\-_、 ]\s*")
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
