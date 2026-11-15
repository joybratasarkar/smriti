<script>
  import { getJSON, formatDate, formatDay, formatTime, formatDateTime, formatRange, dayKey, isQuiet, plural } from './lib/format.js'
  import StoryPath from './StoryPath.svelte'
  import { storySeen, after } from './lib/visits.js'

  let { id } = $props()

  let issue = $state(null)
  let error = $state('')
  let open = $state(0)           // which dot is open; moments.length is "now"
  let allHeadlines = $state(false)
  let copies = $state({})        // headline title -> its copies are shown
  let seen = $state(null)        // the news check of the reader's last visit to this story (D-042)

  $effect(() => {
    issue = null
    error = ''
    getJSON(`/api/issues/${id}`)
      .then((data) => {
        seen = storySeen(id, data.checked)
        issue = data
        open = data.moments.length  // start at "now": where the story stands
      })
      .catch((e) => (error = e.message.startsWith('404') ? 'This story does not exist.' : `Could not load the story (${e.message}).`))
  })

  // A new dot shows its first few headlines again.
  $effect(() => {
    open
    allHeadlines = false
    copies = {}
  })

  const FIRST_HEADLINES = 4

  let latest = $derived(issue ? issue.articles[issue.articles.length - 1] : null)
  let moment = $derived(issue && open < issue.moments.length ? issue.moments[open] : null)
  let outletCount = $derived(issue ? new Set(issue.articles.map((a) => a.source_name)).size : 0)
  let anyLabelled = $derived(issue ? issue.moments.some((m) => m.labelled) : false)

  // Every report, grouped by calendar day (Indian time), for the folded list.
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

  // Small stories have no path, so their links stay a list. 'related' means the LLM hasn't named the link yet.
  const LINK_TYPES = {
    related: 'related',
    same_story: 'same event',
    follow_up: 'follow-up',
    same_actor: 'same person or group',
    same_topic: 'similar news',
  }
</script>

<a href="#/" class="back">← Today's stories</a>

{#if error}
  <p class="error">{error}</p>
{:else if !issue}
  <p class="muted">Loading…</p>
{:else}
  <section class="issue-head">
    <h1>{issue.title ?? issue.label}</h1>
    {#if issue.summary}<p class="summary">{issue.summary}</p>{/if}
    <p class="story-meta">
      {plural(issue.article_count, 'report')} ·
      {formatDay(issue.first_seen)}{#if formatDay(issue.first_seen) !== formatDay(issue.last_seen)}{' – '}{formatDay(issue.last_seen)}{/if} ·
      {plural(outletCount, 'news outlet')}
    </p>
    {#if isQuiet(issue.last_seen, issue.checked)}
      <p class="status-box quiet">No new reports since <strong>{formatDateTime(issue.last_seen)}</strong> · news checked up to {formatDay(issue.checked)}</p>
    {:else}
      <p class="status-box active">Still being reported · latest report <strong>{formatDateTime(issue.last_seen)}</strong> · news checked up to {formatDay(issue.checked)}</p>
    {/if}
  </section>

  {#if issue.mode === 'path'}
    {#if seen && issue.moments.some((m) => after(m.last, seen))}
      <p class="since">Dots marked <span class="fresh-dot" aria-hidden="true"></span> have reports since your last visit.</p>
    {/if}
    <StoryPath moments={issue.moments} {latest} links={issue.links} {seen} bind:open />

    <section class="moment" aria-live="polite">
      {#if moment}
        <h2>{moment.label} <small>{formatRange(moment.start, moment.end)} · {plural(moment.count, 'report')} · {plural(moment.outlets, 'outlet')}</small></h2>
        {#if moment.outlets === 1}
          <p class="single">Only one outlet has reported this so far.</p>
        {/if}
        <ul class="heads">
          {#each allHeadlines ? moment.heads : moment.heads.slice(0, FIRST_HEADLINES) as head (head.title)}
            <li>
              <a href={head.outlets[0].url} target="_blank" rel="noopener noreferrer">{head.title}</a>
              <p class="src">
                {#if after(head.time, seen)}<span class="new">New since your last visit</span>{/if}
                <span>{head.outlets[0].name} · {formatDay(head.time)}, {formatTime(head.time)}</span>
                {#if head.outlets.length > 1}
                  {#if copies[head.title]}
                    {#each head.outlets.slice(1) as copy}
                      <a href={copy.url} target="_blank" rel="noopener noreferrer">{copy.name}</a>
                    {/each}
                  {:else}
                    <button type="button" class="link" onclick={() => (copies[head.title] = true)}>
                      +{head.outlets.length - 1} more {head.outlets.length === 2 ? 'copy' : 'copies'}
                    </button>
                  {/if}
                {/if}
              </p>
            </li>
          {/each}
        </ul>
        {#if !allHeadlines && moment.heads.length > FIRST_HEADLINES}
          <button type="button" class="more" onclick={() => (allHeadlines = true)}>Show all {moment.heads.length + moment.more} headlines</button>
        {:else if allHeadlines && moment.more}
          <p class="muted small">{moment.more} more in the full list below.</p>
        {/if}
      {:else}
        <h2>Where it stands now</h2>
        <ul class="heads">
          <li>
            <a href={latest.url} target="_blank" rel="noopener noreferrer" lang={latest.language ?? undefined}>{latest.title}</a>
            <p class="src"><span>{latest.source_name} · {formatDay(latest.published_at)}, {formatTime(latest.published_at)} · the latest report</span></p>
          </li>
        </ul>
        <p class="muted small">News checked up to {formatDateTime(issue.checked)}. Anything published after that isn't here yet.</p>
      {/if}
    </section>

    {#if anyLabelled || issue.summary}
      <p class="muted small">The summary and the short labels on the dots are written by AI from the headlines and checked against them. The headlines are the reports themselves.</p>
    {/if}
  {:else if issue.links.length}
    <section class="links">
      <h2>Connected stories</h2>
      <ul class="issues">
        {#each issue.links as link (link.id)}
          <li>
            <a href="#/issues/{link.id}" class="card">
              <h3>{link.label}</h3>
              <div class="card-meta">
                <span>{LINK_TYPES[link.link_type]}</span>
                <span>{plural(link.article_count, 'report')}</span>
                <span>{formatDate(link.first_seen)}{#if formatDate(link.first_seen) !== formatDate(link.last_seen)} – {formatDate(link.last_seen)}{/if}</span>
              </div>
            </a>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <details class="all-reports" open={issue.mode === 'list'}>
    <summary>All {plural(issue.article_count, 'report')}, day by day</summary>
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
  </details>
{/if}
