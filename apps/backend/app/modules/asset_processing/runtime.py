"""附件解析与切块运行时，提供文件读取、文本抽取和切块工具。"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.core.config import get_settings
from app.modules.knowledge.runtime import resolve_storage_path
from app.modules.model_registry.resolver import ResolvedModel

logger = get_logger(__name__)

# 允许上传的 MIME 类型集合
ALLOWED_MIME_TYPES: set[str] = {
    # 图片
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    # 文档
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# 图片 MIME 类型（走原生图片输入，不需要文本解析）
IMAGE_MIME_TYPES: set[str] = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}

# 可解析为文本的文档 MIME 类型
TEXT_PARSEABLE_MIME_TYPES: set[str] = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# 上传文件大小上限（默认 25MB）
DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# 附件最大数量
MAX_ATTACHMENTS_PER_MESSAGE = 10

# 解析器名称和版本（chunk 参数从配置读取）
# 0.2.0：新增按文件头嗅探真实格式（Excel 2003 XML / markup / 纯文本），
# 版本号参与处理版本键计算，版本变更后同内容文件会重新解析。
PARSER_NAME = "SimpleDirectoryReader"
PARSER_VERSION = "0.2.0"

# Excel 2003 XML（SpreadsheetML）命名空间。
# 很多系统导出的“xlsx”其实是这个纯 XML 格式，扩展名与 MIME 都不可信，
# pandas/openpyxl 会直接报“无法判断 Excel 文件格式”。
SPREADSHEET_NS = "urn:schemas-microsoft-com:office:spreadsheet"

# 标记型文档（XML/HTML）按标签边界转纯文本时的分行/分列规则
_MARKUP_LINE_BREAK_TAGS = r"row|tr|p|div|br|worksheet|table|si|w:p"
_MARKUP_CELL_BREAK_TAGS = r"cell|td|th"

# 默认切块参数
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50


def compute_processing_version(
    content_hash: str,
    parser_version: str,
    chunk_size: int,
    chunk_overlap: int,
) -> str:
    """根据文件内容 hash、解析器版本和切块参数生成处理版本键。

    相同输入产生相同版本键，用于缓存命中判断。
    """
    raw = f"{content_hash}|{parser_version}|{chunk_size}|{chunk_overlap}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def compute_file_hash(file_path: Path) -> str:
    """计算文件的 SHA-256 hash。"""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _local_endpoint_without_key(base_url: str | None) -> bool:
    """本地 OpenAI 兼容端点（Ollama 等）允许不配置 API key。"""
    if not base_url:
        return False
    hostname = urlparse(base_url).hostname
    return hostname in {"localhost", "127.0.0.1", "::1", "ollama"}


def attachment_embedding_enabled(
    model_config: ResolvedModel | None = None,
) -> bool:
    """附件向量检索是否启用：维度已配置，且绑定模型或全局配置可用。"""
    settings = get_settings()
    if not settings.attachment_embedding_dimension:
        return False
    if model_config is not None:
        return bool(model_config.model_name) and (
            bool(model_config.api_key)
            or _local_endpoint_without_key(model_config.base_url)
        )
    if not settings.attachment_embedding_model:
        return False
    if settings.attachment_embedding_api_key:
        return True
    return _local_endpoint_without_key(settings.attachment_embedding_base_url)


def build_attachment_embedding_model(
    model_config: ResolvedModel | None = None,
):
    """按绑定模型或全局附件 embedding 配置构建模型，兼容 OpenAI-compatible 服务。"""
    from llama_index.embeddings.openai import (
        OpenAIEmbedding,
        OpenAIEmbeddingModelType,
    )

    settings = get_settings()
    if model_config is not None:
        model = model_config.model_name
        base_url = model_config.base_url
        api_key = model_config.api_key
    else:
        model = settings.attachment_embedding_model
        base_url = settings.attachment_embedding_base_url
        api_key = settings.attachment_embedding_api_key
    if not api_key and base_url:
        hostname = urlparse(base_url).hostname
        if hostname in {"localhost", "127.0.0.1", "::1", "ollama"}:
            api_key = "ollama"
    embed_batch_size = settings.embedding_batch_size
    if model not in {item.value for item in OpenAIEmbeddingModelType}:
        return OpenAIEmbedding(
            model="text-embedding-3-small",
            model_name=model,
            api_base=base_url,
            api_key=api_key,
            embed_batch_size=embed_batch_size,
        )
    return OpenAIEmbedding(
        model=model,
        api_base=base_url,
        api_key=api_key,
        embed_batch_size=embed_batch_size,
    )


def is_image_mime(mime_type: str) -> bool:
    """判断是否为图片 MIME 类型。"""
    return mime_type in IMAGE_MIME_TYPES


def is_text_parseable(mime_type: str) -> bool:
    """判断是否可解析为文本。"""
    return mime_type in TEXT_PARSEABLE_MIME_TYPES


def _decode_bytes(data: bytes) -> str:
    """按常见编码尝试解码文本，全部失败时返回空字符串。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _looks_like_text(text: str) -> bool:
    """判断解码结果是否像文本：二进制误判时代码会得到大量不可打印字符。"""
    if not text:
        return False
    printable = sum(1 for char in text if char.isprintable() or char in "\n\r\t")
    return printable / len(text) >= 0.9


def _sniff_document_format(data: bytes) -> str:
    """按文件头字节判断真实格式。

    扩展名和 MIME 由客户端上报，可能与文件真实字节不符（典型是把
    Excel 2003 XML 命名为 .xlsx），所以抽取前先嗅探一次。
    """
    head = data[:4096]
    if head[:3] == b"\xef\xbb\xbf":
        head = head[3:]
    head = head.lstrip()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if head.startswith(b"<"):
        return "markup"
    return "text"


def _extract_with_default_reader(path: Path) -> str:
    """用 SimpleDirectoryReader 抽取 PDF/OOXML 文档，失败时返回空串。"""
    from llama_index.core import SimpleDirectoryReader

    try:
        documents = SimpleDirectoryReader(input_files=[path]).load_data()
    except Exception:  # noqa: BLE001 - 抽取失败统一由调用方判定
        logger.warning("文件解析失败，将按未抽取到文本处理: %s", path, exc_info=True)
        return ""
    return "\n\n".join(document.text for document in documents if document.text)


def _extract_spreadsheetml_text(data: bytes) -> str:
    """抽取 Excel 2003 XML（SpreadsheetML）文本，非该格式返回空串。

    该格式是纯 XML 而非 zip 包，pandas/openpyxl 都会报“无法判断文件格式”，
    但内容本身是结构化表格，按 工作表 → 行 → 单元格 还原成可检索文本。
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ""
    if not root.tag.startswith(f"{{{SPREADSHEET_NS}}}"):
        return ""

    ns = f"{{{SPREADSHEET_NS}}}"
    lines: list[str] = []
    for sheet in root.iter(f"{ns}Worksheet"):
        sheet_name = sheet.get(f"{ns}Name")
        if sheet_name:
            lines.append(f"# {sheet_name}")
        for row in sheet.iter(f"{ns}Row"):
            cells: list[str] = []
            for cell in row.iter(f"{ns}Cell"):
                data_node = cell.find(f"{ns}Data")
                cells.append(
                    (data_node.text or "").strip() if data_node is not None else ""
                )
            if any(cell for cell in cells):
                lines.append("\t".join(cells))
    return "\n".join(lines)


def _extract_markup_text(data: bytes) -> str:
    """兜底抽取 XML/HTML 类文件文本：按标签边界转成纯文本。"""
    text = _decode_bytes(data)
    if not text:
        return ""
    text = re.sub(rf"(?i)<(?:{_MARKUP_LINE_BREAK_TAGS})\b[^>]*>", "\n", text)
    text = re.sub(rf"(?i)</(?:{_MARKUP_LINE_BREAK_TAGS})\s*>", "\n", text)
    text = re.sub(rf"(?i)</(?:{_MARKUP_CELL_BREAK_TAGS})\s*>", "\t", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_file_text(file_path: str | Path, mime_type: str) -> str:
    """读取文件并抽取规范化文本。

    图片类型返回空字符串（走模型原生图片输入，不解析文本）。文档按文件头
    字节嗅探真实格式后分流：PDF/OOXML(zip) 交给 SimpleDirectoryReader，
    Excel 2003 XML、XML/HTML、纯文本走各自分支。所有分支都抽不到文本时抛
    ValueError，让处理记录落成 failed —— 之前把空文本当成功会导致附件既
    没有被注入模型、attachment_search 也永远搜不到内容，而且没有任何原因提示。
    """
    if is_image_mime(mime_type):
        return ""

    resolved = resolve_storage_path(str(file_path))
    if not resolved.exists():
        raise FileNotFoundError(f"文件不存在: {resolved}")

    data = resolved.read_bytes()
    document_format = _sniff_document_format(data)

    text = ""
    if document_format in {"pdf", "zip"}:
        text = _extract_with_default_reader(resolved)
    elif document_format == "markup":
        text = _extract_spreadsheetml_text(data) or _extract_markup_text(data)
    elif document_format == "text":
        text = _decode_bytes(data)
    # ole（Office 97-2003 二进制）暂不支持，落到下面统一抛错

    text = text.strip()
    if text and not _looks_like_text(text):
        # 解码成功但几乎全是不可打印字符：按二进制处理，不当作正文
        text = ""
    if not text:
        raise ValueError(
            f"未能从文件解析出文本（嗅探格式: {document_format}）: {resolved.name}"
        )
    return text
