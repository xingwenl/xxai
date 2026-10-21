"""版本号比较：插件升级与宿主更新共用一套规则。

前端用字符串比较会踩 ``0.10.0 < 0.9.0``，所以「谁更新」只能由宿主算。规则参考本机
akm 项目的 ``version_greater()``：主版本段按数值逐段比较，数字段相同时「无预发布
后缀的正式版」高于「带后缀的预发布版」（``0.2.0 > 0.2.0-beta``）；非法或空版本不抛
异常，退化为「不认为更高」，避免「检查更新」按钮直接报错。
"""

from __future__ import annotations

import re

_SEGMENT_SPLIT = re.compile(r"[.\-_+~\s]+")
_NUMBER = re.compile(r"^\d+$")
_PREFIX = re.compile(r"^[vV]")


def normalize_version(version: str) -> str:
    """去掉首尾空白、常见的 v 前缀与尾部分隔符（``v0.2.0`` → ``0.2.0``）。"""
    text = (version or "").strip()
    text = _PREFIX.sub("", text)
    return text.strip(".-_+~ ")


def _split_version(version: str) -> tuple[list[int], list[str]]:
    """切成 (主版本数字段, 预发布后缀段)：``0.2.0-beta`` → ([0, 2, 0], ["beta"])。"""
    segments = [part for part in _SEGMENT_SPLIT.split(normalize_version(version)) if part]
    main: list[int] = []
    for index, segment in enumerate(segments):
        if not _NUMBER.match(segment):
            return main, segments[index:]
        main.append(int(segment))
    return main, []


def _compare_main(left: list[int], right: list[int]) -> int:
    """主版本段逐段按数值比较，缺失段补 0（``1.0`` 与 ``1.0.0`` 相等）。"""
    for index in range(max(len(left), len(right))):
        left_value = left[index] if index < len(left) else 0
        right_value = right[index] if index < len(right) else 0
        if left_value != right_value:
            return 1 if left_value > right_value else -1
    return 0


def _compare_segment(left: str, right: str) -> int:
    """比较单个预发布段：数字段按数值，数字段高于非数字段，其余按字典序。"""
    left_is_number = bool(_NUMBER.match(left))
    right_is_number = bool(_NUMBER.match(right))
    if left_is_number and right_is_number:
        return (int(left) > int(right)) - (int(left) < int(right))
    if left_is_number != right_is_number:
        return 1 if left_is_number else -1
    return (left > right) - (left < right)


def _compare_prerelease(left: list[str], right: list[str]) -> int:
    """预发布段逐段比较；前缀相同但更长的更具体（``beta.1 > beta``）。"""
    for index in range(min(len(left), len(right))):
        order = _compare_segment(left[index], right[index])
        if order:
            return order
    if len(left) == len(right):
        return 0
    return 1 if len(left) > len(right) else -1


def compare_versions(left: str, right: str) -> int:
    """返回 -1 / 0 / 1，表示 left 低于 / 等于 / 高于 right。"""
    left_main, left_pre = _split_version(left)
    right_main, right_pre = _split_version(right)
    order = _compare_main(left_main, right_main)
    if order:
        return order
    if not left_pre and not right_pre:
        return 0
    # 主版本相同时，正式版高于预发布版
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    return _compare_prerelease(left_pre, right_pre)


def version_greater(left: str, right: str) -> bool:
    """判断 left 是否严格高于 right（相等、任一为空或无法解析时返回 False）。"""
    if not normalize_version(left) or not normalize_version(right):
        return False
    return compare_versions(left, right) > 0
