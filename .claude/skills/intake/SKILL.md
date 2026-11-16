---
name: intake
description: Turn a vague request from a digital product lead into a decision frame and a project.json. Use at the start of a new task or when the goal, audience or constraints change.
---

# Intake: от размытого запроса к рамке решения

Методика: `workflows/intake.md`. Правила: `AGENTS.md`.

1. Если проекта нет, скопируйте `templates/project-state.json` в `projects/<slug>/project.json` и задайте `path_base: "project"`. Если есть — сначала используйте скилл `resume`.
2. Запишите в журнал начало: `python3 scripts/ledger.py begin projects/<slug>/project.json --key intake-v1 --step intake --action "рамка решения" --model <модель>`. Код 3 — рамка уже сделана: не повторяйте, откройте её.
3. Переформулируйте запрос как **решение**: кто выбирает, между чем, к какому сроку, что будет успехом, цена ошибки. Заполните `objective`, `decision_owner`, `constraints`, `unresolved_questions`.
4. Материалы пользователя зарегистрируйте как источники (`kind`, `verification: provided_by_user`). Открытые страницы — через скилл `research`.
5. Задайте человеку **только блокирующие** вопросы (1–3), каждый с пояснением, какой следующий шаг от него зависит. Остальное — в `unresolved_questions`.
6. **Точка решения человека:** если меняется целевая метрика, аудитория или горизонт — покажите рамку из 5 строк и дождитесь подтверждения.
7. `stage: research_plan`, `next_action`. Затем `ledger.py finish … --key intake-v1` с оценкой токенов (`--estimate-chars IN OUT` или реальные числа) и `checkpoint.py save --summary "Рамка решения"`.

Результат для человека: решение одной фразой; что известно; чего не знаем и как узнаем; следующий шаг.
