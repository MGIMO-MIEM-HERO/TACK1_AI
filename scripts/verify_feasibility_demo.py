#!/usr/bin/env python3
"""Run three explicitly authored resource scenarios; no model, users or network."""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from checkpoint import ROOT, write_state
from feasibility import baseline, inspect, record
from project_tool import audit, load, report
from quality import state_hash
from start import restore


def verify_demo():
    outcomes = {}
    with tempfile.TemporaryDirectory() as tmp:
        for scenario in ('enough', 'unknown', 'shortfall'):
            case = Path(tmp) / scenario
            shutil.copytree(ROOT / 'examples/feasibility-case', case)
            path = case / 'project.json'; project = load(path)
            original = copy.deepcopy(project)
            if scenario != 'enough':
                review = copy.deepcopy(project['feasibility_reviews'][-1])
                review.pop('recorded_at', None)
                review['review_id'] = 'F-' + scenario
                review['limitations'] = 'Отдельное авторское условие ' + scenario + ', не новое фактическое наблюдение или решение человека'
                review['baseline'] = baseline(project, path, ROOT)
                plan = review['assessments'][0]
                if scenario == 'unknown':
                    plan['work'][0]['effort'].update(status='unknown', hours=None,
                        basis='В независимом авторском сценарии неизвестного объёма оценки W1 нет.')
                    plan['allocations'] = [a for a in plan['allocations'] if a['work_id'] != 'W1']
                    plan['next_check'] = 'Получить оценку W1 по минимальной декомпозиции и затем сопоставить её с подтверждённой ёмкостью.'
                else:
                    plan['resources'][0]['capacity'].update(hours=4,
                        basis='В независимом авторском дефицитном сценарии DEV имеет только 4 человеко-часа, см. F_T.')
                    plan['next_check'] = 'Показать владельцу дефицит плана O1; отдельно проверенный O2 укладывается в авторские условия, но выбор не менять.'
                record(project, path, ROOT, review)
                project = load(path)
                project['strategy_review']['state_hash'] = state_hash(project, path, ROOT)
                write_state(path, project)
            before = path.read_bytes(); log = (case / 'ledger.jsonl').read_bytes()
            first = restore(path)['feasibility']; second = restore(path)['feasibility']
            assert first == second and path.read_bytes() == before and (case / 'ledger.jsonl').read_bytes() == log
            rows = {row['option_id']: row for row in first['assessments']}
            expected = {'enough': 'feasible', 'unknown': 'unknown', 'shortfall': 'infeasible'}[scenario]
            assert first['status'] == 'review_record_complete' and rows['O1']['outcome'] == expected, first
            assert rows['O2']['outcome'] == 'feasible', first
            assert project['chosen_option_id'] is None and project['recommended_option_id'] == original['recommended_option_id']
            assert project.get('commitments') == original.get('commitments') and project['next_action'] == original['next_action']
            result = audit(project, path, ready=True, quality=True)
            assert result['ready'] == (scenario != 'shortfall'), result
            if scenario == 'shortfall':
                try: report(project, path, final=True)
                except ValueError: pass
                else: raise AssertionError('Final export must not silently approve an infeasible selected plan')
            else:
                assert 'Отдельная проверка осуществимости' in report(project, path, final=True)
            outcomes[scenario] = {'prototype': rows['O1']['outcome'], 'paper': rows['O2']['outcome'],
                                  'ready': result['ready'], 'choice_written': False,
                                  'repeat_open_writes': False, 'review_versions': len(project['feasibility_reviews'])}
        # Source changes invalidate the check, without rewriting history or inventing a new resource fact.
        source = case / 'inputs/brief.md'; source.write_text(source.read_text(encoding='utf-8') + '\nАвторское условие изменено.\n', encoding='utf-8')
        assert inspect(project, path, ROOT)['status'] == 'stale'
    return {'passed': True, 'context': 'authored_example; all people, capacity and dates are fictional',
            'scenarios': outcomes, 'source_change_requires_new_review': True,
            'scope': 'Deterministic contract test, not a live agent benchmark or measured business effect'}


if __name__ == '__main__':
    print(json.dumps(verify_demo(), ensure_ascii=False, indent=2))
