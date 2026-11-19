import copy
import json
from pathlib import Path
import sys
import unittest

import test_follow_up as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, fingerprint, save_checkpoint, write_state
from follow_up import acknowledge, inspect as follow_up, result_version
from material_changes import enable, inspect, prepare, source_version
from project_tool import audit, load, source_health
from quality import state_hash
from start import restore
from validate_project import validate


class MaterialTests(unittest.TestCase):
    setUp = fixture.FollowUpTests.setUp
    complete_record = fixture.FollowUpTests.complete_record
    setup_follow_up = fixture.FollowUpTests.setup_follow_up
    run_cli = fixture.FollowUpTests.run_cli

    def tracked(self, *, json_source=False):
        self.setup_follow_up()
        self.project['follow_up_context'] = 'authored_example'
        self.project['chosen_option_id'] = 'O1'
        if json_source:
            (self.root / 'data.json').write_text('{"a":1, "b":2}', encoding='utf-8')
            self.project['sources'][0]['url_or_path'] = 'data.json'
            self.project['evidence'][0]['claim'] = 'The authored JSON contains key a'
            self.project['evidence'][0]['support'][0]['passage'] = '"a"'
            self.project['checkpoints'][-1]['sources']['S'] = {'location':'data.json', 'fingerprint':fingerprint('data.json',self.root)}
        write_state(self.path, self.project)
        enable(self.project, self.path, ROOT); self.project = load(self.path)
        self.refresh()
        acknowledge(self.project, self.path, ROOT, ['R1'], 'Authored self-review', 'Read synthetic fixture; no human choice')
        self.project = load(self.path)
        return self.project

    def refresh(self):
        self.project['strategy_review']['state_hash'] = state_hash(self.project, self.path, ROOT)
        write_state(self.path, self.project)

    def assessment(self, conclusion='unknown'):
        self.refresh()
        r = prepare(self.project, self.path, ROOT)
        r.update(reviewer='Authored agent self-review, not the owner', conclusion=conclusion,
                 rationale='Explicit comparison of the provided authored conditions, no claim of actual user approval')
        for effect in r['effects']:
            effect.update(analysis='Compared the source, transitive dependencies and the current decision',
                          materiality='material' if conclusion != 'unknown' else 'uncertain',
                          decision_effect=conclusion, evidence_ids=['E1'] if conclusion == 'unchanged' else [])
        return r

    def persist(self, review):
        save_checkpoint(self.project, self.path, 'Authored impact assessment', reviewed_changes=True, change_review=review)
        self.project = load(self.path)

    def test_enable_is_explicit_and_does_not_promote_old_review(self):
        self.setup_follow_up(); old = result_version(self.project, self.path, ROOT, self.project['metric_results'][0])
        self.project['metric_results'][0]['human_decision'] = {'reference':'Fictitious old-version approval', 'version_hash':old}
        write_state(self.path, self.project); enable(self.project, self.path, ROOT); self.project = load(self.path)
        self.assertFalse(follow_up(self.project,self.path,ROOT)['metric_results'][0]['human_decision_current'])
        self.assertTrue(audit(self.project,self.path,quality=True)['content_review']['blockers'])
        self.assertEqual(self.project['metric_results'][0]['human_decision']['version_hash'], old)

    def test_enable_twice_is_idempotent_and_cannot_hide_legacy_source_change(self):
        self.tracked(); before=self.path.read_bytes(); log=(self.root/'ledger.jsonl').read_bytes()
        self.assertFalse(enable(self.project,self.path,ROOT)['recorded'])
        self.assertEqual(before,self.path.read_bytes()); self.assertEqual(log,(self.root/'ledger.jsonl').read_bytes())
        self.project.pop('change_tracking')
        self.project['checkpoints'] = [cp for cp in self.project['checkpoints'] if 'change_snapshot' not in cp]
        self.setup_follow_up(); (self.root/'source.md').write_text('Changed before migration',encoding='utf-8')
        with self.assertRaises(ValueError): enable(self.project,self.path,ROOT)

    def test_source_title_is_logged_but_does_not_invalidate_review_or_receipt(self):
        self.tracked(); content=state_hash(self.project,self.path,ROOT)
        version=result_version(self.project,self.path,ROOT,self.project['metric_results'][0])
        self.project['sources'][0]['title']='Clearer display label'; write_state(self.path,self.project)
        changes=inspect(self.project,self.path,ROOT)
        self.assertEqual(changes['events'][0]['classification'],'cosmetic'); self.assertFalse(changes['needs_assessment'])
        self.assertEqual(content,state_hash(self.project,self.path,ROOT))
        self.assertEqual(version,result_version(self.project,self.path,ROOT,self.project['metric_results'][0]))
        self.assertFalse(source_health(self.project,self.path)['changed_sources'])
        self.assertTrue(follow_up(self.project,self.path,ROOT)['metric_results'][0]['reviewed'])
        self.assertFalse(changes['human_questions'])
        save_checkpoint(self.project,self.path,'Display label clarified'); self.project=load(self.path)
        cp=self.project['checkpoints'][-1]
        self.assertEqual(cp['change_review']['events'][0]['kind'],'source_metadata')
        self.assertIsNone(cp['change_review']['owner_question'])

    def test_json_layout_and_key_order_preserve_current_versions(self):
        self.tracked(json_source=True); version=inspect(self.project,self.path,ROOT)['after_version']
        (self.root/'data.json').write_text('{\n  "b": 2,\n  "a": 1\n}\n',encoding='utf-8')
        changes=inspect(self.project,self.path,ROOT)
        self.assertEqual(changes['after_version'],version)
        self.assertTrue(all(e['classification']=='cosmetic' for e in changes['events']))
        self.assertTrue(follow_up(self.project,self.path,ROOT)['metric_results'][0]['reviewed'])
        self.assertTrue(audit(self.project,self.path,ready=True,quality=True)['ready'])
        save_checkpoint(self.project,self.path,'JSON formatted'); self.project=load(self.path)
        self.assertFalse(inspect(self.project,self.path,ROOT)['events'])

    def test_json_precision_or_array_order_is_not_cosmetic(self):
        self.tracked(json_source=True)
        for content in ('{"a":1.00,"b":2}','{"a":1,"b":[2,1]}'):
            (self.root/'data.json').write_text(content,encoding='utf-8')
            self.assertTrue(inspect(self.project,self.path,ROOT)['needs_assessment'])

    def test_ambiguous_duplicate_json_keys_are_never_canonicalised(self):
        self.tracked(json_source=True)
        (self.root/'data.json').write_text('{"a":1,"a":2}',encoding='utf-8')
        a=source_version(self.project,self.project['sources'][0],self.root)
        self.assertTrue(inspect(self.project,self.path,ROOT)['needs_assessment'])
        (self.root/'data.json').write_text('{"a":2, "a":1}',encoding='utf-8')
        self.assertNotEqual(a,source_version(self.project,self.project['sources'][0],self.root))

    def test_author_date_scope_and_verification_are_not_blanket_ignored(self):
        self.tracked(); original=copy.deepcopy(self.project)
        for key,value in [('author','Different author'),('accessed_at','2026-11-19'),('valid_until','2099-01-01'),
                          ('scope','Different applicability'),('verification','search_snippet')]:
            self.project=copy.deepcopy(original); self.project['sources'][0][key]=value
            changes=inspect(self.project,self.path,ROOT)
            with self.subTest(key=key):
                self.assertTrue(changes['needs_assessment']); self.assertTrue(source_health(self.project,self.path)['changed_sources'])

    def test_evidence_status_and_method_changes_have_explicit_uncertainty(self):
        self.tracked()
        for key,value in [('status','corroborated'),('method','Different measurement process')]:
            original=copy.deepcopy(self.project); self.project['evidence'][0][key]=value
            changes=inspect(self.project,self.path,ROOT)
            self.assertTrue(changes['needs_assessment'])
            self.assertIn('E2',changes['events'][0]['impact']['evidence_ids'])
            self.project=original

    def test_content_change_tracks_transitive_grounds_and_requires_analysis(self):
        self.tracked(); (self.root/'source.md').write_text('Original evidence\nNew condition',encoding='utf-8')
        changes=inspect(self.project,self.path,ROOT)
        self.assertTrue(changes['needs_assessment'])
        self.assertEqual(changes['events'][0]['impact']['evidence_ids'],['E1','E2'])
        self.assertEqual(changes['events'][0]['impact']['option_ids'],['O0','O1','O2'])
        self.assertFalse(audit(self.project,self.path,ready=True,quality=True)['ready'])
        with self.assertRaises(ValueError): save_checkpoint(self.project,self.path,'Blind reset',reviewed_changes=True)

    def test_verified_irrelevant_edit_preserves_history_without_owner_request(self):
        self.tracked(); (self.root/'source.md').write_text('Original evidence\nAn unrelated authored footnote',encoding='utf-8')
        r=self.assessment('unchanged'); self.persist(r)
        self.assertFalse(inspect(self.project,self.path,ROOT)['human_questions'])
        self.assertEqual(self.project['checkpoints'][-1]['change_review']['assessment']['conclusion'],'unchanged')
        self.refresh(); self.assertTrue(audit(self.project,self.path,ready=True,quality=True)['ready'])

    def test_unknown_impact_is_visible_and_keeps_one_versioned_owner_request(self):
        self.tracked(); self.project['sources'][0]['author']='Unverified author'; write_state(self.path,self.project)
        self.persist(self.assessment('unknown'))
        a=inspect(self.project,self.path,ROOT); self.assertEqual(len(a['human_questions']),1)
        self.project['sources'][0]['title']='Cosmetic label'; write_state(self.path,self.project)
        save_checkpoint(self.project,self.path,'Cosmetic save'); self.project=load(self.path)
        b=inspect(self.project,self.path,ROOT)
        self.assertEqual(a['human_questions'],b['human_questions'])
        questions=[q for q in follow_up(self.project,self.path,ROOT)['human_questions'] if q['question_id'].startswith('change:')]
        self.assertEqual(len(questions),1)

    def test_new_recommendation_requires_owner_and_keeps_historical_choice(self):
        self.tracked(); self.project['recommended_option_id']='O2'; self.project['recommendation_rationale']='Explicit authored new proposal'
        write_state(self.path,self.project)
        bad=self.assessment('unchanged')
        with self.assertRaisesRegex(ValueError,'different recommended option'): self.persist(bad)
        self.persist(self.assessment('changed'))
        changes=inspect(self.project,self.path,ROOT)
        self.assertEqual(self.project['chosen_option_id'],'O1'); self.assertEqual(self.project['recommended_option_id'],'O2')
        self.assertEqual(len(changes['human_questions']),1); self.assertEqual(changes['approval_for_current_version'],'not_inferred')

    def test_repeated_record_of_same_event_is_noop(self):
        self.tracked(); self.project['sources'][0]['author']='New author'; write_state(self.path,self.project)
        review=self.assessment(); rpath=self.root/'assessment.json'; rpath.write_text(json.dumps(review),encoding='utf-8')
        a=self.run_cli('material_changes.py','record',self.path,'--review',rpath)
        self.assertEqual(a.returncode,0,a.stderr)
        before=self.path.read_bytes(); log=(self.root/'ledger.jsonl').read_bytes()
        b=self.run_cli('material_changes.py','record',self.path,'--review',rpath)
        self.assertEqual(b.returncode,0,b.stderr); self.assertFalse(json.loads(b.stdout)['recorded'])
        self.assertEqual(before,self.path.read_bytes()); self.assertEqual(log,(self.root/'ledger.jsonl').read_bytes())

    def test_stale_assessment_cannot_cover_new_events(self):
        self.tracked(); self.project['sources'][0]['author']='First author'; write_state(self.path,self.project)
        review=self.assessment(); self.project['sources'][0]['author']='Second author'; write_state(self.path,self.project)
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'stale'): self.persist(review)
        self.assertEqual(before,self.path.read_bytes())

    def test_no_impact_assertion_needs_factual_basis_and_uncertainty_is_not_suppressed(self):
        self.tracked(); self.project['sources'][0]['author']='Unknown author'; write_state(self.path,self.project)
        r=self.assessment('unchanged'); r['effects'][0]['evidence_ids']=[]
        with self.assertRaises(ValueError): self.persist(r)
        r=self.assessment('unchanged'); r['effects'][0]['materiality']='uncertain'
        with self.assertRaises(ValueError): self.persist(r)

    def test_old_metric_approval_does_not_revive_when_value_returns(self):
        self.tracked(); row=self.project['metric_results'][0]
        old=result_version(self.project,self.path,ROOT,row)
        row['human_decision']={'reference':'Authored fictional approval for exactly this version','version_hash':old}
        write_state(self.path,self.project); self.persist(self.assessment())
        self.assertTrue(follow_up(self.project,self.path,ROOT)['metric_results'][0]['human_decision_current'])
        for value in ('3','2'):
            self.project['metric_results'][0]['value']=value; write_state(self.path,self.project)
            self.persist(self.assessment())
            current=follow_up(self.project,self.path,ROOT)['metric_results'][0]
            self.assertNotEqual(current['version_hash'],old); self.assertFalse(current['human_decision_current'])
            self.assertEqual(current['human_decision']['version_hash'],old)

    def test_cosmetic_change_does_not_create_a_new_confirmation(self):
        self.tracked(); old=result_version(self.project,self.path,ROOT,self.project['metric_results'][0])
        decision={'reference':'Authored fictional approval for current version','version_hash':old}
        self.project['metric_results'][0]['human_decision']=decision
        write_state(self.path,self.project); self.persist(self.assessment())
        self.project['sources'][0]['title']='UI label only'; write_state(self.path,self.project)
        state=follow_up(self.project,self.path,ROOT)['metric_results'][0]
        self.assertTrue(state['human_decision_current']); self.assertEqual(state['human_decision'],decision)

    def test_opening_is_read_only_and_event_ids_are_stable(self):
        self.tracked(); self.project['sources'][0]['author']='Review required'; write_state(self.path,self.project)
        before=self.path.read_bytes(); log=(self.root/'ledger.jsonl').read_bytes()
        a=restore(self.path)['material_changes']; b=restore(self.path)['material_changes']
        self.assertEqual(a,b); self.assertEqual(before,self.path.read_bytes()); self.assertEqual(log,(self.root/'ledger.jsonl').read_bytes())

    def test_history_is_validated_and_tracking_cannot_be_removed_silently(self):
        self.tracked(); self.assertEqual(validate(self.project),[])
        for field,value in [('decision_version','0'*64),('input_digest','0'*64),('sources',[])]:
            p=copy.deepcopy(self.project); p['checkpoints'][-1]['change_snapshot'][field]=value
            with self.subTest(field=field): self.assertTrue(validate(p))
        p=copy.deepcopy(self.project); p.pop('change_tracking'); self.assertTrue(validate(p))

    def test_legacy_hashes_and_readers_are_unchanged(self):
        self.setup_follow_up(); before=state_hash(self.project,self.path,ROOT)
        self.project['sources'][0]['title']='Legacy hash still includes title'
        self.assertNotEqual(before,state_hash(self.project,self.path,ROOT))
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'not_enabled')

    def test_resource_or_obligation_uncertainty_reaches_the_owner(self):
        self.tracked(); self.project['commitments'][0]['review_trigger']='Changed acceptance condition'
        write_state(self.path,self.project); changes=inspect(self.project,self.path,ROOT)
        self.assertTrue(changes['events'][0]['selected_option_affected'])
        self.persist(self.assessment())
        self.assertEqual(len(inspect(self.project,self.path,ROOT)['human_questions']),1)

    def test_unresolved_owner_request_survives_unrelated_no_impact_review(self):
        self.tracked(); self.project['sources'][0]['author']='Unverified author'
        write_state(self.path,self.project); self.persist(self.assessment())
        self.assertEqual(len(inspect(self.project,self.path,ROOT)['human_questions']),1)
        (self.root/'source.md').write_text('Original evidence\nUnrelated footnote',encoding='utf-8')
        self.persist(self.assessment('unchanged'))
        self.assertEqual(len(inspect(self.project,self.path,ROOT)['human_questions']),1)

    def test_removed_dependencies_remain_visible_in_historical_impact(self):
        self.tracked(); self.project['sources']=[]; self.project['evidence']=[]
        self.project['metric_results']=[]
        for option in self.project['options']: option['evidence_ids']=[]
        changes=inspect(self.project,self.path,ROOT)
        event=next(e for e in changes['events'] if e['kind']=='source_registry')
        self.assertEqual(event['impact']['evidence_ids'],['E1','E2'])
        self.assertTrue(event['selected_option_affected'])

    def test_boolean_version_is_not_a_supported_tracking_mode(self):
        self.setup_follow_up(); self.project['change_tracking']={'schema_version':True,'hash_mode':'material-v1'}
        self.assertTrue(validate(self.project))


if __name__=='__main__': unittest.main()
