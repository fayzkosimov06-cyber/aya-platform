/* Browser request lifecycle tests, with no dependencies or real accounts. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function browser() {
  const listeners = {}, events = {}, calls = [], forms = [];
  class Form {
    constructor(action = '/profile/edit/', method = 'post', field = {value: 'stale'}) { this.action = action; this.method = method; this.field = field; }
    querySelector() { return this.field; }
    append(field) { this.field = field; }
  }
  const document = {
    cookie: 'csrftoken=current', hidden: false,
    querySelector(selector) { return {content: selector.includes('cookie') ? 'csrftoken' : 'rendered'}; },
    querySelectorAll() { return forms; },
    createElement() { return {}; },
    addEventListener(type, handler) { listeners[type] = handler; },
  };
  const window = {addEventListener(type, handler) { events[type] = handler; }};
  const context = {document, window, HTMLFormElement:Form, location:{href:'https://aya.test/help/', origin:'https://aya.test'}, URL, URLSearchParams, Headers, FormData,
    fetch:async (url, options) => { calls.push({url, ...options}); return new Response('{}'); }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/js/csrf.js'), 'utf8'), context);
  return {document, api:window.AyaCSRF, forms, Form, listeners, events, calls};
}

test('form opened before login uses the new cookie immediately before submit', () => {
  const b = browser(), form = new b.Form();
  b.document.cookie = 'csrftoken=rotated-after-login';
  b.listeners.submit({target:form});
  assert.equal(form.field.value, 'rotated-after-login');
});

test('restored pages and tab focus update hidden fields without submitting anything', () => {
  const b = browser(), form = new b.Form(); b.forms.push(form);
  b.document.cookie = 'csrftoken=after-pageshow'; b.events.pageshow();
  assert.equal(form.field.value, 'after-pageshow');
  b.document.cookie = 'csrftoken=after-focus'; b.events.focus();
  assert.equal(form.field.value, 'after-focus');
  assert.equal(b.calls.length, 0);
});

test('external forms, GET forms and external submit buttons never receive the cookie', () => {
  const b = browser();
  for (const form of [new b.Form('https://elsewhere.test/'), new b.Form('/search/', 'get')]) {
    b.listeners.submit({target:form}); assert.equal(form.field.value, 'stale');
  }
  const form = new b.Form();
  const submitter = {formAction:'https://elsewhere.test/', getAttribute:() => null, hasAttribute:name => name === 'formaction'};
  b.listeners.submit({target:form, submitter}); assert.equal(form.field.value, 'stale');
});

test('search and JSON requests replace cached headers and remove old form-body tokens', async () => {
  const b = browser(); const body = new URLSearchParams({query:'ecology', csrfmiddlewaretoken:'stale-body'});
  await b.api.fetch('/activity/search/', {method:'POST', headers:{'X-CSRFToken':'stale-header'}, body});
  assert.equal(b.calls[0].headers.get('X-CSRFToken'), 'current');
  assert.equal(b.calls[0].body.get('csrfmiddlewaretoken'), null);
  assert.equal(b.calls[0].body.get('query'), 'ecology');
  assert.equal(body.get('csrfmiddlewaretoken'), 'stale-body');
  b.document.cookie = 'csrftoken=new-current';
  await b.api.fetch('/help/progress/', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{"topic":"intro"}'});
  assert.equal(b.calls[1].headers.get('X-CSRFToken'), 'new-current');
  assert.equal(b.calls[1].body, '{"topic":"intro"}');
});

test('multipart uploads keep their fields and binary files', async () => {
  const b = browser(), body = new FormData();
  body.append('csrfmiddlewaretoken', 'old'); body.append('title', 'Portrait'); body.append('photo', new Blob(['image-data']), 'portrait.png');
  await b.api.fetch('/profile/edit/', {method:'POST', body});
  assert.equal(b.calls[0].body.get('csrfmiddlewaretoken'), null);
  assert.equal(b.calls[0].body.get('title'), 'Portrait');
  assert.equal(await b.calls[0].body.get('photo').text(), 'image-data');
  assert.equal(body.get('csrfmiddlewaretoken'), 'old');
});

test('requests cannot leak a token to another origin and no request is automatically replayed', async () => {
  const b = browser();
  await assert.rejects(b.api.fetch('https://elsewhere.test/collect', {method:'POST'}));
  assert.equal(b.calls.length, 0);
  await b.api.fetch('/people/1/phone/', {method:'POST'});
  assert.equal(b.calls.length, 1);
  assert.equal(b.calls[0].credentials, 'same-origin');
  assert.equal(b.calls[0].mode, 'same-origin');
});
