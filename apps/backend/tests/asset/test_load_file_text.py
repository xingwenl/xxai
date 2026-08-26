from __future__ import annotations

import io
import zipfile
from pathlib import Path

import openpyxl
import pytest

from app.modules.asset_processing.runtime import load_file_text


def _build_pdf(text: str) -> bytes:
    """构造一个 xref 偏移准确的单页 PDF，确保 pypdf 无警告抽取文本。"""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET".encode()
    objects.append(
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)


def _build_docx(text: str) -> bytes:
    """构造一个最小合法 DOCX（含 Content_Types 与 document.xml）。"""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def _build_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    workbook = openpyxl.Workbook()
    first = True
    for sheet_name, rows in sheets.items():
        sheet = workbook.active if first else workbook.create_sheet()
        first = False
        sheet.title = sheet_name
        for row in rows:
            sheet.append(row)
    workbook.save(path)


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TestLoadFileText:
    """真实样例文件经 SimpleDirectoryReader 抽取文本。"""

    def test_pdf_text_extracted(self, tmp_path: Path) -> None:
        pdf = tmp_path / "sample.pdf"
        pdf.write_bytes(_build_pdf("Hello PDF Content"))

        text = load_file_text(pdf, PDF_MIME)

        assert "Hello PDF Content" in text

    def test_docx_text_extracted(self, tmp_path: Path) -> None:
        docx = tmp_path / "sample.docx"
        docx.write_bytes(_build_docx("Hello Word Content"))

        text = load_file_text(docx, DOCX_MIME)

        assert "Hello Word Content" in text

    def test_xlsx_text_extracted_with_headers(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "sample.xlsx"
        _build_xlsx(
            xlsx,
            {
                "Sheet1": [
                    ["姓名", "城市", "金额"],
                    ["张三", "上海", 100],
                    ["李四", "北京", 200],
                ]
            },
        )

        text = load_file_text(xlsx, XLSX_MIME)

        assert "姓名: 张三, 城市: 上海, 金额: 100" in text
        assert "姓名: 李四, 城市: 北京, 金额: 200" in text

    def test_xlsx_multiple_sheets_all_extracted(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "multi.xlsx"
        _build_xlsx(
            xlsx,
            {
                "明细": [
                    ["项目", "金额"],
                    ["AI SDK", 100],
                ],
                "汇总": [
                    ["统计", "数值"],
                    ["总金额", 100],
                ],
            },
        )

        text = load_file_text(xlsx, XLSX_MIME)

        assert "项目: AI SDK, 金额: 100" in text
        assert "统计: 总金额, 数值: 100" in text

    def test_image_mime_returns_empty(self, tmp_path: Path) -> None:
        image = tmp_path / "pic.png"
        image.write_bytes(b"not a real image")

        assert load_file_text(image, "image/png") == ""

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_file_text(tmp_path / "not-exist.pdf", PDF_MIME)
