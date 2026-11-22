#!/usr/bin/env python3
"""Capture real built-in UI screens for README (Edge + websocket-client).

Readers need only the committed PNGs. No DOM text or styles are rewritten.
Source: an explicitly supplied saved graph and its matching project JSON.
No PDF, project JSON or complete HTML is copied into publication assets.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

import websocket

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/screenshots/agent'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full-only', action='store_true', help='capture the entire expanded graph only')
    parser.add_argument('--graph', type=Path, required=True, help='saved work-graph.html from the run')
    parser.add_argument('--project', type=Path, required=True, help='matching project.json (read-only)')
    parser.add_argument('--evidence-id', default='F_RIGHTS', help='recorded support to show')
    parser.add_argument('--agent-commit', required=True, help='verified agent version used by the saved run')
    args = parser.parse_args()
    CASE, DEMO = args.project.resolve(), args.graph.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(CASE.read_bytes()).hexdigest()
    graph_before = hashlib.sha256(DEMO.read_bytes()).hexdigest()
    saved = json.loads(DEMO.read_text(encoding='utf-8').split('<script id="data" type="application/json">')[1].split('</script>')[0])
    if saved['state_sha256'] != before:
        parser.error('Saved graph does not match project.json; refusing mixed snapshots')
    provenance = {'case_id': CASE.parent.name, 'graph_sha256': graph_before,
        'case_sha256': before, 'recommended_option': next((p['option_id'] for p in saved['decision_paths'] if p['is_recommended']), None),
        'evidence_id': args.evidence_id, 'source': 'Прогон 3; Пример брифа.pdf',
        'agent_commit': args.agent_commit}
    profile = Path(tempfile.mkdtemp(prefix='readme-agent-screens-'))
    url = DEMO.as_uri()
    process = subprocess.Popen([r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '--headless=new', '--disable-gpu', '--remote-debugging-port=0',
        '--remote-allow-origins=http://localhost', '--user-data-dir='+str(profile), url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    serial = 0
    results = []
    try:
        deadline = time.monotonic()+20
        while True:
            try:
                port = int((profile/'DevToolsActivePort').read_text().splitlines()[0])
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=1))
                tab = next(t for t in tabs if t['type']=='page' and t['url']==url)
                break
            except (OSError, ValueError, IndexError, StopIteration):
                if time.monotonic()>deadline:
                    raise RuntimeError('Edge did not open the demo')
                time.sleep(.1)
        ws = websocket.create_connection(tab['webSocketDebuggerUrl'], origin='http://localhost', timeout=10)

        def call(method, params=None):
            nonlocal serial
            serial += 1
            ws.send(json.dumps({'id': serial, 'method': method, 'params': params or {}}))
            while True:
                response = json.loads(ws.recv())
                if response.get('id') == serial:
                    assert 'error' not in response, response
                    return response.get('result', {})

        def js(code):
            result = call('Runtime.evaluate', {'expression': code, 'returnByValue': True})
            assert 'exceptionDetails' not in result, result
            return result['result'].get('value')

        def ready():
            deadline = time.monotonic()+10
            while not js("document.readyState==='complete'&&typeof cards!=='undefined'"):
                if time.monotonic()>deadline:
                    raise RuntimeError('Visualization not initialized')
                time.sleep(.1)
            js('window.originalData=JSON.stringify(data)')

        def shot(name, selector=None, height=None):
            if selector:
                # Move genuine scroll containers using native scroll APIs.
                js(f'document.querySelector({json.dumps(selector)}).scrollIntoView({{block:"start"}})')
                time.sleep(.1)
                bounds = js(f'(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height}}}})()')
                if height:
                    bounds['height'] = min(height, bounds['height'])
                clip = {**bounds, 'scale': 1}
            else:
                clip = {'x': 0, 'y': 0, 'width': width, 'height': 900, 'scale': 1}
            assert js('JSON.stringify(data)===originalData'), 'View changed graph data'
            assert js('document.documentElement.scrollWidth<=innerWidth'), 'Horizontal overflow'
            png = call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False, 'clip': clip})
            (OUT/name).write_bytes(base64.b64decode(png['data']))
            results.append({'file': name, 'viewport': width, 'clip': clip})

        call('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
        if args.full_only:
            width = 1800
            call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 1400,
                'deviceScaleFactor': 2, 'mobile': False})
            call('Page.navigate', {'url': url})
            ready()
            time.sleep(.2)
            js("setAllClusters(true);selected=null;highlight();fit(false)")
            assert js("collapsedGroups.size===0&&data.nodes.every(n=>cards.has(n.id)&&!isClusterHidden(n.id))")
            assert js("(()=>{const b=svg.getBoundingClientRect();return [...positions.values()].every(p=>{const x=p.x*zoom+panX,y=p.y*zoom+panY;return x-p.r*zoom>=0&&x+p.r*zoom<=b.width&&y-p.r*zoom>=0&&y+p.r*zoom<=b.height})})()")
            shot('00-full-graph.png', '#canvas')
            assert hashlib.sha256(CASE.read_bytes()).hexdigest() == before
            assert hashlib.sha256(DEMO.read_bytes()).hexdigest() == graph_before
            (OUT/'full-capture.json').write_text(json.dumps({**provenance,
                'case_sha256': before, 'all_groups_expanded': True,
                'nodes': js('data.nodes.length'), 'edges': js('data.edges.length'),
                'no_nodes_clipped': True, 'screens': results}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            print('Full graph captured: all groups expanded, no nodes clipped, case unchanged.')
            return
        for width in (1280, 390):
            mobile = width == 390
            suffix = '-mobile' if mobile else ''
            call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 2600 if mobile else 1600,
                'deviceScaleFactor': 1, 'mobile': False})
            call('Page.navigate', {'url': url})
            ready()
            call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
            time.sleep(.2)
            js("setAllClusters(false);showCluster('group:sources');setMapDetail('compact');finishNavigation();selected=null;highlight();window.scrollTo(0,0)")
            shot('01-overview'+suffix+'.png', '#canvas')
            call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 2600 if mobile else 1600, 'deviceScaleFactor': 1, 'mobile': False})
            time.sleep(.2)
            js("setAllClusters(true);document.getElementById('path-toggle').click();selectDecisionPath((data.decision_paths.find(p=>p.is_recommended)||data.decision_paths[0]).option_id);document.querySelector('.path-support').open=true")
            js("window.supportRow=[...document.querySelectorAll('.path-support-row')].find(e=>e.querySelector('strong').textContent.endsWith(' → '+" + json.dumps(args.evidence_id) + "));if(!supportRow)throw Error('Missing requested support');supportRow.id='readme-evidence-row'")
            # ID is only a locator; no record or displayed text is changed.
            shot('02-evidence'+suffix+'.png', '#readme-evidence-row')
            js("document.getElementById('path-toggle').click();clearDecisionPath();document.getElementById('status-toggle').click();chooseStatusCategory('questions');statusPanel.scrollTop=0")
            shot('03-status'+suffix+'.png', '#status-panel')
            js("document.getElementById('status-toggle').click();clearStatusFocus()")
            js("document.getElementById('scenario-toggle').click();chooseScenarioVersion(data.scenario_views.at(-1).review_id);selectScenario(data.scenario_views.at(-1).scenarios[0].scenario_id);finishNavigation()")
            table_height = js("document.querySelector('.scenario-table').getBoundingClientRect().height")
            # Increase only the browser viewport so the genuine scroll panel fits all rows.
            call('Emulation.setDeviceMetricsOverride', {'width': width,
                'height': max(2600 if mobile else 1600, int((table_height+100)/.48)+1),
                'deviceScaleFactor': 1, 'mobile': False})
            time.sleep(.2)
            shot('04-scenarios'+suffix+'.png', '.scenario-table')
            call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 2600 if mobile else 1600, 'deviceScaleFactor': 1, 'mobile': False})
            time.sleep(.2)
            js("document.getElementById('scenario-toggle').click();clearScenarioMode();document.getElementById('history-toggle').click();selectHistoryEvent(historyData.events.filter(e=>e.kind==='checkpoints').at(-1).id);finishNavigation();historyPanel.scrollTop=0")
            shot('05-history'+suffix+'.png', '#history-panel')
        assert hashlib.sha256(CASE.read_bytes()).hexdigest() == before
        assert hashlib.sha256(DEMO.read_bytes()).hexdigest() == graph_before
        (OUT/'capture.json').write_text(json.dumps({**provenance,
            'case_sha256': before, 'case_text_sha256': hashlib.sha256(CASE.read_text(encoding='utf-8').encode('utf-8')).hexdigest(), 'screens': results, 'case_unchanged': True,
            'note': 'Actual UI excerpts, fictional saved snapshot; no model reasoning trace.'}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Captured', len(results), 'screens; graph and case unchanged.')
    finally:
        if ws is not None:
            try:
                call('Browser.close')
            except Exception:
                pass
            ws.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()


if __name__ == '__main__':
    main()
