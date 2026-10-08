/*
 * fly-paradise v0.3.6 desktop adult motion, MIT (package declaration).
 * Package author field: desktop-fly-pet. See NOTICE.md.
 * Source: https://github.com/pyd021226/fly-paradise
 * Commit: 9c6130681c1a112c3c7faaafbad6d335cc0a1c36
 * overlay.js SHA256: dcfe5153feff4b5bfd47ad5fdde63cf5da337cbf286bb41ba0cb0562c7f2ac95
 * Original function bodies below are copied byte-for-byte. Host adaptation is
 * isolated after END UPSTREAM FUNCTIONS. No DOM, IPC, input hooks or saves.
 */
(function () {
'use strict';
let simulationTime = 0;
const performance = { now: () => simulationTime };
let W = 1, H = 1, fast = false, breed = false;
let swatterOn = false, netOn = false;
let mouse = {x: -1e9, y: -1e9, vx: 0, vy: 0, spd: 0};
let screens = [], icons = [], flies = [], foods = [], corpses = [];
let eggs = [], larvae = [], pupae = [], shells = [];
let nextId = 1;
const FLY_HIT = 11;
const MAX_ADULTS = 48;
const MAX_EGGS = 240;
const MAX_LARVAE = 160;
const MAX_PUPAE = 96;
const MAX_SHELLS = 240;
const MAX_SPLATS = 400;
const MAX_FOOD = 8;
const ADULT_LEN = 18;
const MATE_MS = 8000;
const EGG_MS = 30000;
const PUPA_MS = 120000;
const RESPAWN_MIN = 120;
const RESPAWN_MAX = 300;
const NOTICE_RANGE = 220;
const RAG_R = 36;
const FOOD_SLOTS = 6;
const BIN_SLOTS = 8;
const PUPA_CAP = 2;
const PUPA_CELL = 2;
const PUPA_RX = 9 * 0.8;
const PUPA_RY = 3.6 * 0.8;
const LAUNCH_MS = 30 * 60 * 1000;
const FOOD_SUPPLY = 360;
const EAT_NEED = 60;
const EAT_UNITS = 60;
const EAT_L1 = 30;
const EAT_L2 = 60;
const EAT_L3 = 90;
const BREED_ADULTS = 12;
const BREED_EGGS = 18;
const BREED_LARVAE = 18;
const BREED_PUPAE = 18;
const RIPE_MS = 120000;
const AIR_MAX_MS = 15000;
const ICON_PX = 32;
const FAST_MS = 1500;
const FAST_EAT = 2;
const LIFE_MS = 15 * 60 * 1000;
const DRY_MAX_MIN = 20;
const RAG_MAX = 10000;
const RAG_WASH_MS = 5 * 60 * 1000;
const NET_R = 84;
const NET_FALL_MS = 100;
const JAR_DIE_MS = 2 * 60 * 1000;
const JAR_W = 180;
const JAR_H = 320;
const CRUISE_SPD = 280;


// BEGIN UPSTREAM FUNCTIONS
function mateMs() { return fast ? FAST_MS : MATE_MS; }

function ripeMs() { return fast ? FAST_MS : RIPE_MS; }

function retireFallbackMs() { return fast ? FAST_MS * 8 : 180000; }

function eatNeedFor(unit) {
  if (fast) return FAST_EAT;
  if (unit && unit.instar === 1) return EAT_L1;
  if (unit && unit.instar === 2) return EAT_L2;
  if (unit && unit.instar === 3) return EAT_L3;
  return EAT_UNITS;
}

function clutchSexes(n) {
  if (n <= 0) return [];
  if (n === 1) return [Math.random() < 0.5 ? 'm' : 'f'];
  const s = ['m', 'f'];
  for (let i = 2; i < n; i++) s.push(Math.random() < 0.5 ? 'm' : 'f');
  for (let i = s.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const t = s[i];
    s[i] = s[j];
    s[j] = t;
  }
  return s;
}

function isGenoGreen(u) {
  return u && (u.geneD || 0) >= 2 && (u.geneP || 0) >= 2 && (u.geneG || 0) >= 2;
}

function breedingAdults() {
  return flies.filter((f) => f.state !== 'dead' && !f.retired && !f.dieAt).length;
}

function canEclose() { return !breed || breedingAdults() < BREED_ADULTS; }

function canAddAdult() { return canEclose(); }

function adultsFull() { return breed && breedingAdults() >= BREED_ADULTS; }

function extraAllele(n) {
  const k = Number(n);
  if (!Number.isFinite(k) || k <= 0) return 0;
  if (k >= 2) return 1;
  return Math.random() < 0.5 ? 1 : 0;
}

function extraGenes(mom, dad) {
  const mg = isGenoGreen(mom);
  const dg = isGenoGreen(dad);
  if (mg && dg) {
    return {
      geneX: extraAllele(mom.geneX) + extraAllele(dad.geneX),
      geneY: extraAllele(mom.geneY) + extraAllele(dad.geneY),
    };
  }
  if (mg) return { geneX: extraAllele(mom.geneX), geneY: extraAllele(mom.geneY) };
  if (dg) return { geneX: extraAllele(dad.geneX), geneY: extraAllele(dad.geneY) };
  return { geneX: 1, geneY: 1 };
}

function screenOf(x, y) {
  return screens.find((s) => x >= s.x && x < s.x + s.w && y >= s.y && y < s.y + s.h) || null;
}

function rand(a, b) {
  return a + Math.random() * (b - a);
}

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

function bodyPx(fly) {
  return 18 * (fly && fly.scale ? fly.scale : 1);
}

function senseRadius(fly) {
  const L = bodyPx(fly);
  const t = clamp(mouse.spd / 3200, 0, 1);
  const flying = fly.state === 'fly' || fly.state === 'flee';
  const minB = flying ? 20 : 4;
  const maxB = 30;
  return L * (minB + (maxB - minB) * t);
}

function iconGlyph(ic) {
  if (!ic) return { x: 0, y: 0, w: 32, h: 32 };
  const side = Math.max(18, Math.min((ic.h || 32) - 2, 32));
  return {
    x: ic.x + ((ic.w || side) - side) / 2,
    y: ic.y + Math.max(0, ((ic.h || side) - side) / 2),
    w: side,
    h: side,
  };
}

function currentCell(x, y) {
  for (const ic of icons) {
    if (ic.w < 8 || ic.h < 8) continue;
    const g = iconGlyph(ic);
    if (x >= g.x && x <= g.x + g.w && y >= g.y && y <= g.y + g.h) return ic;
  }
  return null;
}

function ringIcons(ic) {
  if (!ic) return [];
  const cx = ic.x + ic.w / 2;
  const cy = ic.y + ic.h / 2;
  const rx = Math.max(80, ic.w * 1.6);
  const ry = Math.max(90, ic.h * 1.8);
  const out = [];
  for (const o of icons) {
    if (Math.abs((o.x + o.w / 2) - cx) <= rx && Math.abs((o.y + o.h / 2) - cy) <= ry) out.push(o);
  }
  return out;
}

function onFood(x, y, food, pad) {
  if (!food) return false;
  const ic = icons.find((i) => i.id === food.iconId);
  const p = Math.max(2, pad || 0);
  if (ic) {
    const g = iconGlyph(ic);
    if (x >= g.x + p && x <= g.x + g.w - p && y >= g.y + p && y <= g.y + g.h - p) return true;
  }
  return Math.hypot(food.x - x, food.y - y) < p;
}

function foodInRing(x, y, skipId) {
  const here = currentCell(x, y);
  if (!here) return null;
  const ids = new Set(ringIcons(here).map((i) => i.id));
  let best = null;
  let bd = 1e9;
  for (const f of foods) {
    if (skipId && f.id === skipId) continue;
    if (!foodOpen(f)) continue;
    if (f.infinite) {
      if (f.iconId !== here.id) continue;
    } else if (!ids.has(f.iconId)) continue;
    const d = Math.hypot(f.x - x, f.y - y);
    if (d < bd) {
      bd = d;
      best = f;
    }
  }
  return best;
}

function iconPad(ic) {
  const g = iconGlyph(ic);
  return { x: g.x + g.w * 0.5, y: g.y + g.h * 0.45 };
}

function clampToGlyph(ic, x, y) {
  if (!ic) return { x, y };
  const g = iconGlyph(ic);
  return {
    x: clamp(x, g.x + 5, g.x + g.w - 5),
    y: clamp(y, g.y + 4, g.y + g.h - 4),
  };
}

function dangerPos() {
  return swatterOn ? paddleCenter() : { x: mouse.x, y: mouse.y };
}

function farFromMouse(ic, min = 90) {
  const c = iconPad(ic);
  const p = dangerPos();
  return Math.hypot(c.x - p.x, c.y - p.y) > min;
}

function randomIcon() {
  if (!icons.length) return null;
  return icons[Math.floor(Math.random() * icons.length)];
}

function nearestIconTo(x, y, excludeId) {
  let best = null;
  let bd = 1e9;
  for (const ic of icons) {
    if (ic.id === excludeId) continue;
    const c = iconPad(ic);
    if (screens.length && !screenOf(c.x, c.y)) continue;
    const d = Math.hypot(c.x - x, c.y - y);
    if (d < bd) {
      bd = d;
      best = ic;
    }
  }
  return best;
}

function pickIcon(preferFood, from, excludeId) {
  if (!icons.length) return null;
  const onScreen = (ic) => {
    const c = iconPad(ic);
    return !!screenOf(c.x, c.y);
  };
  let pool = icons.filter((ic) => ic.id !== excludeId && farFromMouse(ic, 70) && onScreen(ic));
  if (!pool.length) pool = icons.filter((ic) => ic.id !== excludeId && onScreen(ic));
  if (!pool.length) pool = icons.filter((ic) => ic.id !== excludeId);
  if (!pool.length) pool = icons.slice();
  if (preferFood) {
    const forced = seekFoodIcon(from);
    if (forced) return forced;
    const fed = pool.filter((ic) => {
      const f = foods.find((x) => x.iconId === ic.id);
      return f && foodOpen(f);
    });
    if (fed.length) {
      fed.sort((a, b) => foodScore(a, from) - foodScore(b, from));
      if (from) return fed[0];
      const w = [];
      for (const ic of fed) {
        const f = foods.find((x) => x.iconId === ic.id);
        const n = Math.max(1, f && f.attract ? Math.round(f.attract) : 1);
        for (let k = 0; k < n; k++) w.push(ic);
      }
      pool = w;
    }
  }
  if (from) {
    const home = screenOf(from.x, from.y);
    if (home) {
      const same = pool.filter((ic) => {
        const c = iconPad(ic);
        return c.x >= home.x && c.x < home.x + home.w && c.y >= home.y && c.y < home.y + home.h;
      });
      if (same.length) pool = same;
    }
    pool.sort((a, b) => {
      const da = Math.hypot(iconPad(a).x - from.x, iconPad(a).y - from.y);
      const db = Math.hypot(iconPad(b).x - from.x, iconPad(b).y - from.y);
      return da - db;
    });
    return pool[0] || null;
  }
  return pool[Math.floor(Math.random() * pool.length)];
}

function passRecessive(n) {
  const k = n == null ? 1 : n;
  if (k >= 2) return 1;
  if (k <= 0) return 0;
  return Math.random() < 0.5 ? 1 : 0;
}

function inheritGene(a, b) {
  return passRecessive(a) + passRecessive(b);
}

function spawnFly(x, y, opts = {}) {
  if (!opts.force && !canAddAdult()) return null;
  const perched = opts.perch || null;
  const f = {
    id: nextId++,
    x: perched ? iconPad(perched).x : x,
    y: perched ? iconPad(perched).y : y,
    vx: 0,
    vy: 0,
    heading: rand(0, Math.PI * 2),
    visHead: rand(0, Math.PI * 2),
    state: perched ? 'perch' : 'fly',
    hunger: rand(0.2, 0.4),
    energy: perched ? 0.4 : 1,
    restUntil: 0,
    stillUntil: perched ? performance.now() + rand(300, 6000) : 0,
    perch: perched,
    target: null,
    mission: perched ? 'rest' : 'land',
    settleUntil: perched ? performance.now() + 2500 : 0,
    ignoreThreatUntil: 0,
    scareUntil: 0,
    nextTurn: 0,
    fleeSpeed: 0,
    intensity: 0,
    seed: rand(0, 1000),
    scale: rand(0.95, 1.2),
    turn: (Math.random() < 0.5 ? 1 : -1),
    crawling: false,
    crawlFrom: null,
    crawlTo: null,
    crawlT: 0,
    crawlDur: 0.3,
    fed: false,
    eatAcc: 0,
    mateId: 0,
    mateUntil: 0,
    mateRole: 0,
    mateSeek: 0,
    meal: 0,
    eatingFood: 0,
    eatTimer: 0,
    skipFood: 0,
    born: performance.now(),
    ripe: false,
    needMeal: true,
    eatUnits: 0,
    mealDoneAt: 0,
    mates: 0,
    sex: opts.sex || (Math.random() < 0.5 ? 'm' : 'f'),
    geneD: opts.geneD == null ? 1 : opts.geneD,
    geneP: opts.geneP == null ? 1 : opts.geneP,
    geneG: opts.geneG == null ? 0 : opts.geneG,
    geneX: opts.geneX == null ? 0 : opts.geneX,
    geneY: opts.geneY == null ? 0 : opts.geneY,
  };
  if (perched) {
    const p = clampToGlyph(perched, f.x + rand(-10, 10), f.y + rand(-8, 8));
    f.x = p.x;
    f.y = p.y;
  }
  flies.push(f);
  return f;
}

function foodSlots(food) {
  return food && food.infinite ? BIN_SLOTS : FOOD_SLOTS;
}

function foodScore(ic, from) {
  const f = foods.find((x) => x.iconId === ic.id && foodOpen(x));
  if (!f || !from) return 0;
  const c = iconPad(ic);
  return Math.hypot(c.x - from.x, c.y - from.y) / (f.attract || 1);
}

function inBinRadius(x, y) {
  const here = currentCell(x, y);
  if (here && (here.recycleBin || here.nearBin)) return true;
  const n = nearestIconTo(x, y);
  if (!n || !(n.recycleBin || n.nearBin)) return false;
  const c = iconPad(n);
  return Math.hypot(c.x - x, c.y - y) < 70;
}

function seekFoodIcon(from) {
  const inZ = from && inBinRadius(from.x, from.y);
  const binF = foods.find((f) => f.infinite);
  if (inZ && binF && foodOpen(binF)) {
    return icons.find((i) => i.id === binF.iconId) || null;
  }
  if (!inZ) return null;
  const ring = [];
  for (const ic of icons) {
    if (!ic.nearBin) continue;
    const f = foods.find((x) => x.iconId === ic.id && !x.infinite && foodOpen(x));
    if (f) ring.push(ic);
  }
  if (ring.length) {
    if (!from) return ring[0];
    ring.sort((a, b) => {
      const da = Math.hypot(iconPad(a).x - from.x, iconPad(a).y - from.y);
      const db = Math.hypot(iconPad(b).x - from.x, iconPad(b).y - from.y);
      return da - db;
    });
    return ring[0];
  }
  return null;
}

function mouseRel(fly) {
  const p = dangerPos();
  const dx = fly.x - p.x;
  const dy = fly.y - p.y;
  const dist = Math.hypot(dx, dy) || 1;
  const closing = -(mouse.vx * dx + mouse.vy * dy) / dist;
  return { dist, closing, dx, dy, nx: dx / dist, ny: dy / dist };
}

function threat(fly, now) {
  if (netOn) return { p: 0, intensity: 0, dist: 1e9 };
  const { dist } = mouseRel(fly);
  if (fly.state === 'flee') return { p: 0, intensity: 0, dist };
  if (now < (fly.settleUntil || 0)) return { p: 0, intensity: 0, dist };
  const r = senseRadius(fly);
  if (dist > r) return { p: 0, intensity: 0, dist };
  const intensity = clamp(1 - dist / r, 0.4, 1);
  return { p: 1, intensity, dist };
}

function interruptEat(unit) {
  if (!unit) return;
  if (unit.eatingFood) {
    leaveFood(foods.find((f) => f.id === unit.eatingFood), unit.id);
    unit.eatingFood = 0;
  }
  unit.eatStamp = 0;
  unit.eatBegan = 0;
  unit.eatAcc = 0;
}

function scare(fly, now, intensity) {
  interruptEat(fly);
  const t = clamp(intensity, 0.25, 1);
  const pairing = fly.state === 'mate' || !!fly.mateSeek;
  if (fly.state === 'mate') {
    const other = flies.find((x) => x.id === fly.mateId);
    fly.mateId = 0;
    fly.mateUntil = 0;
    if (other && other.state === 'mate') {
      other.mateId = 0;
      other.mateUntil = 0;
      other.state = 'flee';
    }
  }
  fly.state = 'flee';
  fly.mission = 'flee';
  fly.netEscape = 0;
  fly.perch = null;
  fly.target = null;
  fly.crawling = false;
  fly.ci = null;
  fly.mateSeek = 0;
  const linked = flies.find((x) => x.mateSeek === fly.id);
  if (linked) {
    linked.mateSeek = 0;
    linked.ripe = false;
    linked.mateCool = now + 8000;
  }
  if (pairing) {
    fly.ripe = false;
    fly.mateCool = now + 8000;
  }
  fly.intensity = t;
  fly.fleeSpeed = 360 + t * 480;
  fly.scareUntil = now + (4000 + t * 12000);
  fly.settleUntil = 0;
  fly.fleePhase = 'straight';
  fly.quietSince = 0;
  fly.landAfter = 0;
  fly.safeSince = 0;
  fly.afterSafe = null;
  fly.nextTurn = now + rand(80, 220);
  fly.turn = Math.random() < 0.5 ? 1 : -1;
  const { nx, ny, dist } = mouseRel(fly);
  fly.heading = Math.atan2(ny, nx);
  fly.lastSenseDist = 1e9;
  armBoosts(fly, now, dist, senseRadius(fly));
  fly.vx = Math.cos(fly.heading) * fly.fleeSpeed;
  fly.vy = Math.sin(fly.heading) * fly.fleeSpeed;
}

function armBoosts(fly, now, dist, r) {
  const prev = fly.lastSenseDist == null ? 1e9 : fly.lastSenseDist;
  if (dist < r && prev >= r) fly.boost2Until = now + rand(4000, 6000);
  if (dist < r * 0.5 && prev >= r * 0.5) fly.boost4Until = now + rand(4000, 6000);
  if (dist < r * 0.2 && prev >= r * 0.2) fly.boost8Until = now + rand(300, 500);
  fly.lastSenseDist = dist;
}

function fleeMul(fly, now) {
  if (now < (fly.boost8Until || 0)) return 8;
  if (now < (fly.boost4Until || 0)) return 3;
  if (now < (fly.boost2Until || 0)) return 2;
  return 1;
}

function canLand(fly, now) {
  const rel = mouseRel(fly);
  const r = 72;
  if (rel.dist <= r) {
    fly.quietSince = 0;
    fly.landAfter = 0;
    return false;
  }
  if (!fly.quietSince) {
    fly.quietSince = now;
    fly.landAfter = now + rand(600, 1600);
    return false;
  }
  return now >= fly.landAfter;
}

function iconHasFood(ic, skipId) {
  if (!ic) return false;
  const pad = iconPad(ic);
  return foods.some((f) => {
    if (skipId && f.id === skipId) return false;
    const on = f.iconId === ic.id || Math.hypot(f.x - pad.x, f.y - pad.y) < 52;
    return on && (foodOpen(f) || (f.eaters || []).length);
  });
}

function markIconStay(fly, now) {
  if (iconHasFood(fly.perch, fly.skipFood)) fly.leaveAt = 0;
  else fly.leaveAt = now + rand(1000, 5000);
}

function forceLand(fly, ic, now) {
  if (!ic) return;
  const p = clampToGlyph(ic, fly.x, fly.y);
  fly.state = 'perch';
  fly.mission = 'rest';
  fly.perch = ic;
  fly.target = ic;
  fly.x = p.x;
  fly.y = p.y;
  fly.vx = 0;
  fly.vy = 0;
  fly.crawling = false;
  fly._ix = ic.x;
  fly._iy = ic.y;
  markIconStay(fly, now);
}

function landOn(fly, ic, now) {
  if (!ic) return;
  const p = clampToGlyph(ic, fly.x, fly.y);
  const close = Math.hypot(p.x - fly.x, p.y - fly.y) < 48;
  const mouseOk = mouseRel(fly).dist > 56;
  if (!close) {
    fly.state = 'fly';
    fly.mission = 'land';
    fly.target = ic;
    return;
  }
  if (!canLand(fly, now) && !mouseOk) {
    fly.state = 'fly';
    fly.mission = 'land';
    fly.target = ic;
    return;
  }
  fly.state = 'perch';
  fly.mission = 'rest';
  fly.perch = ic;
  fly.target = null;
  fly.vx = 0;
  fly.vy = 0;
  fly.crawling = false;
  fly.ci = null;
  fly.x = p.x;
  fly.y = p.y;
  fly._ix = ic.x;
  fly._iy = ic.y;
  fly.stillUntil = now + rand(300, 6000);
  fly.settleUntil = now + 1800;
  markIconStay(fly, now);
}

function startHop(fly, now) {
  if (!fly.perch) return;
  const len = bodyPx(fly) * rand(1, 2);
  const ang = rand(0, Math.PI * 2);
  const to = clampToGlyph(
    fly.perch,
    fly.x + Math.cos(ang) * len,
    fly.y + Math.sin(ang) * len,
  );
  const dist = Math.hypot(to.x - fly.x, to.y - fly.y);
  fly.crawling = true;
  fly.crawlFrom = { x: fly.x, y: fly.y };
  fly.crawlTo = to;
  fly.crawlT = 0;
  fly.crawlDur = clamp(0.12 + dist / 90, 0.12, 0.28);
  fly.heading = Math.atan2(to.y - fly.y, to.x - fly.x);
  fly.stillUntil = now + rand(300, 6000);
}

function wrapScreen(fly) {
  if (fly.state === 'perch' || fly.state === 'eat' || fly.state === 'mate') return;
  const list = screens.length ? screens : [{ x: 0, y: 0, w: W, h: H }];
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const s of list) {
    x0 = Math.min(x0, s.x);
    y0 = Math.min(y0, s.y);
    x1 = Math.max(x1, s.x + s.w);
    y1 = Math.max(y1, s.y + s.h);
  }
  const vw = x1 - x0;
  const vh = y1 - y0;
  if (!(vw > 0) || !(vh > 0)) return;
  if (!Number.isFinite(fly.x) || !Number.isFinite(fly.y)) {
    fly.x = (x0 + x1) / 2;
    fly.y = (y0 + y1) / 2;
    return;
  }
  while (fly.x < x0) fly.x += vw;
  while (fly.x >= x1) fly.x -= vw;
  while (fly.y < y0) fly.y += vh;
  while (fly.y >= y1) fly.y -= vh;
}

function wanderHeading(fly, dt, now, toward) {
  if (now > (fly.nextTurn || 0)) {
    fly.nextTurn = now + rand(300, 1000);
    if (toward) {
      const want = Math.atan2(toward.y - fly.y, toward.x - fly.x);
      fly.course = want + rand(-2.1, 2.1);
    } else {
      fly.course = fly.heading + rand(-2.6, 2.6);
    }
    fly.burstMul = 1 + rand(0.2, 0.5);
    fly.burstUntil = now + rand(200, 300);
  }
  if (fly.course == null) fly.course = fly.heading;
  let diff = fly.course - fly.heading;
  while (diff > Math.PI) diff -= Math.PI * 2;
  while (diff < -Math.PI) diff += Math.PI * 2;
  fly.heading += diff * Math.min(1, dt * 7);
  fly.heading += Math.sin(now * 0.007 + fly.seed) * 0.8 * dt;
}

function stepFly(fly, dt, now) {
  if (fly.state === 'dead') return;
  if (!fly.born) fly.born = now;
  if (fly.retired) fly.ripe = false;
  else if (fly.mateCool && now < fly.mateCool) fly.ripe = false;
  else if (!fly.needMeal) {
    if (!fly.ripe && now - fly.born >= ripeMs()) fly.ripe = true;
  } else if ((fly.eatUnits || 0) >= eatNeedFor(fly)) {
    if (!fly.mealDoneAt) fly.mealDoneAt = now;
    if (!fly.ripe && now - fly.mealDoneAt >= ripeMs()) fly.ripe = true;
  }

  if (fly.state === 'mate') {
    const p = dangerPos();
    if (Math.hypot(fly.x - p.x, fly.y - p.y) < 140) {
      failMate(fly, now);
      return;
    }
    if (now >= fly.mateUntil) {
      finishMate(fly, now);
      return;
    }
    fly.vx = 0;
    fly.vy = 0;
    return;
  }

  fly.liveMs = (fly.liveMs || 0) + dt * 1000;
  if (fly.liveMs >= LIFE_MS) {
    corpses.push(flyCorpse(fly));
    fly.state = 'dead';
    return;
  }

  if (fly.kidDieAt && !fly.dieAt && now >= fly.kidDieAt) {
    corpses.push(flyCorpse(fly));
    fly.state = 'dead';
    return;
  }

  if (fly.dieAt) {
    if (now >= fly.dieAt) {
      corpses.push(flyCorpse(fly));
      fly.state = 'dead';
      return;
    }
    wanderHeading(fly, dt, now);
    fly.vx = Math.cos(fly.heading) * 300;
    fly.vy = Math.sin(fly.heading) * 300;
    fly.x += fly.vx * dt;
    fly.y += fly.vy * dt;
    wrapScreen(fly);
    return;
  }

  const th = threat(fly, now);
  if (fly.state !== 'flee' && th.p > 0) {
    scare(fly, now, th.intensity);
  }

  fly.hunger = Math.min(1, (fly.hunger || 0) + dt * 0.028);
  if (fly.state === 'eat') fly.hunger = Math.max(0, fly.hunger - dt * 0.3);

  if (fly.state === 'flee') {
    const rel = mouseRel(fly);
    const r = senseRadius(fly);
    if (rel.dist <= r) {
      fly.safeSince = 0;
      fly.afterSafe = null;
    } else if (!fly.safeSince) {
      fly.safeSince = now;
    }
    if (fly.safeSince && now - fly.safeSince >= 3000) {
      fly.state = 'fly';
      fly.netEscape = 0;
      if (Math.random() < 0.5) {
        fly.mission = 'cruise';
        fly.cruiseUntil = now + rand(1000, 3000);
        fly.target = null;
      } else {
        fly.mission = fly.hunger > 0.75 ? 'food' : 'land';
        fly.target = (fly.mission === 'food' ? pickIcon(true, fly) : nearestIconTo(fly.x, fly.y)) || randomIcon();
      }
    } else {
      if (fly.fleePhase !== 'random' && rel.dist > r) {
        fly.fleePhase = 'random';
        fly.nextTurn = now;
      }
      if (fly.fleePhase === 'straight') {
        fly.heading = Math.atan2(rel.ny, rel.nx);
      } else {
        wanderHeading(fly, dt, now);
      }
      let spd;
      let mul;
      if (fly.netEscape) {
        spd = fly.netEscape * (0.9 + 0.1 * Math.sin(now * 0.01 + fly.seed));
        mul = 1;
      } else {
        spd = fly.fleeSpeed * (0.85 + 0.2 * Math.sin(now * 0.008 + fly.seed));
        armBoosts(fly, now, rel.dist, r);
        mul = fleeMul(fly, now);
      }
      fly.vx = Math.cos(fly.heading) * spd * mul;
      fly.vy = Math.sin(fly.heading) * spd * mul;
    }
  } else if (fly.state === 'perch' || fly.state === 'eat') {
    fly.vx = 0;
    fly.vy = 0;
    if (fly.perch) {
      const still = icons.find((i) => i.id === fly.perch.id)
        || icons.find((i) => i.name === fly.perch.name);
      if (still) fly.perch = still;
      else {
        fly.perch = null;
        fly.state = 'fly';
        fly.mission = 'land';
        fly.target = nearestIconTo(fly.x, fly.y) || randomIcon();
        return;
      }
      if (!fly.crawling) {
        if (fly._ix != null) {
          const dx = fly.perch.x - fly._ix;
          const dy = fly.perch.y - fly._iy;
          if (Math.hypot(dx, dy) < 40) {
            fly.x += dx;
            fly.y += dy;
          }
        }
        const held = clampToGlyph(fly.perch, fly.x, fly.y);
        fly.x = held.x;
        fly.y = held.y;
        fly._ix = fly.perch.x;
        fly._iy = fly.perch.y;
      }
    }

    if (fly.ripe && fly.mateSeek) {
      const p = flies.find((x) => x.id === fly.mateSeek);
      if (p && (p.state === 'perch' || p.state === 'eat') && Math.hypot(p.x - fly.x, p.y - fly.y) < 90) {
        startMate(fly, p, now);
        return;
      }
    } else if (fly.ripe && !fly.mateSeek) {
      const other = flies.find((o) => o.ripe && o.id !== fly.id && o.sex !== fly.sex && !o.mateSeek && o.state !== 'dead' && o.state !== 'mate');
      if (other) {
        beginPair(fly, other, now);
        return;
      }
    }

    if (fly.perch) {
      const pad = iconPad(fly.perch);
      const food = foods.find((f) => {
        if (f.id === fly.skipFood) return false;
        const onIcon = f.iconId === fly.perch.id
          || Math.hypot(f.x - pad.x, f.y - pad.y) < 52;
        if (!onIcon) return false;
        return foodOpen(f) || (f.eaters || []).includes(fly.id);
      });
      if (food && joinFood(food, fly.id)) {
        fly.eatingFood = food.id;
        fly.state = 'eat';
        fly.leaveAt = 0;
        if (fly.needMeal) {
          fly.eatUnits = (fly.eatUnits || 0) + dt;
          if (fly.eatUnits >= eatNeedFor(fly) && !fly.mealDoneAt) fly.mealDoneAt = now;
        }
      } else if (fly.hunger > 0.75) {
        const ic = pickIcon(true, fly, fly.perch && fly.perch.id);
        if (ic) {
          interruptEat(fly);
          fly.state = 'fly';
          fly.mission = 'food';
          fly.target = ic;
          fly.perch = null;
          return;
        }
      }
    }

    if (fly.crawling && fly.crawlTo) {
      fly.crawlT += dt / fly.crawlDur;
      const t = clamp(fly.crawlT, 0, 1);
      const e = t * t * (3 - 2 * t);
      fly.x = fly.crawlFrom.x + (fly.crawlTo.x - fly.crawlFrom.x) * e;
      fly.y = fly.crawlFrom.y + (fly.crawlTo.y - fly.crawlFrom.y) * e;
      if (t >= 1) fly.crawling = false;
    } else if (now > (fly.stillUntil || 0)) {
      startHop(fly, now);
    }

    if (fly.perch && !fly.mateSeek && !fly.eatingFood && fly.leaveAt && now >= fly.leaveAt) {
      interruptEat(fly);
      fly.state = 'fly';
      fly.mission = fly.hunger > 0.45 ? 'food' : 'land';
      fly.target = pickIcon(fly.mission === 'food', fly, fly.perch.id) || randomIcon();
      fly.takeoffUntil = now + 400;
      fly.perch = null;
      return;
    }
  } else {
    if (fly.mission === 'food' && !fly.mateSeek && !fly.dieAt) {
      const near = foodInRing(fly.x, fly.y, fly.skipFood);
      if (near) {
        const ic = icons.find((i) => i.id === near.iconId) || nearestIconTo(near.x, near.y);
        if (ic && onFood(fly.x, fly.y, near, bodyPx(fly) * 0.45)) {
          forceLand(fly, ic, now);
          return;
        }
        if (ic) fly.target = ic;
      }
    }
    if (now < (fly.takeoffUntil || 0)) {
      if (Math.hypot(fly.vx, fly.vy) < 30) {
        fly.vx = Math.cos(fly.heading || 0) * 320;
        fly.vy = Math.sin(fly.heading || 0) * 320;
      }
    } else if (fly.mission === 'cruise') {
      wanderHeading(fly, dt, now);
      fly.vx = Math.cos(fly.heading) * 280;
      fly.vy = Math.sin(fly.heading) * 280;
      if (now >= (fly.cruiseUntil || 0)) {
        fly.mission = fly.hunger > 0.75 ? 'food' : 'land';
        fly.target = (fly.mission === 'food' ? pickIcon(true, fly) : nearestIconTo(fly.x, fly.y)) || randomIcon();
      }
    } else if (fly.mission === 'meet' && fly.mateSeek) {
      const p = flies.find((x) => x.id === fly.mateSeek);
      if (p) {
        const want = Math.atan2(p.y - fly.y, p.x - fly.x);
        let diff = want - fly.heading;
        while (diff > Math.PI) diff -= Math.PI * 2;
        while (diff < -Math.PI) diff += Math.PI * 2;
        fly.heading += diff * Math.min(1, dt * 8);
        fly.vx = Math.cos(fly.heading) * 420;
        fly.vy = Math.sin(fly.heading) * 420;
      }
    } else if (fly.mission === 'seekMate' && fly.ripe && !fly.mateSeek) {
      const other = flies.find((o) => o.ripe && o.id !== fly.id && o.sex !== fly.sex && !o.mateSeek && o.state !== 'dead' && o.state !== 'mate');
      if (other) beginPair(fly, other, now);
      else {
        fly.mission = 'land';
        fly.target = nearestIconTo(fly.x, fly.y);
      }
    } else if (!fly.target || !icons.some((i) => i.id === fly.target.id)) {
      if (fly.mateSeek) {
        fly.target = (fly.target && icons.find((i) => i.name === fly.target.name)) || randomIcon();
      } else {
        fly.target = fly.mission === 'food'
          ? (pickIcon(true, fly) || nearestIconTo(fly.x, fly.y))
          : nearestIconTo(fly.x, fly.y);
      }
    }
    if (fly.mission !== 'seekMate' && fly.mission !== 'meet' && fly.target) {
      const c = iconPad(fly.target);
      const dx = c.x - fly.x;
      const dy = c.y - fly.y;
      const d = Math.hypot(dx, dy) || 1;
      const cruise = 380;
      if (d < 50 && (fly.mateSeek || fly.mission === 'food')) {
        forceLand(fly, fly.target, now);
      } else if (d < 40) {
        landOn(fly, fly.target, now);
      } else if (d < 70 && canLand(fly, now)) {
        const want = Math.atan2(dy, dx);
        let diff = want - fly.heading;
        while (diff > Math.PI) diff -= Math.PI * 2;
        while (diff < -Math.PI) diff += Math.PI * 2;
        fly.heading += diff * Math.min(1, dt * 6);
        fly.vx = Math.cos(fly.heading) * cruise;
        fly.vy = Math.sin(fly.heading) * cruise;
      } else {
        wanderHeading(fly, dt, now, c);
        fly.vx = Math.cos(fly.heading) * cruise;
        fly.vy = Math.sin(fly.heading) * cruise;
      }
    } else if (fly.mission !== 'seekMate' && fly.mission !== 'meet' && fly.mission !== 'cruise') {
      wanderHeading(fly, dt, now);
      fly.vx = Math.cos(fly.heading) * 280;
      fly.vy = Math.sin(fly.heading) * 280;
    }
  }

  if (fly.state === 'perch' || fly.state === 'eat' || fly.state === 'mate') {
    fly.airSince = 0;
  } else if (!fly.dieAt && fly.mission !== 'meet' && !fly.mateSeek) {
    if (!fly.airSince) fly.airSince = now;
    if (now - fly.airSince >= AIR_MAX_MS) {
      const ic = nearestIconTo(fly.x, fly.y) || randomIcon();
      if (ic) {
        fly.mission = 'land';
        fly.target = ic;
      }
    }
  }

  if (fly.state !== 'perch' && fly.state !== 'eat') {
    if (now < (fly.burstUntil || 0)) {
      const b = fly.burstMul || 1;
      fly.vx *= b;
      fly.vy *= b;
    }
    fly.x += fly.vx * dt;
    fly.y += fly.vy * dt;
    wrapScreen(fly);
  }

  const spd = Math.hypot(fly.vx, fly.vy);
  if (spd > 6 || fly.crawling) {
    let dh = fly.heading - fly.visHead;
    while (dh > Math.PI) dh -= Math.PI * 2;
    while (dh < -Math.PI) dh += Math.PI * 2;
    fly.visHead += dh * Math.min(1, dt * 10);
  }
}

function flyCorpse(fly) {
  return {
    id: nextId++,
    kind: 'fly',
    x: fly.x,
    y: fly.y,
    heading: fly.visHead || fly.heading || 0,
    seed: fly.seed,
    scale: fly.scale || 1,
    sex: fly.sex,
    geneD: fly.geneD,
    geneP: fly.geneP,
    geneG: fly.geneG,
    geneX: fly.geneX,
    geneY: fly.geneY,
    ageMs: 0,
    wipes: 0,
  };
}

function beginPair(a, b, now) {
  if (!a || !b || a.id === b.id || a.sex === b.sex) return;
  if (a.mateSeek || b.mateSeek) return;
  a.mateSeek = b.id;
  b.mateSeek = a.id;
  const first = !a.needMeal && !b.needMeal;
  const ic = first ? null : randomIcon();
  const go = (f) => {
    interruptEat(f);
    f.state = 'fly';
    f.perch = null;
    if (first || !ic) {
      f.mission = 'meet';
      f.target = null;
    } else {
      f.mission = 'land';
      f.target = ic;
    }
  };
  go(a);
  go(b);
}

function failMate(fly, now) {
  const other = flies.find((x) => x.id === fly.mateId || x.id === fly.mateSeek);
  const fail = (f) => {
    if (!f || f.state === 'dead') return;
    f.state = 'flee';
    f.mission = 'flee';
    f.fleePhase = 'straight';
    f.fleeSpeed = 420;
    f.mateId = 0;
    f.mateUntil = 0;
    f.mateSeek = 0;
    f.ripe = false;
    f.mateCool = now + 8000;
    f.perch = null;
    f.target = null;
    const ang = rand(0, Math.PI * 2);
    f.heading = ang;
    f.vx = Math.cos(ang) * 420;
    f.vy = Math.sin(ang) * 420;
  };
  fail(fly);
  if (other) fail(other);
}

function startMate(a, b, now) {
  if (!a || !b || a.sex === b.sex) return;
  if (a.state === 'mate' || b.state === 'mate') return;
  const x = (a.x + b.x) * 0.5;
  const y = (a.y + b.y) * 0.5;
  a.x = x;
  a.y = y;
  b.x = x + 7;
  b.y = y - 4;
  a.state = 'mate';
  b.state = 'mate';
  a.mateId = b.id;
  b.mateId = a.id;
  a.mateUntil = now + mateMs();
  b.mateUntil = now + mateMs();
  a.mateRole = 0;
  b.mateRole = 1;
  a.vx = a.vy = b.vx = b.vy = 0;
  a.crawling = b.crawling = false;
}

function settleAfterMate(f, now) {
  const ic = nearestIconTo(f.x, f.y) || randomIcon();
  if (!ic) {
    f.state = 'fly';
    f.mission = 'food';
    f.stillUntil = now + rand(400, 2000);
    return;
  }
  const c = iconPad(ic);
  if (Math.hypot(c.x - f.x, c.y - f.y) < 48) forceLand(f, ic, now);
  else {
    f.state = 'fly';
    f.mission = 'land';
    f.target = ic;
    f.perch = null;
  }
  f.stillUntil = now + rand(400, 2000);
}

function finishMate(fly, now) {
  const other = flies.find((x) => x.id === fly.mateId);
  const second = (fly.mates || 0) >= 1 || (other && (other.mates || 0) >= 1);
  const firstOf = [];
  if ((fly.mates || 0) === 0) firstOf.push(fly.id);
  if (other && (other.mates || 0) === 0) firstOf.push(other.id);
  if (other && !(adultsFull() && second)) layEggs(fly.x, fly.y, fly, other, firstOf);
  const reset = (f) => {
    f.mates = (f.mates || 0) + 1;
    f.ripe = false;
    f.born = now;
    f.needMeal = true;
    f.eatUnits = 0;
    f.mealDoneAt = 0;
    f.mateId = 0;
    f.mateUntil = 0;
    f.mateSeek = 0;
    if (f.mates >= 2) {
      f.retired = true;
      f.ripe = false;
      if (!f.kidSeen) f.kidDieAt = now + retireFallbackMs();
    }
    settleAfterMate(f, now);
  };
  reset(fly);
  if (other && other.state === 'mate') reset(other);
}

function layEggs(x, y, mom, dad, firstOf, clone) {
  const want = breed ? 2 + Math.floor(Math.random() * 2) : 6 + Math.floor(Math.random() * 3);
  const room = breed ? Math.max(0, BREED_EGGS - eggs.length) : want;
  const n = Math.min(want, room);
  const from = clone ? null : (firstOf && firstOf.length ? firstOf.slice() : null);
  const sexes = clone ? Array.from({ length: n }, () => (mom && mom.sex) || 'f') : clutchSexes(n);
  for (let i = 0; i < n; i++) {
    const geneD = clone ? (mom && mom.geneD) : inheritGene(mom && mom.geneD, dad && dad.geneD);
    const geneP = clone ? (mom && mom.geneP) : inheritGene(mom && mom.geneP, dad && dad.geneP);
    const geneG = clone ? (mom && mom.geneG) : inheritGene(mom && mom.geneG, dad && dad.geneG);
    const extra = clone
      ? { geneX: (mom && mom.geneX) || 0, geneY: (mom && mom.geneY) || 0 }
      : ((geneD >= 2 && geneP >= 2 && geneG >= 2) ? extraGenes(mom, dad) : { geneX: 0, geneY: 0 });
    eggs.push({
      x: x + rand(-12, 12),
      y: y + rand(-10, 10),
      rot: rand(0, Math.PI),
      t: performance.now(),
      seed: rand(0, 80),
      geneD,
      geneP,
      geneG,
      geneX: extra.geneX,
      geneY: extra.geneY,
      sex: sexes[i],
      firstOf: from,
    });
  }
}

function foodOpen(food) {
  return food && (food.eaters || []).length < foodSlots(food) && (food.infinite || (food.supply || 0) > 0);
}

function joinFood(food, uid) {
  if (!food.eaters) food.eaters = [];
  if (food.eaters.includes(uid)) return true;
  if (food.eaters.length >= foodSlots(food)) return false;
  food.eaters.push(uid);
  return true;
}

function leaveFood(food, uid) {
  if (!food || !food.eaters) return;
  food.eaters = food.eaters.filter((id) => id !== uid);
}

function paddleCenter() {
  return { x: mouse.x, y: mouse.y };
}
// END UPSTREAM FUNCTIONS

// Host adapter: authoritative IDs and backend ownership stay outside this
// renderer. Each individual owns its random stream even if snapshots reorder.
const states = new Map();
let activeRandom = null, previousTime = null, screenSignature = '';
// Desktop presentation only. These values do not alter authoritative population,
// inventory, genetics or any of the pinned upstream function bodies above.
const QUIET_SPEED = 0.18, VISIBLE_LIMIT = 3, FLYING_LIMIT = 1, FADE_SECONDS = 1.2;
const displaySlots = new Map();
let presentationTime = 0;
Math.random = () => {
  if (!activeRandom) throw new Error('Motion RNG used without an individual');
  activeRandom.random = BigInt.asUintN(64, activeRandom.random * 6364136223846793005n + 1442695040888963407n);
  return Number(activeRandom.random >> 11n) / 9007199254740992;
};

function backendOwnership(f) {
  // The host backend owns birth/death, mating, food production and genetics.
  // Keep original adult locomotion fields; disable lifecycle transitions
  // via existing upstream fields, without altering the original step function.
  f.retired = true;
  f.ripe = false;
  f.mateSeek = 0;
  f.liveMs = 0;
  f.kidDieAt = 0;
  f.dieAt = 0;
  // There is no upstream food-care loop in the host. Retain the original
  // newborn hunger band so an empty food list cannot force endless foraging.
  f.hunger = Math.min(f.hunger, 0.4);
}

function rehome(f) {
  if (screenOf(f.x, f.y) || !screens.length) return;
  let best = screens[0], distance = Infinity;
  for (const s of screens) {
    const d = Math.hypot(f.x - clamp(f.x, s.x, s.x+s.w), f.y - clamp(f.y, s.y, s.y+s.h));
    if (d < distance) { best = s; distance = d; }
  }
  const ix = Math.min(12, best.w/2), iy = Math.min(12, best.h/2);
  f.x = clamp(f.x, best.x+ix, best.x+best.w-ix);
  f.y = clamp(f.y, best.y+iy, best.y+best.h-iy);
  f.perch = null; f.target = null; f.state = 'fly'; f.mission = 'land';
  f.crawling = false;
}

function quietSlots(dt, frozen) {
  if (!frozen) presentationTime += dt;
  const admitted = new Map();
  for (const screen of screens) {
    let slots = displaySlots.get(screen.id);
    if (!slots) { slots = []; displaySlots.set(screen.id, slots); }
    const residents = Array.from(states.values()).filter(s => screenOf(s.fly.x,s.fly.y)?.id === screen.id);
    for(let index=0;index<slots.length;index++) {
      if(slots[index] && !residents.some(s=>s.fly.id===slots[index].id)) slots[index]=null;
    }
    for (let index=0; index<VISIBLE_LIMIT; index++) {
      let slot = slots[index];
      const waiting = residents.filter(s=>!slots.some(slot=>slot?.id===s.fly.id));
      if(slot && !frozen && waiting.length && slot.retireStart===undefined && presentationTime-slot.start>=22-FADE_SECONDS) {
        slot.retireStart=presentationTime;
      }
      if (slot && !frozen && slot.retireStart!==undefined && presentationTime-slot.retireStart>=FADE_SECONDS) slot = slots[index] = null;
      if (!slot && presentationTime >= 0.6+index*1.1 && slots.filter(Boolean).length<Math.min(VISIBLE_LIMIT,residents.length)) {
        const candidates=residents.filter(s=>!slots.some(slot=>slot?.id===s.fly.id));
        candidates.sort((a,b)=>(a.lastShown??-Infinity)-(b.lastShown??-Infinity) || a.fly.id.localeCompare(b.fly.id));
        if(candidates.length) {
          const state=candidates[0];state.lastShown=presentationTime;
          slot=slots[index]={id:state.fly.id,start:presentationTime,index};
        }
      }
      if(slot) {
        const age=presentationTime-slot.start;
        const opacity=Math.min(1,age/FADE_SECONDS,slot.retireStart===undefined ? 1:1-(presentationTime-slot.retireStart)/FADE_SECONDS);
        admitted.set(slot.id,{opacity:clamp(opacity,0,1),slot:index,age});
      }
    }
  }
  return admitted;
}

function quietStep(state, dt, admission, moving) {
  const f=state.fly;
  state.opacity=admission?.opacity || 0;
  if (!(dt>0)) return;
  state.displayRest=true;
  if (!admission || !state.opacity) {f.vx=0;f.vy=0;return;}
  state.clock=(state.clock||0)+dt*1000;
  // Three staggered six-second flight windows in an eighteen-second cycle.
  // Each admission first rests through its fade, and capture freezes admission.
  const phase=(presentationTime+admission.slot*6)%18;
  const threatened=state.opacity>0.05 && threat(f,state.clock).p>0;
  const escaping=f.state==='flee' && !netOn;
  const wantsFlight=(admission.age>=4 && phase>=6 && phase<12) || threatened || escaping;
  if(!wantsFlight || moving.count>=FLYING_LIMIT) {
    if(!state.hostRest) {
      state.hostRest={id:'host-rest-'+f.id,name:'host-rest-'+f.id,x:f.x-16,y:f.y-16,w:32,h:32};
      f.state='perch';f.perch=state.hostRest;f.target=null;f.crawling=false;
      f._ix=state.hostRest.x;f._iy=state.hostRest.y;
    }
    // A true uninterrupted stay: exact coordinates and heading remain held.
    f.vx=0;f.vy=0;
    return;
  }
  if(state.hostRest) {
    state.hostRest=null;f.state='fly';f.perch=null;f.crawling=false;
    f.mission='land';f.target=nearestIconTo(f.x,f.y);f.takeoffUntil=state.clock+400;
  }
  state.displayRest=false;
  activeRandom=state;backendOwnership(f);
  const oldX=f.x,oldY=f.y;
  // A display slot belongs to one real monitor. Keep original wrapping within
  // that monitor so a fly cannot overflow a neighbour's three visible slots.
  const allScreens=screens, home=screenOf(f.x,f.y);
  if(home) screens=[home];
  stepFly(f,dt*QUIET_SPEED,state.clock);
  screens=allScreens;
  // Preserve original heading/threat/landing decisions while reducing desktop
  // displacement; do not turn a screen wrap into a path across the screen.
  f.vx*=QUIET_SPEED;f.vy*=QUIET_SPEED;
  const speed=Math.hypot(f.vx,f.vy);
  if(speed>180) {
    const factor=180/speed;
    if(Math.hypot(f.x-oldX,f.y-oldY)<200) {f.x=oldX+(f.x-oldX)*factor;f.y=oldY+(f.y-oldY)*factor;}
    f.vx*=factor;f.vy*=factor;
  }
  if(f.state==='fly'||f.state==='flee') {state.animationTime+=dt;moving.count++;}
}

globalThis.TianmuFlyMotion = {
  step(input) {
    const signature = JSON.stringify(input.screens.map(s => [s.id,s.x,s.y,s.w,s.h]));
    const topologyChanged = signature !== screenSignature;
    screenSignature = signature;
    screens = input.screens;
    icons = input.icons;
    const p = input.pointer;
    mouse = p && p.enabled ? {x:p.x,y:p.y,vx:p.vx,vy:p.vy,spd:Math.hypot(p.vx,p.vy)}
      : {x:-1e9,y:-1e9,vx:0,vy:0,spd:0};
    netOn = !!input.suppressThreat;
    let dt = 0;
    if (Number.isFinite(input.time)) {
      const elapsed = previousTime === null ? 0 : input.time - previousTime;
      previousTime = input.time;
      if (!topologyChanged && elapsed > 0 && elapsed <= 0.25) dt = Math.min(0.05, elapsed);
    } else previousTime = null;
    if (!screens.length) dt = 0;
    simulationTime += dt * 1000;
    const present = new Set(input.rows.map(row => row.id));
    for (const id of states.keys()) if (!present.has(id)) states.delete(id);
    flies = Array.from(states.values()).map(state => state.fly);
    for (const row of input.rows) {
      let state = states.get(row.id);
      if (!state) {
        if (!screens.length) continue;
        state = {random:BigInt(row.seed),animationTime:0,fly:null,opacity:0,clock:0};
        activeRandom = state;
        state.fly = spawnFly(row.x,row.y,{force:true,sex:row.sex});
        state.fly.id = row.id;
        states.set(row.id,state);
        backendOwnership(state.fly);
      } else if (input.quietPresentation === false && dt > 0 && screens.length) {
        activeRandom = state;
        backendOwnership(state.fly);
        stepFly(state.fly,dt,simulationTime);
        if (state.fly.state === 'fly' || state.fly.state === 'flee') state.animationTime += dt;
      }
      rehome(state.fly);
    }
    if(input.quietPresentation !== false) {
      const admitted=quietSlots(dt,!!input.suppressThreat);
      const movingByScreen=new Map();
      for(const state of states.values()) {
        const screen=screenOf(state.fly.x,state.fly.y);
        if(!screen) continue;
        if(!movingByScreen.has(screen.id)) movingByScreen.set(screen.id,{count:0});
        quietStep(state,dt,admitted.get(state.fly.id),movingByScreen.get(screen.id));
        rehome(state.fly);
      }
    }
    activeRandom = null;
    return input.rows.flatMap(row => {
      const state = states.get(row.id);
      if (!state) return [];
      const f = state.fly, screen = screenOf(f.x,f.y);
      if (!screen) return [];
      return [{id:row.id,screenID:screen.id,x:f.x,y:f.y,vx:f.vx,vy:f.vy,heading:f.visHead,
        animationTime:state.animationTime,scale:f.scale,seed:f.seed,
        opacity:input.quietPresentation === false ? 1:state.opacity,
        activity:state.displayRest && input.quietPresentation !== false ? 'resting' : (f.state === 'fly' || f.state === 'flee') ? 'flying' : f.crawling ? 'crawling' : 'resting',
        state:f.state,mission:f.mission,targetID:f.target ? f.target.id : null,
        perchID:f.perch ? f.perch.id : null,simulationTime}];
    });
  },
  reset() { states.clear(); displaySlots.clear(); presentationTime=0; flies = []; previousTime = null; simulationTime = 0; screenSignature = ''; }
};
})();
