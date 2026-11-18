import copy
import json
from pathlib import Path
import sys
import unittest

import test_quality_contract as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, write_state
from claims_audit import baseline, inspect, markdown, prepare, record
from project_tool import audit, report
from quality import state_hash
from start import restore
from validate_project import validate


class ClaimsTests(unittest.TestCase):
    setUp = fixture.QualityContractTests.setUp
    complete_record = fixture.QualityContractTests.complete_record
    run_cli = fixture.QualityContractTests.run_cli

    def setup_claim(self):
        self.complete_record()
        self.project['evidence'][0]['claim_scope'] = 'project_observation'
        self.project['sources'][0]['evidence_scope'] = 'project_observation'
        self.project['product_capabilities'] = [{'capability_id':'C1', 'description':'Create a preparation plan',
                                                'availability':'implemented', 'evidence_ids':['E1']}]
        self.project['marketing_claims'] = [{'claim_id':'M1','text':'Сократить время подготовки вдвое',
                                            'kind':'quantitative', 'requires_causal_evidence':True, 'capability_ids':['C1']}]
        self.project['communication_strategy']['message'] = 'Помощник для планирования; эффект пока не измерен.'
        r = prepare(self.project, self.path, ROOT, 'R1')
        r.update(reviewer='Agent self-review', limitations='Unit-test fixture, not an actual efficacy experiment')
        r['assessments'][0].update(rationale='No measurements demonstrate a time benefit',
            scope_match='No matched audience, comparison or observation window',
            accepted_wording='Помощник для планирования; эффект пока не измерен.',
            validation_method='Compare preparation time on equivalent tasks with a predefined metric and guardrails')
        self.project['marketing_claims_audits'] = [r]
        return r, r['assessments'][0]

    def refresh(self):
        self.project['marketing_claims_audits'][-1]['baseline'] = baseline(self.project, self.path, ROOT)

    def support(self, row, *, status='supported', coverage='full', relation='supports'):
        self.project['marketing_claims'][0].update(kind='qualitative', text='Помощник составляет план', requires_causal_evidence=False)
        row.update(original_claim='Помощник составляет план',status=status,
                   evidence_links=[{'evidence_id':'E1','relation':relation,'coverage':coverage,
                                    'reason':'Observed fixture capability, limited to supplied test context'}])
        self.refresh()

    def test_missing_measurement_is_unsupported_not_false(self):
        r, row = self.setup_claim()
        result = inspect(self.project, self.path, ROOT)
        self.assertEqual(validate(self.project), [])
        self.assertEqual(result['status'], 'review_record_complete', result)
        self.assertEqual(result['claims'][0]['status'], 'unsupported')
        self.assertFalse(result['claims'][0]['has_required_measurements'])
        self.assertIn('требуемых подтверждающих измерений нет', markdown(self.project, result))
        self.assertEqual(self.project['recommended_option_id'],'O1')
        self.assertIsNone(self.project.get('chosen_option_id'))

    def test_quantitative_promise_cannot_be_supported_by_a_capability_document(self):
        r, row = self.setup_claim()
        row.update(status='supported',evidence_links=[{'evidence_id':'E1','relation':'supports','coverage':'full','reason':'Only describes planning'}])
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_all_four_statuses_have_separate_evidence_requirements(self):
        r, row = self.setup_claim()
        for status, relation, coverage in [('supported','supports','full'),('partially_supported','supports','partial'),
                                           ('contradicted','contradicts','full'),('unsupported','context','partial')]:
            with self.subTest(status=status):
                self.support(row,status=status,relation=relation,coverage=coverage)
                result=inspect(self.project,self.path,ROOT)
                self.assertEqual(result['status'],'review_record_complete',result)
                self.assertEqual(result['claims'][0]['status'],status)

    def test_absence_of_evidence_does_not_support_contradiction(self):
        r, row = self.setup_claim()
        row['status']='contradicted'
        self.assertTrue(any('missing proof is not falsehood' in b for b in inspect(self.project,self.path,ROOT)['blockers']))

    def test_contradictory_evidence_cannot_be_hidden(self):
        r,row=self.setup_claim()
        self.support(row,relation='contradicts',status='unsupported')
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_planned_capability_is_not_a_confirmed_working_feature(self):
        r,row=self.setup_claim()
        self.support(row)
        self.project['product_capabilities'][0]['availability']='planned'
        self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_actual_quantitative_observation_allowed_but_not_untested_causality(self):
        r,row=self.setup_claim()
        self.project['evidence'][0]['claim_type']='measured_fact'
        self.project['marketing_claims'][0]['requires_causal_evidence']=False
        self.project['marketing_claims'][0]['text']='В тестовом наборе время подготовки вдвое меньше'
        row['original_claim']=self.project['marketing_claims'][0]['text']
        row.update(status='supported',evidence_links=[{'evidence_id':'E1','relation':'supports','coverage':'full','reason':'Measured fixture comparison; not a general causal claim'}])
        self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')
        self.project['marketing_claims'][0]['requires_causal_evidence']=True
        self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_document_about_missing_measurements_cannot_refute_numerical_effect(self):
        r,row=self.setup_claim()
        self.project['evidence'][0]['claim_scope']='source_description'
        self.project['sources'][0]['evidence_scope']='description'
        row.update(status='contradicted',evidence_links=[{'evidence_id':'E1','relation':'contradicts','coverage':'full',
                                                        'reason':'Describes absent measurements, not an actual contrary effect'}])
        self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_synthetic_observation_cannot_confirm_the_claim(self):
        r,row=self.setup_claim()
        self.support(row)
        self.project['sources'][0]['synthetic']=True
        self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_scope_mismatch_or_hypothesis_cannot_be_full_support(self):
        r,row=self.setup_claim()
        self.support(row,coverage='partial')
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')
        row['evidence_links'][0].update(evidence_id='E2',coverage='full')
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_unmeasured_numbers_cannot_survive_as_accepted_wording(self):
        r,row=self.setup_claim()
        row['accepted_wording']='Будете готовиться вдвое быстрее'
        self.assertTrue(any('numerical promise' in b for b in inspect(self.project,self.path,ROOT)['blockers']))

    def test_unconfirmed_original_message_blocks_final_export(self):
        r,row=self.setup_claim()
        self.project['communication_strategy']['message']=row['original_claim']
        self.refresh()
        self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT)
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')
        self.assertTrue(inspect(self.project,self.path,ROOT)['publication_blockers'])
        with self.assertRaises(ValueError): report(self.project,self.path,final=True)
        self.assertIn('не подтверждено',report(self.project,self.path))

    def test_changed_context_stales_review_and_exposes_it_on_resume(self):
        self.setup_claim()
        self.project['product_capabilities'][0]['availability']='unknown'
        write_state(self.path,self.project)
        self.assertEqual(restore(self.path)['marketing_claims_audit']['status'],'stale')
        self.assertIn('пересмотр',restore(self.path)['decision_question'])
        self.assertFalse(audit(self.project,self.path,ready=True)['ready'])

    def test_incomplete_coverage_unknown_ids_and_malformed_types_rejected(self):
        r,row=self.setup_claim()
        original=copy.deepcopy(self.project)
        mutations=[lambda p:p['marketing_claims'][0].update(kind='qualitative'),
                   lambda p:p['product_capabilities'][0].update(evidence_ids=['FAKE']),
                   lambda p:p['marketing_claims_audits'][0].update(assessments=[]),
                   lambda p:p['marketing_claims_audits'][0]['assessments'][0].update(capability_ids=[{}]),
                   lambda p:p['marketing_claims_audits'][0]['assessments'][0].update(evidence_links=[{}]),
                   lambda p:p['marketing_claims_audits'][0].update(baseline=[])]
        for mutate in mutations:
            p=copy.deepcopy(original);mutate(p)
            self.assertTrue(validate(p))

    def test_record_versions_are_append_only_and_duplicate_is_rejected(self):
        r,row=self.setup_claim()
        self.project.pop('marketing_claims_audits')
        write_state(self.path,self.project)
        record(self.project,self.path,ROOT,r)
        p=json.loads(self.path.read_text(encoding='utf-8'))
        before=self.path.read_bytes()
        with self.assertRaises(ValueError): record(p,self.path,ROOT,r)
        self.assertEqual(self.path.read_bytes(),before)
        r2=copy.deepcopy(r);r2['review_id']='R2'
        record(p,self.path,ROOT,r2)
        after=json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(after['marketing_claims_audits']),2)
        self.assertEqual(after['marketing_claims_audits'][0],p['marketing_claims_audits'][0])
        self.assertEqual(after['communication_strategy'],p['communication_strategy'])

    def test_stale_or_bad_quote_cannot_be_recorded(self):
        r,row=self.setup_claim();self.support(row)
        self.project['evidence'][0]['support'][0]['passage']='Absent passage'
        self.refresh()
        self.assertTrue(any('passage' in b for b in inspect(self.project,self.path,ROOT)['blockers']))
        self.project.pop('marketing_claims_audits');write_state(self.path,self.project)
        with self.assertRaises(ValueError):record(self.project,self.path,ROOT,r)

    def test_output_cannot_overwrite_project_or_sources(self):
        self.setup_claim();write_state(self.path,self.project)
        before=self.path.read_bytes()
        for target in (self.path,self.root/'source.md'):
            r=self.run_cli('claims_audit.py','report',self.path,'--out',target)
            self.assertEqual(r.returncode,1)
        self.assertEqual(self.path.read_bytes(),before)

    def test_review_metadata_does_not_create_a_cross_review_invalidation_loop(self):
        from stress_test import baseline as stress_baseline
        r,row=self.setup_claim()
        before=stress_baseline(self.project,self.path,ROOT)
        full_hash=state_hash(self.project,self.path,ROOT)
        r2=copy.deepcopy(r);r2['review_id']='R2'
        self.project['marketing_claims_audits'].append(r2)
        self.assertEqual(stress_baseline(self.project,self.path,ROOT),before)
        self.assertNotEqual(state_hash(self.project,self.path,ROOT),full_hash)
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')
        self.project['marketing_claims'][0]['text']='Другое обещание'
        self.assertNotEqual(stress_baseline(self.project,self.path,ROOT),before)

    def test_source_change_and_retired_evidence_are_not_laundered(self):
        r,row=self.setup_claim();self.support(row)
        (self.root/'source.md').write_text('Changed observation',encoding='utf-8')
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'stale')
        self.project['evidence'][0]['status']='withdrawn'
        self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'blocked')

    def test_unrelated_empirical_threshold_keeps_full_evidence_namespace(self):
        self.setup_claim()
        other=copy.deepcopy(self.project['evidence'][0])
        other.update(evidence_id='E3',claim_type='measured_fact',status='corroborated')
        self.project['evidence'].append(other)
        self.project['validation_design']['thresholds']=[{'metric':'Fixture metric','value':'0','basis':'empirical',
            'rationale':'Unit fixture, not a business result','evidence_ids':['E3']}]
        self.refresh()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'review_record_complete')


if __name__=='__main__':unittest.main()
