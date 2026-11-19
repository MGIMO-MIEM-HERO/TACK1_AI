#!/usr/bin/env python3
"""Derived decision card and explicit versioned human answers in existing checkpoints."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from material_changes import digest, enabled, snapshot

KINDS = ('recommendation', 'permission', 'data')
OUTCOMES = ('approved', 'rejected', 'needs_changes')
ANSWER_KEYS = {'schema_version', 'confirmation_id', 'project_id', 'kind', 'subject_ref', 'subject_version',
               'decision_version', 'outcome', 'statement', 'confirmed_at', 'context'}


def sha(value): return isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{64}', value))


def context(project):
    authored = project.get('follow_up_context') == 'authored_example' or any(
        (project.get(field) or [{}])[-1].get('context') == 'authored_example' for field in ('feasibility_reviews', 'research_selection_reviews'))
    return 'authored_example' if authored else 'live_project'


def validate_answer(answer, *, stored=False):
    from follow_up import instant
    if not isinstance(answer, dict): return ['Human answer must be an object']
    required = ANSWER_KEYS | ({'reference'} if stored else set())
    if not required <= set(answer) or set(answer) - required - {'confirmed_by'}:
        return ['Human answer has missing/unexpected fields; use an explicit scoped answer, not a view receipt']
    errors = []
    if type(answer['schema_version']) is not int or answer['schema_version'] != 1: errors.append('Answer schema_version must be 1')
    if answer['kind'] not in KINDS or answer['outcome'] not in OUTCOMES: errors.append('Invalid answer kind/outcome')
    for key in ('confirmation_id', 'project_id', 'subject_ref', 'statement'):
        if not isinstance(answer[key], str) or not answer[key].strip(): errors.append('Human answer needs ' + key)
    if not sha(answer['decision_version']) or not sha(answer['subject_version']): errors.append('Human answer needs exact decision/subject SHA-256 versions')
    ref = answer.get('subject_ref')
    if isinstance(ref, str):
        if ((answer['kind'] == 'recommendation' and ref != '/recommended_option_id') or
            (answer['kind'] == 'permission' and not ref.startswith('option:')) or
            (answer['kind'] == 'data' and not ref.startswith(('source:', 'evidence:')))):
            errors.append('Human answer kind must match its subject scope')
    if isinstance(answer['statement'], str) and answer['statement'].strip().lower().rstrip('.!') in ('да', 'нет', 'ок', 'okay', 'ok', 'yes', 'no', 'согласен'):
        errors.append('Generic reply is insufficient: preserve an explicit statement about the named scope')
    if 'confirmed_by' in answer and (not isinstance(answer['confirmed_by'], str) or not answer['confirmed_by'].strip()): errors.append('confirmed_by must be text when actually available')
    try: instant(answer['confirmed_at'])
    except (ValueError, TypeError): errors.append('confirmed_at must be offset-aware')
    if answer['context'] not in ('live_project', 'authored_example'): errors.append('Human answer needs live_project/authored_example context')
    if stored:
        ref = answer['reference']
        if not isinstance(ref, dict) or set(ref) != {'file', 'sha256'} or not isinstance(ref.get('file'), str) or not ref['file'].strip() or not sha(ref.get('sha256')):
            errors.append('Stored human answer needs its actual reply file and fingerprint')
    return errors


def validate_fields(project):
    errors, seen = [], set()
    for cp in project.get('checkpoints', []):
        if not isinstance(cp, dict) or 'human_confirmation' not in cp: continue
        answer = cp['human_confirmation']; problems = validate_answer(answer, stored=True); errors.extend(problems)
        if problems: continue
        if answer['confirmation_id'] in seen: errors.append('Duplicate human confirmation_id')
        seen.add(answer['confirmation_id'])
        if answer['project_id'] != project['project_id']: errors.append('Human confirmation belongs to another project')
        cp_snapshot = cp.get('change_snapshot')
        if not isinstance(cp_snapshot, dict) or cp_snapshot.get('decision_version') != answer['decision_version']:
            errors.append('Human confirmation must name its checkpoint decision version')
    ids = {e['evidence_id'] for e in project.get('evidence', []) if isinstance(e, dict) and isinstance(e.get('evidence_id'), str)}
    for option in project.get('options', []):
        assessment = option.get('selection_assessment') if isinstance(option, dict) else None
        if assessment is None: continue
        if not isinstance(assessment, dict): errors.append('Option selection_assessment must be an object'); continue
        if assessment.get('status') not in ('open', 'not_selected', 'rejected'): errors.append('Invalid option selection status')
        if not isinstance(assessment.get('reason'), str) or not assessment['reason'].strip(): errors.append('Option selection needs an explicit reason')
        refs = assessment.get('evidence_ids')
        if not isinstance(refs, list) or any(not isinstance(e, str) for e in refs) or not set(refs) <= ids:
            errors.append('Option selection needs registered evidence_ids')
        if assessment.get('status') == 'rejected' and not refs: errors.append('Rejected alternative needs referenced grounds')
        if isinstance(refs, list) and all(isinstance(e, str) for e in refs) and len(refs) != len(set(refs)):
            errors.append('Option selection evidence_ids must be distinct')
        if assessment.get('status') == 'rejected' and option.get('option_id') == project.get('recommended_option_id'):
            errors.append('Recommended option cannot also be recorded as rejected')
    return errors


def version(project, path, root):
    snap = snapshot(project, path, root)
    return snap['decision_version'] if enabled(project) else digest({'legacy_read_only': snap['input_digest']})


def subject_version(project, kind, ref, decision_version):
    payload = None
    if kind == 'recommendation' and ref == '/recommended_option_id' and project.get('recommended_option_id'):
        payload = {'option_id': project['recommended_option_id'], 'rationale': project.get('recommendation_rationale')}
        reviews = project.get('research_selection_reviews') or []
        if reviews:
            payload['research_conditions'] = {k: reviews[-1].get(k) for k in ('context', 'gaps', 'recommendation', 'stop_rule')}
    elif kind == 'permission' and ref.startswith('option:'):
        oid = ref[7:]; option = next((o for o in project['options'] if o['option_id'] == oid), None)
        reviews = project.get('feasibility_reviews') or []
        plan = next((p for p in reviews[-1]['assessments'] if p['option_id'] == oid), None) if reviews else None
        if option and plan: payload = {'option': option, 'minimum_scope': plan['minimum_scope'], 'work': plan['work'], 'window': plan['window']}
    elif kind == 'data':
        namespace, _, object_id = ref.partition(':')
        rows, key = (project['evidence'], 'evidence_id') if namespace == 'evidence' else (project['sources'], 'source_id')
        if namespace in ('source', 'evidence'): payload = next((r for r in rows if r[key] == object_id), None)
        if namespace == 'source' and payload and enabled(project): payload = {k:v for k,v in payload.items() if k != 'title'}
    if payload is None: raise ValueError('Unknown/insufficient confirmation scope: ' + str(ref))
    return digest({'kind': kind, 'ref': ref, 'decision_version': decision_version, 'subject': payload})


def reply_path(project, path, root, location):
    base = path.parent if project.get('path_base') == 'project' else root
    candidate = (base / location).resolve()
    if not candidate.is_relative_to(base.resolve()) or not candidate.is_file() or candidate.stat().st_size > 1_000_000:
        raise ValueError('Reply must be an existing local JSON file within the project base, at most 1 MB')
    return candidate, base


def reply_json(raw):
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate reply field: ' + key)
            result[key] = value
        return result
    def reject(value): raise ValueError('Nonfinite reply value: ' + value)
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=distinct, parse_constant=reject)


def reference_matches(project, path, root, answer):
    try:
        file, _ = reply_path(project, path, root, answer['reference']['file'])
        raw = file.read_bytes()
        parsed = reply_json(raw)
        return (digest(parsed) == answer['reference']['sha256'] and
                parsed == {k:v for k,v in answer.items() if k != 'reference'})
    except (OSError, ValueError, TypeError, KeyError): return False


def confirmation_states(project, path, root, decision_version, *, at=None):
    from follow_up import instant
    now = instant(at) if at is not None else datetime.now(timezone.utc)
    result = []
    for index, cp in enumerate(project.get('checkpoints', [])):
        if 'human_confirmation' not in cp: continue
        answer = cp['human_confirmation']
        status = 'historical'
        if answer['decision_version'] == decision_version:
            try: exact = answer['subject_version'] == subject_version(project, answer['kind'], answer['subject_ref'], decision_version)
            except ValueError: exact = False
            if exact: status = 'current'
        if instant(answer['confirmed_at']) > now: status = 'future'
        if answer['context'] != context(project): status = 'context_mismatch'
        if not reference_matches(project, path, root, answer): status = 'reference_changed_or_missing'
        saved = cp['change_snapshot']
        ref = answer['subject_ref']; description = ref
        if answer['kind'] == 'recommendation':
            oid = saved['decision'].get('recommended_option_id')
            title = next((o['title'] for o in saved['business'].get('options') or [] if o['option_id'] == oid), str(oid))
            description = title + ': ' + str(saved['decision'].get('recommendation_rationale') or '')
        elif answer['kind'] == 'permission':
            plan = next((p for p in saved['business'].get('resource_plan') or [] if 'option:' + p['option_id'] == ref), None)
            if plan:
                description = plan['minimum_scope'] + '; окно: ' + str(plan['window'].get('start')) + ' — ' + str(plan['window'].get('end'))
        elif ref.startswith('source:'):
            description = saved['sources'].get(ref[7:], {}).get('metadata', {}).get('title', ref)
        elif ref.startswith('evidence:'):
            description = saved['evidence'].get(ref[9:], {}).get('claim', ref)
        result.append({**copy.deepcopy(answer), 'status': status, 'scope_description':description,
                       'object_ref': '/checkpoints/' + str(index) + '/human_confirmation',
                       'identity_verified': False, 'record_type': 'explicit_answer'})
    # The latest explicit answer supersedes earlier answers to the same scope/version.
    latest = {}
    for row in reversed(result):
        key = (row['kind'], row['subject_ref'], row['decision_version'])
        if key in latest:
            if row['status'] == 'current': row['status'] = 'superseded'
        else: latest[key] = row
    return result


def recommendation_answer(project, path, root, decision_version):
    rows = confirmation_states(project, path, root, decision_version)
    return next((r for r in reversed(rows) if r['kind'] == 'recommendation' and r['status'] == 'current'), None)


def pending_errors(project, path, root, answer):
    from follow_up import instant
    errors = validate_answer(answer, stored=True)
    if errors: return errors
    if not enabled(project): errors.append('Explicit versioned answers require material-v1 tracking')
    current = version(project, path, root)
    if answer['project_id'] != project['project_id'] or answer['decision_version'] != current: errors.append('Human answer names a different project/decision version')
    try:
        if answer['subject_version'] != subject_version(project, answer['kind'], answer['subject_ref'], current): errors.append('Human answer names a different subject version')
    except ValueError as error: errors.append(str(error))
    if instant(answer['confirmed_at']) > datetime.now(timezone.utc): errors.append('Cannot record a future human answer')
    if not reference_matches(project, path, root, answer): errors.append('Actual reply file does not match the answer')
    if context(project) != answer['context']: errors.append('Do not mix authored simulation with a real human confirmation')
    return errors


def request(project, path, root, kind, subject):
    current = version(project, path, root)
    return {'schema_version':1, 'project_id':project['project_id'], 'kind':kind, 'subject_ref':subject,
            'decision_version':current, 'subject_version':subject_version(project, kind, subject, current),
            'context':context(project), 'required_reply_fields':['confirmation_id', 'outcome', 'statement', 'confirmed_at'],
            'optional_reply_fields':['confirmed_by'],
            'note':'Запрос точного ответа, не подтверждение. Используйте фактический ответ; общее «да» не относится автоматически к трём разным предметам.'}


def record_answer(project, path, root, answer_file):
    from checkpoint import save_checkpoint
    file, base = reply_path(project, path, root, str(answer_file))
    raw = file.read_bytes(); answer = reply_json(raw)
    errors = validate_answer(answer)
    if errors: raise ValueError('; '.join(errors))
    answer['reference'] = {'file': file.relative_to(base).as_posix(), 'sha256': digest(answer)}
    existing = [cp['human_confirmation'] for cp in project.get('checkpoints', []) if 'human_confirmation' in cp]
    same = next((r for r in existing if r['confirmation_id'] == answer['confirmation_id']), None)
    if same:
        if same == answer: return {'recorded': False, 'note': 'Exact answer already stored; no duplicate write'}
        raise ValueError('confirmation_id already belongs to a different answer')
    errors = pending_errors(project, path, root, answer)
    if errors: raise ValueError('; '.join(errors))
    save_checkpoint(project, path, 'Явный ответ на версию решения: ' + answer['kind'] + ', ' + answer['outcome'], human_confirmation=answer)
    return {'recorded': True, 'confirmation_id': answer['confirmation_id'], 'note': 'Only the stated scope is recorded; no automatic choice, permission, completion or deadline change'}


def build(path, *, state=None):
    from checkpoint import ROOT
    from project_tool import load
    from start import restore
    path = path.resolve(); project = load(path); state = state or restore(path)
    current = version(project, path, ROOT)
    recommended = next((o for o in project['options'] if o['option_id'] == project.get('recommended_option_id')), None)
    options = []
    for option in project['options']:
        selection = option.get('selection_assessment')
        options.append({**copy.deepcopy(option), 'is_recommended': option == recommended,
            'selection_status': 'recommended' if option == recommended else selection['status'] if selection else 'not_recorded',
            'selection_reason': selection['reason'] if selection else 'Основание отклонения не записано; риск или возражение сами по себе не являются отказом.',
            'object_ref': 'option:' + option['option_id']})
    confirmations = confirmation_states(project, path, ROOT, current)
    legacy = []
    if project.get('chosen_option_id'):
        legacy.append({'kind':'recommendation', 'subject_ref':'/chosen_option_id', 'statement':'Записанный выбор: ' + project['chosen_option_id'],
                       'status':'version_not_recorded', 'confirmed_by':None, 'confirmed_at':None, 'decision_version':None})
    for c in project.get('commitments', []):
        if c.get('agreement_reference'): legacy.append({'kind':'commitment', 'statement':c['agreement_reference'], 'status':'scope_only_no_decision_version'})
    for row in state['follow_up']['metric_results']:
        if row.get('human_decision'): legacy.append({'kind':'metric_result', 'subject_ref':row['object_ref'], **row['human_decision'],
            'status':'current_result_only' if row['human_decision_current'] else 'historical_result', 'decision_version':None})
    for plan in (project.get('feasibility_reviews') or [{}])[-1].get('assessments', []):
        legacy.append({'kind':'permission', 'subject_ref':'option:' + plan['option_id'], 'statement':plan['permission']['basis'],
                       'recorded_status':plan['permission']['status'], 'status':'recorded_plan_statement_not_versioned_answer'})
    unknowns = [{'text':q, 'ref':'/unresolved_questions'} for q in project.get('unresolved_questions', [])]
    for row in state['feasibility']['assessments']:
        unknowns.extend({'text':t, 'ref':'option:' + row['option_id']} for t in row['unknowns'])
    for row in state['research_selection'].get('branch_resolutions', []):
        if row['status'] == 'insufficient_data': unknowns.append({'text':row['next_step'], 'ref':'question:' + row['question_id']})
    for e in project['evidence']:
        if e['claim_type'] in ('hypothesis', 'forecast') or e['status'] in ('stale', 'withdrawn', 'contradicted'):
            unknowns.append({'text':e['claim'] + ' [' + e['claim_type'] + ', ' + e['status'] + ']: ' + e['limitations'], 'ref':'evidence:' + e['evidence_id']})
    if state['feasibility']['status'] in ('not_recorded', 'stale'):
        unknowns.append({'text':'Осуществимость: ' + state['feasibility']['status'], 'ref':'/feasibility_reviews'})
    limits = []
    if project.get('strategy_review', {}).get('evidence_limits'): limits.append(project['strategy_review']['evidence_limits'])
    if state['feasibility'].get('limitations'): limits.append(state['feasibility']['limitations'])
    for review in (project.get('research_selection_reviews') or [])[-1:]: limits.append(review['stop_rule']['remaining_limits'])
    triggers = []
    if project.get('strategy_review', {}).get('reversal_condition'): triggers.append({'text':project['strategy_review']['reversal_condition'], 'ref':'/strategy_review/reversal_condition'})
    for i,c in enumerate(project.get('commitments', [])):
        triggers.append({'text':c['review_trigger'], 'ref':'/commitments/' + str(i) + '/review_trigger'})
    if project.get('validation_plan', {}).get('decision_rule'): triggers.append({'text':project['validation_plan']['decision_rule'], 'ref':'/validation_plan/decision_rule'})
    for s in project['sources']:
        if s.get('valid_until'): triggers.append({'text':'Проверить актуальность ' + s['source_id'] + ' после ' + s['valid_until'], 'ref':'source:' + s['source_id']})
    for review in (project.get('research_selection_reviews') or [])[-1:]:
        triggers.append({'text':review['stop_rule']['condition'], 'ref':'/research_selection_reviews'})
    requests = []
    if recommended: requests.append(request(project, path, ROOT, 'recommendation', '/recommended_option_id'))
    blockers = state['audit']['errors'] + state['content_review']['blockers'] + state['feasibility']['blockers'] + state['feasibility']['decision_blockers']
    for key in ('research_selection', 'decision_stress_test', 'marketing_claims_audit'):
        blockers += state[key]['blockers'] + state[key].get('publication_blockers', [])
    return {'schema_version':1, 'project_id':project['project_id'], 'title':project['title'], 'version':current,
            'version_mode':'material-v1' if enabled(project) else 'legacy_read_only',
            'resume_summary':state['resume_summary'], 'recommendation':{'option_id':project.get('recommended_option_id'),
                'title':recommended['title'] if recommended else None, 'rationale':project.get('recommendation_rationale'),
                'version':subject_version(project, 'recommendation', '/recommended_option_id', current) if recommended else None,
                'evidence_ids':recommended['evidence_ids'] if recommended else []},
            'alternatives':options, 'sources':copy.deepcopy(project['sources']), 'evidence':copy.deepcopy(project['evidence']),
            'source_links':state['resume_summary']['details']['sources'], 'unknowns':unknowns, 'inference_limits':limits,
            'feasibility':state['feasibility'], 'research':state['research_selection'],
            'revisit_conditions':triggers, 'changes':state['material_changes'],
            'confirmations':confirmations, 'confirmation_requests':requests, 'legacy_records':legacy,
            'read_receipts':copy.deepcopy(project.get('follow_up_reviews', [])),
            'history':[{'at':cp['at'], 'summary':cp['summary'], 'version':cp.get('change_snapshot', {}).get('decision_version'),
                        'change_review':cp.get('change_review'), 'confirmation_id':cp.get('human_confirmation', {}).get('confirmation_id')}
                       for cp in project.get('checkpoints', [])],
            'blockers':sorted(set(blockers)),
            'note':'Карточка строится из текущего состояния; просмотр не является согласием. Идентичность автора ответа скриптом не удостоверяется. Старый выбор и разрешение на действие не означают согласование новой рекомендации.'}


def markdown(card):
    from resume_summary import markdown as summary_markdown
    statuses = {'current':'для текущей версии', 'historical':'исторический ответ', 'superseded':'заменён позднейшим ответом',
                'future':'дата ответа в будущем', 'context_mismatch':'контекст ответа не совпадает',
                'reference_changed_or_missing':'исходный ответ изменён или недоступен', 'not_recorded':'причина отклонения не записана',
                'not_selected':'не выбрана', 'rejected':'отклонена', 'open':'ещё рассматривается',
                'version_not_recorded':'версия согласования не записана', 'scope_only_no_decision_version':'согласование отдельного обязательства без версии рекомендации',
                'current_result_only':'ответ только по текущей версии показателя', 'historical_result':'ответ по прежней версии показателя',
                'recorded_plan_statement_not_versioned_answer':'запись в ресурсном плане, не ответ на текущую версию рекомендации'}
    outcomes = {'approved':'подтверждено', 'rejected':'отклонено', 'needs_changes':'нужны изменения'}
    feasibility_labels = {'not_recorded':'не проверена', 'stale':'требует обновления', 'review_record_complete':'проверка записана',
                          'feasible':'осуществимо для записанного плана', 'infeasible':'дефицит для записанного плана', 'unknown':'данных недостаточно'}
    lines = [summary_markdown(card['resume_summary']).rstrip(), '', '# Паспорт решения: ' + card['title'],
             '', 'Версия: `' + card['version'] + '` (' + card['version_mode'] + ')',
             'Рекомендация: ' + str(card['recommendation']['title'] or 'не сформирована'),
             'Версия предмета согласования: `' + str(card['recommendation']['version'] or 'нет рекомендации') + '`',
             'Почему: ' + str(card['recommendation']['rationale'] or 'обоснование не записано'), '', '## Альтернативы']
    for option in card['alternatives']:
        if option['is_recommended']: continue
        lines += ['- ' + option['option_id'] + ' — ' + option['title'] + ' [' + statuses.get(option['selection_status'],option['selection_status']) + ']: ' + option['selection_reason'],
                  '  Риски: ' + '; '.join(option['costs_and_risks']) + '; возражение: ' + option['objection'],
                  '  Основания: ' + ', '.join(option['evidence_ids'])]
    lines += ['', '## Основания и источники']
    for e in card['evidence']:
        lines += ['- ' + e['evidence_id'] + ' [' + e['claim_type'] + ', ' + e['status'] + ']: ' + e['claim'],
                  '  Источники: ' + ', '.join(e['source_ids']) + '; зависимости: ' + ', '.join(e.get('related_evidence_ids', [])) + '; ограничения: ' + e['limitations']]
        for support in e.get('support', []): lines += ['  ' + support['source_id'] + ', ' + support['locator'] + ': ' + support['passage']]
    lines += ['- [' + s['source_id'] + '](<' + s['path'] + '>)' for s in card['source_links']]
    for s in card['sources']:
        lines += ['- ' + s['source_id'] + ': ' + s['title'] + '; проверка: ' + s.get('verification', 'не записана') +
                  '; дата: ' + s['accessed_at'] + '; актуален до: ' + str(s.get('valid_until', 'не указано')) +
                  ('; синтетический материал' if s.get('synthetic') or s.get('evidence_scope') == 'simulation' else '')]
    lines += ['', '## Неизвестное и осуществимость', 'Осуществимость: ' + feasibility_labels.get(card['feasibility']['status'],card['feasibility']['status'])]
    lines += ['- ' + a['option_id'] + ': ' + feasibility_labels[a['outcome']] + '; ' + a['next_check'] for a in card['feasibility']['assessments']]
    lines += ['- ' + item['text'] + ' (' + item['ref'] + ')' for item in card['unknowns']]
    lines += ['Граница вывода: ' + item for item in card['inference_limits']]
    lines += ['', '## Когда пересматривать'] + ['- ' + item['text'] for item in card['revisit_conditions']]
    for event in card['changes']['events']: lines += ['- ' + event['kind'] + ': ' + event['object_ref'] + '; затронуты основания ' + ', '.join(event['impact']['evidence_ids']) + ' и варианты ' + ', '.join(event['impact']['option_ids'])]
    lines += ['', '## Что именно подтвердил человек']
    for kind,label in (('permission','Разрешение действовать'), ('data','Подтверждение исходных данных'), ('recommendation','Согласование рекомендации')):
        rows = [r for r in card['confirmations'] if r['kind'] == kind]
        lines += ['### ' + label]
        if not rows: lines += ['Явный ответ для версии не записан.']
        for row in rows:
            lines += ['- ' + statuses[row['status']] + ': ' + outcomes[row['outcome']] + '; ' + row['subject_ref'] + '; ' + row['statement'],
                      '  Предмет ответа: ' + row['scope_description'],
                      '  Кто: ' + str(row.get('confirmed_by') or 'не указан') + '; когда: ' + row['confirmed_at'] + '; версия: `' + row['decision_version'] + '`',
                      '  Основание ответа: ' + row['reference']['file'] + '; запись: ' + row['object_ref']]
    if card['legacy_records']: lines += ['', 'Ранее записанные выборы/согласования с иной или неуказанной версией:'] + ['- ' + r['kind'] + ': ' + statuses[r['status']] + '; ' + str(r.get('statement') or r.get('reference', '')) for r in card['legacy_records']]
    lines += ['', '## История пересмотра']
    for cp in card['history']:
        lines += ['- ' + cp['at'] + ': ' + cp['summary']]
        review = cp['change_review'] or {}; assessment = review.get('assessment')
        if assessment: lines += ['  Вывод: ' + assessment['conclusion'] + '; ' + assessment['rationale']]
    if card['blockers']: lines += ['', '## Требует проверки'] + ['- ' + b for b in card['blockers']]
    return '\n'.join(lines + ['', card['note']]) + '\n'


def main():
    from checkpoint import ROOT
    from project_tool import load
    from output_guard import check_output
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path); parser.add_argument('--json', action='store_true')
    parser.add_argument('--answer', type=Path, help='Record an actual explicit scoped reply JSON, never generate approval')
    parser.add_argument('--request', choices=KINDS, help='Prepare exact scope/version for a human question, never approve')
    parser.add_argument('--subject', help='Stable scope: /recommended_option_id, option:O1, source:S1 or evidence:E1')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        path = args.project.resolve(); project = load(path)
        if args.answer:
            if args.out or args.json or args.request or args.subject: raise ValueError('Recording an answer rejects report/request flags')
            result = record_answer(project, path, ROOT, args.answer)
            print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
        if args.request:
            if not args.subject: raise ValueError('Request needs --subject')
            output = json.dumps(request(project, path, ROOT, args.request, args.subject), ensure_ascii=False, indent=2)
        else:
            if args.subject: raise ValueError('--subject requires --request')
            card = build(path); output = json.dumps(card, ensure_ascii=False, indent=2) if args.json else markdown(card)
        if args.out:
            check_output(project, path, args.out)
            if args.out.exists(): raise ValueError('Use a new report filename')
            args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(output, encoding='utf-8')
        else: print(output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error: parser.exit(1, 'Decision passport: ' + str(error) + '\n')


if __name__ == '__main__': raise SystemExit(main())
