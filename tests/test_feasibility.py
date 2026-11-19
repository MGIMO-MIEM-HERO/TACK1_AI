import copy
import json
from pathlib import Path
import sys
import unittest

import test_quality_contract as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, write_state
from feasibility import baseline, evaluate, inspect, markdown, prepare, record
from project_tool import audit, report
from quality import state_hash
from start import restore
from validate_project import validate
from stress_test import baseline as strategy_baseline


class FeasibilityTests(unittest.TestCase):
    setUp = fixture.QualityContractTests.setUp
    complete_record = fixture.QualityContractTests.complete_record
    run_cli = fixture.QualityContractTests.run_cli

    def statement(self, status, **kwargs):
        return {'status': status, 'basis': 'Explicit authored fixture, not a real agreement',
                'evidence_ids': ['E1'], **kwargs}

    def assessment(self):
        self.complete_record()
        self.project['chosen_option_id'] = 'O1'
        self.project['commitments'] = [{'owner': 'Fictional role', 'metric': 'scenario count',
                                       'due': '2099-01-02', 'review_trigger': 'Ask the fictional owner'}]
        review = prepare(self.project, self.path, ROOT, 'F1')
        review.update(context='authored_example', reviewer='Unit self-review', limitations='Fiction, not measured efficacy')
        plan = review['assessments'][0]
        plan.update(minimum_scope='A static local form and an error state, no integrations',
                    permission=self.statement('allowed'), scope=self.statement('confirmed'),
                    window=self.statement('confirmed', start='2099-01-01', end='2099-01-02'),
                    work=[{'work_id': 'W1', 'description': 'Form with error handling', 'skill': 'python',
                           'effort': self.statement('estimated', hours=6)},
                          {'work_id': 'W2', 'description': 'Review errors', 'skill': 'python',
                           'effort': self.statement('estimated', hours=2)}],
                    resources=[{'resource_id': 'DEV', 'skills': ['python'],
                                'competence': self.statement('confirmed'),
                                'availability': self.statement('confirmed'),
                                'capacity': self.statement('confirmed', hours=10)}],
                    allocations=[{'work_id': 'W1', 'resource_id': 'DEV', 'hours': 6},
                                 {'work_id': 'W2', 'resource_id': 'DEV', 'hours': 2}],
                    dependencies=[self.statement('satisfied', dependency_id='D1',
                                  description='Static input available', critical=True)],
                    schedule=self.statement('estimated', fit='fits'),
                    next_check='Owner to verify developer capacity and estimate before authorising code; no action in this fixture')
        self.project['feasibility_reviews'] = [review]
        return review, plan

    def refresh(self):
        self.project['feasibility_reviews'][-1]['baseline'] = baseline(self.project, self.path, ROOT)
        self.project['strategy_review']['state_hash'] = state_hash(self.project, self.path, ROOT)

    def result(self):
        self.refresh()
        self.assertEqual(validate(self.project), [])
        return inspect(self.project, self.path, ROOT)

    def test_enough_capacity_is_conditional_and_permission_is_separate(self):
        _, plan = self.assessment(); result = self.result()
        row = result['assessments'][0]
        self.assertEqual(result['status'], 'review_record_complete', result)
        self.assertEqual(row['outcome'], 'feasible')
        self.assertEqual(row['allocated_person_hours'], {'DEV': 8})
        self.assertEqual(len(row['assumptions']), 3)
        self.assertIn('не реальные ресурсы', markdown(self.project, result))
        plan['permission'] = self.statement('unknown')
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')

    def test_known_shortfall_blocks_selected_option_but_does_not_choose_paper(self):
        _, plan = self.assessment()
        plan['resources'][0]['capacity']['hours'] = 4
        result = self.result()
        self.assertEqual(result['assessments'][0]['outcome'], 'infeasible')
        self.assertTrue(result['decision_blockers'])
        self.assertFalse(audit(self.project, self.path, ready=True, quality=True)['ready'])
        self.assertEqual(self.project['recommended_option_id'], 'O1')
        self.assertEqual(self.project['chosen_option_id'], 'O1')

    def test_unknown_effort_is_not_shortfall_or_automatic_paper_choice(self):
        _, plan = self.assessment()
        plan['work'][0]['effort'] = self.statement('unknown', hours=None)
        plan['allocations'][0]['hours'] = 40  # Cannot derive a deficit from an invented allocation.
        result = self.result()
        self.assertEqual(result['assessments'][0]['outcome'], 'unknown')
        self.assertFalse(result['decision_blockers'])
        self.assertTrue(result['questions'])
        self.assertEqual(self.project['recommended_option_id'], 'O1')

    def test_permission_does_not_substitute_for_missing_capacity_or_people(self):
        _, plan = self.assessment(); plan['resources'] = []; plan['allocations'] = []
        row = self.result()['assessments'][0]
        self.assertEqual(row['permission'], 'allowed')
        self.assertEqual(row['outcome'], 'unknown')
        self.assertIn('исполнители', ' '.join(row['unknowns']))

    def test_available_person_without_confirmed_hours_is_unknown(self):
        _, plan = self.assessment()
        plan['resources'][0]['capacity'] = self.statement('estimated', hours=10)
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')
        plan['resources'][0]['capacity'] = self.statement('unknown', hours=None)
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')

    def test_total_capacity_cannot_hide_a_single_person_overload(self):
        _, plan = self.assessment()
        plan['resources'][0]['capacity']['hours'] = 4
        other = copy.deepcopy(plan['resources'][0]); other['resource_id'] = 'OTHER'; other['capacity']['hours'] = 20
        plan['resources'].append(other)
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'infeasible')

    def test_effort_hours_are_not_calendar_days_and_dependencies_are_separate(self):
        _, plan = self.assessment()
        plan['schedule'] = self.statement('unknown', fit='unknown')
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')
        plan['schedule'] = self.statement('confirmed', fit='does_not_fit')
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'infeasible')
        plan['schedule'] = self.statement('estimated', fit='fits')
        plan['dependencies'][0]['status'] = 'unknown'
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')
        plan['dependencies'][0]['status'] = 'blocked'
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'infeasible')

    def test_skill_coverage_and_unavailability_are_not_implicit(self):
        _, plan = self.assessment()
        plan['resources'][0]['skills'] = ['design']
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')
        plan['resources'][0]['availability'] = self.statement('unavailable')
        plan['resources'][0]['capacity'] = self.statement('confirmed', hours=0)
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'infeasible')

    def test_expired_window_cannot_remain_feasible(self):
        _, plan = self.assessment(); plan['window'].update(start='2020-01-01', end='2020-01-02')
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')

    def test_no_unrealistic_hours_inside_short_window(self):
        _, plan = self.assessment(); plan['resources'][0]['capacity']['hours'] = 80
        self.assertEqual(self.result()['assessments'][0]['outcome'], 'unknown')

    def test_live_resources_need_actual_evidence_not_document_description(self):
        review, _ = self.assessment(); review['context'] = 'live_project'
        self.assertEqual(self.result()['status'], 'blocked')
        self.project['evidence'][0]['claim_scope'] = 'owner_input'
        self.assertEqual(self.result()['status'], 'review_record_complete')
        self.project['sources'][0]['evidence_scope'] = 'simulation'
        self.assertEqual(self.result()['status'], 'blocked')

    def test_hypothesis_cannot_confirm_resources_even_in_authored_example(self):
        _, plan = self.assessment(); plan['resources'][0]['availability']['evidence_ids'] = ['E2']
        self.assertEqual(self.result()['status'], 'blocked')

    def test_stale_support_and_source_edits_invalidate_assessment(self):
        self.assessment(); self.refresh()
        (self.root / 'source.md').write_text('Changed resource agreement', encoding='utf-8')
        self.assertEqual(inspect(self.project, self.path, ROOT)['status'], 'stale')
        self.refresh()
        self.project['evidence'][0]['status'] = 'stale'
        self.assertEqual(self.result()['status'], 'blocked')

    def test_unassessed_alternative_remains_unknown(self):
        self.assessment(); self.project['recommended_option_id'] = 'O0'
        result = self.result()
        self.assertEqual(next(x for x in result['assessments'] if x['option_id'] == 'O0')['outcome'], 'unknown')

    def test_resource_plan_changes_invalidate_other_reviews_without_a_hash_cycle(self):
        review, plan = self.assessment(); self.refresh()
        own = baseline(self.project, self.path, ROOT)
        previous = strategy_baseline(self.project, self.path, ROOT)
        review['recorded_at'] = '2026-11-19T00:00:00+00:00'
        self.assertEqual(previous, strategy_baseline(self.project, self.path, ROOT))
        plan['resources'][0]['capacity']['hours'] = 4
        self.assertNotEqual(previous, strategy_baseline(self.project, self.path, ROOT))
        self.assertEqual(own, baseline(self.project, self.path, ROOT))

    def test_old_projects_still_open_without_assuming_feasibility(self):
        self.complete_record(); write_state(self.path, self.project)
        state = restore(self.path)
        self.assertEqual(state['feasibility']['status'], 'not_recorded')
        self.assertTrue(state['audit']['ready'])

    def test_prepare_does_not_invent_scope_hours_or_agreement(self):
        self.complete_record(); before = copy.deepcopy(self.project)
        review = prepare(self.project, self.path, ROOT, 'F1')
        plan = review['assessments'][0]
        self.assertEqual(plan['permission']['status'], 'unknown')
        self.assertIsNone(plan['work'][0]['effort']['hours'])
        self.assertFalse(plan['resources'])
        self.assertEqual(self.project, before)
        with self.assertRaises(ValueError): prepare(self.project, self.path, ROOT, 'BAD', ['MISSING'])

    def test_malformed_fields_are_validation_errors_not_tracebacks(self):
        self.assessment(); self.refresh(); original = copy.deepcopy(self.project)
        changes = [
            lambda r:r.update(assessments=[None]),
            lambda r:r.update(schema_version=True),
            lambda r:r['assessments'][0].update(window={}),
            lambda r:r['assessments'][0]['work'][0].update(effort={}),
            lambda r:r['assessments'][0]['work'][0]['effort'].update(hours=True),
            lambda r:r['assessments'][0]['work'][0]['effort'].update(hours=float('nan')),
            lambda r:r['assessments'][0]['work'][0]['effort'].update(status='unknown', hours=0),
            lambda r:r['assessments'][0]['work'][0]['effort'].update(evidence_ids=[]),
            lambda r:r['assessments'][0]['resources'][0].update(capacity={}),
            lambda r:r['assessments'][0]['allocations'].append({'work_id':'BAD','resource_id':'DEV','hours':1}),
            lambda r:r['assessments'][0]['allocations'].append(copy.deepcopy(r['assessments'][0]['allocations'][0])),
            lambda r:r['assessments'][0]['permission'].update(evidence_ids=['FAKE']),
        ]
        for change in changes:
            p = copy.deepcopy(original); change(p['feasibility_reviews'][0])
            with self.subTest(change=change): self.assertTrue(validate(p))

    def test_record_reopen_history_and_no_automatic_choice_or_obligation(self):
        review, _ = self.assessment(); del self.project['feasibility_reviews']
        review['baseline'] = baseline(self.project, self.path, ROOT)
        write_state(self.path, self.project)
        original = copy.deepcopy(self.project)
        record(self.project, self.path, ROOT, review)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        with self.assertRaises(ValueError): record(self.project, self.path, ROOT, review)
        with self.assertRaises(ValueError): record(saved, self.path, ROOT, review)
        before = self.path.read_bytes(); log = (self.root / 'ledger.jsonl').read_bytes()
        for _ in range(2):
            self.assertEqual(restore(self.path)['feasibility']['assessments'][0]['outcome'], 'feasible')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.root / 'ledger.jsonl').read_bytes(), log)
        for key in ('chosen_option_id', 'recommended_option_id', 'next_action'):
            self.assertEqual(saved[key], original[key])
        self.assertEqual(saved['commitments'], original['commitments'])
        review2 = copy.deepcopy(review); review2['review_id'] = 'F2'
        review2['assessments'][0]['work'][0]['effort']['hours'] = None
        review2['assessments'][0]['work'][0]['effort']['status'] = 'unknown'
        record(saved, self.path, ROOT, review2)
        self.assertEqual(len(json.loads(self.path.read_text(encoding='utf-8'))['feasibility_reviews']), 2)

    def test_cli_and_reports_expose_feasibility_separately(self):
        self.assessment(); self.refresh(); write_state(self.path, self.project)
        state = json.loads(self.run_cli('checkpoint.py', self.path, 'resume').stdout)
        self.assertEqual(state['feasibility']['assessments'][0]['outcome'], 'feasible')
        self.assertIn('Осуществимость', self.run_cli('start.py', self.path).stdout)
        self.assertIn('Отдельная проверка осуществимости', report(self.project, self.path))
        prepared = json.loads(self.run_cli('feasibility.py', 'prepare', self.path, '--review-id', 'F2').stdout)
        self.assertEqual(prepared['review_id'], 'F2')
        self.assertIn('не реальные ресурсы', self.run_cli('feasibility.py', 'report', self.path).stdout)


if __name__ == '__main__': unittest.main()
