#!/usr/bin/env python3
"""Authored continuation walkthrough; no real owner approval or model benchmark."""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from checkpoint import ROOT
from project_tool import load
from resume_summary import acknowledge
from start import restore


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        case = Path(directory) / 'case'
        shutil.copytree(ROOT / 'examples/research-branches-case', case)
        path = case / 'project.json'; original = load(path)
        protected = {k: copy.deepcopy(original.get(k)) for k in ('chosen_option_id', 'commitments', 'metric_results', 'checkpoints')}
        before = path.read_bytes(); ledger = (case / 'ledger.jsonl').read_bytes()
        first = restore(path)['resume_summary']
        assert first['changes']['status'] == 'first_review'
        assert 'unknown' in first['next_step']['text'] and 'W1' in first['next_step']['text']
        assert first == restore(path)['resume_summary']
        assert before == path.read_bytes() and ledger == (case / 'ledger.jsonl').read_bytes()
        acknowledge(path, first['version_hash'], 'Authored agent self-review', 'Read the authored resource uncertainty; no actual owner approval')
        current = restore(path)['resume_summary']
        assert current['changes']['status'] == 'unchanged'
        assert current['owner']['status'] == 'awaiting_decision'
        before = path.read_bytes(); ledger = (case / 'ledger.jsonl').read_bytes()
        assert not acknowledge(path, current['version_hash'], 'Authored agent', 'Same view')['recorded']
        assert before == path.read_bytes() and ledger == (case / 'ledger.jsonl').read_bytes()
        source = case / 'inputs/active-condition.md'
        source.write_text(source.read_text(encoding='utf-8') + '\nNew authored condition to assess; not a real team observation.\n', encoding='utf-8')
        changed = restore(path)['resume_summary']
        assert changed['changes']['status'] == 'changed' and 'Разобрать изменения' in changed['next_step']['text']
        try: acknowledge(path, first['version_hash'], 'Authored agent', 'Stale view')
        except ValueError: pass
        else: raise AssertionError('Stale summary was acknowledged')
        acknowledge(path, changed['version_hash'], 'Authored agent', 'Read changed source; reassessment still pending')
        state = restore(path)
        assert state['audit']['health']['changed_sources']
        assert 'Разобрать изменения' in state['resume_summary']['next_step']['text']
        project = load(path)
        assert all(project.get(k) == value for k, value in protected.items())
        return {'context': 'authored_example', 'four_points': ['changes', 'decision', 'owner', 'next_step'],
                'unknown_resources_remain_unknown': True, 'repeat_view_is_noop': True,
                'view_does_not_accept_changed_source': True, 'stale_view_rejected': True,
                'human_choice_or_approval_created': False}


if __name__ == '__main__': print(json.dumps(verify_demo(), ensure_ascii=False, indent=2))
