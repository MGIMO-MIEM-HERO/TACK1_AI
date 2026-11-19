#!/usr/bin/env python3
"""Versioned resource feasibility, separate from permission and human choice."""
import argparse
import copy
from datetime import date
import json
import math
from pathlib import Path
import re
import sys

from stress_test import baseline as decision_baseline, nonempty, record_review, strings

FIELD = 'feasibility_reviews'


def baseline(project, path, root):
    # The record cannot invalidate itself; other reviews include these resource inputs.
    return decision_baseline(project, path, root, include_feasibility=False)


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def validate_fields(project):
    reviews = project.get(FIELD, [])
    if not isinstance(reviews, list):
        return ['feasibility_reviews must be an array']
    errors, ids = [], set()
    for review in reviews:
        if not isinstance(review, dict):
            errors.append('Feasibility review must be an object'); continue
        rid = review.get('review_id')
        if not nonempty(rid) or rid in ids:
            errors.append('Feasibility review_id must be unique text')
        if nonempty(rid): ids.add(rid)
        if type(review.get('schema_version')) is not int or review['schema_version'] != 1:
            errors.append('Feasibility schema_version must be 1')
        if review.get('context') not in ('live_project', 'authored_example'):
            errors.append('Feasibility context must be live_project/authored_example')
        for key in ('reviewer', 'limitations'):
            if not nonempty(review.get(key)): errors.append('Feasibility needs ' + key)
        base = review.get('baseline')
        if not isinstance(base, dict) or base.get('project_id') != project.get('project_id'):
            errors.append('Feasibility needs a prepared baseline for this project'); continue
        if not isinstance(base.get('state_hash'), str) or not re.fullmatch('[0-9a-f]{64}', base['state_hash']):
            errors.append('Feasibility baseline needs SHA-256')
        if any(not strings(base.get(k)) for k in ('option_ids', 'evidence_ids', 'source_ids')):
            errors.append('Feasibility baseline needs registered IDs'); continue
        evidence_ids, option_ids = set(base['evidence_ids']), set(base['option_ids'])

        def refs(obj):
            values = obj.get('evidence_ids')
            if not strings(values) or len(values) != len(set(values)) or not set(values) <= evidence_ids:
                errors.append('Feasibility evidence_ids must reference distinct baseline IDs')

        def statement(obj, statuses, label):
            if not isinstance(obj, dict):
                errors.append(label + ' must be an object'); return False
            valid_status = obj.get('status') in statuses
            if not valid_status: errors.append(label + ' has invalid status')
            if not nonempty(obj.get('basis')): errors.append(label + ' needs an explicit basis or missing-data explanation')
            refs(obj)
            if obj.get('status') != 'unknown' and not obj.get('evidence_ids'):
                errors.append(label + ' needs evidence for an assertion or estimate')
            return valid_status

        plans = review.get('assessments')
        if not isinstance(plans, list) or not plans:
            errors.append('Feasibility needs at least one option assessment'); continue
        seen = set()
        for plan in plans:
            if not isinstance(plan, dict): errors.append('Feasibility assessment must be an object'); continue
            oid = plan.get('option_id')
            if not nonempty(oid) or oid not in option_ids or oid in seen:
                errors.append('Feasibility option_id must be distinct and registered')
            if nonempty(oid): seen.add(oid)
            for key in ('minimum_scope', 'next_check'):
                if not nonempty(plan.get(key)): errors.append('Feasibility needs ' + key)
            statement(plan.get('permission'), ('allowed', 'denied', 'unknown'), 'Permission')
            statement(plan.get('scope'), ('confirmed', 'unknown'), 'Work breakdown completeness')
            window = plan.get('window')
            if statement(window, ('confirmed', 'unknown'), 'Available window'):
                if window['status'] == 'confirmed':
                    try:
                        if date.fromisoformat(window['start']) > date.fromisoformat(window['end']): raise ValueError()
                    except (ValueError, TypeError, KeyError): errors.append('Window needs ordered ISO calendar dates')
                elif window.get('start') is not None or window.get('end') is not None:
                    errors.append('Unknown window uses null dates')
            schedule = plan.get('schedule')
            if statement(schedule, ('confirmed', 'estimated', 'unknown'), 'Calendar/dependency fit'):
                if schedule.get('fit') not in ('fits', 'does_not_fit', 'unknown'):
                    errors.append('Schedule fit must be fits/does_not_fit/unknown')
                if (schedule['status'] == 'unknown') != (schedule.get('fit') == 'unknown'):
                    errors.append('Unknown schedule must not assert calendar fit')
            work = plan.get('work')
            if not isinstance(work, list) or not work:
                errors.append('Feasibility needs explicit minimum work packages'); work = []
            work_ids = set()
            for task in work:
                if not isinstance(task, dict): errors.append('Work package must be an object'); continue
                wid = task.get('work_id')
                if not nonempty(wid) or wid in work_ids: errors.append('Work IDs must be unique text')
                if nonempty(wid): work_ids.add(wid)
                if not all(nonempty(task.get(k)) for k in ('description', 'skill')):
                    errors.append('Work package needs description and required skill')
                effort = task.get('effort')
                if statement(effort, ('estimated', 'observed', 'unknown'), 'Work effort in person-hours'):
                    if effort['status'] == 'unknown':
                        if effort.get('hours') is not None: errors.append('Unknown effort is null, not zero')
                    elif not number(effort.get('hours')): errors.append('Effort hours must be finite nonnegative numbers')
            resources = plan.get('resources')
            if not isinstance(resources, list): errors.append('Resources must be an array'); resources = []
            resource_ids = set()
            for resource in resources:
                if not isinstance(resource, dict): errors.append('Resource must be an object'); continue
                resource_id = resource.get('resource_id')
                if not nonempty(resource_id) or resource_id in resource_ids: errors.append('Resource IDs must be unique text')
                if nonempty(resource_id): resource_ids.add(resource_id)
                # A resource ID represents one person/pool exactly once within this option.
                if not strings(resource.get('skills')): errors.append('Resources need explicit skills')
                statement(resource.get('competence'), ('confirmed', 'unknown'), 'Competence')
                statement(resource.get('availability'), ('confirmed', 'unavailable', 'unknown'), 'Availability')
                capacity = resource.get('capacity')
                if statement(capacity, ('confirmed', 'estimated', 'unknown'), 'Capacity within the stated window'):
                    if capacity['status'] == 'unknown':
                        if capacity.get('hours') is not None: errors.append('Unknown capacity is null, not zero')
                    elif not number(capacity.get('hours')): errors.append('Capacity hours must be finite nonnegative numbers')
                    if resource.get('availability', {}).get('status') == 'unavailable' and capacity.get('hours') not in (None, 0):
                        errors.append('Unavailable resource cannot provide positive capacity')
            allocations = plan.get('allocations')
            if not isinstance(allocations, list): errors.append('Allocations must be an array'); allocations = []
            pairs = set()
            for row in allocations:
                if not isinstance(row, dict): errors.append('Allocation must be an object'); continue
                wid, resource_id = row.get('work_id'), row.get('resource_id')
                if not nonempty(wid) or not nonempty(resource_id) or wid not in work_ids or resource_id not in resource_ids:
                    errors.append('Allocation needs registered work/resource IDs'); continue
                pair = (wid, resource_id)
                if pair in pairs: errors.append('Duplicate work/resource allocation')
                pairs.add(pair)
                if not number(row.get('hours')): errors.append('Allocated hours must be finite nonnegative numbers')
            valid_hours = [a['hours'] for a in allocations if isinstance(a, dict) and number(a.get('hours'))]
            if not number(sum(valid_hours)):
                errors.append('Aggregate allocated hours must remain finite')
            dependencies = plan.get('dependencies')
            if not isinstance(dependencies, list): errors.append('Dependencies must be an array'); dependencies = []
            dep_ids = set()
            for dep in dependencies:
                if not statement(dep, ('satisfied', 'blocked', 'unknown'), 'Dependency'): continue
                did = dep.get('dependency_id')
                if not nonempty(did) or did in dep_ids: errors.append('Dependency IDs must be unique text')
                if nonempty(did): dep_ids.add(did)
                if not nonempty(dep.get('description')) or type(dep.get('critical')) is not bool:
                    errors.append('Dependency needs description and explicit critical boolean')
    return errors


def prepare(project, path, root, review_id, option_ids=None):
    ids = option_ids if option_ids is not None else list(dict.fromkeys(
        oid for oid in (project.get('recommended_option_id'), project.get('chosen_option_id')) if oid))
    if not ids or not set(ids) <= {o['option_id'] for o in project['options']}:
        raise ValueError('Select registered options to assess; no recommendation or choice is written')
    def unknown():
        return {'status': 'unknown', 'basis': 'Неизвестно; требуется целевое уточнение', 'evidence_ids': []}
    return {'schema_version': 1, 'review_id': review_id, 'baseline': baseline(project, path, root),
            'context': 'live_project', 'reviewer': '', 'limitations': '', 'assessments': [
                {'option_id': oid, 'minimum_scope': '', 'permission': unknown(), 'scope': unknown(),
                 'window': {**unknown(), 'start': None, 'end': None},
                 'work': [{'work_id': 'W1', 'description': '', 'skill': '',
                           'effort': {**unknown(), 'hours': None}}],
                 'resources': [], 'allocations': [], 'dependencies': [],
                 'schedule': {**unknown(), 'fit': 'unknown'}, 'next_check': ''} for oid in ids]}


def evaluate(plan):
    """Evaluate a supplied resource plan, never discover resources or choose an option."""
    unknown, deficits, assumptions = [], [], []
    permission = plan['permission']['status']
    if permission == 'denied': deficits.append('Разрешение на этот объём отсутствует: явно запрещено.')
    elif permission == 'unknown': unknown.append('Уточнить разрешение на минимальный объём; это не проверка ресурсов.')
    if plan['scope']['status'] != 'confirmed': unknown.append('Не подтверждена полнота минимального перечня работ.')
    window = plan['window']
    if window['status'] != 'confirmed': unknown.append('Неизвестно доступное календарное окно.')
    resources = {r['resource_id']: r for r in plan['resources']}
    if not resources: unknown.append('Не указаны доступные исполнители/роли и компетенции; это не доказанный дефицит.')
    for resource in resources.values():
        if resource['competence']['status'] != 'confirmed': unknown.append('Не подтверждены компетенции: ' + resource['resource_id'])
        if resource['availability']['status'] == 'unknown': unknown.append('Не подтверждена доступность: ' + resource['resource_id'])
        cap = resource['capacity']
        if cap['status'] != 'confirmed': unknown.append('Не подтверждена ёмкость в данном окне: ' + resource['resource_id'])
        if cap['status'] == 'estimated': assumptions.append('Ёмкость ' + resource['resource_id'] + ' только оценена: ' + cap['basis'])
        if window['status'] == 'confirmed' and cap['hours'] is not None:
            days = (date.fromisoformat(window['end']) - date.fromisoformat(window['start'])).days + 1
            if cap['hours'] > days * 24:
                unknown.append('Ёмкость превышает физическое календарное окно: ' + resource['resource_id'])
    totals = {rid: 0 for rid in resources}
    load_known = True
    for task in plan['work']:
        wid, effort = task['work_id'], task['effort']
        if effort['status'] == 'unknown':
            unknown.append('Нет оценки трудоёмкости: ' + wid); load_known = False
        elif effort['status'] == 'estimated': assumptions.append('Трудоёмкость ' + wid + ' — оценка: ' + effort['basis'])
        rows = [a for a in plan['allocations'] if a['work_id'] == wid]
        allocated = sum(a['hours'] for a in rows)
        if effort['hours'] is not None and not math.isclose(allocated, effort['hours'], rel_tol=1e-9, abs_tol=1e-9):
            unknown.append('Не распределён весь объём работ (или есть лишние часы): ' + wid)
            load_known = False
        if not rows: unknown.append('Не определён исполнитель: ' + wid)
        for row in rows:
            resource = resources[row['resource_id']]
            totals[row['resource_id']] += row['hours']
            if row['hours'] and task['skill'] not in resource['skills']:
                unknown.append('Назначенная роль не покрывает требуемую компетенцию: ' + wid)
            if row['hours'] and resource['availability']['status'] == 'unavailable':
                deficits.append('Назначенный исполнитель подтверждённо недоступен: ' + row['resource_id'])
    for rid, allocated in totals.items():
        cap = resources[rid]['capacity']
        if load_known and window['status'] == 'confirmed' and cap['status'] == 'confirmed' and allocated > cap['hours'] + 1e-9:
            deficits.append('Нагрузка ' + rid + ': ' + str(allocated) + ' чел·ч превышает подтверждённую ёмкость ' + str(cap['hours']) + ' чел·ч в этом окне (по записанному распределению).')
    for dep in plan['dependencies']:
        if dep['critical'] and dep['status'] == 'blocked': deficits.append('Критическая зависимость заблокирована: ' + dep['description'])
        elif dep['critical'] and dep['status'] == 'unknown': unknown.append('Уточнить критическую зависимость: ' + dep['description'])
    schedule = plan['schedule']
    if schedule['status'] == 'unknown': unknown.append('Не проверена календарная последовательность и зависимости; суммы часов недостаточно.')
    elif schedule['fit'] == 'does_not_fit':
        if schedule['status'] == 'confirmed': deficits.append('Подтверждено: последовательность работ не укладывается в окно.')
        else: unknown.append('По предварительной оценке календарный план не укладывается; уточнить оценку.')
    if schedule['status'] == 'estimated': assumptions.append('Календарный план только оценён: ' + schedule['basis'])
    outcome = 'infeasible' if deficits else 'unknown' if unknown else 'feasible'
    return {'option_id': plan['option_id'], 'outcome': outcome, 'permission': permission,
            'reasons': sorted(set(deficits)), 'unknowns': sorted(set(unknown)),
            'assumptions': sorted(set(assumptions)), 'next_check': plan['next_check'],
            'allocated_person_hours': totals,
            'scope': 'Только указанный минимальный объём и распределение в заданном окне; не обещание успеха, не доказательство отсутствия иных планов.'}


def inspect(project, path, root):
    from quality import support_blockers
    from follow_up import calendar_day
    reviews = project.get(FIELD, [])
    empty = {'status': 'not_recorded', 'blockers': [], 'decision_blockers': [], 'assessments': [], 'questions': []}
    if not reviews:
        return {**empty, 'note': 'Осуществимость не проверена; наличие разрешения или выбора не подтверждает ресурсы.'}
    review = reviews[-1]
    if review['baseline'] != baseline(project, path, root):
        return {**empty, 'status': 'stale', 'review_id': review['review_id'],
                'blockers': ['Feasibility review is stale: scope, constraints, sources or strategy changed; review resources again']}
    by_eid = {e['evidence_id']: e for e in project['evidence']}
    sources = {s['source_id']: s for s in project['sources']}
    blockers, used = [], set()

    def check(obj):
        refs = obj['evidence_ids']; used.update(refs)
        status = obj['status']
        if status in ('unknown', 'estimated'): return
        # Facts about a supplied document do not establish real team capacity.
        supported = False
        for eid in refs:
            e = by_eid[eid]
            pending, seen = [eid], set()
            while pending:
                key = pending.pop()
                if key not in seen:
                    seen.add(key); pending.extend(by_eid[key].get('related_evidence_ids', []))
            synthetic = any(sources[s].get('synthetic') or sources[s]['kind'] in ('synthetic', 'model_respondent')
                            or sources[s].get('evidence_scope') == 'simulation'
                            for key in seen for s in by_eid[key]['source_ids'])
            factual = e['claim_type'] in ('source_fact', 'measured_fact')
            if factual and (review['context'] == 'authored_example' or
                            (not synthetic and e.get('claim_scope') in ('owner_input', 'project_observation'))):
                supported = True
        if not supported: blockers.append('Feasibility factual assertions need actual owner/project evidence, not permission alone, a model hypothesis or document description')

    assessments = []
    for plan in review['assessments']:
        for key in ('permission', 'scope', 'window', 'schedule'): check(plan[key])
        for task in plan['work']: check(task['effort'])
        for resource in plan['resources']:
            for key in ('competence', 'availability', 'capacity'): check(resource[key])
        for dep in plan['dependencies']: check(dep)
        row = evaluate(plan)
        try:
            if plan['window']['status'] == 'confirmed' and date.fromisoformat(plan['window']['end']) < calendar_day(project):
                row['outcome'] = 'unknown'
                row['unknowns'].append('Записанное окно уже закончилось; уточнить новый срок и оставшуюся ёмкость, не переносить их автоматически.')
        except ValueError:
            row['outcome'] = 'unknown'
            row['unknowns'].append('Уточнить часовой пояс для оценки доступного календарного окна.')
        assessments.append({**row, 'plan': copy.deepcopy(plan)})
    blockers.extend(support_blockers(project, path, root, used, 'Feasibility support'))
    checked = {a['option_id'] for a in assessments}
    for oid in {project.get('recommended_option_id'), project.get('chosen_option_id')} - {None}:
        if oid not in checked:
            # An alternative outside the recorded check is not silently deemed feasible.
            assessments.append({'option_id': oid, 'outcome': 'unknown', 'permission': 'unknown',
                                'reasons': [], 'unknowns': ['Этот вариант не проверен в текущей версии.'],
                                'assumptions': [], 'next_check': 'Проверить минимальный объём и ресурсы этого варианта отдельно.'})
    decision_blockers = ['Feasibility: selected option ' + a['option_id'] + ' has a documented resource/permission deficit; ask the owner, do not choose an alternative automatically'
                         for a in assessments if a['outcome'] == 'infeasible' and a['option_id'] in
                         (project.get('recommended_option_id'), project.get('chosen_option_id'))]
    if blockers:
        # Never expose an unsupported favourable conclusion as current.
        for a in assessments: a['outcome'] = 'unknown'
    return {'status': 'blocked' if blockers else 'review_record_complete', 'review_id': review['review_id'],
            'context': review['context'], 'limitations': review['limitations'],
            'blockers': sorted(set(blockers)), 'decision_blockers': [] if blockers else decision_blockers,
            'assessments': assessments,
            'questions': [{'option_id': a['option_id'], 'unknowns': a['unknowns'], 'action': a['next_check']}
                          for a in assessments if a['outcome'] != 'feasible'],
            'note': 'Самопроверка записанного плана. Не проверка истинности источника, не согласие владельца и не автоматический выбор.'}


def markdown(project, result):
    lines = ['## Отдельная проверка осуществимости', '', 'Статус записи: ' + result['status'],
             'Разрешение, ресурсы, оценка работ и календарный план проверяются отдельно.']
    if result.get('context') == 'authored_example': lines.append('Авторский вымышленный пример: это не реальные ресурсы и не согласование команды.')
    if result.get('limitations'): lines.append('Ограничения: ' + result['limitations'])
    for b in result['blockers'] + result['decision_blockers']: lines.append('Блокер: ' + b)
    for row in result['assessments']:
        lines += ['', '### ' + row['option_id'] + ': ' + row['outcome'], 'Разрешение: ' + row['permission']]
        plan = row.get('plan')
        if plan:
            lines += ['Основание разрешения: ' + plan['permission']['basis'] + '; evidence: ' + ', '.join(plan['permission']['evidence_ids']),
                      'Минимальный объём: ' + plan['minimum_scope'], 'Полнота работ: ' + plan['scope']['status'],
                      'Окно: ' + str(plan['window']['start']) + ' — ' + str(plan['window']['end']) + '; ' + plan['window']['basis']]
            for task in plan['work']:
                e = task['effort']
                lines += ['- ' + task['work_id'] + ': ' + task['description'] + '; компетенция: ' + task['skill'] +
                          '; трудоёмкость: ' + ('неизвестно' if e['hours'] is None else str(e['hours']) + ' чел·ч') +
                          ' [' + e['status'] + ']; основание: ' + e['basis'] + '; evidence: ' + ', '.join(e['evidence_ids'])]
            for r in plan['resources']:
                lines += ['- Ресурс ' + r['resource_id'] + ': ' + ', '.join(r['skills']) + '; компетенция ' + r['competence']['status'] +
                          '; доступность ' + r['availability']['status'] + '; ёмкость ' + str(r['capacity']['hours']) +
                          ' чел·ч [' + r['capacity']['status'] + ']; основание: ' + r['capacity']['basis'],
                          '  Доступность: ' + r['availability']['basis'] + '; evidence: ' + ', '.join(r['availability']['evidence_ids']),
                          '  Компетенция: ' + r['competence']['basis'] + '; evidence: ' + ', '.join(r['competence']['evidence_ids'])]
            for d in plan['dependencies']: lines.append('- Зависимость: ' + d['description'] + ' [' + d['status'] + ']; ' + d['basis'])
            lines.append('Календарное соответствие: ' + plan['schedule']['fit'] + ' [' + plan['schedule']['status'] + ']; ' + plan['schedule']['basis'])
        lines += ['Дефицит: ' + x for x in row['reasons']]
        lines += ['Неизвестно / уточнить: ' + x for x in row['unknowns']]
        lines += ['Допущение: ' + x for x in row['assumptions']]
        lines += ['Следующая проверка: ' + row['next_check']]
    lines += ['', result.get('note', ''), 'Неизвестная трудоёмкость сама по себе не делает бумажный вариант основным. Выбор человека не меняется.']
    return '\n'.join(lines) + '\n'


def record(project, path, root, review):
    return record_review(project, path, root, review, field=FIELD, inspector=inspect,
                         action='resource feasibility review', tool='scripts/feasibility.py')


def main():
    from checkpoint import ROOT
    from output_guard import check_output
    from project_tool import load
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'record', 'inspect', 'report'))
    parser.add_argument('project', type=Path)
    parser.add_argument('--review-id'); parser.add_argument('--review', type=Path)
    parser.add_argument('--option-ids', help='Comma-separated existing options for prepare only')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        path = args.project.resolve(); project = load(path)
        if args.option_ids and args.command != 'prepare': raise ValueError('--option-ids is only for prepare')
        if args.command == 'prepare':
            if not args.review_id: raise ValueError('prepare needs --review-id')
            result = prepare(project, path, ROOT, args.review_id, args.option_ids.split(',') if args.option_ids else None)
        elif args.command == 'record':
            if not args.review or args.out: raise ValueError('record needs --review and rejects --out')
            result = record(project, path, ROOT, json.loads(args.review.read_text(encoding='utf-8-sig')))
        else: result = inspect(project, path, ROOT)
        output = markdown(project, result) if args.command == 'report' else json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            check_output(project, path, args.out)
            if args.out.exists(): raise ValueError('Choose a new versioned output filename')
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(output.rstrip() + '\n', encoding='utf-8')
        else: print(output)
        return 1 if args.command in ('inspect', 'report') and result['blockers'] else 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        parser.exit(1, f'Feasibility: {error}\n')


if __name__ == '__main__':
    sys.exit(main())
