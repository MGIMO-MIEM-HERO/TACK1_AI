import copy
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import fingerprint, impacted
from project_tool import audit, inspect_file, report
from start import restore
from ledger import append, summarize, render_report
from validate_project import validate


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'source.md').write_text('Original evidence', encoding='utf-8')
        self.project = {'project_id':'test', 'title':'Decision', 'updated_at':'2026-11-14',
            'objective':'Select next research', 'stage':'research', 'next_action':'Compare sources', 'path_base':'project',
            'sources':[{'source_id':'S', 'kind':'document', 'title':'Supplied source', 'url_or_path':'source.md',
                        'accessed_at':'2026-11-14', 'scope':'Test', 'limitations':'Example only'}],
            'evidence':[{'evidence_id':'E1','claim':'A fact','claim_type':'source_fact','source_ids':['S'],
                         'method':'Read source','status':'provisional','limitations':'Example'},
                        {'evidence_id':'E2','claim':'A dependent hypothesis','claim_type':'hypothesis','source_ids':[],
                         'related_evidence_ids':['E1'], 'method':'Inference','status':'provisional','limitations':'Not proved'}],
            'options':[{'option_id':'O1','title':'Investigate','benefits':['Clarity'],'costs_and_risks':['Time'],
                        'objection':'May not change decision','evidence_ids':['E2']}],
            'checkpoints':[{'at':'2026-11-14','summary':'Saved','stage':'research','next_action':'Compare sources',
                            'sources':{'S':{'location':'source.md','fingerprint':fingerprint('source.md',self.root)}}}]}

    def test_changed_sources_block_export_and_propagate(self):
        self.assertEqual(validate(self.project), [])
        (self.root / 'source.md').write_text('New evidence', encoding='utf-8')
        result = audit(self.project, self.root / 'project.json')
        self.assertFalse(result['ready'])
        self.assertEqual(result['health']['affected_evidence'], ['E1','E2'])
        self.assertEqual(result['health']['affected_options'], ['O1'])
        with self.assertRaises(ValueError):
            report(self.project, self.root / 'project.json')

    def test_malformed_and_synthetic_evidence_rejected(self):
        project = copy.deepcopy(self.project)
        project['evidence'][0]['source_ids'] = [{}]
        self.assertTrue(validate(project))
        project = copy.deepcopy(self.project)
        project['sources'][0]['synthetic'] = True
        project['evidence'][0]['claim_type'] = 'qualitative_signal'
        self.assertTrue(any('synthetic' in error for error in validate(project)))

    def test_missing_snapshot_and_unfinished_strategy_not_ready(self):
        self.assertFalse(audit(self.project, self.root/'project.json', ready=True)['ready'])
        self.project['sources'][0]['url_or_path'] = 'https://example.org/source'
        self.assertTrue(audit(self.project, self.root/'project.json')['errors'])

    def test_withdrawn_basis_blocks_indirect_recommendation(self):
        self.project['recommended_option_id'] = 'O1'
        self.project['evidence'][0]['status'] = 'withdrawn'
        result = audit(self.project, self.root/'project.json')
        self.assertFalse(result['ready'])
        self.assertTrue(any('E2' in error for error in result['errors']))

    def test_table_inspection_detects_bad_rows(self):
        path = self.root/'source.csv'
        path.write_text('id,value\na,1\na,1\nb,\nc,3,extra\n', encoding='utf-8')
        result = inspect_file(path)
        self.assertEqual(result['duplicate_rows'], 1)
        self.assertEqual(result['malformed_rows'], 1)
        self.assertEqual(result['missing']['value'], 1)


    def run_cli(self, script, *args):
        return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts' / script),
                               *map(str, args)], capture_output=True, text=True, encoding='utf-8')

    def test_invalid_types_rejected_before_tools_run(self):
        for field, value in [('recommended_option_id', {}), ('unresolved_questions', [42]),
                             ('path_base', 'typo'), ('recommendation_rationale', [])]:
            with self.subTest(field=field):
                project = copy.deepcopy(self.project)
                project[field] = value
                path = self.root / 'project.json'
                path.write_text(json.dumps(project), encoding='utf-8')
                result = self.run_cli('project_tool.py', 'audit', path)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn('Traceback', result.stderr)
        for field, value in [('snapshot_path', []), ('synthetic', 'false')]:
            project = copy.deepcopy(self.project)
            project['sources'][0][field] = value
            self.assertTrue(validate(project))

    def test_bom_state_supported_by_all_readers(self):
        path = self.root / 'project.json'
        path.write_text(json.dumps(self.project), encoding='utf-8-sig')
        for script, args in [('validate_project.py', [path]), ('checkpoint.py', [path, 'resume']),
                             ('project_tool.py', ['audit', path])]:
            with self.subTest(script=script):
                result = self.run_cli(script, *args)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_report_cannot_overwrite_state_sources_or_log(self):
        path = self.root / 'project.json'
        path.write_text(json.dumps(self.project), encoding='utf-8')
        log = self.root / 'runs.jsonl'
        log.write_text('{}\n', encoding='utf-8')
        for output in (path, self.root / 'source.md', log):
            with self.subTest(output=output.name):
                before = output.read_bytes()
                result = self.run_cli('project_tool.py', 'report', path, '--out', output)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(output.read_bytes(), before)
        output = self.root / 'outputs' / 'report.md'
        result = self.run_cli('project_tool.py', 'report', path, '--out', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.is_file())

    def test_fingerprint_ignores_checkout_line_endings(self):
        path = self.root / 'source.md'
        path.write_bytes(b'First\r\nSecond\r\n')
        windows = fingerprint('source.md', self.root)
        path.write_bytes(b'First\nSecond\n')
        self.assertEqual(windows, fingerprint('source.md', self.root))
        path.write_bytes(b'Changed\nSecond\n')
        self.assertNotEqual(windows, fingerprint('source.md', self.root))

    def test_fingerprint_resolves_workspace_alias(self):
        alias = self.root / 'child' / '..'
        (self.root / 'child').mkdir()
        self.assertEqual(fingerprint('source.md', alias), fingerprint('source.md', self.root))

    def test_csv_preserves_quoted_newlines(self):
        path = self.root / 'multiline.csv'
        path.write_text('id,text\n1,"first line\nsecond line"\n', encoding='utf-8')
        result = inspect_file(path)
        self.assertEqual(result['rows'], 1)
        self.assertEqual(result['preview'][0]['text'], 'first line\nsecond line')


    def test_start_restores_case_without_writing(self):
        self.project['recommended_option_id'] = 'O1'
        self.project['constraints'] = ['Zero budget', 'Three days']
        path = self.root / 'project.json'
        path.write_text(json.dumps(self.project), encoding='utf-8')
        before = path.read_bytes()
        state = restore(path)
        self.assertEqual(state['constraints'], ['Zero budget', 'Three days'])
        self.assertEqual(state['recommendation']['id'], 'O1')
        self.assertIsNone(state['human_choice'])
        self.assertTrue(state['workflow_files'])
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / 'ledger.jsonl').exists())

    def test_search_only_indirect_basis_blocks_report(self):
        self.project['recommended_option_id'] = 'O1'
        self.project['sources'][0]['verification'] = 'search_snippet'
        with self.assertRaisesRegex(ValueError, 'search-only'):
            report(self.project, self.root / 'project.json')

    def test_expired_source_blocks_chosen_option_too(self):
        self.project['chosen_option_id'] = 'O1'
        self.project['sources'][0]['valid_until'] = '2000-01-01'
        result = audit(self.project, self.root / 'project.json')
        self.assertTrue(any('Human choice' in e and 'expired' in e for e in result['errors']))
        self.project['sources'][0]['valid_until'] = 'not-a-date'
        self.assertTrue(any('valid_until' in e for e in validate(self.project)))

    def test_withdrawn_evidence_blocks_chosen_option(self):
        self.project['chosen_option_id'] = 'O1'
        self.project['evidence'][0]['status'] = 'withdrawn'
        with self.assertRaisesRegex(ValueError, 'Human choice'):
            report(self.project, self.root / 'project.json')

    def test_damaged_ledger_blocks_report(self):
        path = self.root / 'project.json'
        append(path, {'step':'research', 'action':'Read source', 'status':'done'})
        log = self.root / 'ledger.jsonl'
        log.write_text(log.read_text(encoding='utf-8').replace('Read source', 'Forged source'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'ledger is damaged'):
            report(self.project, path)
        for content in ('[]\n', '{"cost_usd":"unknown"}\n'):
            log.write_text(content, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'ledger is damaged'):
                report(self.project, path)

    def test_unknown_cost_time_and_tokens_are_not_zero_measurements(self):
        entries = [{'seq':1, 'status':'done', 'model':'unknown', 'action':'Analyze'}]
        totals = summarize(entries)['totals']
        self.assertEqual(totals['cost_unknown_actions'], 1)
        self.assertEqual(totals['unknown_duration_actions'], 1)
        self.assertEqual(totals['unknown_human_time_actions'], 1)
        self.assertEqual(totals['unknown_token_actions'], 1)
        text = render_report(self.root / 'project.json', entries)
        self.assertIn('Пропуски не равны нулю', text)
        known = summarize([{'status':'done', 'model':'test', 'cost_usd':0, 'duration_s':0,
                            'human_minutes':0, 'tokens':{'input':0,'output':0}}])['totals']
        self.assertEqual(known['unknown_duration_actions'], 0)
        self.assertEqual(known['cost_unknown_actions'], 0)

    def test_ledger_report_cannot_overwrite_inputs(self):
        path = self.root / 'project.json'
        path.write_text(json.dumps(self.project), encoding='utf-8')
        append(path, {'step':'research', 'action':'Read source', 'status':'done'})
        for output in (path, self.root / 'source.md', self.root / 'ledger.jsonl'):
            before = output.read_bytes()
            result = self.run_cli('ledger.py', 'report', path, '--out', output)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(output.read_bytes(), before)

    def test_ledger_rejects_invalid_numbers(self):
        path = self.root / 'project.json'
        for flag, value in [('--cost-usd','nan'), ('--duration-s','-1'), ('--input-tokens','-1')]:
            result = self.run_cli('ledger.py','log',path,'--step','test','--action','test',flag,value)
            self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / 'ledger.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
