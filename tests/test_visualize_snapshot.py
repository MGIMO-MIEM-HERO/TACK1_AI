import copy
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
from visualize import graph, render
from visualize_snapshot import comparison_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name) / 'case'
        shutil.copytree(ROOT / 'examples/decision-stress-case', self.folder)
        self.path = self.folder / 'project.json'
        self.project = load(self.path)

    def snapshot(self, project=None, result=None):
        project = project or self.project
        result = result or audit(project, self.path, ready=True, quality=True)
        return comparison_snapshot(project, graph(project, result, 'test-hash'), self.path)

    def test_export_clock_and_derived_status_do_not_create_record_differences(self):
        result = audit(self.project, self.path, ready=True, quality=True)
        before = self.snapshot(result=result)
        result['ready'] = not result['ready']
        result['follow_up']['as_of'] = '2099-01-01T00:00:00+00:00'
        result['health']['changed_sources'] = ['BRIEF']
        self.assertEqual(before['records'], self.snapshot(result=result)['records'])
        self.assertFalse(any(r['id'].startswith(('human-question:', 'alert:', 'passport:', 'summary:')) for r in before['records']))

    def test_changed_source_content_is_detected_without_source_metadata_changes(self):
        before = self.snapshot()
        source = self.project['sources'][0]
        file = self.folder / (source.get('snapshot_path') or source['url_or_path'])
        file.write_text(file.read_text(encoding='utf-8') + '\nAdditional authored condition.\n', encoding='utf-8')
        after = self.snapshot()
        sid = 's:' + source['source_id']
        old = next(r['record'] for r in before['records'] if r['id'] == sid)
        new = next(r['record'] for r in after['records'] if r['id'] == sid)
        self.assertNotEqual(old['observed_file_version'], new['observed_file_version'])
        self.assertEqual({k:v for k,v in old.items() if k!='observed_file_version'}, source)

    def test_record_changes_and_recommendation_are_saved_without_invented_reasons(self):
        before = self.snapshot()
        changed = copy.deepcopy(self.project)
        changed['recommended_option_id'] = 'O2'
        changed['recommendation_rationale'] = 'Explicit authored reassessment.'
        changed['evidence'][0]['claim'] = 'Changed authored claim'
        after = self.snapshot(changed)
        self.assertNotEqual(next(r for r in before['records'] if r['id']=='task')['record'], next(r for r in after['records'] if r['id']=='task')['record'])
        self.assertEqual(after['recommendation']['rationale'], changed['recommendation_rationale'])
        self.assertEqual(self.project['recommended_option_id'], 'O1')
        self.assertNotIn('Оценка выбора в паспорте',self.project['options'][0])

    def test_passport_display_does_not_mutate_project_or_comparison_records(self):
        before=copy.deepcopy(self.project)
        result=audit(self.project,self.path,ready=True,quality=True)
        html=render(self.project,result,self.path.read_bytes(),self.path)
        data=json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(self.project,before)
        option=next(r for r in data['comparison_snapshot']['records'] if r['id']=='o:O1')
        self.assertEqual(option['record'],next(o for o in before['options'] if o['option_id']=='O1'))

    def test_source_read_failure_does_not_break_map(self):
        source = self.project['sources'][0]
        file = self.folder / (source.get('snapshot_path') or source['url_or_path'])
        file.write_bytes(b'\xff\xfe\x00')
        # An existing audit result is enough; comparison must not add an export failure.
        result = {'ready':False,'health':{'changed_sources':[],'unverifiable_sources':{},'affected_evidence':[],'affected_options':[]}}
        snapshot = self.snapshot(result=result)
        self.assertIn('unavailable', next(r for r in snapshot['records'] if r['id']=='s:'+source['source_id'])['record']['observed_file_version'])

    def test_native_exports_embed_comparison_and_preserve_state_sources_and_ledger(self):
        def saved():
            return {p.relative_to(self.folder).as_posix(): p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        before = saved()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'brief.md'
            subprocess.run([sys.executable, '-B', str(ROOT/'scripts/project_tool.py'), 'report', str(self.path), '--out', str(out)], check=True, capture_output=True)
            html = out.with_suffix('.graph.html').read_text(encoding='utf-8')
            data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
            snapshot = data['comparison_snapshot']
            self.assertEqual(snapshot['project_id'], self.project['project_id'])
            self.assertEqual(len(snapshot['records']),len({r['id'] for r in snapshot['records']}))
            self.assertIn('changes-file',html)
            self.assertNotIn('__COMPARE_SCRIPT__',html)
            self.assertEqual(html.lower().count('</script>'),2)
        self.assertEqual(before,saved())

    def test_untrusted_saved_text_remains_inert(self):
        self.project['title'] = '</script><img src=x onerror=alert(1)>'
        result = audit(self.project, self.path)
        html = render(self.project,result,b'bytes')
        data = json.loads(html.split('<script id="data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(data['comparison_snapshot']['title'],self.project['title'])
        self.assertNotIn(self.project['title'],html)
