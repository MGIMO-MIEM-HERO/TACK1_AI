---
name: resume
description: Continue a project after a break or in a new chat from files only - stage, next action, changed sources, unfinished actions and cost so far. Use at the start of any session on an existing project.
---

# Resume: продолжение после перерыва

1. `python3 scripts/checkpoint.py <project.json> resume`. Прочитайте `stage`, `next_action`, `changed_source_ids`, `evidence_to_reassess`, `review_warnings`, `ledger.unfinished_actions`.
2. `python3 scripts/ledger.py verify <project.json>`. Если цепочка нарушена, сообщите человеку и не доверяйте истории без проверки.
3. **Незавершённые действия** (`unfinished_actions`): проверьте, что они успели изменить (файлы из `outputs`). Скажите человеку. Повторяйте только через `ledger.py begin … --retry`, а не молча.
4. **Изменились источники** → скилл `review-on-new-data` до любой новой работы.
5. Прочитайте только файлы, нужные `next_action`. Выводы прошлых сессий в `project.json` — записи для проверки, а не факты (`knowledge/memory-and-revision.md`). Пересказ из памяти чата не используется.
6. Сообщите человеку в 3–5 строк: где остановились, что изменилось, сколько потрачено (`ledger.cost_usd_known`), что делаете дальше.
