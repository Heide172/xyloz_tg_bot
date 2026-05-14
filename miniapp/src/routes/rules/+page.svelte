<script lang="ts">
  const sections = [
    {
      title: 'Как это работает',
      body:
        'В каждом чате свой банк и свои гривны. Новичок получает 1000 гривен при первом действии в боте. Все операции пишутся в журнал.'
    },
    {
      title: 'Как заработать',
      bullets: [
        '/fag — ежедневный розыгрыш «кто_дня». Победитель получает приз из банка чата.',
        'Победа на рынках — выплата из общего пула пропорционально твоей ставке.',
        '/transfer @user СУММА — перевод между участниками.'
      ]
    },
    {
      title: 'Базовые команды',
      mono: [
        '/balance              — твой баланс',
        '/leaderboard          — топ-20 чата',
        '/economy              — состояние банка',
        '/transfer @user СУММА — перевод'
      ]
    },
    {
      title: 'Рынки ставок (parimutuel)',
      body:
        'Все ставки идут в общий пул. После закрытия рынка пул делится между поставившими на выигравший вариант — пропорционально размеру их ставок. Комиссия 5% уходит в банк чата.'
    },
    {
      title: 'Команды рынков',
      mono: [
        '/markets                   — список открытых',
        '/market ID                 — карточка рынка',
        '/bet ID ВАРИАНТ СУММА      — поставить',
        '/portfolio                 — мои ставки'
      ]
    },
    {
      title: 'Создание рынков',
      bullets: [
        '/market_create — диалог через бота. Комиссия 100 гривен в банк чата.',
        '/market_import URL — импорт с Polymarket или Manifold. Резолвится автоматически.'
      ]
    },
    {
      title: 'Важно',
      bullets: [
        'Минимальная ставка: 10 гривен.',
        'Если рынок отменён — деньги возвращаются.',
        'Комиссии копятся в банке чата и распределяются через номинации.'
      ]
    }
  ];
</script>

<a class="back" href={`/` + (typeof window !== 'undefined' ? window.location.search : '')}>← назад</a>

<h1 class="h1">Правила</h1>

<div class="sections">
  {#each sections as s}
    <section class="card">
      <h2 class="h2">{s.title}</h2>
      {#if s.body}
        <p class="body">{s.body}</p>
      {/if}
      {#if s.bullets}
        <ul>
          {#each s.bullets as b}
            <li>{b}</li>
          {/each}
        </ul>
      {/if}
      {#if s.mono}
        <pre class="mono">{s.mono.join('\n')}</pre>
      {/if}
    </section>
  {/each}
</div>

<style>
  .back {
    display: inline-block;
    margin-bottom: 12px;
    font-size: 14px;
    color: var(--text-muted);
  }
  .sections {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .body {
    margin: 0;
    line-height: 1.55;
  }
  ul {
    margin: 0;
    padding-left: 20px;
  }
  li {
    margin-bottom: 6px;
    line-height: 1.5;
  }
  li:last-child {
    margin-bottom: 0;
  }
  .mono {
    margin: 0;
    padding: 10px 12px;
    background: var(--bg-elev-2);
    border-radius: 8px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12.5px;
    line-height: 1.55;
    overflow-x: auto;
    color: var(--text);
  }
</style>
