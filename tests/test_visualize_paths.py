import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from project_tool import audit, load
from visualize import graph, render


class DecisionPathTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT/'examples/decision-stress-case/project.json'
        self.project = load(self.path)
        self.audit = audit(self.project,self.path,ready=True,quality=True)

    def path_data(self,oid='O1'):
        data=graph(self.project,self.audit,'test')
        path=next(p for p in data['decision_paths'] if p['option_id']==oid)
        ids={n['id'] for n in data['nodes']}
        self.assertTrue(set(path['nodes'])<=ids)
        self.assertTrue(all(0<=i<len(data['edges']) for i in path['edge_indexes']))
        self.assertTrue(all(data['edges'][i]['source'] in path['nodes'] and data['edges'][i]['target'] in path['nodes'] for i in path['edge_indexes']))
        return data,path

    def test_transitive_ground_chain_and_cycle_are_traversed_without_unrelated_evidence(self):
        e1,e2=self.project['evidence'][:2]
        self.project['options'][1]['evidence_ids']=[e2['evidence_id']]
        oid=self.project['options'][1]['option_id']
        self.project['decision_stress_tests']=[]
        e2['related_evidence_ids']=[e1['evidence_id']]
        e1['related_evidence_ids']=[e2['evidence_id']]
        data,path=self.path_data(oid)
        self.assertEqual(set(path['evidence']),{'e:'+e1['evidence_id'],'e:'+e2['evidence_id']})
        self.assertEqual(len(path['evidence']),2)
        self.assertFalse(any(n.startswith('group:') or n=='task' for n in path['nodes']))
        self.assertTrue(any(data['edges'][i]['source']=='e:'+e1['evidence_id'] and data['edges'][i]['target']=='e:'+e2['evidence_id'] for i in path['edge_indexes']))

    def test_context_and_contradiction_keep_recorded_passage_reason_and_locator(self):
        row=self.project['evidence'][0]
        row['support'][0]['relation']='contradicts'
        _,path=self.path_data()
        link=next(s for s in path['support'] if s['evidence_id']==row['evidence_id'])
        self.assertEqual(link['relation'],'contradicts')
        self.assertEqual(link['passage'],row['support'][0]['passage'])
        self.assertEqual(link['reason'],row['support'][0]['reason'])
        self.assertIn(['s:'+link['source_id'],'e:'+row['evidence_id']],path['contradictions'])
        row['support'][0]['relation']='context'
        _,path=self.path_data()
        self.assertFalse(path['contradictions'])
        self.assertTrue(any(s['relation']=='context' for s in path['support']))

    def test_only_latest_explicitly_related_assumptions_are_included(self):
        review=self.project['decision_stress_tests'][0]
        review['assumptions'][0]['option_ids']=['O1']
        old=copy.deepcopy(review);old['review_id']='OLD'
        self.project['decision_stress_tests'].insert(0,old)
        _,path=self.path_data()
        self.assertIn('stress:'+review['review_id']+':assumptions:'+review['assumptions'][0]['assumption_id'],path['assumptions'])
        self.assertFalse(any('stress:OLD:' in key for key in path['nodes']))
        _,other=self.path_data('O3')
        self.assertNotIn('stress:'+review['review_id']+':assumptions:'+review['assumptions'][0]['assumption_id'],other['assumptions'])

    def test_recommendation_choice_and_planned_check_remain_distinct(self):
        before=copy.deepcopy(self.project)
        _,path=self.path_data()
        self.assertTrue(path['is_recommended'])
        self.assertFalse(path['is_human_choice'])
        self.assertIn('review',path['checks'])
        self.assertIn('next',path['checks'])
        self.assertIn('не являются отдельным результатом',path['note'])
        self.assertEqual(self.project,before)

    def test_no_options_and_no_grounds_do_not_fabricate_paths(self):
        self.project['decision_stress_tests']=[]
        self.project['options'][1]['evidence_ids']=[]
        oid=self.project['options'][1]['option_id']
        _,path=self.path_data(oid)
        self.assertEqual(path['evidence'],[])
        self.assertEqual(path['sources'],[])
        self.project['options']=[]
        self.assertEqual(graph(self.project,self.audit,'test')['decision_paths'],[])

    def test_current_check_scope_and_stale_status_are_preserved(self):
        self.path=ROOT/'examples/paired-case-review/project.json';self.project=load(self.path)
        self.audit=audit(self.project,self.path,ready=True,quality=True)
        self.audit['feasibility']['status']='stale'
        _,path=self.path_data('O2')
        self.assertTrue(any(k.startswith('feasibility:') for k in path['checks']))
        self.assertTrue(any(k.startswith('research:') for k in path['checks']))
        self.assertEqual(path['review_statuses']['feasibility'],'stale')

    def test_export_is_self_contained_and_untrusted_path_text_is_inert(self):
        self.project['options'][1]['title']='</script><img src=x onerror=alert(1)>'
        html=render(self.project,self.audit,b'test')
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(data['decision_paths'][1]['title'],self.project['options'][1]['title'])
        self.assertEqual(html.lower().count('</script>'),2)
        self.assertNotIn('__PATH_SCRIPT__',html)
        self.assertNotIn(self.project['options'][1]['title'],html)
