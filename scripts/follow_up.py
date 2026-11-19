#!/usr/bin/env python3
"""Read-only decision follow-through; explicit result review never means approval."""
import argparse
import copy
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from stress_test import nonempty, strings, dependency_impact

ACTIVE = ('agreed', 'in_progress', 'blocked')
STATUSES = ('proposed', *ACTIVE, 'completed', 'cancelled')
SHA = re.compile(r'[0-9a-f]{64}')


def instant(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('An explicit timezone offset is required for an instant')
    return dt


def zone(name, local_date=None):
    if not nonempty(name):
        raise ValueError('Project/commitment timezone is not specified')
    if name == 'UTC': return timezone.utc
    if re.fullmatch(r'[+-]\d{2}:\d{2}', name):
        hours, minutes = map(int, name[1:].split(':'))
        if hours > 23 or minutes > 59: raise ValueError('Invalid fixed timezone offset')
        return timezone((1 if name[0] == '+' else -1) * timedelta(hours=hours, minutes=minutes))
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Windows Python need not ship an IANA database. Moscow has been UTC+03
        # since late October 2014. Do not apply this fallback to historical dates.
        if name == 'Europe/Moscow' and (local_date is None or local_date >= date(2014, 10, 27)):
            return timezone(timedelta(hours=3), 'Europe/Moscow (UTC+03 fallback)')
        raise ValueError('Timezone data unavailable: use UTC/an explicit offset or provide IANA tzdata') from None


def deadline(value, zone_name):
    if not nonempty(value): raise ValueError('No deadline recorded')
    value=value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        day = date.fromisoformat(value)
        tz = zone(zone_name, day)
        # A date means the WHOLE local day, not midnight at its beginning.
        local = datetime.combine(day + timedelta(days=1), time.min)
        return localise(local, tz), True
    if not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',value):
        raise ValueError('Use YYYY-MM-DD or an extended ISO date-time; ambiguous date formats are not guessed')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        return localise(dt, zone(zone_name, dt.date())), False
    return instant(dt), False


def localise(naive, tz):
    candidates = []
    for fold in (0, 1):
        dt = naive.replace(tzinfo=tz, fold=fold)
        if dt.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive:
            candidates.append(dt)
    if not candidates: raise ValueError('Local time does not exist; provide an explicit offset')
    if len({dt.astimezone(timezone.utc) for dt in candidates}) > 1:
        raise ValueError('Local time is ambiguous; provide an explicit offset')
    return candidates[0]


def calendar_day(project, at=None):
    """One project-local expiry convention shared with audit/provenance checks."""
    now=instant(at) if at is not None else datetime.now(timezone.utc)
    return now.astimezone(zone(project['timezone'],now.date()) if project.get('timezone') else timezone.utc).date()


def validate_fields(project):
    errors = []
    for key in ('timezone',):
        if key in project and not nonempty(project[key]): errors.append(key + ' must be nonempty text')
    if 'follow_up_context' in project and project['follow_up_context'] not in ('live_project', 'authored_example'):
        errors.append('follow_up_context must be live_project/authored_example')
    commitments = project.get('commitments', [])
    ids = set()
    if not isinstance(commitments, list): return []  # Core validator owns this error.
    for c in commitments:
        if not isinstance(c, dict): continue
        cid = c.get('commitment_id')
        if cid is not None:
            if not nonempty(cid) or cid in ids: errors.append('commitment_id must be unique nonempty text')
            if nonempty(cid): ids.add(cid)
        if 'status' in c and c['status'] not in STATUSES: errors.append('Unknown commitment status')
        for key in ('agreement_reference', 'timezone'):
            if key in c and not nonempty(c[key]): errors.append('Commitment ' + key + ' must be text')
    by_eid = {e['evidence_id']:e for e in project.get('evidence', []) if isinstance(e,dict) and nonempty(e.get('evidence_id'))}
    results = project.get('metric_results', [])
    if not isinstance(results, list): return errors + ['metric_results must be an array']
    result_ids = set()
    for r in results:
        if not isinstance(r, dict): errors.append('Metric result must be an object');continue
        rid = r.get('result_id')
        if not nonempty(rid) or rid in result_ids: errors.append('result_id must be unique text')
        if nonempty(rid): result_ids.add(rid)
        if not nonempty(r.get('commitment_id')) or r['commitment_id'] not in ids: errors.append('Metric result needs a stable registered commitment_id')
        for key in ('metric', 'value', 'unit', 'summary'):
            if not nonempty(r.get(key)): errors.append('Metric result needs ' + key)
        try: instant(r.get('observed_at'))
        except (ValueError, TypeError): errors.append('Metric observed_at needs an offset-aware ISO timestamp')
        if r.get('data_origin') not in ('real', 'synthetic'): errors.append('Metric data_origin must be real/synthetic')
        refs = r.get('evidence_ids')
        if not strings(refs) or not refs or len(refs)!=len(set(refs)) or not set(refs)<=set(by_eid): errors.append('Metric result needs distinct registered evidence_ids')
        c = next((c for c in commitments if isinstance(c,dict) and c.get('commitment_id')==r.get('commitment_id')), {})
        if nonempty(r.get('metric')) and r['metric']!=c.get('metric'): errors.append('Metric result must match the commitment metric exactly')
        decision = r.get('human_decision')
        if decision is not None and (not isinstance(decision,dict) or not nonempty(decision.get('reference'))
                or not isinstance(decision.get('version_hash'),str) or not SHA.fullmatch(decision['version_hash'])):
            errors.append('Human decision needs a reference to an actual answer and the result version_hash')
    receipts = project.get('follow_up_reviews', [])
    if not isinstance(receipts,list): return errors + ['follow_up_reviews must be an array']
    seen = set()
    previous_view = None
    for r in receipts:
        if not isinstance(r,dict): errors.append('Follow-up review receipt must be an object');continue
        if r.get('kind') == 'resume':
            from resume_summary import validate_receipt
            from material_changes import digest
            receipt_errors = validate_receipt(r)
            errors.extend(receipt_errors)
            if not receipt_errors:
                expected = (previous_view['version_hash'] if previous_view and previous_view['observations'] == r['observations'] else
                            digest({'project_id': project['project_id'], 'parent': previous_view['version_hash'] if previous_view else None,
                                    'observations': r['observations']}))
                if expected != r['version_hash']: errors.append('Resume receipt version/observation lineage mismatch')
                if previous_view and previous_view['version_hash'] == r['version_hash']: errors.append('Duplicate resume-view receipt')
                previous_view = r
            continue
        if 'kind' in r:
            errors.append('Unknown follow-up receipt kind'); continue
        if not all(nonempty(r.get(k)) for k in ('result_id','version_hash','reviewer','note')) or not isinstance(r.get('version_hash'),str) or not SHA.fullmatch(r['version_hash']):
            errors.append('Review receipt needs result_id/version_hash/reviewer/note');continue
        key=(r['result_id'],r['version_hash'])
        if key in seen: errors.append('Duplicate result-version review receipt')
        seen.add(key)
        try: instant(r.get('reviewed_at'))
        except (ValueError,TypeError): errors.append('Review receipt reviewed_at must be offset-aware')
    return errors


def result_content_hash(project, path, root, result):
    from quality import state_hash
    evidence = {e['evidence_id']:e for e in project['evidence']}
    refs, pending = set(result['evidence_ids']), list(result['evidence_ids'])
    while pending:
        for eid in evidence[pending.pop()].get('related_evidence_ids', []):
            if eid not in refs: refs.add(eid);pending.append(eid)
    source_ids = {s for eid in refs for s in evidence[eid]['source_ids']}
    commitment=next(c for c in project['commitments'] if c.get('commitment_id')==result['commitment_id'])
    payload = {'result':{k:v for k,v in result.items() if k!='human_decision'},
                       'review_context':{k:commitment.get(k) for k in ('metric','review_trigger')},
                       'evidence':[e for e in project['evidence'] if e['evidence_id'] in refs],
                       'sources':[s for s in project['sources'] if s['source_id'] in source_ids],
                       'path_base':project.get('path_base')}
    from material_changes import enabled
    if enabled(project):
        payload['change_tracking'] = project['change_tracking']; payload['project_id'] = project['project_id']
    return state_hash(payload, path, root)


def result_version(project, path, root, result):
    content = result_content_hash(project, path, root, result)
    from material_changes import enabled, result_lineage
    return result_lineage(project, result['result_id'], content) if enabled(project) else content


def inspect(project, path, root, *, at=None, health=None):
    from project_tool import source_health
    from quality import FACTS, support_blockers
    now = instant(at) if at is not None else datetime.now(timezone.utc)
    tz_name = project.get('timezone')
    timezone_error = None
    try: display_tz = zone(tz_name, now.date()) if tz_name else timezone.utc
    except ValueError as error: display_tz=timezone.utc;timezone_error=str(error)
    questions = {}
    def ask(key, ref, reason, action):
        questions[key]={'question_id':key,'object_ref':ref,'reason':reason,'action':action}
    from material_changes import inspect as inspect_changes
    changes = inspect_changes(project, path, root)
    for q in changes['human_questions']: questions[q['question_id']] = q
    if timezone_error: ask('timezone','/timezone',timezone_error,'Уточнить часовой пояс проекта; локальные сроки не угадываются.')
    rows=[]
    for i,c in enumerate(project.get('commitments',[])):
        cid=c.get('commitment_id') or 'legacy:'+str(i)
        ref='/commitments/'+str(i)
        row={'commitment_id':cid,'object_ref':ref,'owner':c.get('owner'),'metric':c.get('metric'),
             'status':c.get('status'),'due':c.get('due'),'agreement_reference':c.get('agreement_reference'),
             'review_trigger':c.get('review_trigger'),'overdue':False,'deadline_instant':None}
        status=c.get('status')
        if status in ('completed','cancelled'): row['kind']='closed'
        elif status not in ACTIVE or not c.get('agreement_reference'):
            row.update(kind='unconfirmed',reason='Согласованный активный статус и ссылка на согласование не записаны; просрочка не предполагается.')
            ask('commitment:'+ref,ref,row['reason'],'Уточнить согласование, статус, владельца и срок; ничего не назначать за человека.')
        else:
            try:
                limit,date_only=deadline(c.get('due'),c.get('timezone') or tz_name)
                clock_utc,limit_utc=now.astimezone(timezone.utc),limit.astimezone(timezone.utc)
                overdue=clock_utc>=limit_utc if date_only else clock_utc>limit_utc
                row.update(kind='overdue' if overdue else 'blocked' if status=='blocked' else 'pending',
                           overdue=overdue,deadline_instant=limit.isoformat(),date_only=date_only,
                           reason='Срок согласованного незавершённого обязательства прошёл.' if overdue else 'Статус обязательства заблокирован.' if status=='blocked' else 'Срок не прошёл.')
                if overdue or status=='blocked': ask('commitment:'+ref,ref,row['reason'],'Уточнить выполнение, блокер или новый согласованный срок; не переносить срок автоматически.')
            except (ValueError,TypeError,OverflowError) as error:
                row.update(kind='deadline_needs_clarification',reason=str(error))
                ask('commitment:'+ref,ref,str(error),'Уточнить ISO-срок и часовой пояс, при неоднозначном времени указать UTC-смещение.')
        if not c.get('commitment_id'): row['identity_note']='Legacy index reference; assign a stable ID before attaching metric results.'
        rows.append(row)
    health=health if health is not None else source_health(project,path)
    source_alerts=[]
    source_day=now.astimezone(display_tz).date()
    changed=set(health['changed_sources'])
    unavailable=set(health['unverifiable_sources'])
    for i,s in enumerate(project['sources']):
        sid=s['source_id'];reasons=[]
        if sid in changed: reasons.append('Версия/набор источников отличается от последней контрольной точки.')
        if sid in unavailable: reasons.append('Источник недоступен или не имеет отслеживаемого локального снимка.')
        if s.get('valid_until') and not timezone_error and date.fromisoformat(s['valid_until'])<source_day:
            reasons.append('Истёк явно записанный срок valid_until: '+s['valid_until'])
        if reasons:
            hit=dependency_impact(project,[sid],[])
            source_alerts.append({'source_id':sid,'object_ref':'/sources/'+str(i),'reasons':reasons,'impact':hit,
                                  'chosen_option_affected':project.get('chosen_option_id') in hit['option_ids']})
            # Tracked version changes first need an agent impact assessment, not a
            # second owner request for the same source event. Expiry/missing data remain actionable.
            if not changes['enabled'] or sid in unavailable or any(r.startswith('Истёк') for r in reasons):
                ask('source:'+sid,'/sources/'+str(i),'; '.join(reasons),'Проверить источник и пересмотреть перечисленные основания/варианты; не обновлять checkpoint вслепую.')
    for sid in sorted(changed-{s['source_id'] for s in project['sources']}):
        ref='/checkpoints/'+str(len(project.get('checkpoints',[]))-1)+'/sources/'+sid.replace('~','~0').replace('/','~1')
        reason='Источник удалён из реестра после контрольной точки.'
        source_alerts.append({'source_id':sid,'object_ref':ref,'reasons':[reason],
                              'impact':dependency_impact(project,[sid],[]),'chosen_option_affected':None})
        ask('source:'+sid,ref,reason,'Проверить причины удаления и связанные основания; не терять историю решения.')
    retired={e['evidence_id'] for e in project['evidence'] if e['status'] in ('stale','withdrawn','contradicted')}
    affected=dependency_impact(project,[],retired)['evidence_ids'] if retired else []
    evidence_alerts=[]
    for i,e in enumerate(project['evidence']):
        if e['evidence_id'] not in affected: continue
        reason=('Явный статус '+e['status']+': '+e['limitations']) if e['evidence_id'] in retired else 'Зависит от явно устаревшего, отозванного или противоречивого основания.'
        hit=dependency_impact(project,[],[e['evidence_id']])
        evidence_alerts.append({'evidence_id':e['evidence_id'],'object_ref':'/evidence/'+str(i),'reason':reason,'impact':hit,
                                'chosen_option_affected':project.get('chosen_option_id') in hit['option_ids']})
        if not changes['enabled'] or (not changes['human_questions'] and
                {project.get('recommended_option_id'),project.get('chosen_option_id')}.intersection(hit['option_ids'])):
            ask('evidence:'+e['evidence_id'],'/evidence/'+str(i),reason,'Перечитать основания и пересмотреть вывод; не восстанавливать статус без проверки.')
    by_eid={e['evidence_id']:e for e in project['evidence']}
    by_source={s['source_id']:s for s in project['sources']}
    receipt_rows=[r for r in project.get('follow_up_reviews',[]) if r.get('kind') != 'resume']
    receipts={(r['result_id'],r['version_hash']) for r in receipt_rows if instant(r['reviewed_at'])<=now}
    previously={r['result_id'] for r in receipt_rows if instant(r['reviewed_at'])<=now}
    results=[]
    for i,r in enumerate(project.get('metric_results',[])):
        version=result_version(project,path,root,r)
        problems=support_blockers(project,path,root,r['evidence_ids'],'Metric support',today=source_day)
        if instant(r['observed_at'])>now: problems.append('Result observed_at is in the future relative to this report clock')
        if r['data_origin']=='real':
            for eid in r['evidence_ids']:
                e=by_eid[eid]
                if e['claim_type'] not in FACTS or e.get('claim_scope') not in ('project_observation','causal_effect'):
                    problems.append('Real result needs recorded observations, not a hypothesis/source description: '+eid)
                if any(by_source[s].get('synthetic') or by_source[s]['kind'] in ('synthetic','model_respondent','agent_note')
                       or by_source[s].get('evidence_scope')=='simulation' for s in e['source_ids']):
                    problems.append('Synthetic/model material cannot substantiate a real metric result: '+eid)
        reviewed=(r['result_id'],version) in receipts
        decision=r.get('human_decision') or {}
        decision_current=bool(decision.get('reference')) and decision.get('version_hash')==version and not problems
        row={**r,'object_ref':'/metric_results/'+str(i),'version_hash':version,'reviewed':reviewed,
             'new_or_changed':not reviewed,'previously_reviewed_version':r['result_id'] in previously,
             'receipt_after_clock':any(x['result_id']==r['result_id'] and x['version_hash']==version and instant(x['reviewed_at'])>now for x in receipt_rows),
             'support_problems':sorted(set(problems)),'human_decision_current':decision_current}
        results.append(row)
        if not decision_current:
            ask('result:'+r['result_id'],row['object_ref'],
                'Основания результата требуют проверки.' if problems else 'Новая или ещё не решённая человеком версия результата; отметка прочтения не означает одобрение.',
                'Проверить источник, сопоставить показатель с review_trigger обязательства и запросить решение человека. Не объявлять цель достигнутой автоматически.')
    from decision_passport import recommendation_answer
    response = recommendation_answer(project,path,root,changes.get('after_version')) if changes['enabled'] else None
    if project['stage'] in ('follow_up','complete') and not project.get('chosen_option_id') and not response:
        ask('decision','/chosen_option_id','Выбор владельца не записан, хотя проект находится после этапа решения.','Уточнить фактическое решение; не выбирать вариант автоматически.')
    return {'project_id':project['project_id'],'as_of':now.isoformat(),'clock_override':at is not None,
            'timezone':tz_name,'source_expiry_timezone':tz_name or 'UTC (legacy expiry convention)',
            'display_time':now.astimezone(display_tz).isoformat(),'context':project.get('follow_up_context','live_project'),
            'commitments':rows,'overdue_commitments':[r for r in rows if r['overdue']],
            'metric_results':results,'new_results':[r for r in results if r['new_or_changed']],
            'source_alerts':source_alerts,'evidence_alerts':evidence_alerts,
            'human_questions':list(questions.values()),
            'note':'Read-only snapshot; old age alone is not staleness. A reviewed result is not an approved decision or completed commitment.'}


def acknowledge(project,path,root,result_ids,reviewer,note):
    from checkpoint import write_state
    from ledger import append,ledger_path,read_entries,verify
    if not nonempty(reviewer) or not nonempty(note): raise ValueError('Reviewer and an actual review note are required')
    if not strings(result_ids) or not result_ids or len(result_ids)!=len(set(result_ids)): raise ValueError('Provide distinct result IDs')
    snapshot=inspect(project,path,root)
    by_id={r['result_id']:r for r in snapshot['metric_results']}
    if not set(result_ids)<=set(by_id): raise ValueError('Unknown result_id')
    if any(by_id[r]['support_problems'] for r in result_ids): raise ValueError('Verify result support/time before acknowledging it')
    added=[r for r in result_ids if not by_id[r]['reviewed']]
    if not added: return {'recorded':[],'note':'Already reviewed; no state or ledger write'}
    if verify(read_entries(ledger_path(path))): raise ValueError('Damaged ledger; do not record a review')
    if json.loads(path.read_text(encoding='utf-8-sig'))!=project: raise ValueError('Project changed; reload before acknowledging')
    candidate=copy.deepcopy(project)
    now=datetime.now(timezone.utc).isoformat(timespec='seconds')
    candidate.setdefault('follow_up_reviews',[]).extend({'result_id':r,'version_hash':by_id[r]['version_hash'],
        'reviewed_at':now,'reviewer':reviewer,'note':note} for r in added)
    from validate_project import validate
    errors=validate(candidate)
    if errors: raise ValueError('; '.join(errors))
    write_state(path,candidate)
    try: append(path,{'step':project['stage'],'action':'review metric results: '+', '.join(added),'actor':'script',
        'status':'done','tool':'scripts/follow_up.py','note':'Read receipt only; no human approval, completion or schedule change. '+note})
    except (OSError,ValueError) as error: raise ValueError('Review receipts saved but ledger append failed; inspect state before retrying: '+str(error)) from error
    return {'recorded':added,'note':'Read only; decisions/commitments unchanged'}


def markdown(result):
    lines=['## Сопровождение после решения','','Проект: '+result['project_id'],
        'Срез времени: '+result['display_time']+'; часовой пояс проекта: '+str(result['timezone']),
        'Режим: '+('воспроизведение на явно заданную дату' if result['clock_override'] else 'текущее время'),
        'Контекст: '+result['context']]
    if result['context']=='authored_example': lines+=['Все согласования и результаты в этом примере вымышлены; это не реальные обязательства или наблюдения.']
    lines+=['','### Обязательства']
    for c in result['commitments']:
        lines+=['- '+c['commitment_id']+' ['+c['kind']+']; '+str(c['owner'])+'; срок: '+str(c['due'])+'; '+c.get('reason','Статус завершения/отмены уже записан.'),
                '  Объект: '+c['object_ref']+'; показатель: '+str(c['metric'])+'; пересмотр: '+str(c['review_trigger'])]
    lines+=['','### Результаты показателей']
    for r in result['metric_results']:
        lines+=['- '+r['result_id']+' → '+r['commitment_id']+': '+r['value']+' '+r['unit']+' ['+r['data_origin']+']; '+('новая/изменённая версия' if r['new_or_changed'] else 'эта версия рассмотрена'),
                '  '+r['summary']+'; основания: '+', '.join(r['evidence_ids'])+'; версия: '+r['version_hash'],
                *['  Требует проверки: '+p for p in r['support_problems']]]
    lines+=['','### Основания для пересмотра']
    for s in result['source_alerts']: lines+=['- Источник '+s['source_id']+': '+'; '.join(s['reasons'])+'; зависимости: '+json.dumps(s['impact'],ensure_ascii=False)]
    for e in result['evidence_alerts']: lines+=['- Вывод '+e['evidence_id']+': '+e['reason']+'; зависимости: '+json.dumps(e['impact'],ensure_ascii=False)]
    lines+=['','### Требуется человек']
    lines.extend('- '+q['object_ref']+': '+q['reason']+' '+q['action'] for q in result['human_questions'])
    lines+=['',result['note']]
    return '\n'.join(lines)+'\n'


def main():
    from checkpoint import ROOT
    from project_tool import load
    from output_guard import check_output
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('inspect','report','acknowledge'))
    p.add_argument('project',type=Path);p.add_argument('--as-of');p.add_argument('--out',type=Path)
    p.add_argument('--result-ids');p.add_argument('--reviewer');p.add_argument('--note');a=p.parse_args()
    try:
        path=a.project.resolve();project=load(path)
        if a.command=='acknowledge':
            if a.as_of or a.out: raise ValueError('Acknowledge uses real record time and does not accept --as-of/--out')
            result=acknowledge(project,path,ROOT,[v.strip() for v in (a.result_ids or '').split(',')],a.reviewer,a.note)
        else: result=inspect(project,path,ROOT,at=instant(a.as_of) if a.as_of else None)
        output=markdown(result) if a.command=='report' else json.dumps(result,ensure_ascii=False,indent=2)
        if a.out:
            check_output(project,path,a.out)
            if a.out.exists(): raise ValueError('Choose a new snapshot filename')
            a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(output.rstrip()+'\n',encoding='utf-8')
        else: print(output)
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as error:p.exit(1,f'Follow-up: {error}\n')


if __name__=='__main__':main()
