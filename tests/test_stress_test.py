import copy
import json
from pathlib import Path
import sys
import unittest

import test_quality_contract as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, write_state
from ledger import ledger_path, read_entries, verify
from project_tool import audit, report
from quality import state_hash
from start import restore
from stress_test import baseline, inspect, markdown, prepare, record
from validate_project import validate


class StressTests(unittest.TestCase):
    setUp = fixture.QualityContractTests.setUp
    complete_record = fixture.QualityContractTests.complete_record
    run_cli = fixture.QualityContractTests.run_cli

    def review(self):
        self.complete_record()
        self.project['constraints'] = ['Developer available']
        review = prepare(self.project, self.path, ROOT, 'R1')
        review.update(reviewer='Agent self-review; not independent', limitations='Authored test; no measured effect')
        a = review['assumptions'][0]
        a.update(statement='Developer remains available', basis='hypothesis', option_ids=['O1'],
                 verification_needed='Ask the owner; no invented likelihood')
        for i, s in enumerate(review['scenarios']):
            s.update(title='Unavailable developer' if i == 0 else 'Integration delayed',
                     premise='Hypothetically unavailable' if i == 0 else 'Hypothetical delay; investigation is still possible',
                     new_data_needed='Confirmed resource plan', review_trigger='Owner reports a changed resource plan')
            chosen = 'O0' if i == 0 else 'O1'
            for impact in s['option_impacts']:
                impact.update(feasibility='feasible', preference='preferred' if impact['option_id'] == chosen else 'not_preferred',
                              reason='Explicit conditional comparison; no real result', evidence_ids=['E1'])
            s['recommendation'].update(outcome='switch' if i == 0 else 'keep', option_id=chosen,
                                       rationale='Conditional reasoning about the stated premise', evidence_ids=['E1'])
        self.project['decision_stress_tests'] = [review]
        return review

    def test_switch_and_keep_are_conditional_and_do_not_choose(self):
        self.review()
        original = copy.deepcopy(self.project)
        self.assertEqual(validate(self.project), [])
        result = inspect(self.project, self.path, ROOT)
        self.assertEqual(result['status'], 'review_record_complete', result)
        self.assertEqual([s['conditional_recommendation']['outcome'] for s in result['scenarios']], ['switch', 'keep'])
        self.assertEqual(self.project, original)
        self.assertIsNone(self.project.get('chosen_option_id'))

    def test_constraint_change_invalidates_and_keeps_history(self):
        self.review()
        self.project['constraints'] = ['Developer unavailable']
        result = inspect(self.project, self.path, ROOT)
        self.assertEqual(result['status'], 'stale')
        self.assertIn('constraints', result['context_changes'])
        self.assertEqual(result['scenarios'], [])
        self.assertEqual(len(self.project['decision_stress_tests']), 1)
        self.assertFalse(audit(self.project, self.path, ready=True)['ready'])

    def test_source_content_change_invalidates_even_without_a_checkpoint(self):
        self.review()
        self.project['checkpoints'] = []
        # The baseline hash deliberately excludes checkpoints.
        (self.root / 'source.md').write_text('Different evidence', encoding='utf-8')
        self.assertEqual(inspect(self.project, self.path, ROOT)['status'], 'stale')

    def test_seed_evidence_propagates_transitively_and_tracks_assumptions(self):
        review = self.review()
        review['scenarios'][0]['changed_evidence_ids'] = ['E1']
        result = inspect(self.project, self.path, ROOT)
        impact = result['scenarios'][0]['impact']
        self.assertEqual(impact['evidence_ids'], ['E1', 'E2'])
        self.assertIn('O1', impact['option_ids'])

    def test_scenario_cannot_use_its_own_invalidated_support_to_pick_a_winner(self):
        review = self.review()
        review['scenarios'][0]['changed_source_ids'] = ['S']
        result = inspect(self.project, self.path, ROOT)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('invalidated premise' in e for e in result['blockers']))

    def test_unknown_information_does_not_force_a_winner(self):
        review = self.review()
        s = review['scenarios'][0]
        for impact in s['option_impacts']:
            impact.update(feasibility='uncertain', preference='undetermined')
        s['recommendation'].update(outcome='insufficient_evidence', option_id=None, evidence_ids=[])
        self.assertEqual(validate(self.project), [])
        self.assertEqual(inspect(self.project, self.path, ROOT)['scenarios'][0]['conditional_recommendation']['option_id'], None)

    def test_malformed_and_unknown_references_are_rejected(self):
        review = self.review()
        for mutate in (
                lambda r: r.update(scenarios=None),
                lambda r: r['baseline'].update(recommended_option_id=[]),
                lambda r: r['baseline']['snapshot'].update(constraints=None),
                lambda r: r['scenarios'][0].update(option_impacts=[]),
                lambda r: r['scenarios'][0]['recommendation'].update(evidence_ids=['FAKE']),
                lambda r: r['scenarios'][0]['recommendation'].update(option_id='O1'),
                lambda r: r['assumptions'][0].update(evidence_ids=[{}]),
                lambda r: r['scenarios'][0].update(assumption_ids=['FAKE'])):
            with self.subTest(mutate=mutate):
                self.project['decision_stress_tests'] = [copy.deepcopy(review)]
                mutate(self.project['decision_stress_tests'][0])
                self.assertTrue(validate(self.project))

    def test_impossible_winner_and_unexplained_keep_rejected(self):
        r = self.review()
        s = r['scenarios'][1]
        next(i for i in s['option_impacts'] if i['option_id'] == 'O1')['feasibility'] = 'infeasible'
        s['recommendation']['rationale'] = ''
        errors = validate(self.project)
        self.assertTrue(any('feasible' in e for e in errors))
        self.assertTrue(any('rationale' in e for e in errors))

    def test_hypothesis_alone_cannot_establish_observed_premise_or_switch(self):
        r = self.review()
        s = r['scenarios'][0]
        s.update(premise_status='observed', evidence_ids=['E2'])
        s['recommendation']['evidence_ids'] = ['E2']
        self.assertEqual(inspect(self.project, self.path, ROOT)['status'], 'blocked')

    def test_bad_provenance_blocks_conditional_support(self):
        self.review()
        self.project['evidence'][0]['support'][0]['passage'] = 'Not present'
        self.project['decision_stress_tests'][0]['baseline'] = baseline(self.project, self.path, ROOT)
        result = inspect(self.project, self.path, ROOT)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any('passage' in e for e in result['blockers']))

    def test_stale_evidence_cannot_be_laundered_by_refreshing_baseline(self):
        self.review()
        self.project['evidence'][0]['status'] = 'withdrawn'
        self.project['decision_stress_tests'][0]['baseline'] = baseline(self.project, self.path, ROOT)
        self.assertIn('Stress support is unusable: E1', inspect(self.project, self.path, ROOT)['blockers'])

    def test_record_appends_versions_and_prevents_duplicate_and_stale_writes(self):
        r = self.review()
        self.project.pop('decision_stress_tests')
        write_state(self.path, self.project)
        before = self.path.read_bytes()
        bad = copy.deepcopy(r)
        bad['baseline']['state_hash'] = '0' * 64
        with self.assertRaises(ValueError):
            record(self.project, self.path, ROOT, bad)
        self.assertEqual(self.path.read_bytes(), before)
        record(self.project, self.path, ROOT, r)
        p = json.loads(self.path.read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            record(p, self.path, ROOT, r)
        r2 = copy.deepcopy(r)
        r2['review_id'] = 'R2'
        record(p, self.path, ROOT, r2)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(saved['decision_stress_tests']), 2)
        self.assertIn('recorded_at', saved['decision_stress_tests'][-1])
        self.assertEqual(verify(read_entries(ledger_path(self.path))), [])
        self.assertEqual(saved['recommended_option_id'], 'O1')

    def test_report_and_resume_include_review_without_faking_a_choice(self):
        self.review()
        self.project['strategy_review']['state_hash'] = state_hash(self.project, self.path, ROOT)
        write_state(self.path, self.project)
        text = report(self.project, self.path, final=True)
        self.assertIn('Проверка решения на прочность', text)
        self.assertIn('SC1', text)
        self.assertIn('hypothetical', text)
        self.assertEqual(restore(self.path)['decision_stress_test']['status'], 'review_record_complete')
        self.project['constraints'] = ['New constraint']
        with self.assertRaises(ValueError):
            report(self.project, self.path, final=True)
        self.assertIn('stale', markdown(self.project, inspect(self.project, self.path, ROOT)))

    def test_cli_preserves_state_and_sources_on_output_error(self):
        self.review()
        write_state(self.path, self.project)
        before = self.path.read_bytes()
        result = self.run_cli('stress_test.py', 'report', self.path, '--out', self.path)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
