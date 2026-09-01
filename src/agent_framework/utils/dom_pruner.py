"""
utils/dom_pruner.py — DOM / Accessibility Tree Pruning Utility
===============================================================
Converts raw Playwright accessibility tree snapshots into compact,
LLM-consumable InteractiveElement lists.

Pruning strategy (from spec §3/M6):
1. Extract Playwright Accessibility Tree (role-labeled, structured).
2. Filter to interactive roles only.
3. Assign stable short IDs: e1, e2, ...
4. Truncate to max_elements before LLM submission.
"""

from __future__ import annotations

from typing import Any

from ..models import InteractiveElement

# Roles that qualify as "interactive" for agent decision-making
INTERACTIVE_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "combobox",
    "listitem",
    "checkbox",
    "radio",
    "menuitem",
    "tab",
    "option",
    "spinbutton",
    "slider",
}


def prune_accessibility_tree(
    tree: dict[str, Any],
    max_elements: int = 200,
) -> list[InteractiveElement]:
    """
    Flatten and prune a Playwright accessibility tree snapshot.

    Args:
        tree: Raw accessibility tree dict from Playwright's
              `page.accessibility.snapshot()`.
        max_elements: Maximum number of elements to return.

    Returns:
        List of InteractiveElement objects with stable e{n} IDs.
    """
    flat: list[InteractiveElement] = []
    _walk(tree, flat)

    # Truncate
    flat = flat[:max_elements]

    # Assign stable IDs
    for idx, el in enumerate(flat, start=1):
        el.id = f"e{idx}"

    return flat


def _walk(node: dict[str, Any], result: list[InteractiveElement]) -> None:
    """Recursively walk the accessibility tree, collecting interactive nodes."""
    if not isinstance(node, dict):
        return

    role = (node.get("role") or "").lower()
    name = node.get("name") or node.get("value") or ""

    if role in INTERACTIVE_ROLES and name:
        result.append(
            InteractiveElement(
                id="",  # assigned after pruning
                role=role,
                label=str(name).strip()[:120],  # truncate very long labels
                visible=not node.get("hidden", False),
                aria_label=node.get("description") or None,
                has_bounding_box=node.get("valueString") is not None or True,
            )
        )

    for child in node.get("children", []):
        _walk(child, result)


def elements_to_text(elements: list[InteractiveElement]) -> str:
    """
    Serialize a list of InteractiveElements to a compact text block
    suitable for LLM prompts.
    """
    if not elements:
        return "(no interactive elements detected)"
    lines = []
    for el in elements:
        aria = f" [aria: {el.aria_label}]" if el.aria_label else ""
        vis = "" if el.visible else " [hidden]"
        lines.append(f"[{el.id}] {el.role}: '{el.label}'{aria}{vis}")
    return "\n".join(lines)


def elements_to_compact(elements: list[InteractiveElement]) -> str:
    """
    Ultra-compact element serialization for minimal token usage.
    Format: [id] role "label"  — one per line, no extras.
    """
    if not elements:
        return "(none)"
    lines = []
    for el in elements:
        if not el.visible:
            continue
        label = el.label[:60]  # tighter truncation
        lines.append(f'[{el.id}] {el.role} "{label}"')
    return "\n".join(lines)


def filter_for_task(
    elements: list[InteractiveElement],
    task_keywords: list[str],
    max_elements: int = 30,
) -> list[InteractiveElement]:
    """
    Filter elements to only those relevant to the current task.

    Args:
        elements: Full list of interactive elements.
        task_keywords: Keywords from the current task/goal.
        max_elements: Maximum elements to return.

    Returns:
        Filtered list, prioritizing elements matching task keywords.
    """
    if not task_keywords:
        return elements[:max_elements]

    keywords_lower = [k.lower() for k in task_keywords]

    # Score each element by keyword relevance
    scored = []
    for el in elements:
        label_lower = el.label.lower()
        aria_lower = (el.aria_label or "").lower()
        # Always-relevant roles get a base score
        base_score = 2 if el.role in ("textbox", "searchbox", "combobox") else 0
        # Keyword matches
        keyword_score = sum(
            3 for kw in keywords_lower
            if kw in label_lower or kw in aria_lower
        )
        scored.append((base_score + keyword_score, el))

    # Sort by score descending, then take top N
    scored.sort(key=lambda x: x[0], reverse=True)
    return [el for _, el in scored[:max_elements]]

