#!/usr/bin/env python3
"""Exercise the portable case, source invalidation and recovery in an isolated copy."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    started = time.perf_counter()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        case = Path(tmp)/'case'
        shutil.copytree(ROOT/'examples/campus-strategy', case)
        project = case/'project.json'

        def run(script, *args, expected=0):
            before = time.perf_counter()
            command = [sys.executable, str(ROOT/'scripts'/script), *map(str,args)]
            result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
            if result.returncode != expected:
                raise RuntimeError(f'{script}: expected exit {expected}, got {result.returncode}: {result.stderr}\n{result.stdout}')
            results.append({'tool':script, 'exit_code':result.returncode, 'expected':expected,
                            'seconds':round(time.perf_counter()-before,4)})
            return result.stdout

        run('validate_project.py',project)
        resume = json.loads(run('checkpoint.py',project,'resume'))
        assert resume['changed_source_ids'] == [], resume
        run('project_tool.py','audit',project)
        run('project_tool.py','report',project,'--out',case/'outputs/report.md')
        source = case/'inputs/product-brief.md'
        original = source.read_text(encoding='utf-8')
        source.write_text(original+'\nНовые сведения: учебный офис теперь завершает заявки.\n',encoding='utf-8')
        resumed = json.loads(run('checkpoint.py',project,'resume'))
        assert {'E1','H1'} <= set(resumed['evidence_to_reassess']), resumed
        run('project_tool.py','audit',project,expected=1)
        run('project_tool.py','report',project,'--out',case/'outputs/blocked.md',expected=1)
        run('checkpoint.py',project,'save','--summary','Should refuse unreviewed changes',expected=1)
        assert not (case/'outputs/blocked.md').exists()
        # Restore the original fixture; this validates recovery, not a fictitious strategic reassessment.
        source.write_text(original,encoding='utf-8')
        restored = json.loads(run('checkpoint.py',project,'resume'))
        assert restored['changed_source_ids'] == [], restored
        run('project_tool.py','report',project,'--out',case/'outputs/recovered.md')
        source.unlink()
        run('project_tool.py','audit',project,expected=1)
    report = {'at':datetime.now(timezone.utc).isoformat(timespec='seconds'), 'checks':results,
              'elapsed_seconds':round(time.perf_counter()-started,4), 'network_calls':0,'model_calls':0,
              'scope':'Local smoke test, source invalidation, blocked export, recovery and missing-file handling. Not an LLM quality benchmark.'}
    output = ROOT/'docs/verification.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
