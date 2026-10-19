(() => {
  'use strict';
  const form = document.querySelector('[data-card-selection]');
  if (form) {
    const key = `aya-card-selection-${form.dataset.cardSelection}`;
    let saved = [];
    try { saved = JSON.parse(sessionStorage.getItem(key) || '[]'); } catch {}
    const selected = new Set(Array.isArray(saved) ? saved.filter(x => typeof x === 'string').slice(0, 100) : []);
    const boxes = [...form.querySelectorAll('input[type=checkbox][name=cards]:not(:disabled)')];
    const update = () => {
      for (const box of boxes) box.checked = selected.has(box.value);
      form.querySelector('[data-card-count]').textContent = `Выбрано карт: ${selected.size}`;
      try { sessionStorage.setItem(key, JSON.stringify([...selected])); } catch {}
    };
    boxes.forEach(box => box.addEventListener('change', () => {
      if (box.checked && selected.size < 100) selected.add(box.value); else selected.delete(box.value);
      update();
    }));
    form.querySelector('[data-card-select-page]').addEventListener('click', () => {
      boxes.forEach(box => { if (selected.size < 100) selected.add(box.value); }); update();
    });
    form.querySelector('[data-card-clear]').addEventListener('click', () => { selected.clear(); update(); });
    form.addEventListener('submit', event => {
      if (!selected.size) { event.preventDefault(); form.querySelector('[data-card-count]').textContent = 'Сначала выберите карты для печати.'; return; }
      form.querySelectorAll('[data-card-hidden]').forEach(input => input.remove());
      boxes.forEach(box => { box.name = ''; });
      for (const id of selected) {
        const input = document.createElement('input'); input.type = 'hidden'; input.name = 'cards'; input.value = id; input.dataset.cardHidden = '1'; form.append(input);
      }
      // Restore the controls after starting an attachment download.
      setTimeout(() => { boxes.forEach(box => { box.name = 'cards'; }); form.querySelectorAll('[data-card-hidden]').forEach(input => input.remove()); }, 1000);
    });
    update();
  }
  const editor = document.querySelector('[data-card-editor]');
  if (editor) {
    const user = editor.querySelector('#id_user');
    const status = editor.querySelector('[data-card-fill-status]');
    let pending;
    const fill = async () => {
      if (!user.value) { status.textContent = 'Сначала выберите волонтёра.'; return; }
      if (pending) pending.abort(); pending = new AbortController();
      try {
        status.textContent = 'Загружаю данные профиля…';
        const response = await fetch(editor.dataset.profileUrl.replace('/0/', `/${encodeURIComponent(user.value)}/`), {credentials:'same-origin', cache:'no-store', signal:pending.signal});
        if (!response.ok) throw new Error('profile');
        const data = await response.json();
        for (const key of ['first_name','last_name','patronymic','course']) editor.querySelector(`#id_${key}`).value = data[key] ?? '';
        if (editor.dataset.newCard) {
          const edition = editor.querySelector('#id_edition');
          const year = edition.selectedOptions[0]?.textContent.match(/\d{4}/)?.[0];
          editor.querySelector('#id_number').value = year ? `AYA-${year.slice(-2)}-${user.value.padStart(4,'0')}` : data.number;
        }
        editor.querySelector('#id_photo_source').value = data.has_photo ? 'profile' : 'upload';
        status.textContent = data.has_photo ? 'Данные заполнены. Проверьте ФИО и курс перед сохранением.' : 'Данные заполнены. В профиле нет фото — загрузите отдельную фотографию.';
      } catch (error) { if (error.name !== 'AbortError') status.textContent = 'Не удалось получить данные. Можно заполнить поля вручную.'; }
    };
    editor.querySelector('[data-card-fill]').addEventListener('click', fill);
    if (editor.dataset.newCard) {
      user.addEventListener('change', fill);
      // The existing select2 widget emits its own change event.
      if (window.jQuery) window.jQuery(user).on('select2:select', fill);
    }
  }
})();
