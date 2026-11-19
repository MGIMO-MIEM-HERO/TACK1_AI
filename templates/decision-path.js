let currentDecisionPath=null,pathOnly=false,pathNodes=new Set(),pathEdges=new Set();
const pathPanel=document.getElementById('path-panel'),pathSelect=document.getElementById('path-option'),pathContent=document.getElementById('path-content');
const pathStatusNames={not_checked:'не проверено',complete:'запись проверки заполнена',incomplete:'запись проверки неполна',source_fact:'факт о содержании источника',measured_fact:'измерение',association:'статистическая связь',qualitative_signal:'качественное свидетельство',hypothesis:'гипотеза',forecast:'прогноз',decision:'решение',provisional:'предварительно',corroborated:'подтверждено независимым основанием',withdrawn:'отозвано',contradicted:'противоречит данным',stale:'требует пересмотра',review_record_complete:'проверка записана',not_recorded:'не записана',blocked:'есть блокеры',feasible:'осуществимо по записанным условиям',infeasible:'неосуществимо в этом плане',unknown:'неизвестно'};
function pathStatus(text){return text.replace(/[a-z_]+/g,key=>pathStatusNames[key]||key)}
function pathMatches(id){
  if(!pathOnly)return true;
  if(pathNodes.has(id))return true;
  const group=groups.find(g=>g.id===id);
  return !!group&&data.nodes.some(n=>n.column===group.column&&pathNodes.has(n.id));
}
function pathEdgeMatches(edge,grouping){return !pathOnly||(!grouping&&pathEdges.has(edge))}
function clearDecisionPath(){
  currentDecisionPath=null;pathOnly=false;pathNodes.clear();pathEdges.clear();pathSelect.value='';
  document.getElementById('path-only').checked=false;document.getElementById('path-only').disabled=true;
  document.getElementById('path-fit').disabled=true;pathContent.replaceChildren();
  for(const {g} of cards.values())g.classList.remove('path-node');
  for(const {line} of lines)line.classList.remove('path-edge','path-contradiction');
}
function pathSection(title,ids,empty){
  const section=html('section','',pathContent,'path-section');html('h3',title,section);
  if(!ids.length)html('p',empty,section);
  for(const id of ids){
    const card=cards.get(id);if(!card)continue;
    const button=html('button',card.n.title,section,'path-record');
    html('small',pathStatus(card.n.status),button);button.onclick=()=>focus(id);
  }
}
function selectDecisionPath(oid){
  clearHistoryFocus();clearStatusFocus();clearScenarioMode();clearDecisionPath();
  const path=(data.decision_paths||[]).find(p=>p.option_id===oid);if(!path){highlight();return}
  currentDecisionPath=path;pathNodes=new Set(path.nodes);
  pathEdges=new Set(path.edge_indexes.map(i=>data.edges[i]));pathOnly=true;pathSelect.value=oid;
  document.getElementById('path-only').disabled=false;document.getElementById('path-only').checked=true;
  document.getElementById('path-fit').disabled=false;
  // Selecting a path shows its entire recorded scope; previous display filters can be reapplied.
  comparisonOnly=false;document.getElementById('changes-only').checked=false;
  query='';document.getElementById('search').value='';selected=null;
  active.clear();[0,...groups.map(g=>g.column)].forEach(c=>active.add(c));
  document.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed','true'));
  html('p',path.note,pathContent,'path-note');
  html('p',(path.is_recommended?'Рекомендация агента. ':'')+(path.is_human_choice?'Сохранённый выбор человека. ':'')+
    'Сам просмотр пути не меняет решение и не разрешает действие.',pathContent,'path-note');
  pathSection('Источники',path.sources,'Источники для записанных оснований не указаны.');
  pathSection('Основания',path.evidence,'Основания варианта не записаны.');
  pathSection('Допущения',path.assumptions,'Отдельные связанные допущения в последнем сценарном разборе не записаны.');
  pathSection('Вариант',[path.node_id],'');
  pathSection('Связанные проверки и следующий шаг',path.checks,'Связанные проверки не записаны.');
  const support=html('details','',pathContent,'path-support');html('summary','Фрагменты, отношения и ограничения',support);
  const relationNames={supports:'Поддерживает',context:'Контекст',contradicts:'Противоречит'};
  if(!path.support.length)html('p','Отношения между источниками и выводами не записаны. Указание источника само по себе не подтверждает вывод.',support);
  for(const link of path.support){
    const section=html('div','',support,'path-support-row '+(link.relation==='contradicts'?'contradiction':''));
    html('strong',(relationNames[link.relation]||link.relation)+' · '+link.source_id+' → '+link.evidence_id,section);
    html('p',link.passage,section);html('p','Где проверить: '+link.locator,section);html('p','Записанное объяснение: '+link.reason,section);
  }
  for(const row of path.limitations)html('p',row.evidence_id+' · '+pathStatus(row.claim_type)+' · '+pathStatus(row.status)+' · '+row.text,support);
  const statuses=html('div','',pathContent,'path-statuses');
  html('strong','Статусы последних сохранённых проверок',statuses);
  for(const [key,label] of [['decision_stress_test','Сценарии'],['feasibility','Осуществимость'],['research_selection','Исследование']])
    html('p',label+': '+pathStatus(path.review_statuses[key]),statuses);
  if(path.missing_evidence_ids.length)html('p','Не найдены записи оснований: '+path.missing_evidence_ids.join(', '),statuses);
  for(const [id,{g}] of cards)g.classList.toggle('path-node',pathNodes.has(id));
  for(const {e,line,grouping} of lines){
    line.classList.toggle('path-edge',!grouping&&pathEdges.has(e));
    line.classList.toggle('path-contradiction',!grouping&&pathEdges.has(e)&&path.contradictions.some(p=>p[0]===e.source&&p[1]===e.target));
  }
  focus(path.node_id);selected=null;highlight();
}
const placeholder=html('option','Выберите вариант…',pathSelect);placeholder.value='';
for(const path of data.decision_paths||[]){
  const option=html('option',path.option_id+' · '+path.title+(path.is_recommended?' · рекомендация':'')+(path.is_human_choice?' · выбор человека':''),pathSelect);option.value=path.option_id;
}
if(!(data.decision_paths||[]).length){pathSelect.disabled=true;html('p','Варианты ещё не записаны. Путь решения появится после их сохранения.',pathContent)}
document.getElementById('path-toggle').onclick=()=>{
  pathPanel.hidden=!pathPanel.hidden;document.getElementById('path-toggle').setAttribute('aria-expanded',String(!pathPanel.hidden));
};
pathSelect.onchange=()=>selectDecisionPath(pathSelect.value);
document.getElementById('path-only').onchange=event=>{pathOnly=event.target.checked;selected=null;highlight()};
document.getElementById('path-clear').onclick=()=>{clearDecisionPath();selected=null;highlight()};
document.getElementById('path-fit').onclick=()=>{
  const ps=[...pathNodes].map(id=>positions.get(id)).filter(Boolean);if(!ps.length)return;
  const box=svg.getBoundingClientRect(),minX=Math.min(...ps.map(p=>p.x-p.r-35)),maxX=Math.max(...ps.map(p=>p.x+p.r+35)),minY=Math.min(...ps.map(p=>p.y-p.r-35)),maxY=Math.max(...ps.map(p=>p.y+p.r+40));
  zoom=Math.min(4,box.width/(maxX-minX+80),box.height/(maxY-minY+80));panX=box.width/2-(minX+maxX)/2*zoom;panY=box.height/2-(minY+maxY)/2*zoom;update();
};
