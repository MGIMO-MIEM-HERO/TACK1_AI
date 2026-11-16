---
name: options
description: Build at least three substantively different options (including keep-as-is and close/freeze) with strongest objections, then run an independent devil's-advocate critique. Use after synthesis.
---

# Options: варианты и сильные возражения

Методика: `workflows/options-and-strategy.md`, `knowledge/product-strategy.md`.

1. `ledger.py begin … --key options-v<N> --step options`. Код 3 — версия уже готова.
2. Перед вариантами выпишите картину ситуации: факты (с ID), ассоциации, гипотезы, прогнозы, неизвестное.
3. Сформулируйте 3–5 вариантов в `options` с полем `kind`:
   - `status_quo` (оставить как есть) — обязательно;
   - `stop` (закрыть/заморозить) — обязательно;
   - минимум один из `change` / `pivot`; при большой неопределённости — `learn` (проверка до инвестиций).
   Варианты должны различаться ставкой (аудитория, ценность, модель, канал), а не формулировкой.
4. Для каждого: `benefits`, `costs_and_risks`, `objection` (сильнейшее возражение, которое вы не можете легко отбить), `evidence_ids`.
5. **Критика.** В Claude Code вызовите субагента `devils-advocate` с путями к `project.json` и черновику записки. Он работает в чистом контексте и не видит ваших рассуждений. Сохраните ответ в `outputs/critique-<дата>.md`; исправления внесите в варианты и записку. В Cursor/Codex откройте новый чат с инструкцией из `.claude/agents/devils-advocate.md`. Если запустить отдельно нельзя, отметьте в критике, что независимость не обеспечена.
6. `validate_project.py` (требует ≥3 вариантов со `status_quo` и `stop`), `ledger.py finish`, `checkpoint.py save`.
7. **Точка решения человека:** покажите таблицу вариантов, вашу рекомендацию с уверенностью и что её перевернёт. **Не записывайте выбор за человека.**
