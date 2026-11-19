#!/usr/bin/env python3
"""Authored change-review walkthrough, not a model benchmark or owner approval."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from checkpoint import ROOT, save_checkpoint, write_state
from material_changes import enable, inspect, prepare
from project_tool import load
from quality import state_hash
from start import restore


def verify_demo():
    with tempfile.TemporaryDirectory() as directory:
        case = Path(directory) / 'case'
        shutil.copytree(ROOT / 'examples/decision-follow-up-case', case)
        path = case / 'project.json'; project = load(path)
        original_choice = project.get('chosen_option_id')
        original_commitments = copy.deepcopy(project.get('commitments'))
        enable(project, path, ROOT); project = load(path)

        def refresh():
            project['strategy_review']['state_hash'] = state_hash(project, path, ROOT)
            write_state(path, project)

        def assess(conclusion):
            refresh(); review = prepare(project, path, ROOT)
            review.update(reviewer='Authored agent self-review, not owner approval', conclusion=conclusion,
                          rationale=('Only an unrelated labelled footnote was appended; the cited conditions remain.'
                                     if conclusion == 'unchanged' else 'Authorship reliability is unknown; ask the owner about these grounds.'))
            for effect in review['effects']:
                effect.update(materiality='material' if conclusion == 'unchanged' else 'uncertain',
                              decision_effect=conclusion, evidence_ids=['E1'] if conclusion == 'unchanged' else [],
                              analysis=review['rationale'])
            return review

        refresh(); old_hash = state_hash(project, path, ROOT)
        project['sources'][0]['title'] += ' (display label)'; write_state(path, project)
        cosmetic = inspect(project, path, ROOT)
        assert not cosmetic['needs_assessment'] and not cosmetic['human_questions']
        assert state_hash(project, path, ROOT) == old_hash
        save_checkpoint(project, path, 'Authored display-label change'); project = load(path)

        source = case / 'inputs/brief.md'
        source.write_text(source.read_text(encoding='utf-8') + '\nAuthored unrelated footnote; no actual observation.\n', encoding='utf-8')
        assert inspect(project, path, ROOT)['needs_assessment']
        review = assess('unchanged')
        save_checkpoint(project, path, 'Authored no-impact assessment', reviewed_changes=True, change_review=review)
        project = load(path)
        assert not inspect(project, path, ROOT)['human_questions']

        project['sources'][0]['author'] = 'Unverified authored fixture attribution'
        write_state(path, project); review = assess('unknown')
        review_path = case / 'review.json'; review_path.write_text(json.dumps(review), encoding='utf-8')
        command = [sys.executable, '-B', str(ROOT / 'scripts/material_changes.py'), 'record', str(path), '--review', str(review_path)]
        first = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        assert first.returncode == 0, first.stderr
        before = path.read_bytes(); ledger = (case / 'ledger.jsonl').read_bytes()
        repeated = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        assert repeated.returncode == 0 and not json.loads(repeated.stdout)['recorded'], repeated.stderr
        assert before == path.read_bytes() and ledger == (case / 'ledger.jsonl').read_bytes()
        a = restore(path)['material_changes']; b = restore(path)['material_changes']
        assert a == b and len(a['human_questions']) == 1
        assert before == path.read_bytes() and ledger == (case / 'ledger.jsonl').read_bytes()
        project = load(path)
        assert project.get('chosen_option_id') == original_choice
        assert project.get('commitments') == original_commitments
        assert len(a['history']) == 4
        return {'context': 'authored_example', 'cosmetic_preserves_review': True,
                'content_impact_explained': True, 'uncertainty_visible': True,
                'owner_requests_for_current_change': 1, 'duplicate_record_is_noop': True,
                'history_entries': len(a['history']), 'owner_approval_created': False}


if __name__ == '__main__': print(json.dumps(verify_demo(), ensure_ascii=False, indent=2))
