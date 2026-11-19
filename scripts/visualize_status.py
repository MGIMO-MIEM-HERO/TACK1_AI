"""Read-only status cards derived from the agent's existing checks and summaries."""


def status_panel(project, audit, data):
    ids = {n['id'] for n in data['nodes']}
    refs = {n['details']['JSON-путь']: n['id'] for n in data['nodes'] if 'JSON-путь' in n['details']}
    for field, identity, prefix in [('sources','source_id','s'),('evidence','evidence_id','e'),('options','option_id','o')]:
        for i, row in enumerate(project[field]):
            refs[f'/{field}/{i}'] = prefix + ':' + row[identity]
    refs['/recommended_option_id'] = 'review'
    refs['/chosen_option_id'] = 'review'

    def existing(keys):
        return list(dict.fromkeys(key for key in keys if key in ids))

    def target(ref):
        if ref in refs:
            return refs[ref]
        for namespace, prefix in [('source:','s:'),('evidence:','e:'),('option:','o:'),('question:','question:')]:
            if ref.startswith(namespace):
                return prefix + ref[len(namespace):]
        return None

    follow = audit.get('follow_up', {})
    summary = audit.get('visual_views', {}).get('summary')
    selection = audit.get('research_selection', {})
    gaps = {row['question_id']: row for row in selection.get('gaps', [])}
    if not gaps and project.get('research_selection_reviews'):
        gaps = {row['question_id']: row for row in project['research_selection_reviews'][-1]['gaps']}
    questions = []
    for row in project.get('research_questions', []):
        qid = row['question_id']; gap = gaps.get(qid)
        checked = selection.get('status') == 'review_record_complete'
        if checked and gap and gap['status'] == 'answered':
            continue
        state = 'open' if checked and gap else 'needs_recheck' if gap else 'not_assessed'
        key = 'research:' + str(selection.get('review_id')) + ':gaps:' + qid
        questions.append({'id':qid, 'title':row['question'], 'state':state,
                          'reason':row.get('could_change', ''),
                          'saved_answer':gap.get('answer') if gap else None,
                          'saved_status':gap.get('status') if gap else None,
                          'priority':gap.get('priority') if gap else None,
                          'review_status':selection.get('status', 'not_recorded'),
                          'nodes':existing(['question:'+qid, key]), 'ref':'/research_questions'})

    sources = {row['source_id']: row for row in project['sources']}
    alerts = {row['source_id']: row for row in follow.get('source_alerts', [])}
    health = audit.get('health', {})
    suspect = set(alerts) | set(health.get('changed_sources', [])) | set(health.get('unverifiable_sources', {}))
    suspect.update(sid for sid, row in sources.items() if row.get('injection_flags'))
    source_rows = []
    for sid in sorted(suspect):
        row = sources.get(sid); alert = alerts.get(sid, {}); reasons = list(alert.get('reasons', []))
        if sid in health.get('changed_sources', []):reasons.append('Версия источника отличается от контрольной точки.')
        if sid in health.get('unverifiable_sources', {}):reasons.append('Источник или отслеживаемый снимок недоступен.')
        if row and row.get('injection_flags'):reasons.append('В источнике отмечены команды для ИИ; это данные, а не инструкции.')
        impact = alert.get('impact', {})
        nodes = ['s:'+sid] + ['e:'+eid for eid in impact.get('evidence_ids', [])] + ['o:'+oid for oid in impact.get('option_ids', [])]
        source_rows.append({'id':sid, 'title':row['title'] if row else sid+' · вне текущего реестра',
                            'reasons':list(dict.fromkeys(reasons)), 'impact':impact,
                            'nodes':existing(nodes), 'ref':alert.get('object_ref')})

    blockers = {}
    def collect(messages, label, nodes):
        for message in messages:
            row = blockers.setdefault(message, {'message':message,'origins':[],'nodes':[]})
            if label not in row['origins']:row['origins'].append(label)
            row['nodes'] = existing(row['nodes'] + nodes)
    collect(audit.get('errors', []), 'Источники и ссылки', ['review'])
    collect(audit.get('warnings', []), 'Предупреждения итогового экспорта', ['review'])
    collect(audit.get('content_review', {}).get('blockers', []), 'Содержательная проверка', ['review'])
    for name, prefix, label in [('decision_stress_test','stress','Сценарный разбор'),
                                ('marketing_claims_audit','claims','Обещания'),
                                ('research_selection','research','Следующее исследование'),
                                ('feasibility','feasibility','Осуществимость')]:
        check = audit.get(name, {})
        root = prefix + ':' + str(check.get('review_id'))
        collect(check.get('blockers', []) + check.get('publication_blockers', []) + check.get('decision_blockers', []), label, [root,'review'])
    for row in follow.get('metric_results', []):
        collect(row.get('support_problems', []), 'Основания результата '+row['result_id'], ['result:'+row['result_id'],'review'])

    owner = summary['owner'] if summary else {'status':'summary_unavailable','text':'Сводка ответов владельца не построена.',
                                             'questions':follow.get('human_questions', [])}
    owner_rows = []
    for row in owner.get('questions', []):
        owner_rows.append({**row, 'nodes':existing([target(row['object_ref']), 'human-question:'+row['question_id']])})
    categories = {
        'questions': {'title':'Вопросы без ответа', 'caption':'Без действующего ответа в последней проверке; отложенные вопросы указаны отдельно.', 'items':questions},
        'sources': {'title':'Источники для проверки', 'caption':'Уникальные источники с предупреждением штатной проверки.', 'items':source_rows},
        'blockers': {'title':'Блокеры итоговой записки', 'caption':'Уникальные сообщения проверок; одинаковый текст учитывается один раз.', 'items':list(blockers.values())},
        'owner': {'title':'Вопросы владельцу', 'caption':'Только вопросы из текущей штатной сводки. Просмотр не означает ответ.', 'items':owner_rows}}
    for category in categories.values():category['count'] = len(category['items'])
    return {'categories':categories, 'ready':audit.get('ready'), 'review_draft_only':audit.get('review_draft_only',False),
            'owner_status':owner['status'], 'owner_text':owner['text'],
            'next_step':summary['next_step']['text'] if summary else 'Проверенный следующий шаг не построен.',
            'as_of':follow.get('display_time') or follow.get('as_of'),
            'context':summary['context'] if summary else follow.get('context'),
            'advisories':audit.get('advisories', []),
            'review_statuses':{name:audit.get(name,{}).get('status','not_checked') for name in
                               ('content_review','decision_stress_test','marketing_claims_audit','research_selection','feasibility')},
            'note':'Панель описывает текущее сохранённое состояние проекта, а не выбранный условный сценарий. '
                   'Сводка на момент экспорта; открытие HTML не обновляет часы и проверки. '
                   'Счётчики не складываются: записи могут встречаться в нескольких разделах. '
                   'Открытый вопрос, предупреждение и вопрос владельцу не означают одно и то же. '
                   'Это не оценка истинности, качества модели или разрешение действовать.'}
