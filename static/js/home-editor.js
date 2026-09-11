(() => {
  document.querySelectorAll('[data-confirm]').forEach(button => button.addEventListener('click', event => {if (!confirm(button.dataset.confirm)) event.preventDefault();}));
  const input=document.querySelector('[data-previews]');let urls=[];
  input?.addEventListener('change',()=>{urls.forEach(URL.revokeObjectURL);urls=[];const box=document.getElementById(input.dataset.previews);box.replaceChildren();for(const file of input.files){if(!file.type.startsWith('image/'))continue;const img=document.createElement('img');const url=URL.createObjectURL(file);urls.push(url);img.src=url;img.alt=file.name;box.append(img);}});
  const type=document.getElementById('id_author_type');
  function change(){const member=type?.value==='member';document.querySelectorAll('#quote-form [data-field]').forEach(row=>{const name=row.dataset.field;row.hidden=(name==='member'&&!member)||(['author_name','source_url'].includes(name)&&member);});}
  type?.addEventListener('change',change);change();
})();
