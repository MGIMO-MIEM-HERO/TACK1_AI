---
name: review-on-new-data
description: Re-assess conclusions, options and an already chosen decision when a source changes, new data arrives or evidence is withdrawn. Use when resume reports changed sources or the user brings new material.
---

# Пересмотр при новых данных

Методика: `knowledge/memory-and-revision.md`.

1. Зафиксируйте новое: `snapshot.py` для страниц (сообщит `content_changed_since_last_snapshot` и затронутые доказательства) или регистрация файла как источника.
2. `python3 scripts/checkpoint.py <project.json> resume` → `changed_source_ids`, `evidence_to_reassess`, `options_to_reassess`.
3. Для отозванного или опровергнутого вывода: `python3 scripts/checkpoint.py <project.json> impact --evidence-ids E-…` → зависимые выводы, варианты и `chosen_option_affected`.
4. Для каждого затронутого доказательства решите: подтверждено, `contradicted`, `stale` или `withdrawn`. Причину запишите в `limitations`. Не удаляйте записи.
5. Пересоберите затронутые варианты и разделы записки. Отметьте в записке «Пересмотрено <дата>: что изменилось и почему».
6. **Если задет выбранный вариант или обязательство** — остановитесь и покажите человеку: что изменилось, что это значит для решения, ваша рекомендация (оставить/скорректировать/отменить).
7. `ledger.py log … --step follow_up --action "пересмотр: …" --evidence …`, затем `checkpoint.py save --reviewed-changes --summary "…"`.
