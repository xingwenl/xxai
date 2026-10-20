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


def _build_spreadsheetml(sheets: dict[str, list[list[object]]]) -> bytes:
    """构造 Excel 2003 XML（SpreadsheetML）字节。

    该格式是纯 XML 而非 zip 包，但常被导出成 .xlsx 扩展名，
    用于覆盖“按文件头嗅探真实格式”的场景。
    """
    sheet_parts = []
    for name, rows in sheets.items():
        row_parts = []
        for row in rows:
            cells = "".join(
                f'<Cell><Data ss:Type="String">{value}</Data></Cell>' for value in row
            )
            row_parts.append(f"<Row>{cells}</Row>")
        sheet_parts.append(
            f'<Worksheet ss:Name="{name}"><Table>{"".join(row_parts)}</Table></Worksheet>'
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<?mso-application progid="Excel.Sheet"?>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"'
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        + "".join(sheet_parts)
        + "</Workbook>"
    )
    return xml.encode("utf-8")


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

    def test_spreadsheetml_named_xlsx_extracted(self, tmp_path: Path) -> None:
        """真实场景：Excel 2003 XML 被命名为 .xlsx，pandas 会报无法判断格式。"""
        xlsx = tmp_path / "scores.xlsx"
        xlsx.write_bytes(
            _build_spreadsheetml(
                {
                    "Sheet1": [
                        ["岗位代码", "总成绩"],
                        ["2026003", 72.86],
                    ]
                }
            )
        )

        text = load_file_text(xlsx, XLSX_MIME)

        assert "# Sheet1" in text
        assert "岗位代码\t总成绩" in text
        assert "2026003\t72.86" in text

    def test_markup_named_pdf_falls_back_to_markup(self, tmp_path: Path) -> None:
        """扩展名/MIME 与内容不符时，按真实字节走 markup 兜底抽取。"""
        pdf = tmp_path / "table.pdf"
        pdf.write_bytes(
            b"<html><body><table><tr><td>2026003</td>"
            b"<td>72.86</td></tr></table></body></html>"
        )

        text = load_file_text(pdf, PDF_MIME)

        assert "2026003" in text
        assert "72.86" in text

    def test_plain_text_extracted(self, tmp_path: Path) -> None:
        csv = tmp_path / "notes.csv"
        csv.write_text("岗位,总成绩\n综合管理,88.5", encoding="utf-8")

        assert "综合管理,88.5" in load_file_text(csv, "text/csv")

    def test_empty_document_raises(self, tmp_path: Path) -> None:
        """抽不出文本必须抛错，不能静默返回空串当解析成功。"""
        empty = tmp_path / "empty.txt"
        empty.write_bytes(b"")

        with pytest.raises(ValueError, match="未能从文件解析出文本"):
            load_file_text(empty, "text/plain")

    def test_binary_with_document_mime_raises(self, tmp_path: Path) -> None:
        """二进制冒充文档时同样抛错，而不是把乱码当正文入库。"""
        broken = tmp_path / "broken.xlsx"
        broken.write_bytes(b"\x00\x01\x02\x03\xff\xfe garbage bytes")

        with pytest.raises(ValueError, match="未能从文件解析出文本"):
            load_file_text(broken, XLSX_MIME)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_file_text(tmp_path / "not-exist.pdf", PDF_MIME)
