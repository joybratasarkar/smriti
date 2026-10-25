<script>
  import { getJSON, formatDate, formatDay, isQuiet } from './lib/format.js'

  const PAGE = 30

  // When the news was last fetched: "quiet" is measured against it (I-021).
  let checked = $state(null)
  getJSON('/api/summary').then((s) => (checked = s.last_fetched)).catch(() => {})

  let sort = $state('recent')
  let query = $state('')
  let showSingles = $state(false)
  let issues = $state([])
  let total = $state(0)
  let loading = $state(true)
  let error = $state('')

  async function load(append = false) {
    loading = true
    error = ''
    const params = new URLSearchParams({
      sort,
      q: query,
      min_size: showSingles ? 1 : 2,
      limit: PAGE,
      offset: append ? issues.length : 0,
    })
    try {
      const data = await getJSON(`/api/issues?${params}`)
      issues = append ? [...issues, ...data.issues] : data.issues
      total = data.total
    } catch (e) {
      error = `Could not load issues (${e.message}). Is the API running on port 8010?`
    } finally {
      loading = false
    }
  }

  // Reload whenever a filter changes; debounce typing in the search box.
  let timer
  $effect(() => {
    sort; showSingles; query
    clearTimeout(timer)
    timer = setTimeout(() => load(), 250)
  })
</script>

<div class="toolbar">
  <input type="search" placeholder="Search headlines…" bind:value={query} />
  <div class="segmented">
    <button class:active={sort === 'recent'} onclick={() => (sort = 'recent')}>Latest</button>
    <button class:active={sort === 'biggest'} onclick={() => (sort = 'biggest')}>Most covered</button>
  </div>
  <label class="check"><input type="checkbox" bind:checked={showSingles} /> single-article stories</label>
</div>

{#if error}
  <p class="error">{error}</p>
{/if}

<p class="count">{total.toLocaleString()} {total === 1 ? 'issue' : 'issues'}</p>

<ul class="issues">
  {#each issues as issue (issue.id)}
    <li>
      <a href="#/issues/{issue.id}" class="card">
        <h2>{issue.label}</h2>
        <div class="card-meta">
          <span class="pill">{issue.article_count} {issue.article_count === 1 ? 'article' : 'articles'}</span>
          <span>{issue.source_count} {issue.source_count === 1 ? 'source' : 'sources'}</span>
          <span>{formatDate(issue.first_seen)}{#if formatDate(issue.first_seen) !== formatDate(issue.last_seen)}{' – '}{formatDate(issue.last_seen)}{/if}</span>
          {#if checked && isQuiet(issue.last_seen, checked)}
            <span class="status quiet">quiet since {formatDay(issue.last_seen)}</span>
          {:else if checked}
            <span class="status active">active · latest {formatDay(issue.last_seen)}</span>
          {/if}
        </div>
        <p class="sources">{issue.sources.join(' · ')}</p>
      </a>
    </li>
  {/each}
</ul>

{#if loading}
  <p class="muted">Loading…</p>
{:else if issues.length < total}
  <button class="more" onclick={() => load(true)}>Show more</button>
{:else if !issues.length && !error}
  <p class="muted">No issues match.</p>
{/if}
