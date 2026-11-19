import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import unittest

import test_follow_up as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, save_checkpoint, write_state
from decision_passport import ANSWER_KEYS, build, confirmation_states, markdown, record_answer, request, version
from feasibility import baseline as feasibility_baseline
from material_changes import enable, inspect, prepare
from project_tool import load
from quality import state_hash
from research_selection import baseline as research_baseline
from resume_summary import acknowledge
from start import restore
from validate_project import validate


class PassportTests(unittest.TestCase):
    setUp = fixture.FollowUpTests.setUp
    run_cli = fixture.FollowUpTests.run_cli

    def case(self, *, tracking=True):
        shutil.copytree(ROOT/'examples/research-branches-case',self.root,dirs_exist_ok=True)
        self.path=self.root/'project.json';self.project=load(self.path)
        if tracking: enable(self.project,self.path,ROOT);self.project=load(self.path);self.refresh()

    def refresh(self):
        self.project['feasibility_reviews'][-1]['baseline']=feasibility_baseline(self.project,self.path,ROOT)
        self.project['research_selection_reviews'][-1]['baseline']=research_baseline(self.project,self.path,ROOT)
        self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT)
        write_state(self.path,self.project)

    def reply(self, cid='A1', *, kind='recommendation', ref='/recommended_option_id', outcome='approved', **changes):
        scope=request(self.project,self.path,ROOT,kind,ref)
        answer={k:v for k,v in scope.items() if k in ANSWER_KEYS}
        answer.update(confirmation_id=cid,outcome=outcome,statement='Authored fictional owner explicitly '+outcome+' the named '+kind+' scope for this exact version; not a real approval',
                      confirmed_at=datetime.now(timezone.utc).isoformat(),confirmed_by='Fictional owner')
        answer.update(changes)
        file=self.root/(cid+'.json');file.write_text(json.dumps(answer,ensure_ascii=False,indent=2),encoding='utf-8')
        return file,answer

    def record(self, file):
        result=record_answer(self.project,self.path,ROOT,file);self.project=load(self.path);return result

    def assessment(self, conclusion='unknown'):
        self.refresh();review=prepare(self.project,self.path,ROOT)
        review.update(reviewer='Authored agent self-review',conclusion=conclusion,rationale='Compare authored grounds and resource conditions; no actual human agreement')
        for effect in review['effects']:
            effect.update(materiality='uncertain' if conclusion=='unknown' else 'material',decision_effect=conclusion,
                          evidence_ids=['F_S'] if conclusion=='unchanged' else [],analysis=review['rationale'])
        save_checkpoint(self.project,self.path,'Authored reassessment',reviewed_changes=True,change_review=review)
        self.project=load(self.path)

    def test_passport_is_derived_read_only_and_reuses_the_four_point_summary(self):
        self.case();before=self.path.read_bytes();ledger=(self.root/'ledger.jsonl').read_bytes()
        a=build(self.path);b=build(self.path)
        self.assertEqual(a,b);self.assertEqual(a['resume_summary'],restore(self.path)['resume_summary'])
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(ledger,(self.root/'ledger.jsonl').read_bytes())
        self.assertEqual(a['recommendation']['option_id'],'O1');self.assertTrue(a['sources']);self.assertTrue(a['evidence'])
        self.assertTrue(a['unknowns']);self.assertTrue(a['revisit_conditions'])

    def test_legacy_choice_or_plan_permission_is_not_a_versioned_recommendation_approval(self):
        self.case(tracking=False);self.project['chosen_option_id']='O1'
        self.project['commitments']=[{'owner':'Fictional role','metric':'fixture checks','due':'2099-01-01','review_trigger':'Authored owner review'}]
        write_state(self.path,self.project)
        card=build(self.path)
        self.assertEqual(card['version_mode'],'legacy_read_only');self.assertFalse(card['confirmations'])
        self.assertTrue(any(r['status']=='version_not_recorded' for r in card['legacy_records']))
        file,_=self.reply()
        with self.assertRaisesRegex(ValueError,'material-v1'):self.record(file)

    def test_explicit_recommendation_answer_records_who_scope_time_and_version(self):
        self.case();file,answer=self.reply();old=version(self.project,self.path,ROOT);chosen=self.project.get('chosen_option_id')
        self.assertTrue(self.record(file)['recorded']);card=build(self.path);row=card['confirmations'][-1]
        self.assertEqual(row['status'],'current');self.assertEqual(row['confirmed_by'],'Fictional owner')
        self.assertEqual(row['confirmed_at'],answer['confirmed_at']);self.assertEqual(row['decision_version'],old)
        self.assertEqual(card['version'],old);self.assertEqual(self.project.get('chosen_option_id'),chosen)
        self.assertFalse(row['identity_verified']);self.assertEqual(restore(self.path)['resume_summary']['owner']['status'],'responded')

    def test_permission_data_and_recommendation_never_promote_each_other(self):
        self.case();file,_=self.reply('P',kind='permission',ref='option:O1');self.record(file)
        file,_=self.reply('D',kind='data',ref='source:S');self.record(file)
        self.assertFalse(any(r['kind']=='recommendation' for r in build(self.path)['confirmations']))
        self.assertTrue(restore(self.path)['resume_summary']['owner']['questions'])
        file,_=self.reply('R');self.record(file)
        self.assertEqual({r['kind'] for r in build(self.path)['confirmations']},{'permission','data','recommendation'})
        self.assertIsNone(self.project['chosen_option_id'])

    def test_generic_yes_and_view_receipt_are_not_accepted_as_confirmation(self):
        self.case();file,_=self.reply(statement='да')
        with self.assertRaisesRegex(ValueError,'Generic'):self.record(file)
        summary=restore(self.path)['resume_summary'];acknowledge(self.path,summary['version_hash'],'Authored agent','Read only')
        self.project=load(self.path);self.assertFalse(build(self.path)['confirmations'])
        file.write_text(json.dumps(self.project['follow_up_reviews'][-1]),encoding='utf-8')
        with self.assertRaises(ValueError):self.record(file)

    def test_exact_reply_is_idempotent_and_reused_id_cannot_overwrite_history(self):
        self.case();file,answer=self.reply();self.record(file)
        before=self.path.read_bytes();ledger=(self.root/'ledger.jsonl').read_bytes()
        self.assertFalse(self.record(file)['recorded']);self.assertEqual(before,self.path.read_bytes());self.assertEqual(ledger,(self.root/'ledger.jsonl').read_bytes())
        answer['outcome']='rejected';file.write_text(json.dumps(answer),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'confirmation_id'):self.record(file)

    def test_old_confirmation_is_historical_after_source_change(self):
        self.case();file,_=self.reply();self.record(file);old=build(self.path)['version']
        source=self.root/'inputs/active-condition.md';source.write_text(source.read_text(encoding='utf-8')+'\nAuthored changed condition\n',encoding='utf-8')
        card=build(self.path);self.assertNotEqual(card['version'],old);self.assertEqual(card['confirmations'][-1]['status'],'historical')
        self.assertTrue(any('ACTIVE_0' in e['impact']['evidence_ids'] for e in card['changes']['events']))
        self.assertTrue(card['blockers']);self.assertIn('Разобрать изменения',card['resume_summary']['next_step']['text'])

    def test_stale_or_wrong_scope_reply_cannot_be_recorded(self):
        self.case();file,_=self.reply(subject_version='0'*64)
        with self.assertRaisesRegex(ValueError,'subject version'):self.record(file)
        file,_=self.reply('Wrong',project_id='another-project')
        with self.assertRaises(ValueError):self.record(file)

    def test_pending_source_changes_cannot_be_accepted_by_saving_an_answer(self):
        self.case();self.project['sources'][0]['author']='New author';write_state(self.path,self.project)
        file,_=self.reply();before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.record(file)
        self.assertEqual(before,self.path.read_bytes());self.assertFalse(build(self.path)['confirmations'])

    def test_changed_reply_file_does_not_leave_approval_current(self):
        self.case();file,_=self.reply();self.record(file);file.write_text('{}',encoding='utf-8')
        self.assertEqual(build(self.path)['confirmations'][-1]['status'],'reference_changed_or_missing')
        self.assertTrue(restore(self.path)['resume_summary']['owner']['questions'])

    def test_reply_layout_and_windows_line_endings_preserve_the_answer(self):
        self.case();file,answer=self.reply();self.record(file)
        file.write_bytes(json.dumps(answer,sort_keys=True,indent=4).replace('\n','\r\n').encode('utf-8'))
        self.assertEqual(build(self.path)['confirmations'][-1]['status'],'current')
        self.assertFalse(self.record(file)['recorded'])

    def test_later_rejection_supersedes_approval_without_erasing_it(self):
        self.case();file,_=self.reply();self.record(file)
        file,_=self.reply('R2',outcome='rejected');self.record(file)
        rows=build(self.path)['confirmations'];self.assertEqual(rows[0]['status'],'superseded')
        self.assertEqual(rows[1]['outcome'],'rejected');self.assertIn('Пересмотреть рекомендацию',restore(self.path)['resume_summary']['next_step']['text'])
        self.assertIsNone(self.project['chosen_option_id'])

    def test_cosmetic_change_preserves_exact_approval(self):
        self.case();file,_=self.reply();self.record(file)
        self.project['sources'][0]['title']='New display title';write_state(self.path,self.project)
        self.assertEqual(build(self.path)['confirmations'][-1]['status'],'current')

    def test_changed_research_condition_invalidates_the_old_scoped_approval(self):
        self.case();file,_=self.reply();self.record(file);old=build(self.path)['recommendation']['version']
        self.project['research_selection_reviews'][-1]['gaps'][0]['answer_branches'][0]['next_step']='Different action requiring a new scoped answer'
        write_state(self.path,self.project)
        card=build(self.path);self.assertNotEqual(card['recommendation']['version'],old);self.assertEqual(card['confirmations'][-1]['status'],'historical')

    def test_return_to_old_source_value_does_not_revive_the_old_answer(self):
        self.case();file,_=self.reply();self.record(file)
        source=self.root/'inputs/active-condition.md';old=source.read_bytes()
        source.write_bytes(old+b'\nAuthored extra condition\n');self.assessment()
        source.write_bytes(old);self.assessment()
        self.assertEqual(build(self.path)['confirmations'][0]['status'],'historical')

    def test_new_current_answer_resolves_the_versioned_change_request(self):
        self.case();self.project['sources'][0]['author']='Uncertain attribution';write_state(self.path,self.project);self.assessment()
        self.assertTrue(inspect(self.project,self.path,ROOT)['human_questions'])
        file,_=self.reply();self.record(file)
        self.assertFalse(inspect(self.project,self.path,ROOT)['human_questions'])
        self.assertEqual(inspect(self.project,self.path,ROOT)['approval_for_current_version'],'approved')

    def test_alternatives_do_not_invent_rejection_reasons(self):
        self.case();card=build(self.path)
        self.assertTrue(all(o['selection_status']=='not_recorded' for o in card['alternatives'] if not o['is_recommended']))
        self.project['options'][0]['selection_assessment']={'status':'rejected','reason':'Authored comparative judgement based on stated scope','evidence_ids':['F_S']}
        self.assertNotEqual(self.project['options'][0]['option_id'],'O1')
        write_state(self.path,self.project);self.assertEqual(build(self.path)['alternatives'][0]['selection_status'],'rejected')

    def test_future_or_mixed_context_answers_are_rejected(self):
        self.case();file,_=self.reply(confirmed_at='2099-01-01T00:00:00Z')
        with self.assertRaisesRegex(ValueError,'future'):self.record(file)
        file,_=self.reply('Live',context='live_project')
        with self.assertRaisesRegex(ValueError,'simulation'):self.record(file)

    def test_identity_may_be_unknown_without_inventing_a_name(self):
        self.case();file,answer=self.reply();answer.pop('confirmed_by');file.write_text(json.dumps(answer),encoding='utf-8');self.record(file)
        self.assertNotIn('confirmed_by',build(self.path)['confirmations'][-1]);self.assertIn('Кто: не указан',markdown(build(self.path)))

    def test_history_and_confirmation_fields_are_validated(self):
        self.case();file,_=self.reply();self.record(file);self.assertEqual(validate(self.project),[])
        p=copy.deepcopy(self.project);p['checkpoints'][-1]['human_confirmation']['decision_version']='0'*64
        self.assertTrue(validate(p))

    def test_cli_card_request_and_guarded_exports(self):
        self.case();out=self.run_cli('start.py',self.path,'--passport','--json')
        self.assertEqual(out.returncode,0,out.stderr);self.assertIn('confirmations',json.loads(out.stdout))
        target=self.root/'passport.md';out=self.run_cli('decision_passport.py',self.path,'--out',target)
        self.assertEqual(out.returncode,0,out.stderr);self.assertIn('Паспорт решения',target.read_text(encoding='utf-8'))
        before=self.path.read_bytes();out=self.run_cli('decision_passport.py',self.path,'--out',self.path)
        self.assertNotEqual(out.returncode,0);self.assertEqual(before,self.path.read_bytes())

    def test_missing_newer_reply_does_not_revive_a_superseded_approval(self):
        self.case();file,_=self.reply();self.record(file)
        newer,_=self.reply('R2',outcome='rejected');self.record(newer);newer.unlink()
        rows=build(self.path)['confirmations']
        self.assertEqual(rows[0]['status'],'superseded')
        self.assertEqual(rows[1]['status'],'reference_changed_or_missing')
        self.assertNotEqual(inspect(self.project,self.path,ROOT)['approval_for_current_version'],'approved')

    def test_confirmation_inputs_are_protected_from_report_overwrite(self):
        from output_guard import check_output
        self.case();file,_=self.reply();self.record(file)
        with self.assertRaises(ValueError):check_output(self.project,self.path,file)

    def test_ambiguous_duplicate_reply_fields_are_rejected(self):
        self.case();file,_=self.reply()
        raw=file.read_text(encoding='utf-8').replace('"outcome": "approved"','"outcome": "rejected", "outcome": "approved"')
        file.write_text(raw,encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Duplicate reply field'):self.record(file)

    def test_malformed_confirmation_snapshot_is_reported_without_crashing(self):
        self.case();file,_=self.reply();self.record(file)
        for bad in (None,[],{}):
            p=copy.deepcopy(self.project);p['checkpoints'][-1]['change_snapshot']=bad
            with self.subTest(snapshot=bad):self.assertTrue(validate(p))

    def test_permission_card_names_the_bounded_scope_and_window(self):
        self.case();file,_=self.reply('P',kind='permission',ref='option:O1');self.record(file)
        row=build(self.path)['confirmations'][-1]
        self.assertIn('2099',row['scope_description']);self.assertIn('Статическая форма',row['scope_description'])

    def test_explicit_rejection_needs_grounds_and_does_not_reject_the_recommendation(self):
        self.case();self.project['options'][0]['selection_assessment']={'status':'rejected','reason':'Reason without a basis','evidence_ids':[]}
        self.assertTrue(validate(self.project))
        self.project['options'][1]['selection_assessment']={'status':'rejected','reason':'Contradicting current recommendation','evidence_ids':['F_S']}
        self.assertTrue(validate(self.project))


if __name__=='__main__':unittest.main()
