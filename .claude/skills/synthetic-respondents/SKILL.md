---
name: synthetic-respondents
description: Generate clearly-labelled model respondents (synthetic personas) to draft hypotheses and an interview guide, and prepare real interviews. Never treat synthetic answers as evidence of real demand.
---

# Модельные респонденты и подготовка интервью

Правила: `knowledge/synthetic-respondents.md`. Шаблоны: `templates/persona.md`, `templates/interview-guide.md`.

1. Соберите 3–5 карточек персон по `templates/persona.md`. Основа — ID открытых фактов, остальное — явные допущения. Обязательно скептик и человек, который не замечает продукт.
2. Вопросы возьмите из реального гайда: прошлый эпизод, альтернативы, отказ. Лучше выполнять в отдельном контексте: новый чат или субагент без ваших гипотез.
3. Сохраните `interviews/synthetic/<дата>-model-respondents.md` с баннером «СИНТЕТИКА», моделью, датой, карточками, вопросами и ответами.
4. Зарегистрируйте источник `kind: model_respondent`, заголовок со словом «модельные/синтетика», `verification: generated`. Из ответов — только `claim_type: hypothesis` с критерием опровержения.
5. Подготовьте реальный гайд в `interviews/interview-guide.md`: отбор, квоты, согласие, вопросы. Реальные записи — только обезличенные, сырьё в `private/` (вне Git).
6. Журнал: `ledger.py log … --step research --action "модельные респонденты" --model … --estimate-chars IN OUT`.
