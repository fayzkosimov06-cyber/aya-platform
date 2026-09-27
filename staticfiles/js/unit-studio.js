(() => {
  'use strict';
  const root = document.querySelector('.unit-studio');
  if (!root) return;
  const member = root.querySelector('select#id_member');
  if (member) {
    const search = document.createElement('input'); search.type='search';search.placeholder='Найти учителя по имени';search.setAttribute('aria-label','Поиск учителя');
    search.addEventListener('input', () => {for (const option of member.options) option.hidden = !!option.value && !option.text.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase());});
    member.before(search);
  }
  const file = root.querySelector('input[type=file][name=cover]'), preview = root.querySelector('[data-cover-preview]');
  let previewUrl;
  if (file && preview) file.addEventListener('change', () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const image = file.files[0]; if (!image || !image.type.startsWith('image/')) return;
    previewUrl = URL.createObjectURL(image);const img = document.createElement('img');img.src=previewUrl;img.alt='Предпросмотр выбранной обложки';preview.replaceChildren(img);
  });
  window.addEventListener('pagehide',()=>{if(previewUrl) URL.revokeObjectURL(previewUrl);});
  const repeat = root.querySelector('#id_repeat_until'), start = root.querySelector('#id_starts_at'), note = root.querySelector('[data-repeat-summary]');
  const updateRepeat = () => {
    if (!repeat || !start || !note) return;
    if (!repeat.value || !start.value) {note.textContent='Будет создано одно занятие.';return;}
    const first = new Date(start.value.slice(0,10)+'T12:00:00'), last = new Date(repeat.value+'T12:00:00');
    const days = Math.round((last-first)/86400000);
    note.textContent=Number.isFinite(days)&&days>=0&&days<=366 ? `Занятий в серии: ${Math.floor(days/7)+1}. В тот же день недели и время.` : 'Проверьте дату окончания повторов.';
  };
  repeat?.addEventListener('change',updateRepeat);start?.addEventListener('change',updateRepeat);updateRepeat();
  let dirty = false, submitting = false;
  root.querySelectorAll('[data-dirty-form]').forEach(form => {
    form.addEventListener('change',event=>{
      if (!event.target.name) return;
      dirty=true;const label=form.querySelector('[data-save-state]');
      if(label) {label.textContent='Есть несохранённые изменения';label.classList.add('is-dirty');}
    });
    form.addEventListener('input',event=>{if(event.target.name) dirty=true;});
    form.addEventListener('submit',()=>{submitting=true;});
  });
  window.addEventListener('beforeunload',event=>{if(dirty&&!submitting){event.preventDefault();event.returnValue='';}});
})();
