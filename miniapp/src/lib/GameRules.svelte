<script lang="ts">
  export let game: 'slots' | 'coinflip' | 'dice' | 'roulette' | 'blackjack';
</script>

<details class="rules">
  <summary>📖 Правила и выплаты</summary>
  <div class="body">
    {#if game === 'slots'}
      <p>Барабаны <b>5×3</b>, <b>10 линий</b>. Ставка делится на 10 —
        это «ставка-на-линию» (bet/10).</p>
      <table>
        <thead>
          <tr><th>Символ</th><th>3</th><th>4</th><th>5</th></tr>
        </thead>
        <tbody>
          <tr><td>💎 diamond</td><td>10</td><td>27</td><td>72</td></tr>
          <tr><td>⭐ star</td><td>9</td><td>20</td><td>50</td></tr>
          <tr><td>🔔 bell</td><td>5</td><td>14</td><td>36</td></tr>
          <tr><td>🍋 lemon</td><td>5</td><td>11</td><td>24</td></tr>
          <tr><td>🍒 cherry</td><td>4</td><td>10</td><td>20</td></tr>
        </tbody>
      </table>
      <p class="muted small">×ставка-на-линию, за 3/4/5 одинаковых
        подряд слева.</p>
      <ul>
        <li><b>🃏 Wild</b> — заменяет любой символ (кроме scatter),
          достраивает линии.</li>
        <li><b>✨ Scatter</b> — платит от <b>общей</b> ставки в любых
          позициях: 3 → ×2, 4 → ×4, 5 → ×10.</li>
        <li>3+ scatter → <b>фриспины</b>: 3 → 4, 4 → 5, 5 → 7 спинов,
          выигрыши в них <b>×2</b>.</li>
      </ul>
      <p class="ex">Пример: ставка <b>100</b> → линия 10.
        3×🔔 = 5×10 = <b>50</b>. 4×💎 = 27×10 = <b>270</b>.
        3×✨ = 2×100 = <b>200</b> + 4 фриспина ×2.</p>
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
</style>
