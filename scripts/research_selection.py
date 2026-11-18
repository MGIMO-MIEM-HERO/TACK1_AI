#!/usr/bin/env python3
"""Versioned, qualitative selection of decision-changing research. No invented scores."""
import argparse
import copy
import json
from pathlib import Path
import re
import sys

from stress_test import nonempty, strings, baseline as decision_baseline, record_review


def validate_fields(project):
    reviews = project.get('research_selection_reviews', [])
    if not isinstance(reviews, list):
        return ['research_selection_reviews must be an array']
    if not reviews:
        return []  # Keep legacy question formats readable until explicitly migrated.
    errors = []
    def questions(items):
        result = {}
        if not isinstance(items, list):
            errors.append('research_questions must be an array')
            return result
        for q in items:
            if not isinstance(q, dict) or not all(nonempty(q.get(k)) for k in ('question_id', 'question', 'could_change')):
                errors.append('Research selection needs question_id/question/could_change on every existing question')
            elif q['question_id'] in result:
                errors.append('Duplicate research question_id')
            else:
                result[q['question_id']] = q
        return result
    questions(project.get('research_questions', []))
    review_ids = set()
    for review in reviews:
        if not isinstance(review, dict):
            errors.append('Research selection review must be an object')
            continue
        rid = review.get('review_id')
        if not nonempty(rid) or rid in review_ids:
            errors.append('Research review_id must be unique text')
        if nonempty(rid): review_ids.add(rid)
        if type(review.get('schema_version')) is not int or review['schema_version'] != 1:
            errors.append('Research schema_version must be 1')
        for key in ('reviewer', 'limitations', 'comparison_rationale'):
            if not nonempty(review.get(key)): errors.append('Research review needs ' + key)
        base = review.get('baseline')
        if not isinstance(base, dict):
            errors.append('Research review needs a prepared baseline')
            continue
        if base.get('project_id') != project.get('project_id') or not isinstance(base.get('state_hash'), str) or not re.fullmatch('[0-9a-f]{64}', base['state_hash']):
            errors.append('Research baseline project/hash invalid')
        qs = questions(base.get('questions'))
        namespaces = {}
        for key in ('option_ids', 'evidence_ids', 'source_ids'):
            if not strings(base.get(key)):
                errors.append('Research baseline needs ' + key)
                namespaces[key] = set()
            else: namespaces[key] = set(base[key])
        def refs(obj, key, allowed, required=False):
            value = obj.get(key)
            if not strings(value) or len(value) != len(set(value)) or (required and not value):
                errors.append(key + ' needs distinct IDs' + (' (nonempty)' if required else ''))
            elif not set(value) <= set(allowed): errors.append(key + ' references unknown baseline IDs')
        gaps = review.get('gaps')
        if not isinstance(gaps, list):
            errors.append('Research review needs gaps for all existing questions')
            gaps = []
        seen = set()
        for gap in gaps:
            if not isinstance(gap, dict):
                errors.append('Research gap must be an object');continue
            qid = gap.get('question_id')
            if not nonempty(qid) or qid not in qs or qid in seen: errors.append('Gap question_id must be distinct and registered')
            if nonempty(qid): seen.add(qid)
            for key in ('decision_dependency', 'why_changes_decision', 'priority_rationale', 'method_choice_rationale'):
                if not nonempty(gap.get(key)): errors.append('Gap needs ' + key)
            if gap.get('status') not in ('open', 'answered'): errors.append('Gap status must be open/answered')
            if gap.get('impact') not in ('feasibility', 'preference', 'context'): errors.append('Gap impact must be feasibility/preference/context')
            if gap.get('priority') not in ('critical', 'high', 'defer', 'undetermined'): errors.append('Use qualitative critical/high/defer/undetermined priority')
            if gap.get('priority') == 'critical' and gap.get('impact') != 'feasibility': errors.append('Critical priority is a decision feasibility gate')
            if gap.get('status') == 'answered' and (not nonempty(gap.get('answer')) or gap.get('priority') != 'defer'):
                errors.append('Answered questions need an answer and must be deferred from new research')
            refs(gap, 'evidence_ids', namespaces['evidence_ids'], gap.get('status') == 'answered')
            refs(gap, 'option_ids', namespaces['option_ids'], bool(namespaces['option_ids']))
            branches = gap.get('answer_branches')
            if not isinstance(branches, list) or (gap.get('impact') != 'context' and len(branches) < 2):
                errors.append('Decision-changing gaps need at least two answer branches');branches = []
            answers = set()
            for branch in branches:
                if not isinstance(branch, dict) or not all(nonempty(branch.get(k)) for k in ('answer', 'consequence')):
                    errors.append('Answer branch needs answer/consequence');continue
                if branch['answer'] in answers: errors.append('Answer branches must be distinct')
                answers.add(branch['answer'])
                refs(branch, 'option_ids', namespaces['option_ids'], bool(namespaces['option_ids']))
            if gap.get('impact') != 'context' and len({b['consequence'] for b in branches if isinstance(b,dict) and nonempty(b.get('consequence'))}) < 2:
                errors.append('A decision-changing question needs distinct consequences, not duplicate answer branches')
            methods = gap.get('methods')
            if not isinstance(methods, list) or not methods: errors.append('Gap needs at least one sufficient-method candidate');methods = []
            mids = set()
            for method in methods:
                if not isinstance(method, dict): errors.append('Method must be an object');continue
                mid = method.get('method_id')
                if not nonempty(mid) or mid in mids: errors.append('Method IDs must be distinct per question')
                if nonempty(mid): mids.add(mid)
                for key in ('description', 'adequacy_rationale'):
                    if not nonempty(method.get(key)): errors.append('Method needs ' + key)
                if method.get('access') not in ('available', 'unavailable', 'unknown'): errors.append('Method access must be available/unavailable/unknown')
                if method.get('adequacy') not in ('sufficient', 'insufficient', 'unknown'): errors.append('Method adequacy must be sufficient/insufficient/unknown')
                refs(method, 'source_ids', namespaces['source_ids'])
                effort = method.get('effort')
                if not isinstance(effort, dict): errors.append('Method needs explicit effort');continue
                if set(effort) != {'time','resources'}: errors.append('Effort must contain only time and resources')
                for key in ('time', 'resources'):
                    cost = effort.get(key)
                    if not isinstance(cost, dict): errors.append('Effort needs time/resources objects');continue
                    if cost.get('status') not in ('unknown', 'estimated', 'observed'): errors.append('Effort status must be unknown/estimated/observed')
                    if cost.get('status') == 'unknown':
                        if cost.get('value') is not None or cost.get('basis') is not None: errors.append('Unknown effort is null, not zero or a fabricated estimate')
                    elif not nonempty(cost.get('value')) or not nonempty(cost.get('basis')): errors.append('Known/estimated effort needs value, units/resources and basis')
                    refs(cost, 'evidence_ids', namespaces['evidence_ids'], cost.get('status') == 'observed')
            selected = gap.get('selected_method_id')
            if selected is not None and (not nonempty(selected) or selected not in mids): errors.append('selected_method_id must reference a method or be null')
        if seen != set(qs) or not qs: errors.append('Research review must cover all existing questions exactly once')
        choice, stop = review.get('recommendation'), review.get('stop_rule')
        if not isinstance(choice, dict) or not isinstance(stop, dict): errors.append('Research review needs recommendation and stop_rule');continue
        if choice.get('action') not in ('investigate', 'clarify', 'stop'): errors.append('Next action must be investigate/clarify/stop')
        if not nonempty(choice.get('rationale')): errors.append('Next action needs a comparative rationale')
        if stop.get('status') not in ('continue', 'stop', 'uncertain'): errors.append('Stopping assessment must be continue/stop/uncertain')
        for key in ('condition', 'rationale', 'remaining_limits'):
            if not nonempty(stop.get(key)): errors.append('Stop rule needs ' + key)
        refs(stop, 'evidence_ids', namespaces['evidence_ids'], stop.get('status') == 'stop')
        if choice.get('action') == 'stop':
            if choice.get('question_id') is not None or choice.get('method_id') is not None or stop.get('status') != 'stop': errors.append('stop has no next question/method and needs a justified stopping assessment')
        elif not nonempty(choice.get('question_id')) or choice['question_id'] not in qs:
            errors.append('Next research must reference an existing question')
        if (stop.get('status') == 'uncertain') != (choice.get('action') == 'clarify'):
            errors.append('Uncertain stopping assessment requires clarify, without pretending the ranking is known')
        if choice.get('action') == 'investigate' and stop.get('status') != 'continue': errors.append('Investigation requires continue, not a claim that research is finished')
    return errors


def baseline(project, path, root):
    return {**decision_baseline(project, path, root), 'questions': copy.deepcopy(project.get('research_questions', []))}


def inspect(project, path, root):
    from quality import FACTS, support_blockers
    reviews = project.get('research_selection_reviews', [])
    empty = {'status':'not_recorded', 'blockers':[], 'recommendation':None, 'gaps':[]}
    if not reviews: return empty
    review = reviews[-1]
    if review['baseline'] != baseline(project, path, root):
        return {**empty, 'status':'stale', 'review_id':review['review_id'],
                'blockers':['Next-research selection is stale: questions, constraints, answers, sources or strategy changed; compare priorities again']}
    by_eid = {e['evidence_id']:e for e in project['evidence']}
    used = set(review['stop_rule']['evidence_ids'])
    for gap in review['gaps']:
        used.update(gap['evidence_ids'])
        for method in gap['methods']:
            for cost in method['effort'].values(): used.update(cost['evidence_ids'])
    blockers = support_blockers(project,path,root,used,'Research support')
    critical = [g['question_id'] for g in review['gaps'] if g['status']=='open' and g['priority']=='critical']
    choice, stop = review['recommendation'], review['stop_rule']
    if choice['action']=='stop':
        if any(g['status']=='open' and g['priority'] in ('critical','high','undetermined') and g['impact']!='context' for g in review['gaps']):
            blockers.append('Cannot stop while a decision-changing critical/high/undetermined question is unresolved')
        if not any(by_eid[e]['claim_type'] in FACTS for e in stop['evidence_ids']): blockers.append('Stopping needs factual grounds, not only hypotheses')
    else:
        gap = next(g for g in review['gaps'] if g['question_id']==choice['question_id'])
        if gap['status']!='open': blockers.append('Do not repeat an answered question as new research')
        if critical and gap['question_id'] not in critical: blockers.append('Resolve or clarify a critical feasibility gate before lower-priority research')
        if choice['action']=='investigate':
            if gap['impact']=='context': blockers.append('Context-only research does not distinguish the current decision; defer it or clarify the decision frame')
            if gap['priority'] in ('defer','undetermined'): blockers.append('Cannot investigate a deferred/undetermined priority as the selected next step')
            if choice.get('method_id') != gap['selected_method_id'] or not gap['selected_method_id']:
                blockers.append('Next method must match the explicitly selected sufficient method')
        elif choice.get('method_id') is not None: blockers.append('Clarify must not pretend to launch a method with unknown suitability/access')
    for gap in review['gaps']:
        if gap['status']=='answered' and not any(by_eid[e]['claim_type'] in FACTS for e in gap['evidence_ids']):
            blockers.append(gap['question_id']+': an answer needs factual evidence, not a forecast/model hypothesis')
        for method in gap['methods']:
            if method['method_id']==gap['selected_method_id'] and (method['access']!='available' or method['adequacy']!='sufficient'):
                blockers.append(gap['question_id']+': a selected method must be accessible and sufficient; otherwise clarify')
            if method['method_id']==gap['selected_method_id'] and any(len(review['baseline']['source_content'].get(s,''))!=64 for s in method['source_ids']):
                blockers.append(gap['question_id']+': selected method depends on an unavailable/untracked source')
            for cost in method['effort'].values():
                if cost['status']=='observed' and not any(by_eid[e]['claim_type'] in FACTS for e in cost['evidence_ids']):
                    blockers.append(gap['question_id']+': observed effort needs factual grounds')
    return {'status':'blocked' if blockers else 'review_record_complete','review_id':review['review_id'],
            'blockers':sorted(set(blockers)), 'recommendation':choice, 'stop_rule':stop, 'gaps':review['gaps'],
            'note':'Qualitative recorded reasoning, not an optimiser or monetary value-of-information estimate. No research, human decision or next_action is executed automatically.'}


def prepare(project,path,root,review_id):
    qs=project.get('research_questions',[])
    if not qs or any(not isinstance(q,dict) or not all(nonempty(q.get(k)) for k in ('question_id','question','could_change')) for q in qs):
        raise ValueError('First give existing research_questions stable question_id/question/could_change fields')
    unknown=lambda: {'status':'unknown','value':None,'basis':None,'evidence_ids':[]}
    return {'schema_version':1,'review_id':review_id,'baseline':baseline(project,path,root),'reviewer':'','limitations':'','comparison_rationale':'',
            'gaps':[{'question_id':q['question_id'],'decision_dependency':q['could_change'],'why_changes_decision':'',
                'option_ids':[o['option_id'] for o in project['options']],'status':'open','answer':None,
                'impact':'preference','priority':'undetermined','priority_rationale':'','evidence_ids':[],
                'answer_branches':[],'methods':[{'method_id':'M1','description':'','access':'unknown','adequacy':'unknown',
                    'adequacy_rationale':'','source_ids':[],'effort':{'time':unknown(),'resources':unknown()}}],
                'selected_method_id':None,'method_choice_rationale':''} for q in qs],
            'recommendation':{'action':'clarify','question_id':qs[0]['question_id'],'method_id':None,'rationale':''},
            'stop_rule':{'status':'uncertain','condition':'','rationale':'','evidence_ids':[],'remaining_limits':''}}


def markdown(project,result):
    lines=['## Выбор следующего исследования','','Статус: '+result['status']]
    if not project.get('research_selection_reviews'): return '\n'.join(lines+['Сравнение не записано.'])+'\n'
    r=project['research_selection_reviews'][-1]
    lines+=['Версия: '+r['review_id'],'Автор: '+r['reviewer'],'Ограничения: '+r['limitations'],
            'Проект: '+r['baseline']['project_id'], 'Сравнение пробелов: '+r['comparison_rationale'],
            'Хеш контекста: '+r['baseline']['state_hash']]
    if result['blockers']: lines+=['Требуется пересмотр:',*['- '+b for b in result['blockers']]]
    lines+=['При stale/blocked сохранённые приоритеты ниже нельзя применять как актуальные.']
    qs={q['question_id']:q for q in r['baseline']['questions']}
    for g in r['gaps']:
        lines+=['','### '+g['question_id']+': '+qs[g['question_id']]['question'],
                'Статус вопроса: '+g['status']+'; приоритет: '+g['priority']+' — '+g['priority_rationale'],
                'Зависимое решение: '+g['decision_dependency'],'Варианты: '+(', '.join(g['option_ids']) or 'ещё не формализованы'),
                'Почему ответ меняет действие: '+g['why_changes_decision'],'Ответ: '+str(g['answer']),
                'Основания: '+(', '.join(g['evidence_ids']) or 'не указаны')]
        for b in g['answer_branches']: lines+=['- Если '+b['answer']+' → '+b['consequence']+'; варианты: '+', '.join(b['option_ids'])]
        for m in g['methods']:
            lines+=['Способ '+m['method_id']+': '+m['description']+' ['+m['access']+'; '+m['adequacy']+']',
                    'Достаточность: '+m['adequacy_rationale']]
            for k,cost in m['effort'].items(): lines+=['  '+k+': '+('неизвестно' if cost['status']=='unknown' else str(cost['value'])+' ['+cost['status']+']; '+str(cost['basis']))]
        lines+=['Выбран способ: '+str(g['selected_method_id'])+'; '+g['method_choice_rationale']]
    c,s=r['recommendation'],r['stop_rule']
    lines+=['','### Следующее действие',c['action']+'; вопрос: '+str(c['question_id'])+'; способ: '+str(c['method_id']),
            c['rationale'],'','### Когда остановиться',s['status']+': '+s['condition'],s['rationale'],
            'Основания остановки: '+(', '.join(s['evidence_ids']) or 'не указаны'),'Оставшиеся ограничения: '+s['remaining_limits'],
            'Никаких денежных оценок ценности информации, точных баллов или измеренной экономии этот разбор не вычисляет.']
    return '\n'.join(lines)+'\n'


def record(project,path,root,review):
    return record_review(project,path,root,review,field='research_selection_reviews',inspector=inspect,
                         action='next research selection',tool='scripts/research_selection.py')


def main():
    from checkpoint import ROOT
    from project_tool import load
    from output_guard import check_output
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('prepare','record','inspect','report'))
    p.add_argument('project',type=Path);p.add_argument('--review-id');p.add_argument('--review',type=Path);p.add_argument('--out',type=Path)
    a=p.parse_args()
    try:
        path=a.project.resolve();project=load(path)
        if a.command=='prepare':
            if not a.review_id: raise ValueError('prepare needs --review-id')
            result=prepare(project,path,ROOT,a.review_id)
        elif a.command=='record':
            if not a.review or a.out: raise ValueError('record needs --review and rejects --out')
            result=record(project,path,ROOT,json.loads(a.review.read_text(encoding='utf-8-sig')))
        else: result=inspect(project,path,ROOT)
        output=markdown(project,result) if a.command=='report' else json.dumps(result,ensure_ascii=False,indent=2)
        if a.out:
            check_output(project,path,a.out)
            if a.out.exists(): raise ValueError('Choose a new versioned output filename')
            a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(output.rstrip()+'\n',encoding='utf-8')
        else: print(output)
        return 1 if a.command in ('inspect','report') and result['blockers'] else 0
    except (OSError,ValueError,KeyError,TypeError) as e: p.exit(1,f'Research selection: {e}\n')


if __name__=='__main__':sys.exit(main())
