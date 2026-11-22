"""Reproduce the explicitly authored conditional plan; no empirical estimation."""
from pathlib import Path
from fractions import Fraction as F
import json,hashlib
C=Path(__file__).resolve().parent
def load(n):return json.loads((C/n).read_text(encoding='utf-8'))
def value(x):
 if isinstance(x,F):return int(x) if x.denominator==1 else float(x)
 if isinstance(x,dict):return {k:value(v) for k,v in x.items()}
 if isinstance(x,list):return [value(v) for v in x]
 return x
def build():
 s=load('forecast-source-inputs.json');a=load('forecast-author-inputs.json');b=a['baseline_quarterly_calibration'];out={'status':'Conditional author planning forecast, not observed effect of OR or approved pilot','source_inputs':s,'input_sha256':{n:hashlib.sha256((C/n).read_bytes()).hexdigest() for n in ['forecast-source-inputs.json','forecast-author-inputs.json']},'baseline_calibration':[],'scenarios':{}}
 stock=s['base_year_estimate']['family_connected'];owners=s['base_year_estimate']['owners_connected']
 for q in range(4):
  stock+=b['new_family_connections'][q]-b['family_exits'][q];owners+=b['owner_new_connections'][q]-b['owner_exits'][q]
  out['baseline_calibration'].append({'quarter':q+1,'family_end':stock,'owners_end':owners,'created':b['created_groups'][q],'activated_14d':b['activated_14d'][q]})
 for key,p in a['scenarios'].items():
  rows=[];stock=s['base_year_estimate']['family_connected'];paid=[]
  for cohort in p['paid_number_cohorts']:
   for m in range(cohort['launch_month'],13):
    age=m-cohort['launch_month']+1;p0=F('0.90')-F('0.015')*(age-1);p1=p0+F(p['paid_survival_lift']);n=cohort['numbers']
    paid.append({'cohort_launch_month':cohort['launch_month'],'numbers':n,'calendar_month':m,'age_month':age,'p_control':p0,'p_plan':p1,'expected_paid_control':n*p0,'expected_paid_plan':n*p1,'incremental_paid_number_months':n*(p1-p0)})
  cum_net=F(0);cum_i=0
  for q in range(4):
   channels=[]
   for channel in ['app','support']:
    n=p[channel+'_exposed'][q];rate=p['channel_rates'][channel];control=a['channel_control_rates'][channel]
    created=n*F(rate['create']);connected=created*F(rate['accept']);c_created=n*F(control['create']);c_connected=c_created*F(control['accept'])
    channels.append({'channel':channel,'unique_exposed_households':n,'created_plan':created,'invitation_accepted_connected_plan':connected,'created_control':c_created,'connected_control':c_connected,'incremental_connected':connected-c_connected})
   extra=sum(x['incremental_connected'] for x in channels);extra_created=sum(x['created_plan']-x['created_control'] for x in channels);saved=p['saved_family_groups'][q]
   new=b['new_family_connections'][q]+extra;exits=b['family_exits'][q]-saved;opening=stock;stock+=new-exits
   months=sum(x['incremental_paid_number_months'] for x in paid if (x['calendar_month']-1)//3==q)
   contribution=months*s['contribution_per_extra_paid_number_month_rub'];cost=p['direct_cost_by_quarter_rub'][q];net=contribution-cost;cum_net+=net;investment=a['investment_by_quarter_rub'][q];cum_i+=investment
   created=b['created_groups'][q]+extra_created;activated=p['activation_14d_counts'][q]
   rows.append({'quarter':q+1,'channels':channels,'opening_connected_families':opening,'ordinary_new_connections':b['new_family_connections'][q],'incremental_connections':extra,'total_new_connections':new,'ordinary_exits':b['family_exits'][q],'saved_groups':saved,'actual_exits':exits,'end_connected_families':stock,'created_groups':created,'accepted_connected_new_groups':new,'activated_14d':activated,'activation_pct':100*F(activated)/created,'cohort_maturity_rule':'Every created group including unanswered invitations; read after full 14 days for final creation in quarter','extra_paid_number_months':months,'contribution_rub':contribution,'new_direct_cost_rub':cost,'incremental_net_gp_rub':net,'cumulative_net_gp_rub':cum_net,'investment_rub':investment,'cumulative_investment_rub':cum_i,'unrecovered_investment_rub':cum_i-cum_net})
  extra_end=stock-s['no_change']['family_connected'];active_extra=extra_end*F(p['active_share_of_extra_year_end_groups']);M=sum(x['extra_paid_number_months'] for x in rows);cost=sum(p['direct_cost_by_quarter_rub']);gp=s['no_change']['gross_profit_rub']+cum_net
  kpis={'gross_profit_rub':gp,'active_families_last_month':s['no_change']['active_families_last_month']+active_extra,'family_connected':stock,'owners_connected':s['no_change']['owners_connected'],'activation_q4_pct':rows[-1]['activation_pct']}
  out['scenarios'][key]={'quarterly':rows,'paid_cohort_months':paid,'annual':{'kpis':kpis,'gaps_to_target':{k:s['target'][k]-v for k,v in kpis.items()},'incremental_connections':sum(x['incremental_connections'] for x in rows),'saved_family_groups':sum(p['saved_family_groups']),'extra_end_connected_families':extra_end,'active_extra_families_last_month':active_extra,'extra_paid_number_months':M,'new_direct_cost_rub':cost,'contribution_rub':M*500,'net_gp_uplift_rub':cum_net,'family_coverage_pct':100*stock/s['accessible_households'],'owner_coverage_pct':100*F(kpis['owners_connected'])/s['accessible_owners'],'max_repayable_investment_by_year_end_rub':max(0,cum_net),'operating_loss_to_cover_before_any_investment_rub':max(0,-cum_net),'investment_cap_rub':cum_i,'year_end_unrecovered_investment_rub':cum_i-cum_net,'peak_funding_need_rub':max(x['unrecovered_investment_rub'] for x in rows),'target_required_paid_number_months_at_scenario_cost':F(s['target']['gross_profit_rub']-s['no_change']['gross_profit_rub']+cost,500),'cost_neutral_ceiling_rub':M*500}}
 return value(out)
if __name__=='__main__':
 result=build();(C/'forecast-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 old=load('calculations.json');old['numeric_forecast_revision']=result; (C/'calculations.json').write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v['annual'] for k,v in result['scenarios'].items()},ensure_ascii=False,indent=2))
