"""Prevent generated reports from replacing research inputs or persistent state."""
from pathlib import Path

from checkpoint import ROOT


def check_output(project, project_path, output):
    path = Path(project_path).resolve()
    base = path.parent if project.get('path_base') == 'project' else ROOT
    protected = {path, (path.parent / 'runs.jsonl').resolve(), (path.parent / 'ledger.jsonl').resolve()}
    for source in project.get('sources', []):
        for key in ('url_or_path', 'snapshot_path'):
            location = source.get(key)
            if location and not location.startswith(('http://', 'https://')):
                protected.add((base / location).resolve())
    if Path(output).resolve() in protected:
        raise ValueError('Report output must not overwrite project state, sources or run log')
