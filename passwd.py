#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
passwd.py — 密码哈希与校验（仅标准库）。

存储格式：pbkdf2$<iterations>$<salt_hex>$<hash_hex>
verify_password 兼容旧版明文存储（迁移期），命中明文后调用方可升级为哈希。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 100_000
_SALT_BYTES = 16
_PREFIX = "pbkdf2"


def is_hashed(s: str | None) -> bool:
    if not isinstance(s, str):
        return False
    parts = s.split("$")
    return len(parts) == 4 and parts[0] == _PREFIX and parts[1].isdigit() \
        and len(parts[2]) == _SALT_BYTES * 2 and len(parts[3]) == 64


def hash_password(pwd: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, _ITERATIONS)
    return f"{_PREFIX}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(pwd: str, stored: str | None) -> bool:
    """校验密码。stored 为哈希则验哈希，为明文（旧版）则直接比对。"""
    if not isinstance(pwd, str) or not isinstance(stored, str):
        return False
    if is_hashed(stored):
        try:
            _, it_s, salt_hex, hash_hex = stored.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"),
                                     bytes.fromhex(salt_hex), int(it_s))
            return hmac.compare_digest(dk.hex(), hash_hex)
        except Exception:
            return False
    # 旧版明文：恒定时间比对
    return secrets.compare_digest(pwd, stored)
