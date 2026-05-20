"""Auto-classification heuristics for memory entries.

Pure-function keyword scoring. Given free-form content, returns a (category,
tags) tuple used by `MemoryManager.add_entry` when no explicit category is
provided.
"""

from __future__ import annotations

import re


_CLASSIFICATION_RULES: list[tuple[str, list[str], list[str]]] = [
    ("architecture", ["architecture", "design", "pattern", "api", "rest", "backend", "service", "架构", "设计", "模式"]),
    ("code-pattern", ["function", "method", "def", "class", "函数", "方法", "类"]),
    ("testing", ["test", "assert", "pytest", "unit", "测试", "断言"]),
    ("configuration", ["config", "settings", "env", "配置", "设置", "环境", "database", "db", "connection", "connection string", "connection_string", "connection-string"]),
    ("workflow", ["git", "commit", "branch", "merge", "工作流", "分支", "合并"]),
    ("security", ["security", "auth", "permission", "安全", "认证", "权限", "sanitize", "input validation", "input", "xss", "csrf", "sanitize input", "validate input"]),
    ("performance", ["performance", "optimization", "optimize", "benchmark", "async", "异步", "并发", "性能", "优化", "基准", "index", "indexing", "query"]),
    ("convention", ["convention", "style", "naming", "snake_case", "规范", "风格", "命名"]),
]


_CATEGORY_PRIORITY = {
    "architecture": 8,
    "performance": 7,
    "security": 6,
    "testing": 5,
    "configuration": 4,
    "workflow": 3,
    "convention": 2,
    "code-pattern": 1,
}


def _auto_classify_content(content: str) -> tuple[str, list[str]]:
    """Analyze content and return (category, tags) using keyword heuristics.

    Supports both English and Chinese keywords. Returns "general" category
    with empty tags if no classification rules match.
    """
    content_lower = content.lower()
    category_scores: dict[str, int] = {}
    matched_tags: list[str] = []

    category_to_tags = {
        "architecture": ["design-pattern"],
        "code-pattern": ["function"],
        "testing": ["test"],
        "configuration": ["config"],
        "workflow": ["git"],
        "security": ["security"],
        "performance": ["optimization"],
        "convention": ["style"],
    }

    def _keyword_matches(keyword: str) -> bool:
        if any(ord(ch) > 127 for ch in keyword):
            return keyword in content_lower
        pattern = rf"(?<![a-z0-9_]){re.escape(keyword)}(?![a-z0-9_])"
        return re.search(pattern, content_lower) is not None

    for category, keywords in ((rule[0], rule[1]) for rule in _CLASSIFICATION_RULES):
        score = sum(1 for kw in keywords if _keyword_matches(kw))
        if score > 0:
            category_scores[category] = score
            matched_tags.extend(category_to_tags.get(category, []))

    if not category_scores:
        return "general", []

    # Prefer code-pattern for clear code markers, even if other categories scored higher.
    if "code-pattern" in category_scores:
        if re.search(r"\bdef\b|\bclass\b|\bfunc\b|\(.*\)\s*:\s*$", content_lower) or "()" in content_lower:
            return "code-pattern", category_to_tags.get("code-pattern", [])

    best_category = max(
        category_scores,
        key=lambda category: (category_scores[category], _CATEGORY_PRIORITY.get(category, 0)),
    )
    return best_category, matched_tags
