---
name: strategy
description: Write the recommended product strategy and the matching communication strategy, the validation plan and post-decision commitments into decision-brief.md. Use after the human has seen the options.
---

# Strategy: продуктовая и коммуникационная стратегия, план проверки

Методика: `knowledge/product-strategy.md`, `knowledge/communication-strategy.md`, `workflows/validation-and-follow-up.md`. Шаблон: `templates/decision-brief.md`.

1. `ledger.py begin … --key brief-v<N> --step strategy`.
2. **Продуктовая стратегия:** аудитория и её задача; альтернативы клиента; направление; **осознанные отказы** (что и кому не делаем); связь пользы с затратами и доходами — формула ценности с явными неизвестными множителями. Не подставляйте выдуманные числа.
3. **Коммуникационная стратегия** для той же аудитории: ситуация; барьер понимания или выбора; ключевое сообщение; подтверждение (функция или экран, где обещание видно); роль каждого канала. Проверка «обещание = продукт»: каждое утверждение сообщения должно указывать на конкретную функцию.
4. **План проверки:** ожидаемое изменение, primary metric, с чем сравниваем (дизайн), минимально полезный эффект (если его задаёт владелец — так и написать), guardrails, срок, правило остановки, нежелательные последствия.
5. **После выбора человека:** `chosen_option_id` + `commitments` (owner, metric, due, review_trigger). Валидатор не примет выбор без них.
6. Раздел «Стоимость»: `python3 scripts/ledger.py report <project.json> --out <case>/outputs/cost-report.md`; сравнение с `manual_baseline`.
7. Перед показом — повторный проход `devils-advocate` по записке (одна итерация на версию).
8. `ledger.py finish`, `checkpoint.py save --summary "Записка v<N>"`.

Перед итогом: workflows/decision-review.md, validation_design, strategy_review, audit --ready --quality и report --final. Назначенные пороги не равны согласованным или выполненным. В elapsed begin/finish не включай утверждение об экономии времени.
