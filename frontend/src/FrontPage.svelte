<script>
  import StoryCard from './StoryCard.svelte'
  import { getJSON } from './lib/format.js'

  // "Today's stories" (D-032): one lead story, then 12 cards at a time, most outlets first.
  let { topic = 'Top' } = $props()
  const FIRST = 13
  const PAGE = 12

  let stories = $state([])
  let total = $state(0)
  let loading = $state(true)
  let error = $state('')

  async function load() {
    loading = true
    error = ''
    const offset = stories.length
    const params = new URLSearchParams({ topic, offset, limit: offset ? PAGE : FIRST })
    try {
      const data = await getJSON(`/api/front?${params}`)
      stories = [...stories, ...data.stories]
      total = data.total
    } catch (e) {
      error = `Could not load today's stories (${e.message}). Is the API running on port 8010?`
    } finally {
      loading = false
    }
  }
  load()
</script>

<div class="front-head">
  <h1 class="page-title">{topic === 'Top' ? "Today's stories" : topic}</h1>
  <p>Most reported in the 48 hours before the last check, by number of outlets</p>
</div>

{#if error}
  <p class="error">{error}</p>
{/if}

{#if stories.length}
  <StoryCard story={stories[0]} lead />
  <div class="fgrid">
    {#each stories.slice(1) as story (story.id)}
      <StoryCard {story} />
    {/each}
  </div>
{/if}

{#if loading}
  <p class="muted">Loading…</p>
{:else if stories.length < total}
  <button class="more" onclick={load}>Show {Math.min(PAGE, total - stories.length)} more</button>
{:else if !stories.length && !error}
  <p class="muted">No stories with 4 or more reports in the last 48 hours of news. <a href="#/all">See all stories</a>.</p>
{/if}

<p class="muted small all-link"><a href="#/all">All stories</a>, including the small ones and the repeating columns left out here.</p>
