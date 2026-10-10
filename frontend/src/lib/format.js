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

export function isQuiet(lastSeen) {
  return Date.now() - new Date(lastSeen) > QUIET_AFTER_HOURS * 3600 * 1000
}

export async function getJSON(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}
