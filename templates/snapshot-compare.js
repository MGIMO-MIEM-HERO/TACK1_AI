// Previous maps are data only: never attach their HTML or execute their scripts.
let comparisonOnly=false,comparisonChanges=new Map(),comparisonRead=0;
function comparisonMatches(id){
  if(!comparisonOnly)return true;
  if(comparisonChanges.has(id))return true;
  const group=groups.find(g=>g.id===id);
  return !!group&&data.nodes.some(n=>n.column===group.column&&comparisonChanges.has(n.id));
}
function stable(value){
  if(Array.isArray(value))return '['+value.map(stable).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stable(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
function readComparison(text){
  let parsed;
  if(text.trimStart().startsWith('<')){
    const start='<script id="data" type="application/json">',at=text.indexOf(start);
    if(at<0)throw new Error('В файле нет данных карты. Выберите HTML, созданный агентом.');
    const end=text.indexOf('</scr'+'ipt>',at+start.length);
    if(end<0)throw new Error('Данные карты повреждены.');
    parsed=JSON.parse(text.slice(at+start.length,end));
  }else parsed=JSON.parse(text);
  if(!parsed||typeof parsed!=='object')throw new Error('В файле нет данных снимка.');
  const snapshot=parsed.comparison_snapshot||parsed;
  if(snapshot.schema_version!==1||!Array.isArray(snapshot.records)||typeof snapshot.project_id!=='string'||typeof snapshot.state_sha256!=='string')
    throw new Error('Этот снимок ещё не поддерживает сравнение. Сохраните карту новой версией агента.');
  if(snapshot.project_id!==data.comparison_snapshot.project_id)throw new Error('Это другой проект. Выберите предыдущую карту того же проекта.');
  const ids=new Set();
  if(snapshot.records.length>50000)throw new Error('Слишком много записей в снимке.');
  for(const row of snapshot.records){
    if(!row||typeof row.id!=='string'||typeof row.title!=='string'||!row.record||typeof row.record!=='object'||Array.isArray(row.record)||ids.has(row.id))
      throw new Error('Некорректные или повторяющиеся записи снимка.');
    ids.add(row.id);
  }
  return snapshot;
}
const changesPanel=document.getElementById('changes-panel'),changesList=document.getElementById('changes-list'),changesInfo=document.getElementById('changes-info'),changesDetail=document.getElementById('changes-detail');
const changeNames={added:'Добавлено',changed:'Изменено',removed:'Удалено из снимка'};
function clearComparison(){
  comparisonRead++;
  comparisonOnly=false;comparisonChanges.clear();
  document.getElementById('changes-only').checked=false;document.getElementById('changes-only').disabled=true;
  for(const {g} of cards.values())g.classList.remove('snapshot-added','snapshot-changed');
  changesList.replaceChildren();changesDetail.replaceChildren();highlight();
}
const comparisonLabels={title:'Название',objective:'Цель',stage:'Этап',constraints:'Ограничения',recommended_option_id:'Рекомендация',recommendation_rationale:'Обоснование рекомендации',chosen_option_id:'Выбор человека',next_action:'Сохранённый следующий шаг',observed_file_version:'Отпечаток файла источника',status:'Статус',source_ids:'Источники',evidence_ids:'Основания',claim:'Вывод',claim_type:'Тип основания',limitations:'Ограничения',recorded_at:'Дата записи',updated_at:'Дата обновления'};
function showDifference(change){
  changesDetail.replaceChildren();
  html('h3',changeNames[change.kind]+' · '+change.title,changesDetail);
  if(change.kind==='removed')html('p','В текущем снимке записи нет. Она показана здесь из предыдущего снимка; это не отметка отзыва и не текущий узел карты.',changesDetail);
  else if(cards.has(change.id))focus(change.id);
  const before=change.before?.record,after=change.after?.record;
  const keys=new Set([...Object.keys(before||{}),...Object.keys(after||{})]);
  for(const key of keys){
    if(before&&after&&stable(before[key])===stable(after[key]))continue;
    const row=html('div','',changesDetail,'change-field');html('strong',comparisonLabels[key]||fieldNames[key]||key,row);
    if(before)html('p','Было: '+(Object.hasOwn(before,key)?value(before[key]):'поле отсутствовало'),row);
    if(after)html('p','Стало: '+(Object.hasOwn(after,key)?value(after[key]):'поле отсутствует'),row);
  }
}
function applyComparison(previous,name){
  clearComparison();
  const old=new Map(previous.records.map(n=>[n.id,n])),current=new Map(data.comparison_snapshot.records.map(n=>[n.id,n]));
  for(const [id,row] of current){
    if(!old.has(id))comparisonChanges.set(id,{id,title:row.title,kind:'added',after:row});
    else if(stable(row.record)!==stable(old.get(id).record))comparisonChanges.set(id,{id,title:row.title,kind:'changed',before:old.get(id),after:row});
  }
  for(const [id,row] of old)if(!current.has(id))comparisonChanges.set(id,{id,title:row.title,kind:'removed',before:row});
  const count=kind=>[...comparisonChanges.values()].filter(c=>c.kind===kind).length;
  changesInfo.textContent='Сравнение с «'+name+'» · '+count('added')+' добавлено · '+count('changed')+' изменено · '+count('removed')+' удалено из снимка. Зелёный контур — добавлено, фиолетовый — изменено. Удалённые записи — только в списке. '+data.comparison_snapshot.note;
  const version=html('details','',changesList,'comparison-versions');html('summary','Версии сравнения',version);
  html('p','Ранее: '+(previous.updated_at||'дата не записана')+' · '+previous.state_sha256,version);
  html('p','Сейчас: '+(data.comparison_snapshot.updated_at||'дата не записана')+' · '+data.comparison_snapshot.state_sha256,version);
  const oldRecommendation=previous.recommendation,newRecommendation=data.comparison_snapshot.recommendation;
  if(oldRecommendation&&stable(oldRecommendation)!==stable(newRecommendation)){
    const rec=html('div','',changesList,'recommendation-change');
    html('strong','Рекомендация: '+(oldRecommendation.option_id||'не записана')+' → '+(newRecommendation.option_id||'не записана'),rec);
    html('p','Записанное обоснование сейчас: '+(newRecommendation.rationale||'не записано; причина не выводится из различий'),rec);
  }
  if(!comparisonChanges.size)html('p','Сохранённые записи совпадают. Это не подтверждает неизменность недоступных файлов или внешних данных.',changesList);
  for(const change of comparisonChanges.values()){
    const button=html('button',changeNames[change.kind]+' · '+change.title,changesList,'change-row '+change.kind);
    button.onclick=()=>showDifference(change);
    if(cards.has(change.id))cards.get(change.id).g.classList.add('snapshot-'+change.kind);
  }
  document.getElementById('changes-only').disabled=false;highlight();
}
document.getElementById('changes-toggle').onclick=()=>{
  changesPanel.hidden=!changesPanel.hidden;document.getElementById('changes-toggle').setAttribute('aria-expanded',String(!changesPanel.hidden));
};
document.getElementById('changes-load').onclick=()=>document.getElementById('changes-file').click();
document.getElementById('changes-file').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  clearComparison();changesInfo.textContent='Читаю выбранный снимок…';
  const request=comparisonRead;
  try{
    if(file.size>8*1024*1024)throw new Error('Снимок больше 8 МБ. Выберите меньший файл.');
    const text=await file.text();if(request!==comparisonRead)return;
    applyComparison(readComparison(text),file.name);
  }catch(error){if(request===comparisonRead)changesInfo.textContent=error instanceof SyntaxError?'Не удалось прочитать данные: файл повреждён или имеет другой формат.':error.message;}
  event.target.value='';
};
document.getElementById('changes-only').onchange=event=>{comparisonOnly=event.target.checked;selected=null;highlight()};
document.getElementById('changes-clear').onclick=()=>{clearComparison();changesInfo.textContent='Выберите предыдущую HTML-карту этого проекта. Файл читается только в браузере и никуда не отправляется.'};
