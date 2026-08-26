"""附件解析与切块运行时，提供文件读取、文本抽取和切块工具。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.logging import get_logger
from app.modules.knowledge.runtime import resolve_storage_path

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
PARSER_NAME = "SimpleDirectoryReader"
PARSER_VERSION = "0.1.0"

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


def is_image_mime(mime_type: str) -> bool:
    """判断是否为图片 MIME 类型。"""
    return mime_type in IMAGE_MIME_TYPES


def is_text_parseable(mime_type: str) -> bool:
    """判断是否可解析为文本。"""
    return mime_type in TEXT_PARSEABLE_MIME_TYPES


def load_file_text(file_path: str | Path, mime_type: str) -> str:
    """读取文件并抽取规范化文本。

    图片类型返回空字符串，由调用方标记为 ready（不解析文本）。
    其他类型使用 SimpleDirectoryReader 统一抽取。
    """
    from llama_index.core import SimpleDirectoryReader

    if is_image_mime(mime_type):
        return ""

    resolved = resolve_storage_path(str(file_path))
    if not resolved.exists():
        raise FileNotFoundError(f"文件不存在: {resolved}")

    documents = SimpleDirectoryReader(input_files=[resolved]).load_data()
    return "\n\n".join(document.text for document in documents if document.text)
