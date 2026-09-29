/* Shuffle only the podium, once per page. Score and ranking remain unchanged. */
(() => {
  document.querySelectorAll('[data-podium]').forEach(place => {
    const list = place.querySelector('[data-ceremony-people]');
    const cards = Array.from(list.children);
    for (let i = cards.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [cards[i], cards[j]] = [cards[j], cards[i]];
    }
    cards.forEach(card => list.appendChild(card));
    if (cards.length <= 3) return;
    const controls = place.querySelector('.ceremony-controls');
    const status = controls.querySelector('[data-position]');
    let page = 0;
    const pages = Math.ceil(cards.length / 3);
    function show() {
      cards.forEach((card, index) => { card.hidden = Math.floor(index / 3) !== page; });
      const first = page * 3 + 1;
      const last = Math.min(page * 3 + 3, cards.length);
      list.dataset.visible = String(last - first + 1);
      status.textContent = `${first === last ? first : `${first}–${last}`} из ${cards.length}`;
    }
    function move(step) { page = (page + step + pages) % pages; show(); }
    controls.querySelector('[data-prev]').addEventListener('click', () => move(-1));
    controls.querySelector('[data-next]').addEventListener('click', () => move(1));
    let start = null;
    list.addEventListener('touchstart', event => { if (event.touches.length === 1) start = {x:event.touches[0].clientX,y:event.touches[0].clientY}; }, {passive:true});
    list.addEventListener('touchend', event => {
      if (!start || !event.changedTouches.length) return;
      const dx = event.changedTouches[0].clientX - start.x;
      const dy = event.changedTouches[0].clientY - start.y;
      if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.5) move(dx < 0 ? 1 : -1);
      start = null;
    }, {passive:true});
    list.addEventListener('touchcancel', () => { start = null; }, {passive:true});
    place.classList.add('is-carousel');
    controls.hidden = false;
    show();
  });
})();
