#!/usr/bin/env python3
"""Reproduce the actual paired case repair without changing its historical O1 choice."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from checkpoint import ROOT, save_checkpoint, write_state
from claims_audit import prepare as claims_prepare, record as claims_record
from feasibility import prepare as feasibility_prepare, record as feasibility_record
from material_changes import enable, prepare as changes_prepare
from project_tool import audit, load, report
from quality import state_hash
from research_selection import prepare as research_prepare, record as research_record
from stress_test import prepare as stress_prepare, record as stress_record


def prepare_case(path):
    project=load(path);original=copy.deepcopy(project)
    project['project_id']='paired-case-review'
    project['follow_up_context']='authored_example'
    write_state(path,project);enable(project,path,ROOT);project=load(path)
    who='Самопроверка агента по переданным учебным материалам; не независимая экспертиза'
    limits='Авторский кейс. Новые ресурсы, часы, реальные исследования и ответы владельца не добавлены. Неизвестное остаётся неизвестным.'
    def statement(status,basis,refs=(),**fields):return {'status':status,'basis':basis,'evidence_ids':list(refs),**fields}
    feasibility=feasibility_prepare(project,path,ROOT,'F-CASE-REVIEW',['O1','O2'])
    feasibility.update(context='authored_example',reviewer=who,limitations=limits)
    for plan in feasibility['assessments']:
        prototype=plan['option_id']=='O1'
        plan.update(minimum_scope='Локальный исполняемый прототип на вымышленных входах' if prototype else 'Бумажный сценарий и протокол; содержимое пока не предоставлено',
            window=statement('unknown','Окончание подготовки задано до 21 ноября 2026; начало и календарная разбивка не подтверждены. Полное окно не утверждается.',['E9'],start=None,end=None),
            scope=statement('unknown','Предложен минимальный пакет работ; полнота декомпозиции не подтверждена.'),
            permission=statement('unknown','Разрешение на новый исполняемый объём не подтверждено.') if prototype else statement('allowed','POLICY v2 явно допускает бумажный план без кода.',['E10']),
            work=[{'work_id':'BUILD' if prototype else 'PAPER','description':'Подготовить и проверить исполняемый локальный сценарий' if prototype else 'Подготовить содержание, состояния и протокол проверки',
                   'skill':'разработка' if prototype else 'проектирование сценариев','effort':statement('unknown','Оценка трудоёмкости отсутствует.',hours=None)}],
            resources=[{'resource_id':'DEV' if prototype else 'PAPER_TEAM','skills':['разработка' if prototype else 'проектирование сценариев'],
                'competence':statement('unknown','Компетенции не подтверждены.'),
                'availability':statement('unavailable','Разработчик, замена и готовый прототип отсутствуют до конца срока.',['E9']) if prototype else statement('unknown','Доступность исполнителя бумажной подготовки не подтверждена.'),
                'capacity':statement('unknown','Часы не представлены; денежный бюджет 0 не означает нулевой труд.',hours=None)}],
            dependencies=[{'dependency_id':'INPUT','description':'Исполнитель или готовый прототип' if prototype else 'Полные тексты сценариев и протокола',
                'critical':True,**(statement('blocked','POLICY v2 исключает доступного разработчика и готовый прототип.',['E9']) if prototype else statement('unknown','CSV со значением 3 не содержит сами сценарии.'))}],
            next_check='Получить новое подтверждённое ресурсное условие и решение владельца перед пересмотром O1.' if prototype else 'Уточнить исполнителя, доступные часы, декомпозицию и предоставить тексты сценариев; до этого O2 условен.')
    feasibility_record(project,path,ROOT,feasibility);project=load(path)
    research=research_prepare(project,path,ROOT,'R-CASE-REVIEW')
    research.update(context='authored_example',reviewer=who,limitations=limits,
                    comparison_rationale='Сначала различить ресурсные варианты и комплектность бумаги; измерение эффекта нельзя запускать при запрете контактов и отсутствии реализации.')
    for gap in research['gaps']:
        qid=gap['question_id'];resource=qid=='Q1'
        gap.update(impact='feasibility' if qid in ('Q1','Q2') else 'preference',priority='critical' if resource else 'high',
            priority_rationale='Ресурсный план определяет допустимость следующего шага.' if resource else 'Проверить содержание до обещаний результата.',
            why_changes_decision='Ответ различает прототип, условную бумагу и остановку; отсутствие данных не выбирает бумагу автоматически.',
            evidence_ids=['E9','E10'] if resource else ['E7'] if qid=='Q3' else ['E1'],
            method_choice_rationale='Нужен адресный запрос владельцу о ресурсе и материалах, не контакты с реальными организаторами.',selected_method_id=None)
        method=gap['methods'][0]
        method.update(description='Сверить отдельную ресурсную проверку и запросить неизвестный ресурс O2.' if resource else 'Проверить предоставленные тексты сценариев.' if qid=='Q2' else 'Сверить бриф на наличие реальных измерений времени.',
            access='available' if qid in ('Q1','Q3') else 'unknown',adequacy='sufficient' if qid in ('Q1','Q3') else 'unknown',
            adequacy_rationale='Достаточно для определения текущей неопределённости по материалам; не доказывает пользу или спрос.',source_ids=['POLICY'] if resource else ['BRIEF'])
        for branch,index in zip(gap['answer_branches'][:2],(0,1)):
            branch.update(answer=('Ресурс прототипа подтверждён' if index==0 else 'Прототип недоступен, бумага отдельно осуществима') if resource else
                ('Достаточные материалы представлены' if index==0 else 'Комплектность не подтверждена') if qid=='Q2' else
                ('Причинные измерения представлены' if index==0 else 'Измерения отсутствуют в брифе'),
                consequence='Вернуться к проверке прототипа/полного материала/эффекта.' if index==0 else 'Сохранить условную бумагу либо осторожную формулировку; не выдавать неизвестное за результат.',
                option_ids=['O1'] if index==0 else ['O2'],next_step='Показать условия владельцу; не менять выбор и не запускать работу автоматически.')
            if resource:
                branch['condition']={'kind':'feasibility','indicator':'Ресурс минимального плана','criterion':'Результат отдельной проверки объёма, исполнителя и зависимостей','method_id':'M1',
                    'requirements':[{'option_id':'O1','outcome':'feasible'}] if index==0 else [{'option_id':'O1','outcome':'infeasible'},{'option_id':'O2','outcome':'feasible'}]}
            else:
                branch['condition']={'kind':'observation','indicator':'Наличие предоставленных материалов' if qid=='Q2' else 'Наличие измерений в переданном брифе',
                    'criterion':branch['answer'],'method_id':'M1','assessment':'unknown' if qid=='Q2' else 'not_met' if index==0 else 'met',
                    'rationale':'Комплектность сценариев не проверена: самих текстов нет.' if qid=='Q2' else 'E7 прямо описывает отсутствие реальных измерений. Это факт о брифе, не доказательство нулевого эффекта.',
                    'evidence_ids':[] if qid=='Q2' else ['E7'],'thresholds':[]}
        gap['answer_branches'][2]['next_step']='Уточнить ресурс O2 и получить содержимое сценариев; не назначать альтернативу при неизвестных данных.'
    research['recommendation'].update(action='clarify',question_id='Q1',method_id=None,rationale='Неизвестные часы и исполнитель O2 блокируют выбор исследования; сначала целевое уточнение.')
    research['stop_rule'].update(status='uncertain',condition='Остановить ресурсное уточнение после подтверждения или дефицита конкретного плана O2.',
        rationale='Ресурс бумаги ещё неизвестен, прекращать сбор оснований для решения рано.',remaining_limits=limits)
    research_record(project,path,ROOT,research);project=load(path)
    stress=stress_prepare(project,path,ROOT,'S-CASE-REVIEW')
    stress.update(reviewer=who,limitations=limits)
    stress['assumptions'][0].update(statement='Бумага может быть подготовлена в заданном горизонте, только если подтвердятся исполнитель и содержимое.',basis='unknown',option_ids=['O2'],verification_needed='Уточнить ресурс и проверить сами сценарии.')
    for scenario,title,premise in zip(stress['scenarios'],('У бумаги нет исполнителя','Бумажный сценарий не покрывает протокол'),
        ('Предположим, ресурс бумажной подготовки тоже недоступен. Это не новое наблюдение.', 'Предположим, предоставленные материалы неполны. Это риск, не результат проверки пользователей.')):
        scenario.update(title=title,premise=premise,new_data_needed='Фактический ресурс исполнителя и полные материалы; реальные контакты не разрешены.',review_trigger='Новый ресурсный документ, предоставленные сценарии или ответ владельца.')
        for impact in scenario['option_impacts']:
            impact.update(reason='O1 исключён текущим ресурсным условием; O2 зависит от проверяемого допущения; O0/O3 остаются для решения владельца.',evidence_ids=['E9','E10'],
                feasibility='infeasible' if impact['option_id']=='O1' or (scenario['scenario_id']=='SC1' and impact['option_id']=='O2') else 'uncertain')
        scenario['recommendation'].update(rationale='Не назначать предпочтительный вариант без ресурса бумаги и решения владельца; сравнить O0/O3 после уточнения.')
    stress_record(project,path,ROOT,stress);project=load(path)
    claims=claims_prepare(project,path,ROOT,'M-CASE-REVIEW');claims.update(reviewer=who,limitations=limits)
    row=claims['assessments'][0]
    row.update(status='unsupported',evidence_links=[{'evidence_id':'E7','relation':'context','coverage':'partial','reason':'Бриф указывает отсутствие замеров, а не отрицательный измеренный эффект.'}],
        scope_match='CAP1 остаётся planned; ни времени, ни реального спроса не измеряли.',rationale='Обещание ускорения не подтверждено; отсутствие измерений не делает его опровергнутым.',
        accepted_wording=project['marketing_claims'][0]['proposed_replacement'],validation_method='После отдельного разрешения и готовности материала определить сравнение и измерение времени. Сейчас эксперимент не запускать.')
    claims_record(project,path,ROOT,claims);project=load(path)
    project['strategy_review']['state_hash']=state_hash(project,path,ROOT);write_state(path,project)
    changes=changes_prepare(project,path,ROOT)
    changes.update(reviewer=who,conclusion='unchanged',rationale='Формализован тот же условный вывод O2. Новых часов, исполнителей и решений владельца не получено; O1 остаётся прежним неподтверждённым выбором.')
    for effect in changes['effects']:
        effect.update(materiality='material',decision_effect='unchanged',evidence_ids=['E9','E10'],analysis=changes['rationale'])
    save_checkpoint(project,path,'Формализованы осуществимость, исследование, сценарии и обещания без нового выбора',change_review=changes)
    project=load(path)
    assert project['chosen_option_id']==original['chosen_option_id']=='O1'
    assert project['commitments']==original['commitments'] and project['metric_results']==original['metric_results']
    assert not any('human_confirmation' in cp for cp in project['checkpoints'])
    return project


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        case=Path(directory)/'case';shutil.copytree(ROOT/'examples/paired-case-review',case)
        shutil.copyfile(case/'baseline/project.json',case/'project.json');shutil.copyfile(case/'baseline/ledger.jsonl',case/'ledger.jsonl')
        path=case/'project.json';project=prepare_case(path);result=audit(project,path,ready=True,quality=True)
        for key in ('feasibility','research_selection','decision_stress_test','marketing_claims_audit'):
            assert result[key]['status']=='review_record_complete',result[key]
        outcomes={a['option_id']:a['outcome'] for a in result['feasibility']['assessments']}
        assert outcomes=={'O1':'infeasible','O2':'unknown'}
        assert result['research_selection']['branch_resolutions'][0]['branch_id']=='UNKNOWN'
        assert result['marketing_claims_audit']['claims'][0]['status']=='unsupported'
        assert result['review_draft_only'] and not result['ready'] and result['errors']
        before=path.read_bytes();text=report(project,path)
        assert 'НЕ ГОТОВ К ИСПОЛНЕНИЮ' in text and path.read_bytes()==before
        try:report(project,path,final=True)
        except ValueError:pass
        else:raise AssertionError('Unresolved owner choice exported as final')
        output=case/'verified-brief.md'
        done=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/project_tool.py'),'report',str(path),'--out',str(output)],capture_output=True,text=True,encoding='utf-8')
        assert done.returncode==0,done.stderr
        assert output.exists() and output.with_suffix('.graph.html').exists()
        html=output.with_suffix('.graph.html').read_text(encoding='utf-8')
        payload=json.loads(html.split('<script id="data" type="application/json">',1)[1].split('</script>',1)[0])
        nodes={n['id']:n for n in payload['nodes']}
        for key in ('feasibility:F-CASE-REVIEW','research:R-CASE-REVIEW','stress:S-CASE-REVIEW','claims:M-CASE-REVIEW','passport:current'):
            assert key in nodes,key
        assert nodes['review']['status']=='есть блокеры'
        assert 'выбор человека' in nodes['o:O1']['status'] and 'рекомендация агента' in nodes['o:O2']['status']
        return {'passed':True,'formal_reviews_current':True,'prototype':'infeasible','paper':'unknown',
            'research_branch':'UNKNOWN','claim':'unsupported_not_refuted','historical_choice_preserved':'O1',
            'review_draft_and_map_exported':True,'final_still_blocked':True,'human_answer_invented':False}


if __name__=='__main__':print(json.dumps(verify_demo(),ensure_ascii=False,indent=2))
