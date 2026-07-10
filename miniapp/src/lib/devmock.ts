/**
 * Dev-мок API для локальной разработки без бэкенда/Telegram.
 *
 * Активен ТОЛЬКО в `npm run dev` (import.meta.env.DEV) и вне Telegram
 * (нет window.Telegram.WebApp). В продакшн-сборке полностью выключен —
 * `request()` ходит на реальный API. Состояние держится в памяти и
 * сбрасывается на перезагрузке страницы.
 *
 * Зеркалит контракты gacha-v2 (docs/gacha_v2.md), чтобы экраны рендерились
 * как на проде. Новые игровые экраны добавляй сюда же по мере разработки.
 */

export function mockEnabled(): boolean {
  if (!import.meta.env.DEV || typeof window === 'undefined') return false;
  // SDK telegram-web-app.js создаёт window.Telegram.WebApp ДАЖЕ вне Telegram
  // (с пустым initData). Реальная TMA-сессия = непустой подписанный initData.
  const wa = (window as any).Telegram?.WebApp;
  return !wa?.initData;
}

// ---------- каталог (зеркало bot/services/gacha_catalog.py) ----------
type Rar = 'R' | 'SR' | 'SSR' | 'UR';
interface Char {
  id: string;
  name: string;
  rarity: Rar;
  role: 'worker' | 'heroine';
  position: 'front' | 'back';
  ability: string;
  base_value: number;
}
const CHARS: Char[] = [
  { id: 'r_cherry', name: 'Вишнёвая', rarity: 'R', role: 'worker', position: 'front', ability: 'guard', base_value: 0.2 },
  { id: 'r_lemon', name: 'Лимонная', rarity: 'R', role: 'worker', position: 'back', ability: 'crit', base_value: 0.5 },
  { id: 'r_bell', name: 'Колокольчик', rarity: 'R', role: 'worker', position: 'back', ability: 'crit', base_value: 1 },
  { id: 'r_star', name: 'Звёздная', rarity: 'R', role: 'worker', position: 'back', ability: 'heavy_strike', base_value: 2 },
  { id: 'r_diamond', name: 'Бриллиантовая', rarity: 'R', role: 'worker', position: 'front', ability: 'guard', base_value: 4 },
  { id: 'sr_harvest', name: 'Жница', rarity: 'SR', role: 'worker', position: 'front', ability: 'heavy_strike', base_value: 8 },
  { id: 'sr_herbalist', name: 'Травница', rarity: 'SR', role: 'worker', position: 'back', ability: 'heal', base_value: 10 },
  { id: 'sr_beekeeper', name: 'Пасечница', rarity: 'SR', role: 'worker', position: 'front', ability: 'guard', base_value: 13 },
  { id: 'sr_autumn', name: 'Осенняя', rarity: 'SR', role: 'worker', position: 'back', ability: 'aoe', base_value: 16 },
  { id: 'ssr_noble', name: 'Дворянка полей', rarity: 'SSR', role: 'worker', position: 'front', ability: 'heavy_strike', base_value: 35 },
  { id: 'ssr_orchard', name: 'Принцесса садов', rarity: 'SSR', role: 'worker', position: 'back', ability: 'aoe', base_value: 45 },
  { id: 'ssr_sun', name: 'Солнечная богиня', rarity: 'SSR', role: 'heroine', position: 'back', ability: 'heal', base_value: 1.5 },
  { id: 'ur_celestial', name: 'Небесная жница', rarity: 'UR', role: 'heroine', position: 'back', ability: 'heal', base_value: 2 },
  { id: 'ur_cosmic', name: 'Космическая королева', rarity: 'UR', role: 'heroine', position: 'front', ability: 'heavy_strike', base_value: 2.5 },
  { id: 'ur_phoenix', name: 'Дева-феникс', rarity: 'UR', role: 'heroine', position: 'back', ability: 'aoe', base_value: 3 }
];
const BY_ID = Object.fromEntries(CHARS.map((c) => [c.id, c]));
const asset = (id: string) => `/gacha/${id}.webp`;

const TIER_BASE: Record<Rar, { hp: number; atk: number; def: number; spd: number }> = {
  R: { hp: 300, atk: 45, def: 25, spd: 50 },
  SR: { hp: 480, atk: 70, def: 38, spd: 58 },
  SSR: { hp: 720, atk: 105, def: 55, spd: 66 },
  UR: { hp: 1050, atk: 150, def: 78, spd: 75 }
};
const LEVEL_CAP: Record<number, number> = { 1: 20, 2: 30, 3: 40, 4: 50, 5: 60 };

function cardStats(c: Char, stars: number, level: number) {
  const b = { ...TIER_BASE[c.rarity] };
  if (c.position === 'front') {
    b.hp *= 1.3;
    b.def *= 1.3;
    b.atk *= 0.85;
  } else {
    b.atk *= 1.25;
    b.hp *= 0.85;
  }
  const m = (1 + 0.08 * (Math.max(1, Math.min(stars, 5)) - 1)) * (1 + 0.03 * (Math.max(1, level) - 1));
  return {
    hp: Math.round(b.hp * m),
    atk: Math.round(b.atk * m),
    def: Math.round(b.def * m),
    spd: Math.round(b.spd * m)
  };
}
const cardPower = (c: Char, stars: number, level: number) => {
  const s = cardStats(c, stars, level);
  return s.hp + s.atk * 6 + s.def * 4 + s.spd * 3;
};

// ---------- мини-симуляция боя (зеркало bot/services/battle_service.py) ----------
const ABIL_CFG: Record<string, any> = {
  heavy_strike: { type: 'single', mult: 1.8 },
  crit: { type: 'single', mult: 1.6 },
  aoe: { type: 'aoe', mult: 0.6 },
  heal: { type: 'heal', frac: 0.22 },
  guard: { type: 'self_heal', frac: 0.16 }
};
const DMG_K = 0.5;
const ROUND_CAP = 30;
const EVERY_N = 3;

function buildUnit(side: 'a' | 'b', idx: number, char_id: string, position: string, stars: number, level: number) {
  const c = BY_ID[char_id];
  const s = cardStats(c, stars, level);
  return {
    side, idx, char_id, name: c.name, rarity: c.rarity,
    position: position === 'front' ? 'front' : 'back', ability: c.ability,
    atk: s.atk, def: s.def, spd: s.spd, maxhp: s.hp, hp: s.hp, actions: 0
  };
}
const rawDmg = (atk: number, def: number) => Math.max(1, Math.round(atk - def * DMG_K));

function simBattle(A: any[], B: any[]) {
  const log: any[] = [];
  let rounds = 0;
  const alive = (t: any[]) => t.filter((u) => u.hp > 0);
  const pickTarget = (enemies: any[]) => {
    const al = alive(enemies);
    if (!al.length) return null;
    const front = al.filter((u) => u.position === 'front');
    const pool = front.length ? front : al;
    return pool[Math.floor(Math.random() * pool.length)];
  };
  while (alive(A).length && alive(B).length && rounds < ROUND_CAP) {
    rounds++;
    const order = [...alive(A), ...alive(B)].sort((x, y) => y.spd - x.spd || Math.random() - 0.5);
    for (const actor of order) {
      if (actor.hp <= 0) continue;
      const enemies = actor.side === 'a' ? B : A;
      const allies = actor.side === 'a' ? A : B;
      if (!alive(enemies).length) break;
      actor.actions++;
      const cfg = actor.actions % EVERY_N === 0 ? ABIL_CFG[actor.ability] : null;
      const ev: any = { round: rounds, side: actor.side, actor: actor.idx, ability: cfg ? actor.ability : null };
      if (cfg?.type === 'heal') {
        const tgt = alive(allies).sort((p, q) => p.hp / p.maxhp - q.hp / q.maxhp)[0];
        const heal = Math.round(tgt.maxhp * cfg.frac);
        tgt.hp = Math.min(tgt.maxhp, tgt.hp + heal);
        Object.assign(ev, { action: 'heal', target: tgt.idx, heal });
      } else if (cfg?.type === 'self_heal') {
        const heal = Math.round(actor.maxhp * cfg.frac);
        actor.hp = Math.min(actor.maxhp, actor.hp + heal);
        Object.assign(ev, { action: 'guard', target: actor.idx, heal });
      } else if (cfg?.type === 'aoe') {
        const targets = alive(enemies).map((t) => {
          const dmg = rawDmg(actor.atk * cfg.mult, t.def);
          t.hp -= dmg;
          return { idx: t.idx, dmg };
        });
        Object.assign(ev, { action: 'aoe', targets });
      } else {
        const tgt = pickTarget(enemies);
        if (!tgt) break;
        const dmg = rawDmg(actor.atk * (cfg ? cfg.mult : 1), tgt.def);
        tgt.hp -= dmg;
        Object.assign(ev, { action: 'attack', target: tgt.idx, dmg });
      }
      log.push(ev);
      if (!alive(enemies).length) break;
    }
  }
  const aAlive = alive(A).length, bAlive = alive(B).length;
  let winner = 'draw';
  if (aAlive && !bAlive) winner = 'a';
  else if (bAlive && !aAlive) winner = 'b';
  else {
    const frac = (t: any[]) => t.reduce((s, u) => s + Math.max(0, u.hp), 0) / t.reduce((s, u) => s + u.maxhp, 0);
    winner = frac(A) >= frac(B) ? 'a' : 'b';
  }
  return { winner, rounds, log };
}

const sideSnap = (units: any[]) =>
  units.map((u) => ({ char_id: u.char_id, name: u.name, rarity: u.rarity, position: u.position, maxhp: u.maxhp }));

// ---------- состояние (in-memory) ----------
interface Rec {
  stars: number;
  level: number;
  exp: number;
  affection: number;
}
const owned: Record<string, Rec> = {
  r_cherry: { stars: 3, level: 12, exp: 0, affection: 4 },
  r_diamond: { stars: 2, level: 8, exp: 0, affection: 0 },
  sr_harvest: { stars: 4, level: 18, exp: 0, affection: 1 },
  sr_autumn: { stars: 2, level: 10, exp: 0, affection: 0 },
  ssr_noble: { stars: 1, level: 6, exp: 0, affection: 0 },
  ur_phoenix: { stars: 1, level: 5, exp: 0, affection: 2 }
};
const state = {
  gems: 25,
  cp_balance: 12000,
  pity_ssr: 12,
  pity_ur: 41,
  rate_up_lost: 0,
  gacha_rolls: 60,
  active_heroine: 'ur_phoenix',
  banner: 'ur_phoenix',
  daily_available: true,
  pvp_elo: 1040,
  pvp_wins: 7,
  pvp_losses: 4,
  team: null as null | { char_id: string; row: string }[]
};
const CP_PER_GEM = 300;
const ROLL_GEMS = 1;
const X10_GEMS = 9;
const SSR_PITY = 50;
const UR_PITY = 90;
const PET_LINES = ['Скучала по тебе ♥', 'Опять ты~ непоседа', 'Покрутишь ещё разок?', 'Ммм… нежнее.', 'Ты сегодня в ударе!'];

function rng<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)];
}

function pickRarity(): Rar {
  const x = Math.random();
  if (state.pity_ur + 1 >= UR_PITY || x < 0.02) return 'UR';
  if (state.pity_ssr + 1 >= SSR_PITY || x < 0.2) return 'SSR';
  if (x < 0.4) return 'SR';
  return 'SR';
}

function grant(id: string) {
  const c = BY_ID[id];
  const rec = owned[id];
  if (!rec) {
    owned[id] = { stars: 1, level: 1, exp: 0, affection: 0 };
    return { char_id: id, rarity: c.rarity, stars: 1, new: true, refund: 0 };
  }
  if (rec.stars < 5) {
    rec.stars += 1;
    return { char_id: id, rarity: c.rarity, stars: rec.stars, new: false, refund: 0 };
  }
  const refund = { R: 0, SR: 0, SSR: 1, UR: 5 }[c.rarity];
  return { char_id: id, rarity: c.rarity, stars: 5, new: false, refund };
}

function collectionItems() {
  return CHARS.map((c) => {
    const rec = owned[c.id];
    const stars = rec ? rec.stars : 0;
    const level = rec ? rec.level : 1;
    return {
      char_id: c.id,
      name: c.name,
      rarity: c.rarity,
      role: c.role,
      asset: asset(c.id),
      owned: !!rec,
      stars,
      base_value: c.base_value,
      affection: rec ? rec.affection : 0,
      bond: rec ? Math.floor(rec.affection / 10) : 0,
      level,
      exp: rec ? rec.exp : 0,
      exp_to_next: 50 * level,
      level_cap: LEVEL_CAP[Math.max(1, stars)] ?? 60,
      position: c.position,
      ability: c.ability,
      stats: cardStats(c, Math.max(1, stars), level),
      power: cardPower(c, Math.max(1, stars), level)
    };
  });
}

function teamSlots() {
  if (state.team && state.team.length) return state.team;
  return Object.keys(owned)
    .sort((a, b) => cardPower(BY_ID[b], owned[b].stars, owned[b].level) - cardPower(BY_ID[a], owned[a].stars, owned[a].level))
    .slice(0, 5)
    .map((id) => ({ char_id: id, row: BY_ID[id].position }));
}

function snapshot(slots: { char_id: string; row: string }[]) {
  return slots.map((s) => {
    const c = BY_ID[s.char_id];
    return { char_id: s.char_id, name: c.name, rarity: c.rarity, stars: owned[s.char_id]?.stars ?? 1, level: owned[s.char_id]?.level ?? 1, position: s.row };
  });
}

// ---------- роутер мока ----------
export async function mockRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const body = init.body ? JSON.parse(init.body as string) : {};
  await new Promise((r) => setTimeout(r, 120)); // имитация сети
  const out = route(path, body);
  return out as T;
}

function route(path: string, body: any): any {
  switch (path) {
    case '/me':
      return { user_id: 1, username: 'dev', balance: 50000, bank: 100000 };
    case '/balance':
      return { balance: 50000, bank: 100000 };
    case '/event':
      return {};
    case '/gacha/collection':
      return {
        items: collectionItems(),
        active_heroine: state.active_heroine,
        banner: state.banner,
        banner_until: new Date(Date.now() + 5.5 * 86400000).toISOString(),
        pity_ssr: state.pity_ssr,
        pity_ur: state.pity_ur,
        ssr_pity: SSR_PITY,
        ur_pity: UR_PITY,
        soft_pity: 75,
        gacha_rolls: state.gacha_rolls,
        rates: { UR: 2, SSR: 18, SR: 80 },
        banner_rateup: 50,
        daily_available: state.daily_available,
        team: teamSlots(),
        team_size: 5,
        gems: state.gems,
        cp_balance: state.cp_balance,
        roll_cost: ROLL_GEMS,
        x10_cost: X10_GEMS,
        cp_per_gem: CP_PER_GEM,
        daily_amount: 1,
        pvp_elo: state.pvp_elo,
        pvp_wins: state.pvp_wins,
        pvp_losses: state.pvp_losses
      };
    case '/gacha/roll': {
      const count = body.count === 10 ? 10 : 1;
      const price = count === 10 ? X10_GEMS : ROLL_GEMS;
      if (state.gems < price) throw new Error(`Нужно ${price} gems, у тебя ${state.gems}`);
      state.gems -= price;
      const results = [];
      let refund = 0;
      for (let i = 0; i < count; i++) {
        const rar = pickRarity();
        state.pity_ssr += 1;
        state.pity_ur += 1;
        const pool = CHARS.filter((c) => c.rarity === rar).map((c) => c.id);
        const id = rng(pool);
        if (rar === 'UR') {
          state.pity_ur = 0;
          state.pity_ssr = 0;
        } else if (rar === 'SSR') state.pity_ssr = 0;
        const g = grant(id);
        refund += g.refund;
        results.push({ ...g, name: BY_ID[id].name, asset: asset(id) });
      }
      state.gems += refund;
      state.gacha_rolls += count;
      return { results, spent: price, refunded: refund, pity_ssr: state.pity_ssr, pity_ur: state.pity_ur, gems: state.gems };
    }
    case '/gacha/daily': {
      if (!state.daily_available) throw new Error('Сегодня бонус уже получен');
      state.daily_available = false;
      state.gems += 1;
      return { claimed: true, amount: 1, gems: state.gems, daily_available: false };
    }
    case '/gacha/pet': {
      const rec = owned[body.char_id];
      if (!rec) throw new Error('Этого персонажа нет в коллекции');
      rec.affection += 1;
      return { char_id: body.char_id, affection: rec.affection, bond: Math.floor(rec.affection / 10), line: rng(PET_LINES) };
    }
    case '/gacha/heroine':
      state.active_heroine = body.char_id;
      return { active_heroine: body.char_id };
    case '/gacha/gems/buy': {
      const gems = Number(body.gems) || 0;
      const cost = gems * CP_PER_GEM;
      if (state.cp_balance < cost) throw new Error(`Нужно ${cost} cp, у тебя ${state.cp_balance}`);
      state.cp_balance -= cost;
      state.gems += gems;
      return { bought: gems, spent_cp: cost, gems: state.gems, cp_balance: state.cp_balance };
    }
    case '/gacha/team/set':
      state.team = (body.slots ?? []).map((s: any) => ({ char_id: s.char_id, row: s.row === 'front' ? 'front' : 'back' }));
      return { team: state.team };
    case '/gacha/arena': {
      const team = teamSlots();
      const A = team.map((s, i) =>
        buildUnit('a', i, s.char_id, s.row, owned[s.char_id]?.stars ?? 1, owned[s.char_id]?.level ?? 1)
      );
      const enemyChars = [...CHARS].sort(() => Math.random() - 0.5).slice(0, Math.min(5, Math.max(3, A.length)));
      const B = enemyChars.map((c, i) =>
        buildUnit('b', i, c.id, c.position, 1 + Math.floor(Math.random() * 5), 1 + Math.floor(Math.random() * 40))
      );
      const { winner, rounds, log } = simBattle(
        A.map((u) => ({ ...u })),
        B.map((u) => ({ ...u }))
      );
      const won = winner === 'a';
      const delta = won ? 14 : -11;
      state.pvp_elo += delta;
      if (won) {
        state.pvp_wins += 1;
        state.gems += 1;
      } else state.pvp_losses += 1;
      for (const s of team) if (owned[s.char_id]) owned[s.char_id].exp += won ? 120 : 45;
      return {
        result: won ? 'win' : 'loss',
        winner,
        rounds,
        log,
        sides: { a: sideSnap(A), b: sideSnap(B) },
        rewards: { gems: won ? 1 : 0, exp_each: won ? 120 : 45 },
        elo: state.pvp_elo,
        elo_delta: delta,
        gems: state.gems
      };
    }
    case '/gacha/pvp/queue':
      return { matched: false, queued: true, team: snapshot(teamSlots()) };
    case '/gacha/pvp/cancel':
      return { cancelled: true };
    case '/gacha/pvp/ladder':
      return {
        ladder: [
          { user_id: 1, name: 'ты (dev)', elo: state.pvp_elo, wins: state.pvp_wins, losses: state.pvp_losses },
          { user_id: 2, name: 'Соня', elo: 1180, wins: 14, losses: 3 },
          { user_id: 3, name: 'Гоша', elo: 990, wins: 5, losses: 9 }
        ].sort((a, b) => b.elo - a.elo)
      };
    case '/gacha/stars_invoice':
      return { url: '', stars: body.stars, hryvnia: body.stars * 300, rate: 300 };
    default:
      // неизвестный эндпоинт — пустой ок, чтобы ничего не падало
      console.warn('[devmock] unhandled', path, body);
      return {};
  }
}
