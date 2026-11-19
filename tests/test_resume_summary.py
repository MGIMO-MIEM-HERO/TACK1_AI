import copy
import json
from pathlib import Path
import shutil
import sys
import unittest

import test_follow_up as fixture
import test_research_branches as branch_fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, write_state
from follow_up import acknowledge as acknowledge_results, inspect as follow_up, result_version
from material_changes import enable
from project_tool import load
from quality import state_hash
from resume_summary import acknowledge, markdown
from start import restore
from validate_project import validate


class ResumeTests(unittest.TestCase):
    setUp = fixture.FollowUpTests.setUp
    setup_follow_up = fixture.FollowUpTests.setup_follow_up
    complete_record = fixture.FollowUpTests.complete_record
    run_cli = fixture.FollowUpTests.run_cli

    def case(self):
        self.setup_follow_up()
        (self.root/'ledger.jsonl').write_text('',encoding='utf-8')
        self.project['follow_up_context'] = 'authored_example'
        write_state(self.path, self.project)

    def summary(self): return restore(self.path)['resume_summary']

    def seen(self):
        result = acknowledge(self.path, self.summary()['version_hash'], 'Authored agent', 'Read fixture; no owner answer or approval')
        self.project = load(self.path)
        return result

    def test_default_output_is_four_short_points_and_real_detail_path(self):
        self.case(); out = self.run_cli('start.py', self.path)
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = [line for line in out.stdout.splitlines() if line[:2] in ('1.', '2.', '3.', '4.')]
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(len(line) < 230 for line in lines))
        self.assertIn(self.path.resolve().as_posix(), out.stdout)
        self.assertNotIn('Структурная готовность:', out.stdout)
        detailed = self.run_cli('start.py', self.path, '--details')
        self.assertIn('Структурная готовность:', detailed.stdout)
        raw = json.loads(self.run_cli('start.py', self.path, '--json').stdout)
        self.assertEqual(next(iter(raw)), 'resume_summary')
        self.assertIn('audit', raw)

    def test_open_is_read_only_and_does_not_claim_no_historical_changes(self):
        self.case(); before=self.path.read_bytes(); ledger=(self.root/'ledger.jsonl').read_bytes()
        a=self.summary(); b=self.summary()
        self.assertEqual(a,b); self.assertEqual(a['changes']['status'],'first_review')
        self.assertIn('Отметки просмотра ещё нет',a['changes']['text'])
        self.assertEqual(before,self.path.read_bytes()); self.assertEqual(ledger,(self.root/'ledger.jsonl').read_bytes())

    def test_explicit_view_is_not_approval_or_a_source_checkpoint(self):
        self.case(); before=copy.deepcopy(self.project); version=result_version(self.project,self.path,ROOT,self.project['metric_results'][0])
        old_hash=state_hash(self.project,self.path,ROOT)
        self.assertTrue(self.seen()['recorded'])
        for key in ('stage','chosen_option_id','commitments','metric_results','checkpoints','sources','evidence'):
            self.assertEqual(before.get(key),self.project.get(key))
        self.assertEqual(old_hash,state_hash(self.project,self.path,ROOT))
        self.assertEqual(version,result_version(self.project,self.path,ROOT,self.project['metric_results'][0]))
        self.assertFalse(follow_up(self.project,self.path,ROOT)['metric_results'][0]['reviewed'])
        after=self.summary()
        self.assertEqual(after['changes']['status'],'unchanged')
        self.assertEqual(after['owner']['status'],'awaiting_decision')
        self.assertTrue(all(q['seen_in_summary'] for q in after['owner']['questions']))
        self.assertFalse(any(q['reply_recorded'] for q in after['owner']['questions']))

    def test_repeated_acknowledgement_has_no_state_or_ledger_write(self):
        self.case(); self.seen(); before=self.path.read_bytes(); ledger=(self.root/'ledger.jsonl').read_bytes()
        self.assertFalse(self.seen()['recorded'])
        self.assertEqual(before,self.path.read_bytes()); self.assertEqual(ledger,(self.root/'ledger.jsonl').read_bytes())

    def test_source_change_is_visible_and_view_does_not_hide_it_from_audit(self):
        self.case(); self.seen(); (self.root/'source.md').write_text('Original evidence\nNew condition',encoding='utf-8')
        a=self.summary(); self.assertEqual(a['changes']['status'],'changed')
        self.assertIn('source:S',a['changes']['refs'])
        self.assertIn('Разобрать изменения',a['next_step']['text'])
        self.seen()
        self.assertIn('S',restore(self.path)['audit']['health']['changed_sources'])
        self.assertIn('Разобрать изменения',self.summary()['next_step']['text'])

    def test_stale_summary_cannot_be_acknowledged(self):
        self.case(); old=self.summary()['version_hash']
        self.project['sources'][0]['author']='Different author';write_state(self.path,self.project)
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'changed'):acknowledge(self.path,old,'Agent','Old view')
        self.assertEqual(before,self.path.read_bytes())

    def test_cosmetic_title_does_not_resurface_as_new_material_change(self):
        self.case(); enable(self.project,self.path,ROOT);self.project=load(self.path); self.seen()
        self.project['sources'][0]['title']='Display-only label';write_state(self.path,self.project)
        self.assertEqual(self.summary()['changes']['status'],'unchanged')
        self.assertTrue(all(q['seen_in_summary'] for q in self.summary()['owner']['questions']))

    def test_source_reliability_changes_are_visible_even_without_a_strategy_review(self):
        self.case();self.project.pop('strategy_review');write_state(self.path,self.project);self.seen()
        self.project['sources'][0]['author']='New uncertain author';write_state(self.path,self.project)
        self.assertEqual(self.summary()['changes']['status'],'changed')
        self.assertIn('source:S',self.summary()['changes']['refs'])

    def test_return_to_prior_value_still_gets_distinct_view_version(self):
        self.case(); self.seen(); initial=self.summary()['version_hash']
        for value in ('3','2'):
            self.project['metric_results'][0]['value']=value;write_state(self.path,self.project)
            s=self.summary(); self.assertEqual(s['changes']['status'],'changed');self.assertNotEqual(s['version_hash'],initial)
            self.seen()
        self.assertEqual(len([r for r in self.project['follow_up_reviews'] if r.get('kind')=='resume']),3)
        self.assertEqual(validate(self.project),[])

    def test_metric_receipts_and_resume_receipts_coexist(self):
        self.case(); self.seen()
        acknowledge_results(self.project,self.path,ROOT,['R1'],'Authored agent','Read metric only')
        self.project=load(self.path)
        self.assertTrue(follow_up(self.project,self.path,ROOT)['metric_results'][0]['reviewed'])
        self.assertFalse(follow_up(self.project,self.path,ROOT)['metric_results'][0]['human_decision_current'])
        self.assertEqual(validate(self.project),[])
        self.assertFalse(self.seen()['recorded'])

    def test_changed_conditions_get_a_new_question_but_unchanged_ones_stay_seen(self):
        self.case(); self.seen(); self.project['commitments'][0]['status']='blocked';write_state(self.path,self.project)
        questions=self.summary()['owner']['questions']
        # The overdue question stays the same until its underlying reason changes.
        self.assertTrue(any(q['question_id']=='result:R1' and q['seen_in_summary'] for q in questions))
        self.project['commitments'][0]['due']='2099-01-01';write_state(self.path,self.project)
        q=next(q for q in self.summary()['owner']['questions'] if q['object_ref']=='/commitments/0')
        self.assertFalse(q['seen_in_summary'])

    def test_replay_does_not_apply_future_view_receipts(self):
        self.case(); self.seen(); receipt=self.project['follow_up_reviews'][-1]
        receipt['reviewed_at']='2099-01-01T00:00:00Z';write_state(self.path,self.project)
        self.assertEqual(self.summary()['changes']['status'],'first_review')
        result=self.run_cli('start.py',self.path,'--acknowledge-summary',receipt['version_hash'],'--reviewer','A','--note','N','--as-of','2026-11-19T00:00:00Z')
        self.assertNotEqual(result.returncode,0)

    def test_malformed_or_approval_shaped_view_receipts_are_rejected(self):
        self.case(); self.seen()
        for key,value in [('version_hash','0'*64),('observations',[]),('approved',True),('kind','unknown')]:
            p=copy.deepcopy(self.project);p['follow_up_reviews'][-1][key]=value
            with self.subTest(key=key):self.assertTrue(validate(p))

    def test_review_requires_actual_note_and_damaged_ledger_is_not_acknowledged(self):
        self.case(); version=self.summary()['version_hash']
        with self.assertRaises(ValueError):acknowledge(self.path,version,'','')
        (self.root/'ledger.jsonl').write_text('{"seq": 1, "hash":"wrong"}\n',encoding='utf-8')
        with self.assertRaises(ValueError):acknowledge(self.path,version,'Agent','Viewed')

    def test_no_checkpoint_is_explicitly_unknown(self):
        self.case();self.project['checkpoints']=[];write_state(self.path,self.project)
        self.assertIn('Контрольной точки',self.summary()['changes']['text'])

    def test_existing_checkpoint_resume_exposes_the_same_summary(self):
        self.case(); out=self.run_cli('checkpoint.py',self.path,'resume')
        self.assertEqual(out.returncode,0,out.stderr)
        self.assertEqual(json.loads(out.stdout)['resume_summary'],self.summary())

    def test_unknown_resources_override_an_old_action_without_selecting_paper(self):
        shutil.copytree(ROOT/'examples/research-branches-case',self.root,dirs_exist_ok=True)
        self.path=self.root/'project.json';self.project=load(self.path)
        self.project['next_action']='Start building immediately'
        from feasibility import baseline as feasibility_baseline
        from research_selection import baseline as research_baseline
        self.project['feasibility_reviews'][-1]['baseline']=feasibility_baseline(self.project,self.path,ROOT)
        self.project['research_selection_reviews'][-1]['baseline']=research_baseline(self.project,self.path,ROOT)
        self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT)
        write_state(self.path,self.project)
        s=self.summary()
        self.assertIn('unknown',s['next_step']['text']);self.assertIn('W1',s['next_step']['text'])
        self.assertIsNone(load(self.path)['chosen_option_id'])

    def test_unfinished_action_precedes_old_next_action(self):
        from ledger import append
        self.case();append(self.path,{'action':'authored interrupted check','step':'research','status':'started','key':'demo-action'})
        self.assertIn('незавершённых',self.summary()['next_step']['text'])

    def test_explicit_result_decision_removes_its_pending_question(self):
        self.case();self.seen();row=self.project['metric_results'][0]
        row['human_decision']={'reference':'Authored fictional answer, not actual owner approval',
                               'version_hash':result_version(self.project,self.path,ROOT,row)}
        write_state(self.path,self.project)
        self.assertFalse(any(q['question_id']=='result:R1' for q in self.summary()['owner']['questions']))
        self.assertEqual(self.summary()['changes']['status'],'changed')

    def test_open_research_branch_supplies_the_next_step_when_resources_fit(self):
        harness=branch_fixture.BranchTests();harness.setUp();self.addCleanup(harness.doCleanups)
        review,gap=harness.manual()
        gap['answer_branches'][0]['condition'].update(assessment='unknown',evidence_ids=[])
        harness.refresh();write_state(harness.path,harness.project)
        state=restore(harness.path)
        self.assertEqual(state['research_selection']['branch_resolutions'][0]['status'],'insufficient_data')
        self.assertEqual(state['resume_summary']['next_step']['text'],gap['answer_branches'][2]['next_step'])
        self.assertIn('question:Q1',state['resume_summary']['next_step']['refs'])

    def test_known_resource_deficit_does_not_execute_the_paper_branch(self):
        harness=branch_fixture.BranchTests();harness.setUp();self.addCleanup(harness.doCleanups)
        harness.selection();harness.project['feasibility_reviews'][0]['assessments'][0]['resources'][0]['capacity']['hours']=4
        harness.refresh();write_state(harness.path,harness.project)
        state=restore(harness.path)
        self.assertEqual(state['research_selection']['branch_resolutions'][0]['branch_id'],'PAPER')
        self.assertIn('infeasible',state['resume_summary']['next_step']['text'])
        self.assertEqual(load(harness.path)['chosen_option_id'],'O1')


if __name__=='__main__':unittest.main()
