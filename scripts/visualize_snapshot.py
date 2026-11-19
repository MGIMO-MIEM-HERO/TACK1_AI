"""Stable, read-only comparison records carried inside each exported map."""
import copy


def comparison_snapshot(project, data, project_path=None):
    records = []
    sources = {s['source_id']: s for s in project['sources']}
    evidence = {e['evidence_id']: e for e in project['evidence']}
    options = {o['option_id']: o for o in project['options']}
    versions = {}
    if project_path is not None:
        from checkpoint import ROOT, fingerprint
        from pathlib import Path
        base = Path(project_path).resolve().parent if project.get('path_base') == 'project' else ROOT
        for sid, row in sources.items():
            try:
                versions[sid] = fingerprint(row.get('snapshot_path') or row['url_or_path'], base)
            except (OSError, UnicodeError, ValueError):
                versions[sid] = 'unavailable: local fingerprint could not be read'

    for node in data['nodes']:
        key = node['id']
        if key == 'task':
            value = {k: project.get(k) for k in ('title', 'objective', 'stage', 'constraints', 'unresolved_questions',
                     'recommended_option_id', 'recommendation_rationale', 'chosen_option_id')}
        elif key == 'review':
            value = {k: project.get(k) for k in ('validation_design', 'validation_plan', 'product_strategy', 'communication_strategy')}
        elif key == 'next':
            value = {'next_action': project['next_action']}
        elif key.startswith('s:'):
            value = copy.deepcopy(sources[key[2:]])
            if key[2:] in versions:
                value['observed_file_version'] = versions[key[2:]]
        elif key.startswith('e:'):
            value = evidence[key[2:]]
        elif key.startswith('o:'):
            value = options[key[2:]]
        else:
            path = node['details'].get('JSON-путь', '')
            # Derived clock-sensitive summaries/audit findings are not independent saved records.
            if not path or path.startswith(('/audit/', '/derived/')):
                continue
            value = project
            for segment in path.lstrip('/').split('/'):
                segment = segment.replace('~1', '/').replace('~0', '~')
                value = value[int(segment)] if isinstance(value, list) else value[segment]
        records.append({'id': key, 'title': node['title'], 'column': node['column'], 'record': copy.deepcopy(value)})
    return {'schema_version': 1, 'project_id': project['project_id'], 'title': project['title'],
            'updated_at': project.get('updated_at'), 'state_sha256': data['state_sha256'], 'records': records,
            'recommendation': {'option_id': project.get('recommended_option_id'),
                               'rationale': project.get('recommendation_rationale')},
            'note': 'Сравниваются сохранённые записи и доступные локальные отпечатки источников. '
                    'Различие не доказывает влияние, истинность или причинность. Удаление из снимка не означает отзыв вывода.'}
