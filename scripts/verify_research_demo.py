#!/usr/bin/env python3
"""Reproduce authored research prioritisation, new evidence and bounded stopping."""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from checkpoint import ROOT,write_state
from project_tool import load,report
from quality import state_hash
from research_selection import baseline,inspect,record


def evidence(eid,sid,claim,passage):
    return {'evidence_id':eid,'claim':claim,'claim_type':'source_fact','source_ids':[sid],
            'method':'Read the provided authored fixture','status':'provisional','claim_scope':'source_description',
            'locator':'line 2 of the supplied fixture','limitations':'Author-written condition, not real-world feasibility or demand',
            'support':[{'source_id':sid,'relation':'supports','locator':'line 2','passage':passage,
                        'reason':'Supports only the stated condition of the authored example'}]}


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        target=Path(directory)/'case';shutil.copytree(ROOT/'examples/next-research-case',target)
        path=target/'project.json';p=load(path);original=copy.deepcopy(p)
        source_bytes={s['source_id']:(target/s['url_or_path']).read_bytes() for s in p['sources']}
        assert inspect(p,path,ROOT)['recommendation']['question_id']=='Q1'
        passage='В этом учебном сценарии интеграция запрещена; разрешена бумажная проверка без интеграции.'
        assert passage in (target/'inputs/policy.md').read_text(encoding='utf-8')
        p['evidence'].append(evidence('E2','POLICY','Авторское условие запрещает интеграцию и допускает бумажную проверку.',passage))
        p['research_questions'][0]['status']='answered from POLICY; authored condition only'
        write_state(path,p)
        assert inspect(p,path,ROOT)['status']=='stale'
        r2=copy.deepcopy(p['research_selection_reviews'][-1]);r2.pop('recorded_at',None);r2['review_id']='R2'
        r2['baseline']=baseline(p,path,ROOT)
        r2['gaps'][0].update(status='answered',answer='Интеграция запрещена в переданном учебном условии.',
            priority='defer',priority_rationale='Ответ получен из POLICY; повторять вопрос не нужно.',
            evidence_ids=['E2'],selected_method_id=None)
        r2['gaps'][1].update(priority='critical',priority_rationale='После исключения интеграции это оставшийся барьер подготовки O2.')
        r2['recommendation'].update(action='investigate',question_id='Q2',method_id='M1',
            rationale='Q1 закрыт фактом о техническом условии. Теперь проверить, достаточен ли шаблон для O2; повтор Q1 и обзор цветов не различают оставшийся выбор.')
        r2['comparison_rationale']='После E2 вопрос Q1 закрыт, Q2 становится текущим критическим вопросом, Q3 остаётся отложенным.'
        record(p,path,ROOT,r2);p=load(path)
        assert inspect(p,path,ROOT)['recommendation']['question_id']=='Q2'
        passage='В шаблоне есть все обязательные для учебного сценария поля: тема, описание и контакт-заглушка.'
        assert passage in (target/'inputs/form.md').read_text(encoding='utf-8')
        p['evidence'].append(evidence('E3','FORM','Авторский шаблон содержит перечисленные в условии обязательные поля.',passage))
        p['research_questions'][1]['status']='answered from FORM; content only, not usability validation'
        # Explicit authored reassessment, not an automatic recommendation by the selector.
        p['recommended_option_id']='O2'
        p['recommendation_rationale']='По E2 интеграция исключена условием, по E3 шаблон достаточен для подготовки бумажного сценария. Предлагаем O2 только для подготовки, не для запуска или доказательства спроса.'
        p['product_strategy']['direction']='Подготовить бумажный сценарий по предоставленному шаблону; действующий продукт не обещается'
        p['communication_strategy']['message']='Бумажный учебный сценарий; понятность людям, спрос и эффект ещё не проверены'
        next(o for o in p['options'] if o['option_id']=='O2')['evidence_ids']=['E2','E3']
        p['next_action']='Показать владельцу подготовленный план бумажной проверки; не собирать дополнительные материалы о конкурентах для этого выбора.'
        write_state(path,p)
        assert inspect(p,path,ROOT)['status']=='stale'
        try:report(p,path,final=True)
        except ValueError:pass
        else:raise AssertionError('Stale research priorities were exported as current')
        r3=copy.deepcopy(r2);r3['review_id']='R3';r3['baseline']=baseline(p,path,ROOT)
        r3['gaps'][1].update(status='answered',answer='Шаблон содержит обязательные поля в границах учебного условия.',
            priority='defer',priority_rationale='Текущий вопрос подготовки закрыт E3; это не проверка UX или рынка.',
            evidence_ids=['E3'],selected_method_id=None)
        r3['comparison_rationale']='Q1 и Q2 имеют ответы о содержании материалов. Q3 не различает способы подготовки; для текущего решения дальнейший сбор не нужен.'
        r3['recommendation'].update(action='stop',question_id=None,method_id=None,
            rationale='Данных достаточно только для выбора способа подготовки O2. Дополнительный обзор конкурентов не изменит запрет интеграции и достаточность переданного шаблона.')
        r3['stop_rule'].update(status='stop',evidence_ids=['E2','E3'],
            rationale='Техническое условие и состав шаблона различили варианты. Вопросы спроса и UX лежат за пределами текущего решения; их нельзя считать закрытыми.')
        record(p,path,ROOT,r3);p=load(path)
        p['strategy_review']['state_hash']=state_hash(p,path,ROOT);write_state(path,p)
        final=report(p,path,final=True)
        result=inspect(p,path,ROOT)
        assert result['recommendation']['action']=='stop' and 'Когда остановиться' in final
        assert p['research_selection_reviews'][0]==original['research_selection_reviews'][0]
        assert len(p['research_selection_reviews'])==3
        assert p.get('chosen_option_id') is None and p['commitments']==[]
        assert all((target/s['url_or_path']).read_bytes()==source_bytes[s['source_id']] for s in p['sources'])
        return {'passed':True,'sequence':['Q1 feasibility','Q2 template sufficiency','stop for preparation decision only'],
                'new_evidence':['E2','E3'],'old_priorities_invalidated':True,'versions_preserved':3,
                'effort':'unknown, never zero by default','human_choice':None,'market_or_ux_validated':False,
                'scope':'Authored fixture and explicit reassessment; no model calls, interviews or measured business savings'}


if __name__=='__main__':print(json.dumps(verify_demo(),ensure_ascii=False,indent=2))
