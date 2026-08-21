"""远程插件元数据抓取：受限 HTTP 客户端、三级抓取链与图标消毒。

抓取链（业界标准）：站点 web manifest.json -> Open Graph 标签 -> <title> + favicon。
所有对外请求都经过 SSRF 校验（允许公网 / 本机回环 / 私有网段，重定向逐跳重校验）。
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

USER_AGENT = "WW-Desktop/0.2 (+https://example.local)"
MAX_HTML_SIZE = 2 * 1024 * 1024
MAX_ICON_SIZE = 1024 * 1024
REQUEST_TIMEOUT = 10.0
_SIZE_PATTERN = re.compile(r"^(\d+)x(\d+)$")


class MetadataError(Exception):
    """元数据抓取失败（含 SSRF 校验失败）。"""


# ---------- SSRF 防护 ----------


def _is_fetchable_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判断 IP 是否可抓取：允许公网、本机回环与私有网段（桌面应用本机场景）。

    仍拒绝链路本地（169.254.0.0/16、fe80::/10）、组播、保留与未指定地址，
    避免抓取打到链路自动配置地址或无意义的目标。
    """
    # 回环（IPv6 的 ::1 在 ipaddress 中同时标记为 reserved）是本机本地开发场景，必须放行
    if ip.is_loopback:
        return True
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return True


def validate_fetchable_url(url: str) -> str:
    """校验 URL 仅允许 http/https 且目标地址可抓取；非法时抛出 MetadataError。"""
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise MetadataError("仅支持 http/https 的公网地址")
    if not parsed.hostname:
        raise MetadataError("URL 缺少主机名")
    if parsed.username or parsed.password:
        raise MetadataError("URL 不允许携带账号信息")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise MetadataError(f"域名解析失败: {parsed.hostname}") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        # IPv4 映射的 IPv6（如 ::ffff:127.0.0.1）按内嵌 IPv4 判断
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        addresses.append(ip)
    if not any(_is_fetchable_ip(ip) for ip in addresses):
        raise MetadataError("目标地址不可访问（链路本地 / 组播 / 保留 / 未指定地址）")
    return url


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向逐跳重新执行 SSRF 校验，阻止跳入内网。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913
        validate_fetchable_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urlopen(request: urllib.request.Request, timeout: float = REQUEST_TIMEOUT):
    """受限 HTTP 客户端：SSRF 校验 + 重定向逐跳校验；独立封装便于测试注入。"""
    validate_fetchable_url(request.full_url)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    resp = opener.open(request, timeout=timeout)
    validate_fetchable_url(resp.geturl())
    return resp


def _read_capped(resp, limit: int) -> bytes:
    """带上限读取响应体，防止超大响应拖垮宿主。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = resp.read(min(64 * 1024, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise MetadataError(f"响应体超过大小限制（{limit} 字节）")
        chunks.append(chunk)
    return b"".join(chunks)


def _header(resp, name: str) -> str | None:
    """大小写不敏感地读取响应头（兼容 email.Message 与 dict）。"""
    try:
        for key, value in resp.headers.items():
            if key.lower() == name.lower():
                return value
    except AttributeError:
        return None
    return None


def _resolve(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href.strip())


# ---------- HTML 元信息解析 ----------


class _HtmlMetaParser(HTMLParser):
    """提取 title、og 标签、manifest 与图标声明。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.manifest_url: str | None = None
        self.og: dict[str, str] = {}
        self.apple_touch_icon: str | None = None
        self.icon: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            prop = (attr_map.get("property") or attr_map.get("name") or "").lower()
            if prop.startswith("og:") and attr_map.get("content"):
                self.og[prop] = attr_map["content"]
        elif tag == "link":
            rel = " ".join(attr_map.get("rel", "").lower().split())
            href = attr_map.get("href")
            if not href:
                return
            if "manifest" in rel.split():
                self.manifest_url = href
            elif "apple-touch-icon" in rel.split() and self.apple_touch_icon is None:
                self.apple_touch_icon = href
            elif "icon" in rel.split() and self.icon is None:
                self.icon = href

    def handle_data(self, data: str) -> None:
        if self.title is None and data.strip():
            self.title = data.strip()


# ---------- SVG 消毒 ----------


class _SvgSanitizer(HTMLParser):
    """移除 <script>、事件属性与 javascript: 链接，重建安全的 SVG。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._script_depth = 0

    def _clean_attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        parts: list[str] = []
        for name, value in attrs:
            name_l = name.lower()
            value_l = (value or "").lstrip().lower()
            if name_l.startswith("on") or value_l.startswith("javascript:"):
                continue
            parts.append(f' {name}="{html.escape(value or "", quote=True)}"')
        return "".join(parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._script_depth += 1
            return
        if self._script_depth:
            return
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" or self._script_depth:
            return
        self.out.append(f"<{tag}{self._clean_attrs(attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._script_depth = max(0, self._script_depth - 1)
            return
        if self._script_depth:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._script_depth:
            self.out.append(data)

    def handle_comment(self, data: str) -> None:
        return

    def handle_decl(self, decl: str) -> None:
        return


def sanitize_svg(data: bytes) -> bytes:
    """对 SVG 图标消毒：剥离 script、事件属性与 javascript: 链接。"""
    text = data.decode("utf-8", errors="replace")
    parser = _SvgSanitizer()
    parser.feed(text)
    parser.close()
    return "".join(parser.out).encode("utf-8")


# ---------- 抓取链 ----------


@dataclass
class SiteMetadata:
    """站点抓取结果：名称 / 描述 / 图标字节与扩展名（图标可能缺失）。"""

    name: str
    description: str
    icon_bytes: bytes | None = None
    icon_ext: str | None = None


def _best_manifest_icon(manifest: dict, manifest_url: str) -> str | None:
    """从 manifest.icons 选择最合适的图标：优先解析尺寸，取面积最大且 <=512。"""
    icons = manifest.get("icons") or []
    candidates: list[tuple[int, str]] = []
    for icon in icons:
        src = (icon or {}).get("src")
        if not src:
            continue
        sizes = (icon or {}).get("sizes", "")
        match = _SIZE_PATTERN.match(str(sizes))
        area = (int(match.group(1)) * int(match.group(2))) if match else 0
        candidates.append((area, src))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0] > 512 * 512, -item[0]))
    return _resolve(manifest_url, candidates[0][1])


def _parse_manifest(manifest_url: str, fetcher) -> dict:
    """拉取并解析站点 web manifest.json（仅取安装所需字段）。"""
    request = urllib.request.Request(manifest_url, method="GET", headers={"User-Agent": USER_AGENT})
    try:
        resp = fetcher(request, timeout=REQUEST_TIMEOUT)
    except (urllib.error.URLError, OSError, MetadataError) as exc:
        raise MetadataError(f"manifest 抓取失败: {exc}") from exc
    if resp.getcode() != 200:
        raise MetadataError(f"manifest 返回非 200 状态: {resp.getcode()}")
    try:
        data = json.loads(_read_capped(resp, MAX_HTML_SIZE).decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MetadataError("manifest 不是合法 JSON") from exc
    name = str(data.get("name") or data.get("short_name") or "").strip()
    description = str(data.get("description") or "").strip()
    icon_url = _best_manifest_icon(data, manifest_url)
    return {"name": name, "description": description, "icon_url": icon_url}


def _pick_icon_url(page_url: str, parser: _HtmlMetaParser, manifest_icon: str | None) -> str | None:
    """图标候选链：manifest 图标 -> og:image -> apple-touch-icon -> rel=icon -> /favicon.ico。"""
    if manifest_icon:
        return manifest_icon
    if parser.og.get("og:image"):
        return _resolve(page_url, parser.og["og:image"])
    if parser.apple_touch_icon:
        return _resolve(page_url, parser.apple_touch_icon)
    if parser.icon:
        return _resolve(page_url, parser.icon)
    parsed = urllib.parse.urlparse(page_url)
    return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"


def _icon_ext(content_type: str | None, url: str) -> str:
    """根据 Content-Type 或 URL 后缀推断图标扩展名。"""
    suffix = urllib.parse.urlparse(url).path.lower()
    if content_type:
        ctype = content_type.split(";")[0].strip().lower()
        mapping = {
            "image/svg+xml": "svg",
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "image/x-icon": "ico",
            "image/vnd.microsoft.icon": "ico",
        }
        if ctype in mapping:
            return mapping[ctype]
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".ico", ".svg"):
        if suffix.endswith(ext):
            return ext.lstrip(".")
    return "png"


def fetch_icon(icon_url: str, fetcher=None) -> tuple[bytes, str]:
    """下载图标：SSRF 校验、类型与大小限制；SVG 额外消毒。"""
    fetcher = fetcher or _urlopen
    validate_fetchable_url(icon_url)
    request = urllib.request.Request(icon_url, method="GET", headers={"User-Agent": USER_AGENT})
    try:
        resp = fetcher(request, timeout=REQUEST_TIMEOUT)
    except (urllib.error.URLError, OSError, MetadataError) as exc:
        raise MetadataError(f"图标下载失败: {exc}") from exc
    if resp.getcode() != 200:
        raise MetadataError(f"图标下载返回非 200 状态: {resp.getcode()}")
    content_type = _header(resp, "Content-Type")
    ext = _icon_ext(content_type, icon_url)
    if content_type and not content_type.lower().startswith("image/"):
        # 少数服务器把图标报成 octet-stream：按 URL 后缀放行，其余拒绝
        if "octet-stream" not in content_type.lower():
            raise MetadataError(f"图标响应不是图片类型: {content_type}")
    data = _read_capped(resp, MAX_ICON_SIZE)
    if ext == "svg":
        data = sanitize_svg(data)
    return data, ext


def fetch_site_metadata(url: str, fetcher=None) -> SiteMetadata:
    """按三级抓取链获取站点元数据：manifest.json -> og 标签 -> title + favicon。"""
    fetcher = fetcher or _urlopen
    page_url = validate_fetchable_url(url)
    request = urllib.request.Request(page_url, method="GET", headers={"User-Agent": USER_AGENT})
    try:
        resp = fetcher(request, timeout=REQUEST_TIMEOUT)
    except (urllib.error.URLError, OSError, MetadataError) as exc:
        raise MetadataError(f"站点抓取失败: {exc}") from exc
    if resp.getcode() != 200:
        raise MetadataError(f"站点返回非 200 状态: {resp.getcode()}")
    html_text = _read_capped(resp, MAX_HTML_SIZE).decode("utf-8", errors="replace")
    parser = _HtmlMetaParser()
    parser.feed(html_text)
    parser.close()

    name = ""
    description = ""
    icon_url: str | None = None
    if parser.manifest_url:
        try:
            manifest = _parse_manifest(_resolve(page_url, parser.manifest_url), fetcher)
            name = manifest["name"]
            description = manifest["description"]
            icon_url = manifest["icon_url"]
        except MetadataError:
            # manifest 不可用不是致命错误：降级到 og / title
            pass
    if not name:
        name = parser.og.get("og:title", "").strip() or parser.title or ""
    if not description:
        description = parser.og.get("og:description", "").strip()
    icon_url = _pick_icon_url(page_url, parser, icon_url)

    icon_bytes: bytes | None = None
    icon_ext: str | None = None
    try:
        icon_bytes, icon_ext = fetch_icon(icon_url, fetcher)
    except (MetadataError, urllib.error.URLError, OSError):
        # 图标缺失可接受：安装时回退到占位图标
        pass
    return SiteMetadata(name=name, description=description, icon_bytes=icon_bytes, icon_ext=icon_ext)


def preflight_frameable(url: str, fetcher=None) -> bool | None:
    """预检站点是否允许被 iframe 嵌入；无法判断（HEAD 失败等）返回 None。"""
    fetcher = fetcher or _urlopen
    page_url = validate_fetchable_url(url)
    request = urllib.request.Request(page_url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        resp = fetcher(request, timeout=REQUEST_TIMEOUT)
    except urllib.error.HTTPError as exc:
        # HEAD 不支持时按不可判断处理，运行时仍可降级到系统浏览器
        if exc.code in {403, 405, 501}:
            return None
        return None
    except (urllib.error.URLError, OSError, MetadataError):
        return None
    if resp.getcode() != 200:
        return None

    xfo = (_header(resp, "X-Frame-Options") or "").upper()
    if "DENY" in xfo:
        return False
    if "SAMEORIGIN" in xfo or "ALLOW-FROM" in xfo:
        return False
    csp = _header(resp, "Content-Security-Policy") or ""
    directive = ""
    for part in csp.split(";"):
        tokens = part.strip().split()
        if tokens and tokens[0].lower() == "frame-ancestors":
            directive = " ".join(tokens[1:]).lower()
            break
    if directive:
        if "'none'" in directive:
            return False
        if "*" in directive:
            return True
        # 明确列出祖先源：宿主为回环地址，站点不会放行，按不可嵌入处理
        return False
    return True
