import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from project_tool import audit,load
from visualize import graph,render


class ScenarioViewTests(unittest.TestCase):
    def setUp(self):
        self.path=ROOT/'examples/decision-stress-case/project.json'
        self.project=load(self.path)
        self.audit=audit(self.project,self.path,ready=True,quality=True)

    def view(self):
        data=graph(self.project,self.audit,'test')
        for view in data['scenario_views']:
            for scenario in view['scenarios']:
                self.assertTrue(set(scenario['nodes'])<={n['id'] for n in data['nodes']})
                self.assertTrue(all(0<=i<len(data['edges']) for i in scenario['edge_indexes']))
                self.assertTrue(all(data['edges'][i]['source'] in scenario['nodes'] and data['edges'][i]['target'] in scenario['nodes'] for i in scenario['edge_indexes']))
        return data,data['scenario_views'][-1] if data['scenario_views'] else None

    def test_saved_all_option_comparison_and_keep_switch_unknown_are_preserved(self):
        before=copy.deepcopy(self.project)
        _,view=self.view()
        self.assertTrue(view['graph_comparable'])
        self.assertEqual([s['conditional_recommendation']['outcome'] for s in view['scenarios']],['switch','keep','insufficient_evidence'])
        for saved,shown in zip(self.project['decision_stress_tests'][-1]['scenarios'],view['scenarios']):
            self.assertEqual(len(saved['option_impacts']),len(shown['option_impacts']))
            for old,new in zip(saved['option_impacts'],shown['option_impacts']):
                for key,value in old.items():self.assertEqual(new[key],value)
            self.assertEqual(shown['constraint_changes'],saved['constraint_changes'])
            self.assertEqual(shown['new_data_needed'],saved['new_data_needed'])
            self.assertEqual(shown['review_trigger'],saved['review_trigger'])
        self.assertEqual(before,self.project)

    def test_unknown_does_not_turn_into_infeasible_or_preferred(self):
        _,view=self.view()
        scenario=view['scenarios'][2]
        self.assertTrue(all(r['feasibility']=='uncertain' and r['preference']=='undetermined' for r in scenario['option_impacts']))
        self.assertIsNone(scenario['conditional_recommendation']['option_id'])
        self.assertIsNone(view['actual_human_choice'])
        self.assertEqual(view['actual_recommendation'],'O1')

    def test_stale_and_blocked_only_highlight_saved_review_records(self):
        for status in ('stale','blocked','not_checked'):
            self.audit['decision_stress_test']['status']=status
            _,view=self.view()
            self.assertFalse(view['graph_comparable'])
            for scenario in view['scenarios']:
                self.assertTrue(all(n.startswith('stress:') for n in scenario['nodes']))
                self.assertTrue(all(r['node_id'] is None for r in scenario['option_impacts']))
                self.assertIsNone(scenario['evaluation'])

    def test_historical_version_never_adopts_current_option_titles_or_highlights(self):
        old=copy.deepcopy(self.project['decision_stress_tests'][0]);old['review_id']='OLD'
        self.project['decision_stress_tests'].insert(0,old)
        self.project['options'][0]['title']='Changed current title'
        data,_=self.view();old_view=data['scenario_views'][0]
        self.assertEqual(old_view['status'],'historical')
        self.assertFalse(old_view['graph_comparable'])
        for scenario in old_view['scenarios']:
            self.assertTrue(all(r['title']==r['option_id'] and r['node_id'] is None for r in scenario['option_impacts']))
            self.assertTrue(all(n.startswith('stress:OLD') for n in scenario['nodes']))

    def test_absent_baseline_remains_absent_for_conditional_option(self):
        review=self.project['decision_stress_tests'][0]
        review['baseline']['recommended_option_id']=None
        review['scenarios'][0]['recommendation']['outcome']='conditional_option'
        self.project['recommended_option_id']=None
        _,view=self.view()
        self.assertEqual(view['comparison']['status'],'no_baseline_recommendation')
        self.assertIsNone(view['actual_recommendation'])
        self.assertEqual(view['scenarios'][0]['conditional_recommendation']['outcome'],'conditional_option')
        self.assertIn('Базовая рекомендация отсутствует',view['comparison']['note'])

    def test_no_saved_scenarios_create_no_synthetic_scenarios(self):
        self.project['decision_stress_tests']=[]
        data,view=self.view()
        self.assertEqual(data['scenario_views'],[])
        self.assertIsNone(view)

    def test_untrusted_scenario_text_is_inert_and_export_does_not_write(self):
        self.project['decision_stress_tests'][0]['scenarios'][0]['premise']='</script><img src=x onerror=alert(1)>'
        before=self.path.read_bytes();state=copy.deepcopy(self.project)
        html=render(self.project,self.audit,b'state')
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(data['scenario_views'][0]['scenarios'][0]['premise'],self.project['decision_stress_tests'][0]['scenarios'][0]['premise'])
        self.assertEqual(html.lower().count('</script>'),2)
        self.assertNotIn('__SCENARIO_SCRIPT__',html)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.project,state)
