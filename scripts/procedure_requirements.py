"""Final-document prerequisites, separate from provenance and human approval."""


def validate_fields(project):
    errors = []
    for option in project.get('options', []):
        if not isinstance(option, dict) or 'feasibility_requirement' not in option:
            continue
        item = option['feasibility_requirement']
        prefix = 'Option ' + str(option.get('option_id')) + ' feasibility_requirement: '
        if not isinstance(item, dict):
            errors.append(prefix + 'must be an object')
            continue
        if set(item) != {'status', 'action', 'rationale'}:
            errors.append(prefix + 'needs status, action and rationale only')
        if item.get('status') not in ('required', 'not_applicable'):
            errors.append(prefix + 'status must be required/not_applicable')
        if item.get('action') not in ('development', 'launch', 'research', 'maintenance', 'freeze', 'other'):
            errors.append(prefix + 'needs an explicit action classification')
        if not isinstance(item.get('rationale'), str) or not item['rationale'].strip():
            errors.append(prefix + 'needs a substantive rationale')
        if item.get('action') in ('development', 'launch') and item.get('status') != 'required':
            errors.append(prefix + 'development/launch requires a resource check')
    return errors


def inspect(project, stress, feasibility):
    recommended = project.get('recommended_option_id')
    if not recommended:
        return {'blockers': [], 'checks': {
            key: {'status': 'not_applicable', 'reason': 'Рекомендация ещё не сформирована; это не допуск к финальной записке.'}
            for key in ('decision_stress_test', 'feasibility')}}
    checks, blockers = {}, []
    checks['decision_stress_test'] = {'status': stress['status'],
        'reason': 'При сформированной рекомендации требуется актуальный сценарный разбор всех вариантов.',
        'next_step': 'Подготовить и записать разбор через scripts/stress_test.py.'}
    if stress['status'] != 'review_record_complete':
        blockers.append('Required decision stress review is ' + stress['status'] + '; prepare and record scenarios before final export')
    option = next(o for o in project['options'] if o['option_id'] == recommended)
    requirement = option.get('feasibility_requirement')
    if requirement and requirement['status'] == 'not_applicable':
        checks['feasibility'] = {**requirement, 'reason': requirement['rationale']}
    elif requirement or project.get('feasibility_reviews'):
        covered = any(a['option_id'] == recommended and 'plan' in a for a in feasibility['assessments'])
        status = feasibility['status'] if covered else (
            feasibility['status'] if feasibility['status'] in ('stale', 'blocked') else 'not_recorded')
        checks['feasibility'] = {'status': status,
            'reason': requirement['rationale'] if requirement else 'Проверка применима: в проекте уже записан ресурсный разбор.',
            'next_step': 'Проверить минимальный объём, компетенции, ёмкость и календарь именно рекомендованного варианта.'}
        if status != 'review_record_complete':
            blockers.append('Required feasibility review for ' + recommended + ' is ' + status + '; record its resource plan before final export')
    else:
        checks['feasibility'] = {'status': 'unknown',
            'reason': 'Применимость ресурсной проверки не записана; название и kind варианта её не определяют.',
            'next_step': 'Указать options[].feasibility_requirement: действие, required/not_applicable и содержательное обоснование.'}
        blockers.append('Feasibility applicability is unknown for ' + recommended + '; classify the action and justify applicability before final export')
    return {'checks': checks, 'blockers': blockers,
            'note': 'Полнота процедур не подтверждает истинность анализа и не заменяет решение владельца.'}
