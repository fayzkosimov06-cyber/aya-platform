(() => {
 const form=document.querySelector('#quick-award'); if(!form)return;
 const options=[...form.querySelectorAll('.person-option')];
 const search=document.querySelector('#people-search'), chips=document.querySelector('#selected-people');
 function update(){
  const selected=options.filter(o=>o.querySelector('input').checked);chips.replaceChildren();
  selected.forEach(o=>{const b=document.createElement('button');b.type='button';b.className='person-chip';b.textContent=o.querySelector('.person-name').firstChild.textContent.trim()+' ×';b.setAttribute('aria-label','Убрать '+b.textContent);b.onclick=()=>{o.querySelector('input').checked=false;update()};chips.append(b)});
  document.querySelector('#selected-count').textContent=selected.length;
  const n=Number(document.querySelector('#id_points').value);
  document.querySelector('#award-summary').textContent=selected.length&&n>0?`${selected.length} участников × ${n} баллов = ${selected.length*n} всего`:'Выберите участников и укажите баллы';
 }
 const toggle=document.querySelector('#show-other-people');let allPeople=!toggle;
 function filter(){let count=0;const q=search.value.trim().toLocaleLowerCase();options.forEach(o=>{o.hidden=q?!o.dataset.search.toLocaleLowerCase().includes(q):(!allPeople&&o.dataset.team!=='yes'&&!o.querySelector('input').checked);if(!o.hidden)count++;});document.querySelector('#no-people').hidden=!!count;}
 search.addEventListener('input',filter);if(toggle)toggle.onclick=()=>{allPeople=!allPeople;toggle.textContent=allPeople?'Показать команду':'Найти другого волонтёра';filter();};filter();
 form.addEventListener('change',update);document.querySelector('#id_points').addEventListener('input',update);
 const rules=JSON.parse(document.querySelector('#point-rules').textContent);document.querySelector('#id_kind').addEventListener('change',e=>{const r=rules.find(x=>String(x.id)===e.target.value);if(r)document.querySelector('#id_points').value=r.points;update()});
 update();
})();
