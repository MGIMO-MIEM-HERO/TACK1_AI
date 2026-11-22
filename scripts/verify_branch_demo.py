#!/usr/bin/env python3
"""Authored new-data walkthrough of existing research branches and feasibility."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from checkpoint import ROOT, write_state
from feasibility import baseline as feasibility_baseline, record as record_feasibility
from project_tool import audit, load, report
from quality import state_hash
from research_selection import baseline, inspect, record
from start import restore


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        case = Path(directory) / 'case'
        shutil.copytree(ROOT / 'examples/research-branches-case', case)
        path = case / 'project.json'; project = load(path); original = copy.deepcopy(project)
        sequence = []

        def check(expected):
            before = path.read_bytes(); log = (case / 'ledger.jsonl').read_bytes()
            a = restore(path)['research_selection']; b = restore(path)['research_selection']
            assert a == b and path.read_bytes() == before and (case / 'ledger.jsonl').read_bytes() == log
            resolution = a['branch_resolutions'][0]
            assert a['status'] == 'review_record_complete' and resolution['branch_id'] == expected, a
            sequence.append({'branch': expected, 'status': resolution['status'], 'reason': resolution['reason']})
            assert project['chosen_option_id'] == original['chosen_option_id'] is None
            assert project.get('commitments') == original.get('commitments')

        check('UNKNOWN')
        assert audit(project, path, ready=True, quality=True)['structural_ready']
        for index, capacity, expected in ((1, 10, 'PROTOTYPE'), (2, 4, 'PAPER')):
            passage = ('Авторское новое условие ' + str(index) + ': DEV доступен на ' + str(capacity) +
                       ' человеко-часов. Оценка W1 — 6, W2 — 2 человеко-часа. Окно и зависимости прежние; бумага отдельно допускается по F_B. '
                       'Это вымышленный сценарий, не реальные ресурсы команды.')
            (case / 'inputs/active-condition.md').write_text(passage + '\n', encoding='utf-8')
            assert inspect(project, path, ROOT)['status'] == 'stale'
            try: report(project, path, final=True)
            except ValueError: pass
            else: raise AssertionError('Changed source exported without reassessment')
            for e in project['evidence']:
                if e['evidence_id'].startswith('ACTIVE_'): e['status'] = 'stale'
            eid = 'ACTIVE_' + str(index)
            evidence = copy.deepcopy(original['evidence'][-1])
            evidence.update(evidence_id=eid, claim=passage, status='provisional')
            evidence['support'][0]['passage'] = passage
            project['evidence'].append(evidence)
            option = next(o for o in project['options'] if o['option_id'] == 'O1')
            option['evidence_ids'] = [e for e in option['evidence_ids'] if not e.startswith('ACTIVE_')] + [eid]
            # This is explicit authored reassessment, not execution by the resolver.
            project['next_action'] = 'Показать владельцу условный ' + expected + ' и допущения; решение человека не записано.'
            write_state(path, project)
            done = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/checkpoint.py'), str(path), 'save',
                                   '--summary', 'Прочитано новое авторское условие ' + str(index), '--reviewed-changes'],
                                  capture_output=True, text=True, encoding='utf-8')
            assert done.returncode == 0, done.stdout + done.stderr
            project = load(path)
            feasibility = copy.deepcopy(project['feasibility_reviews'][-1]); feasibility.pop('recorded_at', None)
            feasibility.update(review_id='F-' + str(index), baseline=feasibility_baseline(project, path, ROOT),
                               limitations='Новое вымышленное условие ' + str(index) + ', не ресурсы команды')
            plan = feasibility['assessments'][0]
            for task, hours in zip(plan['work'], (6, 2)):
                task['effort'].update(status='estimated', hours=hours, evidence_ids=[eid], basis=passage)
            plan['resources'][0]['capacity'].update(hours=capacity, evidence_ids=[eid], basis=passage)
            plan['allocations'] = [{'work_id': 'W1', 'resource_id': 'DEV', 'hours': 6}, {'work_id': 'W2', 'resource_id': 'DEV', 'hours': 2}]
            plan['next_check'] = 'Проверить допущения и получить выбор владельца; условный расчёт не является разрешением на код.'
            record_feasibility(project, path, ROOT, feasibility); project = load(path)
            assert inspect(project, path, ROOT)['status'] == 'stale'
            review = copy.deepcopy(project['research_selection_reviews'][-1]); review.pop('recorded_at', None)
            review.update(review_id='R-' + str(index), baseline=baseline(project, path, ROOT),
                          comparison_rationale='Ресурсный вопрос повторно проверен по новому условию; дополнительных исследований для этой узкой развилки сейчас не нужно')
            gap = review['gaps'][0]
            gap.update(status='answered', answer='Текущее авторское условие различает ресурсные варианты; предлагаемая ветка ' + expected,
                       evidence_ids=[eid, 'F_B'], priority='defer', selected_method_id=None,
                       priority_rationale='Ответ о ресурсном плане получен, но это не выбор владельца и не подтверждение пользы')
            review['recommendation'].update(action='stop', question_id=None, method_id=None,
                rationale='Остановить только сбор для этой ресурсной развилки; показать условный вывод владельцу')
            review['stop_rule'].update(status='stop', evidence_ids=[eid, 'F_B'],
                rationale='Новый файл и отдельная проверка бумаги различают варианты в рамках авторского условия')
            record(project, path, ROOT, review); project = load(path)
            project['strategy_review']['state_hash'] = state_hash(project, path, ROOT); write_state(path, project)
            check(expected)
            assert audit(project, path, ready=True, quality=True)['structural_ready'] == (expected == 'PROTOTYPE')
            assert not audit(project, path, ready=True, quality=True)['final_ready']
        assert project['research_selection_reviews'][0] == original['research_selection_reviews'][0]
        assert project['feasibility_reviews'][0] == original['feasibility_reviews'][0]
        assert len(project['research_selection_reviews']) == len(project['feasibility_reviews']) == 3
        assert project['recommended_option_id'] == original['recommended_option_id']
        assert len(project['checkpoints']) == len(original['checkpoints']) + 2
        return {'passed': True, 'context': 'authored_example; fictional resources and dates', 'sequence': sequence,
                'versions_preserved': True, 'source_changes_invalidate_old_branches': True,
                'automatic_human_choice_or_obligation': False, 'repeat_open_writes': False,
                'scope': 'Deterministic new-data contract test, not a live LLM benchmark or business result'}


if __name__ == '__main__':
    print(json.dumps(verify_demo(), ensure_ascii=False, indent=2))
