"""Read-only graph projection of optional agent features; no inferred decisions."""


def extend_graph(project, audit, nodes, edges):
    pending = []
    registry = {}
    for field, identity, prefix in [('sources', 'source_id', 's'), ('evidence', 'evidence_id', 'e'), ('options', 'option_id', 'o')]:
        for i, row in enumerate(project[field]):
            registry[f'/{field}/{i}'] = prefix + ':' + row[identity]

    def add(key, column, title, status, record, path, parent=None):
        nodes.append(dict(id=key, column=column, title=title, status=status,
                          details={'JSON-путь': path, **record}))
        registry[path] = key
        if parent:
            edges.append(dict(source=parent, target=key, label='содержит запись'))
        return key

    def refs(key, record, local=None, current=True):
        pending.append((key, record, local or {}, current))

    mappings = [('product_capabilities', 'capability_id', 'cap', 7, 'description', 'availability'),
                ('marketing_claims', 'claim_id', 'claim', 7, 'text', 'kind'),
                ('research_questions', 'question_id', 'question', 8, 'question', 'could_change')]
    for field, identity, prefix, column, title, status in mappings:
        for i, row in enumerate(project.get(field, [])):
            key = add(prefix + ':' + row[identity], column, row[identity] + ' · ' + row[title],
                      str(row.get(status, 'записано')), row, f'/{field}/{i}')
            refs(key, row)

    reviews = [('decision_stress_tests', 'stress', 6, 'decision_stress_test'),
               ('marketing_claims_audits', 'claims', 7, 'marketing_claims_audit'),
               ('research_selection_reviews', 'research', 8, 'research_selection')]
    for field, prefix, column, audit_key in reviews:
        versions = project.get(field, [])
        for i, review in enumerate(versions):
            current = i == len(versions) - 1
            state = audit.get(audit_key, {}) if current else {}
            status = state.get('status', 'статус не проверен') if current else 'историческая версия'
            root = prefix + ':' + review['review_id']
            path = f'/{field}/{i}'
            comparison = {}
            if prefix == 'stress':
                from stress_test import comparison_context
                comparison = {'Сравнение': comparison_context(review)['note']}
            add(root, column, review['review_id'] + ' · ' + {'stress': 'Разбор сценариев',
                'claims': 'Аудит обещаний', 'research': 'Выбор исследования'}[prefix], status,
                {**review, **comparison, 'Текущая проверка': state,
                 'Границы': 'Условные сценарии не меняют решение. Исторические ссылки остаются в сохранённой версии.'}, path)
            children = []
            local = {}
            for collection, identity, title_field, status_field in [
                    ('assumptions', 'assumption_id', 'statement', 'basis'),
                    ('scenarios', 'scenario_id', 'title', 'premise_status'),
                    ('assessments', 'claim_id', 'original_claim', 'status'),
                    ('gaps', 'question_id', 'decision_dependency', 'priority')]:
                for j, row in enumerate(review.get(collection, [])):
                    key = root + ':' + collection + ':' + row[identity]
                    add(key, column, row[identity] + ' · ' + row[title_field],
                        status + ' · ' + str(row.get(status_field, 'записано')), row,
                        f'{path}/{collection}/{j}', root)
                    # Claim/question references lead to current records only for the latest review.
                    if identity == 'assumption_id':
                        local[('assumption_id', row[identity])] = key
                    children.append((key, row))
                    for k, method in enumerate(row.get('methods', [])):
                        mid = key + ':method:' + method['method_id']
                        add(mid, column, method['method_id'] + ' · ' + method['description'],
                            status + ' · ' + method['access'] + ' · ' + method['adequacy'],
                            method, f'{path}/{collection}/{j}/methods/{k}', key)
                        refs(mid, method, current=current)
                        if method['method_id'] == row.get('selected_method_id'):
                            edges.append(dict(source=mid, target=key, label='выбранный метод; не выполненный результат'))
            for key, row in children:
                refs(key, row, local, current)
            if prefix == 'research':
                for name, title in [('recommendation', 'Следующее исследование'), ('stop_rule', 'Условие остановки')]:
                    row = review.get(name)
                    if row:
                        key = add(root + ':' + name, column, title, status + ' · ' + str(row.get('status', row.get('action', ''))),
                                  row, path + '/' + name, root)
                        refs(key, row, current=current)
                        if name == 'recommendation' and row.get('question_id') and row.get('method_id'):
                            method = root + ':gaps:' + row['question_id'] + ':method:' + row['method_id']
                            if any(n['id'] == method for n in nodes):
                                edges.append(dict(source=method, target=key, label='рекомендованный следующий метод; не результат'))

    follow = audit.get('follow_up', {})
    follow_present = bool(project.get('commitments') or project.get('metric_results') or
                          project.get('follow_up_reviews') or follow.get('human_questions'))
    if follow_present:
        add('follow:snapshot', 9, 'Сопровождение решения', 'снимок на ' + follow.get('display_time', 'неизвестное время'),
            follow, '/audit/follow_up')
    commitments = {r['object_ref']: r for r in follow.get('commitments', [])}
    for i, row in enumerate(project.get('commitments', [])):
        path = f'/commitments/{i}'
        checked = commitments.get(path, {})
        key = 'commitment:' + (row.get('commitment_id') or 'legacy:' + str(i))
        add(key, 9, (row.get('commitment_id') or str(i + 1)) + ' · ' + row['metric'],
            checked.get('kind', 'статус срока не проверен'), {**row, 'Проверка срока': checked}, path)
    results = {r['result_id']: r for r in follow.get('metric_results', [])}
    for i, row in enumerate(project.get('metric_results', [])):
        checked = results.get(row['result_id'], {})
        status = 'новая/изменённая версия' if checked.get('new_or_changed') else 'рассмотрено; не означает одобрение' if checked.get('reviewed') else 'не проверено'
        if checked.get('support_problems'):
            status += ' · есть блокеры'
        key = add('result:' + row['result_id'], 9, row['result_id'] + ' · ' + row['value'] + ' ' + row['unit'],
                  row['data_origin'] + ' · ' + status, {**row, 'Проверка результата': checked}, f'/metric_results/{i}')
        refs(key, row)
    for i, row in enumerate(project.get('follow_up_reviews', [])):
        if row.get('kind') == 'resume':
            continue
        checked = results.get(row['result_id'], {})
        current = row['version_hash'] == checked.get('version_hash') and checked.get('reviewed', False)
        key = add('receipt:' + str(i), 9, 'Рассмотрение ' + row['result_id'],
                  'текущая версия; не одобрение' if current else 'историческая версия', row, f'/follow_up_reviews/{i}')
        if current:
            refs(key, row)
    for field in ('source_alerts', 'evidence_alerts'):
        for i, row in enumerate(follow.get(field, [])):
            key = add(f'alert:{field}:{i}', 9, 'Основание для пересмотра', 'предупреждение', row,
                      f'/audit/follow_up/{field}/{i}', 'follow:snapshot')
            refs(key, row)
    for i, row in enumerate(follow.get('human_questions', [])):
        key = add('human-question:' + row['question_id'], 9, row['action'], 'вопрос человеку', row,
                  f'/audit/follow_up/human_questions/{i}', 'follow:snapshot')
        if row['object_ref'] in registry:
            edges.append(dict(source=registry[row['object_ref']], target=key, label='причина вопроса'))

    from visualize_decision import extend_decision
    extend_decision(project, audit, nodes, edges, add, refs, registry)

    prefixes = {'source_id': 's', 'evidence_id': 'e', 'option_id': 'o', 'capability_id': 'cap',
                'claim_id': 'claim', 'question_id': 'question', 'commitment_id': 'commitment', 'result_id': 'result'}
    ids = {n['id'] for n in nodes}
    seen = {(e['source'], e['target'], e['label']) for e in edges}

    def walk(value):
        if isinstance(value, dict):
            for field, item in value.items():
                if field in ('baseline', 'methods', 'answer_branches', 'before', 'after'):
                    continue
                singular = field[:-1] if field.endswith('_ids') else field
                singular = singular.removeprefix('changed_').removeprefix('selected_')
                if singular in prefixes or singular in ('assumption_id', 'work_id', 'resource_id', 'method_id'):
                    for ref in item if isinstance(item, list) else [item]:
                        if isinstance(ref, str):
                            yield singular, ref
                else:
                    yield from walk(item)
        elif isinstance(value, list):
            for item in value:
                yield from walk(item)

    for target, record, local, current in pending:
        for field, ref in walk(record):
            source = local.get((field, ref))
            if source is None and current and field in prefixes:
                source = prefixes[field] + ':' + ref
            edge = (source, target, 'сохранённая ссылка: ' + field)
            if source in ids and source != target and edge not in seen:
                edges.append(dict(source=source, target=target, label=edge[2]))
                seen.add(edge)
