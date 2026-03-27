from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..config import AppConfig
from ..logging import get_logger
from ..types import Channel, NewMessage, OnChatMetadata, OnInboundMessage, RegisteredGroup
from .registry import ChannelOpts, register_channel

logger = get_logger(__name__)


class FeishuChannel(Channel):
    name = "feishu"

    def __init__(
        self,
        config: AppConfig,
        *,
        on_message: OnInboundMessage,
        on_chat_metadata: OnChatMetadata,
        registered_groups: Callable[[], dict[str, RegisteredGroup]],
        auto_register_group: Callable[[str, str, str], bool] | None,
    ) -> None:
        self._config = config
        self._on_message = on_message
        self._on_chat_metadata = on_chat_metadata
        self._registered_groups = registered_groups
        self._auto_register_group = auto_register_group
        self._connected = False
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._ws_thread: threading.Thread | None = None

        try:
            import lark_oapi as lark

            self._lark = lark
            self._client = (
                lark.Client.builder().app_id(config.feishu_app_id).app_secret(config.feishu_app_secret).build()
            )
        except Exception as e:
            raise RuntimeError("Feishu channel requires lark-oapi") from e

        self._ws = None

    async def connect(self) -> None:
        self._main_loop = asyncio.get_event_loop()
        ws_client = self._detect_ws_client()
        if ws_client is None:
            raise RuntimeError(
                "Feishu WebSocket long-connection is not available in current lark-oapi installation. "
                "Upgrade lark-oapi to a version that includes ws client support, or implement HTTP event callback mode."
            )

        self._ws = ws_client

        # lark-oapi ws.Client uses sync start() with its own event loop, run in dedicated thread
        # Need to create fresh event loop for lark-oapi to use (module-level loop is bound at import time)
        thread_ready = threading.Event()
        startup_error: list[Exception] = []

        def run_ws() -> None:
            import lark_oapi.ws.client as ws_mod

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            # Patch the module-level loop that lark-oapi captured at import time
            ws_mod.loop = loop
            thread_ready.set()
            try:
                ws_client.start()
            except Exception as e:
                startup_error.append(e)
                logger.error("ws.Client.start() failed: %s", e)
            finally:
                loop.close()

        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()

        if not thread_ready.wait(timeout=5):
            raise RuntimeError("Feishu WebSocket thread failed to initialize")

        await asyncio.sleep(0.1)
        if startup_error:
            raise RuntimeError(f"Feishu WebSocket failed to start: {startup_error[0]}") from startup_error[0]
        if self._ws_thread is None or not self._ws_thread.is_alive():
            raise RuntimeError("Feishu WebSocket thread exited during startup")
        self._connected = True

    async def send_message(self, jid: str, text: str) -> None:
        if not self._connected:
            return

        chat_id = jid.removeprefix("feishu:")
        req = (
            self._lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                self._lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )

        resp = await asyncio.to_thread(self._client.im.v1.message.create, req)
        if getattr(resp, "code", 0) != 0:
            raise RuntimeError(f"Feishu send_message failed: {getattr(resp, 'msg', 'unknown error')}")

    def is_connected(self) -> bool:
        return self._connected

    def owns_jid(self, jid: str) -> bool:
        return jid.startswith("feishu:")

    async def disconnect(self) -> None:
        self._connected = False
        if self._ws is not None:
            try:
                # lark-oapi ws.Client.close() is sync, not async
                await asyncio.to_thread(self._ws.close)
            except Exception:
                pass
            self._ws = None
        # Wait for ws thread to finish (with timeout)
        if self._ws_thread is not None and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=2.0)
            self._ws_thread = None

    async def set_typing(self, jid: str, is_typing: bool) -> None:
        return

    def _detect_ws_client(self) -> Any | None:
        lark = self._lark
        ws_mod = getattr(lark, "ws", None)
        if ws_mod is None:
            return None
        client_cls = getattr(ws_mod, "Client", None)
        if client_cls is None:
            return None

        channel = self

        def on_event(data: Any) -> None:
            # Schedule async handler from sync callback (called from ws thread)
            if channel._main_loop and channel._main_loop.is_running():
                asyncio.run_coroutine_threadsafe(channel._handle_event(data), channel._main_loop)

        try:
            # lark-oapi >= 1.5.x: Client constructor
            event_handler = (
                lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(on_event).build()
            )
            return client_cls(
                app_id=self._config.feishu_app_id,
                app_secret=self._config.feishu_app_secret,
                event_handler=event_handler,
            )
        except Exception:
            try:
                # lark-oapi < 1.5.x: builder pattern
                builder = client_cls.builder()
                return (
                    builder.app_id(self._config.feishu_app_id)
                    .app_secret(self._config.feishu_app_secret)
                    .on_event(on_event)
                    .build()
                )
            except Exception:
                return None

    async def _handle_event(self, data: Any) -> None:
        try:
            # lark-oapi P2ImMessageReceiveV1 has .event attribute containing message/sender
            event = getattr(data, "event", data)
            message = getattr(event, "message", None) or (event.get("message") if isinstance(event, dict) else None)
            sender = getattr(event, "sender", None) or (event.get("sender") if isinstance(event, dict) else None)
            if not message or not sender:
                return

            raw_chat_id = message.get("chat_id") if isinstance(message, dict) else getattr(message, "chat_id", None)
            if not raw_chat_id:
                return
            chat_jid = f"feishu:{raw_chat_id}"

            message_id = message.get("message_id") if isinstance(message, dict) else getattr(message, "message_id", "")
            create_time = (
                message.get("create_time") if isinstance(message, dict) else getattr(message, "create_time", None)
            )
            timestamp = (
                datetime.fromtimestamp(int(create_time) / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
                if create_time
                else datetime.now(UTC).isoformat().replace("+00:00", "Z")
            )

            sender_id = ""
            if isinstance(sender, dict):
                sid = sender.get("sender_id") or {}
                sender_id = sid.get("user_id") or sid.get("open_id") or ""
            else:
                sid = getattr(sender, "sender_id", None)
                sender_id = getattr(sid, "user_id", "") or getattr(sid, "open_id", "") or ""

            self._on_chat_metadata(chat_jid, datetime.now(UTC).isoformat().replace("+00:00", "Z"), None, "feishu", True)

            group = self._registered_groups().get(chat_jid)
            if not group:
                chat_name = raw_chat_id
                if self._auto_register_group and self._auto_register_group(chat_jid, chat_name, "feishu"):
                    group = self._registered_groups().get(chat_jid)
                else:
                    return

            message_type = (
                message.get("message_type") if isinstance(message, dict) else getattr(message, "message_type", "text")
            )
            if message_type != "text":
                placeholder = f"[{message_type}]"
                self._on_message(
                    chat_jid,
                    NewMessage(
                        id=str(message_id),
                        chat_jid=chat_jid,
                        sender=sender_id,
                        sender_name=sender_id,
                        content=placeholder,
                        timestamp=timestamp,
                        is_from_me=False,
                    ),
                )
                return

            content_raw = message.get("content") if isinstance(message, dict) else getattr(message, "content", "{}")
            parsed = json.loads(content_raw)
            text = parsed.get("text") or ""

            mentions = message.get("mentions") if isinstance(message, dict) else getattr(message, "mentions", None)
            bot_mentioned = False
            if isinstance(mentions, list):
                for mention in mentions:
                    key = mention.get("key")
                    name = mention.get("name")
                    if not key or not name:
                        continue
                    if name.lower() == self._config.assistant_name.lower():
                        bot_mentioned = True
                        text = text.replace(key, f"@{self._config.assistant_name}")
                    else:
                        text = text.replace(key, f"@{name}")

            if bot_mentioned and not self._config.trigger_pattern.search(text):
                text = f"@{self._config.assistant_name} {text}"

            self._on_message(
                chat_jid,
                NewMessage(
                    id=str(message_id),
                    chat_jid=chat_jid,
                    sender=sender_id,
                    sender_name=sender_id,
                    content=text,
                    timestamp=timestamp,
                    is_from_me=False,
                ),
            )
        except Exception as e:
            logger.exception("Feishu event handling failed: %s", e)


def register_feishu_channel(config: AppConfig) -> None:
    def factory(opts: ChannelOpts) -> Channel | None:
        if not config.feishu_app_id or not config.feishu_app_secret:
            return None
        return FeishuChannel(
            config,
            on_message=opts.on_message,
            on_chat_metadata=opts.on_chat_metadata,
            registered_groups=opts.registered_groups,
            auto_register_group=opts.auto_register_group,
        )

    register_channel("feishu", factory)
