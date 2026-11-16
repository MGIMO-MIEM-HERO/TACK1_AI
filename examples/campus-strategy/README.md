# Второй демонстрационный кейс: стратегия «Зачёта»
Не официальный бриф МегаФона. Это самостоятельный тренировочный кейс на
собственных материалах команды, двух прочитанных открытых источниках и
явно синтетической таблице. Интервью и пользовательские проверки не проводились.

Запрос: «Что доделать первым, чтобы кабинет помогал решать учебные вопросы?»
В project.json сохранены основания, четыре альтернативы и две согласованные
стратегии. Агент рекомендует проверку законченного пути справки; выбор владельца
не подменён рекомендацией.

Из корня репозитория:
```
python scripts/project_tool.py inspect examples/campus-strategy/inputs/synthetic-tickets.csv
python scripts/validate_project.py examples/campus-strategy/project.json
python scripts/checkpoint.py examples/campus-strategy/project.json resume
python scripts/project_tool.py audit examples/campus-strategy/project.json --ready
python scripts/project_tool.py report examples/campus-strategy/project.json --out examples/campus-strategy/outputs/decision-brief.md
```

Для проверки пересмотра сделайте копию всей папки во временный проект.
Измените описание возможностей в inputs/product-brief.md и выполните resume:
должны появиться E1, H1 и связанные варианты. Экспорт должен быть заблокирован.
Не перезаписывайте контрольную точку до пересмотра выводов. Сохранение с
--reviewed-changes означает вашу явную отметку о выполненном пересмотре.

В журнале runs.jsonl учитываются только реально выполненные операции.
Полная стоимость разработки и модели неизвестна и не объявляется нулевой.
