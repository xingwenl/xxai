"""首轮工具组预取的规则测试：纯函数，无 IO、无模型。"""

from __future__ import annotations

import pytest

from app.modules.agent_runtime.tool_prefetch import (
    MIN_PREFETCH_SCORE,
    PREFETCH_RULES,
    prefetch_tool_groups,
)

ALL_GROUPS = set(PREFETCH_RULES)


def test_two_keyword_hits_load_the_group():
    assert prefetch_tool_groups("帮我查一下订单和库存", ALL_GROUPS) == {"ops"}


def test_single_keyword_is_not_enough():
    """单个词误伤面太大，宁可漏选：漏选只多一次 load_tool_group。"""

    assert MIN_PREFETCH_SCORE >= 2
    assert prefetch_tool_groups("订单呢", ALL_GROUPS) == set()


def test_multi_group_message_loads_every_matched_group():
    """命中就加载：不设组数上限。"""

    loaded = prefetch_tool_groups("每天定时把订单和库存下载成图片", ALL_GROUPS)

    assert loaded == {"ops", "content", "task"}


def test_result_is_subset_of_available_groups():
    """只预取当前工具清单里真实存在的组，不猜不存在的组。"""

    assert prefetch_tool_groups("订单和库存", {"memory"}) == set()
    assert prefetch_tool_groups("订单和库存", {"ops", "memory"}) == {"ops"}


def test_english_keywords_match_case_insensitively():
    assert prefetch_tool_groups("用 PDF 和 http 下载附件", ALL_GROUPS) == {"content"}


@pytest.mark.parametrize("message", ["", "   ", "你好呀今天天气不错"])
def test_unmatched_message_returns_empty(message):
    assert prefetch_tool_groups(message, ALL_GROUPS) == set()


def test_every_rule_group_has_keywords_and_is_unique():
    for group, keywords in PREFETCH_RULES.items():
        assert group, "组名不能为空"
        assert len(keywords) >= MIN_PREFETCH_SCORE, f"{group} 关键词不足以达标"
        assert len(set(keywords)) == len(keywords), f"{group} 关键词重复"
