import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint import fingerprint, impacted
from project_tool import audit, inspect_file, report
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


if __name__ == '__main__':
    unittest.main()
