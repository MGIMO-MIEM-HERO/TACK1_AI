"""Check omitted procedures in legacy demos without inventing missing reviews."""
import json
from pathlib import Path

from project_tool import audit, load, report

ROOT = Path(__file__).resolve().parents[1]


def assert_final_blocked(project, path, reason):
    try:
        report(project, path, final=True)
    except ValueError as error:
        assert reason in str(error), str(error)
    else:
        raise AssertionError('Incomplete procedure was accepted for final export')


def verify_demo(case=None):
    cases = []
    paths = [ROOT/'examples'/case/'project.json'] if case else sorted((ROOT/'examples').glob('*/project.json'))
    formerly_complete = {'decision-passport-case', 'research-branches-case', 'feasibility-case',
        'decision-follow-up-case', 'next-research-case', 'marketing-claims-case', 'decision-stress-case', 'review-contract-case'}
    for path in paths:
        project = load(path)
        if not project.get('recommended_option_id'):
            continue
        before = path.read_bytes()
        result = audit(project, path, ready=True, quality=True)
        if path.parent.name in formerly_complete:
            assert result['structural_ready'], result
            assert result['content_review']['blockers'] == [], result
        # These older demonstrations intentionally cover individual features,
        # not the complete mandatory workflow. Never silently fill their history.
        assert result['procedure_requirements']['blockers'] or result['errors'], path
        assert not result['final_ready'] and not result['ready'], path
        assert_final_blocked(project, path, 'Final report' if not result['errors'] else 'Cannot export')
        assert path.read_bytes() == before
        cases.append({'case': path.parent.name, 'final': 'blocked',
                      'missing_procedures': result['procedure_requirements']['blockers']})
    return {'passed': True, 'cases': cases, 'scope': 'Deterministic completeness checks; no fabricated reviews or owner decisions'}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=[p.name for p in (ROOT/'examples').iterdir() if p.is_dir()])
    print(json.dumps(verify_demo(parser.parse_args().case), ensure_ascii=False, indent=2))
