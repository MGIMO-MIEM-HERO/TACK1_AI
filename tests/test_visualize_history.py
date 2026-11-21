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
from visualize import graph,render
from visualize_history import decision_history,exact_time


class DecisionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.path=ROOT/'examples/decision-passport-case/project.json'
        self.project=load(self.path)
        self.audit=audit(self.project,self.path,ready=True,quality=True)
        self.data=graph(self.project,self.audit,'test')

    def history(self,project=None,result=None):
        history=decision_history(project or self.project,result or self.audit,self.data)
        ids={n['id'] for n in self.data['nodes']}
        self.assertEqual(len(history['events']),len({e['id'] for e in history['events']}))
        self.assertEqual(sum(history['counts'].values()),len(history['events']))
        self.assertTrue(all(set(e['nodes'])<=ids for e in history['events']))
        return history

    def test_exact_times_sort_by_utc_and_incomplete_times_stay_separate(self):
        self.assertEqual(exact_time('2026-11-20T10:00:00+03:00'),('2026-11-20T07:00:00.000000+00:00','exact'))
        for value,state in [('2026-11-20','date_only'),('2026-11-20T10:00:00','timezone_missing'),('bad','invalid'),(None,'missing')]:
            self.assertEqual(exact_time(value),(None,state))
        project=copy.deepcopy(self.project)
        project['checkpoints']=[{'summary':'Later','at':'2026-11-20T08:00:00+00:00'},
                                {'summary':'Earlier','at':'2026-11-20T10:00:00+03:00'},
                                {'summary':'Unknown zone','at':'2026-11-20T09:00:00'}]
        history=self.history(project)
        checkpoints=[e for e in history['events'] if e['kind']=='checkpoints']
        self.assertEqual([e['title'] for e in checkpoints],['Earlier','Later','Unknown zone'])
        self.assertIsNone(checkpoints[-1]['time_utc'])

    def test_free_text_and_updated_at_do_not_invent_recommendation_or_date(self):
        project=copy.deepcopy(self.project)
        project['checkpoints']=[{'summary':'Рекомендован O2','at':'2026-11-19T10:00:00+03:00'}]
        history=self.history(project)
        event=next(e for e in history['events'] if e['id']=='checkpoint:0')
        self.assertFalse(event['recommendation_recorded'])
        self.assertIsNone(event['recommendation_id'])
        self.assertEqual(event['details']['Рекомендация в снимке'],'Не записана в структурированном снимке')
        project['checkpoints']=[];project['feasibility_reviews']=[];project['research_selection_reviews']=[]
        project['follow_up_reviews']=[];project['metric_results']=[]
        self.assertEqual(self.history(project)['events'],[])

    def test_structured_recommendation_changes_have_saved_reason_and_no_exact_change_claim(self):
        history=self.history()
        event=next(e for e in history['events'] if e['id']=='checkpoint:5')
        self.assertIn('O1 → O2',event['title'])
        self.assertEqual(event['details']['Предыдущая известная рекомендация'],'O1')
        self.assertEqual(event['details']['Обоснование в снимке'],self.project['checkpoints'][5]['change_snapshot']['decision']['recommendation_rationale'])
        self.assertIn('Точное время смены рекомендации',event['details']['Границы сравнения'])

    def test_scoped_answers_use_native_current_and_historical_status(self):
        html=render(self.project,self.audit,self.path.read_bytes(),self.path)
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        answers=[e for e in data['decision_history']['events'] if e['kind']=='answers']
        self.assertEqual(len(answers),4)
        self.assertEqual(sum(e['status']=='current' for e in answers),1)
        self.assertEqual(sum(e['status']=='historical' for e in answers),3)
        self.assertEqual({e['details']['kind'] for e in answers},{'recommendation','permission','data'})
        current=next(e for e in answers if e['status']=='current')
        self.assertEqual(current['details']['kind'],'recommendation')
        self.assertTrue(all(e['at']==e['details']['confirmed_at'] for e in answers))

    def test_read_receipt_is_not_an_answer_and_future_view_is_not_current(self):
        history=self.history()
        self.assertEqual(len([e for e in history['events'] if e['kind']=='views']),len(self.project['follow_up_reviews']))
        project=copy.deepcopy(self.project);project['follow_up_reviews'][0]['reviewed_at']='2099-01-01T00:00:00+00:00'
        history=self.history(project)
        future=next(e for e in history['events'] if e['id']=='receipt:0')
        self.assertTrue(future['after_export_clock'])
        self.assertEqual(future['status'],'historical_view')
        self.assertIn('не согласие',future['details']['Границы'])

    def test_undated_review_and_result_reply_do_not_borrow_other_dates(self):
        project=copy.deepcopy(self.project);project['feasibility_reviews'][0].pop('recorded_at',None)
        history=self.history(project)
        key='review:feasibility_reviews:'+project['feasibility_reviews'][0]['review_id']
        event=next(e for e in history['events'] if e['id']==key)
        self.assertIsNone(event['time_utc'])
        self.assertEqual(event['time_precision'],'missing')
        project=load(ROOT/'examples/decision-follow-up-case/project.json')
        project['metric_results'][0]['human_decision']={'reference':'Authored result-only answer','version_hash':'x'*64}
        history=self.history(project)
        event=next(e for e in history['events'] if e['id']=='result-answer:R1')
        self.assertIsNone(event['at'])
        self.assertIsNone(event['time_utc'])
        self.assertIn('не к рекомендации проекта',event['details']['Границы'])

    def test_synthetic_results_remain_synthetic_and_dates_are_observed_at(self):
        project=load(ROOT/'examples/decision-follow-up-case/project.json')
        history=self.history(project)
        results=[e for e in history['events'] if e['kind']=='results']
        self.assertEqual(len(results),len(project['metric_results']))
        self.assertTrue(all(e['details']['data_origin']=='synthetic' for e in results))
        self.assertEqual(results[0]['at'],project['metric_results'][0]['observed_at'])
        self.assertIn('не время добавления',results[0]['time_basis'])

    def test_exports_embed_history_and_leave_input_objects_and_files_unchanged(self):
        before=copy.deepcopy(self.project)
        saved={str(p):p.read_bytes() for p in self.path.parent.rglob('*') if p.is_file()}
        self.project['checkpoints'][0]['summary']='</script><img src=x onerror=alert(1)>'
        state=copy.deepcopy(self.project)
        html=render(self.project,self.audit,b'bytes')
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(next(e for e in data['decision_history']['events'] if e['id']=='checkpoint:0')['title'],self.project['checkpoints'][0]['summary'])
        self.assertEqual(html.lower().count('</script>'),2)
        self.assertEqual(state,self.project)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'brief.md'
            subprocess.run([sys.executable,'-B',str(ROOT/'scripts/project_tool.py'),'report',str(self.path),'--out',str(out)],check=True,capture_output=True)
            rendered=out.with_suffix('.graph.html').read_text(encoding='utf-8')
            self.assertIn('history-panel',rendered);self.assertNotIn('__HISTORY_SCRIPT__',rendered)
            payload=json.loads(rendered.split('<script id="data" type="application/json">')[1].split('</script>')[0])
            self.assertEqual(payload['decision_history']['current']['recommendation'],before['recommended_option_id'])
        self.assertEqual(saved,{str(p):p.read_bytes() for p in self.path.parent.rglob('*') if p.is_file()})
