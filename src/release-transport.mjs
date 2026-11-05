import https from 'node:https';
import tuf from './vendor/tuf-js/dist/index.js';
import {requireValue as need} from './import-input.mjs';

const endpoint = value => {
  const url = new URL(value);
  need(url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash && url.pathname.endsWith('/'), 'trust_transport_endpoint');
  return url;
};
// URL范围由本机安装配置给出，metadata不能指定新源或通过重定向改变源。
export function createReleaseTransport({metadataBaseUrl, targetBaseUrl, ca}) {
  const metadata = endpoint(metadataBaseUrl), targets = endpoint(targetBaseUrl);
  async function* stream(value, limit, signal, base) {
    const url = new URL(value);
    need(url.origin === base.origin && url.pathname.startsWith(base.pathname) && !url.username && !url.password && !url.search && !url.hash, 'trust_transport_scope');
    need(Number.isSafeInteger(limit) && limit >= 0 && limit <= 536870912, 'trust_transport_capacity');
    let request, response;
    try {
      response = await new Promise((resolve, reject) => {
        request = https.get(url, {ca, signal, minVersion: 'TLSv1.2', headers: {'accept-encoding': 'identity'}, timeout: 30000}, resolve);
        request.on('error', reject); request.on('timeout', () => request.destroy(new Error('trust_transport_timeout')));
      });
      if (response.statusCode !== 200) throw new tuf.DownloadHTTPError('Metadata or target request failed', response.statusCode || 0);
      need(!response.headers['content-range'] && [undefined, 'identity'].includes(response.headers['content-encoding']), 'trust_transport_encoding');
      const declared = response.headers['content-length'];
      if (declared !== undefined) need(/^(0|[1-9][0-9]*)$/.test(declared) && BigInt(declared) <= BigInt(limit), 'trust_transport_capacity');
      let count = 0;
      for await (const chunk of response) {
        count += chunk.length; need(count <= limit, 'trust_transport_capacity'); yield chunk;
      }
      if (declared !== undefined) need(count === Number(declared), 'trust_transport_length');
    } finally { response?.destroy(); request?.destroy(); }
  }
  return Object.freeze({
    async downloadBytes(url, limit, signal) {
      need(limit <= 4194304, 'trust_transport_capacity'); const chunks = [];
      for await (const chunk of stream(url, limit, signal, metadata)) chunks.push(chunk);
      return Buffer.concat(chunks);
    },
    streamTarget(url, limit, signal) { return stream(url, limit, signal, targets); }
  });
}
