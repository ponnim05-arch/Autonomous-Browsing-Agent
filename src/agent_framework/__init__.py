"""
Adaptive Prompt Engineering Framework
======================================
A modular research system for comparing prompting strategies in autonomous
browser agents.

Modules:
    M1  intent_parser      – Parse NL goal → GoalObject
    M2  task_decomposer    – GoalObject → List[SubTask]
    M3  strategy_selector  – Select prompting strategy
    M4  prompt_generator   – Generate prompt string
    M5  browser_executor   – Execute browser actions (Playwright)
    M6  page_observer      – Prune DOM → PageState
    M7  action_selector    – PageState → ActionObject
    M8  verifier           – Verify action outcomes
    M9  repair_engine      – Generate repair amendments on failure
    M10 logger             – SQLite + JSONL telemetry
    M11 evaluator          – Compute & compare metrics
    M12 ui/app.py          – Streamlit interface
"""

__version__ = "1.0.0"
__author__ = "AIML Research Project"
