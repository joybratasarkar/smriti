<script>
  import { getJSON, formatDate, formatTime, formatDateTime, dayKey, timeAgo, isQuiet } from './lib/format.js'

  let { id } = $props()

  let issue = $state(null)
  let error = $state('')

  $effect(() => {
    issue = null
    error = ''
    getJSON(`/api/issues/${id}`)
      .then((data) => (issue = data))
      .catch((e) => (error = e.message.startsWith('404') ? 'This issue does not exist.' : `Could not load issue (${e.message}).`))
  })

  // Group articles by calendar day (Indian time) for the timeline.
  let days = $derived.by(() => {
    if (!issue) return []
    const groups = new Map()
    for (const article of issue.articles) {
      const key = dayKey(article.published_at)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(article)
    }
    return [...groups.entries()].map(([key, articles]) => ({ key, label: formatDate(articles[0].published_at), articles }))
  })

  let sourceCount = $derived(issue ? new Set(issue.articles.map((a) => a.source_name)).size : 0)
</script>

<a href="#/" class="back">← All issues</a>

{#if error}
  <p class="error">{error}</p>
{:else if !issue}
  <p class="muted">Loading…</p>
{:else}
  <section class="issue-head">
    <h1>{issue.label}</h1>
    <div class="card-meta">
      <span class="pill">{issue.article_count} articles</span>
      <span>{sourceCount} sources</span>
      <span>first reported {formatDateTime(issue.first_seen)}</span>
    </div>
    {#if isQuiet(issue.last_seen)}
      <p class="status-box quiet">No reports found since <strong>{formatDateTime(issue.last_seen)}</strong> ({timeAgo(issue.last_seen)}).</p>
    {:else}
      <p class="status-box active">Still being reported · latest article {timeAgo(issue.last_seen)}.</p>
    {/if}
  </section>

  <ol class="timeline">
    {#each days as day (day.key)}
      <li class="day">
        <h3>{day.label}</h3>
        <ul>
          {#each day.articles as article (article.id)}
            <li class="entry">
              <time>{formatTime(article.published_at)}</time>
              <div>
                <a href={article.url} target="_blank" rel="noopener noreferrer" lang={article.language ?? undefined}>{article.title}</a>
                {#if article.snippet}
                  <p class="snippet" lang={article.language ?? undefined}>{article.snippet}</p>
                {/if}
                <p class="source">{article.source_name}</p>
              </div>
            </li>
          {/each}
        </ul>
      </li>
    {/each}
  </ol>
{/if}
