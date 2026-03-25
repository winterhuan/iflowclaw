from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .config import AppConfig

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    auth_mode: str  # "api-key" | "oauth"
    api_key: str
    oauth_token: str
    upstream_url: str


def detect_auth_mode(config: AppConfig) -> str:
    if config.credentials.anthropic_api_key:
        return "api-key"
    return "oauth"


def build_proxy_config(config: AppConfig) -> ProxyConfig:
    creds = config.credentials
    return ProxyConfig(
        auth_mode=detect_auth_mode(config),
        api_key=creds.anthropic_api_key or "",
        oauth_token=creds.claude_oauth_token or "",
        upstream_url=creds.anthropic_base_url,
    )


def _apply_auth_headers(forward_headers: dict[str, str], proxy_config: ProxyConfig) -> None:
    forward_headers.pop("x-api-key", None)
    forward_headers.pop("authorization", None)
    if proxy_config.auth_mode == "api-key":
        if proxy_config.api_key:
            forward_headers["x-api-key"] = proxy_config.api_key
        return
    if proxy_config.oauth_token:
        forward_headers["authorization"] = f"Bearer {proxy_config.oauth_token}"


async def start_credential_proxy_with_proxy_config(
    proxy_config: ProxyConfig,
    *,
    port: int,
    host: str = "127.0.0.1",
) -> asyncio.AbstractServer:
    import urllib.parse  # noqa: PLC0415

    parsed = urllib.parse.urlparse(proxy_config.upstream_url)
    is_https = parsed.scheme == "https"
    upstream_host = parsed.hostname or "api.anthropic.com"
    upstream_port = parsed.port or (443 if is_https else 80)

    async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
            header_text = data.decode("utf-8", errors="replace")
            header_lines = header_text.split("\r\n")
            request_line = header_lines[0]
            headers: dict[str, str] = {}
            for line in header_lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            body = b""
            if content_length > 0:
                body = await asyncio.wait_for(reader.readexactly(content_length), timeout=30)

            forward_headers: dict[str, str] = {}
            for key, value in headers.items():
                if key in ("connection", "keep-alive", "transfer-encoding", "host"):
                    continue
                forward_headers[key] = value

            forward_headers["host"] = upstream_host
            forward_headers["content-length"] = str(len(body))
            _apply_auth_headers(forward_headers, proxy_config)

            if is_https:
                import ssl  # noqa: PLC0415

                ssl_ctx = ssl.create_default_context()
                upstream_reader, upstream_writer = await asyncio.open_connection(
                    upstream_host, upstream_port, ssl=ssl_ctx
                )
            else:
                upstream_reader, upstream_writer = await asyncio.open_connection(upstream_host, upstream_port)

            header_str = f"{request_line}\r\n"
            for key, value in forward_headers.items():
                header_str += f"{key}: {value}\r\n"
            header_str += "\r\n"

            upstream_writer.write(header_str.encode("utf-8") + body)
            await upstream_writer.drain()

            response_data = b""
            while True:
                chunk = await asyncio.wait_for(upstream_reader.read(65536), timeout=120)
                if not chunk:
                    break
                response_data += chunk

            writer.write(response_data)
            await writer.drain()

            upstream_writer.close()
            await upstream_writer.wait_closed()
        except Exception as e:
            logger.error("Credential proxy error: %s", e)
            try:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 11\r\n\r\nBad Gateway")
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_request, host, port)
    logger.info("Credential proxy started on %s:%d (auth_mode=%s)", host, port, proxy_config.auth_mode)
    return server


async def start_credential_proxy(
    config: AppConfig,
    port: int | None = None,
    host: str = "127.0.0.1",
) -> asyncio.AbstractServer:
    actual_port = port or config.credential_proxy_port
    proxy_config = build_proxy_config(config)
    return await start_credential_proxy_with_proxy_config(proxy_config, port=actual_port, host=host)
