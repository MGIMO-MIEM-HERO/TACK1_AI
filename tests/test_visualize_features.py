import copy
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from project_tool import audit, load
from visualize import graph


class FeatureVisualizationTests(unittest.TestCase):
    def case(self, name):
        path = ROOT / 'examples' / name / 'project.json'
        project = load(path)
        before = path.read_bytes()
        result = audit(project, path, ready=True, quality=True)
        data = graph(project, result, 'test')
        self.assertEqual(before, path.read_bytes())
        ids = [n['id'] for n in data['nodes']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in data['edges']))
        return project, result, data

    def test_stress_scenarios_and_history_do_not_choose_for_human(self):
        project, audit_result, data = self.case('decision-stress-case')
        scenarios = [n for n in data['nodes'] if ':scenarios:' in n['id']]
        self.assertEqual(len(scenarios), 3)
        self.assertTrue(all('hypothetical' in n['status'] for n in scenarios))
        old = copy.deepcopy(project['decision_stress_tests'][0])
        project['decision_stress_tests'].append({**copy.deepcopy(old), 'review_id': 'R2'})
        project['decision_stress_tests'][0]['assumptions'][0]['evidence_ids'] = ['REMOVED']
        audit_result['decision_stress_test']['status'] = 'stale'
        updated = graph(project, audit_result, 'test')
        self.assertIn('историческая', next(n for n in updated['nodes'] if n['id']=='stress:R1')['status'])
        self.assertEqual(next(n for n in updated['nodes'] if n['id']=='stress:R2')['status'], 'stale')
        self.assertFalse(any(e['source'].startswith(('s:', 'e:', 'o:')) and e['target'].startswith('stress:R1') for e in updated['edges']))
        self.assertIsNone(project.get('chosen_option_id'))

    def test_claims_keep_wording_proof_and_capability_separate(self):
        project, _, data = self.case('marketing-claims-case')
        for field, prefix in [('product_capabilities','cap:'), ('marketing_claims','claim:')]:
            self.assertEqual(len(project[field]), len([n for n in data['nodes'] if n['id'].startswith(prefix)]))
        for row in project['marketing_claims_audits'][-1]['assessments']:
            node = next(n for n in data['nodes'] if n['id'].endswith(':assessments:'+row['claim_id']))
            self.assertEqual(node['details']['accepted_wording'], row['accepted_wording'])
            self.assertIn(row['status'], node['status'])
            self.assertTrue(any(e['source']=='claim:'+row['claim_id'] and e['target']==node['id'] for e in data['edges']))

    def test_research_methods_effort_stop_and_priority_are_preserved(self):
        project, _, data = self.case('next-research-case')
        review = project['research_selection_reviews'][-1]
        self.assertEqual(next(n for n in data['nodes'] if n['id'].endswith(':stop_rule'))['details']['condition'], review['stop_rule']['condition'])
        methods = [n for n in data['nodes'] if ':method:' in n['id']]
        self.assertEqual(len(methods), sum(len(g['methods']) for g in review['gaps']))
        self.assertTrue(any(n['details']['effort']['time']['status']=='unknown' for n in methods))
        self.assertEqual(len({n['id'] for n in methods}), len(methods))

    def test_followup_uses_inspector_for_deadlines_receipts_and_questions(self):
        project, result, data = self.case('decision-follow-up-case')
        nodes = {n['id']: n for n in data['nodes']}
        for row in result['follow_up']['commitments']:
            self.assertEqual(nodes['commitment:'+row['commitment_id']]['status'], row['kind'])
        for row in result['follow_up']['metric_results']:
            self.assertEqual(nodes['result:'+row['result_id']]['details']['Проверка результата'], row)
            self.assertIn(row['data_origin'], nodes['result:'+row['result_id']]['status'])
        self.assertEqual(len(result['follow_up']['human_questions']), len([n for n in data['nodes'] if n['id'].startswith('human-question:')]))
        self.assertIn('не одобрение', nodes['receipt:0']['status'])
        project['follow_up_reviews'][0]['version_hash']='obsolete'
        changed = graph(project,result,'test')
        self.assertFalse(any(e['source']=='result:R1' and e['target']=='receipt:0' for e in changed['edges']))

    def test_report_automatically_includes_new_feature_graph(self):
        path = ROOT / 'examples/next-research-case/project.json'
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'brief.md'
            subprocess.run([sys.executable, str(ROOT / 'scripts/project_tool.py'), 'report', str(path), '--out', str(out)], check=True, capture_output=True)
            html = out.with_suffix('.graph.html').read_text(encoding='utf-8')
            self.assertIn('research:R1:stop_rule', html)
            self.assertIn('brief.graph.html', out.read_text(encoding='utf-8'))
            self.assertIn('group:research', html)


if __name__ == '__main__':
    unittest.main()
