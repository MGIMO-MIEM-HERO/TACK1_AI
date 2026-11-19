import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from project_tool import audit, load
from visualize import render


def payload(html):
    return json.loads(html.split('<script id="data" type="application/json">', 1)[1].split('</script>', 1)[0])


class DecisionVisualizationTests(unittest.TestCase):
    def export(self, path):
        project = load(path)
        result = audit(project, path, ready=True, quality=True)
        data = payload(render(project, result, path.read_bytes(), path))
        ids = [n['id'] for n in data['nodes']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in data['edges']))
        return data, result

    def test_feasibility_outcomes_and_resource_allocations_come_from_inspector(self):
        data, result = self.export(ROOT / 'examples/feasibility-case/project.json')
        nodes = {n['id']: n for n in data['nodes']}
        review = result['feasibility']['review_id']
        for row in result['feasibility']['assessments']:
            key = 'feasibility:' + review + ':' + row['option_id']
            self.assertIn(row['outcome'], nodes[key]['status'])
            self.assertEqual(nodes[key]['details']['Вычисленный исход'], row)
            self.assertEqual(nodes[key]['details']['permission'], row['plan']['permission'])
        allocations = [n for n in data['nodes'] if ':allocation:' in n['id']]
        self.assertTrue(allocations)
        for allocation in allocations:
            incoming = [e['source'] for e in data['edges'] if e['target'] == allocation['id']]
            self.assertTrue(any(':work:' in key for key in incoming))
            self.assertTrue(any(':resources:' in key for key in incoming))

    def test_insufficient_data_is_a_branch_without_automatic_choice(self):
        path = ROOT / 'examples/research-branches-case/project.json'
        data, result = self.export(path)
        nodes = {n['id']: n for n in data['nodes']}
        for row in result['research_selection']['branch_resolutions']:
            key = 'research:' + result['research_selection']['review_id'] + ':gaps:' + row['question_id'] + ':resolution'
            self.assertEqual(nodes[key]['status'], row['status'])
            self.assertEqual(nodes[key]['details']['next_step'], row['next_step'])
        self.assertTrue(any(':branch:' in n['id'] and 'insufficient_data' in n['status'] for n in data['nodes']))
        self.assertIsNone(load(path).get('chosen_option_id'))

    def test_passport_answers_keep_subject_version_and_history(self):
        data, _ = self.export(ROOT / 'examples/decision-passport-case/project.json')
        answers = [n for n in data['nodes'] if n['id'].startswith('answer:')]
        self.assertEqual(len(answers), 4)
        historical = [n for n in answers if n['details']['status'] == 'historical']
        self.assertEqual(len(historical), 3)
        self.assertEqual({n['details']['kind'] for n in answers}, {'recommendation', 'permission', 'data'})
        self.assertTrue(all(n['details']['identity_verified'] is False for n in answers))
        for n in historical:
            self.assertFalse(any(e['source'] == n['id'] for e in data['edges']))
        current = next(n for n in answers if n['details']['status'] == 'current')
        self.assertEqual(current['details']['kind'], 'recommendation')
        self.assertTrue(any(e['source'] == current['id'] and e['target'] == 'passport:current' for e in data['edges']))

    def test_resume_receipt_does_not_crash_and_next_step_uses_current_summary(self):
        path = ROOT / 'examples/decision-passport-case/project.json'
        data, _ = self.export(path)
        nodes = {n['id']: n for n in data['nodes']}
        self.assertTrue(any(n['id'].startswith('summary-receipt:') for n in data['nodes']))
        self.assertIn('не согласие', next(n['status'] for n in data['nodes'] if n['id'].startswith('summary-receipt:')))
        self.assertEqual(nodes['next']['details']['Проверенный следующий шаг'], nodes['summary:current']['details']['Следующий шаг'])
        self.assertEqual(nodes['next']['details']['Ранее записанный план (требует проверки актуальности)'], load(path)['next_action'])

    def test_cosmetic_change_is_visible_without_promoting_old_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'case'
            shutil.copytree(ROOT / 'examples/decision-passport-case', folder)
            path = folder / 'project.json'
            project = load(path)
            project['title'] += ' — отображаемое название'
            path.write_text(json.dumps(project, ensure_ascii=False), encoding='utf-8')
            data, result = self.export(path)
            event = next(n for n in data['nodes'] if n['id'].startswith('change-event:') and n['details']['kind']=='presentation')
            self.assertEqual(event['status'], 'cosmetic')
            self.assertEqual(result['material_changes']['status'], 'pending')
            self.assertTrue(any(n['id'].startswith('change-review:') for n in data['nodes']))
            self.assertEqual(len([n for n in data['nodes'] if n['id'].startswith('answer:') and n['details']['status']=='historical']), 3)

    def test_direct_and_report_exports_cover_new_features_without_writes(self):
        path = ROOT / 'examples/decision-passport-case/project.json'
        def hashes():
            return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.parent.rglob('*') if p.is_file()}
        before = hashes()
        with tempfile.TemporaryDirectory() as tmp:
            direct = Path(tmp) / 'direct.html'
            report = Path(tmp) / 'brief.md'
            for args in [[str(ROOT / 'scripts/visualize.py'), str(path), '--out', str(direct)],
                         [str(ROOT / 'scripts/project_tool.py'), 'report', str(path), '--out', str(report)]]:
                subprocess.run([sys.executable, *args], check=True, capture_output=True)
            for html in [direct.read_text(encoding='utf-8'), report.with_suffix('.graph.html').read_text(encoding='utf-8')]:
                data = payload(html)
                self.assertTrue({'summary:current', 'passport:current', 'changes:current'} <= {n['id'] for n in data['nodes']})
                self.assertTrue(any(n['column']==10 for n in data['nodes']))
                self.assertTrue(any(':resolution' in n['id'] for n in data['nodes']))
        self.assertEqual(before, hashes())


if __name__ == '__main__':
    unittest.main()
