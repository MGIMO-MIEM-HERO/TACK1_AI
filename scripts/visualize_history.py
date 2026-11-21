"""A timeline of explicitly saved records, not reconstructed decision history."""
from datetime import datetime, timezone


def exact_time(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, 'missing'
    if not isinstance(value, str):
        return None, 'invalid'
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if 'T' not in value and ' ' not in value:
            return None, 'date_only'
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None, 'timezone_missing'
        return stamp.astimezone(timezone.utc).isoformat(timespec='microseconds'), 'exact'
    except (ValueError, OverflowError):
        return None, 'invalid'


def decision_history(project, audit, data):
    ids = {n['id'] for n in data['nodes']}
    follow = audit.get('follow_up', {})
    views = audit.get('visual_views', {})
    summary = views.get('summary')
    passport = views.get('passport', {})
    clock, _ = exact_time(follow.get('as_of'))
    answers = {row['object_ref']: row for row in passport.get('confirmations', [])}
    metrics = {row['result_id']: row for row in follow.get('metric_results', [])}
    events = []

    def add(key, kind, title, at, basis, status, details, ref, nodes=()):
        utc, precision = exact_time(at)
        event = dict(id=key, kind=kind, title=title, at=at, time_utc=utc, time_precision=precision,
                     time_basis=basis, after_export_clock=bool(clock and utc and utc > clock),
                     status=status, details=details, ref=ref,
                     nodes=list(dict.fromkeys(node for node in nodes if node in ids)))
        events.append(event)
        return event

    previous_known = None
    has_previous = False
    for index, checkpoint in enumerate(project.get('checkpoints', [])):
        snapshot = checkpoint.get('change_snapshot', {})
        decision = snapshot.get('decision', {})
        known = 'recommended_option_id' in decision
        oid = decision.get('recommended_option_id')
        title = checkpoint['summary']
        details = {'Сохранённая сводка': checkpoint['summary'], 'Этап': checkpoint.get('stage'),
                   'Сохранённый следующий шаг': checkpoint.get('next_action'),
                   'Версия снимка': snapshot.get('decision_version'),
                   'Рекомендация в снимке': oid if known else 'Не записана в структурированном снимке',
                   'Обоснование в снимке': decision.get('recommendation_rationale') if known else 'Не записано',
                   'Оценка изменения': checkpoint.get('change_review')}
        if 'chosen_option_id' in snapshot.get('business', {}):
            details['Выбор человека в снимке'] = snapshot['business']['chosen_option_id']
        if known and has_previous and oid != previous_known:
            title = 'Сохранён другой вариант: ' + str(previous_known or 'без рекомендации') + ' → ' + str(oid or 'без рекомендации')
            details['Предыдущая известная рекомендация'] = previous_known
            details['Границы сравнения'] = 'Сравнены два сохранённых структурированных снимка. Точное время смены рекомендации между ними не установлено.'
        if known:
            previous_known, has_previous = oid, True
        event = add('checkpoint:'+str(index), 'checkpoints', title, checkpoint.get('at'),
                    'Время сохранения контрольной точки, не обязательно время принятия решения.',
                    'saved_checkpoint', details, '/checkpoints/'+str(index), ['change-review:'+str(index)])
        event['recommendation_recorded'] = known
        event['recommendation_id'] = oid if known else None
        answer = checkpoint.get('human_confirmation')
        if answer:
            ref = '/checkpoints/'+str(index)+'/human_confirmation'
            checked = answers.get(ref, {})
            add('answer:'+answer['confirmation_id'], 'answers',
                {'recommendation':'Ответ на рекомендацию', 'permission':'Разрешение действовать', 'data':'Подтверждение данных'}[answer['kind']],
                answer['confirmed_at'], 'Время ответа, указанное в сохранённой записи.',
                checked.get('status', 'not_checked'),
                {**answer, 'Время записи в контрольную точку':checkpoint.get('at'),
                 'Границы предмета':checked.get('scope_description', answer['subject_ref']),
                 'Проверка личности':'Инструмент не удостоверяет личность автора.'}, ref,
                ['answer:'+answer['confirmation_id']])

    for field, prefix, label, audit_key in [
            ('decision_stress_tests','stress','Сценарный разбор','decision_stress_test'),
            ('marketing_claims_audits','claims','Аудит обещаний','marketing_claims_audit'),
            ('research_selection_reviews','research','Выбор исследования','research_selection'),
            ('feasibility_reviews','feasibility','Проверка осуществимости','feasibility')]:
        versions = project.get(field, [])
        for index, review in enumerate(versions):
            status = audit.get(audit_key, {}).get('status', 'not_checked') if index == len(versions)-1 else 'historical'
            details = {k:review[k] for k in ('review_id','reviewer','limitations','context','strongest_objection',
                       'reversal_condition','recommendation','stop_rule') if k in review}
            details['Исходная рекомендация в базе проверки'] = review.get('baseline', {}).get('recommended_option_id')
            details['Версия базы проверки'] = review.get('baseline', {}).get('state_hash')
            details['Границы'] = 'Сохранённая версия разбора. Базовый вариант не устанавливает дату принятия рекомендации.'
            add('review:'+field+':'+review['review_id'], 'reviews', label+' · '+review['review_id'],
                review.get('recorded_at'), 'Время записи версии проверки.', status, details,
                f'/{field}/{index}', [prefix+':'+review['review_id']])

    for index, receipt in enumerate(project.get('follow_up_reviews', [])):
        resume = receipt.get('kind') == 'resume'
        current = False
        utc, _ = exact_time(receipt.get('reviewed_at'))
        checked_version = bool(clock and utc and utc > clock) or bool(summary if resume else receipt.get('result_id') in metrics)
        if clock and utc and utc <= clock:
            if resume and summary:
                current = bool(receipt['version_hash'] == summary['version_hash'] and summary.get('last_view') and
                               receipt['reviewed_at'] == summary['last_view']['reviewed_at'])
            elif not resume:
                row = metrics.get(receipt['result_id'], {})
                current = receipt['version_hash'] == row.get('version_hash') and row.get('reviewed', False)
        details = {k:v for k,v in receipt.items() if k != 'observations'}
        details['Границы'] = 'Только отметка просмотра указанной версии; не согласие, разрешение, выполнение обязательства или подтверждение истинности.'
        add('receipt:'+str(index), 'views', 'Просмотр сводки' if resume else 'Рассмотрение результата '+receipt['result_id'],
            receipt.get('reviewed_at'), 'Сохранённое время просмотра.',
            'current_view' if current else 'historical_view' if checked_version else 'not_checked', details, '/follow_up_reviews/'+str(index),
            [('summary-receipt:' if resume else 'receipt:')+str(index)])

    for index, result in enumerate(project.get('metric_results', [])):
        checked = metrics.get(result['result_id'], {})
        title = result['result_id']+' · '+result['value']+' '+result['unit']
        details = {**result, 'Проблемы оснований':checked.get('support_problems', []),
                   'Границы':'Записанное значение не является автоматическим достижением цели или выполнением обязательства.'}
        add('result:'+result['result_id'], 'results', title, result.get('observed_at'),
            'Время наблюдения из записи результата, не время добавления в проект.',
            'needs_verification' if checked.get('support_problems') else result['data_origin'],
            details, '/metric_results/'+str(index), ['result:'+result['result_id']])
        if result.get('human_decision'):
            add('result-answer:'+result['result_id'], 'answers', 'Ответ только по результату '+result['result_id'],
                None, 'Время ответа в этой записи не указано.',
                'current_result_only' if checked.get('human_decision_current') else 'historical_result' if checked else 'not_checked',
                {**result['human_decision'], 'Границы':'Ответ относится только к версии результата, не к рекомендации проекта.'},
                '/metric_results/'+str(index)+'/human_decision', ['result:'+result['result_id']])

    dated = sorted((e for e in events if e['time_utc']), key=lambda e:e['time_utc'])
    undated = [e for e in events if not e['time_utc']]
    return {'events':dated+undated,
            'counts':{kind:sum(e['kind']==kind for e in events) for kind in ('checkpoints','reviews','answers','views','results')},
            'dated_count':len(dated), 'undated_count':len(undated),
            'current':{'recommendation':project.get('recommended_option_id'),
                       'rationale':project.get('recommendation_rationale'), 'human_choice':project.get('chosen_option_id'),
                       'as_of':follow.get('display_time') or follow.get('as_of'),
                       'time_utc':exact_time(follow.get('display_time') or follow.get('as_of'))[0],
                       'pending_change_events':len(audit.get('material_changes', {}).get('events', []))},
            'note':'История ограничена сохранёнными контрольными точками, версиями проверок, ответами, просмотрами и результатами. '
                   'Пропущенные события не восстанавливаются. Поле updated_at и сроки обязательств не используются как даты решений. '
                   'Переход открывает сохранённую запись и не восстанавливает прошлое состояние текущей карты.'}
