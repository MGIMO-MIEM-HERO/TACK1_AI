#!/usr/bin/env python3
"""Verify passive follow-through on explicitly fictitious decisions and metrics."""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from checkpoint import ROOT
from follow_up import acknowledge,inspect,instant
from project_tool import load
from quality import state_hash
from start import restore


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        target=Path(directory)/'case';shutil.copytree(ROOT/'examples/decision-follow-up-case',target)
        path=target/'project.json';p=load(path)
        clock=max(instant('2026-11-19T10:00:00+03:00'),
                  *(instant(r['reviewed_at']) for r in p['follow_up_reviews']))
        state_before=path.read_bytes();log_before=(target/'ledger.jsonl').read_bytes()
        a=restore(path,at=clock)['follow_up'];b=restore(path,at=clock)['follow_up']
        assert a==b and path.read_bytes()==state_before and (target/'ledger.jsonl').read_bytes()==log_before
        assert [c['commitment_id'] for c in a['overdue_commitments']]==['C1']
        assert [r['result_id'] for r in a['new_results']]==['R2']
        assert all(c['kind']=='closed' for c in a['commitments'] if c['commitment_id'] in ('C3','C4'))
        assert not next(c for c in a['commitments'] if c['commitment_id']=='C5')['overdue']
        original=copy.deepcopy(p);content_hash=state_hash(p,path,ROOT)
        acknowledge(p,path,ROOT,['R2'],'Авторская проверка','Прочитан синтетический результат; решение человека всё ещё требуется.')
        p=load(path)
        assert state_hash(p,path,ROOT)==content_hash
        after=inspect(p,path,ROOT)
        assert not after['new_results']
        assert any(q['question_id']=='result:R2' for q in after['human_questions'])
        state_reviewed=path.read_bytes();log_reviewed=(target/'ledger.jsonl').read_bytes()
        assert acknowledge(p,path,ROOT,['R2'],'Авторская проверка','Повторное чтение не создаёт запись')['recorded']==[]
        assert path.read_bytes()==state_reviewed and (target/'ledger.jsonl').read_bytes()==log_reviewed
        assert p['commitments']==original['commitments'] and p['chosen_option_id']==original['chosen_option_id']
        assert p['next_action']==original['next_action']
        # No new observation is invented: changing the supporting file means the
        # old result version must be checked, not silently kept as reviewed.
        source=target/'inputs/results.md';source.write_text(source.read_text(encoding='utf-8')+'\nИзменённая авторская версия; нужно перечитать.\n',encoding='utf-8')
        changed=inspect(p,path,ROOT)
        assert changed['new_results'] and changed['source_alerts']
        assert any(r['previously_reviewed_version'] for r in changed['new_results'])
        assert p['chosen_option_id']==original['chosen_option_id']
        return {'passed':True,'context':'authored_example; all agreements and results are fictitious',
                'initial_overdue':['C1'],'initial_new_results':['R2'],
                'completed_cancelled_proposed_not_overdue':True,'repeat_open_writes':False,
                'read_receipt_idempotent':True,'human_decision_still_required':True,
                'source_change_invalidates_old_result_review':True,'automatic_choice_or_deadline_change':False,
                'scope':'Deterministic follow-up contract test, not a real pilot or business-effect measurement'}


if __name__=='__main__':print(json.dumps(verify_demo(),ensure_ascii=False,indent=2))
