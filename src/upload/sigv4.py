# -*- coding: utf-8 -*-
"""AWS Signature Version 4 签名（纯标准库实现，只负责签名，不发请求）。

为什么要自己写：Cloudflare R2 提供的是 S3 兼容接口，官方 SDK 是 ``boto3``，
但它会连带装上 ``botocore`` 等约 30 MB 依赖。本项目对 R2 的用法只有
「PUT / GET / DELETE / HEAD / ListObjectsV2」这几个动作，自己按 AWS 规范
签一次名即可，于是把依赖降到零 —— 本机与 VPS 都不需要再装任何东西。

SigV4 的四步（对应下面四个函数）：

1. **派生签名密钥** :func:`derive_signing_key`
   把 ``"AWS4" + SecretAccessKey`` 依次按 日期 → 区域 → 服务 → 终止符 做 HMAC-SHA256；
2. **规范化请求** :func:`build_canonical_request`
   方法、编码后的 URI、编码并排序后的查询串、规范化头部、签名头列表、载荷哈希；
3. **待签字符串** :func:`build_string_to_sign`
   算法、时间戳、凭据作用域、上一步结果的哈希；
4. **组装 Authorization** :func:`sign_request`
   算法 + Credential + SignedHeaders + Signature，并把
   ``x-amz-date`` / ``x-amz-content-sha256`` 一并放进请求头。

R2 的三处特有约定：区域固定 ``auto``、服务名固定 ``s3``、
载荷哈希必须通过 ``x-amz-content-sha256`` 显式声明。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timezone
from typing import Mapping, Optional
from urllib.parse import quote, urlparse

# SigV4 固定字面量
ALGORITHM = "AWS4-HMAC-SHA256"
_REQUEST_TERMINATOR = "aws4_request"

# R2 的固定约定
DEFAULT_REGION = "auto"
DEFAULT_SERVICE = "s3"

# 头部的值需要把连续空白折叠成单个空格（AWS 规范要求）
_WHITESPACE_RE = re.compile(r"\s+")

# URI 编码时不需要转义的字符（斜杠另行控制是否保留）
_UNRESERVED = "-_.~"


def _sha256_hex(data: bytes) -> str:
    """返回数据的 SHA-256 十六进制小写摘要。"""
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, message: str) -> bytes:
    """以 ``key`` 为密钥对 ``message`` 做 HMAC-SHA256。"""
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def encode_uri(path: str, keep_slash: bool = True) -> str:
    """按 RFC 3986 编码路径。

    :param keep_slash: 为 True 时保留 ``/`` 分隔符（用于路径），
                       为 False 时把 ``/`` 也编码（用于查询串的键值）
    """
    safe = ("/" if keep_slash else "") + _UNRESERVED
    return quote(path, safe=safe)


def build_canonical_query_string(params: Optional[Mapping[str, object]]) -> str:
    """构造规范化查询串：按键名排序、键与值分别编码、以 ``&`` 连接。

    为空时返回空字符串（规范要求这一行仍然存在，只是内容为空）。
    """
    if not params:
        return ""
    pairs = []
    for key, value in params.items():
        if value is None:
            continue
        pairs.append(
            (encode_uri(str(key), keep_slash=False), encode_uri(str(value), keep_slash=False))
        )
    pairs.sort()
    return "&".join(f"{key}={value}" for key, value in pairs)


def normalize_header_value(value: object) -> str:
    """规范化头部取值：去掉首尾空白，并把内部连续空白折叠为单个空格。"""
    return _WHITESPACE_RE.sub(" ", str(value).strip())


def derive_signing_key(
    secret_access_key: str,
    datestamp: str,
    region: str,
    service: str,
) -> bytes:
    """派生签名密钥（AWS 官方称之为 *derived signing key*）。

    :param datestamp: 形如 ``20261015`` 的日期串（UTC）
    """
    key = _hmac_sha256(("AWS4" + secret_access_key).encode("utf-8"), datestamp)
    key = _hmac_sha256(key, region)
    key = _hmac_sha256(key, service)
    return _hmac_sha256(key, _REQUEST_TERMINATOR)


def build_canonical_request(
    method: str,
    canonical_uri: str,
    canonical_query: str,
    canonical_headers: Mapping[str, str],
    signed_header_names: list[str],
    payload_hash: str,
) -> str:
    """拼装规范化请求。

    格式为「方法 / URI / 查询串 / 规范化头部 / 签名头列表 / 载荷哈希」六段，
    段间以换行连接。注意规范化头部自身以换行结尾（每条 ``name:value`` 一行），
    所以它与签名头列表之间会自然形成规范要求的那一个空行。
    """
    header_block = "".join(
        f"{name}:{normalize_header_value(canonical_headers[name])}\n"
        for name in signed_header_names
    )
    return "\n".join(
        [
            method,
            canonical_uri,
            canonical_query,
            header_block,
            ";".join(signed_header_names),
            payload_hash,
        ]
    )


def build_string_to_sign(
    amz_date: str,
    credential_scope: str,
    canonical_request: str,
) -> str:
    """拼装待签字符串。"""
    return "\n".join(
        [
            ALGORITHM,
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request.encode("utf-8")),
        ]
    )


def sign_request(
    *,
    method: str,
    endpoint: str,
    path: str,
    access_key_id: str,
    secret_access_key: str,
    query_params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    payload: bytes = b"",
    region: str = DEFAULT_REGION,
    service: str = DEFAULT_SERVICE,
    now: Optional[datetime] = None,
) -> dict[str, str]:
    """为一次请求生成可直接交给 ``requests`` 使用的请求头。

    :param endpoint: 形如 ``https://<account>.r2.cloudflarestorage.com``
    :param path: **未编码**的路径，例如 ``/fanza/PAYLOAD/PAYLOAD_DAILY.json``
    :param payload: 请求体原始字节（GET/HEAD/DELETE 传空字节串）
    :return: 含 ``Authorization``、``x-amz-date``、``x-amz-content-sha256``
             以及调用方原有头的字典（不包含 Host —— 交给 HTTP 库按 URL 生成，
             我们只是「签名时」按同样的取值计算）
    """
    moment = now or datetime.now(timezone.utc)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    datestamp = moment.strftime("%Y%m%d")

    parsed = urlparse(endpoint)
    host = parsed.netloc
    if not host:
        raise ValueError(f"endpoint 不合法：{endpoint!r}")

    payload_hash = _sha256_hex(payload)

    # 参与签名的头 = 调用方给的头 + host + 两个 amz 头
    signing_headers: dict[str, str] = {
        str(key).lower(): normalize_header_value(value)
        for key, value in (headers or {}).items()
    }
    signing_headers["host"] = host
    signing_headers["x-amz-content-sha256"] = payload_hash
    signing_headers["x-amz-date"] = amz_date

    signed_header_names = sorted(signing_headers)

    canonical_request = build_canonical_request(
        method=method.upper(),
        canonical_uri=encode_uri(path, keep_slash=True),
        canonical_query=build_canonical_query_string(query_params),
        canonical_headers=signing_headers,
        signed_header_names=signed_header_names,
        payload_hash=payload_hash,
    )

    credential_scope = f"{datestamp}/{region}/{service}/{_REQUEST_TERMINATOR}"
    string_to_sign = build_string_to_sign(amz_date, credential_scope, canonical_request)
    signing_key = derive_signing_key(secret_access_key, datestamp, region, service)
    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    outgoing = {str(key): str(value) for key, value in (headers or {}).items()}
    outgoing["x-amz-date"] = amz_date
    outgoing["x-amz-content-sha256"] = payload_hash
    outgoing["Authorization"] = (
        f"{ALGORITHM} "
        f"Credential={access_key_id}/{credential_scope}, "
        f"SignedHeaders={';'.join(signed_header_names)}, "
        f"Signature={signature}"
    )
    return outgoing
