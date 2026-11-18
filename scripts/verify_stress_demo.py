#!/usr/bin/env python3
"""Reproduce the authored scenario comparison and revision in an isolated copy."""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from checkpoint import ROOT, write_state
from project_tool import load, report
from stress_test import baseline, inspect, record


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'case'
        shutil.copytree(ROOT / 'examples/decision-stress-case', target)
        path = target / 'project.json'
        project = load(path)
        initial = inspect(project, path, ROOT)
        assert initial['status'] == 'review_record_complete', initial
        assert [s['conditional_recommendation']['outcome'] for s in initial['scenarios']] == ['switch', 'keep', 'insufficient_evidence']
        original = copy.deepcopy(project)
        # Materialise ONE adverse constraint in this authored test only. No API,
        # scheduler or tool claims to have made the resource change in real life.
        project['constraints'][0] = 'Разработчик недоступен'
        write_state(path, project)
        stale = inspect(project, path, ROOT)
        assert stale['status'] == 'stale', stale
        assert set(stale['impact']['option_ids']) >= {'O1', 'O2'}, stale
        try:
            report(project, path, final=True)
        except ValueError:
            pass
        else:
            raise AssertionError('Final export did not block the stale review')
        assert project['recommended_option_id'] == 'O1', 'The tool must not automatically switch recommendations'
        # Authored reassessment, not an LLM benchmark or an automatic optimiser:
        # E1 explicitly permits a paper check without the unavailable developer.
        project['recommended_option_id'] = 'O2'
        project['recommendation_rationale'] = ('В изменённом учебном условии разработчик недоступен. '
            'По E1 бумажная проверка не требует кода, поэтому рекомендуем O2 вместо O1. '
            'Применимость к реальному проекту и решение владельца ещё не подтверждены.')
        project['product_strategy']['direction'] = 'Подготовить бумажную проверку без разработки; выпуск не обещается'
        project['communication_strategy']['message'] = 'Бумажный учебный сценарий для проверки, а не работающий сервис'
        write_state(path, project)
        revised = copy.deepcopy(original['decision_stress_tests'][-1])
        revised.pop('recorded_at', None)
        revised['review_id'] = 'R2'
        revised['baseline'] = baseline(project, path, ROOT)
        revised['strongest_objection'] = 'Бумажная проверка не обнаружит ошибки интеграции; результаты пока отсутствуют.'
        revised['reversal_condition'] = 'После подтверждения ресурса и оценки разработки повторно сравнить O1 и O2.'
        # New review of the available choices under the changed baseline.
        for scenario in revised['scenarios'][:2]:
            scenario['constraint_changes'] = []
            scenario['premise'] = ('Гипотетически отсутствие разработчика сохраняется; '
                                   'для второго сценария дополнительно задержана интеграция.')
            scenario['recommendation'].update(outcome='keep', option_id='O2', evidence_ids=['E1'],
                rationale='E1 допускает бумажную проверку без кода; при недоступном разработчике и без новых возражений сохраняем O2.')
            for impact in scenario['option_impacts']:
                oid = impact['option_id']
                impact.update(feasibility='infeasible' if oid == 'O1' else 'feasible',
                    preference='preferred' if oid == 'O2' else 'not_preferred', evidence_ids=['E1'],
                    reason={'O0':'Не даёт новой проверки, хотя не требует ресурсов.',
                            'O1':'Для прототипа нет доступного разработчика в изменённом условии.',
                            'O2':'По E1 бумажная проверка не требует кода; ресурсное ограничение не мешает ей.',
                            'O3':'Полная остановка преждевременна при доступной обратимой бумажной проверке.'}[oid])
        saved = record(project, path, ROOT, revised)
        assert saved['status'] == 'review_record_complete', saved
        after = load(path)
        assert after['recommended_option_id'] == 'O2'
        assert after['chosen_option_id'] is None and after['commitments'] == []
        assert after['decision_stress_tests'][0] == original['decision_stress_tests'][0], 'Historical review was rewritten'
        from quality import state_hash
        after['strategy_review'].update(strongest_objection=revised['strongest_objection'],
            reversal_condition=revised['reversal_condition'])
        after['strategy_review']['state_hash'] = state_hash(after, path, ROOT)
        write_state(path, after)
        final = report(after, path, final=True)
        assert 'O2' in final and 'R2' in final
        return {'passed': True, 'initial_recommendation': 'O1',
                'scenario_outcomes': ['switch to O2', 'keep O1', 'insufficient_evidence'],
                'changed_constraint': 'Разработчик недоступен', 'old_review_status': stale['status'],
                'affected_options': stale['impact']['option_ids'], 'revised_recommendation': 'O2',
                'human_choice': None, 'review_versions_preserved': 2,
                'scope': 'Authored scenario and explicit reassessment; deterministic verification, not an LLM benchmark or measured business effect'}


if __name__ == '__main__':
    print(json.dumps(verify_demo(), ensure_ascii=False, indent=2))
