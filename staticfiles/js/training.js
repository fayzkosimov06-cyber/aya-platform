/* Account progress is authoritative. No clicks/submissions on application controls. */
(() => {
  'use strict';
  const config = document.getElementById('aya-training-config');
  if (!config || typeof HTMLDialogElement === 'undefined') return;
  const cfg = config.dataset;
  let version, catalog, states, active, dialog, panel, target, busy = false, generation = 0;
  let restoreMenu = () => {}, restoreScroll = '', restorePadding = '', oldFocus, shades = [], ring;
  let helpFilter='all';
  const groupLabels={basics:'Начало работы',community:'Участие и команды',work:'Мои рабочие задачи'};
  const mutedKey = `aya-tour-muted:${cfg.user}`;
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  function muted(value) {
    try {
      if (value) sessionStorage.setItem(mutedKey, '1');
      return sessionStorage.getItem(mutedKey) === '1';
    } catch (_) { return false; }
  }
  async function api(data) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(cfg.endpoint, {
        credentials: 'same-origin', signal: controller.signal,
        ...(data ? {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRFToken':cfg.csrf}, body:JSON.stringify(data)} : {})
      });
      if (!response.ok) throw new Error(response.status === 409 ? 'Прогресс изменился в другой вкладке. Обновите страницу помощи.' : 'Не удалось сохранить прогресс. Проверьте соединение и повторите.');
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  async function save(topic, action) {
    const result = await api({topic, action, version, revision:states[topic]?.revision ?? null});
    states[topic] = result.state;
    catalog[topic] = result.topic;
    return result.state;
  }
  function button(text, callback, primary = false) {
    const b = el('button', text, primary ? 'aya-tour-primary' : '');
    b.type = 'button';
    b.addEventListener('click', callback);
    return b;
  }
  function error(message) {
    const status = panel?.querySelector('[role="status"]') || document.getElementById('aya-help-status');
    if (status) status.textContent = message;
  }
  function nextTopic(exclude) {
    const available=Object.entries(catalog || {}).filter(([id])=>id!==exclude && !(states[id]?.status==='completed' && states[id]?.version===version));
    return available.sort(([a,ta],[b,tb])=>{
      const resume=id=>['in_progress','deferred'].includes(states[id]?.status) && states[id].version===version;
      return Number(resume(b))-Number(resume(a)) || (tb.priority||0)-(ta.priority||0);
    })[0];
  }
  function notice(message, title='Прогресс сохранён', next=null) {
    document.querySelector('.aya-tour-notice')?.remove();
    const node=el('section','','aya-tour-notice');node.setAttribute('aria-label',title);
    const icon=el('span','✓','aya-notice-icon');icon.setAttribute('aria-hidden','true');
    const copy=el('div','','aya-notice-copy'), announcement=el('div');announcement.setAttribute('role','status');
    announcement.append(el('strong',title),el('p',message));copy.append(announcement);
    const actions=el('div','','aya-notice-actions');
    if(next){
      const [id,topic]=next, resume=['in_progress','deferred'].includes(states[id]?.status)&&states[id].version===version;
      copy.append(el('small',`Далее: ${topic.title}`));
      actions.append(button('Следующая тема',()=>action(resume?'resume':'start',id),true));
    }
    const link=el('a','Все инструкции');link.href=cfg.help;actions.append(link);copy.append(actions);
    const dismiss=button('×',()=>node.remove());dismiss.className='aya-notice-close';dismiss.setAttribute('aria-label','Закрыть сообщение');
    node.append(icon,copy,dismiss);document.body.append(node);
  }
  function clearParameter() {
    const url = new URL(location.href); url.searchParams.delete('aya_tour');
    history.replaceState(null, '', url);
  }
  function teardown() {
    generation++; restoreMenu(); restoreMenu = () => {};
    window.removeEventListener('resize', position);
    window.removeEventListener('scroll', position, true);
    if (dialog) {
      dialog.close(); dialog.remove(); document.body.style.overflow = restoreScroll;
      document.body.style.paddingBottom = restorePadding;
    }
    dialog = panel = target = null;
    if (oldFocus?.isConnected) oldFocus.focus({preventScroll:true});
  }
  async function close() {
    const topic = active;
    muted(true); teardown(); active = null; clearParameter();
    if (topic) {
      try { await save(topic, 'defer'); renderHelp(); }
      catch (_) { notice('Не удалось сохранить паузу. Последний сохранённый шаг доступен в помощи.'); }
    }
  }
  function openDialog() {
    if (dialog) return;
    oldFocus = document.activeElement; restoreScroll = document.body.style.overflow;
    restorePadding = document.body.style.paddingBottom;
    document.body.style.paddingBottom = `${(parseFloat(getComputedStyle(document.body).paddingBottom) || 0)+window.innerHeight}px`;
    document.body.style.overflow = 'hidden';
    dialog = el('dialog', '', 'aya-tour'); dialog.setAttribute('aria-labelledby', 'aya-tour-title');
    dialog.setAttribute('aria-describedby', 'aya-tour-text');
    shades = Array.from({length:4}, () => el('div', '', 'aya-tour-shade'));
    shades.forEach(n => n.setAttribute('aria-hidden', 'true'));
    ring = el('div', '', 'aya-tour-ring'); ring.setAttribute('aria-hidden','true');
    panel = el('section', '', 'aya-tour-panel'); panel.tabIndex = -1;
    dialog.append(...shades, ring, panel); document.body.append(dialog);
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('keydown', event => {
      if (event.key !== 'Tab') return;
      const nodes = [...panel.querySelectorAll('button:not(:disabled), a[href]')];
      if (!nodes.length) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === nodes[0] || document.activeElement === panel)) {event.preventDefault(); nodes.at(-1).focus();}
      else if (!event.shiftKey && document.activeElement === nodes.at(-1)) {event.preventDefault(); nodes[0].focus();}
    });
    dialog.showModal();
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
  }
  function rect(node, x, y, width, height) {
    Object.assign(node.style, {left:`${x}px`, top:`${y}px`, width:`${Math.max(0,width)}px`, height:`${Math.max(0,height)}px`});
  }
  function position() {
    if (!panel) return;
    const w = window.innerWidth, h = window.innerHeight, gap = 12;
    const pw = panel.offsetWidth, ph = panel.offsetHeight;
    const nav = document.getElementById('navbarNav');
    const toggle = document.querySelector('[data-bs-target="#navbarNav"]');
    if (target && nav?.contains(target) && toggle?.getClientRects().length) {
      // Reserve space for the card even when the expanded mobile menu is tall.
      const available = Math.max(70, h-ph-nav.getBoundingClientRect().top-3*gap);
      nav.style.maxHeight = `${available}px`; nav.style.overflowY = 'auto';
      const nr = nav.getBoundingClientRect(), tr = target.getBoundingClientRect();
      nav.scrollTop += tr.top - nr.top - (available-tr.height)/2;
    }
    let r = target?.getBoundingClientRect();
    if (r && (r.width < 1 || r.height < 1)) r = null;
    let x = (w-pw)/2, y = (h-ph)/2;
    if (r) {
      x = Math.max(gap, Math.min(w-pw-gap, r.left));
      if (r.bottom + ph + 2*gap <= h) y = r.bottom + gap;
      else if (r.top - ph - gap >= gap) y = r.top-ph-gap;
      else if (r.right + pw + 2*gap <= w) {x = r.right+gap; y = Math.max(gap,Math.min(h-ph-gap,r.top));}
      else {y = h-ph-gap;}
    }
    if (w <= 600 && r) y = h-ph-gap;
    panel.style.left = `${Math.max(gap,x)}px`; panel.style.top = `${Math.max(gap,y)}px`;
    let left=0, top=0, right=0, bottom=0;
    if (r) {
      left=Math.max(4,r.left-5);right=Math.min(w-4,r.right+5);
      top=Math.max(4,r.top-5);bottom=Math.min(h-4,r.bottom+5);
      // If a large target cannot fit, highlight its visible part above/below the card.
      if (left < x+pw && right > x && top < y+ph && bottom > y) {
        if (top < y) bottom=Math.min(bottom,y-gap); else top=Math.max(top,y+ph+gap);
      }
      if (bottom <= top || right <= left) r=null;
    }
    ring.hidden = !r;
    if (!r) {rect(shades[0],0,0,w,h); shades.slice(1).forEach(n=>rect(n,0,0,0,0)); return;}
    rect(ring,left,top,right-left,bottom-top);
    rect(shades[0],0,0,w,top);rect(shades[1],0,bottom,w,h-bottom);
    rect(shades[2],0,top,left,bottom-top);rect(shades[3],right,top,w-right,bottom-top);
  }
  function reveal(node) {
    restoreMenu(); restoreMenu = () => {};
    const nav = document.getElementById('navbarNav');
    const toggle = document.querySelector('[data-bs-target="#navbarNav"]');
    if (node && nav?.contains(node)) {
      const expanded = toggle?.getAttribute('aria-expanded');
      const wasOpen = nav.classList.contains('show'), height = nav.style.maxHeight, overflow = nav.style.overflowY;
      if (getComputedStyle(nav).display === 'none') {nav.classList.add('show'); toggle?.setAttribute('aria-expanded','true');}
      restoreMenu = () => {
        if (!wasOpen) nav.classList.remove('show');
        nav.style.maxHeight=height;nav.style.overflowY=overflow;
        if (toggle) toggle.setAttribute('aria-expanded', expanded || 'false');
      };
    }
  }
  function renderPanel(title, text, progress) {
    openDialog(); panel.replaceChildren();
    const heading = el('h2', title); heading.id = 'aya-tour-title';
    const copy = el('p', text); copy.id = 'aya-tour-text';
    const status = el('p', '', 'aya-tour-error'); status.setAttribute('role','status');
    panel.append(el('div', progress, 'aya-tour-progress'), heading, copy, status);
  }
  async function action(command, topic = active) {
    if (busy) return;
    document.querySelector('.aya-tour-notice')?.remove();
    busy = true; const epoch = generation;
    panel?.querySelectorAll('button:not(.aya-tour-later)').forEach(b=>b.disabled=true);
    try {
      const state = await save(topic, command);
      if (epoch !== generation) return;
      active = topic;
      if (state.status === 'completed') {
        teardown(); active=null; clearParameter();renderHelp();
        notice(`«${catalog[topic].title}» — готово. Теперь можно попробовать самостоятельно или выбрать другую инструкцию.`,'Тема пройдена',nextTopic(topic));
      } else go();
    } catch (e) { if (epoch === generation) {error(e.message);if(!panel&&!document.getElementById('aya-help-status'))notice(e.message,'Не удалось открыть тему');} }
    finally {busy=false;panel?.querySelectorAll('button').forEach(b=>b.disabled=false);}
  }
  function go() {
    const state = states[active], topic = catalog[active];
    const item = topic.steps[Math.min(state.step,topic.steps.length-1)];
    const destination = new URL(item.url, location.origin);
    destination.searchParams.set('aya_tour', active);
    const current=new URL(location.href);current.searchParams.delete('aya_tour');
    const desired=new URL(destination);desired.searchParams.delete('aya_tour');
    if (current.pathname !== desired.pathname || current.search !== desired.search) { location.assign(destination); return; }
    history.replaceState(null, '', destination);
    showStep(item, state.step, topic);
  }
  function showStep(item, index, topic) {
    target = document.querySelector(`[data-tour="${item.target}"]`);
    reveal(target);
    if (target && !target.getClientRects().length) target = null;
    renderPanel(item.title, (!target && item.fallback) || item.text, `${topic.title} · ${index+1} из ${topic.steps.length}`);
    const meter=el('div','','aya-tour-meter');meter.setAttribute('aria-hidden','true');const fill=el('span');fill.style.width=`${(index+1)/topic.steps.length*100}%`;meter.append(fill);panel.prepend(meter);
    const actions = el('div','','aya-tour-actions');
    if (index > 0) actions.append(button('Назад',()=>action('back')));
    actions.append(button(index+1 === topic.steps.length ? 'Завершить' : 'Далее',()=>action('next'),true));
    panel.append(actions, button('Продолжить позже',close)); panel.lastChild.classList.add('aya-tour-later');
    if (target) {
      target.scrollIntoView({block:window.innerWidth <= 600 ? 'start' : 'center',behavior:'instant'});
      if (window.innerWidth <= 600 && !target.closest('#navbarNav')) {
        const header = document.querySelector('.main-navbar');
        window.scrollBy({top:-(Math.min(header?.offsetHeight || 80,120)+20),behavior:'instant'});
      }
    }
    position(); panel.focus({preventScroll:true});
    requestAnimationFrame(position);
  }
  function welcome() {
    active='main'; target=null;
    renderPanel('Добро пожаловать в AYA!', 'Покажем, как заполнить профиль, найти мероприятие и посмотреть свои результаты.', 'ВАШЕ ЗНАКОМСТВО С AYA');
    const actions=el('div','','aya-tour-actions');
    actions.append(button('Начать знакомство',()=>action('start'),true),button('Позже',close));
    panel.append(actions);position();panel.focus({preventScroll:true});
  }
  function renderHelp() {
    const grid = document.getElementById('aya-help-topics'); if (!grid) return;
    grid.replaceChildren();document.getElementById('aya-help-status').textContent='';
    const entries=Object.entries(catalog), done=id=>states[id]?.status==='completed'&&states[id].version===version;
    const resumable=id=>['in_progress','deferred'].includes(states[id]?.status)&&states[id].version===version;
    const completed=entries.filter(([id])=>done(id)).length, progress=document.getElementById('aya-help-progress');
    progress.replaceChildren();const circle=el('div','','aya-help-progress-ring');circle.style.setProperty('--progress',`${completed/entries.length*100}%`);circle.append(el('strong',`${completed}/${entries.length}`));
    const text=el('div');text.append(el('strong',completed===entries.length?'Все темы пройдены':'Ваш прогресс'),el('p','Можно продолжить в любой момент'));progress.append(circle,text);
    const next=document.getElementById('aya-help-next'), suggested=nextTopic();next.replaceChildren();next.hidden=!suggested;
    if(suggested){const [id,topic]=suggested, copy=el('div');copy.append(el('small',resumable(id)?'ПРОДОЛЖИТЬ С ТОГО ЖЕ МЕСТА':'РЕКОМЕНДУЕМ ДЛЯ ВАС'),el('h2',topic.title),el('p',topic.description));next.append(copy,button(resumable(id)?'Продолжить →':'Показать шаги →',()=>action(resumable(id)?'resume':'start',id),true));}
    const filters=document.getElementById('aya-help-filters');filters.replaceChildren();
    const groups=new Set(entries.map(([,t])=>t.group));
    for(const [id,label] of [['all','Все темы'],...Object.entries(groupLabels).filter(([key])=>groups.has(key)),['completed','Пройденные']]){
      const item=button(label,()=>{helpFilter=id;renderHelp();document.querySelector(`#aya-help-filters [data-filter="${id}"]`)?.focus({preventScroll:true});});item.dataset.filter=id;item.setAttribute('aria-pressed',String(id===helpFilter));filters.append(item);
    }
    const query=document.getElementById('aya-help-search').value.trim().toLocaleLowerCase();let shown=0;
    entries.forEach(([id,topic])=>{
      if(helpFilter==='completed'?!done(id):helpFilter!=='all'&&topic.group!==helpFilter)return;
      if(query&&!`${topic.title} ${topic.description} ${topic.steps.map(s=>s.title+' '+s.text).join(' ')}`.toLocaleLowerCase().includes(query))return;
      shown++;
      const state=states[id], card=el('article','','aya-help-card');card.dataset.topic=id;
      const meta=el('div','','aya-help-card-meta');meta.append(el('span',groupLabels[topic.group]||'Начало работы','aya-help-category'),el('span',`≈ ${topic.minutes||1} мин`));
      card.append(meta,el('h3',topic.title),el('p',topic.description));
      const badge=el('small',done(id)?'✓ Пройдено':resumable(id)?`Продолжить с шага ${state.step+1}`:`Шагов: ${topic.steps.length}`,'aya-help-state');card.append(badge);
      if(done(id))card.classList.add('is-complete');
      const actions=el('div','','aya-help-actions');
      if(resumable(id))actions.append(button('Продолжить',()=>action('resume',id),true));
      actions.append(button(done(id)?'Повторить':resumable(id)?'Сначала':'Показать шаги',()=>action('start',id),!actions.children.length&&!done(id)));
      card.append(actions);grid.append(card);
    });
    if(!shown){const empty=el('div','','aya-help-empty');empty.append(el('h3','Пока нет подходящих тем'),el('p','Попробуйте другое слово или откройте все инструкции.'),button('Показать все',()=>{helpFilter='all';document.getElementById('aya-help-search').value='';renderHelp();}));grid.append(empty);}
  }
  document.getElementById('aya-help-search')?.addEventListener('input',()=>{if(catalog)renderHelp();});
  api().then(data=>{
    version=data.version;catalog=data.topics;states=data.states;renderHelp();
    const requested=new URL(location.href).searchParams.get('aya_tour');
    if (requested && catalog[requested] && states[requested]?.status === 'in_progress') {active=requested;go();}
    else if (!requested && cfg.page === 'home' && states.main?.status === 'not_started' && !muted() && !document.getElementById('birthday-greeting')) welcome();
  }).catch(()=>{
    const status=document.getElementById('aya-help-status');
    if (status) status.textContent='Не удалось загрузить обучение. Обновите страницу, чтобы повторить. Остальные функции сайта доступны.';
  });
  window.addEventListener('pagehide',teardown);
})();
