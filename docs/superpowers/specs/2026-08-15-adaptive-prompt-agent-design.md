# Design Specification: Adaptive Prompt Engineering Framework for Reliable Autonomous Web Agents

**Version:** 1.0  
**Date:** 2026-08-15  
**Project Type:** Final Year AIML Research Project  

---

## 1. Overview

### 1.1 Problem Statement
Traditional browser automation agents use a single static prompt for every task, making them brittle — when a page layout changes, an element is missing, or a step fails, the agent cannot recover. This system solves that by **dynamically generating, evaluating, and repairing prompts at runtime**.

### 1.2 Research Question
> "Can dynamically generated and self-evaluated prompts improve the reliability of autonomous browser agents, compared to static prompts?"

### 1.3 Architecture Style
**Modular Micro-Pipeline Architecture** — a clean, decoupled Python package where each of 12 functional modules is independently testable, measurable, and swappable for A/B strategy experiments.

---

## 2. Repository Layout

```
Auto/
├── docs/
│   └── superpowers/specs/
│       └── 2026-08-15-adaptive-prompt-agent-design.md
├── src/
│   └── agent_framework/
│       ├── __init__.py
│       ├── config.py                    # Central config (LLM, max_retries, token_budget)
│       ├── models.py                    # Pydantic schemas (Goal, Action, Verification, Telemetry)
│       ├── llm_client.py                # Multi-provider async LLM client
│       ├── modules/
│       │   ├── __init__.py
│       │   ├── intent_parser.py         # Module 1: Intent Understanding
│       │   ├── task_decomposer.py       # Module 2: Task Decomposition
│       │   ├── strategy_selector.py     # Module 3: Prompt Strategy Selection Engine
│       │   ├── prompt_generator.py      # Module 4: Dynamic Prompt Generator
│       │   ├── browser_executor.py      # Module 5: Browser Agent / Action Executor
│       │   ├── page_observer.py         # Module 6: Page State Observer
│       │   ├── action_selector.py       # Module 7: Action Selection Module
│       │   ├── verifier.py              # Module 8: Verification Module
│       │   ├── repair_engine.py         # Module 9: Prompt Repair Engine
│       │   ├── logger.py                # Module 10: Logging & Experiment Tracker
│       │   └── evaluator.py             # Module 11: Evaluation / Comparison Dashboard
│       ├── strategies/
│       │   ├── __init__.py
│       │   ├── static.py               # Static baseline prompting
│       │   ├── dynamic.py              # Context-aware dynamic prompting
│       │   ├── self_reflective.py      # Self-critique + reasoning chain prompting
│       │   └── failure_recovery.py     # Active repair + guided recovery prompting
│       └── utils/
│           ├── dom_pruner.py            # DOM/accessibility tree cleaning
│           ├── token_counter.py         # Token counting utility
│           └── search_client.py         # Search API wrapper (Serp/Bing/Google CSE)
├── ui/
│   └── app.py                          # Module 12: Streamlit UI
├── tests/
│   ├── test_intent_parser.py
│   ├── test_task_decomposer.py
│   ├── test_strategy_selector.py
│   ├── test_verifier.py
│   └── test_repair_engine.py
├── data/
│   └── experiments.db                  # SQLite experiment log
├── logs/
│   └── runs/                           # JSON run traces (per task execution)
├── .env.example
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## 3. Data Flow

```
User Goal (str)
  -> [M1] Intent Parser         -> GoalObject
  -> [M2] Task Decomposer       -> List[SubTask]
  -> [M3] Strategy Selector     -> StrategyContext
  -> Loop per SubTask:
      [M4] Prompt Generator    -> Prompt (str)
      [M5] Browser Executor    -> Action executed; raw page state
      [M6] Page Observer       -> PageState (pruned)
      [M7] Action Selector     -> ActionObject
      [M8] Verifier            -> VerificationResult
      -> If Failure:
          [M9] Repair Engine   -> RepairAmendment -> back to M4 (max 3 retries)
      [M10] Logger             -> Log to SQLite + JSONL
  -> [M11] Evaluator            -> Metrics summary
  -> [M12] Streamlit UI         -> Final results + charts
```
