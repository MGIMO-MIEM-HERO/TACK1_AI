let currentHistoryEvent=null,historyOnly=false,historyNodes=new Set();
const historyData=data.decision_history,historyPanel=document.getElementById('history-panel'),historyList=document.getElementById('history-list'),historyDetails=document.getElementById('history-details'),historyNotice=document.getElementById('history-notice');
const historyKinds={checkpoints:'Рекомендации и контрольные точки',reviews:'Проверки',answers:'Ответы владельца',views:'Просмотры',results:'Результаты'};
const historyStatuses={saved_checkpoint:'сохранённая контрольная точка',current:'актуальный ответ',historical:'историческая версия',superseded:'замещён более поздним ответом',future:'время ответа в будущем',reference_changed_or_missing:'исходный файл ответа изменён или недоступен',context_mismatch:'контекст ответа не совпадает',current_view:'просмотр текущей версии; не согласие',historical_view:'исторический просмотр; не согласие',current_result_only:'ответ только по текущей версии результата',historical_result:'ответ по прежней версии результата',needs_verification:'основания результата требуют проверки',synthetic:'синтетические данные',real:'записано как реальное наблюдение',not_checked:'актуальность не проверена'};
function historyMatches(id){
  if(!historyOnly)return true;if(historyNodes.has(id))return true;
  const group=groups.find(g=>g.id===id);return !!group&&data.nodes.some(n=>n.column===group.column&&historyNodes.has(n.id));
}
function historyEdgeMatches(edge,grouping){return !historyOnly||(!grouping&&historyNodes.has(edge.source)&&historyNodes.has(edge.target))}
function historyTime(event){
  if(event.time_utc)return new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(event.time_utc))+' · Москва';
  const labels={missing:'дата не записана',date_only:'точное время не записано',timezone_missing:'часовой пояс не записан',invalid:'время не удалось проверить'};
  return (event.at?String(event.at)+' · ':'')+(labels[event.time_precision]||'нет точного времени');
}
function clearHistoryFocus(){
  currentHistoryEvent=null;historyOnly=false;historyNodes.clear();historyNotice.hidden=true;
  document.getElementById('history-only').checked=false;document.getElementById('history-only').disabled=true;document.getElementById('history-fit').disabled=true;
  historyDetails.replaceChildren();html('p','Выберите сохранённое событие, чтобы прочитать его сведения.',historyDetails,'history-note');
  for(const {g} of cards.values())g.classList.remove('history-node');
}
function selectHistoryEvent(id){
  const event=historyData.events.find(e=>e.id===id);if(!event)return;
  clearHistoryFocus();clearScenarioMode();clearDecisionPath();clearStatusFocus();
  comparisonOnly=false;document.getElementById('changes-only').checked=false;query='';document.getElementById('search').value='';selected=null;
  active.clear();[0,...groups.map(g=>g.column)].forEach(c=>active.add(c));document.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed','true'));
  currentHistoryEvent=event;historyNodes=new Set(event.nodes);historyOnly=!!historyNodes.size;
  document.getElementById('history-only').disabled=!historyNodes.size;document.getElementById('history-only').checked=historyOnly;document.getElementById('history-fit').disabled=!historyNodes.size;
  document.getElementById('history-notice-text').textContent='ИСТОРИЯ · '+event.title+'. Открыта сохранённая запись; прошлое состояние проекта не восстановлено.';historyNotice.hidden=false;
  historyDetails.replaceChildren();html('h3',event.title,historyDetails);html('p',historyTime(event),historyDetails,'history-note');
  html('p',event.time_basis,historyDetails,'history-note');
  html('p',historyStatuses[event.status]||pathStatus(event.status),historyDetails,'history-state');
  if(event.after_export_clock)html('p','Время этой записи позже часов среза. Не считайте событие состоявшимся к моменту этого снимка.',historyDetails,'history-warning');
  if(event.kind==='checkpoints'&&!event.recommendation_recorded)html('p','Структурированная рекомендация в этой точке не записана. Из текста заметки она не выводится.',historyDetails,'history-warning');
  if(event.kind==='answers'&&!event.details.confirmed_by)html('p','Автор ответа в этой записи не указан.',historyDetails,'history-note');
  if(event.kind==='views')html('p','Отметка просмотра не является ответом владельца или разрешением действовать.',historyDetails,'history-warning');
  if(event.kind==='results')html('p',event.details.data_origin==='synthetic'?'Синтетический результат; это не реальная проверка продукта.':'Происхождение результата записано как реальное; пределы оснований сохранены в записи.',historyDetails,'history-note');
  const labels={review_id:'Версия разбора',reviewer:'Кто указан в записи',limitations:'Ограничения',context:'Контекст',strongest_objection:'Сильнейшее возражение',reversal_condition:'Условие пересмотра',recommendation:'Условная рекомендация разбора',stop_rule:'Условие остановки',kind:'Предмет',outcome:'Исход ответа',statement:'Содержание ответа',confirmed_by:'Автор ответа',note:'Записанная заметка',result_id:'Результат',metric:'Показатель',value:'Значение',unit:'Единица',summary:'Сохранённое описание',data_origin:'Происхождение'};
  const visible=new Set(['review_id','reviewer','limitations','context','strongest_objection','reversal_condition','recommendation','stop_rule','kind','outcome','statement','confirmed_by','note','result_id','metric','value','unit','summary','data_origin']);
  for(const [key,v] of Object.entries(event.details)){
    if(key==='Версия снимка'||key==='Версия базы проверки')continue;
    if(key==='Оценка изменения'){
      if(v?.assessment){
        const section=html('div','',historyDetails,'history-field');html('strong','Сохранённая оценка влияния',section);
        html('p',({changed:'Вывод изменён',unchanged:'Вывод сохранён',unknown:'Влияние не определено'}[v.assessment.conclusion]||v.assessment.conclusion)+'\n'+v.assessment.rationale,section);
      }
      continue;
    }
    if(!visible.has(key)&&!/[А-Яа-я]/.test(key))continue;
    if(v===null||v===undefined){if(['Рекомендация в снимке','Исходная рекомендация в базе проверки','Выбор человека в снимке'].includes(key)){const field=html('div','',historyDetails,'history-field');html('strong',key,field);html('p','Не зафиксирована',field)}continue}
    const translations=key==='kind'?{recommendation:'согласование рекомендации',permission:'разрешение действовать',data:'подтверждение данных',resume:'просмотр сводки'}:key==='outcome'?{approved:'записано одобрение указанного предмета и версии',rejected:'в записи указан отказ',needs_changes:'в записи запрошены изменения'}:key==='data_origin'?{synthetic:'синтетические данные',real:'записано как реальное наблюдение'}:{};
    const field=html('div','',historyDetails,'history-field');html('strong',labels[key]||key,field);html('p',typeof v==='string'&&translations[v]||value(v),field);
  }
  const raw=html('details','',historyDetails,'history-raw');html('summary','Время и происхождение записи',raw);
  html('p','Исходная отметка: '+(event.at||'не записана'),raw);html('p','Источник записи: '+event.ref,raw);
  html('pre',JSON.stringify(event.details,null,2),raw);
  if(!event.nodes.length)html('p','У этой записи нет отдельного текущего узла. Сведения показаны здесь, без добавления узлов или реконструкции старой карты.',historyDetails,'history-note');
  for(const id of event.nodes){const card=cards.get(id);if(!card)continue;const button=html('button','Открыть запись: '+card.n.title,historyDetails,'button');button.onclick=()=>focus(id,true)}
  for(const [key,{g}] of cards)g.classList.toggle('history-node',historyNodes.has(key));
  revealNodes(event.nodes);if(event.nodes.length)focus(event.nodes[0]);else focus(cards.has('summary:current')?'summary:current':'task');selected=null;highlight();
  if(historyOnly)document.getElementById('history-fit').click();
  historyDetails.scrollIntoView({block:'nearest'});
}
function renderHistoryList(){
  clearHistoryFocus();historyList.replaceChildren();
  const kind=document.getElementById('history-kind').value,query=document.getElementById('history-search').value.toLocaleLowerCase();
  const matches=historyData.events.filter(e=>(!kind||e.kind===kind)&&(!query||JSON.stringify(e).toLocaleLowerCase().includes(query)));
  const dated=matches.filter(e=>e.time_utc),undated=matches.filter(e=>!e.time_utc);
  if(document.getElementById('history-order').value==='newest')dated.reverse();
  document.getElementById('history-count').textContent='Показано '+matches.length+' из '+historyData.events.length+' сохранённых записей. Без точного времени: '+undated.length+'.';
  if(!matches.length)html('p',historyData.events.length?'По выбранному фильтру событий нет.':'Сохранённых событий ещё нет. Дата текущего решения не выводится из поля обновления проекта.',historyList,'history-note');
  for(const [title,events] of [['С точным временем',dated],['Без точного времени — отдельно от временной шкалы',undated]]){
    if(!events.length)continue;html('h3',title,historyList);
    const list=html('ol','',historyList,'history-timeline');
    for(const event of events){
      const item=html('li','',list),button=html('button','',item,'history-event');button.dataset.event=event.id;
      html('small',historyTime(event)+' · '+historyKinds[event.kind],button);html('strong',event.title,button);
      html('span',historyStatuses[event.status]||pathStatus(event.status),button);
      if(event.after_export_clock)html('span','Позже времени среза',button,'history-future');
      button.onclick=()=>selectHistoryEvent(event.id);
    }
  }
  highlight();
}
const all=html('option','Все события',document.getElementById('history-kind'));all.value='';
for(const [key,label] of Object.entries(historyKinds)){const option=html('option',label+' · '+historyData.counts[key],document.getElementById('history-kind'));option.value=key}
const historyClock=historyData.current.time_utc?historyTime({time_utc:historyData.current.time_utc}):statusTime(historyData.current.as_of);
document.getElementById('history-current').textContent='Текущее состояние на момент экспорта: рекомендация '+(historyData.current.recommendation||'не записана')+'; выбор человека '+(historyData.current.human_choice||'не записан')+'. Срез: '+historyClock+'.';
document.getElementById('history-note').textContent=historyData.note+' События с точным временем показаны по Москве; исходная отметка сохранена в деталях.';
if(historyData.current.pending_change_events)html('p','Изменения, ожидающие разбора в текущем состоянии: '+historyData.current.pending_change_events+'. Это не датированные события истории.',document.getElementById('history-current'),'history-note');
document.getElementById('history-toggle').onclick=()=>{historyPanel.hidden=!historyPanel.hidden;document.getElementById('history-toggle').setAttribute('aria-expanded',String(!historyPanel.hidden))};
document.getElementById('history-kind').onchange=document.getElementById('history-order').onchange=renderHistoryList;
document.getElementById('history-search').oninput=renderHistoryList;
document.getElementById('history-only').onchange=event=>{historyOnly=event.target.checked&&historyNodes.size>0;selected=null;highlight()};
document.getElementById('history-clear').onclick=document.getElementById('history-exit').onclick=()=>{clearHistoryFocus();focus(cards.has('summary:current')?'summary:current':'task');selected=null;highlight()};
document.getElementById('history-fit').onclick=()=>{
  fitNodeSet(historyNodes);
};
renderHistoryList();
