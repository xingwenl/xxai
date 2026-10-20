"""知识库文档加载复用附件解析链路：抽不出文本必须报错，不能静默成功。"""

import pytest

from app.modules.knowledge.runtime import load_file_text


SPREADSHEET_NS = "urn:schemas-microsoft-com:office:spreadsheet"


def _build_spreadsheetml(rows: list[list[str]]) -> str:
    body = "".join(
        "<Row>"
        + "".join(f'<Cell><Data ss:Type="String">{cell}</Data></Cell>' for cell in row)
        + "</Row>"
        for row in rows
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Workbook xmlns="{SPREADSHEET_NS}" '
        f'xmlns:ss="{SPREADSHEET_NS}">'
        f'<Worksheet ss:Name="Sheet1">{body}</Worksheet>'
        "</Workbook>"
    )


def test_spreadsheetml_document_extracted(tmp_path):
    """把 Excel 2003 XML 命名为 .xlsx 时也要能抽出表格文本。"""
    path = tmp_path / "成绩.xlsx"
    path.write_text(
        _build_spreadsheetml(
            [["岗位代码", "总成绩"], ["2026003", "72.86"]],
        ),
        encoding="utf-8",
    )

    text = load_file_text(str(path))

    assert "# Sheet1" in text
    assert "岗位代码\t总成绩" in text
    assert "2026003\t72.86" in text


def test_unparseable_document_raises(tmp_path):
    """二进制文件抽不出文本时必须抛错，让入库任务标记失败而不是空文档成功。"""
    path = tmp_path / "broken.pdf"
    path.write_bytes(bytes([0, 1, 2, 3, 4, 5]))

    with pytest.raises(ValueError, match="未能从文件解析出文本"):
        load_file_text(str(path))
