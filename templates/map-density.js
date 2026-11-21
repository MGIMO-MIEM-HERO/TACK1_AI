// Presentation only: preserve camera, filters, selection and saved records.
let mapDetail='compact';
function titleLines(title){
  const chars=Array.from(String(title).replace(/\s+/g,' ').trim()),lines=[];
  while(chars.length&&lines.length<3){
    let end=Math.min(24,chars.length);
    if(chars.length>end){const space=chars.slice(0,end+1).lastIndexOf(' ');if(space>10)end=space}
    let text=chars.splice(0,end).join('').trim();
    while(chars[0]===' ')chars.shift();
    if(lines.length===2&&chars.length)text=text.replace(/.$/u,'')+'…';
    lines.push(text);
  }
  return lines.length?lines:['Без названия'];
}
for(const {n,g} of cards.values()){
  if(g.classList.contains('hub')||g.classList.contains('center'))continue;
  const label=g.querySelector('.label');label.classList.add('record-title');
  label.replaceChildren();
  for(const [index,line] of titleLines(n.title).entries())el('tspan',{x:0,dy:index?13:0},label).textContent=line;
}
function setMapDetail(mode){
  if(mode!=='compact'&&mode!=='detailed')return;
  mapDetail=mode;svg.setAttribute('data-detail',mode);
  document.getElementById('view-compact').setAttribute('aria-pressed',String(mode==='compact'));
  document.getElementById('view-detailed').setAttribute('aria-pressed',String(mode==='detailed'));
  document.getElementById('view-note').textContent=mode==='compact'
    ?'Компактный вид: короткие ID и отметки статуса. Название — при выборе или фокусе; полная запись — в боковой карточке.'
    :'Подробный вид: названия записей до трёх строк. Для плотных групп приблизьте карту; полное название и статус — в боковой карточке.';
}
document.getElementById('view-compact').onclick=()=>setMapDetail('compact');
document.getElementById('view-detailed').onclick=()=>setMapDetail('detailed');
setMapDetail('compact');
