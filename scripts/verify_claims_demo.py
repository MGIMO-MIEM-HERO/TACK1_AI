#!/usr/bin/env python3
"""Check the authored unmeasured 'twice as fast' example in an isolated copy."""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from checkpoint import ROOT, write_state
from claims_audit import baseline, inspect, record
from project_tool import load, report
from quality import state_hash


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        target=Path(directory)/'case'
        shutil.copytree(ROOT/'examples/marketing-claims-case',target)
        path=target/'project.json'
        p=load(path)
        source_before=(target/'inputs/brief.md').read_bytes()
        initial=inspect(p,path,ROOT)
        assert initial['status']=='review_record_complete',initial
        assert initial['claims'][0]['status']=='unsupported'
        assert initial['claims'][0]['has_required_measurements'] is False
        assert 'не подтверждено' in report(p,path,final=True)
        original=copy.deepcopy(p)
        row=p['marketing_claims_audits'][-1]['assessments'][0]
        p['communication_strategy']['message']=row['original_claim']
        write_state(path,p)
        assert inspect(p,path,ROOT)['status']=='stale'
        # Save an honest diagnosis of the unsafe message; this is allowed so that
        # the problem is visible. Export remains blocked independently of storage.
        r=copy.deepcopy(p['marketing_claims_audits'][-1])
        r.pop('recorded_at',None);r['review_id']='R2';r['baseline']=baseline(p,path,ROOT)
        result=record(p,path,ROOT,r)
        assert result['publication_blockers'],result
        p=load(path)
        try: report(p,path,final=True)
        except ValueError: pass
        else: raise AssertionError('Unconfirmed numerical message was exported as final')
        # The prepared safe wording is applied explicitly, never by the audit tool.
        p['communication_strategy']['message']=row['accepted_wording']
        write_state(path,p)
        r=copy.deepcopy(r);r['review_id']='R3';r['baseline']=baseline(p,path,ROOT)
        result=record(p,path,ROOT,r)
        assert not result['blockers'] and not result['publication_blockers'],result
        p=load(path)
        p['strategy_review']['state_hash']=state_hash(p,path,ROOT)
        write_state(path,p)
        final=report(p,path,final=True)
        assert row['accepted_wording'] in final and 'измерений нет' in final
        assert len(p['marketing_claims_audits'])==3
        assert p['marketing_claims_audits'][0]==original['marketing_claims_audits'][0]
        assert (target/'inputs/brief.md').read_bytes()==source_before
        assert p['recommended_option_id']==original['recommended_option_id']
        assert p.get('chosen_option_id') is None and p.get('commitments')==[]
        assert p['validation_design']['status']=='planned'
        return {'passed':True,'claim':'Сократить время подготовки вдвое',
                'assessment':'unsupported, not contradicted','measurements':False,
                'capability':'planned','unsafe_message_final_export':'blocked',
                'explicit_safe_wording_and_new_audit':'passed','history_versions_preserved':3,
                'source_unchanged':True,'human_choice':None,
                'scope':'Authored UI-independent contract test, not a real speed experiment, LLM benchmark or legal review'}


if __name__=='__main__':
    print(json.dumps(verify_demo(),ensure_ascii=False,indent=2))
