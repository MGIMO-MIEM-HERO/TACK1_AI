"""Four read-only continuation points; explicit view receipts never approve a decision."""
import copy
from datetime import datetime, timezone
import re

from material_changes import digest, enabled, source_versions


def validate_receipt(receipt):
    from follow_up import instant
    errors = []
    sha = lambda value: isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{64}', value))
    if set(receipt) != {'kind', 'version_hash', 'observations', 'reviewed_at', 'reviewer', 'note'}:
        errors.append('Resume receipt has unexpected or missing fields; it is a view, not approval')
    if not sha(receipt.get('version_hash')): errors.append('Resume receipt needs a SHA-256 version_hash')
    for k in ('reviewer', 'note'):
        if not isinstance(receipt.get(k), str) or not receipt[k].strip(): errors.append('Resume receipt needs ' + k)
    observations = receipt.get('observations')
    if not isinstance(observations, dict) or not observations or any(not isinstance(k, str) or not sha(v) for k, v in observations.items()):
        errors.append('Resume receipt observations must be a nonempty fingerprint map')
    try: instant(receipt.get('reviewed_at'))
    except (ValueError, TypeError): errors.append('Resume receipt needs an offset-aware reviewed_at')
    return errors


def compact(value, limit=180):
    value = ' '.join(str(value).split())
    return value if len(value) <= limit else value[:limit - 1] + '…'


def build(project, path, root, audit, follow_up, ledger):
    now = datetime.fromisoformat(follow_up['as_of'])
    receipts = [r for r in project.get('follow_up_reviews', []) if r.get('kind') == 'resume'
                and datetime.fromisoformat(r['reviewed_at'].replace('Z', '+00:00')) <= now]
    previous = receipts[-1] if receipts else None
    changes = audit['material_changes']
    observations, references, labels = {}, {}, {}

    def observe(key, value, label, refs):
        observations[key] = digest(value); references[key] = refs; labels[key] = label

    base = path.parent if project.get('path_base') == 'project' else root
    versions = source_versions(project, base)
    by_source = {s['source_id']: s for s in project['sources']}
    for sid, row in versions.items():
        metadata = {k:v for k,v in by_source[sid].items() if k != 'title' or not enabled(project)}
        observe('source:' + sid, {**row, 'metadata': metadata}, 'источник ' + sid, ['source:' + sid])
    for e in project['evidence']:
        observe('evidence:' + e['evidence_id'], e, 'основание ' + e['evidence_id'], ['evidence:' + e['evidence_id']])
    observe('decision', {k: project.get(k) for k in ('objective', 'constraints', 'recommended_option_id',
            'recommendation_rationale', 'chosen_option_id', 'options', 'product_strategy', 'communication_strategy',
            'validation_plan', 'validation_design')}, 'условия решения', ['/recommended_option_id', '/options'])
    for row in follow_up['commitments']:
        observe('commitment:' + row['commitment_id'], row, 'обязательство ' + row['commitment_id'], [row['object_ref']])
    for row in follow_up['metric_results']:
        observe('result:' + row['result_id'], {'version': row['version_hash'], 'problems': row['support_problems'],
                'human_decision_current': row['human_decision_current']}, 'результат ' + row['result_id'], [row['object_ref']])
    for name in ('feasibility', 'research_selection'):
        observe(name, audit[name], 'осуществимость' if name == 'feasibility' else 'развилки исследования',
                ['/feasibility_reviews' if name == 'feasibility' else '/research_selection_reviews'])
    observe('health', {'source_alerts': follow_up['source_alerts'], 'evidence_alerts': follow_up['evidence_alerts'],
            'errors': audit['errors'], 'quality': audit['content_review']['blockers'],
            'unfinished': ledger.get('unfinished_actions', []), 'chain': ledger.get('chain_intact', True),
            'ledger_error': ledger.get('error')},
            'проверки оснований и журнала', ['/sources', '/evidence', 'ledger'])
    assessments = [r for r in changes['history'] if r.get('assessment')]
    if assessments: observe('material_review', assessments[-1], 'разбор влияния изменения', ['/checkpoints'])
    from decision_passport import confirmation_states
    responses = confirmation_states(project, path, root, changes.get('after_version'), at=follow_up['as_of']) if changes['enabled'] else []
    response = next((r for r in reversed(responses) if r['kind'] == 'recommendation' and r['status'] == 'current'), None)
    if responses: observe('human_answers', responses, 'ответ владельца для версии', ['/checkpoints'])
    questions = []
    owner_questions = list(follow_up['human_questions'])
    if project.get('recommended_option_id') and not project.get('chosen_option_id') and not owner_questions and not response:
        from decision_passport import subject_version
        question_version = subject_version(project, 'recommendation', '/recommended_option_id', changes['after_version']) if changes['enabled'] else observations['decision']
        owner_questions.append({'question_id': 'recommendation:' + question_version,
            'object_ref': '/recommended_option_id', 'reason': 'Рекомендация есть, выбор владельца не записан.',
            'action': 'После проверки оснований показать рекомендацию и альтернативы владельцу; выбор оставлен человеку.'})
    for question in owner_questions:
        key = 'question:' + question['question_id']
        observe(key, question, 'вопрос владельцу', [question['object_ref']])
        seen = bool(previous and previous['observations'].get(key) == observations[key])
        questions.append({**question, 'seen_in_summary': seen, 'reply_recorded': False})

    old = previous['observations'] if previous else {}
    changed = sorted(k for k in set(old) | set(observations) if old.get(k) != observations.get(k)) if previous else []
    substantive = [e for e in changes['events'] if e['classification'] != 'cosmetic']
    if previous:
        status = 'changed' if changed else 'unchanged'
        text = ('Изменилось: ' + ', '.join(labels.get(k, 'удалённый объект ' + k) for k in changed[:3]) +
                ('; ещё ' + str(len(changed) - 3) if len(changed) > 3 else '') + '.') if changed else 'Новых изменений с последнего отмеченного просмотра нет.'
    else:
        status = 'first_review'
        text = 'Отметки просмотра ещё нет; исходная сводка.'
        pending = sorted(audit['health']['changed_sources'])
        if pending or substantive:
            text += ' Изменения после контрольной точки: ' + str(len(pending)) + ' источников, ' + str(len(substantive)) + ' событий.'
        elif project.get('checkpoints'):
            text += ' Новых изменений источников после контрольной точки нет.'
        else: text += ' Контрольной точки для сравнения источников нет.'

    touched = sorted({oid for e in substantive for oid in e['impact']['option_ids']})
    selected = project.get('chosen_option_id'); recommended = project.get('recommended_option_id')
    decision_ids = touched or [oid for oid in (recommended, selected) if oid]
    decision_ids = list(dict.fromkeys(decision_ids))
    titles = {o['option_id']: compact(o['title'], 50) for o in project['options']}
    impact = (('Затронуты варианты: ' if touched else 'Текущее решение: ') +
              ', '.join(oid + ' — ' + titles.get(oid, 'исторический вариант') for oid in decision_ids[:3])) if decision_ids else 'Решение ещё не сформировано; уточнить рамку задачи.'
    if changes['needs_assessment']: impact += '; влияние на вывод ещё оценивается.'
    if assessments:
        last = assessments[-1]['assessment']
        impact += ' Последний разбор: ' + {'changed':'вывод изменился', 'unchanged':'вывод сохранён', 'unknown':'влияние неизвестно'}[last['conclusion']] + '.'
    fresh_questions = [q for q in questions if not q['seen_in_summary']]
    if fresh_questions:
        owner_status = 'action_needed'; owner = 'Требуется решение/уточнение: ' + fresh_questions[0]['reason']
        if len(fresh_questions) > 1: owner += ' Ещё вопросов: ' + str(len(fresh_questions) - 1) + '.'
    elif questions:
        owner_status = 'awaiting_decision'; owner = 'Ожидается ответ по уже рассмотренным вопросам; просмотр не является согласием.'
    elif response:
        answer_label = {'approved':'согласована', 'rejected':'отклонена', 'needs_changes':'требует доработки'}[response['outcome']]
        owner_status = 'responded'; owner = 'Текущая рекомендация ' + answer_label + '. Разрешение действовать и подтверждение данных учитываются отдельно.'
    elif recommended and not selected:
        owner_status = 'decision_needed'; owner = 'Выбор владельца не записан. Рекомендацию можно согласовывать после проверки оснований.'
    else:
        owner_status = 'none'; owner = 'Нового запроса владельцу нет. Прежний выбор сам по себе не подтверждает обновлённую рекомендацию.'

    step, step_refs = next_step(project, audit, follow_up, ledger, questions, responses)
    version = (previous['version_hash'] if previous and old == observations else
               digest({'project_id': project['project_id'], 'parent': previous['version_hash'] if previous else None,
                       'observations': observations}))
    refs = sorted({ref for k in changed for ref in references.get(k, [k])})
    if not previous: refs = ['source:' + s for s in audit['health']['changed_sources']] + ['/checkpoints']
    source_links = []
    for source in project['sources']:
        location = source.get('snapshot_path') or source['url_or_path']
        candidate = (base / location).resolve()
        href = candidate.as_posix() if candidate.is_relative_to(base.resolve()) and candidate.is_file() else None
        if href is None and source['url_or_path'].startswith(('https://', 'http://')): href = source['url_or_path']
        if href: source_links.append({'source_id': source['source_id'], 'path': href})
    context = ('authored_example' if follow_up['context'] == 'authored_example' or
               audit['feasibility'].get('context') == 'authored_example' or
               audit['research_selection'].get('context') == 'authored_example' else 'live_project')
    return {'schema_version': 1, 'version_hash': version,
            'context': context,
            'changes': {'status': status, 'text': compact(text), 'refs': refs},
            'decision': {'text': compact(impact), 'option_ids': decision_ids, 'refs': ['/recommended_option_id', '/chosen_option_id', '/options', '/checkpoints']},
            'owner': {'status': owner_status, 'text': compact(owner), 'questions': questions,
                      'refs': [q['object_ref'] for q in questions]},
            'next_step': {'text': compact(step), 'refs': step_refs},
            'last_view': {k: previous[k] for k in ('reviewed_at', 'reviewer', 'note')} if previous else None,
            'observations': observations,
            'details': {'project': path.as_posix(), 'history': '/checkpoints', 'sources': source_links,
                        'command': ['python', 'scripts/start.py', str(path), '--details'],
                        'json_command': ['python', 'scripts/start.py', str(path), '--json']},
            'note': 'Отметка просмотра относится к показанной версии. Она не подтверждает данные, рекомендацию, разрешение действовать или выполнение обязательства.'}


def next_step(project, audit, follow_up, ledger, questions, responses=()):
    if ledger.get('error') or ledger.get('chain_intact') is False:
        return 'Проверить повреждение журнала; до проверки не доверять истории действий.', ['ledger']
    if ledger.get('unfinished_actions'):
        return 'Проверить последствия незавершённых действий перед повтором: ' + ', '.join(ledger['unfinished_actions']), ['ledger']
    if audit['material_changes']['needs_assessment'] or audit['health']['changed_sources']:
        return 'Разобрать изменения источников и затронутых оснований; затем повторить осуществимость и развилки, если их условия изменились.', ['/sources', '/evidence', '/checkpoints']
    if audit['errors']: return 'Исправить ошибки состояния: ' + audit['errors'][0], ['/']
    answer = next((r for r in reversed(responses) if r['kind'] == 'recommendation' and r['status'] == 'current'), None)
    if answer and answer['outcome'] != 'approved':
        return 'Пересмотреть рекомендацию с учётом явного ответа владельца: ' + answer['statement'], [answer['object_ref']]
    selected = {project.get('recommended_option_id'), project.get('chosen_option_id')} - {None}
    relevant_alerts = [a for a in follow_up['source_alerts'] + follow_up['evidence_alerts']
                       if not selected or selected.intersection(a['impact']['option_ids'])]
    if relevant_alerts or any(r['support_problems'] for r in follow_up['metric_results']):
        return 'Проверить актуальность и происхождение затронутых оснований до выбора и действий.', ['/sources', '/evidence']
    feasibility = audit['feasibility']
    if feasibility['status'] == 'stale' or feasibility['blockers']:
        return 'Осуществимость: обновить отдельную проверку ресурсов и календарных зависимостей.', ['/feasibility_reviews']
    if feasibility['status'] == 'not_recorded' and project.get('recommended_option_id'):
        return 'Осуществимость ещё не проверена: уточнить минимальные работы, ресурсы и зависимости до разработки.', ['/feasibility_reviews', '/options']
    selected = {project.get('recommended_option_id'), project.get('chosen_option_id')}
    rows = [a for a in feasibility['assessments'] if a['option_id'] in selected and a['outcome'] != 'feasible']
    if rows: return 'Осуществимость ' + rows[0]['option_id'] + ' (' + rows[0]['outcome'] + '): ' + rows[0]['next_check'], ['/feasibility_reviews', 'option:' + rows[0]['option_id']]
    if feasibility['decision_blockers']:
        return 'Проверить разрешение и условия осуществимости: ' + feasibility['decision_blockers'][0], ['/feasibility_reviews']
    research = audit['research_selection']
    if research['blockers']: return 'Обновить сравнение исследований и проверяемые условия развилок.', ['/research_selection_reviews']
    priorities = {g['question_id']:g['priority'] for g in research.get('gaps', [])}
    unresolved = [r for r in research.get('branch_resolutions', []) if r['status'] == 'insufficient_data' and priorities.get(r['question_id']) != 'defer']
    if unresolved: return unresolved[0]['next_step'], ['question:' + unresolved[0]['question_id'], '/research_selection_reviews']
    if audit['content_review']['blockers']:
        return 'Завершить содержательную проверку оснований и рекомендации: ' + audit['content_review']['blockers'][0], ['/strategy_review', '/evidence']
    for name in ('decision_stress_test', 'marketing_claims_audit'):
        if audit[name]['blockers'] or audit[name].get('publication_blockers'):
            return 'Обновить проверку решения и ограничений обещаний перед публикацией.', [
                '/decision_stress_tests' if name == 'decision_stress_test' else '/marketing_claims_audits']
    if questions:
        if all(q['seen_in_summary'] for q in questions):
            return 'Дождаться ответа владельца по показанным вопросам; нового согласия не записано.', [q['object_ref'] for q in questions]
        return questions[0]['action'], [questions[0]['object_ref']]
    if answer:
        permission = next((r for r in reversed(responses) if r['kind'] == 'permission' and r['status'] == 'current'
                           and r['subject_ref'] == 'option:' + project.get('recommended_option_id', '')), None)
        if not permission or permission['outcome'] != 'approved':
            return 'Рекомендация согласована; отдельно уточнить разрешение на конкретный объём действий.', ['/checkpoints', '/feasibility_reviews']
    if project.get('recommended_option_id') and not project.get('chosen_option_id') and not answer:
        return 'Показать проверенную рекомендацию и альтернативы владельцу; выбор оставлен человеку.', ['/recommended_option_id', '/options']
    return project['next_action'], ['/next_action']


def markdown(summary):
    labels = (('changes', 'Что изменилось'), ('decision', 'На какое решение влияет'),
              ('owner', 'Что требуется от владельца'), ('next_step', 'Следующий шаг'))
    lines = [str(i) + '. **' + label + ':** ' + summary[key]['text'] for i, (key, label) in enumerate(labels, 1)]
    if summary['context'] == 'authored_example': lines += ['', 'Авторский вымышленный пример; согласования и результаты не являются реальными.']
    lines += ['', '[Источники, состояние и история](<' + summary['details']['project'] + '>)',
              'Подробности: `python scripts/start.py "' + summary['details']['project'] + '" --details`.']
    links = summary['details']['sources'][:3]
    if links: lines += ['Материалы: ' + ', '.join('[' + compact(s['source_id'], 30) + '](<' + s['path'] + '>)' for s in links) + '.']
    return '\n'.join(lines) + '\n'


def acknowledge(path, expected_version, reviewer, note):
    from checkpoint import write_state
    from ledger import append
    from project_tool import load
    from start import restore
    from validate_project import validate
    if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(note, str) or not note.strip():
        raise ValueError('Explicit reviewer and an actual view note are required')
    path = path.resolve(); project = load(path); state = restore(path); summary = state['resume_summary']
    if expected_version != summary['version_hash']: raise ValueError('Summary changed; reload before acknowledging the exact version')
    if state['ledger'].get('error') or state['ledger'].get('chain_intact') is False: raise ValueError('Damaged ledger; do not save a view receipt')
    receipts = [r for r in project.get('follow_up_reviews', []) if r.get('kind') == 'resume']
    if receipts and datetime.fromisoformat(receipts[-1]['reviewed_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc):
        raise ValueError('Future-dated view receipt; inspect the recorded clock before adding another view')
    if receipts and receipts[-1]['version_hash'] == expected_version:
        return {'recorded': False, 'note': 'This summary version was already viewed; no write or new owner request'}
    if load(path) != project or restore(path)['resume_summary']['version_hash'] != expected_version:
        raise ValueError('Project or sources changed; reload before acknowledging')
    candidate = copy.deepcopy(project)
    candidate.setdefault('follow_up_reviews', []).append({'kind': 'resume', 'version_hash': expected_version,
        'observations': summary['observations'], 'reviewed_at': datetime.now(timezone.utc).isoformat(),
        'reviewer': reviewer.strip(), 'note': note.strip()})
    errors = validate(candidate)
    if errors: raise ValueError('; '.join(errors))
    write_state(path, candidate)
    try:
        append(path, {'step': project['stage'], 'action': 'resume summary viewed', 'status': 'done', 'actor': 'script',
                      'tool': 'scripts/start.py', 'note': 'View receipt only; no approval or permission. ' + note})
    except (OSError, ValueError) as error:
        raise ValueError('View receipt saved but ledger append failed; inspect before retrying: ' + str(error)) from error
    return {'recorded': True, 'version_hash': expected_version, 'note': 'Viewed only; decisions and commitments unchanged'}
