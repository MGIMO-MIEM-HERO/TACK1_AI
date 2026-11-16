"""Regression tests for the problems observed in the two live trials."""
import copy
import json
from pathlib import Path
import sys
import unittest

import test_project_tools as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from quality import assess, state_hash
from project_tool import audit, report
from checkpoint import ROOT, fingerprint
from ledger import read_entries, summarize
from snapshot import find_excerpts
from validate_project import validate
from compare_runs import compare, load_manifest


class QualityContractTests(unittest.TestCase):
    setUp = fixture.EvidenceTests.setUp
    run_cli = fixture.EvidenceTests.run_cli

    def complete_record(self):
        p = self.project
        p['research_requirements'] = {'source_kinds': ['document'], 'rationale': 'This question only requires the supplied document'}
        p['evidence'][0].update(locator='source.md, line 1', claim_scope='source_description', support=[
            {'source_id':'S', 'locator':'line 1', 'relation':'supports', 'passage':'Original evidence',
             'reason':'The claim describes this test document, not demand or a real effect'}])
        p['recommended_option_id'] = 'O1'
        p['recommendation_rationale'] = 'Investigate before making a real commitment'
        for i, kind in ((0,'status_quo'), (2,'stop')):
            p['options'].append({'option_id':f'O{i}', 'kind':kind, 'title':kind, 'benefits':['Save resources'],
                'costs_and_risks':['No new learning'], 'objection':'May miss an opportunity', 'evidence_ids':['E1']})
        for section, fields in [('product_strategy', ('audience','job','alternatives','direction','non_goals','economics')),
                                ('communication_strategy', ('audience','situation','barrier','message','proof','channels')),
                                ('validation_plan', ('hypothesis','primary_metric','comparison','window','guardrails','decision_rule'))]:
            p[section] = {field:'Explicit test assumption; not an observed result' for field in fields}
        p['validation_design'] = {'status':'planned', 'purpose':'quality', 'data_origin':'none',
            'sample':{'cases':12,'variants':2,'repeats':1,'planned_outputs':24},
            'thresholds':[{'metric':'critical errors','value':'0','basis':'proposed',
                           'rationale':'Safety gate proposal, not an empirical claim or human approval'}],
            'unit_of_analysis':'one unedited answer', 'comparison':'same model, prompt and source, source context differs',
            'stop_rule':'stop publication if a critical error is observed',
            'inference_limits':'content quality only; no inference about demand'}
        p['strategy_review'] = {'reviewer':'agent self-review, not independent',
            'comparison':'Compare all options on cost, learning and risk',
            'strongest_objection':'A prepared explanation may conceal raw model errors',
            'reversal_condition':'After a controlled quality test, reconsider building',
            'evidence_limits':'No users, no market or commercial result', 'state_hash':'pending'}
        self.path = self.root / 'project.json'
        p['strategy_review']['state_hash'] = state_hash(p, self.path, ROOT)
        (self.root / 'runs.jsonl').write_text('', encoding='utf-8')
        return p

    def refresh(self):
        self.project['strategy_review']['state_hash'] = state_hash(self.project, self.path, ROOT)

    def test_document_only_case_can_pass_with_explicit_requirements(self):
        p = self.complete_record()
        self.assertEqual(validate(p), [])
        result = audit(p, self.path, ready=True, quality=True)
        self.assertTrue(result['ready'], result)
        self.assertFalse(result['content_review']['independent_truth_check'])
        self.assertEqual(result['content_review']['experiment_status'], 'planned')
        self.assertIn('ЧЕРНОВИК', report(p, self.path))
        self.assertIn('Записка для решения', report(p, self.path, final=True))

    def test_missing_task_required_table_blocks_but_irrelevant_table_does_not(self):
        p = self.complete_record()
        self.assertTrue(audit(p, self.path, ready=True)['ready'])
        p['research_requirements']['source_kinds'].append('table')
        self.assertFalse(audit(p, self.path, ready=True)['ready'])

    def test_structural_pass_is_not_content_review(self):
        p = self.complete_record()
        del p['strategy_review']
        self.assertTrue(audit(p, self.path, ready=True)['ready'])
        self.assertFalse(audit(p, self.path, ready=True, quality=True)['ready'])
        with self.assertRaisesRegex(ValueError, 'Final report'):
            report(p, self.path, final=True)

    def test_changed_task_or_source_invalidates_self_review(self):
        p = self.complete_record()
        p['constraints'] = ['No developer available']
        self.assertIn('stale', ' '.join(assess(p, self.path, ROOT)['blockers']))
        self.refresh()
        (self.root / 'source.md').write_text('Original evidence with contradictory context', encoding='utf-8')
        self.assertIn('stale', ' '.join(assess(p, self.path, ROOT)['blockers']))

    def test_url_or_wrong_quote_does_not_establish_support(self):
        p = self.complete_record()
        p['evidence'][0]['support'][0]['passage'] = 'Not actually in the source'
        self.refresh()
        self.assertIn('does not match', ' '.join(assess(p, self.path, ROOT)['blockers']))
        p['evidence'][0]['support'] = []
        self.assertIn('URL alone', ' '.join(assess(p, self.path, ROOT)['blockers']))

    def test_summary_and_general_guidance_cannot_prove_market_demand(self):
        p = self.complete_record()
        p['sources'][0]['content_kind'] = 'summary'
        p['evidence'][0]['claim_scope'] = 'market_demand'
        blockers = ' '.join(assess(p, self.path, ROOT)['blockers'])
        self.assertIn('source summary', blockers)
        self.assertIn('not market-demand', blockers)

    def test_false_completed_test_and_sample_count_are_blocked(self):
        p = self.complete_record()
        p['validation_design']['sample']['planned_outputs'] = 12
        p['validation_design']['status'] = 'completed'
        self.assertEqual(validate(p), [])
        blockers = ' '.join(assess(p, self.path, ROOT)['blockers'])
        self.assertIn('= 24', blockers)
        self.assertIn('results artifact', blockers)
        self.assertIn('data_origin=none', blockers)

    def test_threshold_approval_and_observed_basis_require_references(self):
        p = self.complete_record()
        threshold = p['validation_design']['thresholds'][0]
        threshold['basis'] = 'owner_agreed'
        self.assertIn('agreement_reference', ' '.join(validate(p)))
        threshold['basis'] = 'empirical'
        self.assertIn('evidence_ids', ' '.join(validate(p)))

    def test_quote_marked_not_found_cannot_support_a_claim(self):
        p = self.complete_record()
        p['sources'][0]['quote_checks'] = [
            {'excerpt':'Original evidence','found':False}, {'excerpt':'another quote','found':True}]
        self.refresh()
        self.assertIn('actually found', ' '.join(assess(p, self.path, ROOT)['blockers']))

    def test_results_artifact_must_be_a_registered_source(self):
        p = self.complete_record()
        (self.root / 'unrelated.md').write_text('Unverified report',encoding='utf-8')
        p['validation_design'].update(status='completed',data_origin='synthetic',
            results={'artifact_path':'unrelated.md','source_ids':['S'],'summary':'Declared result'})
        self.refresh()
        self.assertIn('registered result-source', ' '.join(assess(p, self.path, ROOT)['blockers']))

    def test_retired_evidence_can_be_preserved_without_approving_it(self):
        p = self.complete_record()
        p['evidence'].append({'evidence_id':'OLD','claim':'Earlier withdrawn claim','claim_type':'hypothesis',
            'source_ids':[],'method':'Old draft','status':'withdrawn','limitations':'No longer a basis'})
        self.refresh()
        result = audit(p, self.path, ready=True, quality=True)
        self.assertTrue(result['ready'],result)
        self.assertTrue(result['advisories'])

    def test_circular_justification_is_rejected(self):
        self.project['evidence'][0]['related_evidence_ids'] = ['E2']
        self.assertIn('circular', ' '.join(validate(self.project)))

    def test_retrospective_logging_does_not_manufacture_duration(self):
        path = self.root / 'project.json'
        self.assertEqual(self.run_cli('ledger.py','begin',path,'--key','past','--step','research',
                         '--action','Past research','--retrospective').returncode, 0)
        self.assertEqual(self.run_cli('ledger.py','finish',path,'--key','past').returncode, 0)
        entries = read_entries(self.root / 'ledger.jsonl')
        self.assertNotIn('duration_s', entries[-1])
        self.assertNotIn('elapsed_s', entries[-1])
        self.assertEqual(summarize(entries)['totals']['unknown_duration_actions'], 1)

    def test_measured_zero_duration_is_not_replaced_by_elapsed(self):
        path = self.root / 'project.json'
        self.assertEqual(self.run_cli('ledger.py','begin',path,'--key','zero','--step','research','--action','Check').returncode,0)
        self.assertEqual(self.run_cli('ledger.py','finish',path,'--key','zero','--duration-s','0','--duration-basis','measured').returncode,0)
        entry = read_entries(self.root / 'ledger.jsonl')[-1]
        self.assertEqual(entry['duration_s'], 0)
        self.assertEqual(entry['duration_basis'], 'measured')
        self.assertIn('elapsed_s', entry)

    def test_numeric_duration_and_token_estimate_require_measurement_basis(self):
        path = self.root / 'project.json'
        for flags in (['--duration-s','10'], ['--estimate-chars','100','50']):
            result = self.run_cli('ledger.py','log',path,'--step','research','--action','Check',*flags)
            self.assertEqual(result.returncode, 2)

    def test_quote_case_and_letters_are_not_silently_changed(self):
        self.assertFalse(find_excerpts('Ёж', ['еж'])[0]['found'])
        self.assertTrue(find_excerpts('One\n sentence', ['One sentence'])[0]['found'])

    def test_snapshot_provenance_cannot_be_forged_and_paths_are_safe(self):
        path = self.root / 'project.json'
        path.write_text(json.dumps(self.project),encoding='utf-8')
        for flags in (['--source-id','../escape'], ['--source-id','S','--stdin','--via','http_snapshot'],
                      ['--source-id','S','--stdin','--content-kind','summary','--excerpt','Quote']):
            result = self.run_cli('snapshot.py',path,'--url','https://example.org',*flags)
            self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'sources').exists())

    def test_same_version_continuations_do_not_prove_improvement(self):
        run = dict(task_hash='x',material_hashes=['y'],model='same',model_settings={},tools=[],
                   time_budget_seconds=60,session_mode='continuation',agent_revision='v3',mode='agent')
        result = compare(run,copy.deepcopy(run),'version_comparison')
        self.assertFalse(result['comparable'])
        self.assertIn('Same agent revision', ' '.join(result['mismatches']))
        self.assertTrue(compare(run,copy.deepcopy(run),'behavioral_repeat')['comparable'])

    def test_benchmark_hashes_real_artifacts_and_rejects_mismatch(self):
        for name, body in [('task.md','same task'),('answer.md','answer')]:
            (self.root / name).write_text(body,encoding='utf-8')
        manifest = dict(task_path='task.md',material_paths=[],answer_path='answer.md',model='same',
                        model_settings={},tools=[],time_budget_seconds=60,session_mode='fresh',agent_revision='v3',mode='agent')
        path = self.root / 'run.json'
        path.write_text(json.dumps(manifest),encoding='utf-8')
        first = load_manifest(path)
        (self.root / 'task.md').write_text('changed task',encoding='utf-8')
        second = load_manifest(path)
        self.assertFalse(compare(first,second,'behavioral_repeat')['comparable'])


if __name__ == '__main__':
    unittest.main()
