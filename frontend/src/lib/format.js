// Dates are shown in Indian time.
const TZ = 'Asia/Kolkata'

export function formatDate(iso) {
  return new Date(iso).toLocaleDateString('en-IN', { timeZone: TZ, day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('en-IN', { timeZone: TZ, hour: 'numeric', minute: '2-digit' })
}

export function formatDateTime(iso) {
  return `${formatDate(iso)}, ${formatTime(iso)}`
}

// "16 Oct": a timestamp, or a plain YYYY-MM-DD day (read as that day in India).
export function formatDay(iso) {
  return new Date(iso).toLocaleDateString('en-IN', { timeZone: TZ, day: 'numeric', month: 'short' })
}

// "9–14 Oct", "30 Sep – 2 Oct" or "16 Oct" for two YYYY-MM-DD days.
export function formatRange(start, end) {
  if (start === end) return formatDay(start)
  const [d1, m1] = formatDay(start).split(' ')
  const [d2, m2] = formatDay(end).split(' ')
  return m1 === m2 ? `${d1}–${d2} ${m1}` : `${d1} ${m1} – ${d2} ${m2}`
}

export function plural(n, word) {
  return `${n.toLocaleString('en-IN')} ${word}${n === 1 ? '' : 's'}`
}

// Calendar day key in Indian time, used to group the timeline.
export function dayKey(iso) {
  return new Date(iso).toLocaleDateString('en-CA', { timeZone: TZ })
}

export function timeAgo(iso) {
  const minutes = Math.round((Date.now() - new Date(iso)) / 60000)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} days ago`
}

// An issue with no new report for this long is shown as quiet.
const QUIET_AFTER_HOURS = 48

// Measured against the last fetch, not today: after it we haven't looked, so we can't say nothing was reported (I-021).
export function isQuiet(lastSeen, checked) {
  return new Date(checked) - new Date(lastSeen) > QUIET_AFTER_HOURS * 3600 * 1000
}

export async function getJSON(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}
