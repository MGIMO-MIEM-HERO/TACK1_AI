#!/usr/bin/env python3
"""Authored end-to-end decision revision, never real owner approval or an LLM benchmark."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

from checkpoint import ROOT, save_checkpoint, write_state
from decision_passport import ANSWER_KEYS, build, markdown, record_answer, request
from feasibility import baseline as feasibility_baseline, record as record_feasibility
from material_changes import enable, prepare
from project_tool import load
from quality import state_hash
from research_selection import baseline as research_baseline, record as record_research
from resume_summary import acknowledge


def walkthrough(case):
    path=case/'project.json';project=load(path);initial=copy.deepcopy(project)
    enable(project,path,ROOT);project=load(path)

    def technical_reviews(suffix):
        nonlocal project
        feasibility=copy.deepcopy(project['feasibility_reviews'][-1]);feasibility.pop('recorded_at',None)
        feasibility.update(review_id='F-PASSPORT-'+suffix,baseline=feasibility_baseline(project,path,ROOT))
        record_feasibility(project,path,ROOT,feasibility);project=load(path)
        research=copy.deepcopy(project['research_selection_reviews'][-1]);research.pop('recorded_at',None)
        research.update(review_id='R-PASSPORT-'+suffix,baseline=research_baseline(project,path,ROOT))
        record_research(project,path,ROOT,research);project=load(path)
        project['strategy_review']['state_hash']=state_hash(project,path,ROOT);write_state(path,project)

    def fictional_answer(cid,kind,subject):
        nonlocal project
        scope=request(project,path,ROOT,kind,subject)
        answer={k:v for k,v in scope.items() if k in ANSWER_KEYS}
        answer.update(confirmation_id=cid,outcome='approved',confirmed_by='Вымышленный владелец учебного кейса',
            confirmed_at=datetime.now(timezone.utc).isoformat(),
            statement='Авторский вымышленный ответ: подтверждаю только предмет '+kind+' '+subject+' для явно указанной версии; это не реальное согласие участника команды.')
        replies=case/'inputs/replies';replies.mkdir(exist_ok=True)
        file=replies/(cid+'.json');file.write_text(json.dumps(answer,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        record_answer(project,path,ROOT,file);project=load(path)

    technical_reviews('INITIAL')
    fictional_answer('DEMO-P1','permission','option:O1')
    fictional_answer('DEMO-D1','data','source:ACTIVE')
    fictional_answer('DEMO-R1','recommendation','/recommended_option_id')
    first=build(path);assert all(r['status']=='current' for r in first['confirmations'])
    acknowledge(path,first['resume_summary']['version_hash'],'Авторская самопроверка агента','Рассмотрен вымышленный кейс, не реальный ответ владельца')
    project=load(path)

    passage=('Новое авторское условие: DEV доступен на 4 человеко-часа. Оценка W1 — 6, W2 — 2 человеко-часа. '
             'Окно и зависимости прежние; бумага отдельно допускается по F_B. Это вымышленный сценарий, не ресурсы команды.')
    (case/'inputs/active-condition.md').write_text(passage+'\n',encoding='utf-8')
    changed=build(path)
    assert changed['version']!=first['version'] and all(r['status']=='historical' for r in changed['confirmations'])
    assert any('ACTIVE_0' in e['impact']['evidence_ids'] for e in changed['changes']['events'])
    assert changed['feasibility']['status']=='stale' and changed['research']['status']=='stale'
    for e in project['evidence']:
        if e['evidence_id']=='ACTIVE_0':e['status']='stale'
    evidence=copy.deepcopy(initial['evidence'][-1]);evidence.update(evidence_id='ACTIVE_NEW',claim=passage,status='provisional')
    evidence['support'][0]['passage']=passage;project['evidence'].append(evidence)
    option=next(o for o in project['options'] if o['option_id']=='O1')
    option['evidence_ids']=[e for e in option['evidence_ids'] if e!='ACTIVE_0']+['ACTIVE_NEW']
    option['selection_assessment']={'status':'rejected',
        'reason':'Для этого объёма требуется оценочно 8 чел·ч при заданной ёмкости 4; пересмотреть объём или ресурс. Это не невозможность любого прототипа.',
        'evidence_ids':['ACTIVE_NEW']}
    project['recommended_option_id']='O2'
    project['recommendation_rationale']='Условно предложить отдельно осуществимую бумажную подготовку: текущему объёму прототипа не хватает заданной ёмкости. Выбор владельца и разрешение на действия отдельно.'
    project['next_action']='Получить ответ владельца на новую рекомендацию и отдельно уточнить разрешение на объём бумаги.'
    write_state(path,project)
    feasibility=copy.deepcopy(project['feasibility_reviews'][-1]);feasibility.pop('recorded_at',None)
    feasibility.update(review_id='F-PASSPORT-NEW',baseline=feasibility_baseline(project,path,ROOT))
    plan=feasibility['assessments'][0]
    for task,hours in zip(plan['work'],(6,2)):
        task['effort'].update(status='estimated',hours=hours,evidence_ids=['ACTIVE_NEW'],basis=passage)
    plan['resources'][0]['capacity'].update(hours=4,evidence_ids=['ACTIVE_NEW'],basis=passage)
    plan['allocations']=[{'work_id':'W1','resource_id':'DEV','hours':6},{'work_id':'W2','resource_id':'DEV','hours':2}]
    record_feasibility(project,path,ROOT,feasibility);project=load(path)
    research=copy.deepcopy(project['research_selection_reviews'][-1]);research.pop('recorded_at',None)
    research.update(review_id='R-PASSPORT-NEW',baseline=research_baseline(project,path,ROOT))
    gap=research['gaps'][0]
    gap.update(status='answered',answer='Авторское условие различает варианты: доступна условная PAPER, не текущий объём прототипа.',
               evidence_ids=['ACTIVE_NEW','F_B'],priority='defer',selected_method_id=None,priority_rationale='Ресурсная развилка проверена; ответ не означает выбор человека.')
    research['recommendation'].update(action='stop',question_id=None,method_id=None,rationale='Для текущей ресурсной развилки достаточно авторского условия; выбор оставить человеку.')
    research['stop_rule'].update(status='stop',evidence_ids=['ACTIVE_NEW','F_B'],rationale='Данные различают заданные планы; это не доказательство пользы или реального ресурса.')
    record_research(project,path,ROOT,research);project=load(path)
    project['strategy_review']['state_hash']=state_hash(project,path,ROOT);write_state(path,project)
    review=prepare(project,path,ROOT)
    review.update(reviewer='Авторская самопроверка агента, не независимая экспертиза',conclusion='changed',
                  rationale='Изменилось ресурсное основание: текущий прототип не помещается в ёмкость, бумажный объём проверен отдельно. Предлагается O2; прежние согласования не переносятся.')
    for effect in review['effects']:
        effect.update(materiality='material',decision_effect='changed',evidence_ids=['ACTIVE_NEW','F_B'],analysis=review['rationale'])
    save_checkpoint(project,path,'Авторский пересмотр: дефицит ресурса и условная рекомендация O2',reviewed_changes=True,change_review=review)
    project=load(path);revised=build(path)
    assert revised['research']['branch_resolutions'][0]['branch_id']=='PAPER'
    assert revised['changes']['human_questions'] and revised['resume_summary']['changes']['status']=='changed'
    assert all(r['status']=='historical' for r in revised['confirmations'])
    fictional_answer('DEMO-R2','recommendation','/recommended_option_id')
    final=build(path)
    assert final['confirmations'][-1]['status']=='current' and final['confirmations'][-1]['outcome']=='approved'
    assert not final['changes']['human_questions']
    assert not any(r['kind']=='permission' and r['status']=='current' for r in final['confirmations'])
    assert 'отдельно уточнить разрешение' in final['resume_summary']['next_step']['text']
    assert project['chosen_option_id']==initial['chosen_option_id'] is None
    assert project.get('commitments')==initial.get('commitments')
    assert project['research_selection_reviews'][0]==initial['research_selection_reviews'][0]
    assert project['feasibility_reviews'][0]==initial['feasibility_reviews'][0]
    before=path.read_bytes();ledger=(case/'ledger.jsonl').read_bytes()
    assert build(path)==final and path.read_bytes()==before and (case/'ledger.jsonl').read_bytes()==ledger
    return {'passed':True,'context':'authored_example, all replies fictional',
        'source_fact_changed':True,'affected_grounds_traced':True,'resource_and_research_reassessed':True,
        'branch':'PAPER','recommendation':'O2','old_answers_historical':True,'new_answer_exact_version':True,
        'permission_not_inferred':True,'repeat_open_read_only':True,'real_owner_approval_created':False}


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        case=Path(directory)/'case';shutil.copytree(ROOT/'examples/research-branches-case',case)
        return walkthrough(case)


if __name__=='__main__': print(json.dumps(verify_demo(),ensure_ascii=False,indent=2))
