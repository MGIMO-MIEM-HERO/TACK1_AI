"""Optional Edge integration check: python tests/browser_map_density.py.
Requires Python websocket-client and Edge; writes local artifacts under projects/.
"""
import json,time,subprocess,tempfile,urllib.request
from pathlib import Path
import websocket
root=Path(__file__).resolve().parents[1]
out=root/'projects/map-density-2026-11-22'
out.mkdir(parents=True,exist_ok=True)
subprocess.run([__import__('sys').executable,'-B',str(root/'scripts/visualize.py'),str(root/'examples/paired-case-review/project.json'),'--out',str(out/'paired.html')],check=True,cwd=root)
p=subprocess.Popen([r'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','--headless=new','--disable-gpu','--remote-debugging-port=9371','--remote-allow-origins=http://localhost:9371','--user-data-dir='+tempfile.mkdtemp(prefix='cluster-qa-'),(out/'paired.html').as_uri()],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
 for _ in range(100):
  try:
   tabs=json.load(urllib.request.urlopen('http://127.0.0.1:9371/json')); tab=next(t for t in tabs if t['type']=='page');break
  except Exception:time.sleep(.1)
 ws=websocket.create_connection(tab['webSocketDebuggerUrl'],origin='http://localhost:9371'); seq=0
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
 check('compact default',"mapDetail==='compact'&&document.getElementById('view-compact').getAttribute('aria-pressed')==='true'")
 ev('window.original=JSON.stringify(data);window.geometry=JSON.stringify([...positions]);window.camera=[zoom,panX,panY];window.member=groupMembers(clusterGroups[0])[0]')
 check('compact hides ordinary titles',"getComputedStyle(cards.get(member).g.querySelector('.record-title')).display==='none'")
 ev("document.getElementById('view-detailed').click()");time.sleep(.2)
 check('detailed reveals titles',"mapDetail==='detailed'&&getComputedStyle(cards.get(member).g.querySelector('.record-title')).display!=='none'&&cards.get(member).g.querySelectorAll('tspan').length>0")
 check('mutually exclusive buttons',"document.getElementById('view-compact').getAttribute('aria-pressed')==='false'&&document.getElementById('view-detailed').getAttribute('aria-pressed')==='true'")
 check('camera and geometry unchanged',"geometry===JSON.stringify([...positions])&&JSON.stringify(camera)===JSON.stringify([zoom,panX,panY])")
 ev("setMapDetail('compact');focus(member)")
 check('compact selected title visible',"getComputedStyle(cards.get(member).g.querySelector('.record-title')).display!=='none'")
 ev("selected=null;highlight();cards.get(member).g.focus()")
 check('compact keyboard focus title visible',"getComputedStyle(cards.get(member).g.querySelector('.record-title')).display!=='none'")
 ev('setAllClusters(false);window.folded=[...collapsedGroups];setMapDetail("detailed")')
 check('folded records stay hidden',"JSON.stringify(folded)===JSON.stringify([...collapsedGroups])&&isClusterHidden(member)&&getComputedStyle(cards.get(member).g).display==='none'")
 ev('selectDecisionPath(data.decision_paths[0].option_id);finishNavigation();window.pathState=[currentDecisionPath.option_id,...pathNodes];setMapDetail("compact");setMapDetail("detailed")')
 check('path preserved',"pathOnly&&JSON.stringify(pathState)===JSON.stringify([currentDecisionPath.option_id,...pathNodes])")
 check('markers retained',"[...cards.values()].every(({g})=>[...g.querySelectorAll('.mark,.recommend,.choice')].every(e=>getComputedStyle(e).display!=='none'))")
 check('safe bounded unicode titles',"titleLines('😀'.repeat(200)).length===3&&titleLines('😀'.repeat(200)).at(-1).endsWith('…')&&titleLines('<script>alert(1)</script>').join('').includes('<script>')")
 check('payload unchanged',"JSON.stringify(data)===original")
 (out/'decision-network.svg').unlink(missing_ok=True)
 call('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(out)})
 ev("document.getElementById('download').click()")
 for _ in range(40):
  if (out/'decision-network.svg').exists():break
  time.sleep(.1)
 import xml.etree.ElementTree as ET
 exported=ET.parse(out/'decision-network.svg').getroot()
 assert exported.attrib.get('data-detail')=='detailed'
 assert 'Подробный вид' in ''.join(exported.itertext())
 assert not any(e.tag.split('}')[-1] in ('script','foreignObject','image') for e in exported.iter())
 checks.append('SVG preserves detailed mode safely')
 ev('showCluster(clusterGroups[0].id);finishNavigation()')
 import base64
 (out/'detailed.png').write_bytes(base64.b64decode(call('Page.captureScreenshot',{'format':'png'})['data']))
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
 ev('setMapDetail("detailed");setMapDetail("compact")')
 check('empty groups safe',"clusterGroups.length===0&&clusterSelect.disabled&&cards.size===3&&Number.isFinite(zoom)")
 (out/'browser-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(checks,ensure_ascii=False,indent=2))
finally:p.terminate()
