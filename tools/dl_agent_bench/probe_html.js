// probe_html.js - load a single-file HTML game headlessly and play it with random keys.
//
//     node probe_html.js page.html [seconds=30] [seed=1]
//
// Every inline <script> runs against stub browser APIs (DOM, canvas, WebAudio, timers, requestAnimationFrame).
// Frames are 16 ms of simulated time; a random game key is pressed every 5 frames.  Prints one JSON line:
// {"ok": bool, "frames": n, "keys": n, "error": "..."} - ok means nothing threw.
'use strict';
const fs = require('fs');
const vm = require('vm');

const [file, secs = '30', seedArg = '1'] = process.argv.slice(2);
const html = fs.readFileSync(file, 'utf8');
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);

// A value that is every object at once: any property is itself, calling it returns itself, it converts to 0.
function anything() {
  const target = function () {};
  const store = {};
  const p = new Proxy(target, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => 0;
      if (k === 'then') return undefined;               // not a promise
      if (k in store) return store[k];
      return p;
    },
    set(t, k, v) { store[k] = v; return true; },
    apply() { return p; },
    construct() { return anything(); },
    has() { return true; },
  });
  return p;
}

const listeners = {};
const on = (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); };
const off = (type, fn) => { listeners[type] = (listeners[type] || []).filter(f => f !== fn); };
let now = 0;
const raf = [];
const timers = [];
let timerId = 0;

function element(tag) {
  const el = anything();
  el.tagName = (tag || 'div').toUpperCase();
  el.style = {};
  el.dataset = {};
  el.width = 300; el.height = 600;
  el.textContent = ''; el.innerHTML = ''; el.innerText = ''; el.value = '';
  el.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  el.addEventListener = on; el.removeEventListener = off;
  el.getContext = () => anything();
  el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 600, right: 300, bottom: 600 });
  el.appendChild = c => c; el.removeChild = c => c; el.append = () => {}; el.prepend = () => {}; el.remove = () => {};
  el.querySelector = () => element(); el.querySelectorAll = () => [];
  el.setAttribute = () => {}; el.getAttribute = () => null; el.focus = () => {};
  return el;
}

const byId = {};
const document = {
  getElementById: id => (byId[id] = byId[id] || element('canvas')),
  querySelector: () => element('canvas'), querySelectorAll: () => [],
  getElementsByTagName: () => [element('canvas')], getElementsByClassName: () => [],
  createElement: element, createTextNode: () => element('text'),
  addEventListener: on, removeEventListener: off,
  body: element('body'), documentElement: element('html'), head: element('head'),
  hidden: false, visibilityState: 'visible', readyState: 'complete',
};

const sandbox = {
  document, console: { log() {}, info() {}, warn() {}, error() {}, debug() {} },
  addEventListener: on, removeEventListener: off,
  requestAnimationFrame: fn => { raf.push(fn); return raf.length; }, cancelAnimationFrame: () => {},
  setTimeout: (fn, ms = 0) => { timers.push({ id: ++timerId, fn, at: now + ms, every: 0 }); return timerId; },
  setInterval: (fn, ms = 0) => { timers.push({ id: ++timerId, fn, at: now + ms, every: Math.max(1, ms) }); return timerId; },
  clearTimeout: id => { const i = timers.findIndex(t => t.id === id); if (i >= 0) timers.splice(i, 1); },
  performance: { now: () => now }, Date,
  AudioContext: function () { return anything(); }, webkitAudioContext: function () { return anything(); },
  Audio: function () { return anything(); }, Image: function () { return element('img'); },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  innerWidth: 1280, innerHeight: 800, devicePixelRatio: 1,
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  navigator: { userAgent: 'probe' }, location: { href: 'file:///probe/index.html', protocol: 'file:', host: '',
    hostname: '', pathname: '/probe/index.html', search: '', hash: '', origin: 'null', reload() {}, assign() {}, replace() {} },
  URLSearchParams, URL,
  alert() {}, confirm: () => true, prompt: () => null, focus() {},
};
sandbox.clearInterval = sandbox.clearTimeout;
sandbox.window = sandbox; sandbox.self = sandbox; sandbox.globalThis = sandbox;
document.defaultView = sandbox;
vm.createContext(sandbox);

let seed = Number(seedArg) >>> 0 || 1;
const rand = () => { seed ^= seed << 13; seed >>>= 0; seed ^= seed >>> 17; seed ^= seed << 5; seed >>>= 0; return seed / 4294967296; };
const KEYS = [['ArrowLeft', 'ArrowLeft', 37], ['ArrowRight', 'ArrowRight', 39], ['ArrowUp', 'ArrowUp', 38],
  ['ArrowDown', 'ArrowDown', 40], ['KeyA', 'a', 65], ['KeyD', 'd', 68], ['KeyW', 'w', 87], ['KeyS', 's', 83],
  ['Space', ' ', 32]];
const fire = (type, ev) => { for (const fn of [...(listeners[type] || [])]) fn.call(sandbox, ev); };
const keyEvent = ([code, key, keyCode]) => ({ code, key, keyCode, which: keyCode, repeat: false, ctrlKey: false,
  metaKey: false, altKey: false, shiftKey: false, preventDefault() {}, stopPropagation() {}, target: document.body });

let frames = 0, keys = 0;
const out = r => { process.stdout.write(JSON.stringify(r) + '\n'); };
try {
  for (const s of scripts) vm.runInContext(s, sandbox, { filename: file, timeout: 5000 });
  fire('DOMContentLoaded', {}); fire('load', {});
  const total = Math.round(Number(secs) * 1000 / 16);
  for (frames = 0; frames < total; frames++) {
    now += 16;
    for (const t of [...timers]) {
      if (t.at > now) continue;
      if (t.every) t.at += t.every; else timers.splice(timers.indexOf(t), 1);
      t.fn();
    }
    const cbs = raf.splice(0);
    for (const fn of cbs) fn(now);
    if (frames % 5 === 0) {
      const k = KEYS[Math.floor(rand() * KEYS.length)];
      fire('keydown', keyEvent(k)); fire('keyup', keyEvent(k)); keys++;
    }
  }
  out({ ok: true, frames, keys, scripts: scripts.length });
} catch (e) {
  out({ ok: false, frames, keys, scripts: scripts.length, error: String(e && e.stack || e).split('\n').slice(0, 3).join(' | ') });
}
