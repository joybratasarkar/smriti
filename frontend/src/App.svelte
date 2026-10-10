<script>
  import IssueList from './IssueList.svelte'
  import IssueDetail from './IssueDetail.svelte'
  import { getJSON, formatDate, timeAgo } from './lib/format.js'

  // Minimal hash router: #/ is the list, #/issues/42 is one issue.
  let hash = $state(location.hash)
  $effect(() => {
    const onChange = () => { hash = location.hash; window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  })
  let issueId = $derived(hash.match(/^#\/issues\/(\d+)/)?.[1])

  let summary = $state(null)
  getJSON('/api/summary').then((s) => (summary = s)).catch(() => {})
</script>

<header>
  <a href="#/" class="brand">
    <span class="mark">स्</span>
    <span>
      <strong>Smriti</strong>
      <small>news that remembers</small>
    </span>
  </a>
  {#if summary}
    <p class="meta">
      {summary.articles.toLocaleString()} articles · {summary.sources} sources ·
      {formatDate(summary.oldest)} – {formatDate(summary.newest)} ·
      updated {timeAgo(summary.last_fetched)}
    </p>
  {/if}
</header>

<main>
  {#if issueId}
    {#key issueId}
      <IssueDetail id={issueId} />
    {/key}
  {:else}
    <IssueList />
  {/if}
</main>
