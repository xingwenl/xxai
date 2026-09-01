#!/usr/bin/env python3
"""Harness request 一致性审计脚本。

校验 docs/harness/requests/ 下每个 request 的文件完整性与 meta.json 字段一致性。
存在 ERROR 时以非零码退出，可在 CI 或提交前执行。

用法：
    python3 tools/harness/audit.py
"""

import json
import os
import sys
from datetime import datetime

REQUESTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "harness", "requests")
)

PHASES = ("research", "spec", "plan", "implement", "verify", "acceptance")
STATUSES = ("active", "done", "blocked")
# research.status 词汇：pending（未开始）/ done（模板示例）/ completed（仓库实际多数 request 用法）
RESEARCH_STATUSES = ("pending", "done", "completed")

# 每个阶段至少应存在的正式文档（meta.json 总是必需）
PHASE_FILES = {
    "research": (),
    "spec": ("spec.md",),
    "plan": ("spec.md", "plan.md"),
    "implement": ("spec.md", "plan.md"),
    "verify": ("spec.md", "plan.md", "verify.md"),
    "acceptance": ("spec.md", "plan.md", "verify.md", "acceptance.md"),
}


def audit_request(request_id: str):
    """返回 (errors, warnings, infos)。"""
    errors, warnings, infos = [], [], []
    req_dir = os.path.join(REQUESTS_DIR, request_id)
    files = set(os.listdir(req_dir))
    meta_path = os.path.join(req_dir, "meta.json")

    if "meta.json" not in files:
        return [f"{request_id}: 缺少 meta.json"], [], []
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    phase = meta.get("phase")
    status = meta.get("status")

    # 字段枚举校验
    if phase not in PHASES:
        errors.append(f"{request_id}: phase 非法值 {phase!r}（应为 {PHASES}）")
    if status not in STATUSES:
        errors.append(f"{request_id}: status 非法值 {status!r}（应为 {STATUSES}）")

    research = meta.get("research") or {}
    if not meta.get("research"):
        warnings.append(f"{request_id}: meta 缺少 research 字段（模板默认 required=true）")
    research_status = research.get("status")
    if research_status is not None and research_status not in RESEARCH_STATUSES:
        errors.append(
            f"{request_id}: research.status 非法值 {research_status!r}（应为 {RESEARCH_STATUSES}）"
        )

    # 状态流转校验
    if status == "done" and phase != "acceptance":
        errors.append(f"{request_id}: status=done 但 phase={phase!r}（应为 acceptance）")
    if research.get("required") and "research.md" not in files:
        errors.append(f"{request_id}: research.required=true 但缺少 research.md")

    # 阶段文件完整性
    required_files = PHASE_FILES.get(phase, ())
    for name in required_files:
        if name not in files:
            errors.append(f"{request_id}: phase={phase} 但缺少 {name}")
    if status == "done" and "acceptance.md" not in files:
        errors.append(f"{request_id}: status=done 但缺少 acceptance.md")

    # 积压提示：停在 acceptance 且未收口
    if phase == "acceptance" and status == "active":
        try:
            created = datetime.strptime(request_id[:10], "%Y-%m-%d").date()
            age_days = (datetime.now().date() - created).days
            if age_days > 14:
                warnings.append(f"{request_id}: acceptance 阶段积压 {age_days} 天，未标 done/blocked")
            else:
                infos.append(f"{request_id}: acceptance 阶段进行中（{age_days} 天）")
        except ValueError:
            pass

    return errors, warnings, infos


def main() -> int:
    if not os.path.isdir(REQUESTS_DIR):
        print(f"未找到 request 目录：{REQUESTS_DIR}")
        return 2

    request_ids = sorted(os.listdir(REQUESTS_DIR))
    all_errors, all_warnings, all_infos = [], [], []
    for request_id in request_ids:
        req_dir = os.path.join(REQUESTS_DIR, request_id)
        if not os.path.isdir(req_dir):
            continue
        errors, warnings, infos = audit_request(request_id)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        all_infos.extend(infos)

    for line in all_errors:
        print(f"ERROR  {line}")
    for line in all_warnings:
        print(f"WARN   {line}")
    for line in all_infos:
        print(f"INFO   {line}")

    print(f"\nrequests: {len(request_ids)}  ERROR: {len(all_errors)}  WARN: {len(all_warnings)}")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
