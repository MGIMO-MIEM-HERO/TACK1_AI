"""Arithmetic and dimensional constraints, not validation of planning assumptions."""
from pathlib import Path
import json,math,hashlib
C=Path(__file__).resolve().parent
def load(n):return json.loads((C/n).read_text(encoding='utf-8'))
s=load('forecast-source-inputs.json');a=load('forecast-author-inputs.json');r=load('forecast-results.json');checks=[]
def test(name,ok):checks.append({'check':name,'passed':bool(ok)});assert ok,name
def eq(x,y):return math.isclose(x,y,rel_tol=1e-10,abs_tol=1e-7)
for name,digest in r['input_sha256'].items():test('inputs_current:'+name,hashlib.sha256((C/name).read_bytes()).hexdigest()==digest)
test('PDF_anchors',s['no_change']=={'gross_profit_rub':279000000,'active_families_last_month':5000,'family_connected':8000,'owners_connected':1000,'activation_q4_pct':45})
test('baseline_stock_calibrated',r['baseline_calibration'][-1]['family_end']==8000 and r['baseline_calibration'][-1]['owners_end']==1000)
expected={'main':{'gross_profit_rub':279120000,'active_families_last_month':6062,'family_connected':9770,'owners_connected':1000,'activation_q4_pct':50},'adverse':{'gross_profit_rub':278172000,'active_families_last_month':5138,'family_connected':8345,'owners_connected':1000,'activation_q4_pct':44}}
for key,x in r['scenarios'].items():
 p=a['scenarios'][key];annual=x['annual'];quarters=x['quarterly'];test(key+':independent_expected_KPIs',all(eq(annual['kpis'][k],v) for k,v in expected[key].items()))
 test(key+':exposed_within_household_base',sum(p['app_exposed'])+sum(p['support_exposed'])<=s['accessible_households']-6500)
 test(key+':existing_retention_families',sum(c['numbers'] for c in p['paid_number_cohorts'])/2<=6500)
 for row in quarters:
  q=row['quarter'];pre=key+':Q'+str(q)
  test(pre+':stock_flow',eq(row['end_connected_families'],row['opening_connected_families']+row['total_new_connections']-row['actual_exits']))
  test(pre+':saved_are_subset_of_exits',0<=row['saved_groups']<=row['ordinary_exits'])
  test(pre+':funnel',0<=row['activated_14d']<=row['accepted_connected_new_groups']<=row['created_groups'])
  test(pre+':14day_denominator',eq(row['activation_pct'],100*row['activated_14d']/row['created_groups']))
  test(pre+':counterfactual_is_not_added_twice',sum(v['connected_control'] for v in row['channels'])<=row['ordinary_new_connections'] and eq(row['incremental_connections'],sum(v['invitation_accepted_connected_plan']-v['connected_control'] for v in row['channels'])))
  test(pre+':profit',eq(row['incremental_net_gp_rub'],500*row['extra_paid_number_months']-row['new_direct_cost_rub']))
  test(pre+':cumulative_profit',eq(row['cumulative_net_gp_rub'],sum(v['incremental_net_gp_rub'] for v in quarters[:q])))
  test(pre+':investment_separate',eq(row['unrecovered_investment_rub'],sum(v['investment_rub'] for v in quarters[:q])-row['cumulative_net_gp_rub']))
 test(key+':contribution_survival',all(0<=v['p_control']<=v['p_plan']<=1 and v['cohort_launch_month']<=v['calendar_month']<=12 and eq(v['incremental_paid_number_months'],v['expected_paid_plan']-v['expected_paid_control']) for v in x['paid_cohort_months']))
 test(key+':cohort_month_bound',len(x['paid_cohort_months'])==18 and all(v['age_month']==v['calendar_month']-v['cohort_launch_month']+1 for v in x['paid_cohort_months']))
 test(key+':quarters_equal_annual',eq(sum(v['extra_paid_number_months'] for v in quarters),annual['extra_paid_number_months']) and eq(sum(v['incremental_net_gp_rub'] for v in quarters),annual['net_gp_uplift_rub']))
 test(key+':monthly_equals_annual',eq(sum(v['incremental_paid_number_months'] for v in x['paid_cohort_months']),annual['extra_paid_number_months']))
 test(key+':cost_categories_once',sum(p['direct_cost_categories_rub'].values())==sum(p['direct_cost_by_quarter_rub'])==annual['new_direct_cost_rub'])
 test(key+':GP_anchor_and_costs',eq(annual['kpis']['gross_profit_rub'],279000000+500*annual['extra_paid_number_months']-annual['new_direct_cost_rub']))
 test(key+':coverage',annual['kpis']['family_connected']<=100000 and annual['kpis']['owners_connected']<=40000 and eq(annual['family_coverage_pct'],annual['kpis']['family_connected']/1000))
 test(key+':last_month_only',eq(annual['kpis']['active_families_last_month'],5000+(annual['kpis']['family_connected']-8000)*float(p['active_share_of_extra_year_end_groups'])) and annual['kpis']['active_families_last_month']<=annual['kpis']['family_connected'])
 test(key+':gaps',all(eq(annual['gaps_to_target'][k],s['target'][k]-v) for k,v in annual['kpis'].items()))
 test(key+':no_first_year_payback',annual['max_repayable_investment_by_year_end_rub']<annual['investment_cap_rub'])
 test(key+':target_threshold',eq(500*annual['target_required_paid_number_months_at_scenario_cost']-annual['new_direct_cost_rub'],6000000))
test('paid_months_independent_main',r['scenarios']['main']['annual']['extra_paid_number_months']==1440)
test('paid_months_independent_adverse',r['scenarios']['adverse']['annual']['extra_paid_number_months']==144)
report={'status':'passed','assertions':len(checks),'checks':checks,'limits':'Arithmetic only. No empirical support, causality, sample-size adequacy, consent, budgets or resources validated.'}
(C/'forecast-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('PASS: '+str(len(checks))+' arithmetic and boundary assertions')
