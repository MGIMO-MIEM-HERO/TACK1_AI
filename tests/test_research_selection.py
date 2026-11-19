import copy
import json
from pathlib import Path
import sys
import unittest

import test_quality_contract as fixture

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from checkpoint import ROOT,write_state
from quality import state_hash
from research_selection import baseline,inspect,markdown,prepare,record
from project_tool import audit,report
from start import restore
from validate_project import validate


class ResearchTests(unittest.TestCase):
    setUp=fixture.QualityContractTests.setUp
    complete_record=fixture.QualityContractTests.complete_record
    run_cli=fixture.QualityContractTests.run_cli

    def selection(self):
        self.complete_record()
        self.project['research_questions']=[{'question_id':q,'question':text,'could_change':'Which option to use'}
            for q,text in [('Q1','Is integration possible?'),('Q2','Which delivery method?'),('Q3','Competitor colours?')]]
        r=prepare(self.project,self.path,ROOT,'R1')
        r.update(reviewer='Agent self-review',limitations='Unit fixture, not measured savings',
                 comparison_rationale='Resolve feasibility first; compare delivery later; colours do not distinguish current options')
        for i,g in enumerate(r['gaps']):
            g.update(impact=['feasibility','preference','context'][i],priority=['critical','high','defer'][i],
                why_changes_decision='Integration failure excludes O1' if i==0 else 'Compare applicable methods within current decision',
                priority_rationale='Feasibility gates the decision' if i==0 else 'Lower priority after feasibility',
                selected_method_id='M1',method_choice_rationale='Available supplied document is enough; effort is unknown')
            g['answer_branches']=[] if i==2 else [
                {'answer':'Yes','consequence':'O1 remains an option','option_ids':['O1']},
                {'answer':'No','consequence':'Prefer avoiding implementation','option_ids':['O0']}]
            g['methods'][0].update(description='Read supplied document',access='available',adequacy='sufficient',
                adequacy_rationale='The supplied source contains the relevant condition',source_ids=['S'])
        r['recommendation'].update(action='investigate',question_id='Q1',method_id='M1',rationale='Q1 can exclude implementation before spending effort on Q2 or Q3')
        r['stop_rule'].update(status='continue',condition='Stop when feasibility and delivery are resolved for this decision',
            rationale='Two decision-changing questions remain',remaining_limits='No market/demand inference')
        self.project['research_selection_reviews']=[r]
        return r

    def refresh(self):self.project['research_selection_reviews'][-1]['baseline']=baseline(self.project,self.path,ROOT)

    def test_feasibility_precedes_lower_priority_and_effort_stays_unknown(self):
        self.selection();before=copy.deepcopy(self.project)
        self.assertEqual(validate(self.project),[])
        result=inspect(self.project,self.path,ROOT)
        self.assertEqual(result['status'],'review_record_complete',result)
        self.assertEqual(result['recommendation']['question_id'],'Q1')
        self.assertIsNone(result['gaps'][0]['methods'][0]['effort']['time']['value'])
        self.assertEqual(self.project,before)
        self.assertIn('неизвестно',markdown(self.project,result))

    def test_cannot_choose_lower_priority_while_feasibility_is_open(self):
        r=self.selection();r['recommendation']['question_id']='Q2'
        self.assertTrue(any('critical feasibility' in b for b in inspect(self.project,self.path,ROOT)['blockers']))

    def test_unknown_access_requires_clarification_instead_of_fake_execution(self):
        r=self.selection();g=r['gaps'][0]
        g['methods'][0]['access']='unknown';g['selected_method_id']=None
        r['recommendation'].update(action='clarify',method_id=None)
        r['stop_rule']['status']='uncertain'
        self.assertEqual(validate(self.project),[])
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')
        g['selected_method_id']='M1'
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_accessible_but_insufficient_method_is_not_selected(self):
        r=self.selection();r['gaps'][0]['methods'][0]['adequacy']='insufficient'
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_unknown_effort_cannot_be_zero_and_estimates_need_basis(self):
        r=self.selection();cost=r['gaps'][0]['methods'][0]['effort']['time']
        cost['value']=0
        self.assertTrue(any('Unknown effort' in e for e in validate(self.project)))
        cost.update(status='estimated',value='15 minutes',basis=None)
        self.assertTrue(validate(self.project))
        cost['basis']='Explicit authored estimate, not measured'
        self.assertEqual(validate(self.project),[])

    def test_observed_effort_cannot_be_a_model_hypothesis(self):
        r=self.selection();cost=r['gaps'][0]['methods'][0]['effort']['time']
        cost.update(status='observed',value='15 minutes',basis='Claimed measurement',evidence_ids=['E2'])
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_answered_question_needs_fact_and_is_not_repeated(self):
        r=self.selection();g=r['gaps'][0]
        g.update(status='answered',answer='Available in this fixture',priority='defer',evidence_ids=['E1'],selected_method_id=None)
        r['recommendation']['question_id']='Q2'
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')
        r['recommendation'].update(question_id='Q1',method_id=None)
        self.assertTrue(any('answered' in b for b in inspect(self.project,self.path,ROOT)['blockers']))
        g['evidence_ids']=['E2']
        self.assertTrue(any('factual evidence' in b for b in inspect(self.project,self.path,ROOT)['blockers']))

    def test_stop_requires_resolved_decision_changing_gaps_and_factual_ground(self):
        r=self.selection();r['recommendation'].update(action='stop',question_id=None,method_id=None)
        r['stop_rule'].update(status='stop',evidence_ids=['E1'])
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')
        for g in r['gaps'][:2]:g.update(status='answered',answer='Resolved in test context',priority='defer',evidence_ids=['E1'],selected_method_id=None)
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')
        r['stop_rule']['evidence_ids']=['E2']
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_stopping_uncertainty_is_visible(self):
        r=self.selection();r['stop_rule']['status']='uncertain'
        self.assertTrue(validate(self.project))
        r['recommendation'].update(action='clarify',method_id=None)
        self.assertEqual(validate(self.project),[])

    def test_malformed_refs_and_incomplete_comparison_are_rejected(self):
        r=self.selection();original=copy.deepcopy(self.project)
        mutations=[lambda p:p['research_selection_reviews'][0].update(gaps=[]),
            lambda p:p['research_selection_reviews'][0]['gaps'][0].update(option_ids=['FAKE']),
            lambda p:p['research_selection_reviews'][0]['gaps'][0].update(answer_branches=[]),
            lambda p:p['research_selection_reviews'][0]['gaps'][0].update(methods=[{}]),
            lambda p:p['research_selection_reviews'][0]['gaps'][0]['methods'][0]['effort'].update(money=0),
            lambda p:p['research_selection_reviews'][0]['recommendation'].update(question_id=[]),
            lambda p:p.update(research_selection_reviews=[{}]),
            lambda p:p['research_questions'].append(copy.deepcopy(p['research_questions'][0]))]
        for mutate in mutations:
            p=copy.deepcopy(original);mutate(p);self.assertTrue(validate(p))

    def test_source_new_evidence_and_constraints_stale_the_selection(self):
        self.selection();original=copy.deepcopy(self.project)
        for mutate in (lambda p:p.update(constraints=['New limit']),
                       lambda p:p['evidence'][0].update(claim='Changed observation'),
                       lambda p:p['research_questions'][0].update(question='Changed decision question')):
            self.project=copy.deepcopy(original);mutate(self.project)
            self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'stale')
        self.project=copy.deepcopy(original)
        (self.root/'source.md').write_text('Changed source',encoding='utf-8')
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'stale')

    def test_retired_support_is_not_laundered_by_refreshing(self):
        r=self.selection();r['gaps'][0]['evidence_ids']=['E1']
        self.project['evidence'][0]['status']='withdrawn';self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_record_versions_and_never_execute_or_choose_for_owner(self):
        r=self.selection();self.project.pop('research_selection_reviews');write_state(self.path,self.project)
        record(self.project,self.path,ROOT,r);p=json.loads(self.path.read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):record(p,self.path,ROOT,r)
        r2=copy.deepcopy(r);r2['review_id']='R2';record(p,self.path,ROOT,r2)
        after=json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(after['research_selection_reviews']),2)
        self.assertEqual(after['next_action'],p['next_action'])
        self.assertEqual(after['recommended_option_id'],'O1');self.assertIsNone(after.get('chosen_option_id'))

    def test_resume_and_final_report_include_selection(self):
        self.selection();self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT)
        write_state(self.path,self.project)
        self.assertEqual(restore(self.path)['research_selection']['recommendation']['question_id'],'Q1')
        self.assertIn('Когда остановиться',report(self.project,self.path,final=True))
        self.project['constraints']=['Changed'];write_state(self.path,self.project)
        self.assertIn('пересмотр',restore(self.path)['decision_question'])
        with self.assertRaises(ValueError):report(self.project,self.path,final=True)

    def test_early_project_without_formal_options_is_supported(self):
        r=self.selection();self.project['options']=[];self.project['recommended_option_id']=None
        for g in r['gaps']:
            g['option_ids']=[]
            for b in g['answer_branches']:b['option_ids']=[]
        self.refresh()
        self.assertEqual(validate(self.project),[])
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')

    def test_cli_protects_sources_and_state(self):
        self.selection();write_state(self.path,self.project);before=self.path.read_bytes()
        result=self.run_cli('research_selection.py','report',self.path,'--out',self.path)
        self.assertEqual(result.returncode,1);self.assertEqual(self.path.read_bytes(),before)

    def test_context_only_question_is_not_selected_as_decision_changing(self):
        r=self.selection();r['gaps'][0].update(status='answered',answer='Resolved',priority='defer',evidence_ids=['E1'],selected_method_id=None)
        r['gaps'][2]['priority']='high';r['recommendation']['question_id']='Q3'
        self.assertTrue(any('Context-only' in b for b in inspect(self.project,self.path,ROOT)['blockers']))

    def test_missing_method_source_is_not_called_accessible(self):
        self.selection();(self.root/'source.md').unlink();self.refresh()
        self.assertTrue(any('unavailable/untracked' in b for b in inspect(self.project,self.path,ROOT)['blockers']))

    def test_review_only_records_do_not_create_mutual_invalidation(self):
        r=self.selection();r2=copy.deepcopy(r);r2['review_id']='R2'
        self.project['research_selection_reviews'].append(r2)
        self.project['marketing_claims_audits']=[];self.project['decision_stress_tests']=[]
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')
        self.project['research_questions'][0]['could_change']='Changed decision dependency'
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'stale')


if __name__=='__main__':unittest.main()
