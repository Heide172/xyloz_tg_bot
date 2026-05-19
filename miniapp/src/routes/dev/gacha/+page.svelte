<script lang="ts">
  /**
   * Тест-контур для художника по контракту гача-v2 (см. docs/gacha_v2.md).
   * 4 контекста рендера на одной странице:
   *   1. ККИ-карта (card_art + UI-рамка по редкости)
   *   2. Боевой токен (battle_token в круге, ряд из 5)
   *   3. Тайл коллекции (portrait_anim, рамка по редкости)
   *   4. Фермовый слот (portrait_anim на farm_bg)
   *
   * Файлы кладутся в miniapp/static/gacha/<char_id>/{portrait_anim.webp,
   * card_art.webp, battle_token.png, splash_art.webp}.
   * Бэкенд не нужен; npm run dev → instant HMR.
   */

  type Rarity = 'R' | 'SR' | 'SSR' | 'UR';

  let charId = 'sample';
  let charName = 'Sample Hero';
  let rarity: Rarity = 'SSR';
  let stars = 3;
  let bust = 1;

  const SAMPLE_FALLBACK = {
    card_art: '/farm/heroine_idle.png',
    portrait_anim: '/farm/heroine_idle.png',
    battle_token: '/farm/cherry_t1.png'
  } as const;

  function assetUrl(slot: keyof typeof SAMPLE_FALLBACK, ext: string): string {
    if (charId === 'sample') return `${SAMPLE_FALLBACK[slot]}?b=${bust}`;
    return `/gacha/${charId}/${slot}.${ext}?b=${bust}`;
  }

  $: cardSrc = assetUrl('card_art', 'webp');
  $: portraitSrc = assetUrl('portrait_anim', 'webp');
  $: tokenSrc = assetUrl('battle_token', 'png');

  const RARITY_COLOR: Record<Rarity, string> = {
    R: '#8d949e',
    SR: '#4aa8ff',
    SSR: '#c277ff',
    UR: '#ffb444'
  };
  $: accent = RARITY_COLOR[rarity];

  function hideOnError(e: Event) {
    const el = e.target as HTMLImageElement | null;
    if (el) el.style.opacity = '0.2';
  }

  function setRarity(r: string) {
    rarity = r as Rarity;
  }
  function setStars(s: number) {
    stars = s;
  }
</script>

<a class="back" href="/">← на главную</a>
<h1 class="h1">Dev · гача-v2 плейграунд</h1>

<section class="card hint">
  <p><b>Контракт ассетов</b> (см. <code>docs/gacha_v2.md</code>):</p>
  <ul>
    <li><code>portrait_anim.webp</code> 512×512 — анимированный, для коллекции/баннера/фермы</li>
    <li><code>card_art.webp</code> 768×1024 — статичный портрет для ККИ-карты (рамка — UI)</li>
    <li><code>battle_token.png</code> 256×256 — для боевого токена (обрамляется UI в круг)</li>
    <li><code>splash_art</code> (опц.) 1920×1080 — для reveal-экрана UR</li>
  </ul>
  <p>Путь: <code>miniapp/static/gacha/&lt;char_id&gt;/&lt;file&gt;</code>. <code>npm run dev</code> → HMR.</p>
  <p class="muted small">
    Дефолтный <code>sample</code> использует ассеты фермы — убедиться что playground жив.
  </p>
</section>

<section class="card ctl">
  <label>char_id <input bind:value={charId} placeholder="например: aria" /></label>
  <label>имя <input bind:value={charName} placeholder="отображаемое имя" /></label>
  <div class="row">
    <div class="seg">
      {#each ['R', 'SR', 'SSR', 'UR'] as r}
        <button class:on={rarity === r} on:click={() => setRarity(r)}>{r}</button>
      {/each}
    </div>
    <div class="seg">
      {#each [1, 2, 3, 4, 5] as s}
        <button class:on={stars === s} on:click={() => setStars(s)}>{s}★</button>
      {/each}
    </div>
  </div>
  <button class="reload" on:click={() => (bust += 1)}>🔄 Reload ассеты (cache-bust)</button>
</section>

<div class="grid">
  <!-- 1. ККИ-карта -->
  <section class="card ctx">
    <div class="lbl">ККИ-карта</div>
    <div class="kki" style="--ac: {accent};">
      <div class="kki-art">
        <img src={cardSrc} alt={charName} on:error={hideOnError} />
      </div>
      <div class="kki-name">{charName}</div>
      <div class="kki-stars">
        {#each Array(5) as _, i}
          <span class:on={i < stars}>★</span>
        {/each}
      </div>
      <div class="kki-stats">
        <span>HP <b>1240</b></span>
        <span>ATK <b>320</b></span>
        <span>DEF <b>180</b></span>
        <span>SPD <b>95</b></span>
      </div>
      <div class="kki-ability">⚡ <i>Frostbite</i> · оглушает цель на 1 раунд</div>
      <div class="kki-rarity">{rarity}</div>
    </div>
  </section>

  <!-- 2. Боевой токен в строю 5 -->
  <section class="card ctx">
    <div class="lbl">Боевой ряд 5×</div>
    <div class="battle-row">
      {#each Array(5) as _, i}
        <div class="token" style="--ac: {accent};">
          <img src={tokenSrc} alt={charName} on:error={hideOnError} />
          <div class="hp"><div class="hp-fill" style="width: {[100, 78, 100, 45, 100][i]}%"></div></div>
        </div>
      {/each}
    </div>
    <div class="muted small">shake/flash/damage numbers рендерит движок, не художник.</div>
  </section>

  <!-- 3. Тайл коллекции -->
  <section class="card ctx">
    <div class="lbl">Тайл в коллекции</div>
    <div class="coll-grid">
      {#each Array(4) as _, i}
        <div class="coll-tile" class:dim={i === 3} style="--ac: {accent};">
          <img src={portraitSrc} alt={charName} on:error={hideOnError} />
          <div class="coll-stars">
            {#each Array(stars) as _}<span>★</span>{/each}
          </div>
        </div>
      {/each}
    </div>
  </section>

  <!-- 4. Фермовый слот -->
  <section class="card ctx">
    <div class="lbl">Слот на ферме</div>
    <div class="farm-slot">
      <img src={portraitSrc} alt={charName} on:error={hideOnError} />
    </div>
  </section>
</div>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .small { font-size: 12px; }
  code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    background: rgba(127, 127, 127, 0.12);
    padding: 1px 5px;
    border-radius: 4px;
  }
  .hint ul { padding-left: 18px; margin: 6px 0; }
  .hint li { margin: 4px 0; font-size: 13px; line-height: 1.5; }

  .ctl { display: flex; flex-direction: column; gap: 10px; }
  .ctl label { display: flex; gap: 8px; align-items: center; font-size: 13px; }
  .ctl input:not([type='checkbox']) {
    flex: 1; padding: 8px 10px; border: 1px solid var(--separator);
    border-radius: 8px; background: var(--bg); color: var(--text); font-size: 14px;
  }
  .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .seg {
    display: flex; gap: 0; border: 1px solid var(--separator); border-radius: 8px;
    overflow: hidden;
  }
  .seg button {
    padding: 6px 12px; border: 0; background: var(--bg); color: var(--text);
    cursor: pointer; font-size: 13px;
  }
  .seg button.on { background: var(--accent); color: var(--accent-text); }
  .reload {
    padding: 8px 14px; border: 0; border-radius: 8px; background: var(--accent);
    color: var(--accent-text); cursor: pointer; font-weight: 600; font-size: 13px;
    align-self: flex-start;
  }

  .grid {
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;
    margin-top: 4px;
  }
  .ctx { padding: 12px; }
  .lbl {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
    color: var(--text-muted); margin-bottom: 8px;
  }

  /* ──── ККИ-карта ──── */
  .kki {
    position: relative;
    background: linear-gradient(180deg, color-mix(in srgb, var(--ac) 22%, transparent), transparent 60%);
    border: 2px solid var(--ac);
    border-radius: 14px;
    padding: 10px;
    box-shadow: 0 0 18px color-mix(in srgb, var(--ac) 25%, transparent);
  }
  .kki-art {
    aspect-ratio: 3 / 4;
    border-radius: 8px;
    overflow: hidden;
    background: rgba(0, 0, 0, 0.15);
  }
  .kki-art img { width: 100%; height: 100%; object-fit: cover; }
  .kki-name { font-weight: 700; font-size: 15px; margin-top: 6px; text-align: center; }
  .kki-stars { text-align: center; color: #555; font-size: 13px; }
  .kki-stars .on { color: var(--ac); }
  .kki-stats {
    display: grid; grid-template-columns: 1fr 1fr; gap: 2px 8px;
    font-size: 12px; margin-top: 4px;
  }
  .kki-stats b { float: right; }
  .kki-ability {
    margin-top: 6px; font-size: 12px; color: var(--text-muted);
    background: rgba(0, 0, 0, 0.15); padding: 5px 7px; border-radius: 6px;
  }
  .kki-rarity {
    position: absolute; top: 6px; right: 8px;
    font-weight: 800; font-size: 11px; color: var(--ac);
    background: rgba(0, 0, 0, 0.35); padding: 2px 6px; border-radius: 4px;
  }

  /* ──── Боевой ряд ──── */
  .battle-row { display: flex; gap: 6px; justify-content: space-between; }
  .token {
    flex: 1; aspect-ratio: 1; border-radius: 50%; overflow: hidden;
    position: relative; border: 2px solid var(--ac);
    background: rgba(0, 0, 0, 0.15);
    box-shadow: 0 0 10px color-mix(in srgb, var(--ac) 30%, transparent);
  }
  .token img { width: 100%; height: 100%; object-fit: cover; }
  .hp {
    position: absolute; bottom: 4px; left: 8%; right: 8%;
    height: 4px; background: rgba(0, 0, 0, 0.4); border-radius: 2px; overflow: hidden;
  }
  .hp-fill { height: 100%; background: #5fbf7f; transition: width 0.3s; }

  /* ──── Тайл коллекции ──── */
  .coll-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .coll-tile {
    position: relative; aspect-ratio: 1; border-radius: 8px; overflow: hidden;
    border: 2px solid var(--ac); padding: 2px;
    background: rgba(0, 0, 0, 0.1);
  }
  .coll-tile img { width: 100%; height: 100%; object-fit: cover; border-radius: 6px; }
  .coll-tile.dim img { filter: grayscale(1) brightness(0.5); }
  .coll-stars {
    position: absolute; bottom: 2px; left: 0; right: 0;
    text-align: center; color: var(--ac); font-size: 10px; text-shadow: 0 0 3px #000;
  }

  /* ──── Фермовый слот ──── */
  .farm-slot {
    aspect-ratio: 1; max-width: 240px; margin: 0 auto;
    background: rgba(127, 127, 127, 0.08);
    background-image: url('/farm/farm_bg.png');
    background-size: cover; background-position: center;
    border-radius: 12px; overflow: hidden; position: relative;
    display: flex; align-items: flex-end; justify-content: center;
  }
  .farm-slot img { width: 70%; height: 70%; object-fit: contain; }
</style>
