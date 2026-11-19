import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from visualize import graph, render


class VisualizationTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.project = json.loads((root / 'examples/review-contract-case/project.json').read_text(encoding='utf-8'))
        self.audit = {'ready': False, 'health': {'changed_sources': ['S'],
                      'affected_evidence': ['E1'], 'affected_options': ['O0'], 'unverifiable_sources': {}},
                      'errors': ['test blocker']}

    def test_dependencies_and_human_choice_are_not_invented(self):
        result = graph(self.project, self.audit, 'abc')
        nodes = {n['id']: n for n in result['nodes']}
        self.assertEqual(nodes['s:S']['status'], 'изменён')
        self.assertIn('пересмотра', nodes['e:E1']['status'])
        self.assertIn({'source': 's:S', 'target': 'e:E1', 'label': 'источник; см. support'}, result['edges'])
        self.assertFalse(any('выбор человека' in n['status'] for n in result['nodes']))
        self.assertEqual(nodes['review']['details']['Выбор человека'], 'не зафиксирован')
        self.assertEqual(nodes['review']['status'], 'есть блокеры')
        self.assertEqual(nodes['review']['details']['Дизайн проверки']['status'], 'planned')

    def test_untrusted_text_cannot_break_out_of_inert_payload(self):
        hostile = '</script><img src=x onerror=alert(1)>&'
        self.project['title'] = hostile
        html = render(self.project, self.audit, b'original state')
        self.assertNotIn(hostile, html)
        payload = html.split('<script id="data" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertEqual(json.loads(payload)['title'], hostile)
        self.assertNotIn('https://', html)
        self.assertNotIn('innerHTML', html)

    def test_minimal_intake_has_no_fabricated_research(self):
        self.project['sources'] = []
        self.project['evidence'] = []
        self.project['options'] = []
        result = graph(self.project, self.audit, 'abc')
        self.assertEqual([n['id'] for n in result['nodes']], ['task', 'review', 'next'])
        self.assertEqual(len(result['edges']), 1)

    def test_source_instruction_flags_are_visible(self):
        self.project['sources'][0]['injection_flags'] = ['instruction_in_document']
        result = graph(self.project, self.audit, 'abc')
        source = next(n for n in result['nodes'] if n['id'].startswith('s:'))
        self.assertIn('предупреждение', source['status'])
        self.assertEqual(source['details']['injection_flags'], ['instruction_in_document'])

    def test_review_exposes_blockers_and_does_not_invent_results(self):
        self.audit['warnings'] = ['source warning']
        self.audit['content_review'] = {'blockers': ['review blocker']}
        result = graph(self.project, self.audit, 'abc')
        review = next(n for n in result['nodes'] if n['id'] == 'review')['details']
        self.assertEqual(review['Блокеры и предупреждения'],
                         ['test blocker', 'source warning', 'review blocker'])
        self.assertEqual(review['Статус эксперимента'], 'planned')
        self.assertEqual(review['Результаты эксперимента'], 'Результаты не записаны')
        self.project['validation_design']['results'] = {'summary': 'Recorded result'}
        updated = graph(self.project, self.audit, 'abc')
        review = next(n for n in updated['nodes'] if n['id'] == 'review')['details']
        self.assertEqual(review['Результаты эксперимента'], {'summary': 'Recorded result'})


if __name__ == '__main__':
    unittest.main()
