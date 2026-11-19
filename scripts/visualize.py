#!/usr/bin/env python3
"""Offline project graph. Edges describe recorded dependencies, not causality."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

from output_guard import check_output


def graph(project, audit_result, state_hash):
    nodes, edges = [], []

    def node(key, column, title, status, details):
        nodes.append(dict(id=key, column=column, title=title, status=status, details=copy.deepcopy(details)))

    def edge(source, target, label):
        edges.append(dict(source=source, target=target, label=label))

    node('task', 0, project['title'], project['stage'],
         {'Цель': project['objective'], 'Ограничения': project.get('constraints', []),
          'Неизвестное': project.get('unresolved_questions', [])})
    health = audit_result['health']
    for source in project['sources']:
        sid = source['source_id']
        status = 'изменён' if sid in health['changed_sources'] else 'записан'
        if sid in health['unverifiable_sources']:
            status = 'недоступен'
        if source.get('injection_flags'):
            status += ' · предупреждение: команды в документе'
        node('s:' + sid, 1, sid + ' · ' + source['title'], status, source)
        edge('task', 's:' + sid, 'материал задачи')
    for item in project['evidence']:
        eid = item['evidence_id']
        status = item['claim_type'] + ' · ' + item['status']
        if eid in health['affected_evidence']:
            status += ' · требует пересмотра'
        node('e:' + eid, 2, eid + ' · ' + item['claim'], status, item)
        for sid in item['source_ids']:
            edge('s:' + sid, 'e:' + eid, 'источник; см. support')
        for ref in item.get('related_evidence_ids', []):
            edge('e:' + ref, 'e:' + eid, 'связанный вывод')
    for option in project['options']:
        oid = option['option_id']
        marks = [option.get('kind', 'тип не указан')]
        if oid == project.get('recommended_option_id'):
            marks.append('рекомендация агента')
        if oid == project.get('chosen_option_id'):
            marks.append('выбор человека')
        if oid in health['affected_options']:
            marks.append('требует пересмотра')
        node('o:' + oid, 3, oid + ' · ' + option['title'], ' · '.join(marks), option)
        for ref in option['evidence_ids']:
            edge('e:' + ref, 'o:' + oid, 'основание варианта; не доказательство')
    node('review', 4, 'Проверка и решение',
         'проверки пройдены' if audit_result['ready'] else 'есть блокеры',
         {'Рекомендация': project.get('recommended_option_id'),
          'Обоснование': project.get('recommendation_rationale'),
          'Выбор человека': project.get('chosen_option_id') or 'не зафиксирован',
          'Блокеры и предупреждения': (audit_result.get('errors', [])
                                      + audit_result.get('warnings', [])
                                      + audit_result.get('content_review', {}).get('blockers', [])),
          'Статус эксперимента': project.get('validation_design', {}).get('status', 'не записан'),
          'Результаты эксперимента': project.get('validation_design', {}).get('results') or 'Результаты не записаны',
          'Дизайн проверки': project.get('validation_design', {}),
          'План проверки': project.get('validation_plan', {}),
          'Аудит': audit_result})
    for option in project['options']:
        edge('o:' + option['option_id'], 'review', 'сравнить / проверить')
    node('next', 5, 'Следующий шаг', 'сохранённый план',
         {'Действие': project['next_action'], 'Обязательства': project.get('commitments', []),
          'Контрольные точки': project.get('checkpoints', [])})
    edge('review', 'next', 'продолжение; не факт выполнения')
    from visualize_features import extend_graph
    extend_graph(project, audit_result, nodes, edges)
    return dict(title=project['title'], updated_at=project.get('updated_at'),
                state_sha256=state_hash, nodes=nodes, edges=edges)


def render(project, audit_result, state_bytes, project_path=None):
    if project_path is not None:
        from checkpoint import ROOT, ledger_summary
        from resume_summary import build as summary_build
        from decision_passport import build as passport_build
        path = Path(project_path).resolve()
        summary = summary_build(project, path, ROOT, audit_result,
                                audit_result['follow_up'], ledger_summary(path))
        state = {**audit_result, 'audit': audit_result, 'resume_summary': summary}
        audit_result = {**audit_result, 'visual_views': {
            'summary': summary, 'passport': passport_build(path, state=state)}}
    data = graph(project, audit_result, hashlib.sha256(state_bytes).hexdigest())
    from visualize_snapshot import comparison_snapshot
    data['comparison_snapshot'] = comparison_snapshot(project, data, project_path)
    # JSON is embedded as inert text. Escape HTML delimiters, including </script>.
    payload = json.dumps(data, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    return HTML.replace('__GRAPH_DATA__', payload)


_TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'
HTML = (_TEMPLATES / 'work-graph.html').read_text(encoding='utf-8').replace(
    '__COMPARE_SCRIPT__', (_TEMPLATES / 'snapshot-compare.js').read_text(encoding='utf-8'))


def main():
    from project_tool import load, audit
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        path = args.project.resolve()
        project = load(path)
        check_output(project, path, args.out)
        result = audit(project, path, ready=True, quality=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render(project, result, path.read_bytes(), path), encoding='utf-8')
        print(args.out)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f'Visualization: {error}\n')


if __name__ == '__main__':
    sys.exit(main())
