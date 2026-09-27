(() => {
  'use strict';
  document.querySelectorAll('.selection-list,.member-picker').forEach(list => {
    if (list.matches('input,select,textarea') || list.dataset.selectionReady || list.parentElement.closest('.selection-list,.member-picker')) return;
    list.dataset.selectionReady = 'true';
    const rows = [...list.children].filter(row => row.querySelector('input[type=checkbox],input[type=radio]'));
    const boxes = rows.flatMap(row => [...row.querySelectorAll('input[type=checkbox]:not(:disabled),input[type=radio]:not(:disabled)')]);
    const single = boxes.some(box=>box.type==='radio');
    if (!boxes.length) return;
    const panel = document.createElement('div'); panel.className='aya-selection';
    const bar = document.createElement('div'); bar.className='aya-selection-bar';
    const search=document.createElement('input'); search.type='search'; search.placeholder='Поиск в списке'; search.setAttribute('aria-label','Поиск в списке');
    const count=document.createElement('span'); count.className='aya-selection-count'; count.setAttribute('aria-live','polite');
    const filter=document.createElement('button'); filter.type='button'; filter.textContent='Выбранные';filter.setAttribute('aria-pressed','false');
    const menu=document.createElement('details'); const summary=document.createElement('summary');summary.textContent='Выбор';menu.append(summary);
    let selectedOnly=false;
    const update=()=>{
      const q=search.value.trim().toLocaleLowerCase();
      rows.forEach(row=>{row.hidden=!row.textContent.toLocaleLowerCase().includes(q)||(selectedOnly&&!row.querySelector('input:checked'));});
      count.textContent=`Выбрано: ${boxes.filter(c=>c.checked).length} · Доступно для выбора: ${boxes.length} · Показано: ${rows.filter(r=>!r.hidden).length}`;
      empty.hidden=rows.some(r=>!r.hidden);
    };
    for(const [label,checked] of [['Выбрать найденных',true],['Очистить весь выбор',false]]){
      const button=document.createElement('button');button.type='button';button.textContent=label;
      button.addEventListener('click',()=>{
        const targets=checked?rows.filter(r=>!r.hidden).flatMap(r=>[...r.querySelectorAll('input[type=checkbox]:not(:disabled)')]):boxes;
        targets.forEach(c=>{if(c.checked!==checked){c.checked=checked;c.dispatchEvent(new Event('change',{bubbles:true}));}});
        menu.open=false;update();
      });menu.append(button);
    }
    filter.addEventListener('click',()=>{selectedOnly=!selectedOnly;filter.setAttribute('aria-pressed',String(selectedOnly));update();});
    search.addEventListener('input',update);list.addEventListener('change',update);
    const empty=document.createElement('p');empty.className='aya-selection-empty';empty.textContent='Ничего не найдено. Измените поиск или отключите фильтр выбранных.';
    bar.append(search,filter);if(!single)bar.append(menu);list.before(panel);panel.append(bar,count,list,empty);update();
  });
})();
