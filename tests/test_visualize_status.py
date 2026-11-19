import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from project_tool import audit,load
from start import restore
from visualize import graph,render
from visualize_status import status_panel


class StatusPanelTests(unittest.TestCase):
    def setUp(self):
        self.path=ROOT/'examples/paired-case-review/project.json'
        self.project=load(self.path)
        self.audit=audit(self.project,self.path,ready=True,quality=True)
        self.data=graph(self.project,self.audit,'test')

    def panel(self,result=None,project=None):
        panel=status_panel(project or self.project,result or self.audit,self.data)
        ids={n['id'] for n in self.data['nodes']}
        for category in panel['categories'].values():
            self.assertEqual(category['count'],len(category['items']))
            for row in category['items']:self.assertTrue(set(row['nodes'])<=ids)
        return panel

    def test_only_current_answered_questions_close_and_deferred_remain_explicit(self):
        project=copy.deepcopy(self.project)
        result=copy.deepcopy(self.audit)
        project['research_questions']=[dict(question_id=q,question=q,could_change='Authored decision dependency',source_ids=[]) for q in ('Q1','Q2','Q3')]
        result['research_selection']={'status':'review_record_complete','review_id':'test','gaps':[
            dict(question_id='Q1',status='answered',answer='Saved answer',priority='high'),
            dict(question_id='Q2',status='open',answer=None,priority='high'),
            dict(question_id='Q3',status='open',answer=None,priority='defer')]}
        items=self.panel(result,project)['categories']['questions']['items']
        self.assertEqual({r['id'] for r in items},{'Q2','Q3'})
        self.assertEqual(next(r for r in items if r['id']=='Q3')['priority'],'defer')
        result['research_selection']['status']='stale'
        items=self.panel(result,project)['categories']['questions']['items']
        self.assertEqual({r['id'] for r in items},{'Q1','Q2','Q3'})
        self.assertEqual(next(r for r in items if r['id']=='Q1')['state'],'needs_recheck')

    def test_missing_research_check_does_not_invent_an_answer(self):
        result=copy.deepcopy(self.audit);result['research_selection']={'status':'not_recorded'}
        project=copy.deepcopy(self.project);project.pop('research_selection_reviews',None)
        items=self.panel(result,project)['categories']['questions']['items']
        self.assertEqual(len(items),len(project['research_questions']))
        self.assertTrue(all(r['state']=='not_assessed' for r in items))

    def test_sources_are_unique_and_removed_source_has_no_fabricated_node(self):
        project=copy.deepcopy(self.project);sid=project['sources'][0]['source_id']
        project['sources'][0]['injection_flags']=['authored warning']
        result=copy.deepcopy(self.audit)
        result['health']['changed_sources']=[sid]
        result['health']['unverifiable_sources']={sid:'not available'}
        result['follow_up']['source_alerts']=[{'source_id':sid,'reasons':['Expired according to native clock'],'impact':{'evidence_ids':[],'option_ids':[]}},
            {'source_id':'REMOVED','reasons':['Removed from source registry'],'object_ref':'/checkpoints/0','impact':{'evidence_ids':[],'option_ids':[]}}]
        rows=self.panel(result,project)['categories']['sources']['items']
        self.assertEqual(len(rows),2)
        self.assertGreaterEqual(len(next(r for r in rows if r['id']==sid)['reasons']),3)
        self.assertEqual(next(r for r in rows if r['id']=='REMOVED')['nodes'],[])

    def test_duplicate_blocker_messages_keep_origins_without_counting_advice_as_blocker(self):
        result=copy.deepcopy(self.audit)
        result['errors']=['same blocker'];result['warnings']=['same blocker'];result['content_review']['blockers']=['same blocker']
        for name in ('decision_stress_test','marketing_claims_audit','research_selection','feasibility'):
            for field in ('blockers','publication_blockers','decision_blockers'):result[name][field]=[]
        result['feasibility']['blockers']=['same blocker']
        result['follow_up']['metric_results']=[]
        result['advisories']=['Unknown resource hours; clarification needed']
        panel=self.panel(result);blockers=panel['categories']['blockers']
        self.assertEqual(blockers['count'],1)
        self.assertEqual(len(blockers['items'][0]['origins']),4)
        self.assertEqual(panel['advisories'],result['advisories'])

    def test_native_current_owner_summary_overrides_raw_followup_questions(self):
        path=ROOT/'examples/decision-passport-case/project.json'
        state=restore(path);project=load(path);result=state['audit']
        result['visual_views']={'summary':state['resume_summary']}
        result['follow_up']['human_questions']=[{'question_id':'stale-raw-question','object_ref':'/recommended_option_id','reason':'Must not resurrect an answered question','action':'Ask again'}]
        data=graph(project,result,'test');panel=status_panel(project,result,data)
        self.assertEqual(panel['categories']['owner']['count'],len(state['resume_summary']['owner']['questions']))
        self.assertFalse(any(q['question_id']=='stale-raw-question' for q in panel['categories']['owner']['items']))
        self.assertEqual(panel['owner_text'],state['resume_summary']['owner']['text'])

    def test_summary_view_is_not_an_answer_and_time_is_copied_not_recomputed(self):
        result=copy.deepcopy(self.audit);result['follow_up']['display_time']='2026-11-19T10:00:00+03:00'
        result['visual_views']={'summary':{'owner':{'status':'awaiting_decision','text':'A reply is needed','questions':[
            dict(question_id='q',object_ref='/recommended_option_id',reason='Unresolved',action='Review decision',seen_in_summary=True,reply_recorded=False)]},
            'next_step':{'text':'Verified next step'},'context':'authored_example'}}
        panel=self.panel(result)
        self.assertEqual(panel['categories']['owner']['count'],1)
        self.assertTrue(panel['categories']['owner']['items'][0]['seen_in_summary'])
        self.assertFalse(panel['categories']['owner']['items'][0]['reply_recorded'])
        self.assertEqual(panel['as_of'],'2026-11-19T10:00:00+03:00')
        self.assertEqual(panel['next_step'],'Verified next step')

    def test_report_and_direct_export_are_readonly_and_embed_status(self):
        before={str(p):p.read_bytes() for p in self.path.parent.rglob('*') if p.is_file()}
        state=copy.deepcopy(self.project)
        html=render(self.project,self.audit,self.path.read_bytes(),self.path)
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertTrue(data['status_panel']['review_draft_only'])
        self.assertGreater(data['status_panel']['categories']['blockers']['count'],0)
        self.assertEqual(self.project,state)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'brief.md'
            subprocess.run([sys.executable,'-B',str(ROOT/'scripts/project_tool.py'),'report',str(self.path),'--out',str(out)],check=True,capture_output=True)
            rendered=out.with_suffix('.graph.html').read_text(encoding='utf-8')
            self.assertIn('status-cards',rendered);self.assertNotIn('__STATUS_SCRIPT__',rendered)
            self.assertEqual(rendered.lower().count('</script>'),2)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.path.parent.rglob('*') if p.is_file()})

    def test_untrusted_status_text_stays_inert(self):
        result=copy.deepcopy(self.audit);result['errors']=['</script><img src=x onerror=alert(1)>']
        html=render(self.project,result,b'bytes')
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertTrue(any('<img' in r['message'] for r in data['status_panel']['categories']['blockers']['items']))
        self.assertNotIn(result['errors'][0],html)
