#!/usr/bin/env python3
"""Check whether two recorded runs can support the declared comparison. Does not grade answers."""
import argparse
import hashlib
import json
from pathlib import Path


def digest_file(base, value):
    if not isinstance(value, str) or not value:
        raise ValueError('A nonempty artifact path is required')
    path = (base / value).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError('Artifact missing or outside manifest directory: ' + value)
    raw = path.read_bytes()
    try:
        raw = raw.decode('utf-8-sig').replace('\r\n', '\n').encode('utf-8')
    except UnicodeError:
        pass
    return hashlib.sha256(raw).hexdigest()


def load_manifest(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('Run manifest must be an object')
    for key in ('model', 'session_mode', 'agent_revision', 'mode'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError('Missing ' + key)
    if data['session_mode'] not in ('fresh', 'continuation') or data['mode'] not in ('agent', 'plain_chat'):
        raise ValueError('Invalid run mode')
    if not isinstance(data.get('model_settings'), dict) or not isinstance(data.get('tools'), list) or not all(isinstance(t, str) for t in data['tools']):
        raise ValueError('Record model_settings and available tools')
    if type(data.get('time_budget_seconds')) is not int or data['time_budget_seconds'] <= 0:
        raise ValueError('Record a positive time budget')
    materials = data.get('material_paths')
    if not isinstance(materials, list):
        raise ValueError('material_paths must be an array')
    base = path.parent
    return {**data, 'task_hash': digest_file(base, data.get('task_path')),
            'material_hashes': sorted(digest_file(base, p) for p in materials),
            'answer_hash': digest_file(base, data.get('answer_path'))}


def compare(left, right, kind):
    if kind not in ('behavioral_repeat', 'version_comparison', 'agent_vs_chat'):
        raise ValueError('Unknown comparison kind')
    mismatches = []
    for field in ('task_hash', 'material_hashes', 'model', 'model_settings', 'time_budget_seconds', 'session_mode'):
        if left[field] != right[field]:
            mismatches.append('Different ' + field)
    if sorted(left['tools']) != sorted(right['tools']):
        mismatches.append('Different available tools')
    if kind in ('version_comparison', 'agent_vs_chat') and (left['session_mode'] != 'fresh' or right['session_mode'] != 'fresh'):
        mismatches.append('Independent fresh contexts required for an improvement claim')
    if kind == 'version_comparison':
        if left['agent_revision'] == right['agent_revision']:
            mismatches.append('Same agent revision: cannot demonstrate a version improvement')
        if left['mode'] != 'agent' or right['mode'] != 'agent':
            mismatches.append('Version comparison requires two agent runs')
    if kind == 'agent_vs_chat' and {left['mode'], right['mode']} != {'agent', 'plain_chat'}:
        mismatches.append('Need one agent run and one plain-chat run')
    return {'comparable': not mismatches, 'comparison_kind': kind, 'mismatches': mismatches,
            'note': 'Manifest consistency only; model/settings/version are declared, artifact hashes are computed. '
                    'One pair cannot establish superiority. Use repeated runs and blind assessment of quality, errors, cost and human time.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('--kind', choices=('behavioral_repeat', 'version_comparison', 'agent_vs_chat'), required=True)
    args = parser.parse_args()
    try:
        result = compare(load_manifest(args.left.resolve()), load_manifest(args.right.resolve()), args.kind)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['comparable'] else 1
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f'Comparison: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
