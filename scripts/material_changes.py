#!/usr/bin/env python3
"""Assess source/decision changes in existing checkpoints; never approve a decision."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

MODE = {'schema_version': 1, 'hash_mode': 'material-v1'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def enabled(project):
    mode = project.get('change_tracking')
    return isinstance(mode, dict) and type(mode.get('schema_version')) is int and mode == MODE


def meaningful_payload(project):
    """Narrow presentation whitelist; reliability, scope, dates and methods remain."""
    payload = {k: copy.deepcopy(v) for k, v in project.items() if k not in
               ('checkpoints', 'updated_at', 'strategy_review', 'follow_up_reviews', 'change_tracking')}
    if enabled(project):
        payload.pop('title', None)
        for source in payload.get('sources', []): source.pop('title', None)
    return payload


def source_version(project, source, base):
    from checkpoint import fingerprint
    location = source.get('snapshot_path') or source['url_or_path']
    old = fingerprint(location, base)
    if not enabled(project): return old
    if len(old) != 64: return old
    candidate = (base / location).resolve()
    if candidate.suffix.lower() != '.json' or candidate.stat().st_size > 5_000_000:
        return old
    class Number(str): pass
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate JSON key; do not infer cosmetic equivalence')
            result[key] = value
        return result
    def reject(value): raise ValueError('Nonfinite JSON constant: ' + value)
    def canonical(value):
        if isinstance(value, Number): return ['number', str(value)]
        if isinstance(value, dict): return ['object', [[k, canonical(v)] for k, v in sorted(value.items())]]
        if isinstance(value, list): return ['array', [canonical(v) for v in value]]
        if value is None: return ['null']
        if isinstance(value, bool): return ['boolean', value]
        return ['string', value]
    try:
        data = json.loads(candidate.read_text(encoding='utf-8-sig'), object_pairs_hook=distinct,
                          parse_constant=reject, parse_int=Number, parse_float=Number)
        # Preserve numeric spelling/precision: ignore layout/key order only.
        return digest({'canonical_json_v1': canonical(data)})
    except (ValueError, UnicodeError, OSError):
        return raw_digest(candidate)  # Ambiguous/invalid JSON is not normalised.


def raw_digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''): h.update(chunk)
    return h.hexdigest()


def source_versions(project, base):
    result = {}
    for source in project['sources']:
        row = {'location': source['url_or_path'], 'fingerprint': source_version(project, source, base)}
        if enabled(project):
            row['metadata_fingerprint'] = digest({k: v for k, v in source.items() if k != 'title'})
        result[source['source_id']] = row
    return result


def snapshot(project, path, root):
    base = path.parent if project.get('path_base') == 'project' else root
    versions = source_versions(project, base)
    sources = {}
    for source in project['sources']:
        location = source.get('snapshot_path') or source['url_or_path']
        candidate = (base / location).resolve()
        raw = (raw_digest(candidate)
               if candidate.is_relative_to(base.resolve()) and candidate.is_file() else 'unavailable')
        sources[source['source_id']] = {'metadata': copy.deepcopy(source), 'raw_digest': raw,
                                        'semantic_digest': versions[source['source_id']]['fingerprint']}
    decision = {k: copy.deepcopy(project.get(k)) for k in
                ('objective', 'constraints', 'recommended_option_id', 'recommendation_rationale',
                 'product_strategy', 'communication_strategy', 'validation_plan', 'validation_design')}
    business = {k: copy.deepcopy(project.get(k)) for k in
                ('options', 'research_questions', 'commitments', 'metric_results', 'chosen_option_id')}
    if project.get('feasibility_reviews'):
        business['resource_plan'] = copy.deepcopy(project['feasibility_reviews'][-1]['assessments'])
    evidence = {e['evidence_id']: copy.deepcopy(e) for e in project['evidence']}
    version_business = copy.deepcopy(business)
    version_business.pop('chosen_option_id', None)  # A response does not redefine the proposal it answers.
    for metric in version_business.get('metric_results') or []: metric.pop('human_decision', None)
    grounds = {'sources': versions, 'evidence': evidence, 'business': version_business}
    content = digest({'project_id': project['project_id'], 'decision': decision, 'grounds': grounds})
    previous = previous_snapshot(project)
    version = (previous['decision_version'] if previous and previous.get('input_digest') == content
               else digest({'parent': previous['decision_version'] if previous else None, 'input': content}))
    from follow_up import result_content_hash, result_version
    metrics = {r['result_id']: {'content_hash': result_content_hash(project, path, root, r),
                              'version': result_version(project, path, root, r)} for r in project.get('metric_results', [])}
    return {'schema_version': 1, 'project_id': project['project_id'], 'project_title': project['title'], 'sources': sources,
            'evidence': evidence, 'decision': decision, 'business': business,
            'input_digest': content, 'decision_version': version, 'result_versions': metrics,
            'recommendation_hash': digest(decision)}


def previous_snapshot(project):
    for checkpoint in reversed(project.get('checkpoints', [])):
        if 'change_snapshot' in checkpoint: return checkpoint['change_snapshot']
    return None


def result_lineage(project, result_id, content_hash):
    previous = previous_snapshot(project)
    old = previous.get('result_versions', {}).get(result_id) if previous else None
    if old and old['content_hash'] == content_hash: return old['version']
    return digest({'project_id': project['project_id'], 'parent': old['version'] if old else None, 'result': result_id, 'content': content_hash})


def validate_fields(project):
    errors = []
    if 'change_tracking' in project and not enabled(project): errors.append('Unknown change_tracking mode; expected material-v1')
    def sha(value): return isinstance(value, str) and bool(re.fullmatch('[0-9a-f]{64}', value))
    previous = None
    for cp in project.get('checkpoints', []):
        error_count = len(errors)
        if not isinstance(cp, dict): continue
        snap = cp.get('change_snapshot')
        if snap is None:
            if 'change_review' in cp: errors.append('Change review needs its checkpoint snapshot')
            continue
        if not enabled(project): errors.append('Tracked checkpoint history cannot silently revert to legacy hashes')
        if not isinstance(snap, dict) or type(snap.get('schema_version')) is not int or snap['schema_version'] != 1:
            errors.append('Invalid change snapshot schema_version'); continue
        if snap.get('project_id') != project.get('project_id'): errors.append('Change snapshot belongs to another project')
        if any(not isinstance(snap.get(k), dict) for k in ('sources', 'evidence', 'decision', 'business', 'result_versions')) or not isinstance(snap.get('project_title'), str):
            errors.append('Change snapshot needs sources/evidence/decision/business/result_versions and title'); continue
        if any(not sha(snap.get(k)) for k in ('input_digest', 'decision_version', 'recommendation_hash')):
            errors.append('Change snapshot needs SHA-256 versions'); continue
        valid_sources = True; versions = {}
        for sid, source in snap['sources'].items():
            if (not isinstance(sid, str) or not isinstance(source, dict) or not isinstance(source.get('metadata'), dict)
                    or not isinstance(source.get('raw_digest'), str) or not isinstance(source.get('semantic_digest'), str)
                    or not isinstance(source['metadata'].get('url_or_path'), str)):
                errors.append('Invalid historical source snapshot'); valid_sources = False; continue
            versions[sid] = {'location': source['metadata']['url_or_path'], 'fingerprint': source['semantic_digest'],
                             'metadata_fingerprint': digest({k:v for k,v in source['metadata'].items() if k != 'title'})}
        if valid_sources:
            business = copy.deepcopy(snap['business']); business.pop('chosen_option_id', None)
            metrics = business.get('metric_results') or []
            if not isinstance(metrics, list) or any(not isinstance(r, dict) for r in metrics):
                errors.append('Invalid historical metric results'); continue
            for metric in metrics: metric.pop('human_decision', None)
            content = digest({'project_id': project['project_id'], 'decision': snap['decision'],
                              'grounds': {'sources': versions, 'evidence': snap['evidence'], 'business': business}})
            if content != snap['input_digest'] or digest(snap['decision']) != snap['recommendation_hash']:
                errors.append('Historical change snapshot content/hash mismatch')
            version = (previous['decision_version'] if previous and previous['input_digest'] == content
                       else digest({'parent': previous['decision_version'] if previous else None, 'input': content}))
            if version != snap['decision_version']: errors.append('Historical decision version lineage mismatch')
        for rid, result in snap['result_versions'].items():
            if not isinstance(result, dict) or not sha(result.get('content_hash')) or not sha(result.get('version')):
                errors.append('Historical result versions need content/version hashes'); continue
            old = previous.get('result_versions', {}).get(rid) if previous else None
            version = old['version'] if old and old['content_hash'] == result['content_hash'] else digest({
                'project_id': project['project_id'], 'parent': old['version'] if old else None, 'result': rid, 'content': result['content_hash']})
            if version != result['version']: errors.append('Historical result version lineage mismatch')
        review = cp.get('change_review')
        if not isinstance(review, dict) or review.get('kind') not in ('initialisation', 'assessment', 'cosmetic_or_progress'):
            errors.append('Tracked checkpoint needs a valid change_review'); continue
        if review.get('after_version') != snap['decision_version']: errors.append('Change review version does not match its snapshot')
        events = review.get('events')
        if not isinstance(events, list): errors.append('Change review needs events'); events = []
        seen = set()
        for event in events:
            if not isinstance(event, dict) or not sha(event.get('event_id')):
                errors.append('Change event needs an ID'); continue
            if event['event_id'] in seen: errors.append('Duplicate event in checkpoint')
            seen.add(event['event_id'])
            if digest({k:v for k,v in event.items() if k != 'event_id'}) != event['event_id']:
                errors.append('Change event content/hash mismatch')
            if event.get('classification') not in ('cosmetic', 'material', 'uncertain'):
                errors.append('Invalid historical change classification')
        q = review.get('owner_question')
        if q is not None and (not isinstance(q, dict) or q.get('question_id') != 'change:' + snap['decision_version']
                              or any(not isinstance(q.get(k), str) or not q[k].strip() for k in ('object_ref', 'reason', 'action'))):
            errors.append('Owner request needs the exact decision version and action')
        if len(errors) == error_count: previous = snap
    return errors


def compare(project, before, after):
    from stress_test import dependency_impact
    events = []
    # A removed dependency is still part of the historical grounds being assessed.
    impact_project = dict(project)
    def union_rows(old, new, id_key, refs):
        rows = {r[id_key]: copy.deepcopy(r) for r in old}
        for row in new:
            prior = rows.get(row[id_key], {})
            merged = copy.deepcopy(row)
            for ref in refs: merged[ref] = sorted(set(prior.get(ref, [])) | set(row.get(ref, [])))
            rows[row[id_key]] = merged
        return list(rows.values())
    impact_project['evidence'] = union_rows(list(before['evidence'].values()), list(after['evidence'].values()),
                                            'evidence_id', ('source_ids', 'related_evidence_ids'))
    impact_project['options'] = union_rows(before['business'].get('options') or [], after['business'].get('options') or [],
                                          'option_id', ('evidence_ids',))
    def add(kind, ref, old, new, classification, source_ids=(), evidence_ids=(), option_ids=()):
        impact = dependency_impact(impact_project, source_ids, evidence_ids)
        impact['option_ids'] = sorted(set(impact['option_ids']) | set(option_ids))
        item = {'kind': kind, 'object_ref': ref, 'before': old, 'after': new,
                'classification': classification, 'impact': impact,
                'selected_option_affected': bool(set(impact['option_ids']) &
                    {project.get('recommended_option_id'), project.get('chosen_option_id')})}
        item['event_id'] = digest(item)
        events.append(item)
    for sid in sorted(set(before['sources']) | set(after['sources'])):
        old, new = before['sources'].get(sid), after['sources'].get(sid)
        if old is None or new is None:
            add('source_registry', 'source:' + sid, old, new, 'uncertain', [sid]); continue
        if old['raw_digest'] != new['raw_digest']:
            same = old['semantic_digest'] == new['semantic_digest'] and len(new['semantic_digest']) == 64
            add('formatting' if same else 'source_data', 'source:' + sid,
                {k: old[k] for k in ('raw_digest', 'semantic_digest')},
                {k: new[k] for k in ('raw_digest', 'semantic_digest')}, 'cosmetic' if same else 'uncertain', [sid])
        changed = {k for k in set(old['metadata']) | set(new['metadata']) if old['metadata'].get(k) != new['metadata'].get(k)}
        if changed:
            add('source_metadata', 'source:' + sid,
                {k: old['metadata'].get(k) for k in sorted(changed)},
                {k: new['metadata'].get(k) for k in sorted(changed)},
                'cosmetic' if changed <= {'title'} else 'uncertain', [sid])
    for eid in sorted(set(before['evidence']) | set(after['evidence'])):
        old, new = before['evidence'].get(eid), after['evidence'].get(eid)
        if old != new: add('evidence', 'evidence:' + eid, old, new, 'uncertain', evidence_ids=[eid])
    if before['project_title'] != after['project_title']:
        add('presentation', '/title', before['project_title'], after['project_title'], 'cosmetic')
    if before['decision'] != after['decision']:
        add('recommendation', '/decision', before['decision'], after['decision'], 'material',
            option_ids=[oid for oid in (project.get('recommended_option_id'), project.get('chosen_option_id')) if oid])
    if before['business'] != after['business']:
        affected = []
        if any(before['business'].get(k) != after['business'].get(k) for k in ('options', 'resource_plan', 'commitments', 'research_questions')):
            affected = [oid for oid in (project.get('recommended_option_id'), project.get('chosen_option_id')) if oid]
        add('decision_context', '/business', before['business'], after['business'], 'uncertain', option_ids=affected)
    return events


def inspect(project, path, root):
    empty = {'enabled': enabled(project), 'status': 'not_enabled', 'events': [], 'human_questions': [],
             'needs_assessment': False, 'history': []}
    if not enabled(project): return {**empty, 'note': 'Legacy hashes preserved. Enable explicitly; old approvals are not migrated.'}
    current = snapshot(project, path, root); previous = previous_snapshot(project)
    history = [cp['change_review'] for cp in project.get('checkpoints', []) if 'change_review' in cp]
    events = compare(project, previous, current) if previous else []
    key = digest({'checkpoint_index': len(project.get('checkpoints', [])), 'before': digest(previous), 'after': digest(current)}) if previous else None
    questions = []
    # A cosmetic save retains the same pending owner request, never a new approval.
    latest = history[-1] if history else None
    if latest and latest.get('owner_question') and latest.get('after_version') == current['decision_version']:
        questions.append(copy.deepcopy(latest['owner_question']))
    changed_choice = previous and previous['decision'].get('recommended_option_id') != current['decision'].get('recommended_option_id')
    if changed_choice:
        questions = [{'question_id': 'change:' + current['decision_version'], 'object_ref': '/recommended_option_id',
                      'reason': 'Рекомендация изменилась; прежний выбор не является согласием с новой версией.',
                      'action': 'Показать новые основания и получить решение владельца для этой версии.'}]
    return {**empty, 'status': 'pending' if events else 'current', 'events': events, 'event_set_hash': key,
            'before_version': previous.get('decision_version') if previous else None,
            'after_version': current['decision_version'], 'snapshot': current,
            'needs_assessment': any(e['classification'] != 'cosmetic' for e in events),
            'human_questions': questions, 'history': history,
            'human_choice': project.get('chosen_option_id'),
            'approval_for_current_version': 'not_inferred',
            'note': 'Read-only detection. Persist observed events through checkpoint save/record; assessment is not human approval.'}


def prepare(project, path, root):
    result = inspect(project, path, root)
    if not result['enabled']: raise ValueError('First enable change tracking explicitly')
    if not result['events']: raise ValueError('No new events to assess')
    return {'schema_version': 1, 'event_set_hash': result['event_set_hash'], 'reviewer': '',
            'effects': [{'event_id': e['event_id'], 'materiality': e['classification'],
                        'decision_effect': 'unchanged' if e['classification'] == 'cosmetic' else 'unknown',
                        'evidence_ids': [], 'analysis': ''} for e in result['events']],
            'conclusion': 'unknown' if result['needs_assessment'] else 'unchanged', 'rationale': ''}


def validate_review(project, result, review):
    errors = []
    if not isinstance(review, dict): return ['Change assessment must be an object']
    if type(review.get('schema_version')) is not int or review['schema_version'] != 1: errors.append('Change assessment schema_version must be 1')
    if review.get('event_set_hash') != result['event_set_hash']: errors.append('Change assessment is stale; reload the exact pending events')
    for key in ('reviewer', 'rationale'):
        if not isinstance(review.get(key), str) or not review[key].strip(): errors.append('Change assessment needs ' + key)
    if review.get('conclusion') not in ('changed', 'unchanged', 'unknown'): errors.append('Conclusion must be changed/unchanged/unknown')
    effects = review.get('effects'); events = {e['event_id']: e for e in result['events']}
    if not isinstance(effects, list): return errors + ['Change assessment needs effects for every event']
    seen = set(); allowed = {e['evidence_id'] for e in project['evidence']}
    for effect in effects:
        if not isinstance(effect, dict): errors.append('Change effect must be an object'); continue
        eid = effect.get('event_id')
        if not isinstance(eid, str) or eid not in events or eid in seen: errors.append('Effect must name a distinct pending event')
        if isinstance(eid, str): seen.add(eid)
        if effect.get('materiality') not in ('cosmetic', 'material', 'uncertain'): errors.append('Invalid change materiality')
        if effect.get('decision_effect') not in ('changed', 'unchanged', 'unknown'): errors.append('Invalid decision effect')
        if not isinstance(effect.get('analysis'), str) or not effect['analysis'].strip(): errors.append('Each effect needs an explanation of influence')
        refs = effect.get('evidence_ids')
        if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs) or len(refs) != len(set(refs)) or not set(refs) <= allowed:
            errors.append('Effect evidence_ids must be registered distinct IDs')
        # Explicit human/agent review may find an irrelevant content edit. Require a factual basis,
        # not merely a hash reset. Uncertain impact stays uncertain, not silently cosmetic.
        if isinstance(eid, str) and eid in events and events[eid]['classification'] != 'cosmetic' and effect.get('decision_effect') == 'unchanged' and not refs:
            errors.append('Unchanged conclusion after a noncosmetic event needs evidence and analysis')
        if effect.get('materiality') == 'uncertain' and effect.get('decision_effect') != 'unknown':
            errors.append('Uncertain materiality must preserve unknown decision effect')
    if seen != set(events): errors.append('Assess every pending event exactly once')
    if review.get('conclusion') == 'unchanged' and any(e.get('decision_effect') != 'unchanged' for e in effects if isinstance(e, dict)):
        errors.append('Cannot claim unchanged conclusion with unresolved/changed effects')
    before = previous_snapshot(project)
    if before and before['decision'].get('recommended_option_id') != result['snapshot']['decision'].get('recommended_option_id') and review.get('conclusion') != 'changed':
        errors.append('A different recommended option is a changed recommendation')
    return errors


def checkpoint_fields(project, path, root, review=None, *, initial=False):
    result = inspect(project, path, root)
    if initial:
        return {'change_snapshot': result['snapshot'], 'change_review': {'kind': 'initialisation',
                'events': [], 'owner_question': None, 'after_version': result['after_version'],
                'note': 'New hash mode; old reviews/confirmations remain historical, not migrated approvals.'}}
    if review is None and result['needs_assessment']:
        raise ValueError('Tracked noncosmetic changes need material_changes prepare/record; --reviewed-changes alone is not an impact assessment')
    if review is not None:
        errors = validate_review(project, result, review)
        if errors: raise ValueError('; '.join(errors))
        from quality import FACTS, support_blockers
        refs = {r for effect in review['effects'] for r in effect['evidence_ids']}
        blockers = support_blockers(project, path, root, refs, 'Change assessment support')
        by_id = {e['evidence_id']: e for e in project['evidence']}
        for effect in review['effects']:
            if effect['evidence_ids'] and not any(by_id[r]['claim_type'] in FACTS for r in effect['evidence_ids']):
                blockers.append('Change assessment cannot use only a model hypothesis as factual confirmation')
        if blockers: raise ValueError('; '.join(blockers))
    conclusion = review['conclusion'] if review else 'unchanged'
    uncertain_selected = any(e['selected_option_affected'] for e in result['events']) and conclusion == 'unknown'
    need_owner = conclusion == 'changed' or uncertain_selected
    previous_question = (result['human_questions'][0] if result['human_questions'] else
                         result['history'][-1].get('owner_question') if result['history'] else None)
    if need_owner:
        question = {'question_id': 'change:' + result['after_version'], 'object_ref': '/recommended_option_id',
                    'reason': 'Вывод изменился.' if conclusion == 'changed' else 'Влияние изменения на выбранные основания остаётся неопределённым.',
                    'action': 'Показать разбор и получить решение владельца для этой версии; прежнее согласие не переносить.'}
    else:
        question = copy.deepcopy(previous_question)
        if question: question['question_id'] = 'change:' + result['after_version']
    return {'change_snapshot': result['snapshot'], 'change_review': {
        'kind': 'assessment' if review else 'cosmetic_or_progress', 'event_set_hash': result['event_set_hash'],
        'before_version': result['before_version'], 'after_version': result['after_version'],
        'events': result['events'], 'assessment': copy.deepcopy(review), 'owner_question': question,
        'note': 'Agent assessment/checkpoint only; never approval, human choice or completion.'}}


def enable(project, path, root):
    if enabled(project): return {'enabled': True, 'recorded': False}
    from checkpoint import save_checkpoint
    from project_tool import source_health
    if source_health(project, path)['changed_sources']:
        raise ValueError('Review pending legacy source changes before enabling; do not hide them in a new baseline')
    candidate = copy.deepcopy(project); candidate['change_tracking'] = dict(MODE)
    save_checkpoint(candidate, path, 'Включено отслеживание существенности; старые подтверждения не перенесены',
                    initial_tracking=True, expected=project)
    return {'enabled': True, 'recorded': True, 'note': 'Refresh substantive reviews explicitly; no approval was created.'}


def markdown(result):
    lines = ['## Существенность изменений', '', 'Статус: ' + result['status'], result['note']]
    if result.get('history'):
        assessment = result['history'][-1].get('assessment')
        if assessment:
            lines += ['Вывод: ' + assessment['conclusion'] + '. ' + assessment['rationale']]
    for event in result['events']:
        lines += ['- ' + event['event_id'] + ': ' + event['kind'] + ' [' + event['classification'] + '] ' + event['object_ref'],
                  '  Основания: ' + ', '.join(event['impact']['evidence_ids']) + '; варианты: ' + ', '.join(event['impact']['option_ids'])]
    for q in result['human_questions']: lines += ['Человеку: ' + q['reason'] + ' ' + q['action'] + ' ID: ' + q['question_id']]
    if result.get('enabled'): lines += ['Версия оснований/решения: ' + result['after_version'],
                                       'Выбор в файле: ' + str(result['human_choice']) + '; подтверждение текущей версии не выводится из просмотра.']
    return '\n'.join(lines) + '\n'


def main():
    from checkpoint import ROOT, save_checkpoint
    from project_tool import load
    from output_guard import check_output
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('enable', 'inspect', 'report', 'prepare', 'record'))
    parser.add_argument('project', type=Path); parser.add_argument('--review', type=Path); parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        path = args.project.resolve(); project = load(path)
        if args.command in ('enable', 'record') and args.out: raise ValueError('Mutations reject --out')
        if args.command == 'enable': result = enable(project, path, ROOT)
        elif args.command == 'prepare': result = prepare(project, path, ROOT)
        elif args.command == 'record':
            if not args.review: raise ValueError('record needs --review')
            review = json.loads(args.review.read_text(encoding='utf-8-sig'))
            current = inspect(project, path, ROOT)
            if not current['events']:
                last = (project.get('checkpoints') or [{}])[-1].get('change_review', {})
                if last.get('assessment') == review:
                    result = {'recorded': False, 'note': 'Same event assessment already saved; no duplicate request.'}
                else: raise ValueError('No pending events; do not record a different assessment blindly')
            else:
                save_checkpoint(project, path, 'Оценено влияние изменений на решение', reviewed_changes=True, change_review=review)
                result = {'recorded': True, 'note': 'Checkpoint assessment saved, not human approval.'}
        else: result = inspect(project, path, ROOT)
        output = markdown(result) if args.command == 'report' else json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            check_output(project, path, args.out)
            if args.out.exists(): raise ValueError('Choose a new output filename')
            args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(output.rstrip() + '\n', encoding='utf-8')
        else: print(output)
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        parser.exit(1, f'Material changes: {error}\n')


if __name__ == '__main__': sys.exit(main())
