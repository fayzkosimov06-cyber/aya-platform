/* Use the current browser secret after login in another tab or back/forward restore. */
(() => {
  'use strict';
  const cookieName = document.querySelector('meta[name="aya-csrf-cookie"]')?.content || 'csrftoken';
  function token() {
    const prefix = cookieName + '=';
    const item = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith(prefix));
    if (item) {
      try { return decodeURIComponent(item.slice(prefix.length)); } catch (_) { return ''; }
    }
    return document.querySelector('meta[name="aya-csrf-token"]')?.content || '';
  }
  function internal(url) {
    try { return new URL(url, location.href).origin === location.origin; } catch (_) { return false; }
  }
  function syncForm(form, submitter) {
    if (!(form instanceof HTMLFormElement)) return;
    const method = submitter?.getAttribute('formmethod') || form.method;
    const action = submitter?.hasAttribute('formaction') ? submitter.formAction : form.action;
    if (method.toLowerCase() !== 'post' || !internal(action)) return;
    const current = token();
    if (!current) return;
    let field = form.querySelector('input[name="csrfmiddlewaretoken"]');
    if (!field) {
      field = document.createElement('input'); field.type = 'hidden'; field.name = 'csrfmiddlewaretoken'; form.append(field);
    }
    field.value = current;
  }
  function syncForms() { document.querySelectorAll('form').forEach(form => syncForm(form)); }
  function request(url, options = {}) {
    if (!internal(url)) return Promise.reject(new TypeError('AYA requests must stay on this site.'));
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    let body = options.body;
    if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes((options.method || 'GET').toUpperCase())) {
      const current = token();
      if (current) headers.set('X-CSRFToken', current);
      // Django checks a form body before its header, so remove obsolete body values too.
      if (body instanceof URLSearchParams) {
        body = new URLSearchParams(body); body.delete('csrfmiddlewaretoken');
      } else if (body instanceof FormData) {
        body = new FormData(); options.body.forEach((value, key) => { if (key !== 'csrfmiddlewaretoken') body.append(key, value); });
      }
    }
    return fetch(url, {...options, body, headers, credentials: 'same-origin', mode: 'same-origin'});
  }
  async function errorMessage(response, fallback) {
    if (response.headers.get('X-AYA-Error') === 'csrf') {
      try { return (await response.json()).message + ' Обновите страницу и повторите действие.'; } catch (_) { /* Use fallback. */ }
    }
    return fallback;
  }
  window.AyaCSRF = Object.freeze({token, fetch: request, errorMessage});
  document.addEventListener('submit', event => syncForm(event.target, event.submitter), true);
  window.addEventListener('pageshow', syncForms);
  window.addEventListener('focus', syncForms);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) syncForms(); });
  syncForms();
})();
