#!/usr/bin/env python3
"""Persist claim/capability/evidence reviews without treating missing proof as falsehood."""
import argparse
import copy
import json
from pathlib import Path
import re
import sys

from stress_test import nonempty, strings, baseline as decision_baseline, record_review

STATUSES = ('supported', 'partially_supported', 'unsupported', 'contradicted')
LABELS = dict(supported='подтверждено', partially_supported='частично подтверждено',
              unsupported='не подтверждено', contradicted='противоречит данным')
NUMBER_PROMISE = re.compile(r'вдвое|втрое|наполовину|\d\s*(?:%|процент|раз[а-я]*\b|минут|секунд|час)', re.I)


def validate_fields(project):
    errors = []
    def namespace(items, key, name):
        if not isinstance(items, list):
            errors.append(name + ' must be an array')
            return {}
        result = {}
        for item in items:
            if not isinstance(item, dict) or not nonempty(item.get(key)):
                errors.append(name + ' needs objects with ' + key)
            elif item[key] in result:
                errors.append(name + ' contains duplicate ' + key)
            else:
                result[item[key]] = item
        return result
    evidence_ids = {e['evidence_id'] for e in project.get('evidence', []) if isinstance(e, dict) and nonempty(e.get('evidence_id'))}
    caps = namespace(project.get('product_capabilities', []), 'capability_id', 'product_capabilities')
    claims = namespace(project.get('marketing_claims', []), 'claim_id', 'marketing_claims')
    def refs(item, key, allowed, required=False):
        value = item.get(key)
        if not strings(value) or len(value) != len(set(value)) or (required and not value):
            errors.append(key + ' needs distinct nonempty IDs')
        elif not set(value) <= set(allowed):
            errors.append(key + ' references unknown IDs')
    for cap in caps.values():
        if not nonempty(cap.get('description')) or cap.get('availability') not in ('implemented', 'planned', 'unknown'):
            errors.append('capability needs description and implemented/planned/unknown availability')
        refs(cap, 'evidence_ids', evidence_ids)
    for claim in claims.values():
        if not nonempty(claim.get('text')) or claim.get('kind') not in ('quantitative', 'qualitative'):
            errors.append('claim needs text and quantitative/qualitative kind')
        if type(claim.get('requires_causal_evidence')) is not bool:
            errors.append('claim requires_causal_evidence must be boolean')
        if nonempty(claim.get('text')) and NUMBER_PROMISE.search(claim['text']) and claim.get('kind') != 'quantitative':
            errors.append('Explicit numerical promise must be quantitative: ' + claim['claim_id'])
        refs(claim, 'capability_ids', caps, True)
    reviews = project.get('marketing_claims_audits', [])
    if not isinstance(reviews, list):
        return errors + ['marketing_claims_audits must be an array']
    ids = set()
    for review in reviews:
        if not isinstance(review, dict):
            errors.append('Claims audit must be an object')
            continue
        rid = review.get('review_id')
        if not nonempty(rid) or rid in ids:
            errors.append('Claims audit review_id must be unique text')
        if nonempty(rid):
            ids.add(rid)
        if type(review.get('schema_version')) is not int or review['schema_version'] != 1:
            errors.append('Claims audit schema_version must be 1')
        for key in ('reviewer', 'limitations'):
            if not nonempty(review.get(key)):
                errors.append('Claims audit needs ' + key)
        base = review.get('baseline')
        if not isinstance(base, dict):
            errors.append('Claims audit needs prepared baseline')
            continue
        if base.get('project_id') != project.get('project_id') or not isinstance(base.get('state_hash'), str) or not re.fullmatch('[0-9a-f]{64}', base['state_hash']):
            errors.append('Claims audit has invalid project/hash')
        old_claims = namespace(base.get('claims'), 'claim_id', 'baseline.claims')
        old_caps = namespace(base.get('capabilities'), 'capability_id', 'baseline.capabilities')
        old_evidence = base.get('evidence_ids')
        if not strings(old_evidence):
            errors.append('Claims baseline needs evidence_ids')
            old_evidence = []
        for key in ('evidence_catalog', 'source_catalog'):
            if not isinstance(base.get(key), dict) or any(not isinstance(v, dict) for v in base[key].values()):
                errors.append('Claims baseline needs ' + key + ' objects')
            else:
                for value in base[key].values():
                    required = ('claim', 'claim_type', 'status') if key == 'evidence_catalog' else ('title', 'url_or_path', 'accessed_at')
                    if any(not nonempty(value.get(k)) for k in required):
                        errors.append('Malformed historical ' + key + ' entry')
                    if key == 'evidence_catalog' and (not strings(value.get('source_ids')) or
                            ('locator' in value and not nonempty(value['locator']))):
                        errors.append('Historical evidence needs source_ids and text locator when present')
        for cap in old_caps.values():
            if not nonempty(cap.get('description')) or cap.get('availability') not in ('implemented', 'planned', 'unknown'):
                errors.append('Malformed historical capability')
            refs(cap, 'evidence_ids', old_evidence)
        for claim in old_claims.values():
            if not nonempty(claim.get('text')) or claim.get('kind') not in ('quantitative', 'qualitative') or type(claim.get('requires_causal_evidence')) is not bool:
                errors.append('Malformed historical marketing claim')
            refs(claim, 'capability_ids', old_caps, True)
        assessments = review.get('assessments')
        rows = namespace(assessments, 'claim_id', 'assessments')
        if not old_claims or set(rows) != set(old_claims):
            errors.append('Audit must cover every baseline claim exactly once')
        for cid, row in rows.items():
            original = old_claims.get(cid, {})
            if not nonempty(row.get('original_claim')) or row.get('original_claim') != original.get('text'):
                errors.append('Audit original_claim must exactly match baseline claim')
            for key in ('rationale', 'accepted_wording', 'validation_method', 'scope_match'):
                if not nonempty(row.get(key)):
                    errors.append('Claim assessment needs ' + key)
            if row.get('status') not in STATUSES:
                errors.append('Unknown claim status')
            refs(row, 'capability_ids', old_caps, True)
            if row.get('capability_ids') != original.get('capability_ids'):
                errors.append('Assessment must preserve the claim capability mapping')
            links = row.get('evidence_links')
            if not isinstance(links, list):
                errors.append('evidence_links must be an array')
                continue
            seen = set()
            for link in links:
                if not isinstance(link, dict):
                    errors.append('Evidence link must be an object')
                    continue
                eid = link.get('evidence_id')
                if not nonempty(eid) or eid not in old_evidence or eid in seen:
                    errors.append('Evidence link needs a distinct registered evidence_id')
                if nonempty(eid):
                    seen.add(eid)
                if link.get('relation') not in ('supports', 'context', 'contradicts') or link.get('coverage') not in ('full', 'partial') or not nonempty(link.get('reason')):
                    errors.append('Evidence link needs relation, full/partial coverage and reason')
    return errors


def baseline(project, path, root):
    return {**decision_baseline(project, path, root),
            'claims': copy.deepcopy(project.get('marketing_claims', [])),
            'capabilities': copy.deepcopy(project.get('product_capabilities', [])),
            'evidence_catalog': {e['evidence_id']: {k: copy.deepcopy(e[k]) for k in
                ('claim', 'claim_type', 'status', 'locator', 'source_ids') if k in e} for e in project['evidence']},
            'source_catalog': {s['source_id']: {k: s[k] for k in
                ('title', 'url_or_path', 'snapshot_path', 'accessed_at') if k in s} for s in project['sources']}}


def prepare(project, path, root, review_id):
    if not project.get('marketing_claims'):
        raise ValueError('First register significant marketing_claims and their product_capabilities')
    return {'schema_version': 1, 'review_id': review_id, 'baseline': baseline(project, path, root),
            'reviewer': '', 'limitations': '',
            'assessments': [{'claim_id': c['claim_id'], 'original_claim': c['text'],
                            'capability_ids': c['capability_ids'].copy(), 'status': 'unsupported',
                            'evidence_links': [], 'scope_match': '', 'rationale': '',
                            'accepted_wording': '', 'validation_method': ''} for c in project['marketing_claims']]}


def inspect(project, path, root):
    from quality import FACTS, support_blockers
    reviews = project.get('marketing_claims_audits', [])
    empty = {'status': 'not_recorded', 'blockers': [], 'publication_blockers': [], 'claims': []}
    if not reviews:
        if project.get('marketing_claims'):
            empty.update(status='needs_review', blockers=['Registered marketing claims need a saved audit'])
        return empty
    review = reviews[-1]
    if review['baseline'] != baseline(project, path, root):
        return {**empty, 'status': 'stale', 'review_id': review['review_id'],
                'blockers': ['Marketing claims audit is stale: message, capability, source or decision context changed; prepare a new version']}
    by_eid = {e['evidence_id']: e for e in project['evidence']}
    by_source = {s['source_id']: s for s in project['sources']}
    caps = {c['capability_id']: c for c in project['product_capabilities']}
    claims = {c['claim_id']: c for c in project['marketing_claims']}
    used = {link['evidence_id'] for row in review['assessments'] for link in row['evidence_links']}
    used |= {eid for row in review['assessments'] for cid in row['capability_ids'] for eid in caps[cid]['evidence_ids']}
    blockers = support_blockers(project, path, root, used, 'Claims support')
    publication, results = [], []
    def actual_observation(eid):
        e = by_eid[eid]
        return (e['claim_type'] in FACTS and e.get('claim_scope') in ('project_observation', 'causal_effect')
                and bool(e['source_ids']) and all(not by_source[s].get('synthetic') and by_source[s]['kind'] not in
                    ('synthetic', 'model_respondent', 'agent_note') and by_source[s].get('evidence_scope') != 'simulation'
                    for s in e['source_ids']))
    for row in review['assessments']:
        claim = claims[row['claim_id']]
        cid = claim['claim_id']
        supporting = [l for l in row['evidence_links'] if l['relation'] == 'supports']
        contrary = [l for l in row['evidence_links'] if l['relation'] == 'contradicts']
        factual_support = [l for l in supporting if by_eid[l['evidence_id']]['claim_type'] in FACTS]
        implemented = all(caps[c]['availability'] == 'implemented' and
                          any(actual_observation(e) for e in caps[c]['evidence_ids']) for c in row['capability_ids'])
        full = bool(factual_support) and all(l['coverage'] == 'full' for l in factual_support)
        measurements = [l for l in factual_support if by_eid[l['evidence_id']]['claim_type'] == 'measured_fact'
                        and actual_observation(l['evidence_id'])]
        causal = [l for l in measurements if by_eid[l['evidence_id']].get('claim_scope') == 'causal_effect']
        # These gates check recorded provenance, not whether a passage entails the claim.
        proof = full and implemented
        if claim['kind'] == 'quantitative':
            proof = proof and bool(measurements)
        if claim['requires_causal_evidence']:
            design = project.get('validation_design', {})
            proof = proof and bool(causal) and design.get('status') == 'completed' and design.get('data_origin') == 'real' and design.get('purpose') == 'causal_effect'
            if proof:
                from quality import assess
                blockers.extend('Claims causal proof: ' + b for b in assess(project, path, root)['blockers']
                                if not b.startswith('Strategy review') and not b.startswith('Record strategy_review'))
        status = row['status']
        if contrary and status != 'contradicted':
            blockers.append(cid + ': explicit contradictory evidence cannot be hidden')
        if status == 'contradicted' and (not contrary or any(by_eid[l['evidence_id']]['claim_type'] not in FACTS for l in contrary)):
            blockers.append(cid + ': contradiction requires factual contrary evidence; missing proof is not falsehood')
        if status == 'contradicted' and claim['kind'] == 'quantitative' and not any(actual_observation(l['evidence_id']) for l in contrary):
            blockers.append(cid + ': a document about missing measurements cannot refute a numerical effect without contrary observations')
        if status == 'supported' and (contrary or not proof):
            blockers.append(cid + ': full confirmation needs relevant observations, implemented capabilities and required measurements/causal design')
        if status == 'partially_supported' and (contrary or not factual_support):
            blockers.append(cid + ': partial confirmation needs relevant factual support, not only a hypothesis')
        if status == 'unsupported' and (contrary or factual_support):
            blockers.append(cid + ': use context links for irrelevant evidence; distinguish partial support from absence')
        if status != 'supported' and row['accepted_wording'].strip().casefold() == claim['text'].strip().casefold():
            blockers.append(cid + ': unconfirmed original promise cannot be its own accepted wording')
        if status != 'supported' and not measurements and NUMBER_PROMISE.search(row['accepted_wording']):
            blockers.append(cid + ': accepted wording still has a numerical promise without measurements')
        if status != 'supported' and claim['text'].casefold() in project.get('communication_strategy', {}).get('message', '').casefold():
            publication.append(cid + ': communication message still contains the unconfirmed original promise')
        results.append({'claim_id': cid, 'status': status, 'quantitative': claim['kind'] == 'quantitative',
                        'has_required_measurements': bool(measurements), 'capabilities_implemented_with_observations': implemented,
                        'accepted_wording': row['accepted_wording'],
                        'note': 'No proof is not proof of falsehood; a cautious wording does not supply missing evidence.'})
    return {'status': 'blocked' if blockers else 'review_record_complete', 'review_id': review['review_id'],
            'blockers': sorted(set(blockers)), 'publication_blockers': publication, 'claims': results,
            'note': 'Recorded content review, not an independent semantic/advertising guarantee. Strategy is never rewritten automatically.'}


def markdown(project, result):
    lines = ['## Проверка маркетинговых обещаний', '', 'Статус аудита: ' + result['status'],
             'Отсутствие подтверждения не доказывает ложность. Осторожная формулировка не заменяет измерения.']
    if not project.get('marketing_claims_audits'):
        return '\n'.join(lines + ['Аудит не записан.']) + '\n'
    review = project['marketing_claims_audits'][-1]
    lines += ['Версия: ' + review['review_id'], 'Проверил: ' + review['reviewer'],
              'Ограничения: ' + review['limitations'], 'Хеш контекста: ' + review['baseline']['state_hash']]
    if result['blockers'] or result['publication_blockers']:
        lines += ['', 'Требуется пересмотр:', *['- ' + b for b in result['blockers'] + result['publication_blockers']]]
    caps = {c['capability_id']: c for c in review['baseline']['capabilities']}
    lines += ['', 'При stale/blocked ниже показана историческая запись; применять её как актуальную нельзя.']
    for row in review['assessments']:
        lines += ['', '### ' + row['claim_id'] + ': ' + row['original_claim'], 'Статус: ' + LABELS[row['status']],
                  'Возможности: ' + '; '.join(c + ': ' + caps[c]['description'] + ' [' + caps[c]['availability'] + ']' for c in row['capability_ids']),
                  'Обоснование: ' + row['rationale'], 'Применимость: ' + row['scope_match']]
        result_row = next((r for r in result['claims'] if r['claim_id'] == row['claim_id']), None)
        if result_row and result_row['quantitative'] and not result_row['has_required_measurements']:
            lines += ['Количественное обещание: требуемых подтверждающих измерений нет.']
        for link in row['evidence_links']:
            lines += ['- ' + link['evidence_id'] + ' [' + link['relation'] + '; ' + link['coverage'] + ']: ' + link['reason']]
        # Preserve historical provenance in the standalone report as well as in project.json.
        refs = {l['evidence_id'] for l in row['evidence_links']}
        refs |= {eid for c in row['capability_ids'] for eid in caps[c]['evidence_ids']}
        for eid in sorted(refs):
            item = review['baseline']['evidence_catalog'].get(eid, {})
            lines += ['  ' + eid + ': ' + item.get('claim', '') + '; координаты: ' + item.get('locator', 'не записаны')]
            for sid in item.get('source_ids', []):
                source = review['baseline']['source_catalog'].get(sid, {})
                lines += ['  Источник ' + sid + ': ' + source.get('url_or_path', '') + '; дата: ' + source.get('accessed_at', 'не записана')]
        if not row['evidence_links']:
            lines += ['Подтверждающие измерения/источники обещания не указаны.']
        lines += ['Допустимая формулировка (предложение агента): ' + row['accepted_wording'],
                  'Как проверить исходное обещание: ' + row['validation_method']]
    return '\n'.join(lines) + '\n'


def record(project, path, root, review):
    return record_review(project, path, root, review, field='marketing_claims_audits', inspector=inspect,
                         action='marketing claims audit', tool='scripts/claims_audit.py')


def main():
    from checkpoint import ROOT
    from output_guard import check_output
    from project_tool import load
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'record', 'inspect', 'report'))
    parser.add_argument('project', type=Path)
    parser.add_argument('--review-id')
    parser.add_argument('--review', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        path = args.project.resolve()
        project = load(path)
        if args.command == 'record':
            if not args.review or args.out:
                raise ValueError('record requires --review and rejects --out')
            result = record(project, path, ROOT, json.loads(args.review.read_text(encoding='utf-8-sig')))
        elif args.command == 'prepare':
            if not args.review_id:
                raise ValueError('prepare requires --review-id')
            result = prepare(project, path, ROOT, args.review_id)
        else:
            result = inspect(project, path, ROOT)
        output = markdown(project, result) if args.command == 'report' else json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            check_output(project, path, args.out)
            if args.out.exists():
                raise ValueError('Output exists; choose a new versioned filename')
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output.rstrip() + '\n', encoding='utf-8')
        else:
            print(output)
        return 1 if args.command in ('inspect', 'report') and (result['blockers'] or result['publication_blockers']) else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Claims audit: {error}\n')


if __name__ == '__main__':
    sys.exit(main())
