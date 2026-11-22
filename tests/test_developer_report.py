"""Regressions D-01 through D-03 from the 22 November developer review."""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote
from unittest.mock import patch

import test_stress_test as fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import ROOT, write_state
from project_tool import audit, load, report, source_link
from quality import state_hash
from start import restore
from validate_project import validate


class RequiredProcedureTests(unittest.TestCase):
    setUp = fixture.StressTests.setUp
    complete_record = fixture.StressTests.complete_record
    review = fixture.StressTests.review

    def complete(self):
        self.review()
        self.project['strategy_review']['state_hash'] = state_hash(self.project, self.path, ROOT)
        return self.project

    def test_missing_whole_review_blocks_final_but_not_draft(self):
        self.complete_record()
        result = audit(self.project, self.path, ready=True, quality=True)
        self.assertFalse(result['ready'])
        self.assertFalse(result['final_ready'])
        self.assertEqual(result['procedure_requirements']['checks']['decision_stress_test']['status'], 'not_recorded')
        with self.assertRaisesRegex(ValueError, 'Required decision stress'):
            report(self.project, self.path, final=True)
        self.assertIn('Обязательные процедуры', report(self.project, self.path))

    def test_complete_procedures_allow_document_without_inventing_owner_choice(self):
        project = self.complete()
        self.assertTrue(audit(project, self.path, ready=True, quality=True)['final_ready'])
        self.assertIn('Записка для решения', report(project, self.path, final=True))
        self.assertIsNone(project.get('chosen_option_id'))
        project['constraints'].append('New adverse constraint')
        with self.assertRaises(ValueError): report(project, self.path, final=True)

    def test_development_requires_resource_check_and_unknown_applicability_blocks(self):
        project = self.complete()
        for status in ('required', None):
            if status:
                project['options'][0]['feasibility_requirement'] = {
                    'status': status, 'action':'development', 'rationale':'Implement a working prototype'}
            else:
                project['options'][0].pop('feasibility_requirement')
            result = audit(project, self.path, ready=True, quality=True)
            self.assertFalse(result['ready'])
            self.assertIn('feasibility', ' '.join(result['procedure_requirements']['blockers']).lower())
        project['options'][0]['feasibility_requirement'] = {
            'status':'not_applicable', 'action':'launch', 'rationale':'Unsupported exemption'}
        self.assertTrue(validate(project))

    def test_invalid_or_empty_applicability_is_not_an_exemption(self):
        self.complete_record()
        for value in (None, {}, {'status':'not_applicable','action':'research','rationale':' '},
                      {'status':'not_applicable','action':'unclassified','rationale':'Unknown action'}):
            self.project['options'][0]['feasibility_requirement'] = value
            self.assertTrue(validate(self.project))

    def test_existing_unknown_resource_is_not_automatically_infeasible(self):
        path = ROOT/'examples/research-branches-case/project.json'
        result = audit(load(path), path, ready=True, quality=True)
        self.assertEqual(result['feasibility']['assessments'][0]['outcome'], 'unknown')
        self.assertEqual(result['procedure_requirements']['checks']['feasibility']['status'], 'review_record_complete')
        self.assertFalse(result['final_ready'])  # Missing scenarios still block the final document.

    def test_reported_examples_reject_final_without_writing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('review-contract-case', 'research-branches-case'):
                out = Path(directory)/(name+'.md')
                result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/project_tool.py'),
                    'report', str(ROOT/'examples'/name/'project.json'), '--out', str(out), '--final'],
                    capture_output=True, text=True, encoding='utf-8')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Required decision stress', result.stderr)
                self.assertFalse(out.exists())
                self.assertFalse(out.with_suffix('.graph.html').exists())


class ExportSourceTests(unittest.TestCase):
    def test_native_exports_resolve_sources_from_each_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)/'кейс с пробелами'
            shutil.copytree(ROOT/'examples/review-contract-case', case)
            original = {str(p.relative_to(case)):p.read_bytes() for p in case.rglob('*') if p.is_file()}
            path = case/'project.json'
            for out in (case/'brief.md', case/'outputs/записка.md', Path(directory)/'внешняя папка/brief.md'):
                result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/project_tool.py'),
                    'report', str(path), '--out', str(out)], capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                links = re.findall(r'\]\(([^)]+)\)', out.read_text(encoding='utf-8'))
                for location in links:
                    if location.startswith(('https://', 'http://')): continue
                    self.assertTrue((out.parent/unquote(location)).is_file(), location)
                self.assertIn(out.with_suffix('.graph.html').name, [unquote(link) for link in links])
            for name, content in original.items(): self.assertEqual((case/name).read_bytes(), content)

    def test_spaces_unicode_delimiters_and_repository_base(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base/'материалы/Источник #1% [а](б).md'
            source.parent.mkdir(); source.write_text('Source', encoding='utf-8')
            project_path = base/'case/project.json'
            output = base/'отчёт/brief.md'
            with patch('project_tool.ROOT', base):
                link = source_link({}, project_path, {'url_or_path':str(source.relative_to(base))}, output)
            self.assertNotIn(' ', link); self.assertNotIn('#', link); self.assertNotIn('(', link)
            self.assertEqual((output.parent/unquote(link)).resolve(), source.resolve())
            url = 'https://example.org/path?q=a%20b#section'
            self.assertEqual(source_link({}, project_path, {'url_or_path':url}, output), url)


class DecisionRoleTests(unittest.TestCase):
    setUp = fixture.StressTests.setUp
    complete_record = fixture.StressTests.complete_record

    def test_absent_matching_different_and_historical_choice_are_distinct(self):
        self.complete_record()
        for chosen in (None, 'O1', 'O0'):
            self.project['chosen_option_id'] = chosen
            self.project['commitments'] = ([{'owner':'Authored test owner, not a real person',
                'metric':'Review test case', 'due':'2099-01-01', 'review_trigger':'Test input changes'}] if chosen else [])
            write_state(self.path, self.project)
            before = self.path.read_bytes()
            summary = restore(self.path)['resume_summary']['decision']
            self.assertIn('Рекомендация агента: O1', summary['text'])
            self.assertEqual(summary['recommendation_id'], 'O1')
            self.assertEqual(summary['owner_choice_id'], chosen)
            self.assertIn('не записан' if chosen is None else chosen, summary['text'])
            self.assertNotIn('Текущее решение:', summary['text'])
            self.assertEqual(before, self.path.read_bytes())
        path = ROOT/'examples/paired-case-review/project.json'
        summary = restore(path)['resume_summary']['decision']
        self.assertIn('Рекомендация агента: O2', summary['text'])
        self.assertIn('Прежний выбор владельца: O1', summary['text'])
        self.assertEqual(summary['owner_choice_status'], 'historical')


if __name__ == '__main__': unittest.main()
