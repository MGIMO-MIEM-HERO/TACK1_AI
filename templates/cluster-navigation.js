// Display state only. Collapsing never rewrites records or reroutes dependencies.
const collapsedGroups=new Set(),clusterGroups=groups.filter(group=>group.id.startsWith('group:')&&cards.has(group.id));
const clusterSelect=document.getElementById('cluster-select'),motionToggle=document.getElementById('navigation-motion');
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
let smoothNavigation=true,cameraAnimation=null;
function groupMembers(group){return data.nodes.filter(n=>n.column===group.column).map(n=>n.id)}
function groupForNode(id){const n=cards.get(id)?.n;return n&&clusterGroups.find(g=>g.column===n.column&&g.id!==id)}
function isClusterHidden(id){const group=groupForNode(id);return !!group&&collapsedGroups.has(group.id)}
function cancelNavigation(finish=false){
  if(!cameraAnimation)return;
  const animation=cameraAnimation;cameraAnimation=null;cancelAnimationFrame(animation.frame);
  if(finish){zoom=animation.target.zoom;panX=animation.target.panX;panY=animation.target.panY;update()}
}
function finishNavigation(){cancelNavigation(true)}
function moveCamera(target,animate=true){
  cancelNavigation();
  if(![target.zoom,target.panX,target.panY].every(Number.isFinite)||target.zoom<=0)return;
  if(!animate||!smoothNavigation||reducedMotion.matches){zoom=target.zoom;panX=target.panX;panY=target.panY;update();return}
  const start={zoom,panX,panY},animation={target,start,time:null,frame:0};cameraAnimation=animation;
  function frame(time){
    if(cameraAnimation!==animation)return;
    if(animation.time===null)animation.time=time;
    const progress=Math.min(1,(time-animation.time)/320),ease=1-Math.pow(1-progress,3);
    zoom=start.zoom+(target.zoom-start.zoom)*ease;panX=start.panX+(target.panX-start.panX)*ease;panY=start.panY+(target.panY-start.panY)*ease;update();
    if(progress<1)animation.frame=requestAnimationFrame(frame);else cameraAnimation=null;
  }
  animation.frame=requestAnimationFrame(frame);
}
function syncClusterControls(){
  for(const group of clusterGroups){
    const collapsed=collapsedGroups.has(group.id),card=cards.get(group.id);
    card.g.classList.toggle('cluster-collapsed',collapsed);card.g.setAttribute('aria-expanded',String(!collapsed));
    card.g.querySelector('.label').textContent=group.name+(collapsed?' · свёрнуто':'');
    if(group.halo)group.halo.classList.toggle('cluster-hidden',collapsed);
  }
  const group=clusterGroups.find(g=>g.id===clusterSelect.value),button=document.getElementById('cluster-fold');
  button.disabled=!group;document.getElementById('cluster-show').disabled=!group;
  button.textContent=group&&collapsedGroups.has(group.id)?'Раскрыть группу':'Свернуть группу';
  const note=document.getElementById('cluster-note');note.hidden=!collapsedGroups.size;
  note.textContent=collapsedGroups.size?'Свёрнуты: '+clusterGroups.filter(g=>collapsedGroups.has(g.id)).map(g=>g.name+' ('+groupMembers(g).length+' записей)').join(', ')+'. Записи и их связи скрыты только в представлении; центры групп не заменяют фактические зависимости.':'';
  renderClusterDetailControls(detailNodeId);
}
function revealNodes(ids){
  let changed=false;
  for(const id of ids){const group=groupForNode(id);if(group&&collapsedGroups.delete(group.id))changed=true}
  if(changed){syncClusterControls();highlight()}
}
function setClusterExpanded(id,expanded){
  cancelNavigation();
  const group=clusterGroups.find(g=>g.id===id);if(!group)return;
  if(expanded)collapsedGroups.delete(id);else collapsedGroups.add(id);
  syncClusterControls();
  if(isClusterHidden(detailNodeId)){focus(group.id);selected=null}
  highlight();
}
function setAllClusters(expanded){
  cancelNavigation();
  if(expanded)collapsedGroups.clear();else for(const group of clusterGroups)collapsedGroups.add(group.id);
  syncClusterControls();
  if(isClusterHidden(detailNodeId)){focus(groupForNode(detailNodeId).id);selected=null}
  highlight();
}
function fitNodeSet(ids,animate=true){
  const keys=[...ids];revealNodes(keys);
  const ps=keys.map(id=>positions.get(id)).filter(Boolean);if(!ps.length)return;
  const box=svg.getBoundingClientRect(),minX=Math.min(...ps.map(p=>p.x-p.r-35)),maxX=Math.max(...ps.map(p=>p.x+p.r+35)),minY=Math.min(...ps.map(p=>p.y-p.r-35)),maxY=Math.max(...ps.map(p=>p.y+p.r+40));
  const nextZoom=Math.min(4,box.width/(maxX-minX+80),box.height/(maxY-minY+80));
  moveCamera({zoom:nextZoom,panX:box.width/2-(minX+maxX)/2*nextZoom,panY:box.height/2-(minY+maxY)/2*nextZoom},animate);
}
function fitVisible(animate=true){fitNodeSet([...cards.keys()].filter(id=>!isClusterHidden(id)),animate)}
function showCluster(id){
  const group=clusterGroups.find(g=>g.id===id);if(!group)return;
  setClusterExpanded(id,true);clusterSelect.value=id;syncClusterControls();focus(id);
  fitNodeSet([id,...groupMembers(group)]);
}
function navigateNode(id){
  if(clusterGroups.some(g=>g.id===id)){showCluster(id);return}
  revealNodes([id]);const p=positions.get(id);if(!p)return;
  const box=svg.getBoundingClientRect(),nextZoom=Math.min(4,Math.max(zoom,.9));
  moveCamera({zoom:nextZoom,panX:box.width/2-p.x*nextZoom,panY:box.height/2-p.y*nextZoom});
}
function renderClusterDetailControls(id){
  const container=document.getElementById('cluster-detail-actions');container.replaceChildren();
  const group=clusterGroups.find(g=>g.id===id);if(!group)return;
  const toggle=html('button',collapsedGroups.has(id)?'Раскрыть группу':'Свернуть группу',container,'button');toggle.onclick=()=>setClusterExpanded(id,collapsedGroups.has(id));
  const show=html('button','Показать группу',container,'button');show.onclick=()=>showCluster(id);
}
for(const group of clusterGroups){const option=html('option',group.name+' · '+groupMembers(group).length+' записей',clusterSelect);option.value=group.id;cards.get(group.id).g.setAttribute('aria-expanded','true')}
if(!clusterGroups.length){clusterSelect.disabled=true;document.getElementById('cluster-fold').disabled=true;document.getElementById('cluster-show').disabled=true;document.getElementById('cluster-empty').textContent='Группы записей ещё не созданы.'}
clusterSelect.onchange=syncClusterControls;
document.getElementById('cluster-fold').onclick=()=>setClusterExpanded(clusterSelect.value,collapsedGroups.has(clusterSelect.value));
document.getElementById('cluster-show').onclick=()=>showCluster(clusterSelect.value);
document.getElementById('clusters-expand').onclick=()=>setAllClusters(true);
document.getElementById('clusters-collapse').onclick=()=>setAllClusters(false);
document.getElementById('cluster-toggle').onclick=()=>{const panel=document.getElementById('cluster-panel');panel.hidden=!panel.hidden;document.getElementById('cluster-toggle').setAttribute('aria-expanded',String(!panel.hidden))};
function syncMotion(){
  motionToggle.disabled=reducedMotion.matches;motionToggle.checked=smoothNavigation&&!reducedMotion.matches;
  document.getElementById('navigation-motion-note').textContent=reducedMotion.matches?'Плавное движение отключено системной настройкой уменьшения анимации.':'Настройка движения относится только к этой странице.';
  if(reducedMotion.matches)finishNavigation();
}
motionToggle.onchange=()=>{smoothNavigation=motionToggle.checked;if(!smoothNavigation)finishNavigation()};
reducedMotion.addEventListener('change',syncMotion);syncMotion();
