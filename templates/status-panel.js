let statusOnly=false,statusNodes=new Set(),statusCategory=null;
const statusPanel=document.getElementById('status-panel'),statusCards=document.getElementById('status-cards'),statusContent=document.getElementById('status-content'),statusData=data.status_panel;
function statusMatches(id){
  if(!statusOnly)return true;if(statusNodes.has(id))return true;
  const group=groups.find(g=>g.id===id);return !!group&&data.nodes.some(n=>n.column===group.column&&statusNodes.has(n.id));
}
function statusEdgeMatches(edge,grouping){return !statusOnly||(!grouping&&statusNodes.has(edge.source)&&statusNodes.has(edge.target))}
function clearStatusFocus(){
  statusOnly=false;statusNodes.clear();document.getElementById('status-only').checked=false;document.getElementById('status-only').disabled=true;
  document.getElementById('status-fit').disabled=true;
  for(const {g} of cards.values())g.classList.remove('status-node');
}
function showStatusNode(id){
  clearScenarioMode();clearDecisionPath();comparisonOnly=false;document.getElementById('changes-only').checked=false;
  query='';document.getElementById('search').value='';active.clear();[0,...groups.map(g=>g.column)].forEach(c=>active.add(c));document.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed','true'));
  focus(id);
}
function statusLinks(row,parent){
  if(!row.nodes.length){html('p','Текущего узла на карте нет. Сохранённая запись доступна в этом списке.',parent,'status-empty-link');return}
  const links=html('div','',parent,'status-links');
  for(const id of row.nodes){const card=cards.get(id);if(!card)continue;const button=html('button',card.n.title,links,'button');button.onclick=()=>showStatusNode(id)}
}
function chooseStatusCategory(key,filter=true){
  clearStatusFocus();selected=null;statusCategory=key;statusContent.replaceChildren();
  const category=statusData.categories[key];
  for(const button of statusCards.children)button.setAttribute('aria-pressed',String(button.dataset.category===key));
  html('h3',category.title+' · '+category.count,statusContent);html('p',category.caption,statusContent,'status-note');
  if(!category.items.length)html('p','По данным этого снимка записей в разделе нет. Это не подтверждает полноту исходных данных.',statusContent,'status-note');
  const states={open:'открыт',needs_recheck:'требует повторной проверки',not_assessed:'ответ в текущем разборе не зафиксирован'};
  for(const row of category.items){
    const item=html('article','',statusContent,'status-item');
    if(key==='questions'){
      html('strong',row.id+' · '+row.title,item);html('p',states[row.state]||row.state,item);
      if(row.priority==='defer')html('p','В последнем разборе вопрос отложен.',item);
      if(row.reason)html('p','На что может повлиять: '+row.reason,item);
      if(row.saved_answer)html('p','Сохранённый ответ (актуальность: '+pathStatus(row.review_status)+'): '+row.saved_answer,item);
    }else if(key==='sources'){
      html('strong',row.id+' · '+row.title,item);for(const reason of row.reasons)html('p',reason,item);
    }else if(key==='blockers'){
      html('strong',row.origins.join(' · '),item);html('p',row.message,item);
    }else{
      html('strong',row.action,item);html('p',row.reason,item);
      html('p',row.seen_in_summary?'Этот вопрос уже был показан в просмотренной сводке; это не ответ.':'Просмотр именно этого вопроса в сводке не подтверждён.',item);
    }
    statusLinks(row,item);for(const id of row.nodes)statusNodes.add(id);
  }
  document.getElementById('status-only').disabled=!statusNodes.size;
  document.getElementById('status-fit').disabled=!statusNodes.size;
  if(filter&&statusNodes.size){
    clearScenarioMode();clearDecisionPath();comparisonOnly=false;document.getElementById('changes-only').checked=false;
    selected=null;query='';document.getElementById('search').value='';active.clear();[0,...groups.map(g=>g.column)].forEach(c=>active.add(c));document.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed','true'));
    statusOnly=true;document.getElementById('status-only').checked=true;
  }
  for(const [id,{g}] of cards)g.classList.toggle('status-node',statusNodes.has(id));highlight();
  if(statusOnly)document.getElementById('status-fit').click();
}
function statusTime(value){
  const match=typeof value==='string'&&value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/);
  return match?match[3]+'.'+match[2]+'.'+match[1]+' · '+match[4]+' · '+(match[5]==='Z'?'UTC':'UTC'+match[5]):value||'время не указано';
}
if(statusData){
  const clock=document.getElementById('status-time');html('span','Снимок: ',clock);
  const time=html('time',statusTime(statusData.as_of),clock);if(statusData.as_of)time.dateTime=statusData.as_of;
  if(statusData.context==='authored_example')html('span',' · Учебный пример: данные и согласования вымышлены.',clock);
  document.getElementById('status-note').textContent=statusData.note;
  document.getElementById('status-next').textContent='Проверенный следующий шаг: '+statusData.next_step;
  document.getElementById('status-owner').textContent=statusData.owner_text;
  const verdict=document.getElementById('status-verdict');
  verdict.textContent=statusData.review_draft_only?'Доступен черновик для пересмотра. Итоговая записка заблокирована.':statusData.ready===true?'Штатные проверки этого снимка не сообщают блокеров. Это не подтверждение истинности или согласие действовать.':'Штатные проверки требуют внимания; подробности ниже.';
  for(const [key,category] of Object.entries(statusData.categories)){
    const button=html('button','',statusCards,'status-card');button.dataset.category=key;button.setAttribute('aria-pressed','false');
    html('b',String(category.count),button);html('span',category.title,button);button.onclick=()=>chooseStatusCategory(key);
  }
  const checks=document.getElementById('status-checks');
  for(const [key,label] of [['content_review','Содержательная проверка'],['decision_stress_test','Сценарии'],['marketing_claims_audit','Обещания'],['research_selection','Исследование'],['feasibility','Осуществимость']])
    html('p',label+': '+pathStatus(statusData.review_statuses[key]),checks);
  for(const note of statusData.advisories)html('p',note,document.getElementById('status-advisories'));
}
document.getElementById('status-toggle').onclick=()=>{statusPanel.hidden=!statusPanel.hidden;document.getElementById('status-toggle').setAttribute('aria-expanded',String(!statusPanel.hidden))};
document.getElementById('status-only').onchange=event=>{statusOnly=event.target.checked&&statusNodes.size>0;selected=null;highlight()};
document.getElementById('status-clear').onclick=()=>{clearStatusFocus();selected=null;highlight()};
document.getElementById('status-fit').onclick=()=>{
  const ps=[...statusNodes].map(id=>positions.get(id)).filter(Boolean);if(!ps.length)return;
  const box=svg.getBoundingClientRect(),minX=Math.min(...ps.map(p=>p.x-p.r-35)),maxX=Math.max(...ps.map(p=>p.x+p.r+35)),minY=Math.min(...ps.map(p=>p.y-p.r-35)),maxY=Math.max(...ps.map(p=>p.y+p.r+40));
  zoom=Math.min(4,box.width/(maxX-minX+80),box.height/(maxY-minY+80));panX=box.width/2-(minX+maxX)/2*zoom;panY=box.height/2-(minY+maxY)/2*zoom;update();
};
