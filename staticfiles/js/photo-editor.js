(() => {
  'use strict';
  for (const input of document.querySelectorAll('input[type=file]:not([multiple])')) {
    if (!['photo','image','cover','cover_image','author_photo','quote_photo'].includes(input.name.split('-').pop())) continue;
    let applied=false;
    const hint=document.createElement('p');hint.className='photo-hint';hint.textContent='После выбора фотографии можно настроить кадр и масштаб.';input.after(hint);
    input.addEventListener('change',async()=>{
      if(applied){applied=false;return;}
      const file=input.files[0];if(!file||!file.type.startsWith('image/'))return;
      const url=URL.createObjectURL(file),img=new Image();img.src=url;
      try{await img.decode();}catch{URL.revokeObjectURL(url);hint.textContent='Изображение не удалось открыть. Выберите другой файл.';return;}
      const dialog=document.createElement('dialog');dialog.className='photo-editor';
      const title=document.createElement('h2');title.textContent='Выберите удачный кадр';
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=640;canvas.setAttribute('aria-label','Предпросмотр кадрирования');
      const ctx=canvas.getContext('2d');let ratio=input.name.includes('cover')?16/9:1,zoom=1,x=.5,y=.5;
      const help=document.createElement('p');help.textContent='Перемещайте фотографию мышью или пальцем. Ползунки доступны с клавиатуры.';
      const controls=document.createElement('div');controls.className='photo-controls';
      const source=()=>{
        const width=Math.min(img.naturalWidth,img.naturalHeight*ratio)/zoom;
        const height=width/ratio;
        return {width,height,left:(img.naturalWidth-width)*x,top:(img.naturalHeight-height)*y};
      };
      const draw=()=>{canvas.height=Math.round(canvas.width/ratio);const s=source();ctx.clearRect(0,0,canvas.width,canvas.height);ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(img,s.left,s.top,s.width,s.height,0,0,canvas.width,canvas.height);};
      const slider=(name,min,max,value,fn)=>{const label=document.createElement('label');label.textContent=name;const field=document.createElement('input');field.type='range';field.min=min;field.max=max;field.step='.01';field.value=value;field.addEventListener('input',()=>{fn(Number(field.value));draw();});label.append(field);controls.append(label);return field;};
      slider('Масштаб',1,4,1,v=>zoom=v);const sx=slider('По горизонтали',0,1,.5,v=>x=v),sy=slider('По вертикали',0,1,.5,v=>y=v);
      let drag=null;canvas.style.touchAction='none';canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,ox:x,oy:y};canvas.setPointerCapture(e.pointerId);});
      canvas.addEventListener('pointermove',e=>{if(!drag)return;const s=source(),rect=canvas.getBoundingClientRect();x=Math.max(0,Math.min(1,drag.ox-(e.clientX-drag.x)/rect.width*s.width/Math.max(1,img.naturalWidth-s.width)));y=Math.max(0,Math.min(1,drag.oy-(e.clientY-drag.y)/rect.height*s.height/Math.max(1,img.naturalHeight-s.height)));sx.value=x;sy.value=y;draw();});
      canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('pointercancel',()=>drag=null);
      const buttons=document.createElement('div');buttons.className='photo-buttons';
      const apply=document.createElement('button');apply.type='button';apply.textContent='Использовать этот кадр';
      const keep=document.createElement('button');keep.type='button';keep.textContent='Оставить оригинал';
      apply.addEventListener('click',()=>{
        apply.disabled=true;const s=source(),out=document.createElement('canvas');out.width=Math.max(1,Math.round(Math.min(input.name.includes('cover')?1600:1000,s.width)));out.height=Math.max(1,Math.round(out.width/ratio));
        const outctx=out.getContext('2d');outctx.imageSmoothingQuality='high';outctx.drawImage(img,s.left,s.top,s.width,s.height,0,0,out.width,out.height);
        out.toBlob(blob=>{if(!blob){apply.disabled=false;return;}try{const data=new DataTransfer();data.items.add(new File([blob],file.name.replace(/\.[^.]+$/,'')+'-crop.png',{type:'image/png'}));input.files=data.files;applied=true;input.dispatchEvent(new Event('change',{bubbles:true}));hint.textContent=`Кадр подготовлен: ${out.width} × ${out.height}. Сохраните форму, чтобы применить фотографию.`;dialog.close();}catch{hint.textContent='Браузер не поддерживает замену файла. Будет использован оригинал.';dialog.close();}},'image/png');
      });
      keep.addEventListener('click',()=>dialog.close());buttons.append(apply,keep);dialog.append(title,help,canvas,controls,buttons);document.body.append(dialog);
      dialog.addEventListener('close',()=>{URL.revokeObjectURL(url);dialog.remove();input.focus();},{once:true});dialog.showModal();draw();
    });
  }
})();
