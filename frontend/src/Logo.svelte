<script>
  // Smriti's mark (D-043): a story's path drawn as an S. It starts at a moment (the square), passes another,
  // and ends at "now" (the diamond), as on every story page.
  let { size = 34 } = $props()
</script>

<svg class="logo" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
  <path class="logo-road" d="M23 6.5 C 9 6.5, 7 15.5, 16 16 S 23 25.5, 9 25.5" />
  <rect class="logo-start" x="19.5" y="3" width="7" height="7" rx="1.8" />
  <rect class="logo-mid" x="13.6" y="13.6" width="4.8" height="4.8" rx="1.2" />
  <rect class="logo-now" x="5.2" y="21.7" width="7.6" height="7.6" rx="1.4" transform="rotate(45 9 25.5)" />
</svg>
