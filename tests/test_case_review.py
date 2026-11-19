from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from checkpoint import ROOT
from project_tool import audit,load,report
from start import restore
from verify_case_review_demo import verify_demo


class CaseReviewTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)/'case';shutil.copytree(ROOT/'examples/paired-case-review',self.root)
        self.path=self.root/'project.json';self.project=load(self.path)

    def test_draft_is_for_review_and_does_not_remove_the_owner_blocker(self):
        before=self.path.read_bytes();result=audit(self.project,self.path,ready=True,quality=True)
        self.assertTrue(result['review_draft_only']);self.assertFalse(result['ready'])
        text=report(self.project,self.path)
        self.assertIn('НЕ ГОТОВ К ИСПОЛНЕНИЮ',text)
        for error in result['errors']:self.assertIn(error,text)
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(self.project['chosen_option_id'],'O1')
        self.assertIn('Показать владельцу причины пересмотра',restore(self.path)['resume_summary']['next_step']['text'])
        with self.assertRaises(ValueError):report(self.project,self.path,final=True)

    def test_unsafe_recommendation_is_never_exported_as_a_review_draft(self):
        self.project['recommended_option_id']='O1'
        self.assertFalse(audit(self.project,self.path)['review_draft_only'])
        with self.assertRaises(ValueError):report(self.project,self.path)

    def test_unknown_missing_or_changed_source_still_blocks_draft_export(self):
        source=self.root/'inputs/brief.md';source.unlink()
        self.assertFalse(audit(self.project,self.path)['review_draft_only'])
        with self.assertRaises(ValueError):report(self.project,self.path)

    def test_changed_source_is_not_accepted_by_diagnostic_export(self):
        source=self.root/'inputs/policy.md'
        source.write_text(source.read_text(encoding='utf-8')+'\nНовый текст для проверки\n',encoding='utf-8')
        self.assertFalse(audit(self.project,self.path)['review_draft_only'])
        with self.assertRaises(ValueError):report(self.project,self.path)

    def test_unread_primary_source_is_not_whitelisted_as_history(self):
        self.project['sources'][0]['verification']='search_snippet'
        self.assertFalse(audit(self.project,self.path)['review_draft_only'])
        with self.assertRaises(ValueError):report(self.project,self.path)

    def test_only_a_distinct_recorded_recommendation_can_be_reviewed(self):
        self.project.pop('recommended_option_id')
        self.assertFalse(audit(self.project,self.path)['review_draft_only'])
        with self.assertRaises(ValueError):report(self.project,self.path)

    def test_all_formal_reviews_are_current_without_making_paper_feasible(self):
        result=audit(self.project,self.path)
        for name in ('feasibility','research_selection','decision_stress_test','marketing_claims_audit'):
            self.assertEqual(result[name]['status'],'review_record_complete')
        self.assertEqual({a['option_id']:a['outcome'] for a in result['feasibility']['assessments']},{'O1':'infeasible','O2':'unknown'})
        self.assertEqual(result['research_selection']['branch_resolutions'][0]['branch_id'],'UNKNOWN')
        self.assertEqual(result['marketing_claims_audit']['claims'][0]['status'],'unsupported')
        self.assertFalse(any('human_confirmation' in cp for cp in self.project['checkpoints']))
        for plan in self.project['feasibility_reviews'][-1]['assessments']:
            self.assertTrue(all(t['effort']['hours'] is None for t in plan['work']))

    def test_original_choice_obligations_results_and_input_files_are_preserved(self):
        original=load(self.root/'baseline/project.json')
        for field in ('chosen_option_id','commitments','metric_results','follow_up_reviews','evidence'):
            self.assertEqual(original.get(field),self.project.get(field))

    def test_main_case_exports_both_draft_and_map_with_final_still_blocked(self):
        result=verify_demo()
        self.assertTrue(result['review_draft_and_map_exported']);self.assertTrue(result['final_still_blocked'])


if __name__=='__main__':unittest.main()
