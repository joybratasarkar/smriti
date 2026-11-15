<script>
  import FrontPage from './FrontPage.svelte'
  import IssueList from './IssueList.svelte'
  import IssueDetail from './IssueDetail.svelte'
  import Logo from './Logo.svelte'
  import { getJSON, formatDay, formatTime } from './lib/format.js'

  // Minimal hash router: #/ is the front page, #/topic/Sports one category tab, #/topic/Sports/India
  // one tab in one region (#/topic/Top/World: every category), #/all every story,
  // #/search/<words> the search results, #/issues/42 one story.
  let hash = $state(location.hash)
  $effect(() => {
    const onChange = () => { hash = location.hash; window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  })
  let issueId = $derived(hash.match(/^#\/issues\/(\d+)/)?.[1])
  let topic = $derived(decodeURIComponent(hash.match(/^#\/topic\/([^/]+)/)?.[1] ?? 'Top'))
  let region = $derived(hash.match(/^#\/topic\/[^/]+\/(India|World)/)?.[1] ?? 'All')
  let search = $derived(hash.startsWith('#/search/') ? decodeURIComponent(hash.slice(9)) : null)
  let all = $derived(hash.startsWith('#/all') || search !== null)

  // Tabs and when the news was last checked (D-032): an old fetch turns the top bar amber.
  let top = $state(null)
  getJSON('/api/front?limit=0').then((t) => (top = t)).catch(() => {})
  let stale = $derived(top && Date.now() - new Date(top.checked) > 24 * 3600 * 1000)

  let query = $state('')
  $effect(() => { if (search !== null) query = search })
  function submit(e) {
    e.preventDefault()
    const q = query.trim()
    location.hash = q ? `#/search/${encodeURIComponent(q)}` : '#/all'
  }
</script>

<header class="masthead">
<div class="topbar">
  <a href="#/" class="brand" aria-label="Smriti, today's stories">
    <Logo />
    <span>
      <strong>smriti</strong>
      <small>news that remembers</small>
    </span>
  </a>
  <nav class="tabs" aria-label="Topics">
    <a href={region === 'All' ? '#/' : `#/topic/Top/${region}`} aria-current={!issueId && !all && topic === 'Top' ? 'page' : undefined}>Top stories</a>
    {#each top?.tabs ?? [] as tab (tab.name)}
      <a href="#/topic/{encodeURIComponent(tab.name)}{region === 'All' ? '' : `/${region}`}" aria-current={!issueId && !all && topic === tab.name ? 'page' : undefined}>{tab.name}</a>
    {/each}
  </nav>
  <form class="find" role="search" onsubmit={submit}>
    <input type="search" placeholder="Search all stories" aria-label="Search all stories" bind:value={query} />
  </form>
  {#if top}
    <p class="checked" class:stale>
      {#if stale}
        news may be out of date · last updated {formatDay(top.checked)}
      {:else}
        updated {formatTime(top.checked)}
      {/if}
    </p>
  {/if}
</div>
</header>

<main class:wide={!issueId && !all}>
  {#if issueId}
    {#key issueId}
      <IssueDetail id={issueId} />
    {/key}
  {:else if all}
    {#key search}
      <IssueList initialQuery={search ?? ''} />
    {/key}
  {:else}
    {#key `${topic}/${region}`}
      <FrontPage {topic} {region} />
    {/key}
  {/if}
</main>
