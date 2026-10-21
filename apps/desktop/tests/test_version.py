"""版本号比较测试：宿主更新与插件升级共用 ``desktop_app.version`` 的实现。"""

from __future__ import annotations

import pytest

from desktop_app.version import compare_versions, normalize_version, version_greater


@pytest.mark.parametrize(
    ("newer", "older"),
    [
        ("0.10.0", "0.9.0"),  # 字符串比较在这里会错
        ("1.0.0", "0.99.99"),
        ("0.2.0", "0.2.0-beta"),  # 正式版高于预发布版
        ("1.0.0", "v0.9.9"),  # v 前缀
        ("2", "1.9.9"),
        ("1.0.1", "1.0"),
    ],
)
def test_version_greater_accepts_newer(newer: str, older: str) -> None:
    assert version_greater(newer, older) is True
    assert version_greater(older, newer) is False


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0.2.0", "0.2.0"),
        ("1.0.0", "1"),
        ("v1.0.0", "1.0"),
        ("0.2.0-beta", "0.2.0-beta"),
    ],
)
def test_version_greater_equal_is_false(left: str, right: str) -> None:
    assert version_greater(left, right) is False
    assert compare_versions(left, right) == 0


def test_compare_versions_orders_prerelease() -> None:
    assert compare_versions("0.2.0-rc1", "0.2.0-beta") == 1
    assert compare_versions("0.2.0-beta.1", "0.2.0-beta") == 1


@pytest.mark.parametrize(("version", "expected"), [("v0.2.0", "0.2.0"), (" 1.0.0 ", "1.0.0"), ("", "")])
def test_normalize_version(version: str, expected: str) -> None:
    assert normalize_version(version) == expected


@pytest.mark.parametrize(
    ("left", "right"),
    [("", "1.0.0"), ("1.0.0", ""), ("", ""), ("not-a-version", "1.0.0")],
)
def test_version_greater_invalid_input_does_not_raise(left: str, right: str) -> None:
    assert version_greater(left, right) is False
