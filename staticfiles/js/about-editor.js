(() => {
 document.querySelectorAll('[data-confirm]').forEach(button=>button.addEventListener('click',event=>{if(!confirm(button.dataset.confirm))event.preventDefault();}));
 const source=document.getElementById('id_source');function numberMode(){const row=document.querySelector('[data-field="number"]');if(row&&source)row.hidden=source.value!=='manual';}source?.addEventListener('change',numberMode);numberMode();
 const platform=document.getElementById('id_platform'),privateInput=document.getElementById('id_requires_volunteer_access');function privacy(){if(!platform||!privateInput)return;const p=platform.value;const fixed=['instagram','facebook','telegram'].includes(p);if(fixed)privateInput.checked=p==='telegram';const row=document.querySelector('[data-field="requires_volunteer_access"]');row.hidden=fixed;}platform?.addEventListener('change',privacy);privacy();
})();
