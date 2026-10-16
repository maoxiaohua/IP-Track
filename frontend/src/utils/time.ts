/**
 * Shared time formatting helpers.
 *
 * NOTE: `formatLastResponse` must stay identical to the "Last Response" column
 * shown in the subnet detail table and the IPAM Excel export, so both places
 * always show the same value.
 */

/**
 * Relative "Last Response" text based on when the IP actually responded.
 * Only `last_seen_at` is used on purpose (a scan timestamp is not a response).
 */
export function formatLastResponse(dateStr?: string | null): string {
  if (!dateStr) {
    return ''
  }

  try {
    const date = new Date(dateStr)
    const now = new Date()

    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffDays === 0) {
      if (diffMins < 1) return 'Just now'
      if (diffMins < 60) return `${diffMins} min ago`
      if (diffHours < 2) return `${diffHours} hour ago`
      return 'Today'
    }

    if (diffDays === 1) return 'Yesterday'

    if (diffDays < 7) return `${diffDays} days ago`

    if (diffDays < 30) {
      const weeks = Math.floor(diffDays / 7)
      return `${weeks} week${weeks > 1 ? 's' : ''} ago`
    }

    if (diffDays < 365) {
      const months = Math.floor(diffDays / 30)
      return `${months} month${months > 1 ? 's' : ''} ago`
    }

    const years = Math.floor(diffDays / 365)
    return `${years} year${years > 1 ? 's' : ''} ago`
  } catch {
    return 'Unknown'
  }
}

/** Absolute date time, e.g. 2025/05/21 08:45 */
export function formatDateTime(dateStr?: string | null): string {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return dateStr
  }
}
