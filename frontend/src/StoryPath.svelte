<script>
  // A story's timeline as a path of key moments (D-030): left to right when wide, winding downward when narrow.
  // The last stop is "now". Linked stories hang off the moment they connect to as small side dots.
  import { tick } from 'svelte'
  import { formatDay, formatRange, plural } from './lib/format.js'
  import { after } from './lib/visits.js'

  // `seen`: the news check of the reader's last visit; dots with reports after it get a ring (D-042).
  let { moments, latest, links = [], seen = null, open = $bindable() } = $props()

  const LINK_NAMES = {
    same_story: 'same event',
    follow_up: 'follow-up',
    same_actor: 'same person or group',
    same_topic: 'similar news',
    related: 'related',
  }
  const SIDE_DOTS = 6

  let map = $state()
  let narrow = $state(false)
  let road = $state({ path: '', branches: [] })

  let biggest = $derived(Math.max(...moments.map((m) => m.count)))
  const size = (count) => Math.round(30 + 34 * Math.sqrt(count / biggest))

  // Each linked story sits at the moment closest to its first report.
  let sides = $derived.by(() => {
    const at = moments.map(() => [])
    for (const link of links.slice(0, SIDE_DOTS)) {
      const first = link.first_seen.slice(0, 10)
      let best = 0
      moments.forEach((m, i) => {
        if (Math.abs(Date.parse(m.start) - Date.parse(first)) < Math.abs(Date.parse(moments[best].start) - Date.parse(first))) best = i
      })
      at[best].push(link)
    }
    return at
  })

  // The road runs through the dot centres, so it is drawn after the browser has placed them.
  async function measure() {
    if (!map) return
    narrow = map.clientWidth < 640
    await tick()
    const box = map.getBoundingClientRect()
    const centre = (el) => {
      const r = el.getBoundingClientRect()
      return [r.left - box.left + r.width / 2, r.top - box.top + r.height / 2]
    }
    const pts = [...map.querySelectorAll('.dot')].map(centre)
    let path = pts.length ? `M${pts[0][0]},${pts[0][1]}` : ''
    for (let k = 1; k < pts.length; k++) {
      const [x0, y0] = pts[k - 1]
      const [x1, y1] = pts[k]
      path += narrow
        ? ` C${x0},${(y0 + y1) / 2} ${x1},${(y0 + y1) / 2} ${x1},${y1}`
        : ` C${(x0 + x1) / 2},${y0} ${(x0 + x1) / 2},${y1} ${x1},${y1}`
    }
    // Each side dot hangs from the one above it, or from its moment, so no line crosses text.
    const branches = [...map.querySelectorAll('.sdot')].map((sd) => {
      const stop = sd.closest('.stop')
      const above = sd.closest('.side').previousElementSibling
      const from = (above ?? (narrow ? stop.querySelector('.dot') : stop.querySelector('.reports'))).getBoundingClientRect()
      const to = sd.getBoundingClientRect()
      return `M${from.left - box.left + from.width / 2},${from.bottom - box.top} L${to.left - box.left + to.width / 2},${to.top - box.top}`
    })
    road = { path, branches }
  }

  $effect(() => {
    moments; links
    measure()
    const observer = new ResizeObserver(() => measure())
    observer.observe(map)
    return () => observer.disconnect()
  })

  function step(event, i) {
    const move = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    if (!move) return
    event.preventDefault()
    const next = map.querySelector(`.dot[data-i="${Math.min(moments.length, Math.max(0, i + move))}"]`)
    next?.focus()
  }
</script>

<div class="path" class:narrow bind:this={map}>
  <svg class="road" aria-hidden="true">
    <path class="line" d={road.path} />
    <path class="done" d={road.path} />
    {#each road.branches as d}<path class="branch" {d} />{/each}
  </svg>
  <ol class="stops">
    {#each moments as m, i}
      <li class="stop">
        <span class="when">{formatRange(m.start, m.end)}</span>
        <button
          type="button"
          class="dot"
          class:fresh={after(m.last, seen)}
          data-i={i}
          style:width="{size(m.count)}px"
          style:height="{size(m.count)}px"
          aria-expanded={open === i}
          aria-label="{formatRange(m.start, m.end)}: {m.label}, {plural(m.count, 'report')} from {plural(m.outlets, 'outlet')}{after(m.last, seen) ? ', new since your last visit' : ''}"
          onclick={() => (open = i)}
          onkeydown={(e) => step(e, i)}
        ><span class="n">{m.count}</span></button>
        <span class="label">{m.label}</span>
        <span class="reports">{plural(m.count, 'report')}</span>
        {#if sides[i].length}
          <div class="sides">
            {#each sides[i] as link (link.id)}
              <a class="side" href="#/issues/{link.id}" aria-label="Connected story ({LINK_NAMES[link.link_type] ?? link.link_type}): {link.label}">
                <span class="sdot"></span>
                <span class="stype">{LINK_NAMES[link.link_type] ?? link.link_type}</span>
                <span class="sname">{link.label}</span>
              </a>
            {/each}
          </div>
        {/if}
      </li>
    {/each}
    <li class="stop now">
      <span class="flag">NOW</span>
      <button
        type="button"
        class="dot"
        data-i={moments.length}
        aria-expanded={open === moments.length}
        aria-label="Now: latest report {formatDay(latest.published_at)}"
        onclick={() => (open = moments.length)}
        onkeydown={(e) => step(e, moments.length)}
      ></button>
      <span class="label">{latest.title}</span>
      <span class="reports">latest {formatDay(latest.published_at)}</span>
    </li>
  </ol>
</div>
