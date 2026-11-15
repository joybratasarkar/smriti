// What the reader has already seen (D-042), kept only in this browser. We store the news check time ("checked")
// they last saw, not the clock: a report is new to them when it came after the news they were shown.
// Storage can be blocked (private window, cleared site data); then nothing is marked.
const FRONT = 'smriti.seen.front'

function read(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // nothing kept: every visit looks like the first
  }
}

// Read once per page load, so switching tabs or regions keeps the same "last visit".
const frontBefore = read(FRONT)

// The news check the reader saw on their last visit to the front page (null on a first visit); records this one.
export function frontSeen(checked) {
  write(FRONT, checked)
  return frontBefore
}

// The same for one story page.
export function storySeen(id, checked) {
  const key = `smriti.seen.story.${id}`
  const before = read(key)
  write(key, checked)
  return before
}

export const after = (iso, seen) => Boolean(seen) && new Date(iso) > new Date(seen)
