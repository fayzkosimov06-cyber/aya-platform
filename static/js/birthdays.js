(()=>{'use strict';
 document.querySelectorAll('[data-phone-url]').forEach(button=>button.addEventListener('click',async()=>{
  button.disabled=true;const status=button.nextElementSibling;status.textContent='Открываем…';
  try{const response=await fetch(button.dataset.phoneUrl,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':button.dataset.csrf}});if(!response.ok)throw Error();const data=await response.json();const link=document.createElement('a');link.textContent=data.phone;link.href='tel:'+data.phone.replace(/[^+0-9]/g,'');status.replaceChildren(link);button.remove();}catch(e){status.textContent='Не удалось открыть номер. Попробуйте ещё раз.';button.disabled=false;}
 }));
 const dialog=document.getElementById('birthday-greeting');if(!dialog)return;let lastFocus=null;
 const open=()=>{lastFocus=document.activeElement;dialog.showModal();const sparks=dialog.querySelector('.birthday-sparks');sparks.replaceChildren();if(!matchMedia('(prefers-reduced-motion: reduce)').matches){for(let i=0;i<40;i++){const piece=document.createElement('i');piece.style.setProperty('--x',(Math.random()*100)+'%');piece.style.setProperty('--delay',(Math.random()*1.5)+'s');piece.style.setProperty('--color',['#ffdb85','#8be0ed','#ffafbe'][i%3]);sparks.append(piece);}}fetch(dialog.dataset.seen,{method:'POST',credentials:'same-origin',headers:{'X-CSRFToken':dialog.dataset.csrf}}).catch(()=>{});};
 dialog.querySelectorAll('[data-birthday-close]').forEach(button=>button.addEventListener('click',()=>dialog.close()));dialog.addEventListener('close',()=>lastFocus?.focus());document.querySelectorAll('[data-birthday-open]').forEach(button=>button.addEventListener('click',open));if(dialog.dataset.auto==='yes')open();
})();
