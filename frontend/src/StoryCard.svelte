<script>
  import { plural, timeAgo } from './lib/format.js'

  // One front-page story (D-032). The mini dot-path has no labels: dot size is how much was reported,
  // and it ends at a pulsing "now". The whole card opens the story page.
  let { story, lead = false } = $props()

  let biggest = $derived(Math.max(...story.dots))
  const size = (n) => (lead ? 7 : 6) + (lead ? 16 : 10) * Math.sqrt(n / biggest)
</script>

<a href="#/issues/{story.id}" class="fcard" class:lead>
  <div class="ftag">
    {#if story.new}
      <span class="new">New</span>
    {:else}
      <span class="developing">Developing · day {story.day}</span>
    {/if}
    <span>{story.topic}</span>
  </div>
  <h2>{story.title}</h2>
  <div class="minipath" aria-hidden="true">
    {#each story.dots as n, i (i)}
      <span class="mdot" class:last={i === story.dots.length - 1} style="width:{size(n)}px;height:{size(n)}px"></span>
    {/each}
    <span class="mdot now"></span>
  </div>
  <p class="latest"><span>Latest:</span> {story.latest}</p>
  {#if lead}
    <ul class="lead-heads">
      {#each story.latest_heads as h (h)}<li>{h}</li>{/each}
    </ul>
  {/if}
  <p class="fmeta">
    {plural(story.reports, 'report')} · {plural(story.outlets, 'outlet')} in 48 h · updated {timeAgo(story.last_seen)}
  </p>
</a>
