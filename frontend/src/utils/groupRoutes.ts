import type { AccessGroup } from '../types'

const PREFIX = '#/admin/groups/'

/** Encode names as individual segments, so slashes and URL punctuation stay in the name. */
export function groupUrl(group: AccessGroup): string {
  if (group.group_type === 'TENANT_SUBGROUP') {
    return `${PREFIX}tenants/${encodeURIComponent(group.name.toLowerCase())}`
  }
  const name = encodeURIComponent(group.name)
  // Keep a numeric group name distinct from a legacy database-ID bookmark.
  return PREFIX + (/^\d+$/.test(name) ? `%${name.charCodeAt(0).toString(16)}${name.slice(1)}` : name)
}

export function resolveGroupRoute(route: string, groups: AccessGroup[]): AccessGroup | undefined {
  if (!route.startsWith(PREFIX)) return undefined
  const path = route.slice(PREFIX.length).replace(/\/$/, '')
  if (/^\d+$/.test(path)) return groups.find((group) => group.id === Number(path))
  try {
    const segments = path.split('/').map(decodeURIComponent)
    const matches = groups.filter((group) => {
      if (segments.length === 2 && segments[0] === 'tenants') {
        return group.group_type === 'TENANT_SUBGROUP' && group.name.toLowerCase() === segments[1].toLowerCase()
      }
      return segments.length === 1 && group.group_type !== 'TENANT_SUBGROUP' && group.name === segments[0]
    })
    // Never silently select a different group when names are ambiguous.
    return matches.length === 1 ? matches[0] : undefined
  } catch {
    return undefined
  }
}
