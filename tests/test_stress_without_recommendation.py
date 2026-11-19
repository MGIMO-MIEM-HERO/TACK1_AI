"""Conditional analysis may precede a recommendation, without inventing one."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_stress_test as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, write_state
from ledger import ledger_path, read_entries, verify
from project_tool import audit, load
from start import restore
from stress_test import baseline, inspect, prepare, record
from validate_project import validate


class StressWithoutRecommendationTests(unittest.TestCase):
    setUp = fixture.StressTests.setUp
    complete_record = fixture.StressTests.complete_record
    review = fixture.StressTests.review
    run_cli = fixture.StressTests.run_cli

    def without_recommendation(self, *, history=True):
        old = self.review()
        self.project['recommended_option_id'] = None
        self.project['recommendation_rationale'] = ''
        if not history:
            self.project.pop('decision_stress_tests')
        write_state(self.path, self.project)
        review = copy.deepcopy(old)
        review.update(review_id='NO-BASE', baseline=baseline(self.project, self.path, ROOT))
        for scenario in review['scenarios']:
            for impact in scenario['option_impacts']:
                impact.update(feasibility='uncertain', preference='undetermined')
            scenario['recommendation'].update(outcome='insufficient_evidence', option_id=None,
                evidence_ids=[], rationale='No baseline recommendation; compare conditional limits only')
        return review

    def test_cli_prepare_accepts_no_recommendation_and_preserves_state(self):
        self.without_recommendation()
        before = self.path.read_bytes()
        result = self.run_cli('stress_test.py', 'prepare', self.path, '--review-id', 'PREPARED')
        self.assertEqual(result.returncode, 0, result.stderr)
        prepared = json.loads(result.stdout)
        self.assertIsNone(prepared['baseline']['recommended_option_id'])
        self.assertEqual(prepared['baseline']['option_ids'], ['O1', 'O0', 'O2'])
        self.assertEqual(before, self.path.read_bytes())

    def test_record_and_reload_replace_stale_analysis_without_replacing_history(self):
        review = self.without_recommendation()
        historical = copy.deepcopy(self.project['decision_stress_tests'][0])
        self.assertEqual(inspect(self.project, self.path, ROOT)['status'], 'stale')
        result = record(self.project, self.path, ROOT, review)
        saved = load(self.path)
        self.assertEqual(saved['decision_stress_tests'][0], historical)
        self.assertEqual(len(saved['decision_stress_tests']), 2)
        self.assertEqual(saved['decision_stress_tests'][-1]['review_id'], 'NO-BASE')
        self.assertIsNone(saved['recommended_option_id'])
        self.assertIsNone(saved.get('chosen_option_id'))
        self.assertEqual(saved['recommendation_rationale'], '')
        self.assertEqual(inspect(saved, self.path, ROOT), result)
        self.assertEqual(result['status'], 'review_record_complete')
        self.assertEqual(result['comparison']['status'], 'no_baseline_recommendation')
        self.assertIsNone(result['comparison']['recommended_option_id'])
        self.assertEqual(restore(self.path)['decision_stress_test'], result)
        self.assertFalse(audit(saved, self.path, ready=True)['ready'])
        self.assertEqual(verify(read_entries(ledger_path(self.path))), [])

    def test_first_analysis_can_be_saved_without_a_recommendation(self):
        review = self.without_recommendation(history=False)
        record(self.project, self.path, ROOT, review)
        self.assertEqual(len(load(self.path)['decision_stress_tests']), 1)

    def test_missing_baseline_cannot_claim_keep_or_switch_or_fake_option(self):
        review = self.without_recommendation()
        for mutate in (
            lambda r: r['scenarios'][0]['recommendation'].update(outcome='keep', option_id='O1', evidence_ids=['E1']),
            lambda r: r['scenarios'][0]['recommendation'].update(outcome='switch', option_id='O0', evidence_ids=['E1']),
            lambda r: r['baseline'].update(recommended_option_id='FAKE'),
            lambda r: r['baseline'].update(recommended_option_id=[]),
            lambda r: r['baseline'].pop('recommended_option_id')):
            with self.subTest(mutate=mutate):
                candidate = copy.deepcopy(review)
                mutate(candidate)
                project = copy.deepcopy(self.project)
                project['decision_stress_tests'].append(candidate)
                self.assertTrue(validate(project))

    def conditional(self, review):
        scenario = review['scenarios'][0]
        next(i for i in scenario['option_impacts'] if i['option_id'] == 'O0').update(
            feasibility='feasible', preference='preferred')
        scenario['recommendation'].update(outcome='conditional_option', option_id='O0', evidence_ids=['E1'])

    def test_conditional_option_has_support_checks_and_is_not_a_global_recommendation(self):
        review = self.without_recommendation()
        self.conditional(review)
        project = copy.deepcopy(self.project)
        project['decision_stress_tests'].append(review)
        self.assertEqual(validate(project), [])
        self.assertEqual(inspect(project, self.path, ROOT)['status'], 'review_record_complete')
        for mutate in (
            lambda s: s.update(changed_evidence_ids=['E1']),
            lambda s: s['recommendation'].update(evidence_ids=['E2'])):
            candidate = copy.deepcopy(project)
            mutate(candidate['decision_stress_tests'][-1]['scenarios'][0])
            self.assertEqual(inspect(candidate, self.path, ROOT)['status'], 'blocked')
        record(self.project, self.path, ROOT, review)
        self.assertIsNone(load(self.path)['recommended_option_id'])
        # With a baseline, use keep/switch rather than conceal the comparison.
        project['decision_stress_tests'][-1]['baseline']['recommended_option_id'] = 'O1'
        self.assertTrue(validate(project))

    def test_failed_record_preserves_state_and_history_and_reports_ledger_failure(self):
        review = self.without_recommendation()
        before = self.path.read_bytes()
        ledger_path(self.path).touch()
        log = ledger_path(self.path).read_bytes()
        for mutate in (lambda r: r.update(reviewer=''),
                       lambda r: r['baseline'].update(state_hash='0' * 64)):
            candidate = copy.deepcopy(review)
            mutate(candidate)
            with self.assertRaises(ValueError):
                record(self.project, self.path, ROOT, candidate)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(ledger_path(self.path).read_bytes(), log)
        with patch('ledger.append', side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(ValueError, 'Review saved but ledger append failed'):
                record(self.project, self.path, ROOT, review)
        saved = load(self.path)
        self.assertEqual(len(saved['decision_stress_tests']), 2)
        self.assertEqual(saved['decision_stress_tests'][0], self.project['decision_stress_tests'][0])
        self.assertIsNone(saved['recommended_option_id'])

    def test_native_report_and_map_explain_missing_comparison_and_history(self):
        review = self.without_recommendation()
        self.conditional(review)
        record(self.project, self.path, ROOT, review)
        before = self.path.read_bytes()
        out = self.root / 'without-recommendation.md'
        result = self.run_cli('project_tool.py', 'report', self.path, '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = out.read_text(encoding='utf-8')
        self.assertIn('Базовая рекомендация отсутствует', text)
        self.assertNotIn('Исходная рекомендация: None', text)
        self.assertIn('conditional_option', text)
        self.assertIn('SC1', text)
        data = json.loads(out.with_suffix('.graph.html').read_text(encoding='utf-8').split(
            '<script id="data" type="application/json">', 1)[1].split('</script>', 1)[0])
        current = next(n for n in data['nodes'] if n['id'] == 'stress:NO-BASE')
        historical = next(n for n in data['nodes'] if n['id'] == 'stress:R1')
        self.assertEqual(current['status'], 'review_record_complete')
        self.assertEqual(current['details']['Текущая проверка']['comparison']['status'], 'no_baseline_recommendation')
        self.assertEqual(historical['status'], 'историческая версия')
        self.assertEqual(before, self.path.read_bytes())

    def test_new_recommendation_invalidates_no_baseline_analysis(self):
        review = self.without_recommendation()
        record(self.project, self.path, ROOT, review)
        saved = load(self.path)
        saved.update(recommended_option_id='O1', recommendation_rationale='New actual recommendation')
        self.assertEqual(inspect(saved, self.path, ROOT)['status'], 'stale')


if __name__ == '__main__':
    unittest.main()
