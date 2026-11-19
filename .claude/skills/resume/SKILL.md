---
name: resume
description: Continue a project after a break or in a new chat from files only - stage, next action, changed sources, unfinished actions and cost so far. Use at the start of any session on an existing project.
---

# Resume: продолжение после перерыва

1. `python3 scripts/start.py <project.json> --json`. Первым покажите четыре пункта `resume_summary`: изменения, решение, запрос владельцу, следующий шаг. Подробности — по ссылкам и `--details`; см. `workflows/project-resume-summary.md`. `checkpoint.py resume` возвращает ту же сводку.
2. `python3 scripts/ledger.py verify <project.json>`. Если цепочка нарушена, сообщите человеку и не доверяйте истории без проверки.
3. **Незавершённые действия** (`unfinished_actions`): проверьте, что они успели изменить (файлы из `outputs`). Скажите человеку. Повторяйте только через `ledger.py begin … --retry`, а не молча.
4. **Изменились источники** → скилл `review-on-new-data` до любой новой работы.
5. Прочитайте только файлы, нужные `resume_summary.next_step`. При изменении оснований или ресурсов прежний `next_action` может быть неактуален. Выводы прошлых сессий — записи для проверки, а не факты (`knowledge/memory-and-revision.md`).
6. Открытие ничего не сохраняет. Только после фактического рассмотрения явно отметьте просмотр точной версии по workflow. Укажите реального рассмотревшего; самопроверка агента не означает, что владелец увидел или согласовал решение. Уже рассмотренные вопросы остаются ожиданием ответа, а не новым запросом. Расходы и детали доступны в полном отчёте.
