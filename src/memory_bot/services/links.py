from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

URL_PATTERN = re.compile(r"https?://[^\s<>\]\[()]+", re.IGNORECASE)


@dataclass(slots=True)
class LinkContent:
    url: str
    title: str | None
    text: str
    content_type: str | None


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(match.rstrip(".,;:!?\"'") for match in URL_PATTERN.findall(text)))


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Chi ho tro URL http/https hop le")
    if parsed.username or parsed.password:
        raise ValueError("URL co thong tin dang nhap khong duoc ho tro")
    loop = __import__("asyncio").get_running_loop()
    addresses = await loop.run_in_executor(
        None,
        lambda: socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM),
    )
    if not addresses or any(not _is_public_ip(item[4][0]) for item in addresses):
        raise ValueError("URL tro den mang noi bo hoac dia chi khong an toan")


class LinkReader:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes

    async def read(self, url: str) -> LinkContent:
        current_url = url
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": "PersonalMemoryBot/0.1"},
        ) as client:
            for _ in range(5):
                await validate_public_url(current_url)
                async with client.stream("GET", current_url, follow_redirects=False) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Redirect khong co dia chi dich")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise ValueError("Noi dung URL vuot qua gioi han tai xuong")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    return self._parse(current_url, body, content_type)
        raise ValueError("URL chuyen huong qua nhieu lan")

    @staticmethod
    def _parse(url: str, body: bytes, content_type: str | None) -> LinkContent:
        if content_type in {"text/html", "application/xhtml+xml"}:
            soup = BeautifulSoup(body, "html.parser")
            for element in soup(["script", "style", "noscript", "svg"]):
                element.decompose()
            title = soup.title.get_text(" ", strip=True) if soup.title else None
            text = "\n".join(
                line.strip() for line in soup.get_text("\n").splitlines() if line.strip()
            )
            return LinkContent(url=url, title=title, text=text[:200_000], content_type=content_type)
        if content_type and (content_type.startswith("text/") or "json" in content_type):
            return LinkContent(
                url=url,
                title=None,
                text=body.decode("utf-8", errors="replace")[:200_000],
                content_type=content_type,
            )
        return LinkContent(url=url, title=None, text="", content_type=content_type)
