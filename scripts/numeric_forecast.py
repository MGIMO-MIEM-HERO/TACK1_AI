#!/usr/bin/env python3
"""Record conditional numeric scenarios; arithmetic is not empirical validation."""
import argparse
import ast
import copy
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys

FIELD = 'numeric_forecast_reviews'


def text(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    if type(value) not in (int, float):
        raise ValueError('needs a finite numeric value, not a formula, null or boolean')
    result = Decimal(str(value))
    if not result.is_finite() or abs(result) > Decimal('1e30'):
        raise ValueError('numeric value is nonfinite or outside supported bounds')
    return result


def calculate(expression, values):
    """Small arithmetic language. No eval, calls, attributes, indexing or powers."""
    if not text(expression) or len(expression) > 1000:
        raise ValueError('needs a bounded arithmetic formula')
    try:
        tree = ast.parse(expression, mode='eval')
        if len(list(ast.walk(tree))) > 80:
            raise ValueError('formula is too complex; split the calculation into documented drivers')
        def visit(node, depth=0):
            if depth > 20: raise ValueError('formula nesting is too deep')
            if isinstance(node, ast.Constant): return number(node.value)
            if isinstance(node, ast.Name):
                if node.id not in values: raise ValueError('unknown formula input: ' + node.id)
                return number(values[node.id])
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand, depth + 1)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
                if isinstance(node.op, ast.Add): result = left + right
                elif isinstance(node.op, ast.Sub): result = left - right
                elif isinstance(node.op, ast.Mult): result = left * right
                else: result = left / right
                if not result.is_finite() or abs(result) > Decimal('1e30'): raise ValueError('formula result outside bounds')
                return result
            raise ValueError('formula allows only numbers, registered names and + - * /')
        return visit(tree.body)
    except (SyntaxError, RecursionError, ArithmeticError, InvalidOperation) as error:
        raise ValueError('invalid arithmetic formula: ' + str(error)) from error


def requirement_errors(requirement):
    errors = []
    if not isinstance(requirement, dict): return ['Forecast requirements must be an object']
    if not all(text(requirement.get(k)) for k in ('horizon', 'rationale')):
        errors.append('Forecast requirements need horizon and rationale from the task')
    metrics = requirement.get('metrics')
    if not isinstance(metrics, list) or not metrics: return errors + ['Forecast requirements need all requested metrics']
    ids = set()
    for metric in metrics:
        if not isinstance(metric, dict):
            errors.append('Forecast metric requirement must be an object'); continue
        mid = metric.get('metric_id')
        if not text(mid) or mid in ids: errors.append('Forecast metric_id must be unique nonempty text')
        if text(mid): ids.add(mid)
        if not all(text(metric.get(k)) for k in ('label', 'unit', 'basis')):
            errors.append('Forecast metric needs label, unit and basis for baseline/target or their absence')
        if metric.get('direction') not in ('higher', 'lower'):
            errors.append('Forecast metric direction must be higher/lower')
        for key in ('baseline', 'target'):
            if key not in metric: errors.append('Forecast metric must explicitly record ' + key + ', including null if unknown')
            elif metric[key] is not None:
                try: number(metric[key])
                except ValueError as error: errors.append('Forecast ' + key + ': ' + str(error))
    return errors


def review_errors(project, review):
    errors = []
    if not isinstance(review, dict): return ['Numeric forecast review must be an object']
    if type(review.get('schema_version')) is not int or review['schema_version'] != 1:
        errors.append('Numeric forecast schema_version must be 1')
    for key in ('review_id', 'reviewer', 'conditions', 'limitations', 'sensitivity'):
        if not text(review.get(key)): errors.append('Numeric forecast needs ' + key)
    base = review.get('baseline')
    if not isinstance(base, dict): return errors + ['Numeric forecast needs a prepared baseline']
    if base.get('project_id') != project.get('project_id'): errors.append('Forecast baseline belongs to another project')
    if not isinstance(base.get('state_hash'), str) or not re.fullmatch('[a-f0-9]{64}', base['state_hash']):
        errors.append('Forecast baseline needs SHA-256')
    for key in ('option_ids', 'evidence_ids', 'source_ids'):
        if not isinstance(base.get(key), list) or any(not text(v) for v in base[key]):
            errors.append('Forecast baseline needs ' + key)
    if errors: return errors
    if review.get('option_id') not in base['option_ids']:
        errors.append('Forecast option_id must reference a baseline option; it does not select it')
    requirement = review.get('requirements')
    errors.extend(requirement_errors(requirement))
    if errors: return errors
    inputs = {}
    assumptions = review.get('assumptions')
    if not isinstance(assumptions, list) or not assumptions:
        return errors + ['Forecast needs explicit numeric inputs and their provenance']
    for item in assumptions:
        if not isinstance(item, dict): errors.append('Forecast input must be an object'); continue
        identity = item.get('assumption_id')
        if (not isinstance(identity, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,31}', identity)
                or identity in ('baseline', 'target') or identity in inputs):
            errors.append('Forecast input needs a distinct arithmetic name, excluding baseline/target'); continue
        try: number(item.get('value'))
        except ValueError as error: errors.append(identity + ': ' + str(error)); continue
        inputs[identity] = item['value']
        if not all(text(item.get(k)) for k in ('unit', 'rationale', 'validation_step')):
            errors.append(identity + ': needs unit, rationale and next validation step')
        if item.get('basis') not in ('source', 'author_scenario'):
            errors.append(identity + ': basis must be source/author_scenario, never implied observation')
        refs = item.get('evidence_ids')
        if not isinstance(refs, list) or any(not text(e) or e not in base['evidence_ids'] for e in refs):
            errors.append(identity + ': evidence_ids must reference baseline evidence')
        elif item.get('basis') == 'source' and not refs:
            errors.append(identity + ': source input needs evidence_ids')
    metrics = review.get('metrics')
    if not isinstance(metrics, list): return errors + ['Forecast needs metric results']
    required = {m['metric_id']: m for m in requirement['metrics']}
    seen = set()
    for row in metrics:
        if not isinstance(row, dict): errors.append('Forecast metric result must be an object'); continue
        mid = row.get('metric_id')
        if not text(mid) or mid not in required or mid in seen:
            errors.append('Forecast must cover every requested metric exactly once'); continue
        seen.add(mid); metric = required[mid]
        if not all(text(row.get(k)) for k in ('action', 'limits')):
            errors.append(mid + ': explain the team action and inference limits')
        values = {**inputs, **{k:metric[k] for k in ('baseline', 'target') if metric[k] is not None}}
        outcomes = {}
        for scenario in ('main', 'adverse'):
            result = row.get(scenario)
            if not isinstance(result, dict): errors.append(mid + ': needs both numeric scenarios'); continue
            try:
                value = number(result.get('value')); computed = calculate(result.get('formula'), values)
                if abs(value - computed) > max(Decimal('1e-8'), abs(computed) * Decimal('1e-8')):
                    errors.append(mid + ': stated ' + scenario + ' value differs from its formula')
                outcomes[scenario] = value
            except ValueError as error: errors.append(mid + ': ' + scenario + ': ' + str(error))
        if len(outcomes) == 2:
            difference = outcomes['adverse'] - outcomes['main']
            if (metric['direction'] == 'higher' and difference > 0) or (metric['direction'] == 'lower' and difference < 0):
                errors.append(mid + ': adverse outcome is more favourable; revise the scenario or label')
    if seen != set(required): errors.append('Forecast missing required metrics: ' + ', '.join(sorted(set(required) - seen)))
    return errors


def validate_fields(project):
    errors = []
    requirement = project.get('forecast_requirements')
    if requirement is not None: errors.extend(requirement_errors(requirement))
    reviews = project.get(FIELD, [])
    if not isinstance(reviews, list): return errors + ['numeric_forecast_reviews must be an array']
    ids = set()
    for review in reviews:
        errors.extend(review_errors(project, review))
        identity = review.get('review_id') if isinstance(review, dict) else None
        if text(identity):
            if identity in ids: errors.append('Numeric forecast review_id must be unique')
            ids.add(identity)
    return errors


def baseline(project, path, root):
    from stress_test import baseline as decision_baseline
    return decision_baseline({k:v for k,v in project.items() if k != FIELD}, path, root)


def prepare(project, path, root, review_id, option_id=None):
    requirement = project.get('forecast_requirements')
    errors = requirement_errors(requirement)
    if errors: raise ValueError('; '.join(errors))
    option = option_id or project.get('recommended_option_id')
    if option not in [o['option_id'] for o in project['options']]:
        raise ValueError('Specify the conditional option explicitly; no human choice is inferred')
    return {'schema_version':1, 'review_id':review_id, 'baseline':baseline(project,path,root),
        'requirements':copy.deepcopy(requirement), 'option_id':option, 'reviewer':'', 'conditions':'',
        'limitations':'', 'sensitivity':'', 'assumptions':[],
        'metrics':[{'metric_id':m['metric_id'], 'action':'', 'limits':'',
            'main':{'value':None,'formula':''}, 'adverse':{'value':None,'formula':''}} for m in requirement['metrics']]}


def inspect(project, path, root):
    requirement = project.get('forecast_requirements'); reviews = project.get(FIELD, [])
    if not requirement:
        return {'status':'not_requested', 'blockers':[], 'metrics':[],
            'note':'Запрос прогноза не записан. Это не подтверждает полноту прочтения брифа.'}
    if not reviews:
        return {'status':'not_recorded', 'metrics':[], 'blockers':[
            'Required numeric forecast is not recorded; provide main/adverse values for every requested metric']}
    review = reviews[-1]
    if review['baseline'] != baseline(project,path,root) or review['requirements'] != requirement:
        return {'status':'stale', 'review_id':review['review_id'], 'metrics':[], 'blockers':[
            'Numeric forecast is stale: review changed scope, sources, requirements or resources; preserve the historical version']}
    from quality import support_blockers
    factual = {eid for a in review['assumptions'] if a['basis']=='source' for eid in a['evidence_ids']}
    blockers = support_blockers(project,path,root,factual,'Forecast source input')
    by_id = {e['evidence_id']:e for e in project['evidence']}
    for a in review['assumptions']:
        if a['basis']=='source' and any(by_id[eid]['claim_type'] not in ('source_fact','measured_fact') for eid in a['evidence_ids']):
            blockers.append('Forecast source input cannot be supported by a hypothesis, forecast or association: ' + a['assumption_id'])
    rows = []
    results = {r['metric_id']:r for r in review['metrics']}
    for metric in requirement['metrics']:
        row = results[metric['metric_id']]
        gap = lambda value: None if metric['target'] is None else float(
            (number(metric['target']) - number(value)) * (1 if metric['direction']=='higher' else -1))
        rows.append({**metric, **copy.deepcopy(row), 'main_gap':gap(row['main']['value']),
                     'adverse_gap':gap(row['adverse']['value'])})
    return {'status':'blocked' if blockers else 'review_record_complete', 'review_id':review['review_id'],
        'blockers':sorted(set(blockers)), 'horizon':requirement['horizon'], 'option_id':review['option_id'],
        'conditions':review['conditions'], 'limitations':review['limitations'], 'sensitivity':review['sensitivity'],
        'assumptions':copy.deepcopy(review['assumptions']), 'metrics':rows,
        'note':'Условный авторский прогноз. Проверена запись и арифметика; достоверность предпосылок, причинность, ресурсы и согласие не подтверждены.'}


def markdown(result):
    cell = lambda v: 'не задано' if v is None else str(v).replace('|','\\|').replace('\n',' ')
    lines = ['## Численный условный прогноз', '', 'Статус: ' + result['status']]
    lines.extend('- '+b for b in result['blockers'])
    if not result.get('metrics'): return '\n'.join(lines)+'\n'
    lines += [result['note'], 'Горизонт: '+result['horizon'], 'Условный вариант: '+result['option_id'],
        'Условия исполнения: '+result['conditions'], '',
        '| Показатель / единица | Без изменений | Основной | Неблагоприятный | Цель | Разрыв основного | Разрыв неблагоприятного |',
        '|---|---:|---:|---:|---:|---:|---:|']
    lines[-2:-2] = ['Разрыв учитывает направление цели и дан в единицах показателя; для процентов это процентные пункты. Отрицательный разрыв означает превышение цели, а не потребность в дополнительном эффекте.', '']
    for m in result['metrics']:
        lines.append('| '+' | '.join(cell(v) for v in [m['label']+' / '+m['unit'],m['baseline'],m['main']['value'],m['adverse']['value'],m['target'],m['main_gap'],m['adverse_gap']])+' |')
        lines += ['', '**'+cell(m['label'])+'**: '+m['action'], 'Основание базы/цели: '+m['basis'],
            'Основной расчёт: `'+m['main']['formula']+'`; неблагоприятный: `'+m['adverse']['formula']+'`.',
            'Ограничения: '+m['limits'], '']
    lines += ['### Численные входы и происхождение']
    for a in result['assumptions']:
        lines += ['- '+a['assumption_id']+' = '+cell(a['value'])+' '+a['unit']+' ['+
            ('авторское сценарное допущение' if a['basis']=='author_scenario' else 'данные источника')+']: '+a['rationale'],
            '  Основания: '+(', '.join(a['evidence_ids']) or 'не измерено')+'. Проверить: '+a['validation_step']]
    lines += ['', 'Чувствительность: '+result['sensitivity'], 'Пределы: '+result['limitations']]
    return '\n'.join(lines)+'\n'


def record(project, path, root, review):
    from stress_test import record_review
    return record_review(project,path,root,review,field=FIELD,inspector=inspect,
        action='conditional numeric forecast',tool='scripts/numeric_forecast.py')


def main():
    from checkpoint import ROOT
    from project_tool import load
    from output_guard import check_output
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','record','inspect','report'));parser.add_argument('project',type=Path)
    parser.add_argument('--review-id');parser.add_argument('--option-id');parser.add_argument('--review',type=Path);parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    try:
        path=args.project.resolve();project=load(path)
        if args.command=='prepare':
            if not text(args.review_id):raise ValueError('prepare needs --review-id')
            result=prepare(project,path,ROOT,args.review_id,args.option_id)
        elif args.command=='record':
            if args.review is None or args.out is not None:raise ValueError('record needs --review and rejects --out')
            result=record(project,path,ROOT,json.loads(args.review.read_text(encoding='utf-8-sig')))
        else:result=inspect(project,path,ROOT)
        output=markdown(result) if args.command=='report' else json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
        if args.out:
            check_output(project,path,args.out)
            if args.out.exists():raise ValueError('Output exists; use a new versioned filename')
            args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(output+'\n',encoding='utf-8')
        else:print(output)
        return 1 if args.command in ('inspect','report') and result['blockers'] else 0
    except (OSError,ValueError,KeyError,TypeError) as error:parser.exit(1,'Numeric forecast: '+str(error)+'\n')


if __name__=='__main__':sys.exit(main())
