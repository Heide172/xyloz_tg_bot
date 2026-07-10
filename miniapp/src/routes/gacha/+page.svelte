<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import PixelImg from '$lib/PixelImg.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, openInvoice, showAlert } from '$lib/tg';
  import type { BalanceResponse } from '$lib/types';

  // ---------- данные ----------
  let balance: BalanceResponse | null = null;
  let col: any = null;
  let loading = true;
  let err: string | null = null;
  let busy = false;

  type Tab = 'home' | 'spin' | 'collection' | 'arena';
  let tab: Tab = 'home';

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  // ---------- редкости (конфиг FX из дизайн-сборки) ----------
  type Rar = 'R' | 'SR' | 'SSR' | 'UR';
  const RAR: Record<string, any> = {
    R:   { label: 'R',   color: '#b6bdc9', glow: 'rgba(182,189,201,.55)', soft: 'rgba(182,189,201,.12)', g1: '#3b414d', g2: '#20242c', rays: 10, parts: 18, t: { charge: 560, beam: 300, burst: 230 } },
    SR:  { label: 'SR',  color: '#4bb4ff', glow: 'rgba(75,180,255,.6)',   soft: 'rgba(75,180,255,.18)',  g1: '#0f4974', g2: '#0a2236', rays: 16, parts: 32, t: { charge: 820, beam: 680, burst: 340 } },
    SSR: { label: 'SSR', color: '#cf5bff', glow: 'rgba(207,91,255,.65)',  soft: 'rgba(207,91,255,.2)',   g1: '#511a78', g2: '#280a3a', rays: 26, parts: 50, t: { charge: 1080, beam: 1080, burst: 540 } },
    UR:  { label: 'UR',  color: '#ffb43a', glow: 'rgba(255,180,58,.72)',  soft: 'rgba(255,180,58,.22)',  g1: '#6f4910', g2: '#3a2606', rays: 42, parts: 74, t: { charge: 1500, beam: 1780, burst: 840 } }
  };
  const RANK: Record<Rar, number> = { R: 0, SR: 1, SSR: 2, UR: 3 };

  function buildFx(r: Rar) {
    const cfg = RAR[r];
    const rays = Array.from({ length: cfg.rays }, (_, i) => ({
      a: i * (360 / cfg.rays) + (Math.random() * 6 - 3),
      len: 38 + Math.random() * 52,
      w: r === 'UR' ? 3 + Math.random() * 3 : 2 + Math.random() * 1.6,
      delay: Math.random() * 0.12
    }));
    const parts = Array.from({ length: cfg.parts }, () => {
      const a = Math.random() * Math.PI * 2;
      const d = 60 + Math.random() * 200;
      const di = 150 + Math.random() * 120;
      return {
        tx: Math.cos(a) * d, ty: Math.sin(a) * d,
        fx: Math.cos(a) * di, fy: Math.sin(a) * di,
        s: 3 + Math.random() * 6, delay: Math.random() * 0.25, dur: 0.6 + Math.random() * 0.7
      };
    });
    return { rarity: r, color: cfg.color, glow: cfg.glow, soft: cfg.soft, g1: cfg.g1, g2: cfg.g2, rays, parts };
  }

  // спицы «колеса лучей» вокруг карточки (SSR/UR)
  function wheelSpokes(r: Rar) {
    const n = r === 'UR' ? 24 : 16;
    return Array.from({ length: n }, (_, i) => i * (360 / n));
  }
  function sparkleList(n: number) {
    return Array.from({ length: n }, () => ({
      top: 10 + Math.random() * 80,
      left: 8 + Math.random() * 84,
      s: 4 + Math.random() * 5,
      dur: 1.4 + Math.random() * 1.4,
      delay: Math.random() * 1.2
    }));
  }

  // ---------- загрузка ----------
  async function refresh() {
    try {
      [balance, col] = await Promise.all([api.balance(), api.gachaCollection()]);
      if (col && !teamInit) {
        teamSlots = (col.team ?? []).map((s: any) => ({ char_id: s.char_id, row: s.row }));
        savedTeamKey = teamKey(teamSlots);
        teamInit = true;
      }
    } catch (e: any) {
      err = e?.message;
    } finally {
      loading = false;
    }
  }
  onMount(refresh);

  function charById(id: string) {
    return col?.items?.find((i: any) => i.char_id === id);
  }
  const FALLBACK = '/farm/heroine_idle.png';
  function imgErr(e: Event) {
    const el = e.target as HTMLImageElement;
    if (el && el.src.indexOf(FALLBACK) === -1) el.src = FALLBACK;
  }
  $: bannerChar = col ? charById(col.banner) : null;

  // ---------- крутка + анимация призыва ----------
  type Phase = 'idle' | 'launch' | 'beam' | 'burst' | 'reveal' | 'grid';
  let phase: Phase = 'idle';
  let fx: any = null;
  let batch: any[] = []; // реальные результаты с бэка
  let lastRefund = 0;
  let timers: any[] = [];

  function clearTimers() {
    timers.forEach((t) => clearTimeout(t));
    timers = [];
  }

  function bestRarity(results: any[]): Rar {
    return results.reduce<Rar>((acc, r) => (RANK[r.rarity as Rar] > RANK[acc] ? (r.rarity as Rar) : acc), 'R');
  }

  async function pull(count: number) {
    if (busy || phase !== 'idle') return;
    busy = true;
    lastRefund = 0;
    // мгновенно показываем «зарядку» (нейтральный FX), пока летит запрос
    fx = buildFx('SR');
    batch = [];
    phase = 'launch';
    haptic('medium');
    let r: any;
    try {
      r = await api.gachaRoll(count);
    } catch (e: any) {
      phase = 'idle';
      fx = null;
      busy = false;
      haptic('error');
      showAlert(e?.message ?? 'Ошибка');
      return;
    }
    if (col) col = { ...col, gems: r.gems };
    batch = r.results;
    lastRefund = r.refunded ?? 0;
    const best = bestRarity(r.results);
    fx = buildFx(best);
    const cfg = RAR[best];
    haptic(best === 'UR' || best === 'SSR' ? 'success' : 'light');

    clearTimers();
    let acc = 0;
    acc += cfg.t.charge;
    timers.push(setTimeout(() => (phase = 'beam'), acc));
    acc += cfg.t.beam;
    timers.push(setTimeout(() => (phase = 'burst'), acc));
    acc += cfg.t.burst;
    timers.push(
      setTimeout(() => {
        phase = count === 10 ? 'grid' : 'reveal';
      }, acc)
    );
    busy = false;
  }

  function skip() {
    if (!batch.length) return; // ещё ждём ответ — пропускать нечего
    clearTimers();
    phase = batch.length === 10 ? 'grid' : 'reveal';
  }

  async function closePull() {
    clearTimers();
    phase = 'idle';
    fx = null;
    batch = [];
    const refund = lastRefund;
    lastRefund = 0;
    await refresh();
    if (refund > 0) showAlert(`Дубли 5★ → возврат ${fmtCoins(refund)}`);
  }

  function againX1() {
    closePull().then(() => setTimeout(() => pull(1), 80));
  }

  // ---------- детальная карточка + «приласкать» ----------
  let detail: any = null;
  let detailLine: string | null = null;
  let hearts: any[] = [];
  let heartTimer: any = null;
  let petBusy = false;

  function openDetail(it: any) {
    if (!it.owned) return;
    detail = it;
    detailLine = null;
    hearts = [];
  }
  function closeDetail() {
    detail = null;
    detailLine = null;
    hearts = [];
    clearTimeout(heartTimer);
  }

  async function pet() {
    if (!detail || petBusy) return;
    petBusy = true;
    // визуальные сердечки сразу
    hearts = Array.from({ length: 12 }, (_, i) => ({
      id: Date.now() + i,
      hx: Math.random() * 150 - 75,
      dur: 1 + Math.random() * 0.7,
      delay: Math.random() * 0.35,
      s: 13 + Math.random() * 16,
      left: 18 + Math.random() * 64
    }));
    haptic('light');
    clearTimeout(heartTimer);
    heartTimer = setTimeout(() => (hearts = []), 1800);
    try {
      const r = await api.gachaPet(detail.char_id);
      detailLine = r.line;
      // обновим привязанность в открытой карточке и в коллекции
      detail = { ...detail, affection: r.affection, bond: r.bond };
      if (col) {
        col = {
          ...col,
          items: col.items.map((x: any) =>
            x.char_id === detail.char_id ? { ...x, affection: r.affection, bond: r.bond } : x
          )
        };
      }
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      petBusy = false;
    }
  }

  async function setHeroine(id: string) {
    if (busy) return;
    busy = true;
    try {
      await api.gachaSetHeroine(id);
      haptic('success');
      await refresh();
      if (detail) detail = charById(id) ?? detail;
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      busy = false;
    }
  }

  // ---------- ежедневный бонус ----------
  let dailyBusy = false;
  async function claimDaily() {
    if (dailyBusy || !col?.daily_available) return;
    dailyBusy = true;
    try {
      const r = await api.gachaDaily();
      col = { ...col, daily_available: false, gems: r.gems };
      haptic('success');
      toast(`Получено +${fmtCoins(r.amount)} ◆`);
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      dailyBusy = false;
    }
  }

  // ---------- поддержать (звёзды → гривны) ----------
  const STAR_PACKS = [1, 5, 25, 100];
  let donateOpen = false;
  let donateBusy = false;
  async function donate(stars: number) {
    if (donateBusy) return;
    donateBusy = true;
    try {
      const inv = await api.gachaStarsInvoice(stars);
      const status = await openInvoice(inv.url);
      if (status === 'paid') {
        haptic('success');
        showAlert(`Спасибо! +${inv.hryvnia}г будет на балансе через пару секунд.`);
        setTimeout(refresh, 1500);
        donateOpen = false;
      } else if (status === 'cancelled') {
        haptic('light');
      } else if (status === 'unsupported') {
        showAlert('Открой страницу в Telegram, чтобы оплатить звёздами.');
      } else if (status === 'failed') {
        haptic('error');
        showAlert('Не получилось открыть оплату — попробуй ещё раз.');
      }
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      donateBusy = false;
    }
  }

  // ---------- gems: покупка за cp ----------
  let buyGemsOpen = false;
  let buyGemsBusy = false;
  const GEM_PACKS = [1, 10, 50];
  async function buyGems(qty: number) {
    if (buyGemsBusy) return;
    buyGemsBusy = true;
    try {
      const r = await api.gachaBuyGems(qty);
      col = { ...col, gems: r.gems, cp_balance: r.cp_balance };
      haptic('success');
      toast(`+${fmtCoins(r.bought)} ◆ (−${fmtCoins(r.spent_cp)} cp)`);
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      buyGemsBusy = false;
    }
  }

  // ---------- арена: пиксельный бой с проигрыванием лога ----------
  let arenaBusy = false;
  let ladder: any[] | null = null;
  let showRoster = false; // тоггл редактора состава

  interface Unit {
    char_id: string;
    name: string;
    rarity: string;
    position: string;
    maxhp: number;
    hp: number;
    dead: boolean;
    attacking: boolean;
    hit: boolean;
    healing: boolean;
    pop: string | null;
    popKind: string;
    popKey: number;
  }
  let unitsA: Unit[] = [];
  let unitsB: Unit[] = [];
  let playing = false;
  let battleBanner: 'win' | 'loss' | null = null;
  let battleInfo: string | null = null;

  const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const artOf = (cid: string) => itemMap[cid]?.asset ?? `/gacha/${cid}.webp`;
  // чиби-спрайт, если положен в /gacha/sprites/<id>.png; иначе откат на портрет
  const spriteOf = (cid: string) => `/gacha/sprites/${cid}.png`;

  // суммарная HP вражеской стороны — для «боссовой» полосы
  $: enemyHpPct =
    unitsB.length
      ? (unitsB.reduce((s, u) => s + Math.max(0, u.hp), 0) /
          unitsB.reduce((s, u) => s + u.maxhp, 0)) *
        100
      : 100;

  function mkUnit(u: any): Unit {
    return {
      char_id: u.char_id, name: u.name, rarity: u.rarity, position: u.position,
      maxhp: u.maxhp, hp: u.maxhp, dead: false, attacking: false, hit: false,
      healing: false, pop: null, popKind: '', popKey: 0
    };
  }

  function applyHit(units: Unit[], idx: number, dmg: number) {
    const u = units[idx];
    if (!u || u.dead) return;
    u.hp = Math.max(0, u.hp - dmg);
    u.hit = true;
    u.pop = `-${dmg}`;
    u.popKind = 'dmg';
    u.popKey++;
    if (u.hp <= 0) u.dead = true;
    unitsA = unitsA;
    unitsB = unitsB;
    setTimeout(() => {
      u.hit = false;
      unitsA = unitsA;
      unitsB = unitsB;
    }, 200);
  }
  function applyHeal(units: Unit[], idx: number, heal: number) {
    const u = units[idx];
    if (!u || u.dead) return;
    u.hp = Math.min(u.maxhp, u.hp + heal);
    u.healing = true;
    u.pop = `+${heal}`;
    u.popKind = 'heal';
    u.popKey++;
    unitsA = unitsA;
    unitsB = unitsB;
    setTimeout(() => {
      u.healing = false;
      unitsA = unitsA;
      unitsB = unitsB;
    }, 350);
  }

  async function playBattle(res: any) {
    playing = true;
    battleBanner = null;
    battleInfo = null;
    unitsA = (res.sides?.a ?? []).map(mkUnit);
    unitsB = (res.sides?.b ?? []).map(mkUnit);
    await delay(450);
    for (const ev of res.log ?? []) {
      const actors = ev.side === 'a' ? unitsA : unitsB;
      const foes = ev.side === 'a' ? unitsB : unitsA;
      const actor = actors[ev.actor];
      if (actor && !actor.dead) {
        actor.attacking = true;
        unitsA = unitsA;
        unitsB = unitsB;
      }
      await delay(150);
      if (ev.action === 'attack') applyHit(foes, ev.target, ev.dmg);
      else if (ev.action === 'aoe') for (const t of ev.targets ?? []) applyHit(foes, t.idx, t.dmg);
      else if (ev.action === 'heal' || ev.action === 'guard') applyHeal(actors, ev.target, ev.heal);
      if (actor) {
        actor.attacking = false;
        unitsA = unitsA;
        unitsB = unitsB;
      }
      await delay(130);
    }
    battleBanner = res.result;
    const rw = res.rewards;
    battleInfo = `${res.rounds} раундов · +${rw?.gems ?? 0} ◆ · +${rw?.exp_each ?? 0} exp · ELO ${res.elo} (${res.elo_delta >= 0 ? '+' : ''}${res.elo_delta})`;
    if (col) col = { ...col, gems: res.gems };
    haptic(res.result === 'win' ? 'success' : 'warning');
    playing = false;
    refresh();
  }

  async function fightArena() {
    if (arenaBusy || playing) return;
    arenaBusy = true;
    try {
      if (teamDirty) await saveTeam();
      const r = await api.gachaArena();
      await playBattle(r);
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      arenaBusy = false;
    }
  }

  async function matchmake() {
    if (arenaBusy || playing) return;
    arenaBusy = true;
    try {
      if (teamDirty) await saveTeam();
      const r = await api.gachaPvpQueue();
      if (r.matched && r.sides) await playBattle(r);
      else toast('В очереди — бой начнётся, как найдётся соперник');
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      arenaBusy = false;
    }
  }

  async function openLadder() {
    try {
      const r = await api.gachaPvpLadder();
      ladder = r.ladder;
    } catch {
      ladder = [];
    }
  }

  // ---------- сборка команды ----------
  let teamSlots: { char_id: string; row: string }[] = [];
  let savedTeamKey = '';
  let teamInit = false;
  let teamSaving = false;

  const teamKey = (slots: { char_id: string; row: string }[]) =>
    slots.map((s) => `${s.char_id}:${s.row}`).join('|');

  $: teamSizeMax = col?.team_size ?? 5;
  $: itemMap = col ? Object.fromEntries(col.items.map((i: any) => [i.char_id, i])) : {};
  $: ownedItems = col ? col.items.filter((i: any) => i.owned) : [];
  $: teamDirty = teamKey(teamSlots) !== savedTeamKey;
  $: teamPower = teamSlots.reduce((s, sl) => s + (itemMap[sl.char_id]?.power ?? 0), 0);
  $: frontSlots = teamSlots.filter((s) => s.row === 'front');
  $: backSlots = teamSlots.filter((s) => s.row === 'back');

  function addToTeam(it: any) {
    if (teamSlots.some((s) => s.char_id === it.char_id)) return;
    if (teamSlots.length >= teamSizeMax) {
      toast(`Максимум ${teamSizeMax} карт`);
      return;
    }
    teamSlots = [...teamSlots, { char_id: it.char_id, row: it.position || 'back' }];
    haptic('light');
  }
  function removeFromTeam(cid: string) {
    teamSlots = teamSlots.filter((s) => s.char_id !== cid);
    haptic('light');
  }
  function toggleRow(cid: string) {
    teamSlots = teamSlots.map((s) =>
      s.char_id === cid ? { ...s, row: s.row === 'front' ? 'back' : 'front' } : s
    );
    haptic('light');
  }
  async function saveTeam() {
    if (teamSaving || !teamSlots.length) return;
    teamSaving = true;
    try {
      const r = await api.gachaSetTeam(teamSlots);
      teamSlots = r.team.map((s) => ({ char_id: s.char_id, row: s.row }));
      savedTeamKey = teamKey(teamSlots);
      haptic('success');
      toast('Состав сохранён');
      refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      teamSaving = false;
    }
  }

  // ---------- баннер: превью + обратный отсчёт ----------
  let showPreview = false;
  let now = Date.now();
  let nowTimer: any = null;
  onMount(() => {
    nowTimer = setInterval(() => (now = Date.now()), 60_000);
  });
  onDestroy(() => {
    clearInterval(nowTimer);
    clearTimers();
    clearTimeout(heartTimer);
  });

  $: bannerTimer = (() => {
    if (!col?.banner_until) return null;
    const end = new Date(col.banner_until).getTime();
    const diff = end - now;
    if (isNaN(end) || diff <= 0) return null;
    const d = Math.floor(diff / 86_400_000);
    const h = Math.floor((diff % 86_400_000) / 3_600_000);
    return `${d}д ${h}ч`;
  })();

  $: ssrPct = col ? Math.min(100, Math.round((col.pity_ssr / col.ssr_pity) * 100)) : 0;
  $: urPct = col ? Math.min(100, Math.round((col.pity_ur / col.ur_pity) * 100)) : 0;
  $: ssrLeft = col ? Math.max(0, col.ssr_pity - col.pity_ssr) : 0;
  $: poolList = col ? col.items.filter((i: any) => i.rarity === 'UR') : [];

  // ---------- toast ----------
  let toastMsg: string | null = null;
  let toastTimer: any = null;
  function toast(msg: string) {
    toastMsg = msg;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toastMsg = null), 1700);
  }

  function fmtBalance(n: number | undefined) {
    return (n ?? 0).toLocaleString('ru-RU');
  }

  const ABIL: Record<string, string> = {
    heavy_strike: 'Тяжёлый удар',
    crit: 'Критический',
    aoe: 'Залп',
    heal: 'Исцеление',
    guard: 'Защита'
  };
</script>

<svelte:head>
  <link rel="stylesheet" href="/gacha/fonts.css" />
  <link rel="stylesheet" href="/gacha/fx.css" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link
    rel="stylesheet"
    href="https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@400..700&family=Press+Start+2P&display=swap"
  />
</svelte:head>

<div class="g-root">
  <!-- шапка -->
  <div class="g-head">
    <div class="g-bal">
      <div class="g-diamond">◆</div>
      <div class="g-bal-txt">
        <span class="g-bal-cap">Gems</span>
        <span class="g-bal-num">{fmtBalance(col?.gems)}</span>
      </div>
      <button class="g-buygems" on:click={() => (buyGemsOpen = true)} title="Купить gems за cp">+</button>
    </div>
    <div class="g-head-right">
      {#if col}<span class="g-cp" title="cp фермы">{fmtBalance(col.cp_balance)} cp</span>{/if}
      <a class="g-icon" href={`/farm${search}`} title="К ферме">✿</a>
    </div>
  </div>

  <!-- вкладки -->
  <div class="g-tabs">
    <button class="g-tab" class:on={tab === 'home'} on:click={() => (tab = 'home')}>Меню</button>
    <button class="g-tab" class:on={tab === 'spin'} on:click={() => (tab = 'spin')}>Крутка</button>
    <button class="g-tab" class:on={tab === 'collection'} on:click={() => (tab = 'collection')}>Коллекция</button>
    <button class="g-tab" class:on={tab === 'arena'} on:click={() => (tab = 'arena')}>Арена</button>
  </div>

  <div class="scrollY g-scroll">
    {#if loading}
      <div class="g-muted" style="padding:24px 16px;">Загрузка…</div>
    {:else if err}
      <div class="g-muted" style="padding:24px 16px;color:#ff8a80;">{err}</div>
    {:else if col}
      <!-- ===================== МЕНЮ ===================== -->
      {#if tab === 'home'}
        <div class="g-pad">
          <div class="g-daily">
            <div class="g-daily-ic">🎁</div>
            <div class="g-daily-txt">
              <div class="g-daily-h">Ежедневный бонус</div>
              <div class="g-sub">Заходи каждый день — копи на крутку</div>
            </div>
            <button
              class="g-daily-btn"
              class:claimed={!col.daily_available}
              disabled={dailyBusy || !col.daily_available}
              on:click={claimDaily}
            >
              {col.daily_available ? `+${fmtCoins(col.daily_amount)} ◆` : 'Получено ✓'}
            </button>
          </div>

          <button class="g-banner home" on:click={() => (showPreview = true)}>
            <img class="g-banner-art" src="/gacha/banner.webp" alt="banner" on:error={imgErr} />
            <div class="g-banner-grad"></div>
            <div class="g-banner-tag">UR · РЕЙТ-АП</div>
            {#if bannerTimer}
              <div class="g-banner-timer"><span>⏳</span>{bannerTimer}</div>
            {/if}
            <div class="g-banner-info">
              <div class="g-banner-kicker">Лимитный баннер</div>
              <div class="g-banner-name">{bannerChar?.name ?? 'Рейт-ап'}</div>
              <div class="g-banner-lore">Повышенный шанс UR-героини в крутке</div>
              <div class="g-banner-more">Подробнее →</div>
            </div>
          </button>

          <div class="g-actions">
            <button class="g-act act-spin" on:click={() => (tab = 'spin')}>
              <span class="g-act-ic ic-gold">✦</span>
              <span class="g-act-txt"><b>Крутить</b><small>Призыв персонажей</small></span>
            </button>
            <button class="g-act act-coll" on:click={() => (tab = 'collection')}>
              <span class="g-act-ic ic-purple">❖</span>
              <span class="g-act-txt"><b>Коллекция</b><small>15 героинь в пуле</small></span>
            </button>
            <a class="g-act act-farm" href={`/farm${search}`}>
              <span class="g-act-ic ic-green">✿</span>
              <span class="g-act-txt"><b>Ферма</b><small>Доход ср/ур</small></span>
            </a>
            <button class="g-act act-arena" on:click={() => (tab = 'arena')}>
              <span class="g-act-ic ic-red">⚔</span>
              <span class="g-act-txt"><b>Арена</b><small>Состав и бой 5×5</small></span>
            </button>
            <button class="g-act act-support" on:click={() => (donateOpen = true)}>
              <span class="g-act-ic ic-gold">★</span>
              <span class="g-act-txt"><b>Поддержать</b><small>Звёзды → гривны</small></span>
            </button>
          </div>

          <div class="g-foot">тест-сборка · гача</div>
        </div>
      {/if}

      <!-- ===================== КРУТКА ===================== -->
      {#if tab === 'spin'}
        <div class="g-pad">
          <div class="g-banner spin">
            <img class="g-banner-art" src="/gacha/banner.webp" alt="banner" on:error={imgErr} />
            <div class="g-banner-grad"></div>
            <div class="g-banner-tag">UR · РЕЙТ-АП</div>
            {#if bannerTimer}
              <div class="g-banner-timer"><span>⏳</span>{bannerTimer}</div>
            {/if}
            <div class="g-banner-info">
              <div class="g-banner-kicker">Лимитный призыв</div>
              <div class="g-banner-name">{bannerChar?.name ?? 'Рейт-ап'}</div>
              <div class="g-banner-lore">Повышенный шанс этой UR в крутке</div>
            </div>
          </div>

          <div class="g-pity-row">
            <div class="g-pity-bar"><div class="g-pity-fill ssr" style="width:{ssrPct}%"></div></div>
            <span class="g-pity-cap">Гарант SSR через {ssrLeft}</span>
          </div>

          <div class="g-pull-btns">
            <button class="g-pull x1" disabled={busy} on:click={() => pull(1)}>
              <span class="g-pull-h">Крутить ×1</span>
              <span class="g-pull-c gold">◆ {fmtCoins(col.roll_cost)}</span>
            </button>
            <button class="g-pull x10" disabled={busy} on:click={() => pull(10)}>
              <span class="g-pull-h">Крутить ×10</span>
              <span class="g-pull-c">◆ {fmtCoins(col.x10_cost)}</span>
              <span class="g-pull-badge">SR+ гарант</span>
            </button>
          </div>

          <div class="g-rates">
            <span style="color:#ffb43a;">UR {col.rates?.UR ?? 2}%</span>
            <span style="color:#cf5bff;">SSR {col.rates?.SSR ?? 18}%</span>
            <span style="color:#4bb4ff;">SR {col.rates?.SR ?? 80}%</span>
          </div>
        </div>
      {/if}

      <!-- ===================== КОЛЛЕКЦИЯ ===================== -->
      {#if tab === 'collection'}
        <div class="g-pad coll">
          <div class="g-grid">
            {#each col.items as it, idx (it.char_id)}
              <button
                class="g-cell rar-{it.rarity}"
                class:locked={!it.owned}
                class:active={col.active_heroine === it.char_id}
                style="--g1:{RAR[it.rarity].g1};--g2:{RAR[it.rarity].g2};--rc:{RAR[it.rarity].color};--soft:{RAR[it.rarity].soft};animation-delay:{idx * 0.17}s"
                on:click={() => openDetail(it)}
              >
                <div class="g-cell-art">
                  <img src={it.asset} alt={it.name} class:dim={!it.owned} on:error={imgErr} />
                  {#if col.active_heroine === it.char_id}<div class="g-cell-act">активна</div>{/if}
                </div>
                <div class="g-cell-rar" style="color:{RAR[it.rarity].color}">{it.rarity}</div>
                <div class="g-cell-name">{it.name}</div>
                {#if it.owned}
                  <div class="g-cell-stars"><span class="f">{'★'.repeat(it.stars)}</span><span class="e">{'☆'.repeat(5 - it.stars)}</span></div>
                {:else}
                  <div class="g-cell-locked">не открыта</div>
                {/if}
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- ===================== АРЕНА (СБОРКА + БОЙ) ===================== -->
      {#if tab === 'arena'}
        <div class="g-pad px-wrap">
          <div class="g-team-head">
            <div>
              <b class="px-title">АРЕНА</b>
              <div class="g-sub">💪 {fmtCoins(teamPower)} · ELO {col.pvp_elo} ({col.pvp_wins}/{col.pvp_losses})</div>
            </div>
            {#if showRoster}
              <button class="g-save" disabled={!teamDirty || teamSaving} on:click={saveTeam}>
                {teamDirty ? 'Сохранить' : '✓'}
              </button>
            {/if}
          </div>

          <!-- пиксельная сцена боя (сайд-вью, как TBH) -->
          <div class="px-stage">
            <div class="px-bg sky"></div>
            <div class="px-bg hills"></div>
            <div class="px-bg trees"></div>
            <div class="px-ground"></div>

            <!-- боссовая HP-полоса врага -->
            <div class="px-boss">
              <span class="px-boss-skull">☠</span>
              <div class="px-boss-bar"><div class="px-boss-fill" style="width:{enemyHpPct}%"></div></div>
              <span class="px-boss-tag">АКТ 1</span>
            </div>

            <div class="px-field">
              <!-- враги слева, лицом вправо -->
              <div class="px-group foe">
                {#if unitsB.length}
                  {#each unitsB as u, i (i)}
                    <div class="px-fig foe" class:dead={u.dead} class:atk={u.attacking} class:hit={u.hit} class:heal={u.healing}>
                      {#if u.pop}{#key u.popKey}<div class="px-pop {u.popKind}">{u.pop}</div>{/key}{/if}
                      <div class="px-hp"><div class="px-hp-fill" style="width:{u.maxhp ? (u.hp / u.maxhp) * 100 : 0}%"></div></div>
                      <div class="px-sprite foe" style="--rc:{RAR[u.rarity]?.color ?? '#888'}">
                        <PixelImg src={spriteOf(u.char_id)} fallback={artOf(u.char_id)} px={56} alt={u.name} />
                      </div>
                      <div class="px-shadow"></div>
                    </div>
                  {/each}
                {:else}
                  <div class="px-fig foe idle-foe">
                    <div class="px-sprite foe boss"><span class="px-skull">☠</span></div>
                    <div class="px-shadow"></div>
                  </div>
                {/if}
              </div>

              <!-- герои справа, лицом влево -->
              <div class="px-group hero">
                {#if unitsA.length}
                  {#each unitsA as u, i (i)}
                    <div class="px-fig hero" class:dead={u.dead} class:atk={u.attacking} class:hit={u.hit} class:heal={u.healing}>
                      {#if u.pop}{#key u.popKey}<div class="px-pop {u.popKind}">{u.pop}</div>{/key}{/if}
                      <div class="px-hp"><div class="px-hp-fill" style="width:{u.maxhp ? (u.hp / u.maxhp) * 100 : 0}%"></div></div>
                      <div class="px-sprite hero" style="--rc:{RAR[u.rarity]?.color ?? '#888'}">
                        <PixelImg src={spriteOf(u.char_id)} fallback={artOf(u.char_id)} px={56} alt={u.name} />
                      </div>
                      <div class="px-shadow"></div>
                    </div>
                  {/each}
                {:else if teamSlots.length}
                  {#each teamSlots as s (s.char_id)}
                    {@const it = itemMap[s.char_id]}
                    <div class="px-fig hero">
                      <div class="px-sprite hero" style="--rc:{RAR[it?.rarity]?.color ?? '#888'}">
                        <PixelImg src={spriteOf(s.char_id)} fallback={artOf(s.char_id)} px={56} alt={it?.name} />
                      </div>
                      <div class="px-shadow"></div>
                    </div>
                  {/each}
                {:else}
                  <div class="px-empty">Собери состав ↓</div>
                {/if}
              </div>
            </div>

            {#if battleBanner}
              <div class="px-banner {battleBanner}">{battleBanner === 'win' ? 'ПОБЕДА' : 'ПОРАЖЕНИЕ'}</div>
            {/if}
          </div>
          {#if battleInfo}<div class="px-info">{battleInfo}</div>{/if}

          <div class="g-arena-fight">
            <button class="g-pull x10" disabled={arenaBusy || playing || !teamSlots.length} on:click={fightArena}>
              <span class="g-pull-h">⚔ В бой</span>
              <span class="g-pull-c">{playing ? 'идёт…' : '×бот'}</span>
            </button>
            <button class="g-pull x1" disabled={arenaBusy || playing || !teamSlots.length} on:click={matchmake}>
              <span class="g-pull-h">Матчмейк</span>
              <span class="g-pull-c gold">PvP</span>
            </button>
          </div>
          <div class="g-arena-row">
            <button class="g-ladder-btn" on:click={openLadder}>🏆 Ладдер</button>
            <button class="g-ladder-btn" on:click={() => (showRoster = !showRoster)}>
              {showRoster ? 'Скрыть состав' : '⚙ Состав'}
            </button>
          </div>
          {#if ladder}
            <div class="g-ladder">
              {#each ladder as row, i (row.user_id)}
                <div class="g-ladder-row"><span>{i + 1}. {row.name}</span><span>{row.elo} · {row.wins}/{row.losses}</span></div>
              {/each}
              {#if !ladder.length}<div class="g-sub" style="text-align:center">Пока пусто</div>{/if}
            </div>
          {/if}

          {#if showRoster}
            <div class="g-form">
              <div class="g-form-row">
                <div class="g-form-cap">🛡 Фронт <span class="g-sub">принимает удар первым</span></div>
                <div class="g-form-slots">
                  {#each frontSlots as s (s.char_id)}
                    {@const it = itemMap[s.char_id]}
                    <div class="g-tcard" style="border-color:{RAR[it?.rarity]?.color ?? '#555'}">
                      <img src={it?.asset} alt={it?.name} on:error={imgErr} />
                      <div class="g-tcard-name">{it?.name}</div>
                      <div class="g-tcard-ctl">
                        <button on:click={() => toggleRow(s.char_id)} title="в бэк">↧</button>
                        <button on:click={() => removeFromTeam(s.char_id)} title="убрать">✕</button>
                      </div>
                    </div>
                  {/each}
                  {#if !frontSlots.length}<div class="g-form-empty">пусто — поставь танков сюда</div>{/if}
                </div>
              </div>
              <div class="g-form-row">
                <div class="g-form-cap">🎯 Бэк <span class="g-sub">бьёт из-за фронта</span></div>
                <div class="g-form-slots">
                  {#each backSlots as s (s.char_id)}
                    {@const it = itemMap[s.char_id]}
                    <div class="g-tcard" style="border-color:{RAR[it?.rarity]?.color ?? '#555'}">
                      <img src={it?.asset} alt={it?.name} on:error={imgErr} />
                      <div class="g-tcard-name">{it?.name}</div>
                      <div class="g-tcard-ctl">
                        <button on:click={() => toggleRow(s.char_id)} title="во фронт">↥</button>
                        <button on:click={() => removeFromTeam(s.char_id)} title="убрать">✕</button>
                      </div>
                    </div>
                  {/each}
                  {#if !backSlots.length}<div class="g-form-empty">пусто — дамагеры сюда</div>{/if}
                </div>
              </div>
            </div>
            <div class="g-roster-h">Твои карты — нажми, чтобы добавить/убрать</div>
            {#if !ownedItems.length}
              <div class="g-sub" style="padding:8px 2px">Пока нет карт — собери их в крутке.</div>
            {/if}
            <div class="g-roster">
              {#each ownedItems as it (it.char_id)}
                {@const inTeam = teamSlots.some((s) => s.char_id === it.char_id)}
                <button
                  class="g-rcard"
                  class:inteam={inTeam}
                  style="border-color:{RAR[it.rarity].color}"
                  on:click={() => (inTeam ? removeFromTeam(it.char_id) : addToTeam(it))}
                >
                  <img src={it.asset} alt={it.name} on:error={imgErr} />
                  <span class="g-rcard-lvl">Ур{it.level}</span>
                  {#if inTeam}<span class="g-rcard-on">✓</span>{/if}
                </button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>

  <!-- ===================== ПРЕВЬЮ БАННЕРА ===================== -->
  {#if showPreview}
    <div class="g-preview">
      <div class="g-pv-head">
        <button class="g-pv-back" on:click={() => (showPreview = false)}>←</button>
        <span class="g-pv-title">Баннер призыва</span>
        {#if bannerTimer}<div class="g-banner-timer"><span>⏳</span>{bannerTimer}</div>{:else}<div style="width:36px"></div>{/if}
      </div>
      <div class="scrollY g-pv-scroll">
        <div class="g-pv-art">
          <img src="/gacha/banner.webp" alt="banner" on:error={imgErr} />
          <div class="g-pv-grad"></div>
          <div class="g-banner-tag">UR · РЕЙТ-АП</div>
          <div class="g-pv-info">
            <div class="g-banner-kicker">Лимитный призыв</div>
            <div class="g-pv-name">{bannerChar?.name ?? 'Рейт-ап'}</div>
            <div class="g-pv-lore">В дни баннера её шанс выпадения повышен. Баннерная UR забирает {col.banner_rateup ?? 50}% всех UR-выпадений.</div>
          </div>
        </div>

        <div class="g-pv-rates">
          <div class="g-pv-rate" style="--c:#ffb43a"><b>{col.rates?.UR ?? 2}%</b><small>UR</small></div>
          <div class="g-pv-rate" style="--c:#cf5bff"><b>{col.rates?.SSR ?? 18}%</b><small>SSR</small></div>
          <div class="g-pv-rate" style="--c:#4bb4ff"><b>{col.rates?.SR ?? 80}%</b><small>SR</small></div>
        </div>

        <div class="g-pv-pity">
          <div class="g-pv-pity-row"><span>Гарант SSR</span><span style="color:#cf5bff">{col.pity_ssr} / {col.ssr_pity}</span></div>
          <div class="g-pv-track"><div class="g-pv-fill ssr" style="width:{ssrPct}%"></div></div>
          <div class="g-pv-pity-row" style="margin-top:14px"><span>Гарант UR</span><span style="color:#ffb43a">{col.pity_ur} / {col.ur_pity}</span></div>
          <div class="g-pv-track"><div class="g-pv-fill ur" style="width:{urPct}%"></div></div>
        </div>

        <div class="g-pv-pool">
          <div class="g-pv-pool-h">UR-героини в пуле</div>
          <div class="g-pv-pool-row">
            {#each poolList as p (p.char_id)}
              <div class="g-pv-pool-item">
                <div class="g-pv-pool-art" style="border-color:{RAR[p.rarity].color};box-shadow:0 0 14px {RAR[p.rarity].soft}">
                  <img src={p.asset} alt={p.name} class:dim={!p.owned} on:error={imgErr} />
                </div>
                <div class="g-pv-pool-name">{p.name}</div>
              </div>
            {/each}
          </div>
        </div>
      </div>

      <div class="g-pv-foot">
        <button class="g-pull x1" disabled={busy} on:click={() => { showPreview = false; pull(1); }}>
          <span class="g-pull-h">Крутить ×1</span>
          <span class="g-pull-c gold">◆ {fmtCoins(col.roll_cost)}</span>
        </button>
        <button class="g-pull x10" disabled={busy} on:click={() => { showPreview = false; pull(10); }}>
          <span class="g-pull-h">Крутить ×10</span>
          <span class="g-pull-c">◆ {fmtCoins(col.x10_cost)}</span>
          <span class="g-pull-badge">SR+ гарант</span>
        </button>
      </div>
    </div>
  {/if}

  <!-- ===================== ОВЕРЛЕЙ ПРИЗЫВА ===================== -->
  {#if phase !== 'idle' && fx}
    <div class="g-ov" class:shake={phase === 'burst' && (fx.rarity === 'SSR' || fx.rarity === 'UR')}>
      <div class="g-ov-bd"></div>

      {#if phase === 'launch' || phase === 'beam'}
        <!-- круг призыва -->
        <div class="g-summon">
          <div class="g-ring" style="width:308px;height:308px;border:2px dashed rgba(205,232,255,.45);animation:ringSpin 9s linear infinite"></div>
          <div class="g-ring" style="width:246px;height:246px;background:conic-gradient(from 0deg,transparent,rgba(160,210,255,.5),transparent 58%);animation:ringSpinRev 4.2s linear infinite;filter:blur(2px)"></div>
          <div class="g-ring" style="width:192px;height:192px;border:1px solid rgba(190,225,255,.7);animation:ringSpin 6s linear infinite"></div>
          <div class="g-ring" style="width:120px;height:120px;border:1px solid rgba(255,255,255,.32)"></div>
          <div class="g-core"></div>
          {#each Array(6) as _, i}
            <div class="g-summon-pt" style="transform:rotate({i * 60}deg)">
              <div class="g-summon-dot" style="animation-delay:{i * 0.12}s"></div>
            </div>
          {/each}
          {#each fx.parts.slice(0, 22) as p}
            <div class="g-cpt">
              <div class="g-cpt-in" style="--fx:{p.fx}px;--fy:{p.fy}px;animation:partIn {p.dur + 0.3}s ease-in {p.delay}s infinite"></div>
            </div>
          {/each}
        </div>
      {/if}

      {#if phase === 'beam'}
        <div class="g-beam">
          <div class="g-beam-glow" style="background:radial-gradient(46% 60% at 50% 58%,{fx.glow},transparent 66%)"></div>
          <div class="g-beam-p1" style="background:linear-gradient(to top,{fx.color},{fx.color}66 40%,transparent)"></div>
          <div class="g-beam-p2" style="background:linear-gradient(to top,#fff,{fx.color} 45%,transparent)"></div>
          <div class="g-beam-ground" style="background:radial-gradient(closest-side,{fx.color},transparent)"></div>
        </div>
      {/if}

      {#if phase === 'burst'}
        <div class="g-burst">
          <div class="g-burst-flash" style="background:radial-gradient(circle,#fff 0%,{fx.color} 22%,transparent 60%)"></div>
          {#each fx.rays as r}
            <div class="g-cpt" style="transform:rotate({r.a}deg)">
              <div class="g-ray" style="top:{-r.w / 2}px;height:{r.w}px;width:{r.len}vmax;background:linear-gradient(to right,#fff,{fx.color} 30%,transparent);animation:rayOut .8s cubic-bezier(.15,.8,.25,1) {r.delay}s forwards"></div>
            </div>
          {/each}
          {#each fx.parts as p, i}
            <div class="g-cpt">
              <div class="g-bpt" style="width:{p.s}px;height:{p.s}px;background:{i % 3 ? fx.color : '#fff'};box-shadow:0 0 10px {fx.color};--tx:{p.tx}px;--ty:{p.ty}px;animation:partOut {p.dur + 0.2}s ease-out {p.delay}s forwards"></div>
            </div>
          {/each}
        </div>
      {/if}

      {#if phase === 'reveal' && batch[0]}
        {@const c = batch[0]}
        {@const cfg = RAR[c.rarity]}
        <div class="g-reveal">
          <div class="g-halo" style="background:radial-gradient(circle,{cfg.glow} 0%,transparent 55%)"></div>
          {#if c.rarity === 'SSR' || c.rarity === 'UR'}
            <div class="g-wheel" style="animation:rayWheel {c.rarity === 'UR' ? 22 : 30}s linear infinite;opacity:{c.rarity === 'UR' ? 0.5 : 0.34}">
              {#each wheelSpokes(c.rarity) as a}
                <div class="g-spoke" style="transform:rotate({a}deg);background:linear-gradient(to right,{cfg.color}aa,transparent 70%);height:{c.rarity === 'UR' ? 4 : 3}px"></div>
              {/each}
            </div>
            <div class="g-sparkles">
              {#each sparkleList(c.rarity === 'UR' ? 16 : 9) as s}
                <div class="g-spark" style="top:{s.top}%;left:{s.left}%;width:{s.s}px;height:{s.s}px;box-shadow:0 0 10px {cfg.color};animation:sparkleDrift {s.dur}s ease-in-out {s.delay}s infinite"></div>
              {/each}
            </div>
          {/if}
          <div class="g-reveal-kicker" style="color:{cfg.color}">{c.new ? 'Новый персонаж' : `+1★ → ${c.stars}★`}</div>
          <div class="g-card" style="--rc:{cfg.color};--glow:{cfg.glow};--g1:{cfg.g1};--g2:{cfg.g2}">
            <img class="g-card-art" src={c.asset} alt={c.name} on:error={imgErr} />
            <div class="g-card-grad"></div>
            <div class="g-card-shine"></div>
            {#if c.new}<div class="g-card-new" style="background:{cfg.color};box-shadow:0 0 16px {cfg.glow}">NEW</div>{/if}
            <div class="g-card-rar" style="color:{cfg.color};border-color:{cfg.color};box-shadow:0 0 14px {cfg.glow}">{cfg.label}</div>
            <div class="g-card-info">
              <div class="g-card-name">{c.name}</div>
              <div class="g-card-stars"><span class="f">{'★'.repeat(c.stars)}</span><span class="e">{'☆'.repeat(5 - c.stars)}</span></div>
              {#if c.refund > 0}<div class="g-card-rate" style="color:{cfg.color}">дубль 5★ · +{fmtCoins(c.refund)} ◆</div>{/if}
            </div>
          </div>
          <div class="g-reveal-btns">
            <button class="g-rb ghost" on:click={againX1}>Ещё ×1</button>
            <button class="g-rb gold" on:click={closePull}>Получить</button>
          </div>
        </div>
      {/if}

      {#if phase === 'grid'}
        <div class="g-gridlayer">
          {#if fx.rarity === 'SSR' || fx.rarity === 'UR'}
            <div class="g-wheel" style="animation:rayWheel {fx.rarity === 'UR' ? 22 : 30}s linear infinite;opacity:{fx.rarity === 'UR' ? 0.5 : 0.34}">
              {#each wheelSpokes(fx.rarity) as a}
                <div class="g-spoke" style="transform:rotate({a}deg);background:linear-gradient(to right,{fx.color}aa,transparent 70%);height:{fx.rarity === 'UR' ? 4 : 3}px"></div>
              {/each}
            </div>
          {/if}
          <div class="g-grid-ttl">Результаты ×10</div>
          <div class="g-grid-cells">
            {#each batch as c, i (i)}
              {@const cfg = RAR[c.rarity]}
              <div class="g-gcell" style="--g1:{cfg.g1};--g2:{cfg.g2};--rc:{cfg.color};box-shadow:0 6px 18px rgba(0,0,0,.4),0 0 {c.rarity === 'SSR' || c.rarity === 'UR' ? 16 : 8}px {cfg.soft};animation:gridPop .5s cubic-bezier(.2,.85,.25,1) {i * 0.08}s both">
                <div class="g-gcell-art"><img src={c.asset} alt={c.name} on:error={imgErr} /></div>
                <div class="g-gcell-rar" style="color:{cfg.color};border-color:{cfg.color}">{cfg.label}</div>
                <div class="g-gcell-name">{c.name}</div>
              </div>
            {/each}
          </div>
          <button class="g-rb gold" style="margin-top:24px" on:click={closePull}>Получить всё</button>
        </div>
      {/if}

      {#if phase === 'launch' || phase === 'beam'}
        <button class="g-skip" on:click={skip}>Пропустить ›</button>
      {/if}
    </div>
  {/if}

  <!-- ===================== ДЕТАЛЬНАЯ КАРТОЧКА ===================== -->
  {#if detail}
    {@const cfg = RAR[detail.rarity]}
    <div class="g-detail" style="background:radial-gradient(70% 70% at 50% 45%,{cfg.soft},rgba(0,0,0,.94))">
      <button class="g-detail-x" on:click={closeDetail}>✕</button>
      {#if detail.rarity === 'SSR' || detail.rarity === 'UR'}
        <div class="g-sparkles">
          {#each sparkleList(10) as s}
            <div class="g-spark" style="top:{s.top}%;left:{s.left}%;width:{s.s}px;height:{s.s}px;box-shadow:0 0 10px {cfg.color};animation:sparkleDrift {s.dur}s ease-in-out {s.delay}s infinite"></div>
          {/each}
        </div>
      {/if}
      <div class="g-detail-card" style="--rc:{cfg.color};--glow:{cfg.glow};--g1:{cfg.g1};--g2:{cfg.g2}">
        <div class="g-detail-sway">
          <img src={detail.asset} alt={detail.name} on:error={imgErr} />
        </div>
        <div class="g-detail-grad"></div>
        <div class="g-detail-rar" style="color:{cfg.color};border-color:{cfg.color}">{cfg.label}</div>
        {#if detailLine}<div class="g-bubble">{detailLine}</div>{/if}
        <div class="g-detail-info">
          <div class="g-detail-name">{detail.name}</div>
          <div class="g-card-stars"><span class="f">{'★'.repeat(detail.stars)}</span><span class="e">{'☆'.repeat(5 - detail.stars)}</span></div>
          <div class="g-detail-bond" style="color:{cfg.color}">Ур. {detail.level ?? 1}/{detail.level_cap ?? 60} · ♥ {detail.affection ?? 0}</div>
        </div>
      </div>

      {#if detail.stats}
        <div class="g-statbar">
          <div><b>{detail.stats.hp}</b><span>HP</span></div>
          <div><b>{detail.stats.atk}</b><span>ATK</span></div>
          <div><b>{detail.stats.def}</b><span>DEF</span></div>
          <div><b>{detail.stats.spd}</b><span>SPD</span></div>
        </div>
        <div class="g-detail-abil">{detail.position === 'front' ? '🛡 фронт' : '🎯 бэк'} · {ABIL[detail.ability] ?? detail.ability}</div>
      {/if}

      <div class="g-detail-actions">
        <button class="g-love" style="border-color:{cfg.color};box-shadow:0 0 24px {cfg.soft}" disabled={petBusy} on:click={pet}>Приласкать ♥</button>
        {#if detail.role === 'heroine'}
          {#if col.active_heroine === detail.char_id}
            <div class="g-heroine on">Активная героиня ✓</div>
          {:else}
            <button class="g-heroine" disabled={busy} on:click={() => setHeroine(detail.char_id)}>Сделать героиней</button>
          {/if}
        {/if}
      </div>

      <div class="g-hearts">
        {#each hearts as ht (ht.id)}
          <div class="g-heart" style="left:{ht.left}%;font-size:{ht.s}px;--hx:{ht.hx}px;animation:heartUp {ht.dur}s ease-out {ht.delay}s forwards">♥</div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- ===================== ПОДДЕРЖАТЬ ===================== -->
  {#if donateOpen}
    <div class="g-detail" style="background:radial-gradient(70% 70% at 50% 40%,rgba(255,180,58,.18),rgba(0,0,0,.94))">
      <button class="g-detail-x" on:click={() => (donateOpen = false)}>✕</button>
      <div class="g-donate">
        <div class="g-donate-h">⭐ Поддержать сервер</div>
        <div class="g-sub" style="text-align:center;max-width:280px">
          1⭐ → {fmtCoins(col.roll_cost)}г на твой баланс. Идёт на хостинг и развитие.
        </div>
        <div class="g-donate-grid">
          {#each STAR_PACKS as n}
            <button class="g-pack" disabled={donateBusy} on:click={() => donate(n)}>
              <div class="g-pack-s">{n}⭐</div>
              <div class="g-pack-h">+{fmtCoins(n * col.roll_cost)}</div>
            </button>
          {/each}
        </div>
      </div>
    </div>
  {/if}

  <!-- ===================== КУПИТЬ GEMS ===================== -->
  {#if buyGemsOpen}
    <div class="g-detail" style="background:radial-gradient(70% 70% at 50% 40%,rgba(75,180,255,.16),rgba(0,0,0,.94))">
      <button class="g-detail-x" on:click={() => (buyGemsOpen = false)}>✕</button>
      <div class="g-donate">
        <div class="g-donate-h">◆ Купить gems</div>
        <div class="g-sub" style="text-align:center;max-width:280px">
          Курс: 1 ◆ = {fmtCoins(col?.cp_per_gem ?? 0)} cp. Доступно: {fmtCoins(col?.cp_balance ?? 0)} cp.
          cp зарабатывается на ферме.
        </div>
        <div class="g-donate-grid" style="grid-template-columns:repeat(3,1fr)">
          {#each GEM_PACKS as n}
            <button
              class="g-pack"
              disabled={buyGemsBusy || (col?.cp_balance ?? 0) < n * (col?.cp_per_gem ?? 0)}
              on:click={() => buyGems(n)}
            >
              <div class="g-pack-s">{n} ◆</div>
              <div class="g-pack-h">{fmtCoins(n * (col?.cp_per_gem ?? 0))} cp</div>
            </button>
          {/each}
        </div>
        <a class="g-heroine" href={`/farm${search}`} style="text-decoration:none;text-align:center">На ферму за cp →</a>
      </div>
    </div>
  {/if}


  <!-- ===================== TOAST ===================== -->
  {#if toastMsg}
    <div class="g-toast">{toastMsg}</div>
  {/if}
</div>

<style>
  /* корневой полноэкранный тёмный экран (ломает паддинг layout) */
  .g-root {
    position: fixed;
    inset: 0;
    z-index: 20;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: radial-gradient(120% 80% at 50% -10%, #16121f 0%, #0a0a0f 46%, #060608 100%);
    font-family: Manrope, system-ui, sans-serif;
    color: #eef0f4;
  }
  .g-root :global(*) {
    box-sizing: border-box;
  }
  .g-muted {
    color: #9aa0ac;
  }
  .g-sub {
    font-size: 11px;
    color: #9aa0ac;
    margin-top: 1px;
  }
  .g-scroll {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    position: relative;
  }
  .g-pad {
    padding: 4px 16px 26px;
    max-width: 560px;
    margin: 0 auto;
    width: 100%;
  }
  .g-pad.coll {
    padding: 4px 14px 30px;
  }

  /* шапка */
  .g-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 18px 18px 12px;
    flex: none;
    z-index: 5;
  }
  .g-bal {
    display: flex;
    align-items: center;
    gap: 9px;
  }
  .g-diamond {
    width: 26px;
    height: 26px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(145deg, #ffd76b, #ff9a3a);
    box-shadow: 0 0 14px rgba(255, 180, 58, 0.45);
    color: #5a3500;
    font-weight: 800;
    font-size: 15px;
  }
  .g-bal-txt {
    display: flex;
    flex-direction: column;
    line-height: 1;
  }
  .g-bal-cap {
    font-size: 10px;
    color: #7e8492;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
  }
  .g-bal-num {
    font-family: Unbounded, sans-serif;
    font-weight: 700;
    font-size: 17px;
    color: #fff;
    margin-top: 3px;
  }
  .g-icon {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: #15171e;
    border: 1px solid rgba(255, 255, 255, 0.06);
    display: flex;
    align-items: center;
    justify-content: center;
    color: #9aa0ac;
    font-size: 15px;
    text-decoration: none;
  }

  /* вкладки */
  .g-tabs {
    display: flex;
    gap: 5px;
    margin: 0 16px 12px;
    background: #13141a;
    border-radius: 15px;
    padding: 5px;
    flex: none;
    border: 1px solid rgba(255, 255, 255, 0.04);
    z-index: 5;
    max-width: 560px;
    width: calc(100% - 32px);
    align-self: center;
  }
  .g-tab {
    flex: 1;
    padding: 11px 0;
    border-radius: 11px;
    border: none;
    cursor: pointer;
    font-family: Manrope, sans-serif;
    font-weight: 700;
    font-size: 14px;
    color: #8b909c;
    background: transparent;
  }
  .g-tab.on {
    color: #fff;
    background: linear-gradient(180deg, #2a2c38, #1d1f29);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4), inset 0 0 0 1px rgba(255, 255, 255, 0.06);
  }

  /* ежедневный бонус */
  .g-daily {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 12px 14px;
    border-radius: 14px;
    background: linear-gradient(110deg, #1a1430, #14131c);
    border: 1px solid rgba(207, 91, 255, 0.2);
    margin-bottom: 14px;
  }
  .g-daily-ic {
    width: 42px;
    height: 42px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    background: rgba(207, 91, 255, 0.14);
    border: 1px solid rgba(207, 91, 255, 0.3);
    flex: none;
  }
  .g-daily-txt {
    flex: 1;
    min-width: 0;
  }
  .g-daily-h {
    font-weight: 800;
    font-size: 14px;
    color: #fff;
  }
  .g-daily-btn {
    flex: none;
    padding: 9px 15px;
    border-radius: 11px;
    border: none;
    cursor: pointer;
    font-family: Manrope, sans-serif;
    font-weight: 800;
    font-size: 13px;
    white-space: nowrap;
    color: #3a1d52;
    background: linear-gradient(180deg, #d59bff, #a85cff);
    box-shadow: 0 6px 16px rgba(168, 92, 255, 0.35);
  }
  .g-daily-btn.claimed {
    color: #7e8492;
    background: rgba(255, 255, 255, 0.06);
    box-shadow: none;
  }
  .g-daily-btn:disabled {
    cursor: default;
  }

  /* баннер */
  .g-banner {
    position: relative;
    width: 100%;
    display: block;
    border-radius: 22px;
    overflow: hidden;
    cursor: pointer;
    border: 1px solid rgba(255, 180, 58, 0.32);
    box-shadow: 0 0 44px rgba(255, 180, 58, 0.16), inset 0 0 0 1px rgba(255, 255, 255, 0.05);
    padding: 0;
    text-align: left;
  }
  .g-banner.home {
    aspect-ratio: 16/13;
    max-height: 340px;
  }
  .g-banner.spin {
    height: 344px;
    cursor: default;
  }
  .g-banner-art {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-banner-grad {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: linear-gradient(180deg, rgba(10, 7, 2, 0.05) 30%, rgba(8, 6, 3, 0.5) 62%, rgba(6, 4, 2, 0.92));
  }
  .g-banner-tag {
    position: absolute;
    top: 14px;
    left: 14px;
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 12px;
    letter-spacing: 1.5px;
    color: #ffce5e;
    padding: 5px 11px;
    border-radius: 9px;
    background: rgba(40, 24, 2, 0.6);
    border: 1px solid rgba(255, 180, 58, 0.55);
    box-shadow: 0 0 16px rgba(255, 180, 58, 0.4);
  }
  .g-banner-timer {
    position: absolute;
    top: 16px;
    right: 14px;
    display: flex;
    align-items: center;
    gap: 6px;
    background: rgba(0, 0, 0, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.1);
    padding: 5px 10px;
    border-radius: 9px;
    color: #dfe2e8;
    font-size: 11px;
    font-weight: 700;
  }
  .g-banner-timer span {
    color: #ff8fb4;
    font-size: 12px;
  }
  .g-banner-info {
    position: absolute;
    left: 18px;
    right: 18px;
    bottom: 16px;
  }
  .g-banner-kicker {
    font-size: 11px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #ffce5e;
    font-weight: 800;
  }
  .g-banner-name {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 30px;
    color: #fff;
    margin-top: 5px;
    line-height: 1;
    text-shadow: 0 2px 20px rgba(0, 0, 0, 0.6);
  }
  .g-banner-lore {
    font-size: 12px;
    color: #c9ccd3;
    margin-top: 8px;
    font-weight: 500;
  }
  .g-banner-more {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 12px;
    padding: 8px 14px;
    border-radius: 11px;
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: #fff;
    font-size: 12px;
    font-weight: 700;
  }

  /* быстрые действия */
  .g-actions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 11px;
    margin-top: 14px;
  }
  .g-act {
    display: flex;
    align-items: center;
    gap: 12px;
    text-align: left;
    padding: 15px 16px;
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    color: #fff;
    cursor: pointer;
    font-family: Manrope, sans-serif;
    text-decoration: none;
  }
  .act-spin {
    border-color: rgba(255, 200, 90, 0.45);
    background: linear-gradient(135deg, rgba(255, 180, 58, 0.2), rgba(255, 140, 40, 0.06));
  }
  .act-coll {
    background: linear-gradient(135deg, rgba(207, 91, 255, 0.16), rgba(122, 140, 255, 0.05));
  }
  .act-farm {
    border-color: rgba(255, 255, 255, 0.08);
    background: linear-gradient(135deg, rgba(75, 180, 255, 0.12), rgba(31, 138, 91, 0.05));
  }
  .act-support {
    border-color: rgba(255, 255, 255, 0.08);
    background: linear-gradient(135deg, rgba(255, 180, 58, 0.1), rgba(255, 255, 255, 0.02));
  }
  .g-act-ic {
    width: 38px;
    height: 38px;
    flex: none;
    border-radius: 11px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
  }
  .ic-gold {
    color: #ffce5e;
    background: rgba(255, 180, 58, 0.16);
    border: 1px solid rgba(255, 180, 58, 0.4);
  }
  .ic-purple {
    color: #d59bff;
    background: rgba(207, 91, 255, 0.14);
    border: 1px solid rgba(207, 91, 255, 0.35);
  }
  .ic-green {
    color: #7fd0a0;
    background: rgba(31, 138, 91, 0.16);
    border: 1px solid rgba(31, 138, 91, 0.4);
  }
  .g-act-txt {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .g-act-txt b {
    font-weight: 800;
    font-size: 15px;
  }
  .g-act-txt small {
    font-size: 11px;
    color: #bfc4d0;
  }
  .g-foot {
    margin-top: 18px;
    text-align: center;
    font-size: 11px;
    color: #5b616d;
    font-weight: 600;
  }

  /* pity-полоса в крутке */
  .g-pity-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 16px;
  }
  .g-pity-bar {
    flex: 1;
    height: 7px;
    border-radius: 6px;
    background: #16171f;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.05);
  }
  .g-pity-fill.ssr {
    height: 100%;
    background: linear-gradient(90deg, #cf5bff, #7a8cff);
    box-shadow: 0 0 12px rgba(207, 91, 255, 0.6);
  }
  .g-pity-cap {
    font-size: 11px;
    color: #9aa0ac;
    font-weight: 600;
    white-space: nowrap;
  }

  /* кнопки крутки */
  .g-pull-btns {
    display: flex;
    gap: 12px;
    margin-top: 18px;
  }
  .g-pull {
    flex: 1;
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    padding: 15px 10px;
    border-radius: 16px;
    cursor: pointer;
    font-family: Manrope, sans-serif;
    transition: transform 0.12s;
  }
  .g-pull:active {
    transform: scale(0.97);
  }
  .g-pull:disabled {
    opacity: 0.6;
  }
  .g-pull.x1 {
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: linear-gradient(180deg, #1c1e27, #15161d);
    color: #fff;
  }
  .g-pull.x10 {
    flex: 1.25;
    border: 1px solid rgba(255, 200, 90, 0.5);
    background: linear-gradient(180deg, #ffd76b, #ff9b3b);
    color: #4a2c00;
    box-shadow: 0 8px 26px rgba(255, 150, 40, 0.32);
  }
  .g-pull-h {
    font-size: 15px;
    font-weight: 800;
  }
  .g-pull-c {
    font-size: 12px;
    font-weight: 800;
  }
  .g-pull-c.gold {
    color: #ffce5e;
    font-weight: 700;
  }
  .g-pull-badge {
    position: absolute;
    top: -9px;
    right: -6px;
    background: #ff3d7f;
    color: #fff;
    font-size: 10px;
    font-weight: 800;
    padding: 3px 7px;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(255, 61, 127, 0.5);
  }
  .g-rates {
    display: flex;
    justify-content: center;
    gap: 14px;
    margin-top: 14px;
    font-size: 11px;
    font-weight: 600;
  }

  /* коллекция */
  .g-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  .g-cell {
    position: relative;
    border-radius: 14px;
    padding: 8px;
    cursor: pointer;
    border: 1.5px solid var(--rc);
    background: linear-gradient(180deg, color-mix(in srgb, var(--g1) 18%, transparent), color-mix(in srgb, var(--g2) 80%, transparent));
    box-shadow: 0 8px 22px rgba(0, 0, 0, 0.45), 0 0 16px var(--soft), inset 0 0 0 1px rgba(255, 255, 255, 0.04);
    animation: floatIdle 4s ease-in-out infinite;
    text-align: center;
    font-family: Manrope, sans-serif;
  }
  .g-cell.locked {
    filter: saturate(0.5);
    opacity: 0.78;
  }
  .g-cell.active {
    outline: 2px solid #ffce5e;
    outline-offset: 1px;
  }
  .g-cell-art {
    position: relative;
    width: 100%;
    aspect-ratio: 1/1;
    border-radius: 10px;
    overflow: hidden;
    background: #0b0c10;
  }
  .g-cell-art img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-cell-art img.dim {
    filter: grayscale(1) brightness(0.5);
  }
  .g-cell-act {
    position: absolute;
    bottom: 5px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 9px;
    font-weight: 800;
    color: #3a2600;
    background: linear-gradient(180deg, #ffd76b, #ff9b3b);
    padding: 2px 8px;
    border-radius: 7px;
    white-space: nowrap;
  }
  .g-cell-rar {
    font-family: Unbounded, sans-serif;
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 1px;
    margin-top: 7px;
  }
  .g-cell-name {
    font-weight: 700;
    font-size: 12px;
    color: #eef0f4;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .g-cell-stars {
    margin-top: 3px;
    font-size: 11px;
    letter-spacing: 1px;
  }
  .g-cell-stars .f,
  .g-card-stars .f {
    color: #ffcf4a;
  }
  .g-cell-stars .e,
  .g-card-stars .e {
    color: #454a55;
  }
  .g-cell-locked {
    margin-top: 3px;
    font-size: 10px;
    color: #8b909c;
    font-weight: 700;
  }

  /* ---------- превью баннера ---------- */
  .g-preview {
    position: absolute;
    inset: 0;
    z-index: 50;
    display: flex;
    flex-direction: column;
    background: linear-gradient(180deg, #0c0a12, #070608);
  }
  .g-pv-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 15px 16px 11px;
    flex: none;
  }
  .g-pv-back {
    width: 36px;
    height: 36px;
    border-radius: 11px;
    background: rgba(255, 255, 255, 0.07);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: #dfe2e8;
    font-size: 17px;
    cursor: pointer;
  }
  .g-pv-title {
    font-family: Unbounded, sans-serif;
    font-weight: 700;
    font-size: 14px;
    color: #fff;
    letter-spacing: 0.5px;
  }
  .g-pv-scroll {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 0 16px 14px;
  }
  .g-pv-art {
    position: relative;
    width: 100%;
    aspect-ratio: 5/6;
    max-height: 54vh;
    border-radius: 22px;
    overflow: hidden;
    border: 2px solid #ffb43a;
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.55), 0 0 50px rgba(255, 180, 58, 0.28);
  }
  .g-pv-art img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-pv-grad {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: linear-gradient(180deg, rgba(10, 7, 2, 0.04) 38%, rgba(8, 6, 3, 0.55) 70%, rgba(6, 4, 2, 0.95));
  }
  .g-pv-info {
    position: absolute;
    left: 18px;
    right: 18px;
    bottom: 18px;
  }
  .g-pv-name {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 32px;
    color: #fff;
    margin-top: 5px;
    line-height: 1;
    text-shadow: 0 2px 20px rgba(0, 0, 0, 0.7);
  }
  .g-pv-lore {
    font-size: 13px;
    color: #d3c4b0;
    margin-top: 9px;
    line-height: 1.5;
  }
  .g-pv-rates {
    display: flex;
    gap: 8px;
    margin-top: 14px;
  }
  .g-pv-rate {
    flex: 1;
    text-align: center;
    padding: 10px 4px;
    border-radius: 12px;
    background: color-mix(in srgb, var(--c) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--c) 30%, transparent);
  }
  .g-pv-rate b {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 15px;
    color: var(--c);
  }
  .g-pv-rate small {
    display: block;
    font-size: 10px;
    color: #9aa0ac;
    font-weight: 700;
    margin-top: 2px;
  }
  .g-pv-pity {
    margin-top: 12px;
    padding: 15px 16px;
    border-radius: 14px;
    background: #13141a;
    border: 1px solid rgba(255, 255, 255, 0.06);
  }
  .g-pv-pity-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 7px;
    font-size: 12px;
    color: #cfd3db;
    font-weight: 700;
  }
  .g-pv-track {
    height: 8px;
    border-radius: 6px;
    background: #0b0c10;
    overflow: hidden;
    border: 1px solid rgba(255, 255, 255, 0.05);
  }
  .g-pv-fill {
    height: 100%;
  }
  .g-pv-fill.ssr {
    background: linear-gradient(90deg, #cf5bff, #7a8cff);
    box-shadow: 0 0 12px rgba(207, 91, 255, 0.6);
  }
  .g-pv-fill.ur {
    background: linear-gradient(90deg, #ff9b3b, #ff3d7f);
    box-shadow: 0 0 12px rgba(255, 150, 40, 0.6);
  }
  .g-pv-pool {
    margin-top: 12px;
  }
  .g-pv-pool-h {
    font-size: 11px;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: #7e8492;
    font-weight: 800;
    margin-bottom: 9px;
  }
  .g-pv-pool-row {
    display: flex;
    gap: 10px;
  }
  .g-pv-pool-item {
    flex: 1;
    min-width: 0;
  }
  .g-pv-pool-art {
    position: relative;
    width: 100%;
    aspect-ratio: 1/1;
    border-radius: 12px;
    overflow: hidden;
    background: #0b0c10;
    border: 1.5px solid #fff;
  }
  .g-pv-pool-art img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-pv-pool-art img.dim {
    filter: grayscale(1) brightness(0.5);
  }
  .g-pv-pool-name {
    text-align: center;
    font-size: 11px;
    font-weight: 700;
    color: #dfe2e8;
    margin-top: 5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .g-pv-foot {
    flex: none;
    display: flex;
    gap: 11px;
    padding: 12px 16px 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    background: linear-gradient(180deg, transparent, #070608);
  }

  /* ---------- оверлей призыва ---------- */
  .g-ov {
    position: absolute;
    inset: 0;
    z-index: 60;
    overflow: hidden;
  }
  .g-ov.shake {
    animation: screenShake 0.55s ease;
  }
  .g-ov-bd {
    position: absolute;
    inset: 0;
    background: radial-gradient(80% 80% at 50% 50%, rgba(2, 1, 4, 0.9), rgba(0, 0, 0, 0.98));
  }
  .g-summon {
    position: absolute;
    inset: 0;
    z-index: 10;
    animation: summonIn 0.5s ease;
  }
  .g-ring {
    position: absolute;
    inset: 0;
    margin: auto;
    border-radius: 50%;
  }
  .g-core {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 96px;
    height: 96px;
    border-radius: 50%;
    background: radial-gradient(circle, #ffffff, #c2e2ff 42%, rgba(120, 180, 255, 0) 72%);
    filter: blur(2px);
    animation: corePulse 1s ease-in-out infinite;
  }
  .g-summon-pt {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 0;
    height: 0;
  }
  .g-summon-dot {
    position: absolute;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #dff0ff;
    box-shadow: 0 0 13px #9fd0ff;
    transform: translateY(-152px);
    animation: glowPulse 1.2s ease-in-out infinite;
  }
  /* центральная точка для частиц/лучей */
  .g-cpt {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 0;
    height: 0;
  }
  .g-cpt-in {
    position: absolute;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #cfeaff;
    box-shadow: 0 0 8px #9fd0ff;
  }
  .g-bpt {
    position: absolute;
    border-radius: 50%;
  }
  .g-ray {
    position: absolute;
    left: 0;
    transform-origin: 0 50%;
    filter: blur(0.4px);
  }

  /* луч */
  .g-beam {
    position: absolute;
    inset: 0;
    z-index: 10;
  }
  .g-beam-glow {
    position: absolute;
    inset: 0;
    animation: flashHit 1s ease forwards;
  }
  .g-beam-p1 {
    position: absolute;
    left: 50%;
    bottom: 0;
    transform: translateX(-50%);
    transform-origin: bottom;
    width: 150px;
    height: 94%;
    filter: blur(7px);
    opacity: 0.9;
    animation: beamRise 1s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
  }
  .g-beam-p2 {
    position: absolute;
    left: 50%;
    bottom: 0;
    transform: translateX(-50%);
    transform-origin: bottom;
    width: 34px;
    height: 96%;
    filter: blur(1px);
    animation: beamRise 0.85s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
  }
  .g-beam-ground {
    position: absolute;
    left: 50%;
    bottom: 4%;
    transform: translateX(-50%);
    width: 260px;
    height: 60px;
    border-radius: 50%;
    filter: blur(6px);
    opacity: 0.7;
  }

  /* взрыв */
  .g-burst {
    position: absolute;
    inset: 0;
    z-index: 12;
  }
  .g-burst-flash {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 60vmax;
    height: 60vmax;
    border-radius: 50%;
    animation: burstFlash 0.85s ease-out forwards;
  }

  /* раскрытие / колесо лучей / искры */
  .g-reveal,
  .g-gridlayer {
    position: absolute;
    inset: 0;
    z-index: 14;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 22px;
  }
  .g-halo {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 80vmax;
    height: 80vmax;
    border-radius: 50%;
    opacity: 0.55;
  }
  .g-wheel {
    position: absolute;
    inset: 0;
    margin: auto;
    width: 0;
    height: 0;
    z-index: 1;
  }
  .g-spoke {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 70vmax;
    margin-top: -2px;
    transform-origin: 0 50%;
  }
  .g-sparkles {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }
  .g-spark {
    position: absolute;
    border-radius: 50%;
    background: #fff;
  }
  .g-reveal-kicker {
    position: relative;
    z-index: 2;
    margin-bottom: 16px;
    font-family: Unbounded, sans-serif;
    font-weight: 700;
    font-size: 12px;
    letter-spacing: 4px;
    text-transform: uppercase;
    animation: fadeUp 0.5s ease 0.15s both;
  }
  .g-card {
    position: relative;
    z-index: 2;
    width: 300px;
    max-width: 78vw;
    aspect-ratio: 300/420;
    border-radius: 22px;
    overflow: hidden;
    border: 2px solid var(--rc);
    background: linear-gradient(180deg, var(--g1), var(--g2));
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6), 0 0 50px var(--glow), inset 0 0 0 1px rgba(255, 255, 255, 0.06);
    animation: cardRise 0.7s cubic-bezier(0.2, 0.85, 0.25, 1) both;
  }
  .g-card-art {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-card-grad {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: linear-gradient(180deg, rgba(0, 0, 0, 0.05) 35%, rgba(5, 4, 8, 0.55) 70%, rgba(4, 3, 6, 0.93));
  }
  .g-card-shine {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    width: 45%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.35), transparent);
    animation: shineSweep 1.6s ease 0.35s 1;
    pointer-events: none;
  }
  .g-card-new {
    position: absolute;
    top: 13px;
    left: 13px;
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 11px;
    letter-spacing: 1.5px;
    color: #fff;
    padding: 5px 10px;
    border-radius: 8px;
    animation: badgePop 0.4s ease 0.15s both;
  }
  .g-card-rar {
    position: absolute;
    top: 13px;
    right: 13px;
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 12px;
    letter-spacing: 1.5px;
    padding: 5px 11px;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.5);
    border: 1px solid;
  }
  .g-card-info {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 0 18px 18px;
    text-align: center;
  }
  .g-card-name {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 25px;
    color: #fff;
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.7);
    animation: nameRise 0.6s cubic-bezier(0.2, 0.8, 0.2, 1) 0.25s both;
  }
  .g-card-stars {
    margin-top: 6px;
    font-size: 14px;
    letter-spacing: 2px;
    animation: fadeUp 0.5s ease 0.5s both;
  }
  .g-card-rate {
    margin-top: 7px;
    font-size: 12px;
    font-weight: 700;
    animation: fadeUp 0.5s ease 0.62s both;
  }
  .g-reveal-btns {
    position: relative;
    z-index: 2;
    display: flex;
    gap: 12px;
    margin-top: 24px;
    animation: fadeUp 0.5s ease 0.7s both;
  }
  .g-rb {
    border-radius: 14px;
    font-family: Manrope, sans-serif;
    font-weight: 800;
    font-size: 14px;
    cursor: pointer;
  }
  .g-rb.ghost {
    padding: 13px 22px;
    border: 1px solid rgba(255, 255, 255, 0.16);
    background: rgba(255, 255, 255, 0.07);
    color: #eef0f4;
    font-weight: 700;
  }
  .g-rb.gold {
    padding: 13px 30px;
    border: none;
    background: linear-gradient(180deg, #ffd76b, #ff9b3b);
    color: #4a2c00;
    box-shadow: 0 8px 24px rgba(255, 150, 40, 0.3);
  }

  /* сетка ×10 */
  .g-grid-ttl {
    position: relative;
    z-index: 2;
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 18px;
    color: #fff;
    margin-bottom: 16px;
    animation: fadeUp 0.5s ease both;
  }
  .g-grid-cells {
    position: relative;
    z-index: 2;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 9px;
    width: 100%;
    max-width: 420px;
  }
  .g-gcell {
    position: relative;
    border-radius: 11px;
    overflow: hidden;
    border: 1.5px solid var(--rc);
    background: linear-gradient(180deg, var(--g1), var(--g2));
  }
  .g-gcell-art {
    position: relative;
    width: 100%;
    aspect-ratio: 3/4;
    overflow: hidden;
    background: #0b0c10;
  }
  .g-gcell-art img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-gcell-rar {
    position: absolute;
    top: 5px;
    left: 5px;
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 9px;
    letter-spacing: 1px;
    padding: 2px 5px;
    border-radius: 5px;
    background: rgba(0, 0, 0, 0.55);
    border: 1px solid;
  }
  .g-gcell-name {
    padding: 5px 4px 6px;
    text-align: center;
    font-family: Manrope, sans-serif;
    font-weight: 700;
    font-size: 10px;
    color: #eef0f4;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .g-skip {
    position: absolute;
    bottom: 22px;
    right: 18px;
    z-index: 30;
    background: rgba(255, 255, 255, 0.08);
    color: #cfd3db;
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 20px;
    padding: 8px 16px;
    font-family: Manrope, sans-serif;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }

  /* ---------- детальная карточка ---------- */
  .g-detail {
    position: absolute;
    inset: 0;
    z-index: 55;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 0 22px;
    backdrop-filter: blur(3px);
  }
  .g-detail-x {
    position: absolute;
    top: 16px;
    right: 16px;
    width: 38px;
    height: 38px;
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    color: #dfe2e8;
    font-size: 18px;
    cursor: pointer;
  }
  .g-detail-card {
    position: relative;
    width: 262px;
    max-width: 72vw;
    aspect-ratio: 262/360;
    border-radius: 22px;
    overflow: hidden;
    border: 2px solid var(--rc);
    background: linear-gradient(180deg, var(--g1), var(--g2));
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6), 0 0 46px var(--glow);
    animation: breathe 4s ease-in-out infinite;
  }
  .g-detail-sway {
    position: absolute;
    inset: 0;
    animation: sway 5s ease-in-out infinite;
  }
  .g-detail-sway img {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-detail-grad {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: linear-gradient(180deg, transparent 45%, rgba(4, 3, 6, 0.9));
  }
  .g-detail-rar {
    position: absolute;
    top: 12px;
    right: 12px;
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 12px;
    letter-spacing: 1.5px;
    padding: 5px 11px;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.5);
    border: 1px solid;
  }
  .g-bubble {
    position: absolute;
    top: 16px;
    left: 14px;
    max-width: 170px;
    background: rgba(255, 255, 255, 0.95);
    color: #2a2030;
    padding: 8px 12px;
    border-radius: 14px 14px 14px 4px;
    font-size: 12px;
    font-weight: 600;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.4);
    animation: bubblePop 0.35s cubic-bezier(0.2, 0.85, 0.25, 1) both;
  }
  .g-detail-info {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 0 16px 16px;
    text-align: center;
  }
  .g-detail-name {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 22px;
    color: #fff;
  }
  .g-detail-bond {
    margin-top: 6px;
    font-size: 12px;
    font-weight: 700;
  }
  .g-detail-actions {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
    margin-top: 22px;
  }
  .g-love {
    padding: 13px 30px;
    border-radius: 16px;
    border: 1px solid;
    background: linear-gradient(180deg, rgba(255, 111, 156, 0.22), rgba(255, 111, 156, 0.08));
    color: #ffd0de;
    font-family: Manrope, sans-serif;
    font-weight: 800;
    font-size: 15px;
    cursor: pointer;
  }
  .g-love:disabled {
    opacity: 0.6;
  }
  .g-heroine {
    padding: 10px 22px;
    border-radius: 14px;
    border: 1px solid rgba(255, 200, 90, 0.5);
    background: linear-gradient(180deg, #ffd76b, #ff9b3b);
    color: #4a2c00;
    font-family: Manrope, sans-serif;
    font-weight: 800;
    font-size: 13px;
    cursor: pointer;
  }
  .g-heroine.on {
    background: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.15);
    color: #7fd0a0;
  }
  .g-hearts {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }
  .g-heart {
    position: absolute;
    bottom: 90px;
    color: #ff6f9c;
    text-shadow: 0 0 10px rgba(255, 111, 156, 0.6);
  }

  /* ---------- поддержать ---------- */
  .g-donate {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    width: 100%;
    max-width: 360px;
  }
  .g-donate-h {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 18px;
    color: #fff;
  }
  .g-donate-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    width: 100%;
    margin-top: 6px;
  }
  .g-pack {
    padding: 14px 4px;
    border: 1px solid rgba(255, 180, 58, 0.35);
    background: rgba(255, 180, 58, 0.08);
    color: #fff;
    border-radius: 14px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
  }
  .g-pack:disabled {
    opacity: 0.5;
    cursor: progress;
  }
  .g-pack-s {
    font-weight: 800;
    font-size: 16px;
  }
  .g-pack-h {
    font-size: 11px;
    color: #ffce5e;
    font-weight: 700;
  }

  /* v2: gems в шапке + cp */
  .g-buygems {
    width: 24px;
    height: 24px;
    margin-left: 6px;
    border-radius: 8px;
    border: 1px solid rgba(255, 200, 90, 0.5);
    background: rgba(255, 180, 58, 0.16);
    color: #ffce5e;
    font-size: 16px;
    font-weight: 800;
    line-height: 1;
    cursor: pointer;
  }
  .g-head-right {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .g-cp {
    font-size: 11px;
    font-weight: 700;
    color: #7fd0a0;
    background: rgba(31, 138, 91, 0.14);
    border: 1px solid rgba(31, 138, 91, 0.3);
    padding: 4px 8px;
    border-radius: 9px;
    white-space: nowrap;
  }
  .act-arena {
    border-color: rgba(255, 80, 90, 0.4);
    background: linear-gradient(135deg, rgba(255, 80, 90, 0.16), rgba(255, 255, 255, 0.02));
  }
  .ic-red {
    color: #ff8a8a;
    background: rgba(255, 80, 90, 0.16);
    border: 1px solid rgba(255, 80, 90, 0.4);
  }

  /* v2: статы карты в детальной */
  .g-statbar {
    display: flex;
    gap: 8px;
    margin-top: 14px;
  }
  .g-statbar div {
    flex: 1;
    text-align: center;
    padding: 7px 2px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  .g-statbar b {
    display: block;
    font-family: Unbounded, sans-serif;
    font-size: 13px;
    color: #fff;
  }
  .g-statbar span {
    font-size: 9px;
    color: #9aa0ac;
    font-weight: 700;
  }
  .g-detail-abil {
    margin-top: 8px;
    font-size: 12px;
    color: #cfd3db;
    font-weight: 700;
  }

  /* v2: арена */
  .g-arena {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    width: 100%;
    max-width: 380px;
  }
  .g-arena-h {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 26px;
  }
  .g-arena-teams {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    margin-top: 4px;
  }
  .g-arena-side {
    flex: 1;
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    justify-content: center;
  }
  .g-arena-cap {
    width: 100%;
    text-align: center;
    font-size: 11px;
    font-weight: 800;
    color: #9aa0ac;
    margin-bottom: 2px;
  }
  .g-arena-card {
    width: 30%;
    aspect-ratio: 1/1;
    border-radius: 9px;
    overflow: hidden;
    border: 1.5px solid #555;
    background: #0b0c10;
  }
  .g-arena-card img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .g-arena-vs {
    font-family: Unbounded, sans-serif;
    font-weight: 800;
    font-size: 13px;
    color: #ffce5e;
    flex: none;
  }
  .g-arena-actions {
    display: flex;
    gap: 10px;
    margin-top: 6px;
  }
  .g-ladder {
    width: 100%;
    margin-top: 6px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 28vh;
    overflow-y: auto;
  }
  .g-ladder-row {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #dfe2e8;
    padding: 7px 11px;
    border-radius: 9px;
    background: rgba(255, 255, 255, 0.05);
  }

  /* v2: сборка команды */
  .g-team-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  .g-team-head b {
    font-size: 16px;
  }
  .g-save {
    padding: 9px 16px;
    border-radius: 11px;
    border: 1px solid rgba(255, 200, 90, 0.5);
    background: linear-gradient(180deg, #ffd76b, #ff9b3b);
    color: #4a2c00;
    font-family: Manrope, sans-serif;
    font-weight: 800;
    font-size: 13px;
    cursor: pointer;
  }
  .g-save:disabled {
    background: rgba(255, 255, 255, 0.07);
    border-color: rgba(255, 255, 255, 0.12);
    color: #7fd0a0;
  }
  .g-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .g-form-row {
    padding: 10px 12px;
    border-radius: 14px;
    background: #13141a;
    border: 1px solid rgba(255, 255, 255, 0.06);
  }
  .g-form-cap {
    font-size: 12px;
    font-weight: 800;
    color: #cfd3db;
    margin-bottom: 8px;
  }
  .g-form-cap .g-sub {
    display: inline;
    font-weight: 600;
    margin-left: 4px;
  }
  .g-form-slots {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    min-height: 64px;
  }
  .g-form-empty {
    align-self: center;
    font-size: 11px;
    color: #5b616d;
    font-weight: 600;
  }
  .g-tcard {
    width: 72px;
    border-radius: 11px;
    overflow: hidden;
    border: 1.5px solid #555;
    background: #0b0c10;
    position: relative;
  }
  .g-tcard img {
    width: 100%;
    aspect-ratio: 1/1;
    object-fit: cover;
    display: block;
  }
  .g-tcard-name {
    font-size: 9px;
    font-weight: 700;
    text-align: center;
    padding: 2px 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: #eef0f4;
  }
  .g-tcard-ctl {
    display: flex;
  }
  .g-tcard-ctl button {
    flex: 1;
    border: none;
    background: rgba(255, 255, 255, 0.08);
    color: #dfe2e8;
    font-size: 12px;
    padding: 4px 0;
    cursor: pointer;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }
  .g-tcard-ctl button:first-child {
    border-right: 1px solid rgba(255, 255, 255, 0.06);
  }
  .g-roster-h {
    margin: 16px 0 8px;
    font-size: 11px;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: #7e8492;
    font-weight: 800;
  }
  .g-roster {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 7px;
  }
  .g-rcard {
    position: relative;
    border-radius: 9px;
    overflow: hidden;
    border: 1.5px solid #555;
    background: #0b0c10;
    padding: 0;
    cursor: pointer;
  }
  .g-rcard img {
    width: 100%;
    aspect-ratio: 1/1;
    object-fit: cover;
    display: block;
  }
  .g-rcard.inteam {
    outline: 2px solid #7fd0a0;
    outline-offset: -2px;
  }
  .g-rcard.inteam img {
    opacity: 0.55;
  }
  .g-rcard-lvl {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    font-size: 8px;
    font-weight: 800;
    color: #fff;
    background: rgba(0, 0, 0, 0.6);
    padding: 1px 0;
  }
  .g-rcard-on {
    position: absolute;
    top: 2px;
    right: 2px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #7fd0a0;
    color: #08291a;
    font-size: 11px;
    font-weight: 900;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .g-arena-fight {
    display: flex;
    gap: 12px;
    margin-top: 18px;
  }
  .g-ladder-btn {
    width: 100%;
    margin-top: 12px;
    padding: 11px;
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.05);
    color: #dfe2e8;
    font-weight: 700;
    font-size: 13px;
    cursor: pointer;
  }

  /* ===================== пиксельная арена (сайд-вью, TBH) ===================== */
  .px-wrap,
  .px-stage,
  .px-info,
  .px-boss,
  .px-pop,
  .px-banner,
  .px-empty {
    font-family: 'Pixelify Sans', 'Press Start 2P', monospace;
  }
  .px-title {
    font-family: 'Pixelify Sans', monospace;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #ffce5e;
    text-shadow: 1px 1px 0 #000;
  }
  .g-arena-row {
    display: flex;
    gap: 10px;
    margin-top: 10px;
  }
  .g-arena-row .g-ladder-btn {
    margin-top: 0;
  }
  .px-stage {
    position: relative;
    height: 240px;
    overflow: hidden;
    border: 3px solid #2a1d12;
    border-radius: 4px;
    box-shadow: inset 0 0 0 2px #11140f, inset 0 0 0 4px #b8923f, 0 6px 22px rgba(0, 0, 0, 0.55);
    image-rendering: pixelated;
  }
  /* параллакс-фон (лесные сумерки) */
  .px-bg {
    position: absolute;
    inset: 0;
  }
  .px-bg.sky {
    background: linear-gradient(180deg, #14313a 0%, #1c4a4a 45%, #2f6157 72%, #3c5f3f 100%);
  }
  .px-bg.hills {
    bottom: 46px;
    top: auto;
    height: 120px;
    background:
      radial-gradient(60px 40px at 20% 100%, #16323a 60%, transparent 62%),
      radial-gradient(80px 52px at 55% 100%, #122b32 60%, transparent 62%),
      radial-gradient(70px 46px at 88% 100%, #16323a 60%, transparent 62%);
    opacity: 0.9;
  }
  .px-bg.trees {
    bottom: 40px;
    top: auto;
    height: 96px;
    background-image: repeating-linear-gradient(
      90deg,
      transparent 0 8px,
      rgba(7, 20, 18, 0.9) 8px 10px,
      transparent 10px 26px,
      rgba(10, 26, 22, 0.85) 26px 34px,
      transparent 34px 48px
    );
    -webkit-mask-image: linear-gradient(180deg, transparent, #000 40%);
    mask-image: linear-gradient(180deg, transparent, #000 40%);
    opacity: 0.75;
  }
  .px-ground {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 46px;
    background: repeating-linear-gradient(90deg, #3a2e1f 0 14px, #322617 14px 28px);
    border-top: 4px solid #5a7a3a;
    box-shadow: inset 0 5px 0 rgba(0, 0, 0, 0.3);
  }
  /* боссовая HP-полоса */
  .px-boss {
    position: absolute;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    width: 72%;
    display: flex;
    align-items: center;
    gap: 6px;
    z-index: 4;
  }
  .px-boss-skull {
    color: #ff5a6a;
    font-size: 14px;
    text-shadow: 1px 1px 0 #000;
  }
  .px-boss-bar {
    flex: 1;
    height: 12px;
    background: #1a0d0d;
    border: 2px solid #000;
    box-shadow: inset 0 0 0 1px #5a2b2b;
    overflow: hidden;
    image-rendering: pixelated;
  }
  .px-boss-fill {
    height: 100%;
    background: repeating-linear-gradient(90deg, #ff3b3b 0 10px, #d12626 10px 12px);
    transition: width 0.25s linear;
    box-shadow: 0 0 8px rgba(255, 60, 60, 0.5);
  }
  .px-boss-tag {
    font-size: 11px;
    color: #ffce5e;
    text-shadow: 1px 1px 0 #000;
    white-space: nowrap;
  }
  /* поле боя */
  .px-field {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 30px;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    padding: 0 14px;
    z-index: 3;
  }
  .px-group {
    display: flex;
    align-items: flex-end;
    gap: 4px;
  }
  .px-group.hero {
    flex-direction: row-reverse;
  }
  .px-fig {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    transition: transform 0.14s ease;
  }
  .px-fig.hero.atk {
    transform: translateX(-16px);
  }
  .px-fig.foe.atk {
    transform: translateX(16px);
  }
  .px-fig.dead {
    opacity: 0.2;
    filter: grayscale(1);
  }
  .px-fig.dead .px-sprite {
    animation: none;
  }
  .px-sprite {
    position: relative;
    width: 50px;
    height: 50px;
    border: 2px solid var(--rc, #888);
    background: rgba(8, 10, 16, 0.55);
    box-shadow: 0 0 0 2px #0a0a12;
    overflow: hidden;
    animation: pxbob 1.7s steps(2) infinite;
    image-rendering: pixelated;
  }
  .px-sprite.foe :global(.pixel-canvas) {
    transform: scaleX(-1);
  }
  .px-sprite.boss {
    width: 64px;
    height: 64px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-color: #ff5a6a;
  }
  .px-skull {
    font-size: 40px;
    filter: drop-shadow(2px 2px 0 #000);
  }
  .px-fig.hit .px-sprite {
    animation: pxhit 0.2s steps(2);
    box-shadow: 0 0 0 2px #fff, 0 0 12px #fff;
  }
  .px-fig.heal .px-sprite {
    box-shadow: 0 0 0 2px #7fe07f, 0 0 12px #7fe07f;
  }
  .px-shadow {
    width: 40px;
    height: 8px;
    margin-top: -3px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.45);
    filter: blur(1px);
  }
  .px-hp {
    width: 44px;
    height: 5px;
    margin-bottom: 3px;
    background: #11131a;
    border: 1px solid #000;
  }
  .px-hp-fill {
    height: 100%;
    background: linear-gradient(180deg, #8bf07a, #36a83a);
    transition: width 0.2s linear;
  }
  .px-pop {
    position: absolute;
    left: 50%;
    top: -10px;
    transform: translateX(-50%);
    font-size: 14px;
    font-weight: 700;
    pointer-events: none;
    text-shadow: 1px 1px 0 #000;
    animation: pxpop 0.9s ease-out forwards;
    z-index: 6;
  }
  .px-pop.dmg {
    color: #ff5a6a;
  }
  .px-pop.heal {
    color: #8bf07a;
  }
  .px-empty {
    font-size: 12px;
    color: #cfd3db;
    align-self: center;
    padding-bottom: 8px;
  }
  .px-banner {
    position: absolute;
    left: 50%;
    top: 44%;
    transform: translate(-50%, -50%);
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 2px;
    padding: 8px 18px;
    border: 3px solid #000;
    background: rgba(10, 8, 14, 0.85);
    text-shadow: 2px 2px 0 #000;
    animation: pxbanner 0.4s steps(3) both;
    z-index: 7;
  }
  .px-banner.win {
    color: #8bf07a;
    box-shadow: 0 0 0 2px #8bf07a;
  }
  .px-banner.loss {
    color: #ff5a6a;
    box-shadow: 0 0 0 2px #ff5a6a;
  }
  .px-info {
    margin-top: 8px;
    text-align: center;
    font-size: 12px;
    color: #cfd3db;
  }
  @keyframes pxbob {
    0%,
    100% {
      transform: translateY(0);
    }
    50% {
      transform: translateY(-3px);
    }
  }
  @keyframes pxhit {
    0%,
    100% {
      transform: translateX(0);
    }
    50% {
      transform: translateX(3px);
    }
  }
  @keyframes pxpop {
    0% {
      opacity: 0;
      transform: translate(-50%, 6px);
    }
    25% {
      opacity: 1;
    }
    100% {
      opacity: 0;
      transform: translate(-50%, -28px);
    }
  }
  @keyframes pxbanner {
    0% {
      opacity: 0;
      transform: translate(-50%, -50%) scale(0.6);
    }
    100% {
      opacity: 1;
      transform: translate(-50%, -50%) scale(1);
    }
  }

  /* toast */
  .g-toast {
    position: absolute;
    left: 50%;
    bottom: 30px;
    transform: translateX(-50%);
    z-index: 80;
    background: rgba(20, 18, 26, 0.96);
    color: #fff;
    padding: 11px 20px;
    border-radius: 13px;
    font-family: Manrope, sans-serif;
    font-size: 13px;
    font-weight: 700;
    border: 1px solid rgba(255, 255, 255, 0.14);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5);
    animation: bubblePop 0.3s cubic-bezier(0.2, 0.85, 0.25, 1) both;
    white-space: nowrap;
  }
</style>
