(() => {
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  document.querySelectorAll('[data-gallery]').forEach(root => {
    const slides=Array.from(root.querySelectorAll('[data-slide]'));
    if(!slides.length)return;
    const count=Math.max(1,Number(root.dataset.count)||1), pages=Math.ceil(slides.length/count);
    const delay=Number(root.dataset.autoplay)||0, label=root.querySelector('[data-position]'), pause=root.querySelector('[data-pause]');
    let page=0,timer=null,paused=reduced.matches,hovered=false,focused=false;
    function render(){slides.forEach((slide,i)=>slide.hidden=Math.floor(i/count)!==page);if(label)label.textContent=`${page+1} / ${pages}`;}
    function schedule(){clearInterval(timer);timer=null;if(delay&&pages>1&&!paused&&!hovered&&!focused&&!document.hidden)timer=setInterval(()=>{page=(page+1)%pages;render();},delay);if(pause){pause.textContent=paused?'Продолжить':'Пауза';pause.setAttribute('aria-label',paused?'Продолжить смену фотографий':'Приостановить смену фотографий');}}
    root.querySelector('[data-next]')?.addEventListener('click',()=>{page=(page+1)%pages;render();schedule();});
    root.querySelector('[data-prev]')?.addEventListener('click',()=>{page=(page-1+pages)%pages;render();schedule();});
    pause?.addEventListener('click',()=>{paused=!paused;schedule();});
    root.addEventListener('mouseenter',()=>{hovered=true;schedule();});root.addEventListener('mouseleave',()=>{hovered=false;schedule();});
    root.addEventListener('focusin',()=>{focused=true;schedule();});root.addEventListener('focusout',()=>{setTimeout(()=>{focused=root.contains(document.activeElement);schedule();},0);});
    document.addEventListener('visibilitychange',schedule);
    reduced.addEventListener('change',()=>{paused=reduced.matches;schedule();});render();schedule();
  });
})();
