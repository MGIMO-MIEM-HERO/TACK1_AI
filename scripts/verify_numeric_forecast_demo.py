#!/usr/bin/env python3
"""Exercise five-metric numeric forecasts in an isolated fictional case."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from checkpoint import ROOT, write_state
from numeric_forecast import inspect, prepare, record
from project_tool import load


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        case=Path(directory)/'case';shutil.copytree(ROOT/'examples/review-contract-case',case)
        path=case/'project.json';project=load(path)
        original_choice=project.get('chosen_option_id');original_recommendation=project.get('recommended_option_id')
        specifications=[('profit','Вклад за год','руб.',10000,13000,12500,10000),
            ('active','Активные группы в последнем месяце','групп',100,160,130,102),
            ('connected','Подключённые группы на конец года','групп',200,300,250,210),
            ('other','Другой сегмент без запуска','владельцев',40,80,40,40),
            ('activation','Активация зрелой когорты за 14 дней','%',30,50,38,29)]
        project['forecast_requirements']={'horizon':'Авторский условный плановый год',
            'rationale':'Самостоятельный вымышленный пример: все пять показателей требуются для проверки контракта',
            'metrics':[dict(metric_id=mid,label=label,unit=unit,baseline=base,target=target,direction='higher',
                basis='Авторские учебные исходные числа этого примера, не фактические данные компании')
                for mid,label,unit,base,target,_,_ in specifications]}
        write_state(path,project)
        r=prepare(project,path,ROOT,'N1')
        r.update(reviewer='Авторская самопроверка',conditions='Только при прохождении ресурсных и пользовательских проверок',
            limitations='Учебная арифметика. Удержание, спрос, затраты и разрешение не измерены.',
            sensitivity='При нулевой добавке результат равен базе. Более поздний запуск требует пересчитать горизонты и затраты.')
        r['assumptions']=[]
        for row,(_,_,unit,base,_,main,adverse) in zip(r['metrics'],specifications):
            mid=row['metric_id']
            for suffix,value in [('MAIN',main-base),('BAD',adverse-base)]:
                r['assumptions'].append(dict(assumption_id=mid+'_'+suffix,value=value,unit=unit,basis='author_scenario',
                    evidence_ids=[],rationale='Явная авторская условная дельта для проверки арифметики; не эмпирическая оценка',
                    validation_step='Раскрыть драйверы воронки/когорт/затрат и проверить их до финансирования'))
            row.update(action='Условный учебный план; другому сегменту не приписан эффект',
                limits='Сценарная дельта не доказывает причинность; физические единицы проверяются содержательно',
                main={'value':main,'formula':'baseline + '+mid+'_MAIN'},
                adverse={'value':adverse,'formula':'baseline + '+mid+'_BAD'})
        record(project,path,ROOT,r);project=load(path)
        first=inspect(project,path,ROOT)
        assert first['status']=='review_record_complete' and len(first['metrics'])==5
        assert [m['main']['value'] for m in first['metrics']]==[12500,130,250,40,38]
        assert first==inspect(load(path),path,ROOT)
        before=path.read_bytes();output=case/'forecast.md'
        process=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/project_tool.py'),'report',str(path),
            '--out',str(output)],capture_output=True,text=True,encoding='utf-8')
        assert process.returncode==0,process.stderr
        document=output.read_text(encoding='utf-8')
        assert all(m['label'] in document for m in project['forecast_requirements']['metrics'])
        assert 'авторское сценарное допущение' in document and '12500' in document
        graph=json.loads(output.with_suffix('.graph.html').read_text(encoding='utf-8').split(
            '<script id="data" type="application/json">')[1].split('</script>')[0])
        assert len([n for n in graph['nodes'] if n['id'].startswith('forecast:N1:metric:')])==5
        assert path.read_bytes()==before
        bad=copy.deepcopy(r);bad['review_id']='INCOMPLETE';bad['metrics'].pop()
        try: record(project,path,ROOT,bad)
        except ValueError: pass
        else: raise AssertionError('Missing metric was recorded')
        assert path.read_bytes()==before
        revised=copy.deepcopy(r);revised['review_id']='N2';record(project,path,ROOT,revised)
        saved=load(path)
        assert saved['numeric_forecast_reviews'][0]==project['numeric_forecast_reviews'][0]
        assert saved.get('chosen_option_id')==original_choice and saved.get('recommended_option_id')==original_recommendation
        saved['forecast_requirements']['horizon']='Другой год'
        assert inspect(saved,path,ROOT)['status']=='stale'
        return {'passed':True,'metrics':5,'history_versions':2,'missing_metric_rejected':True,
            'native_report_and_map_checked':True,'scope':'Deterministic fictional contract example, not a live LLM benchmark or empirically validated forecast'}


if __name__=='__main__':print(json.dumps(verify_demo(),ensure_ascii=False,indent=2))
