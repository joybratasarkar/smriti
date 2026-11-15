<script>
  import { plural, timeAgo } from './lib/format.js'

  // One front-page story (D-032, simplified by D-037): category · region, title, the latest moment, outlets and time.
  // Only the lead card draws the mini dot-path (dot size is how much was reported, ending at a pulsing "now").
  // The whole card opens the story page.
  let { story, lead = false } = $props()

  let biggest = $derived(Math.max(...story.dots))
  const size = (n) => 7 + 16 * Math.sqrt(n / biggest)
</script>

<a href="#/issues/{story.id}" class="fcard" class:lead>
  <div class="ftag">
    <span>{story.category} · {story.region}</span>
    {#if story.new}<span class="new">New</span>{/if}
  </div>
  <h2>{story.title}</h2>
  {#if lead}
    <div class="minipath" aria-hidden="true">
      {#each story.dots as n, i (i)}
        <span class="mdot" class:last={i === story.dots.length - 1} style="width:{size(n)}px;height:{size(n)}px"></span>
      {/each}
      <span class="mdot now"></span>
    </div>
  {/if}
  <p class="latest"><span>Latest:</span> {story.latest}</p>
  <p class="fmeta">{plural(story.outlets, 'outlet')} · {timeAgo(story.last_seen)}</p>
</a>
