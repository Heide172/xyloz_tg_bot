<script lang="ts">
  export let game: 'slots' | 'coinflip' | 'dice' | 'roulette' | 'blackjack';

  // 10 paylines: индекс ряда (0=верх, 1=центр, 2=низ) на каждом из 5 барабанов.
  // Совпадает с SLOT_LINES в casino_service.
  const PAYLINES: number[][] = [
    [1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0],
    [2, 2, 2, 2, 2],
    [0, 1, 2, 1, 0],
    [2, 1, 0, 1, 2],
    [0, 0, 1, 0, 0],
    [2, 2, 1, 2, 2],
    [1, 2, 2, 2, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 0, 1, 1]
  ];

  // Пример выигрыша: 5 диамантов на центральной линии.
  const EXAMPLE_GRID: string[][] = [
    ['lemon', 'bell', 'cherry', 'star', 'lemon'],
    ['diamond', 'diamond', 'diamond', 'diamond', 'diamond'],
    ['cherry', 'lemon', 'bell', 'cherry', 'star']
  ];

  const SYM_TILES = [
    { n: 'diamond', p: [10, 27, 72] },
    { n: 'star', p: [9, 20, 50] },
    { n: 'bell', p: [5, 14, 36] },
    { n: 'lemon', p: [5, 11, 24] },
    { n: 'cherry', p: [4, 10, 20] }
  ];
</script>

<details class="rules">
  <summary>📖 Правила и выплаты</summary>
  <div class="body">
    {#if game === 'slots'}
      <p>Барабаны <b>5×3</b>, <b>10 линий</b> слева направо.
        Ставка делится на 10 — это «ставка-на-линию» (bet/10).</p>

      <div class="lbl">Выплаты по символам <span class="muted small">×ставка-на-линию · 3 / 4 / 5 подряд слева</span></div>
      <div class="symtiles">
        {#each SYM_TILES as s}
          <div class="symtile">
            <img class="sym" src={`/slots/${s.n}.png`} alt={s.n} />
            <div class="pays">
              <span><b>3</b> →&nbsp;{s.p[0]}</span>
              <span><b>4</b> →&nbsp;{s.p[1]}</span>
              <span><b>5</b> →&nbsp;{s.p[2]}</span>
            </div>
          </div>
        {/each}
      </div>

      <div class="lbl">10 линий выплат</div>
      <div class="lines-grid">
        {#each PAYLINES as line, i}
          <div class="line-mini">
            <div class="line-lbl">Линия {i + 1}</div>
            <svg viewBox="0 0 68 40" preserveAspectRatio="xMidYMid meet">
              {#each [0, 1, 2] as r}
                {#each [0, 1, 2, 3, 4] as c}
                  <rect
                    x={c * 14}
                    y={r * 14}
                    width="12"
                    height="12"
                    rx="2"
                    class="lcell"
                    class:on={line[c] === r}
                  />
                {/each}
              {/each}
              <polyline
                points={line.map((r, c) => `${c * 14 + 6},${r * 14 + 6}`).join(' ')}
                class="ltrace"
              />
            </svg>
          </div>
        {/each}
      </div>

      <div class="lbl">Особые символы</div>
      <div class="specials">
        <div class="spec">
          <img class="sym" src="/slots/wild.png" alt="wild" />
          <div><b>Wild</b> — заменяет любой символ (кроме scatter),
            достраивает линии.</div>
        </div>
        <div class="spec">
          <img class="sym" src="/slots/scatter.png" alt="scatter" />
          <div><b>Scatter</b> — платит от <b>общей</b> ставки в любых
            позициях: 3 → ×2, 4 → ×4, 5 → ×10.<br />
            3+ scatter → <b>фриспины</b> (3 → 4, 4 → 5, 5 → 7 спинов,
            выигрыши <b>×2</b>).</div>
        </div>
      </div>

      <div class="lbl">Пример выигрыша</div>
      <div class="ex-wrap">
        <div class="ex-grid">
          {#each EXAMPLE_GRID as row, ri}
            {#each row as name, ci}
              <div class="ex-cell" class:hit={ri === 1}>
                <img src={`/slots/${name}.png`} alt={name} />
              </div>
            {/each}
          {/each}
          <div class="ex-line"></div>
        </div>
        <p class="ex">Ставка <b>100</b> → линия = 10. Центральная линия:
          5×💎 = 72 × 10 = <b>720</b> 🎉</p>
      </div>

      <p class="muted small">RTP ≈ 94% (преимущество казино ≈ 6%).</p>
    {:else if game === 'coinflip'}
      <p>Угадай <b>орла или решку</b>. Победа — выплата
        <b>×1.98</b> (включая ставку).</p>
      <p class="ex">Пример: ставка 100, угадал → <b>198</b>
        (чистыми +98). Не угадал → −100.</p>
      <p class="muted small">Преимущество казино 2%.</p>
    {:else if game === 'dice'}
      <p>Бросок <b>1–100</b>. <b>over</b> — победа если выпало больше
        порога; <b>under</b> — если меньше.</p>
      <p>Множитель = (1 − 2%) / шанс. Чем рискованнее (меньше шанс) —
        тем выше выплата.</p>
      <p class="ex">Примеры: <b>under 50</b> (шанс 49%) → ×~2.0;
        <b>over 90</b> (шанс 10%) → ×~9.8;
        <b>over 50</b> (шанс 50%) → ×~1.96.</p>
      <p class="muted small">Преимущество казино 2%.</p>
    {:else if game === 'roulette'}
      <p>Колесо <b>0–36</b> (одно зеро). Множители включают возврат
        ставки:</p>
      <ul>
        <li><b>Число</b> (0–36) → <b>×36</b></li>
        <li><b>Цвет</b> (красное/чёрное) → <b>×2</b></li>
        <li><b>Чёт/нечет</b> → <b>×2</b></li>
        <li><b>Половина</b> (1–18 / 19–36) → <b>×2</b></li>
        <li><b>Дюжина</b> (1–12 / 13–24 / 25–36) → <b>×3</b></li>
      </ul>
      <p class="ex">Пример: 100 на красное, выпало красное →
        <b>200</b>. На число, угадал → <b>3600</b>.</p>
      <p class="muted small">Зеро (0) — внешние ставки проигрывают.</p>
    {:else if game === 'blackjack'}
      <p>Набери сумму ближе к <b>21</b>, не перебрав. Дилер добирает
        до <b>17</b> и встаёт.</p>
      <ul>
        <li>Победа → выплата <b>×2</b> (ставка + равный выигрыш).</li>
        <li><b>Блэкджек</b> (21 с двух карт) → <b>×2.5</b> (3:2).</li>
        <li>Ничья (push) → <b>возврат ставки</b>.</li>
        <li><b>Double</b> — удвоить ставку, добрать одну карту.</li>
        <li>Перебор (&gt;21) или меньше дилера → проигрыш.</li>
      </ul>
      <p class="ex">Пример: ставка 100, выиграл → <b>200</b>;
        блэкджек → <b>250</b>; ничья → 100 назад.</p>
    {/if}
  </div>
</details>

<style>
  .rules {
    margin: 14px 0 4px;
    background: var(--bg-elev, rgba(127, 127, 127, 0.06));
    border-radius: 12px;
    overflow: hidden;
  }
  summary {
    cursor: pointer;
    padding: 12px 14px;
    font-weight: 600;
    font-size: 14px;
    list-style: none;
  }
  summary::-webkit-details-marker {
    display: none;
  }
  summary::after {
    content: '▾';
    float: right;
    opacity: 0.5;
    transition: transform 0.15s;
  }
  details[open] summary::after {
    transform: rotate(180deg);
  }
  .body {
    padding: 0 14px 14px;
    font-size: 14px;
    line-height: 1.5;
  }
  .body p {
    margin: 8px 0;
  }
  .body ul {
    margin: 8px 0;
    padding-left: 18px;
  }
  .body li {
    margin: 4px 0;
  }
  .small {
    font-size: 12px;
  }
  .ex {
    background: var(--bg-elev-2, rgba(127, 127, 127, 0.1));
    border-radius: 8px;
    padding: 8px 10px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 13px;
  }
  th,
  td {
    text-align: center;
    padding: 5px 4px;
    border-bottom: 1px solid var(--separator, rgba(127, 127, 127, 0.2));
  }
  th:first-child,
  td:first-child {
    text-align: left;
  }
  th {
    color: var(--text-muted);
    font-weight: 600;
  }

  /* ---------- slots visuals ---------- */
  .lbl {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin: 14px 0 6px;
  }
  .symtiles {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 6px;
  }
  .symtile {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 6px 4px;
    background: var(--bg-elev-2, rgba(127, 127, 127, 0.08));
    border-radius: 8px;
  }
  .sym {
    width: 36px;
    height: 36px;
    object-fit: contain;
    image-rendering: -webkit-optimize-contrast;
  }
  .pays {
    display: flex;
    flex-direction: column;
    align-items: center;
    font-size: 11px;
    line-height: 1.35;
    color: var(--text-muted);
  }
  .pays span {
    white-space: nowrap;
  }
  .pays b {
    color: var(--text);
  }
  .lines-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }
  .line-mini {
    padding: 6px 8px;
    background: var(--bg-elev-2, rgba(127, 127, 127, 0.08));
    border-radius: 8px;
  }
  .line-lbl {
    font-size: 11px;
    color: var(--text-muted);
    margin-bottom: 3px;
  }
  .line-mini svg {
    width: 100%;
    height: auto;
    display: block;
  }
  .lcell {
    fill: rgba(127, 127, 127, 0.18);
  }
  .lcell.on {
    fill: var(--accent, #4aa8ff);
    opacity: 0.45;
  }
  .ltrace {
    fill: none;
    stroke: var(--accent, #4aa8ff);
    stroke-width: 1.3;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .specials {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .spec {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 8px 10px;
    background: var(--bg-elev-2, rgba(127, 127, 127, 0.08));
    border-radius: 8px;
    font-size: 13px;
    line-height: 1.4;
  }
  .spec .sym {
    width: 40px;
    height: 40px;
    flex-shrink: 0;
  }
  .ex-wrap {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .ex-grid {
    position: relative;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 4px;
    padding: 6px;
    background: var(--bg-elev-2, rgba(127, 127, 127, 0.08));
    border-radius: 10px;
  }
  .ex-cell {
    aspect-ratio: 1 / 1;
    background: var(--bg);
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 4px;
  }
  .ex-cell.hit {
    background: color-mix(in srgb, var(--accent, #4aa8ff) 18%, transparent);
    outline: 1.5px solid var(--accent, #4aa8ff);
  }
  .ex-cell img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .ex-line {
    position: absolute;
    left: 6px;
    right: 6px;
    top: 50%;
    height: 2px;
    background: var(--accent, #4aa8ff);
    opacity: 0.55;
    pointer-events: none;
  }
</style>
