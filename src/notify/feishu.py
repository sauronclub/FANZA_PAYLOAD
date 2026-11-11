# -*- coding: utf-8 -*-
"""飞书群机器人通知。

* 以「交互卡片」推送运行摘要，全绿/红色表头一眼可辨；
* 支持可选的签名校验（机器人开启「签名校验」时需要）；
* 自带超时与重试，失败不会影响主流程。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any, Optional

import requests

from ..core.exceptions import NotifyError
from ..core.models import RunResult
from ..logkit import get_logger
from .base import Notifier, NullNotifier

_TIMEOUT_S = 10.0
_MAX_ATTEMPT = 2

# 卡片表头配色：成功用绿色，存在失败用红色
_COLOR_OK = "green"
_COLOR_FAIL = "red"

# 未配置 webhook 时复用的空实现
_NULL_NOTIFIER: Notifier = NullNotifier()


class FeishuNotifier(Notifier):
    """飞书群机器人通知实现。"""

    def __init__(
        self,
        webhook_url: str,
        sign_secret: str = "",
        timeout_s: float = _TIMEOUT_S,
    ) -> None:
        if not webhook_url:
            raise NotifyError("飞书 webhook 地址为空")
        self._webhook_url = webhook_url
        self._sign_secret = sign_secret
        self._timeout_s = timeout_s
        self._logger = get_logger("notify.feishu")

    # ── 对外接口 ──────────────────────────────────────────────
    def send_run_summary(self, result: RunResult) -> None:
        """推送运行摘要卡片。"""
        if result.ok:
            title = f"FANZA Payload（ThinkPad） 捕获完成（{result.succeeded}/{result.total} 成功）"
        else:
            title = f"FANZA Payload（ThinkPad） 捕获异常（失败 {result.failed}/{result.total}）"
        template = _COLOR_OK if result.ok else _COLOR_FAIL
        self._send_card(title, template, self._build_markdown(result))

    # ── 内部实现 ──────────────────────────────────────────────
    @staticmethod
    def _build_markdown(result: RunResult) -> str:
        """把运行结果整理为飞书 markdown 文本。"""
        lines = [
            f"**运行 ID**：{result.run_id}",
            f"**成功 / 总数**：{result.succeeded} / {result.total}",
            f"**失败数**：{result.failed}",
            f"**耗时**：{result.duration_s:.1f} 秒",
        ]
        if result.failed_pages:
            lines.append("")
            lines.append("**失败明细**")
            for page in result.failed_pages:
                reason = (page.error or "未知原因").replace("\n", " ")
                lines.append(f"- `{page.page_name}`：{reason}")
        return "\n".join(lines)

    def _build_payload(self, title: str, template: str, markdown: str) -> dict[str, Any]:
        """构造飞书交互卡片报文。"""
        payload: dict[str, Any] = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": template,
                    "title": {"tag": "plain_text", "content": title},
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": markdown}},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"发送时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
                            }
                        ],
                    },
                ],
            },
        }
        if self._sign_secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = self._sign(timestamp)
        return payload

    def _sign(self, timestamp: str) -> str:
        """按飞书规则计算签名：HMAC-SHA256(key="<timestamp>\\n<secret>", msg="")。"""
        string_to_sign = f"{timestamp}\n{self._sign_secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _send_card(self, title: str, template: str, markdown: str) -> None:
        """发送交互卡片，失败按次数重试。

        :raises NotifyError: 全部尝试失败
        """
        payload = self._build_payload(title, template, markdown)
        last_error: Optional[Exception] = None

        for attempt in range(1, _MAX_ATTEMPT + 1):
            try:
                response = requests.post(
                    self._webhook_url,
                    json=payload,
                    timeout=self._timeout_s,
                )
                response.raise_for_status()
                body = response.json()
                code = body.get("code", body.get("StatusCode", 0))
                if code not in (0, None):
                    raise NotifyError(f"飞书返回错误码 {code}：{body.get('msg')}")
                self._logger.info("飞书运行摘要已推送")
                return
            except (requests.RequestException, ValueError, NotifyError) as exc:
                last_error = exc
                self._logger.warning("飞书推送第 %d 次失败：%s", attempt, exc)

        raise NotifyError(f"飞书推送失败：{last_error}")


def build_notifier(webhook_url: str, sign_secret: str = "") -> Notifier:
    """按配置构造通知器；未配置 webhook 时返回空实现。"""
    if not webhook_url:
        return _NULL_NOTIFIER
    return FeishuNotifier(webhook_url=webhook_url, sign_secret=sign_secret)
