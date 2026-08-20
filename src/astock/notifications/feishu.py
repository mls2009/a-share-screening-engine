import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.request import Request, urlopen

Transport = Callable[[str, dict, float], dict]


def sign(timestamp: str, secret: str) -> str:
    signing_key = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(signing_key, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _transport(url: str, payload: dict, timeout: float) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    error: str | None = None


class FeishuNotifier:
    def __init__(
        self,
        webhook: str,
        secret: str | None = None,
        transport: Transport = _transport,
        timeout: float = 5,
    ) -> None:
        self.webhook = webhook
        self.secret = secret
        self.transport = transport
        self.timeout = timeout

    @staticmethod
    def _card(message: dict) -> dict:
        comparator = {
            "above": "达到上方",
            "below": "达到下方",
            "cross_above": "向上突破",
            "cross_below": "向下跌破",
        }.get(message.get("comparator"), message.get("comparator", ""))
        return {
            "header": {
                "template": "green" if "above" in message.get("comparator", "") else "red",
                "title": {"tag": "plain_text", "content": "AStock 实时点位提醒"},
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"**{message.get('task_name', '价格监控')}**\n"
                        f"证券：`{message.get('symbol', '-')}`\n"
                        f"条件：{comparator} `{message.get('threshold', '-')}`\n"
                        f"现价：**{message.get('price', '-')}**\n"
                        f"触发：{message.get('triggered_at', '-')}"
                    ),
                }
            ],
        }

    def send(self, message: dict, timestamp: int | None = None) -> DeliveryResult:
        current = str(timestamp if timestamp is not None else int(time.time()))
        payload = {"msg_type": "interactive", "card": self._card(message)}
        if self.secret:
            payload.update({"timestamp": current, "sign": sign(current, self.secret)})
        try:
            response = self.transport(self.webhook, payload, self.timeout)
        except (OSError, TimeoutError, ValueError) as error:
            return DeliveryResult(False, str(error))
        code = response.get("code", response.get("StatusCode", -1))
        if code != 0:
            return DeliveryResult(False, str(response.get("msg", "Feishu rejected message")))
        return DeliveryResult(True)
