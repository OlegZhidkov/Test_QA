# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this is

The Ammeter Testing Exercise (spec: `Exam/ammeter-test-specification.md`): a testing framework around three TCP-socket ammeter emulators (Greenlee, ENTES, CIRCUTOR) in `Ammeters/`. The ammeter checks are written as pytest test cases in `tests/`; the framework's own tests are in `tests/framework/`. Python 3.11+, libraries: `pyyaml` (runtime) and `pytest` (tests).

Scope right now is the core of the spec (unified API, sampling, statistics, result management, config, `main.py` working) plus error simulation (faults injected into managed emulators, `config/error_simulation.yaml`). The other bonus items (visualization, accuracy comparison) come later.

## Commands

- Install: `python3 -m pip install -r requirements.txt`
- Run: `python3 main.py`
- All tests (303, about 35 s): `python3 -m pytest`
- Error-simulation scenario only: `python3 -m pytest tests/test_error_simulation.py`
- Framework tests only (`tests/framework/`): `python3 -m pytest tests/framework`
- Ammeter tests only (directly in `tests/`): `python3 -m pytest tests --ignore=tests/framework`

## Rules (from the exam spec)

**Technical constraints**
- Use the existing emulator infrastructure. Never delete a given file. If the given code has an error, fix it and explain the fix, with its reason, in `docs/design-decisions.md`.
- Minimal dependencies. List every installed library in the README.
- Cross-platform: `pathlib`, no OS-specific calls.
- Clear, readable code: small modules with one job each, type hints, short docstrings, no dead code or commented-out blocks.

**Evaluation criteria**
- Flexibility: ports, commands, sampling and expected ranges come from `config/config.yaml`; nothing hard-coded. Adding an ammeter should not need framework edits.
- Error handling: every failure path is handled explicitly (connection refused, timeout, empty or non-numeric reply, invalid config, unwritable results folder). Specific exception types, no bare `except`, no silent failures.
- Reporting: every run reports consistently: ammeter, run ID, parameters, statistics.

**Deliverables:** Python implementation, README with usage, sample results (`docs/sample_results/`), brief design-decisions document.

## Working rules

- Tests first. Small, focused commits.
- Git author is Guy Zhidkov only. Never add `Co-Authored-By`, "Generated with Claude Code" or any other attribution to commits, pull requests or files.
- Never push without telling the user first.
- Explain things to the user in simple terms.

## Workflow

Work proceeds in three phases; do not start a phase until the previous one is done.

1. **Planning** — `architect` subagent: design and implementation plan.
2. **Implementing** — `automation-engineer` subagent: tests-first implementation following the plan.
3. **Reviewing** — `reviewer` subagent: checks the work against the spec and the rules above; findings are fixed before finishing.

Subagent definitions live in `.claude/agents/`.
