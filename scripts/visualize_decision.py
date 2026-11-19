"""Projection of resource plans, decision branches, change reviews and scoped answers."""


def extend_decision(project, audit, nodes, edges, add, refs, registry):
    def link(source, target, label):
        if source and target and source != target:
            edges.append(dict(source=source, target=target, label=label))

    feasibility = audit.get('feasibility', {})
    current_plans = {}
    versions = project.get('feasibility_reviews', [])
    for i, review in enumerate(versions):
        current = i == len(versions) - 1
        state = feasibility if current else {}
        status = state.get('status', 'не проверено') if current else 'историческая версия'
        path = f'/feasibility_reviews/{i}'
        root = 'feasibility:' + review['review_id']
        add(root, 10, review['review_id'] + ' · Осуществимость', status,
            {**review, 'Текущая проверка': state}, path)
        checked = {r['option_id']: r for r in state.get('assessments', [])}
        for j, plan in enumerate(review['assessments']):
            key = root + ':' + plan['option_id']
            base = f'{path}/assessments/{j}'
            calculated = checked.get(plan['option_id'], {})
            add(key, 10, plan['option_id'] + ' · ' + plan['minimum_scope'],
                status + ' · ' + calculated.get('outcome', 'исход не проверен'),
                {**plan, 'Вычисленный исход': calculated,
                 'Границы': 'Ресурсы, разрешение и согласование рекомендации — разные предметы.'}, base, root)
            refs(key, {k: v for k, v in plan.items() if k not in ('work', 'resources', 'allocations', 'dependencies')}, current=current)
            if current:
                current_plans[plan['option_id']] = key
            local = {}
            for field, identity, title in [('work', 'work_id', 'description'),
                                            ('resources', 'resource_id', 'resource_id'),
                                            ('dependencies', 'dependency_id', 'description')]:
                for k, row in enumerate(plan[field]):
                    child = key + ':' + field + ':' + row[identity]
                    local[(identity, row[identity])] = child
                    add(child, 10, row[identity] + ' · ' + row[title],
                        status + ' · ' + row.get('status', 'условия записаны; не гарантия'),
                        row, f'{base}/{field}/{k}', key)
                    refs(child, row, current=current)
            for k, row in enumerate(plan['allocations']):
                child = add(key + ':allocation:' + str(k), 10,
                            row['work_id'] + ' ← ' + row['resource_id'], status + ' · план нагрузки',
                            row, f'{base}/allocations/{k}', key)
                refs(child, row, local, current=False)

    selection = audit.get('research_selection', {})
    versions = project.get('research_selection_reviews', [])
    resolutions = {r['question_id']: r for r in selection.get('branch_resolutions', [])}
    for i, review in enumerate(versions):
        current = i == len(versions) - 1
        for j, gap in enumerate(review['gaps']):
            parent = 'research:' + review['review_id'] + ':gaps:' + gap['question_id']
            result = resolutions.get(gap['question_id'], {}) if current else {}
            conditions = {r['branch_id']: r for r in result.get('conditions', [])}
            for k, branch in enumerate(gap.get('answer_branches', [])):
                bid = branch.get('branch_id', str(k + 1))
                key = parent + ':branch:' + bid
                checked = conditions.get(bid, {})
                status = 'историческая версия' if not current else (
                    selection.get('status', 'не проверено') + ' · ' +
                    ('insufficient_data' if branch.get('condition', {}).get('kind') == 'insufficient_data'
                     else checked.get('state', 'не сопоставлено')))
                add(key, 8, bid + ' · ' + branch['answer'], status,
                    {**branch, 'Проверка условия': checked,
                     'Границы': 'Условная ветка не означает выбор владельца или выполненное действие.'},
                    f'/research_selection_reviews/{i}/gaps/{j}/answer_branches/{k}', parent)
                refs(key, branch, current=current)
                method_id = branch.get('condition', {}).get('method_id')
                method = parent + ':method:' + str(method_id)
                if any(n['id'] == method for n in nodes):
                    link(method, key, 'метод проверки условия')
                if current:
                    for requirement in branch.get('condition', {}).get('requirements', []):
                        link(current_plans.get(requirement['option_id']), key, 'условие осуществимости; не разрешение')
            if result:
                branch_id = result['branch_id']
                contextual = (result['status'] == 'not_applicable' and
                              gap.get('impact') == 'context' and not gap.get('answer_branches'))
                if branch_id is None:
                    if not contextual:
                        raise ValueError(gap['question_id'] + ': null branch requires an unbranched context question')
                    branch = None
                else:
                    if not isinstance(branch_id, str) or not any(
                            n['id'] == parent + ':branch:' + branch_id for n in nodes):
                        raise ValueError(gap['question_id'] + ': unknown branch in resolution')
                    branch = parent + ':branch:' + branch_id
                title = ' · Контекстный вопрос · без выбора ветки' if branch is None else ' · Текущая развилка'
                key = add(parent + ':resolution', 8, gap['question_id'] + title,
                          result['status'], result, f'/audit/research_selection/branch_resolutions/{gap["question_id"]}', parent)
                if branch is not None:
                    link(branch, key, 'сопоставленный исход; не решение человека')
                refs(key, result)

    changes = audit.get('material_changes', {})
    if changes.get('enabled'):
        add('changes:current', 11, 'Изменения и влияние на решение', changes['status'],
            {k: v for k, v in changes.items() if k != 'snapshot'}, '/audit/material_changes')
        for i, event in enumerate(changes['events']):
            key = add('change-event:' + event['event_id'], 11, event['kind'] + ' · ' + event['object_ref'],
                      event['classification'], event, f'/audit/material_changes/events/{i}', 'changes:current')
            refs(key, event)
        for i, cp in enumerate(project.get('checkpoints', [])):
            if 'change_review' not in cp:
                continue
            review = cp['change_review']
            parent = add('change-review:' + str(i), 11, cp['summary'], 'сохранённая оценка · ' + review.get('kind', ''),
                         {'at': cp['at'], **review}, f'/checkpoints/{i}/change_review')
            for j, event in enumerate(review.get('events', [])):
                add(parent + ':event:' + str(j), 11, event.get('kind', 'Событие изменения'),
                    'историческая оценка · ' + event.get('materiality', event.get('classification', '')),
                    event, f'/checkpoints/{i}/change_review/events/{j}', parent)
        for i, row in enumerate(changes.get('human_questions', [])):
            add('change-question:' + row['question_id'], 11, row['action'], 'вопрос владельцу', row,
                f'/audit/material_changes/human_questions/{i}', 'changes:current')

    views = audit.get('visual_views', {})
    summary = views.get('summary')
    passport = views.get('passport')
    if summary:
        fields = {'Что изменилось': summary['changes']['text'], 'На какое решение влияет': summary['decision']['text'],
                  'Что требуется от владельца': summary['owner']['text'], 'Следующий шаг': summary['next_step']['text'],
                  'Последний просмотр': summary['last_view'] or 'Просмотр ещё не записан',
                  'Версия': summary['version_hash'], 'Контекст': summary['context'], 'Примечание': summary['note']}
        add('summary:current', 12, 'Продолжение работы · четыре пункта', summary['owner']['status'], fields, '/derived/resume_summary')
        link('summary:current', 'next', 'проверенный следующий шаг')
        next_node = next(n for n in nodes if n['id'] == 'next')
        next_node['details'] = {'Проверенный следующий шаг': summary['next_step']['text'],
                                'Ранее записанный план (требует проверки актуальности)': project['next_action'],
                                **{k: v for k, v in next_node['details'].items() if k != 'Действие'}}
        next_node['status'] = 'проверенный шаг по текущему состоянию; не факт выполнения'
    if passport:
        recommendation = passport['recommendation']
        fields = {'Рекомендация': (recommendation['title'] or 'Не сформирована') +
                  (' · ' + recommendation['option_id'] if recommendation['option_id'] else ''),
                  'Обоснование': recommendation['rationale'] or 'Не записано',
                  'Неизвестное': [row['text'] for row in passport['unknowns']],
                  'Пределы оснований': passport['inference_limits'],
                  'Условия пересмотра': [row['text'] for row in passport['revisit_conditions']],
                  'Блокеры': passport['blockers'], 'Версия': passport['version'], 'Режим': passport['version_mode'],
                  'Примечание': passport['note']}
        add('passport:current', 12, 'Паспорт решения', 'требует проверки' if passport['blockers'] else 'снимок текущего состояния', fields, '/derived/decision_passport')
        refs('passport:current', passport['recommendation'])
        link('summary:current' if summary else None, 'passport:current', 'сводка текущего паспорта')
        options = {n['id']: n for n in nodes if n['id'].startswith('o:')}
        for row in passport['alternatives']:
            options['o:' + row['option_id']]['details']['Оценка выбора в паспорте'] = {
                'status': row['selection_status'], 'reason': row['selection_reason']}
            link('o:' + row['option_id'], 'passport:current', 'альтернатива в паспорте; ' + row['selection_status'])
        confirmations = passport['confirmations']
    else:
        confirmations = [{**cp['human_confirmation'], 'status': 'актуальность не проверена',
                          'object_ref': f'/checkpoints/{i}/human_confirmation'}
                         for i, cp in enumerate(project.get('checkpoints', [])) if 'human_confirmation' in cp]
    subjects = {'/recommended_option_id': 'passport:current', '/chosen_option_id': 'task'}
    for name, prefix, identity in [('sources', 'source', 'source_id'), ('evidence', 'evidence', 'evidence_id'), ('options', 'option', 'option_id')]:
        for row in project[name]:
            subjects[prefix + ':' + row[identity]] = {'source': 's', 'evidence': 'e', 'option': 'o'}[prefix] + ':' + row[identity]
    for row in confirmations:
        key = add('answer:' + row['confirmation_id'], 12, row['kind'] + ' · ' + row['outcome'],
                  row['status'] + ' · ' + row['outcome'], row, row['object_ref'])
        if row['status'] == 'current':
            target = subjects.get(row['subject_ref'])
            if target and any(n['id'] == target for n in nodes):
                link(key, target, 'ответ только на указанный предмет и версию: ' + row['kind'])
    if passport:
        for i, row in enumerate(passport['confirmation_requests']):
            answered = any(a['status'] == 'current' and a['kind'] == row['kind'] and
                           a['subject_ref'] == row['subject_ref'] for a in confirmations)
            add('answer-request:' + str(i), 12, 'Предмет ответа · ' + row['kind'],
                'явный ответ записан' if answered else 'ожидает явного ответа; запрос не согласие',
                row, f'/derived/decision_passport/confirmation_requests/{i}', 'passport:current')
        for i, row in enumerate(passport['legacy_records']):
            add('legacy-answer:' + str(i), 12, 'Прежняя запись · ' + row['kind'], row['status'],
                row, f'/derived/decision_passport/legacy_records/{i}', 'passport:current')
    for i, receipt in enumerate(project.get('follow_up_reviews', [])):
        if receipt.get('kind') != 'resume':
            continue
        current = bool(summary and receipt['version_hash'] == summary['version_hash'] and summary['last_view'] and
                       receipt['reviewed_at'] == summary['last_view']['reviewed_at'])
        key = add('summary-receipt:' + str(i), 12, 'Просмотр сводки',
                  'просмотр текущей версии; не согласие' if current else 'исторический просмотр; не согласие',
                  receipt, f'/follow_up_reviews/{i}')
        if current:
            link(key, 'summary:current', 'просмотр; не одобрение')
