(() => {
  'use strict';
  const form = document.querySelector('[data-profile-editor]');
  if (!form) return;
  const input = form.querySelector('[data-profile-photo-input]');
  const preview = form.querySelector('[data-photo-preview]');
  const image = preview.querySelector('img');
  const clear = form.querySelector('input[name="photo-clear"]');
  const reframe = form.querySelector('[data-photo-reframe]');
  const reset = form.querySelector('[data-photo-reset]');
  const status = form.querySelector('#profile-photo-state');
  const saveState = form.querySelector('[data-editor-state]');
  const dialog = document.querySelector('.pe-crop-dialog');
  const canvas = dialog.querySelector('canvas'), ctx = canvas.getContext('2d');
  const zoomField = dialog.querySelector('[data-crop-zoom]');
  const xField = dialog.querySelector('[data-crop-x]'), yField = dialog.querySelector('[data-crop-y]');
  const apply = dialog.querySelector('[data-crop-apply]');
  const original = dialog.querySelector('[data-crop-original]');
  const cropStatus = dialog.querySelector('[data-crop-status]');
  let accepted = null, acceptedUrl = '', pending = null, pendingUrl = '', decoded = null;
  let zoom = 1, x = .5, y = .5, drag = null, generation = 0, origin = input, dirty = false, submitting = false;
  const markDirty = () => { dirty = true; saveState.textContent = 'Есть несохранённые изменения'; };
  const assign = file => { const transfer = new DataTransfer(); if (file) transfer.items.add(file); input.files = transfer.files; };
  const showAccepted = () => {
    image.src = clear?.checked ? preview.dataset.photoFallback : (acceptedUrl || preview.dataset.photoInitial || preview.dataset.photoFallback);
    reframe.hidden = !!clear?.checked || !(accepted || preview.dataset.photoInitial);
    reset.hidden = !accepted;
  };
  const cleanPending = () => { if (pendingUrl) URL.revokeObjectURL(pendingUrl); pendingUrl = ''; pending = null; decoded = null; };
  const source = () => { const side = Math.min(decoded.naturalWidth, decoded.naturalHeight) / zoom; return {side, left:(decoded.naturalWidth-side)*x, top:(decoded.naturalHeight-side)*y}; };
  const draw = () => { if (!decoded) return; const s = source(); ctx.clearRect(0,0,720,720); ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(decoded,s.left,s.top,s.side,s.side,0,0,720,720); };
  const accept = file => {
    assign(file); accepted = file;
    if (acceptedUrl) URL.revokeObjectURL(acceptedUrl);
    acceptedUrl = URL.createObjectURL(file);
    if (clear) clear.checked = false;
    showAccepted(); markDirty(); status.textContent = 'Новая фотография готова. Сохраните изменения, чтобы обновить профиль.';
    dialog.close();
  };
  const begin = async (file, trigger) => {
    const token = ++generation;
    if (!file) return;
    if (!/\.(jpe?g|png|webp)$/i.test(file.name) || !['image/jpeg','image/png','image/webp'].includes(file.type)) {
      assign(accepted); status.textContent = 'Выберите фотографию JPEG, PNG или WebP.'; return;
    }
    if (file.size > 5*1024*1024) { assign(accepted); status.textContent = 'Фотография слишком большая. Максимум 5 МБ.'; return; }
    const url = URL.createObjectURL(file), picture = new Image(); picture.src = url;
    try { await picture.decode(); }
    catch { URL.revokeObjectURL(url); if (token === generation) { assign(accepted); status.textContent = 'Не удалось прочитать фотографию. Выберите другой файл.'; } return; }
    if (token !== generation) { URL.revokeObjectURL(url); return; }
    if (picture.naturalWidth*picture.naturalHeight > 20000000 || Math.max(picture.naturalWidth,picture.naturalHeight)>10000) {
      URL.revokeObjectURL(url); assign(accepted); status.textContent = 'Фотография слишком большая: максимум 20 миллионов пикселей и 10000 по стороне.'; return;
    }
    cleanPending(); pending = file; pendingUrl = url; decoded = picture; origin = trigger;
    // Keep only the accepted selection in the form until the user confirms the dialog.
    assign(accepted); zoom = 1; x = .5; y = .5; zoomField.value = 1; xField.value = .5; yField.value = .5;
    apply.disabled = original.disabled = false; cropStatus.textContent = '';
    dialog.showModal(); draw();
  };
  input.addEventListener('change', () => begin(input.files[0], input));
  reframe.addEventListener('click', async () => {
    if (accepted) { begin(accepted, reframe); return; }
    const token = ++generation;
    reframe.disabled = true;
    try {
      const url = new URL(preview.dataset.photoInitial, location.href);
      if (url.origin !== location.origin) throw new Error('Unexpected photo location');
      const response = await fetch(url, {credentials:'same-origin'});
      if (!response.ok) throw new Error('Photo unavailable');
      const blob = await response.blob();
      if (token !== generation) return;
      const type = blob.type.split(';')[0];
      const extension = {'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[type];
      if (!extension) throw new Error('Unsupported image');
      await begin(new File([blob], 'profile.'+extension, {type}), reframe);
    } catch { if (token === generation) status.textContent = 'Не удалось открыть текущее фото. Выберите файл с устройства.'; }
    finally { reframe.disabled = false; }
  });
  for (const field of [zoomField,xField,yField]) field.addEventListener('input', () => { zoom = Number(zoomField.value); x = Number(xField.value); y = Number(yField.value); draw(); });
  canvas.addEventListener('pointerdown', event => { drag = {x:event.clientX,y:event.clientY,ox:x,oy:y}; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointermove', event => {
    if (!drag || !decoded) return;
    const s = source(), rect = canvas.getBoundingClientRect();
    // object-fit:contain can leave side gutters on short screens: use the visible square size.
    const size = Math.min(rect.width, rect.height);
    x = Math.max(0,Math.min(1,drag.ox-(event.clientX-drag.x)/size*s.side/Math.max(1,decoded.naturalWidth-s.side)));
    y = Math.max(0,Math.min(1,drag.oy-(event.clientY-drag.y)/size*s.side/Math.max(1,decoded.naturalHeight-s.side)));
    xField.value = x; yField.value = y; draw();
  });
  for (const event of ['pointerup','pointercancel','lostpointercapture']) canvas.addEventListener(event, () => { drag = null; });
  apply.addEventListener('click', () => {
    if (!decoded || !pending) return;
    apply.disabled = original.disabled = true;
    const token = generation, file = pending, s = source(), out = document.createElement('canvas');
    out.width = out.height = Math.max(1,Math.round(Math.min(1200,s.side)));
    const context = out.getContext('2d'); context.fillStyle = '#fff'; context.fillRect(0,0,out.width,out.height); context.imageSmoothingQuality = 'high';
    context.drawImage(decoded,s.left,s.top,s.side,s.side,0,0,out.width,out.height);
    out.toBlob(blob => {
      if (token !== generation || !dialog.open) return;
      if (!blob) { cropStatus.textContent = 'Не удалось подготовить кадр. Попробуйте ещё раз.'; apply.disabled = original.disabled = false; return; }
      try { accept(new File([blob],file.name.replace(/\.[^.]+$/,'')+'-crop.jpg',{type:'image/jpeg'})); }
      catch { cropStatus.textContent = 'Браузер не поддерживает подготовку файла. Выберите фото без кадрирования.'; apply.disabled = original.disabled = false; }
    },'image/jpeg',.9);
  });
  original.addEventListener('click', () => { if (pending) accept(pending); });
  dialog.querySelectorAll('[data-crop-cancel]').forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('close', () => { ++generation; cleanPending(); assign(accepted); showAccepted(); origin.focus(); });
  clear?.addEventListener('change', () => {
    ++generation; accepted = null; assign(null);
    if (acceptedUrl) URL.revokeObjectURL(acceptedUrl); acceptedUrl = '';
    showAccepted(); markDirty(); status.textContent = clear.checked ? 'Фото будет удалено после сохранения. Снимите галочку, чтобы оставить его.' : 'Текущее фото сохранится.';
  });
  reset.addEventListener('click', () => {
    ++generation; accepted = null; assign(null);
    if (acceptedUrl) URL.revokeObjectURL(acceptedUrl); acceptedUrl = '';
    if (clear) clear.checked = false;
    showAccepted(); status.textContent = preview.dataset.photoInitial ? 'Замена отменена. Текущее фото сохранится.' : 'Замена отменена. Можно выбрать другую фотографию.';
  });
  form.addEventListener('input', event => { if (event.target.name && event.target !== input) markDirty(); });
  form.addEventListener('change', event => { if (event.target.name && event.target !== input) markDirty(); });
  form.addEventListener('submit', () => { submitting = true; });
  window.addEventListener('beforeunload', event => { if (dirty && !submitting) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('pagehide', () => { if (acceptedUrl) URL.revokeObjectURL(acceptedUrl); cleanPending(); });
  const errors = document.getElementById('profile-error-summary');
  if (errors) errors.focus();
  showAccepted();
})();
