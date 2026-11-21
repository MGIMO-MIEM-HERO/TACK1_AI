"""Optional Edge integration check: python tests/browser_cluster_navigation.py.
Requires Python websocket-client and Edge; writes local artifacts under projects/.
"""
import json,time,subprocess,tempfile,urllib.request
from pathlib import Path
import websocket
root=Path(__file__).resolve().parents[1]
out=root/'projects/cluster-navigation-2026-11-22'
out.mkdir(parents=True,exist_ok=True)
subprocess.run([__import__('sys').executable,'-B',str(root/'scripts/visualize.py'),str(root/'examples/paired-case-review/project.json'),'--out',str(out/'paired.html')],check=True,cwd=root)
p=subprocess.Popen([r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','--headless=new','--disable-gpu','--remote-debugging-port=9370','--remote-allow-origins=http://localhost:9370','--user-data-dir='+tempfile.mkdtemp(prefix='cluster-qa-'),(out/'paired.html').as_uri()],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(100):
  try:
   tabs=json.load(urllib.request.urlopen('http://127.0.0.1:9370/json')); tab=next(t for t in tabs if t['type']=='page');break
  except Exception:time.sleep(.1)
 ws=websocket.create_connection(tab['webSocketDebuggerUrl'],origin='http://localhost:9370'); seq=0
 def call(method,params={}):
  global seq
  seq+=1;ws.send(json.dumps({'id':seq,'method':method,'params':params}))
  while True:
   r=json.loads(ws.recv())
   if r.get('id')==seq:return r.get('result',{})
 def ev(code):
  r=call('Runtime.evaluate',{'expression':code,'returnByValue':True})
  if 'exceptionDetails' in r:raise AssertionError(r['exceptionDetails'])
  return r['result'].get('value')
 time.sleep(1)
 checks=[]
 def check(name,code):
  assert ev(code),name;checks.append(name)
 check('initialized',"cards.size>3 && clusterGroups.length>0 && document.getElementById('detail-title').textContent.length>0")
 ev('window.original=JSON.stringify(data);window.edgeCount=lines.length;setAllClusters(false)')
 check('collapse real records and edges',"clusterGroups.every(g=>groupMembers(g).every(id=>isClusterHidden(id)&&cards.get(id).g.classList.contains('cluster-hidden')&&cards.get(id).g.getAttribute('tabindex')==='-1')) && lines.every(({e,line})=>!(isClusterHidden(e.source)||isClusterHidden(e.target))||line.classList.contains('cluster-hidden'))")
 check('hubs and singleton controls retained',"!isClusterHidden('task')&&!isClusterHidden('review')&&!isClusterHidden('next')&&clusterGroups.every(g=>cards.get(g.id).g.getAttribute('aria-expanded')==='false')")
 ev('window.member=groupMembers(clusterGroups[0])[0];focus(member,true)');time.sleep(.5)
 check('record reveals group and finishes camera',"!isClusterHidden(member)&&cameraAnimation===null&&Number.isFinite(zoom)")
 ev('setAllClusters(false);selectDecisionPath(data.decision_paths[0].option_id)');time.sleep(.5)
 check('path reveals participants',"[...pathNodes].every(id=>!isClusterHidden(id))&&cameraAnimation===null")
 ev('setAllClusters(false);chooseScenarioVersion(data.scenario_views[0].review_id);selectScenario(data.scenario_views[0].scenarios[0].scenario_id)');time.sleep(.5)
 check('scenario reveals participants',"[...scenarioNodes].every(id=>!isClusterHidden(id))&&scenarioNodes.size>0&&cameraAnimation===null")
 ev('setAllClusters(false);chooseStatusCategory(Object.keys(statusData.categories).find(k=>statusData.categories[k].items.some(i=>i.nodes.length)))')
 check('status reveals participants',"[...statusNodes].every(id=>!isClusterHidden(id))&&statusNodes.size>0")
 ev('setAllClusters(false);selectHistoryEvent(historyData.events.find(e=>e.nodes.length).id)')
 check('history reveals participants',"[...historyNodes].every(id=>!isClusterHidden(id))&&historyNodes.size>0")
 ev('setAllClusters(false);document.getElementById("search").value=cards.get(member).n.title;document.getElementById("search").dispatchEvent(new Event("input"))')
 check('search reveals matching records',"!isClusterHidden(member)")
 ev('showCluster(clusterGroups[0].id)')
 check('smooth camera starts',"cameraAnimation!==null")
 ev('scale(1.1,100,100);window.cancelled=[zoom,panX,panY]');time.sleep(.5)
 check('manual zoom cancels animation',"cameraAnimation===null&&JSON.stringify(cancelled)===JSON.stringify([zoom,panX,panY])")
 call('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'reduce'}]});time.sleep(.1)
 ev('navigateNode(member)')
 check('reduced motion immediate',"reducedMotion.matches&&motionToggle.disabled&&!motionToggle.checked&&cameraAnimation===null")
 call('Emulation.setEmulatedMedia',{'features':[{'name':'prefers-reduced-motion','value':'no-preference'}]});time.sleep(.1)
 ev('navigateNode(member);window.target={...cameraAnimation.target};finishNavigation()')
 check('export finishes target',"cameraAnimation===null&&zoom===target.zoom&&panX===target.panX&&panY===target.panY")
 ev('setAllClusters(false);fit(false)')
 check('fit preserves collapse',"collapsedGroups.size===clusterGroups.length")
 check('data unchanged',"JSON.stringify(data)===original&&lines.length===edgeCount")
 call('Emulation.setDeviceMetricsOverride',{'width':800,'height':900,'deviceScaleFactor':1,'mobile':False});time.sleep(.2)
 check('mobile no overflow',"document.documentElement.scrollWidth<=800")
 import sys
 sys.path.insert(0,str(root/'scripts'))
 from visualize import render
 project=json.loads((root/'examples/review-contract-case/project.json').read_text(encoding='utf-8'))
 for key in ('sources','evidence','options'):project[key]=[]
 (out/'minimal.html').write_text(render(project,{'ready':False,'health':{},'errors':[]},b'minimal'),encoding='utf-8')
 call('Page.navigate',{'url':(out/'minimal.html').as_uri()});time.sleep(.5)
 ev('setAllClusters(false);fit(false);setAllClusters(true)')
 check('empty groups safe',"clusterGroups.length===0&&clusterSelect.disabled&&cards.size===3&&Number.isFinite(zoom)")
 (out/'browser-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(checks,ensure_ascii=False,indent=2))
finally:p.terminate()
