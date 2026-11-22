"""Conditional forecast contract, using a fictional case unrelated to the PDF run."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_stress_test as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from checkpoint import ROOT, write_state
from ledger import ledger_path, read_entries, verify
from numeric_forecast import baseline, calculate, inspect, prepare, record
from project_tool import audit, load, report
from quality import state_hash
from start import restore
from stress_test import baseline as stress_baseline, record as record_stress
from validate_project import validate
from visualize import render


class NumericForecastTests(unittest.TestCase):
    setUp = fixture.StressTests.setUp
    complete_record = fixture.StressTests.complete_record
    review = fixture.StressTests.review
    run_cli = fixture.StressTests.run_cli

    def setup_forecast(self):
        self.review()
        specs = [('profit','Contribution','RUB',10000,13000),
                 ('active','Active groups in final month','groups',100,160),
                 ('connected','Connected groups at year end','groups',200,300),
                 ('other','Other segment not launched','owners',40,80),
                 ('activation','Activation within complete 14-day window','percent',30,50)]
        self.project['forecast_requirements'] = {'horizon':'Fictional planning year',
            'rationale':'Authored acceptance task explicitly requests five numeric metrics, not real operator data',
            'metrics':[dict(metric_id=mid,label=label,unit=unit,direction='higher',baseline=b,target=t,
                basis='Explicit fictional test brief, not an observation') for mid,label,unit,b,t in specs]}
        write_state(self.path,self.project)
        r = prepare(self.project,self.path,ROOT,'N1',option_id='O1')
        r.update(reviewer='Authored self-review',conditions='Only if access, resource and owner gates pass before launch',
            limitations='Not empirical; annual paid months differ from connected groups; no automatic approval',
            sensitivity='At zero retained months, profit is baseline minus new direct costs; later launch reduces the window')
        r['assumptions'] = [dict(assumption_id=k,value=v,unit=u,basis='author_scenario',evidence_ids=[],
            rationale='Explicit round-number conditional load for this test, not an estimate of observed demand',
            validation_step='Replace with measured cohort and cost data before funding')
            for k,v,u in [('M',30,'additional paid number-months'),('A',10,'additional paid number-months'),
                ('RATE',100,'RUB per additional paid number-month'),('C',500,'RUB new direct costs'),
                ('D',1000,'RUB new direct costs'),('G',50,'net connected groups'),('G_BAD',10,'net connected groups'),
                ('ACTIVE',0.6,'active share of extra groups'),('ACTIVE_BAD',0.2,'active share of extra groups'),
                ('ACT',8,'activation percentage-point increase'),('ACT_BAD',1,'activation percentage-point decrease')]]
        pairs = [('baseline + M * RATE - C',12500,'baseline + A * RATE - D',10000),
                 ('baseline + G * ACTIVE',130,'baseline + G_BAD * ACTIVE_BAD',102),
                 ('baseline + G',250,'baseline + G_BAD',210),
                 ('baseline',40,'baseline',40),('baseline + ACT',38,'baseline - ACT_BAD',29)]
        for row,(main,mv,adverse,av) in zip(r['metrics'],pairs):
            row.update(action='Conditional existing-path signal; no effect attributed to the unlaunched other segment',
                       limits='Same horizon and population; authored planning values, not a measured causal effect')
            row['main'].update(value=mv,formula=main);row['adverse'].update(value=av,formula=adverse)
        return r

    def test_requested_forecast_missing_blocks_final_and_draft_names_gap(self):
        self.setup_forecast()
        result=audit(self.project,self.path,ready=True,quality=True)
        self.assertEqual(result['numeric_forecast']['status'],'not_recorded')
        self.assertFalse(result['final_ready'])
        self.assertTrue(any('Required numeric forecast' in b for b in result['procedure_requirements']['blockers']))
        self.assertIn('not_recorded',report(self.project,self.path))
        with self.assertRaises(ValueError):report(self.project,self.path,final=True)

    def test_record_reload_current_values_and_history_do_not_choose(self):
        r=self.setup_forecast();before=copy.deepcopy(self.project)
        first=record(self.project,self.path,ROOT,r);self.project=load(self.path)
        self.assertEqual(first['status'],'review_record_complete')
        self.assertEqual(first,inspect(self.project,self.path,ROOT))
        self.assertEqual(restore(self.path)['numeric_forecast'],first)
        self.assertEqual([m['main']['value'] for m in first['metrics']],[12500,130,250,40,38])
        self.assertEqual([m['adverse']['value'] for m in first['metrics']],[10000,102,210,40,29])
        self.assertEqual(first['metrics'][0]['main_gap'],500)
        self.assertEqual(self.project['recommended_option_id'],before['recommended_option_id'])
        self.assertEqual(self.project.get('chosen_option_id'),before.get('chosen_option_id'))
        r2=copy.deepcopy(r);r2['review_id']='N2'
        record(self.project,self.path,ROOT,r2)
        saved=load(self.path)
        self.assertEqual(saved['numeric_forecast_reviews'][0],self.project['numeric_forecast_reviews'][0])
        self.assertEqual(len(saved['numeric_forecast_reviews']),2)
        self.assertEqual(verify(read_entries(ledger_path(self.path))),[])

    def test_missing_metric_or_scenario_formulas_only_and_bad_math_fail_atomically(self):
        r=self.setup_forecast();before=self.path.read_bytes()
        for mutate in (lambda x:x['metrics'].pop(),
                       lambda x:x['metrics'][0].pop('adverse'),
                       lambda x:x['metrics'][0]['main'].update(value=None),
                       lambda x:x['metrics'][0]['main'].update(value=999),
                       lambda x:x['metrics'][0]['main'].update(value=True),
                       lambda x:x['metrics'][0]['adverse'].update(value=99999,formula='99999'),
                       lambda x:x['metrics'][0]['main'].update(formula='M / 0'),
                       lambda x:x['assumptions'][0].update(basis='observed'),
                       lambda x:x['assumptions'][0].update(value=float('nan'))):
            with self.subTest(mutate=mutate):
                broken=copy.deepcopy(r);mutate(broken)
                with self.assertRaises(ValueError):record(self.project,self.path,ROOT,broken)
                self.assertEqual(self.path.read_bytes(),before)

    def test_arithmetic_language_never_executes_source_commands(self):
        for expression in ['__import__("os").system("echo bad")','M.__class__','[M][0]',
                           '2 ** 999999','True','missing + 1','[x for x in M]']:
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):calculate(expression,{'M':2})
        self.assertEqual(calculate('(M + 2) * 3 / 2',{'M':2}),6)

    def test_changed_source_or_requirements_invalidates_without_erasing_history(self):
        r=self.setup_forecast();record(self.project,self.path,ROOT,r);self.project=load(self.path)
        old=copy.deepcopy(self.project['numeric_forecast_reviews'])
        (self.root/'source.md').write_text('Original evidence; changed scope',encoding='utf-8')
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'stale')
        (self.root/'source.md').write_text('Original evidence',encoding='utf-8')
        self.project['forecast_requirements']['horizon']='Different planning year'
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'stale')
        self.assertEqual(self.project['numeric_forecast_reviews'],old)

    def test_hypothesis_cannot_masquerade_as_source_input(self):
        r=self.setup_forecast()
        r['assumptions'][0].update(basis='source',evidence_ids=['E2'])
        with self.assertRaisesRegex(ValueError,'hypothesis'):
            record(self.project,self.path,ROOT,r)

    def test_future_conditional_option_does_not_replace_current_recommendation(self):
        r=self.setup_forecast()
        self.project['recommended_option_id']='O0'
        self.project['recommendation_rationale']='Do not commit before the missing inputs are checked'
        r['baseline']=baseline(self.project,self.path,ROOT)
        write_state(self.path,self.project)
        result=record(self.project,self.path,ROOT,r)
        saved=load(self.path)
        self.assertEqual(result['option_id'],'O1')
        self.assertEqual(saved['recommended_option_id'],'O0')
        self.assertIsNone(saved.get('chosen_option_id'))

    def test_numeric_source_requires_actual_evidence_and_lower_direction_gap(self):
        r=self.setup_forecast();r['assumptions'][0].update(basis='source',evidence_ids=[])
        self.assertTrue(validate({**self.project,'numeric_forecast_reviews':[r]}))
        r=copy.deepcopy(r)
        r['assumptions'][0].update(basis='author_scenario')
        r['requirements']['metrics'][0]['direction']='lower'
        self.project['forecast_requirements']['metrics'][0]['direction']='lower'
        self.project['forecast_requirements']['metrics'][0]['target']=9000
        r['requirements']['metrics'][0]['target']=9000
        r['baseline']=baseline(self.project,self.path,ROOT)
        r['metrics'][0]['main'],r['metrics'][0]['adverse']=r['metrics'][0]['adverse'],r['metrics'][0]['main']
        write_state(self.path,self.project)
        out=record(self.project,self.path,ROOT,r)
        self.assertEqual(out['metrics'][0]['main_gap'],1000)

    def test_cli_record_report_and_map_embed_all_five_numeric_rows(self):
        r=self.setup_forecast();request=self.root/'forecast.json'
        request.write_text(json.dumps(r),encoding='utf-8')
        result=self.run_cli('numeric_forecast.py','record',self.path,'--review',request)
        self.assertEqual(result.returncode,0,result.stderr)
        self.project=load(self.path)
        # New numeric assumptions change the strategy. Reassess the existing
        # authored stress review instead of pretending it remained current.
        stress=copy.deepcopy(self.project['decision_stress_tests'][-1])
        stress.update(review_id='AFTER-FORECAST',baseline=stress_baseline(self.project,self.path,ROOT),
                      limitations='Authored review after the numeric assumptions; conditional, not measured')
        stress.pop('recorded_at',None)
        record_stress(self.project,self.path,ROOT,stress);self.project=load(self.path)
        self.project['strategy_review']['evidence_limits']='Forecast coefficients are authored; no measured effect or human approval'
        self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT)
        write_state(self.path,self.project)
        before=self.path.read_bytes();out=self.root/'forecast-brief.md'
        result=self.run_cli('project_tool.py','report',self.path,'--out',out,'--final')
        self.assertEqual(result.returncode,0,result.stderr)
        document=out.read_text(encoding='utf-8')
        self.assertIn('12500',document);self.assertIn('130',document);self.assertIn('author',document)
        for m in self.project['forecast_requirements']['metrics']:self.assertIn(m['label'],document)
        html=out.with_suffix('.graph.html').read_text(encoding='utf-8')
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(len([n for n in data['nodes'] if n['id'].startswith('forecast:N1:metric:')]),5)
        self.assertEqual(self.path.read_bytes(),before)

    def test_unrequested_tasks_are_unchanged_and_prepare_is_not_a_complete_review(self):
        initial=copy.deepcopy(self.project)
        self.complete_record()
        self.assertEqual(inspect(self.project,self.path,ROOT)['status'],'not_requested')
        with self.assertRaises(ValueError):prepare(self.project,self.path,ROOT,'N1')
        self.project=initial
        r=self.setup_forecast()
        self.assertEqual(validate({**self.project,'numeric_forecast_reviews':[r]}),[])
        draft=prepare(self.project,self.path,ROOT,'N-DRAFT')
        self.assertIsNone(draft['metrics'][0]['main']['value'])
        with self.assertRaises(ValueError):record(self.project,self.path,ROOT,draft)


if __name__=='__main__':unittest.main()
