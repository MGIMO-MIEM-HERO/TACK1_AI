# CLAUDE.md

Постоянные правила агента — в @AGENTS.md (общие для Claude Code, Cursor и Codex). Здесь — только то, что специфично для Claude Code.

- **Скиллы** (`.claude/skills/`): `intake`, `research`, `synthetic-respondents`, `options`, `strategy`, `resume`, `review-on-new-data`, `adapt-brief`. В начале работы с существующим проектом — `resume`.
- **Субагенты** (`.claude/agents/`): `source-researcher` — чтение многих открытых страниц вне основного контекста (модель sonnet); `devils-advocate` — независимая критика вариантов и записки (модель opus, только чтение, один проход на версию).
- **Hooks** (`.claude/settings.json`, скрипты в `scripts/hooks/`): SessionStart показывает проекты и незавершённые действия; PreToolUse блокирует запись секретов и `.env`; PostToolUse проверяет `project.json` валидатором и пишет запись в журнал проекта; Stop один раз напоминает сохранить checkpoint.
- Стоимость: вызовы моделей и поиска записывайте в `ledger.jsonl` через `python3 scripts/ledger.py log …`; отчёт — `ledger.py report`.
