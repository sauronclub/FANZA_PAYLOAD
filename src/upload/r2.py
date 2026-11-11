# -*- coding: utf-8 -*-
"""Cloudflare R2 客户端与上传实现（S3 兼容 API，零额外依赖）。

R2 提供 S3 兼容接口，但官方 SDK ``boto3`` 会连带装上 ``botocore`` 等约 30 MB
依赖。本项目对 R2 的用法只有「PUT / GET / DELETE / HEAD / ListObjectsV2」，
因此直接用 :mod:`src.upload.sigv4`（纯标准库签名）+ ``requests`` 发请求，
不引入任何新依赖 —— 本机与 VPS 都无需额外安装。

层次：

* :class:`R2Client`   —— 与 R2 打交道的底层 HTTP 客户端，也供运维脚本使用；
* :class:`R2Uploader` —— 实现 :class:`~src.upload.base.Uploader` 接口，供主流程调用。

三处 R2 特有约定：区域固定 ``auto``、服务名固定 ``s3``、采用 path-style 寻址
（``<endpoint>/<bucket>/<key>``）。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional
from urllib.parse import urlparse

import requests

from ..core.exceptions import ConfigError, R2RequestError
from ..core.settings import Settings
from ..logkit import get_logger
from . import sigv4
from .base import UploadBatch, UploadItem, UploadOutcome, Uploader

# 单个文件的上传重试次数（网络抖动导致的失败通常重试即可成功）
_MAX_ATTEMPTS = 3

# 单次 HTTP 请求超时（秒）；文件都很小，不需要更长
_DEFAULT_TIMEOUT_S = 30.0

# 我们上传的都是 JSON，统一声明；也参与 SigV4 签名，必须与实际发送值一致
_JSON_CONTENT_TYPE = "application/json; charset=utf-8"


# ── XML 解析辅助（S3 响应用 XML） ────────────────────────────


def _local_name(tag: str) -> str:
    """去掉 XML 命名空间前缀，只留标签名。"""
    return tag.rsplit("}", 1)[-1]


def _parse_error(response: requests.Response) -> tuple[str, str]:
    """从 S3 风格的 XML 错误响应里提取 ``(Code, Message)``。

    解析不出来时退化为截断的原始文本 —— 无论如何都要让日志里有线索。
    """
    text = (response.text or "").strip()
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return "", text[:200]

    code = message = ""
    for child in root:
        name = _local_name(child.tag)
        if name == "Code":
            code = (child.text or "").strip()
        elif name == "Message":
            message = (child.text or "").strip()
    return code, message or text[:200]


def _parse_list_objects(xml_text: str) -> dict[str, Any]:
    """解析 ``ListObjectsV2`` 响应。"""
    root = ET.fromstring(xml_text)
    objects: list[dict[str, Any]] = []
    truncated = False
    next_token: Optional[str] = None

    for child in root:
        name = _local_name(child.tag)
        if name == "Contents":
            fields = {_local_name(g.tag): (g.text or "") for g in child}
            objects.append(
                {
                    "key": fields.get("Key", ""),
                    "size": int(fields.get("Size") or 0),
                    "etag": (fields.get("ETag") or "").strip('"'),
                }
            )
        elif name == "IsTruncated":
            truncated = (child.text or "").strip().lower() == "true"
        elif name == "NextContinuationToken":
            next_token = (child.text or "").strip() or None

    return {"objects": objects, "truncated": truncated, "next_token": next_token}


# ── R2 HTTP 客户端 ───────────────────────────────────────────


class R2Client:
    """Cloudflare R2 的 S3 兼容 HTTP 客户端。

    只实现本项目用得到的几个动作；所有请求都走 SigV4 签名。
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str = sigv4.DEFAULT_REGION,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        parsed = urlparse(
            endpoint_url if "://" in endpoint_url else f"https://{endpoint_url}"
        )
        if not parsed.netloc:
            raise ConfigError(f"R2 端点不合法：{endpoint_url!r}")

        self.endpoint = f"{parsed.scheme or 'https'}://{parsed.netloc}"
        self.bucket = bucket
        self.region = region

        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._timeout = timeout
        self._session = requests.Session()
        self._logger = get_logger("upload.r2")

    # ── 底层 ────────────────────────────────────────────────

    def _bucket_path(self, key: str = "") -> str:
        """拼出**未编码**的路径（编码统一在签名与发 URL 时做，保证两者一致）。"""
        return f"/{self.bucket}" + (f"/{key}" if key else "")

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        body: Optional[bytes] = None,
    ) -> requests.Response:
        """发一次已签名的请求；网络层异常统一转成 :class:`R2RequestError`。"""
        url = self.endpoint + sigv4.encode_uri(path, keep_slash=True)
        if query:
            url += "?" + sigv4.build_canonical_query_string(query)

        signed_headers = sigv4.sign_request(
            method=method,
            endpoint=self.endpoint,
            path=path,
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            query_params=query,
            headers=headers,
            payload=body or b"",
            region=self.region,
        )

        try:
            return self._session.request(
                method, url, headers=signed_headers, data=body, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise R2RequestError(f"{method} {url} 请求失败：{exc}") from exc

    def _expect_ok(self, response: requests.Response, action: str) -> requests.Response:
        """非 2xx 一律抛 :class:`R2RequestError`，并把 R2 的错误码带进消息。"""
        if 200 <= response.status_code < 300:
            return response
        code, message = _parse_error(response)
        detail = f"{code}：{message}" if code else message
        raise R2RequestError(
            f"{action} 失败：HTTP {response.status_code}"
            + (f"（{detail}）" if detail else "")
        )

    # ── 公开动作 ────────────────────────────────────────────

    def head_bucket(self) -> None:
        """确认桶存在且凭据可访问（不存在或无权限都会抛异常）。"""
        response = self._request("HEAD", self._bucket_path())
        self._expect_ok(response, f"访问桶 {self.bucket}")

    def put_object(
        self, key: str, body: bytes, content_type: str = _JSON_CONTENT_TYPE
    ) -> int:
        """上传一个对象，返回写入字节数。"""
        response = self._request(
            "PUT",
            self._bucket_path(key),
            headers={"content-type": content_type},
            body=body,
        )
        self._expect_ok(response, f"上传 {key}")
        return len(body)

    def get_object(self, key: str) -> bytes:
        """下载一个对象，返回原始字节。"""
        response = self._request("GET", self._bucket_path(key))
        self._expect_ok(response, f"下载 {key}")
        return response.content

    def delete_object(self, key: str) -> None:
        """删除一个对象（对象不存在时 S3 也返回成功）。"""
        response = self._request("DELETE", self._bucket_path(key))
        self._expect_ok(response, f"删除 {key}")

    def list_objects(
        self,
        prefix: str = "",
        max_keys: int = 1000,
        continuation_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """列举一页对象。"""
        query: dict[str, Any] = {"list-type": "2", "max-keys": str(max_keys)}
        if prefix:
            query["prefix"] = prefix
        if continuation_token:
            query["continuation-token"] = continuation_token

        response = self._request("GET", self._bucket_path(), query=query)
        self._expect_ok(response, f"列举桶 {self.bucket}")
        return _parse_list_objects(response.text)

    def iter_objects(
        self, prefix: str = "", page_size: int = 1000
    ) -> Iterator[dict[str, Any]]:
        """跨页遍历所有对象（自动跟随 ``continuation-token``）。"""
        token: Optional[str] = None
        while True:
            page = self.list_objects(
                prefix=prefix, max_keys=page_size, continuation_token=token
            )
            yield from page["objects"]
            if not page["truncated"] or not page["next_token"]:
                return
            token = page["next_token"]

    def close(self) -> None:
        """释放连接池。"""
        self._session.close()


# ── 上传器 ───────────────────────────────────────────────────


class R2Uploader(Uploader):
    """把文件上传到 Cloudflare R2 存储桶。"""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        prefix: str = "",
    ) -> None:
        self._logger = get_logger("upload.r2")
        self._prefix = prefix.strip().strip("/")
        self.client = R2Client(
            endpoint_url=endpoint_url,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            bucket=bucket,
        )
        self._logger.debug(
            "R2 客户端就绪：endpoint=%s bucket=%s prefix=%r",
            self.client.endpoint,
            bucket,
            self._prefix,
        )

    @property
    def bucket(self) -> str:
        return self.client.bucket

    def _full_key(self, remote_key: str) -> str:
        """把相对键拼上配置的前缀。"""
        return f"{self._prefix}/{remote_key}" if self._prefix else remote_key

    def upload_one(self, item: UploadItem) -> UploadOutcome:
        """上传单个文件，失败不抛异常，返回失败结果。"""
        key = self._full_key(item.remote_key)
        path = Path(item.local_path)

        if not path.is_file():
            self._logger.error("待上传文件不存在，已跳过：%s", path)
            return UploadOutcome(
                remote_key=key, success=False, error=f"本地文件不存在：{path}"
            )

        try:
            body = path.read_bytes()
        except OSError as exc:
            return UploadOutcome(
                remote_key=key, success=False, error=f"读取文件失败：{exc}"
            )

        last_error: Optional[str] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                self.client.put_object(key, body)
                self._logger.debug("已上传 %s（%d 字节）", key, len(body))
                return UploadOutcome(remote_key=key, success=True, size_bytes=len(body))
            except Exception as exc:  # noqa: BLE001 - 网络/签名/权限异常统一收敛
                last_error = f"{exc.__class__.__name__}: {exc}"
                self._logger.warning(
                    "上传 %s 第 %d/%d 次失败：%s",
                    key,
                    attempt,
                    _MAX_ATTEMPTS,
                    last_error,
                )

        return UploadOutcome(
            remote_key=key, success=False, size_bytes=len(body), error=last_error
        )

    def upload_many(self, items: Iterable[UploadItem]) -> UploadBatch:
        """逐个上传并汇总结果。"""
        batch = UploadBatch()
        for item in items:
            batch.outcomes.append(self.upload_one(item))
        return batch


def build_uploader(settings: Settings) -> Uploader:
    """根据配置构造上传器。

    :return: 配置齐全时返回 :class:`R2Uploader`；未配置时返回
             :class:`NullUploader`（调用方无需判断）
    :raises ConfigError: 配置不完整
    """
    from .base import NullUploader  # noqa: PLC0415 - 避免与 base 循环导入

    if not settings.upload_enabled:
        if settings.r2_partial:
            # 到这里说明是调用方没先 validate()，这里再兜一次
            raise ConfigError("R2 配置不完整，无法启用上传")
        return NullUploader()

    return R2Uploader(
        endpoint_url=settings.r2_endpoint_url,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket=settings.r2_bucket,
        prefix=settings.r2_prefix,
    )
