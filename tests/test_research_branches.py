import copy
import json
from pathlib import Path
import sys
import unittest

import test_feasibility as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, write_state
from feasibility import baseline as feasibility_baseline
from project_tool import load
from quality import state_hash
from research_selection import baseline, inspect, markdown, prepare, record
from start import restore
from validate_project import validate


class BranchTests(unittest.TestCase):
    setUp = fixture.FeasibilityTests.setUp
    complete_record = fixture.FeasibilityTests.complete_record
    statement = fixture.FeasibilityTests.statement
    assessment = fixture.FeasibilityTests.assessment
    run_cli = fixture.FeasibilityTests.run_cli

    def selection(self):
        self.assessment()
        self.project['options'].append({'option_id': 'O3', 'kind': 'learn', 'title': 'Paper protocol',
            'benefits': ['No developer needed'], 'costs_and_risks': ['Analyst time'],
            'objection': 'Does not check code', 'evidence_ids': ['E1']})
        paper = copy.deepcopy(self.project['feasibility_reviews'][0]['assessments'][0])
        paper.update(option_id='O3', minimum_scope='Paper states only',
            work=[{'work_id': 'P', 'description': 'Paper states', 'skill': 'product',
                   'effort': self.statement('estimated', hours=2)}],
            resources=[{'resource_id': 'ANALYST', 'skills': ['product'],
                        'competence': self.statement('confirmed'), 'availability': self.statement('confirmed'),
                        'capacity': self.statement('confirmed', hours=3)}],
            allocations=[{'work_id': 'P', 'resource_id': 'ANALYST', 'hours': 2}])
        self.project['feasibility_reviews'][0]['assessments'].append(paper)
        self.project['research_questions'] = [{'question_id': 'Q1', 'question': 'Does the scoped prototype fit actual available capacity and dependencies?',
                                               'could_change': 'Prototype O1 versus a separately feasible paper O3'}]
        review = prepare(self.project, self.path, ROOT, 'R1')
        review.update(context='authored_example', reviewer='Unit self-review', limitations='All fixtures are authored fiction',
                      comparison_rationale='Feasibility must distinguish alternatives before secondary research')
        gap = review['gaps'][0]
        gap.update(impact='feasibility', priority='critical', priority_rationale='Capacity gates the proposed work',
            why_changes_decision='A known shortfall makes this prototype plan unusable; missing estimates need clarification',
            selected_method_id='M1', method_choice_rationale='Read the existing resource plan, no experiment or code')
        gap['methods'][0].update(description='Inspect separately recorded scope, work, skills, capacity, allocations and calendar dependencies',
            access='available', adequacy='sufficient', adequacy_rationale='Enough for a bounded resource-plan decision, not success prediction', source_ids=['S'])
        for branch, bid, oid, outcome in [(gap['answer_branches'][0], 'BUILD', 'O1', 'feasible'),
                                         (gap['answer_branches'][1], 'PAPER', 'O3', 'infeasible')]:
            branch.update(branch_id=bid, answer='Prototype resource plan is ' + outcome,
                consequence='Conditionally retain the scoped prototype' if bid == 'BUILD' else 'Propose the separately resource-checked paper plan',
                option_ids=[oid], next_step='Show this conditional alternative and its assumptions to the owner; do not execute')
            requirements = [{'option_id': 'O1', 'outcome': outcome}]
            if bid == 'PAPER': requirements.append({'option_id': 'O3', 'outcome': 'feasible'})
            branch['condition'] = {'kind': 'feasibility', 'indicator': 'Resource fit of specified work in the shared window',
                'criterion': 'Confirmed capacity, complete work allocation, required skills and calendar dependencies support this outcome',
                'method_id': 'M1', 'requirements': requirements}
        gap['answer_branches'][2]['next_step'] = 'Ask for missing work estimate or available hours; if prohibited, document the access limitation'
        review['recommendation'].update(action='investigate', question_id='Q1', method_id='M1', rationale='Check the existing resource plan first')
        review['stop_rule'].update(status='continue', condition='Stop this inquiry once resource conditions distinguish the current options',
            rationale='Do not research secondary matters while critical inputs are unknown', remaining_limits='No demand or implementation proof')
        self.project['research_selection_reviews'] = [review]
        self.refresh()
        return review, gap

    def refresh(self):
        self.project['feasibility_reviews'][-1]['baseline'] = feasibility_baseline(self.project, self.path, ROOT)
        if self.project.get('research_selection_reviews'):
            self.project['research_selection_reviews'][-1]['baseline'] = baseline(self.project, self.path, ROOT)
        self.project['strategy_review']['state_hash'] = state_hash(self.project, self.path, ROOT)

    def result(self):
        self.refresh(); self.assertEqual(validate(self.project), [])
        return inspect(self.project, self.path, ROOT)

    def resolution(self):
        return self.result()['branch_resolutions'][0]

    def manual(self):
        review, gap = self.selection()
        for branch, state, criterion in zip(gap['answer_branches'][:2], ('met', 'not_met'), ('Static mode is permitted', 'Static mode is explicitly prohibited')):
            branch['condition'] = {'kind': 'observation', 'indicator': 'Allowed scope in supplied policy', 'criterion': criterion,
                'method_id': 'M1', 'assessment': state, 'rationale': 'Read the cited condition; no inference about demand',
                'evidence_ids': ['E1'], 'thresholds': []}
        return review, gap

    def test_new_template_is_v2_and_unfilled_conditions_do_not_pass(self):
        self.complete_record(); self.project['research_questions'] = [{'question_id':'Q','question':'What differs?', 'could_change':'O1'}]
        original = copy.deepcopy(self.project); r = prepare(self.project, self.path, ROOT, 'R')
        self.assertEqual(r['schema_version'], 2)
        self.assertEqual(r['gaps'][0]['answer_branches'][2]['condition']['kind'], 'insufficient_data')
        self.assertEqual(self.project, original)
        self.project['research_selection_reviews'] = [r]
        self.assertTrue(validate(self.project))

    def test_enough_resources_match_build_and_keep_estimates_visible(self):
        self.selection(); result = self.resolution()
        self.assertEqual(result['status'], 'matched'); self.assertEqual(result['branch_id'], 'BUILD')
        self.assertEqual(result['option_ids'], ['O1']); self.assertTrue(result['assumptions'])
        self.assertTrue(all(c['feasibility_review_id'] == 'F1' for c in result['conditions']))

    def test_confirmed_deficit_requires_separately_feasible_alternative(self):
        self.selection(); self.project['feasibility_reviews'][0]['assessments'][0]['resources'][0]['capacity']['hours'] = 4
        self.assertEqual(self.resolution()['branch_id'], 'PAPER')
        self.assertEqual(self.project['chosen_option_id'], 'O1'); self.assertEqual(self.project['recommended_option_id'], 'O1')
        self.project['feasibility_reviews'][0]['assessments'][1]['resources'][0]['capacity']['hours'] = 1
        result = self.resolution()
        self.assertEqual(result['branch_id'], 'UNKNOWN'); self.assertEqual(result['option_ids'], [])

    def test_unknown_effort_never_selects_paper(self):
        self.selection(); plan = self.project['feasibility_reviews'][0]['assessments'][0]
        plan['work'][0]['effort'].update(status='unknown', hours=None); plan['allocations'] = plan['allocations'][1:]
        result = self.resolution()
        self.assertEqual(result['status'], 'insufficient_data'); self.assertEqual(result['option_ids'], [])
        self.assertIn('missing work estimate', result['next_step'])

    def test_hours_fitting_without_calendar_fit_remain_unknown(self):
        self.selection(); plan = self.project['feasibility_reviews'][0]['assessments'][0]
        plan['schedule'] = self.statement('unknown', fit='unknown')
        self.assertEqual(self.resolution()['branch_id'], 'UNKNOWN')

    def test_unreliable_estimation_method_requires_clarification_not_a_winner(self):
        review, gap = self.selection()
        gap['methods'][0].update(adequacy='unknown', adequacy_rationale='Available estimate lacks a reliable technical decomposition')
        gap['selected_method_id'] = None
        review['recommendation'].update(action='clarify', method_id=None)
        review['stop_rule']['status'] = 'uncertain'
        result = self.resolution()
        self.assertEqual(result['branch_id'], 'UNKNOWN')
        self.assertTrue(all(c['state'] == 'unknown' for c in result['conditions']))

    def test_resume_asks_for_missing_condition_before_approving_recommendation(self):
        self.selection(); plan = self.project['feasibility_reviews'][0]['assessments'][0]
        plan['resources'][0]['capacity'] = self.statement('unknown', hours=None)
        self.refresh(); write_state(self.path, self.project)
        question = restore(self.path)['decision_question']
        self.assertIn('уточнить условие', question)
        self.assertIn('missing work estimate', question)
        self.assertNotIn('Подтверждаете ли', question)

    def test_missing_or_stale_feasibility_is_not_a_shortcut_to_paper(self):
        initial = copy.deepcopy(self.project)
        self.selection(); self.project.pop('feasibility_reviews'); self.project['research_selection_reviews'][0]['baseline'] = baseline(self.project, self.path, ROOT)
        self.assertEqual(inspect(self.project, self.path, ROOT)['branch_resolutions'][0]['branch_id'], 'UNKNOWN')
        self.project = initial
        self.selection(); self.project['feasibility_reviews'][0]['baseline']['state_hash'] = '0' * 64
        self.project['research_selection_reviews'][0]['baseline'] = baseline(self.project, self.path, ROOT)
        self.assertEqual(inspect(self.project, self.path, ROOT)['branch_resolutions'][0]['branch_id'], 'UNKNOWN')

    def test_authored_resource_check_cannot_confirm_a_live_condition(self):
        review, _ = self.selection(); review['context'] = 'live_project'
        self.assertEqual(self.resolution()['branch_id'], 'UNKNOWN')

    def test_known_observation_maps_to_a_branch_and_new_result_explains_change(self):
        _, gap = self.manual(); self.assertEqual(self.resolution()['branch_id'], 'BUILD')
        gap['answer_branches'][0]['condition']['assessment'] = 'not_met'
        gap['answer_branches'][1]['condition']['assessment'] = 'met'
        result = self.resolution()
        self.assertEqual(result['branch_id'], 'PAPER')
        self.assertIn('Ровно одно', result['reason'])

    def test_overlapping_or_unknown_competing_conditions_use_fallback(self):
        _, gap = self.manual(); gap['answer_branches'][1]['condition']['assessment'] = 'met'
        self.assertEqual(self.resolution()['branch_id'], 'UNKNOWN')
        gap['answer_branches'][1]['condition']['assessment'] = 'unknown'
        self.assertEqual(self.resolution()['branch_id'], 'UNKNOWN')
        for b in gap['answer_branches'][:2]: b['condition']['assessment'] = 'not_met'
        self.assertEqual(self.resolution()['branch_id'], 'UNKNOWN')

    def test_hypothesis_cannot_close_a_condition(self):
        _, gap = self.manual(); gap['answer_branches'][0]['condition']['evidence_ids'] = ['E2']
        result = self.result(); self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['branch_resolutions'][0]['branch_id'], 'UNKNOWN')

    def test_qualified_observation_keeps_its_evidence_type(self):
        self.manual(); self.project['evidence'][0]['claim_type'] = 'qualitative_signal'
        self.assertEqual(self.resolution()['branch_id'], 'BUILD')
        self.assertEqual(self.project['evidence'][0]['claim_type'], 'qualitative_signal')

    def test_synthetic_live_observation_cannot_close_a_condition(self):
        review, _ = self.manual(); review['context'] = 'live_project'
        self.project['sources'][0]['evidence_scope'] = 'simulation'
        self.assertEqual(self.result()['status'], 'blocked')

    def test_retired_condition_support_is_not_used_for_matching(self):
        self.manual(); self.project['evidence'][0]['status'] = 'withdrawn'
        result = self.result(); self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['branch_resolutions'][0]['branch_id'], 'UNKNOWN')

    def test_numeric_threshold_without_a_basis_is_rejected(self):
        _, gap = self.manual(); c = gap['answer_branches'][0]['condition']; c['criterion'] = 'At least 2 complete states'
        self.refresh(); self.assertTrue(validate(self.project))
        c['thresholds'] = [{'metric':'states','value':2,'unit':'states','basis':'proposed','rationale':'Convenient count','evidence_ids':['E1']}]
        self.assertTrue(validate(self.project))
        c['thresholds'][0].update(basis='derived', rationale='Explicit authored limit; no empirical success claim')
        # Supply the actual numerical condition, not just a type-correct unrelated URL.
        passage = 'Авторское условие: лимит составляет 2 состояния.'
        with (self.root / 'source.md').open('a', encoding='utf-8') as stream: stream.write('\n' + passage)
        evidence = copy.deepcopy(self.project['evidence'][0])
        evidence.update(evidence_id='LIMIT', claim=passage)
        evidence['support'][0]['passage'] = passage
        self.project['evidence'].append(evidence)
        c['thresholds'][0]['evidence_ids'] = ['LIMIT']
        self.refresh()
        self.assertEqual(validate(self.project), [])
        self.assertEqual(self.result()['status'], 'review_record_complete')

    def test_owner_and_empirical_thresholds_require_relevant_evidence(self):
        _, gap = self.manual(); c = gap['answer_branches'][0]['condition']
        t = {'metric':'states','value':2,'unit':'states','basis':'owner_agreed','agreement_reference':'Not an actual approval',
             'rationale':'A reference alone is not evidence of owner input','evidence_ids':['E1']}
        c['thresholds'] = [t]
        self.assertEqual(self.result()['status'], 'blocked')
        t['basis'] = 'empirical'
        self.assertEqual(self.result()['status'], 'blocked')

    def test_question_cannot_be_marked_answered_on_unknown_feasibility(self):
        _, gap = self.selection(); plan = self.project['feasibility_reviews'][0]['assessments'][0]
        plan['resources'][0]['capacity'] = self.statement('unknown', hours=None)
        gap.update(status='answered', answer='Permission exists, therefore enough resources', priority='defer', evidence_ids=['E1'])
        self.assertTrue(any('cannot mark' in b for b in self.result()['blockers']))

    def test_source_and_resource_changes_stale_the_prior_branch(self):
        self.selection(); original = copy.deepcopy(self.project)
        self.project['feasibility_reviews'][0]['assessments'][0]['resources'][0]['capacity']['hours'] = 4
        result = inspect(self.project, self.path, ROOT)
        self.assertEqual(result['status'], 'stale'); self.assertFalse(result.get('branch_resolutions'))
        self.project = original
        (self.root / 'source.md').write_text('New condition', encoding='utf-8')
        self.assertEqual(inspect(self.project, self.path, ROOT)['status'], 'stale')

    def test_malformed_condition_shapes_are_validation_errors(self):
        self.selection(); original = copy.deepcopy(self.project)
        mutations = [lambda r:r['gaps'][0].update(methods=None),
            lambda r:r.update(context='unknown'),
            lambda r:r['gaps'][0]['answer_branches'][0].update(condition={}),
            lambda r:r['gaps'][0]['answer_branches'][0]['condition'].update(requirements=[{}]),
            lambda r:r['gaps'][0]['answer_branches'][0]['condition'].update(method_id='FAKE'),
            lambda r:r['gaps'][0]['answer_branches'][0]['condition']['requirements'][0].update(option_id='FAKE'),
            lambda r:r['gaps'][0]['answer_branches'][0]['condition']['requirements'][0].update(outcome='unknown'),
            lambda r:r['gaps'][0]['answer_branches'][2].update(option_ids=['O3']),
            lambda r:r['gaps'][0]['answer_branches'].pop(),
            lambda r:r['gaps'][0]['answer_branches'][1].update(branch_id='BUILD'),
            lambda r:r['gaps'][0]['answer_branches'][1].update(condition=copy.deepcopy(r['gaps'][0]['answer_branches'][0]['condition']))]
        for mutation in mutations:
            p = copy.deepcopy(original); mutation(p['research_selection_reviews'][0])
            with self.subTest(mutation=mutation): self.assertTrue(validate(p))

    def test_recording_and_reopening_preserve_choice_obligations_and_history(self):
        review, _ = self.selection(); self.project.pop('research_selection_reviews')
        original = copy.deepcopy(self.project); write_state(self.path, self.project)
        record(self.project, self.path, ROOT, review); saved = load(self.path)
        before = self.path.read_bytes(); log = (self.root / 'ledger.jsonl').read_bytes()
        a = restore(self.path)['research_selection']; b = restore(self.path)['research_selection']
        self.assertEqual(a, b); self.assertEqual(a['branch_resolutions'][0]['branch_id'], 'BUILD')
        self.assertEqual(before, self.path.read_bytes()); self.assertEqual(log, (self.root / 'ledger.jsonl').read_bytes())
        for key in ('chosen_option_id','recommended_option_id','commitments','next_action'):
            self.assertEqual(saved[key], original[key])
        newer = copy.deepcopy(review); newer['review_id'] = 'R2'
        record(saved, self.path, ROOT, newer)
        self.assertEqual(len(load(self.path)['research_selection_reviews']), 2)

    def test_cli_prepare_and_report_show_current_condition_and_fallback(self):
        self.selection(); write_state(self.path, self.project)
        r = self.run_cli('research_selection.py', 'prepare', self.path, '--review-id', 'NEW')
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(json.loads(r.stdout)['schema_version'], 2)
        text = markdown(self.project, self.result())
        self.assertIn('Сопоставление: matched', text); self.assertIn('UNKNOWN', text)
        self.assertIn('F1', json.dumps(self.result()))

    def test_legacy_review_remains_readable_without_claiming_a_computed_branch(self):
        review, gap = self.manual(); review['schema_version'] = 1
        gap['answer_branches'] = [{k:b[k] for k in ('answer','consequence','option_ids')} for b in gap['answer_branches'][:2]]
        result = self.result()
        self.assertEqual(result['branch_resolutions'], [])
        self.assertIn('Исторический формат v1', markdown(self.project, result))


if __name__ == '__main__': unittest.main()
