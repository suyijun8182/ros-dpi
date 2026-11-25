import assert from 'node:assert/strict'
import { remoteEntry } from '../src/remote-link.js'

assert.equal(remoteEntry({ domain: 'example.com', proto: 6, port: 80 }), 'http://example.com/')
assert.equal(remoteEntry({ domain: 'example.com', proto: 17, port: 443 }), 'https://example.com/')
assert.equal(remoteEntry({ remote: '192.0.2.1', proto: 6, port: 443 }), 'https://192.0.2.1/')
assert.equal(remoteEntry({ remote: '2001:db8::1', proto: 6, port: 443 }), 'https://[2001:db8::1]/')
for (const domain of ['javascript:alert(1)', 'good.com@evil.com', 'good.com/evil', 'good.com?token=x', 'good.com#x', 'good.com\\evil', 'good.com\n', 'good.com:443', '%65vil.com', '[::1]:443']) {
  assert.equal(remoteEntry({ domain, proto: 6, port: 443 }), '', domain)
}
for (const [proto, port] of [[17, 80], [6, 22], [6, 8080], [1, 443]]) {
  assert.equal(remoteEntry({ domain: 'example.com', proto, port }), '')
}
console.log('Remote entry links: standard ports, IPv4/IPv6 and unsafe names verified')
