(() => {
  const form = document.getElementById('rights-editor');
  if (!form) return;
  const people = new Map(JSON.parse(document.getElementById('rights-people-data').textContent).map(p => [p.id, p]));
  const scoped = JSON.parse(document.getElementById('rights-scoped-data').textContent);
  const checks = [...form.querySelectorAll('input[name="targets"]')];
  const rows = [...form.querySelectorAll('.permission-row')];
  const search = document.getElementById('rights-search');
  const scopes = {own:'свои команды', selected:'выбранные команды', all:'все команды'};
  const choices = {keep:'Не менять', on:'Разрешить', off:'Запретить', inherit:'По должности'};
  rows.forEach(row => {
    const select = row.querySelector('select');
    [...select.options].forEach(option => {option.textContent = choices[option.value] || option.textContent;});
  });
  checks.forEach(input => {
    const person = people.get(input.value);
    if (!person) return;
    const label = input.closest('label');
    const badge = document.createElement('small'); badge.textContent = person.role; label.appendChild(badge);
  });
  const selected = () => checks.filter(c => c.checked).map(c => people.get(c.value)).filter(Boolean);
  const update = () => {
    const picked = selected();
    document.getElementById('selected-count').textContent = picked.length ? `Выбрано: ${picked.length}` : 'Никто не выбран';
    document.getElementById('selected-names').textContent = picked.map(p => p.name).join(', ') || 'Можно выбрать одного или нескольких человек.';
    const changes = [];
    rows.forEach(row => {
      const code = row.dataset.code, select = row.querySelector('select');
      const current = row.querySelector('.permission-current');
      const active = picked.filter(p => p.states[code].enabled).length;
      if (picked.length === 1) {
        const state = picked[0].states[code];
        current.textContent = `Сейчас: ${state.enabled ? 'разрешено' : 'запрещено'} · ${state.source}${state.enabled && scoped.includes(code) ? ' · ' + (scopes[state.scope] || state.scope) : ''}`;
      } else current.textContent = picked.length ? `Сейчас разрешено: ${active} из ${picked.length}` : 'Выберите человека, чтобы увидеть его доступ.';
      row.classList.toggle('is-changed', select.value !== 'keep' && !!select.value);
      if (select.value && select.value !== 'keep') changes.push(`${row.querySelector('label').textContent} → ${choices[select.value]}`);
    });
    form.querySelector('.rights-ack').hidden = !['events_edit','directions','schools'].some(c => form.elements[c].value === 'off');
    rows.filter(r => r.querySelector('select').value && r.querySelector('select').value !== 'keep').forEach(r => r.closest('details').open = true);
    const needScope = rows.some(r => scoped.includes(r.dataset.code) && r.querySelector('select').value === 'on');
    form.querySelector('.rights-scope').hidden = !needScope;
    document.getElementById('selected-teams').hidden = form.elements.scope.value !== 'selected';
    const list = document.getElementById('rights-changes'); list.replaceChildren();
    changes.forEach(text => {const li = document.createElement('li'); li.textContent = text; list.appendChild(li);});
    if (needScope) {const li = document.createElement('li');li.textContent = 'Область: ' + scopes[form.elements.scope.value];list.appendChild(li);}
    document.getElementById('rights-review-text').textContent = changes.length ? `Изменений: ${changes.length}. Пользователей: ${picked.length}. Остальные права сохранятся.` : 'Выберите нужные изменения. Остальные права сохранятся.';
    document.getElementById('save-rights').disabled = !picked.length || !changes.length;
  };
  search.addEventListener('input', () => {
    let count = 0;
    checks.forEach(c => {const p = people.get(c.value);const show = p && `${p.name} ${p.role}`.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()); c.closest('#id_targets > div').hidden = !show; if(show)count++;});
    document.getElementById('rights-empty').hidden = count > 0;
  });
  document.getElementById('select-visible').addEventListener('click', () => {checks.filter(c => !c.closest('#id_targets > div').hidden).forEach(c => c.checked = true);update();});
  document.getElementById('clear-selection').addEventListener('click', () => {checks.forEach(c => c.checked = false);update();});
  document.getElementById('reset-rights').addEventListener('click', () => {rows.forEach(r => r.querySelector('select').value = 'keep');update();});
  form.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => {
    const sets = {visits:['visits'], events:['events_edit'], points:['points_award']};
    sets[button.dataset.preset].forEach(code => form.elements[code].value = 'on'); update();
  }));
  form.addEventListener('change', update);
  form.addEventListener('submit', () => {document.getElementById('save-rights').disabled = true;});
  update();
})();
