// A web entry inferred from a standard port, never an observed request URL.
export function remoteEntry(session) {
  const proto = Number(session.proto)
  const port = Number(session.port)
  const scheme = port === 80 && proto === 6 ? 'http' : port === 443 && [6, 17].includes(proto) ? 'https' : ''
  if (!scheme) return ''
  const host = session.domain || session.remote || ''
  // Reject URL syntax, credentials, escapes and control characters in observed names.
  if (!host || /[^a-zA-Z0-9.:[\]-]/.test(host)) return ''
  if (host.startsWith('[') && !/^\[[0-9a-fA-F:.]+\]$/.test(host)) return ''
  const authority = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host
  try {
    const url = new URL(`${scheme}://${authority}/`)
    if (url.username || url.password || url.port || url.pathname !== '/' || url.search || url.hash) return ''
    return url.href
  } catch { return '' }
}
