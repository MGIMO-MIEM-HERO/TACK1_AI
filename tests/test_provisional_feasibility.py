import copy
import json
from pathlib import Path
import sys
import unittest

import test_stress_test as fixture

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from checkpoint import ROOT,write_state
from project_tool import audit,load,report
from stress_test import inspect,record
from visualize import render
from validate_project import validate


class ProvisionalFeasibilityTests(unittest.TestCase):
    setUp=fixture.StressTests.setUp
    complete_record=fixture.StressTests.complete_record
    review=fixture.StressTests.review

    def provisional(self):
        old=self.review();write_state(self.path,self.project)
        r=copy.deepcopy(old);r['review_id']='WITH-ESTIMATE'
        a=r['assumptions'][0]
        a.update(statement='For desk design only, assume an analyst can review already supplied nonprivate material',
                 verification_needed='Ask for actual allocation and permitted scope; do not assume a pilot is approved')
        s=r['scenarios'][0]
        s.update(title='Resource not yet allocated',premise='The full delivery resource is unknown; only a reduced desk-design stage is considered')
        row=s['option_impacts'][0]
        row.update(feasibility='uncertain',preference='undetermined',reason='Full resource unconfirmed; reduced scope can be considered')
        row['provisional_assessment']={'verdict':'likely_feasible','assumption_ids':['A1'],
            'rationale':'Reduced desk scope avoids delivery and external contact; actual assignment remains unknown',
            'check_next':'Confirm analyst allocation and access to the supplied materials'}
        return r

    def test_save_reload_preserves_estimate_but_not_confirmed_resource_or_choice(self):
        r=self.provisional();old=copy.deepcopy(self.project['decision_stress_tests'][0])
        result=record(self.project,self.path,ROOT,r);saved=load(self.path)
        self.assertEqual(saved['decision_stress_tests'][0],old)
        row=saved['decision_stress_tests'][-1]['scenarios'][0]['option_impacts'][0]
        self.assertEqual(row['feasibility'],'uncertain')
        self.assertEqual(row['preference'],'undetermined')
        self.assertEqual(row['provisional_assessment']['verdict'],'likely_feasible')
        self.assertEqual(result['scenarios'][0]['provisional_assessments'][0]['verdict'],'likely_feasible')
        self.assertIsNone(saved.get('chosen_option_id'))
        self.assertEqual(saved['recommended_option_id'],self.project['recommended_option_id'])
        self.assertEqual(inspect(saved,self.path,ROOT),result)

    def test_missing_condition_bad_scope_and_confirmed_override_are_rejected(self):
        r=self.provisional();before=self.path.read_bytes()
        for mutate in (
            lambda row:row['provisional_assessment'].update(assumption_ids=[]),
            lambda row:row['provisional_assessment'].update(assumption_ids=['FAKE']),
            lambda row:row['provisional_assessment'].update(rationale=''),
            lambda row:row['provisional_assessment'].update(check_next=''),
            lambda row:row['provisional_assessment'].update(verdict='confirmed'),
            lambda row:row['provisional_assessment'].update(approved=True),
            lambda row:row.update(feasibility='infeasible'),
            lambda row:row.update(preference='preferred')):
            with self.subTest(mutate=mutate):
                broken=copy.deepcopy(r);mutate(broken['scenarios'][0]['option_impacts'][0])
                with self.assertRaises(ValueError):record(self.project,self.path,ROOT,broken)
                self.assertEqual(self.path.read_bytes(),before)

    def test_assumption_must_cover_this_option_and_scenario(self):
        r=self.provisional()
        r['assumptions'][0]['option_ids']=['O0']
        self.assertTrue(validate({**self.project,'decision_stress_tests':[r]}))
        r=copy.deepcopy(r)
        r['assumptions'][0]['option_ids']=['O1']
        other=copy.deepcopy(r['assumptions'][0]);other['assumption_id']='OTHER'
        r['assumptions'].append(other)
        r['scenarios'][0]['option_impacts'][0]['provisional_assessment']['assumption_ids']=['OTHER']
        self.assertTrue(validate({**self.project,'decision_stress_tests':[r]}))

    def test_report_and_map_preserve_provenance_and_keep_purple_unknown(self):
        r=self.provisional();record(self.project,self.path,ROOT,r);saved=load(self.path)
        before=self.path.read_bytes()
        text=report(saved,self.path)
        self.assertIn('предположительно осуществимо',text)
        self.assertIn('ресурс не подтверждён',text)
        self.assertIn('Confirm analyst allocation',text)
        html=render(saved,audit(saved,self.path,ready=True,quality=True),before,self.path)
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        row=data['scenario_views'][-1]['scenarios'][0]['option_impacts'][0]
        self.assertEqual(row['feasibility'],'uncertain')
        self.assertIn('provisional_assessment',row)
        self.assertIn('Предположительно осуществимо',html)
        self.assertEqual(before,self.path.read_bytes())

    def test_unsafe_text_is_inert_and_historical_versions_stay_historical(self):
        r=self.provisional()
        r['scenarios'][0]['option_impacts'][0]['provisional_assessment']['rationale']='</script><img src=x onerror=alert(1)>'
        record(self.project,self.path,ROOT,r);saved=load(self.path)
        html=render(saved,audit(saved,self.path),self.path.read_bytes(),self.path)
        self.assertEqual(html.lower().count('</script>'),2)
        self.assertNotIn('</script><img',html)

    def test_old_reviews_remain_valid_without_an_estimate(self):
        self.review()
        self.assertEqual(validate(self.project),[])


if __name__=='__main__':unittest.main()
