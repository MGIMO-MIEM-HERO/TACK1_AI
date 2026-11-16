---
name: adapt-brief
description: Start a new project from an officially published competition or company brief, reusing an example case structure. Use when the user provides a new brief (e.g., the MegaFon demo-project brief).
---

# Адаптация к опубликованному брифу

1. Сохраните бриф: открытый URL → `snapshot.py`; файл от пользователя → `projects/<slug>/sources/brief.*`, источник `kind: document`, `verification: provided_by_user`.
2. Выберите ближайший пример: `examples/operator-subscription-case` (цифровой сервис оператора, открытые данные) или `examples/activation-case` (данные продукта, эксперимент). Скопируйте структуру в `projects/<slug>/`, очистите `ledger.jsonl`, `checkpoints`, `evidence`, `options`.
3. Выполните скилл `intake` по тексту брифа. Требования брифа — в `constraints`; критерии оценки — в определение успеха.
4. Переносите из примера только методы и шаблоны. Факты примера — только если они относятся к брифу и сняты первоисточниками. Синтетику не переносите.
5. Сверьте бриф с `README.md`: какие требования покрыты, какие нет. Расхождения запишите в `unresolved_questions`.
