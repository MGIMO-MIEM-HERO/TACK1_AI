let currentScenarioView=null,currentScenario=null,scenarioOnly=false,scenarioNodes=new Set(),scenarioEdges=new Set();
const scenarioPanel=document.getElementById('scenario-panel'),scenarioVersion=document.getElementById('scenario-version'),scenarioSelect=document.getElementById('scenario-select'),scenarioContent=document.getElementById('scenario-content'),scenarioNotice=document.getElementById('scenario-notice');
const scenarioLabels={review_record_complete:'разбор записан',historical:'историческая версия',stale:'требует пересмотра',blocked:'есть блокеры',not_checked:'актуальность не проверена',hypothetical:'гипотетическая предпосылка',observed:'предпосылка записана как наблюдавшаяся',feasible:'условно осуществимо',infeasible:'неосуществимо в этом сценарии',uncertain:'осуществимость неизвестна',preferred:'условно предпочтителен',not_preferred:'не предпочтителен в этом сценарии',undetermined:'предпочтение не определено',keep:'условно сохранить исходный вариант',switch:'условно сменить исходный вариант',conditional_option:'условный вариант; не рекомендация проекта',insufficient_evidence:'данных недостаточно; вариант не выбран'};
function scenarioMatches(id){
  if(!scenarioOnly)return true;if(scenarioNodes.has(id))return true;
  const group=groups.find(g=>g.id===id);return !!group&&data.nodes.some(n=>n.column===group.column&&scenarioNodes.has(n.id));
}
function scenarioEdgeMatches(edge,grouping){return !scenarioOnly||(!grouping&&scenarioEdges.has(edge))}
function clearScenarioMode(){
  currentScenarioView=null;currentScenario=null;scenarioOnly=false;scenarioNodes.clear();scenarioEdges.clear();scenarioSelect.value='';
  document.getElementById('scenario-only').checked=false;document.getElementById('scenario-only').disabled=true;
  document.getElementById('scenario-fit').disabled=true;scenarioNotice.hidden=true;scenarioContent.replaceChildren();
  for(const {g} of cards.values())g.classList.remove('scenario-node','scenario-feasible','scenario-infeasible','scenario-uncertain','scenario-preferred');
  for(const {line} of lines)line.classList.remove('scenario-edge');
}
function chooseScenarioVersion(id){
  clearScenarioMode();scenarioSelect.replaceChildren();
  const view=(data.scenario_views||[]).find(v=>v.review_id===id);
  const placeholder=html('option','Выберите сценарий…',scenarioSelect);placeholder.value='';
  for(const scenario of view?.scenarios||[]){const option=html('option',scenario.scenario_id+' · '+scenario.title,scenarioSelect);option.value=scenario.scenario_id}
  scenarioSelect.disabled=!view;
}
function scenarioText(title,text,parent=scenarioContent){const section=html('section','',parent,'scenario-section');html('h3',title,section);html('p',text,section);return section}
function selectScenario(id){
  const reviewId=scenarioVersion.value;clearScenarioMode();
  const view=(data.scenario_views||[]).find(v=>v.review_id===reviewId),scenario=view?.scenarios.find(s=>s.scenario_id===id);
  if(!scenario){highlight();return}
  clearDecisionPath();comparisonOnly=false;document.getElementById('changes-only').checked=false;
  currentScenarioView=view;currentScenario=scenario;scenarioSelect.value=id;
  scenarioNodes=new Set(scenario.nodes);scenarioEdges=new Set(scenario.edge_indexes.map(i=>data.edges[i]));scenarioOnly=true;
  document.getElementById('scenario-only').disabled=false;document.getElementById('scenario-only').checked=true;document.getElementById('scenario-fit').disabled=false;
  query='';document.getElementById('search').value='';selected=null;active.clear();[0,...groups.map(g=>g.column)].forEach(c=>active.add(c));document.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed','true'));
  document.getElementById('scenario-notice-text').textContent='УСЛОВНЫЙ СЦЕНАРИЙ — НЕ ПРИМЕНЁН К РЕШЕНИЮ · '+view.review_id+' / '+id+' · '+(scenarioLabels[view.status]||view.status);
  scenarioNotice.hidden=false;
  html('p',view.note,scenarioContent,'scenario-note');
  html('p','Текущая рекомендация проекта: '+(view.actual_recommendation||'не записана')+'. Выбор человека: '+(view.actual_human_choice||'не записан')+'.',scenarioContent,'scenario-note');
  if(!view.graph_comparable)html('p','Оценки ниже сохранены в этой версии. Они не перенесены на текущие узлы вариантов; актуальность или основания разбора требуют проверки.',scenarioContent,'scenario-warning');
  scenarioText('Предпосылка · '+(scenarioLabels[scenario.premise_status]||scenario.premise_status),scenario.premise);
  scenarioText('С чем сравнивается',view.comparison.note);
  const decision=scenario.conditional_recommendation;
  scenarioText('Сохранённый условный исход',(scenarioLabels[decision.outcome]||decision.outcome)+(decision.option_id?' · '+decision.option_id:'')+'\n'+decision.rationale);
  const table=html('table','',scenarioContent,'scenario-table'),caption=html('caption','Все варианты в сохранённом сценарии',table),head=html('thead','',table),header=html('tr','',head);
  for(const label of ['Вариант','Осуществимость','Предпочтение и объяснение']){const th=html('th',label,header);th.scope='col'}
  const body=html('tbody','',table);
  for(const row of scenario.option_impacts){
    const tr=html('tr','',body,'scenario-row '+row.feasibility),name=html('td','',tr);
    if(row.node_id){const button=html('button',row.option_id+' · '+row.title,name,'button');button.onclick=()=>focus(row.node_id)}else html('span',row.option_id,name);
    html('td',scenarioLabels[row.feasibility]||row.feasibility,tr);
    const reason=html('td','',tr);html('strong',scenarioLabels[row.preference]||row.preference,reason);html('p',row.reason,reason);
    html('small','Основания: '+(row.evidence_ids.join(', ')||'не записаны'),reason);
    if(view.graph_comparable&&row.node_id){const g=cards.get(row.node_id)?.g;if(g){g.classList.add('scenario-'+row.feasibility);g.classList.toggle('scenario-preferred',row.preference==='preferred')}}
  }
  const details=html('details','',scenarioContent,'scenario-details');html('summary','Изменяемые условия, допущения и основания',details);
  for(const change of scenario.constraint_changes)scenarioText('Условное изменение ограничения',change.before+' → '+change.after,details);
  for(const row of scenario.assumptions)scenarioText(row.assumption_id+' · Допущение',row.statement+'\nПроверить: '+row.verification_needed,details);
  scenarioText('Изменяемые источники',scenario.changed_source_ids.join(', ')||'не указаны',details);
  scenarioText('Изменяемые основания',scenario.changed_evidence_ids.join(', ')||'не указаны',details);
  if(scenario.evaluation?.impact)scenarioText('Зависимости для пересмотра','Основания: '+scenario.evaluation.impact.evidence_ids.join(', ')+'\nВарианты: '+scenario.evaluation.impact.option_ids.join(', '),details);
  scenarioText('Какие данные нужны',scenario.new_data_needed);
  scenarioText('Когда пересмотреть',scenario.review_trigger);
  scenarioText('Ограничения разбора',view.limitations);
  if(view.blockers.length)scenarioText('Блокеры текущего разбора',view.blockers.join('\n'));
  for(const [key,{g}] of cards)g.classList.toggle('scenario-node',scenarioNodes.has(key));
  for(const {e,line,grouping} of lines)line.classList.toggle('scenario-edge',!grouping&&scenarioEdges.has(e));
  if(cards.has(scenario.node_id))focus(scenario.node_id);selected=null;highlight();
}
for(const view of data.scenario_views||[]){const option=html('option',view.review_id+' · '+(scenarioLabels[view.status]||view.status),scenarioVersion);option.value=view.review_id}
if((data.scenario_views||[]).length){scenarioVersion.value=data.scenario_views.at(-1).review_id;chooseScenarioVersion(scenarioVersion.value)}
else{scenarioVersion.disabled=true;scenarioSelect.disabled=true;html('p','Сценарии ещё не записаны. Сохраните содержательный сценарный разбор средствами агента; просмотр не создаёт его автоматически.',scenarioContent)}
document.getElementById('scenario-toggle').onclick=()=>{scenarioPanel.hidden=!scenarioPanel.hidden;document.getElementById('scenario-toggle').setAttribute('aria-expanded',String(!scenarioPanel.hidden))};
scenarioVersion.onchange=()=>{chooseScenarioVersion(scenarioVersion.value);selected=null;highlight()};
scenarioSelect.onchange=()=>selectScenario(scenarioSelect.value);
document.getElementById('scenario-only').onchange=event=>{scenarioOnly=event.target.checked;selected=null;highlight()};
document.getElementById('scenario-clear').onclick=document.getElementById('scenario-exit').onclick=()=>{clearScenarioMode();focus(cards.has('summary:current')?'summary:current':'task');selected=null;highlight()};
document.getElementById('scenario-fit').onclick=()=>{
  const ps=[...scenarioNodes].map(id=>positions.get(id)).filter(Boolean);if(!ps.length)return;
  const box=svg.getBoundingClientRect(),minX=Math.min(...ps.map(p=>p.x-p.r-35)),maxX=Math.max(...ps.map(p=>p.x+p.r+35)),minY=Math.min(...ps.map(p=>p.y-p.r-35)),maxY=Math.max(...ps.map(p=>p.y+p.r+40));
  zoom=Math.min(4,box.width/(maxX-minX+80),box.height/(maxY-minY+80));panX=box.width/2-(minX+maxX)/2*zoom;panY=box.height/2-(minY+maxY)/2*zoom;update();
};
