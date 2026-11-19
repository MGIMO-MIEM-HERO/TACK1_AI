import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from checkpoint import write_state
from project_tool import audit,load
from quality import state_hash
from research_selection import baseline,record
from visualize import graph,render


def payload(html):
    return json.loads(html.split('<script id="data" type="application/json">',1)[1].split('</script>',1)[0])


class NullableBranchTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.case=Path(directory.name)/'case'
        shutil.copytree(ROOT/'examples/research-branches-case',self.case)
        self.path=self.case/'project.json';self.project=load(self.path)

    def contextual(self, *, mixed=True):
        # Save through the actual review writer; resolutions are derived, never invented IDs.
        self.project['research_questions'].append({'question_id':'Q_CONTEXT','question':'What are the inference limits?',
            'could_change':'Context for the owner; no selection of an alternative'})
        write_state(self.path,self.project)
        review=copy.deepcopy(self.project['research_selection_reviews'][-1]);review.pop('recorded_at',None)
        review['review_id']='NULL-CONTEXT'
        gap=copy.deepcopy(review['gaps'][0])
        gap.update(question_id='Q_CONTEXT',decision_dependency='Inference limits only',impact='context',priority='defer',
            priority_rationale='Context does not choose the current action',status='open',answer=None,
            why_changes_decision='No option choice is inferred from context',selected_method_id=None,answer_branches=[])
        review['gaps'].append(gap)
        if not mixed:
            review['stop_rule']['status']='uncertain'
            self.project['research_questions']=self.project['research_questions'][-1:]
            review['gaps']=review['gaps'][-1:]
            review['recommendation'].update(action='clarify',question_id='Q_CONTEXT',method_id=None,
                rationale='Clarify the frame; do not pretend context chooses an option')
            write_state(self.path,self.project)
        # Changing the question catalog invalidates the old resource review's technical baseline.
        from feasibility import baseline as feasibility_baseline
        self.project['feasibility_reviews'][-1]['baseline']=feasibility_baseline(self.project,self.path,ROOT)
        write_state(self.path,self.project)
        review['baseline']=baseline(self.project,self.path,ROOT)
        record(self.project,self.path,ROOT,review);self.project=load(self.path)
        self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT)
        write_state(self.path,self.project)
        return audit(self.project,self.path,ready=True,quality=True)

    def test_map_preserves_a_valid_null_resolution_without_a_branch_edge(self):
        result=self.contextual();before=self.path.read_bytes();log=(self.case/'ledger.jsonl').read_bytes()
        data=payload(render(self.project,result,before,self.path))
        key='research:NULL-CONTEXT:gaps:Q_CONTEXT:resolution'
        node=next(n for n in data['nodes'] if n['id']==key)
        self.assertIsNone(node['details']['branch_id']);self.assertEqual(node['status'],'not_applicable')
        self.assertIn('нет выбора альтернативы',node['details']['next_step'])
        self.assertFalse(any(e['target']==key and ':branch:' in e['source'] for e in data['edges']))
        self.assertFalse(any(n['id'].endswith(':branch:None') or n['id'].endswith(':branch:null') for n in data['nodes']))
        ids={n['id'] for n in data['nodes']}
        self.assertTrue(all(e['source'] in ids and e['target'] in ids for e in data['edges']))
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(log,(self.case/'ledger.jsonl').read_bytes())

    def test_native_report_exports_document_and_map_with_context_and_real_branch(self):
        result=self.contextual();out=self.case/'brief.md';before=self.path.read_bytes()
        process=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/project_tool.py'),'report',str(self.path),'--out',str(out)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(process.returncode,0,process.stderr)
        document=out.read_text(encoding='utf-8');self.assertIn('Q_CONTEXT',document)
        self.assertIn('Контекстный вопрос',document);self.assertIn('brief.graph.html',document)
        self.assertIn('не применяется — контекстный вопрос без выбора альтернативы',document)
        self.assertNotIn('ветка: None',document)
        data=payload(out.with_suffix('.graph.html').read_text(encoding='utf-8'))
        for row in result['research_selection']['branch_resolutions']:
            key='research:NULL-CONTEXT:gaps:'+row['question_id']+':resolution'
            node=next(n for n in data['nodes'] if n['id']==key)
            for field,value in row.items():self.assertEqual(node['details'][field],value)
        selected=next(r for r in result['research_selection']['branch_resolutions'] if r['question_id']=='Q_RESOURCE')
        self.assertTrue(any(e['source']=='research:NULL-CONTEXT:gaps:Q_RESOURCE:branch:'+selected['branch_id'] and e['target']=='research:NULL-CONTEXT:gaps:Q_RESOURCE:resolution' for e in data['edges']))
        self.assertEqual(before,self.path.read_bytes())

    def test_context_only_and_reload_preserve_meaning(self):
        result=self.contextual(mixed=False)
        before=self.path.read_bytes();first=payload(render(self.project,result,before,self.path))
        reloaded=load(self.path);again=audit(reloaded,self.path,ready=True,quality=True)
        second=payload(render(reloaded,again,self.path.read_bytes(),self.path))
        key='research:NULL-CONTEXT:gaps:Q_CONTEXT:resolution'
        self.assertEqual(next(n for n in first['nodes'] if n['id']==key),next(n for n in second['nodes'] if n['id']==key))
        self.assertEqual(before,self.path.read_bytes())

    def test_unknown_nonnull_resolution_is_rejected_not_treated_as_context(self):
        result=self.contextual()
        result['research_selection']['branch_resolutions'][0]['branch_id']='DOES_NOT_EXIST'
        with self.assertRaisesRegex(ValueError,'unknown branch'):graph(self.project,result,'test')

    def test_null_is_not_a_valid_branch_definition_or_a_matched_selection(self):
        from validate_project import validate
        result=self.contextual()
        broken=copy.deepcopy(self.project);broken['research_selection_reviews'][-1]['gaps'][0]['answer_branches'][0]['branch_id']=None
        self.assertTrue(validate(broken))
        result['research_selection']['branch_resolutions'][0]['branch_id']=None
        with self.assertRaisesRegex(ValueError,'context'):graph(self.project,result,'test')


if __name__=='__main__':unittest.main()
