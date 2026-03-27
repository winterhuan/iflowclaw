from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .config import AppConfig, BackendCredentials

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    auth_mode: str  # "api-key" | "oauth" | "bearer"
    api_key: str
    oauth_token: str
    upstream_url: str
    api_key_header: str = "x-api-key"


def detect_auth_mode(config: AppConfig, provider: str = "anthropic") -> str:
    normalized_provider = provider.strip().lower()
    if normalized_provider == "openai":
        return "bearer"
    if config.credentials.anthropic_api_key:
        return "api-key"
    return "oauth"


def build_proxy_config_for_provider(provider: str, credentials: BackendCredentials) -> ProxyConfig:
    normalized_provider = provider.strip().lower()
    if normalized_provider == "anthropic":
        return ProxyConfig(
            auth_mode="api-key" if credentials.anthropic_api_key else "oauth",
            api_key=credentials.anthropic_api_key or "",
            oauth_token=credentials.claude_oauth_token or "",
            upstream_url=credentials.anthropic_base_url,
            api_key_header="x-api-key",
        )
    if normalized_provider == "openai":
        return ProxyConfig(
            auth_mode="bearer",
            api_key="",
            oauth_token=credentials.openai_api_key or "",
            upstream_url=credentials.openai_base_url,
        )
    raise ValueError(f"Unsupported credential proxy provider: {provider}")


def build_proxy_config(config: AppConfig, provider: str = "anthropic") -> ProxyConfig:
    return build_proxy_config_for_provider(provider, config.credentials)


def _apply_auth_headers(forward_headers: dict[str, str], proxy_config: ProxyConfig) -> None:
    for header_name in ("x-api-key", "authorization", proxy_config.api_key_header.lower()):
        forward_headers.pop(header_name, None)
    if proxy_config.auth_mode == "api-key":
        if proxy_config.api_key:
            forward_headers[proxy_config.api_key_header.lower()] = proxy_config.api_key
        return
    if proxy_config.auth_mode in {"oauth", "bearer"} and proxy_config.oauth_token:
        forward_headers["authorization"] = f"Bearer {proxy_config.oauth_token}"


def rewrite_request_line_for_upstream(request_line: str, upstream_url: str) -> str:
    parsed_upstream = urlsplit(upstream_url)
    upstream_path = parsed_upstream.path or ""
    upstream_query = parsed_upstream.query or ""
    parts = request_line.split(" ", 2)
    if len(parts) != 3:
        return request_line

    method, target, version = parts
    target_parts = urlsplit(target)
    target_path = target_parts.path or "/"

    if upstream_path and upstream_path != "/":
        prefix = upstream_path.rstrip("/")
        if target_path == "/":
            combined_path = prefix
        elif target_path == prefix or target_path.startswith(prefix + "/"):
            combined_path = target_path
        else:
            combined_path = prefix + (target_path if target_path.startswith("/") else f"/{target_path}")
    else:
        combined_path = target_path

    query_parts = [q for q in (upstream_query, target_parts.query) if q]
    combined_query = "&".join(query_parts)
    rewritten_target = urlunsplit(("", "", combined_path or "/", combined_query, ""))
    return f"{method} {rewritten_target} {version}"


async def start_credential_proxy_with_proxy_config(
    proxy_config: ProxyConfig,
    *,
    port: int,
    host: str = "127.0.0.1",
) -> asyncio.AbstractServer:
    parsed = urlsplit(proxy_config.upstream_url)
    is_https = parsed.scheme == "https"
    upstream_host = parsed.hostname or "api.anthropic.com"
    upstream_port = parsed.port or (443 if is_https else 80)

    async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
            header_text = data.decode("utf-8", errors="replace")
            header_lines = header_text.split("\r\n")
            request_line = rewrite_request_line_for_upstream(header_lines[0], proxy_config.upstream_url)
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
