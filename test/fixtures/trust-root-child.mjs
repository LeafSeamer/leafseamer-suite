import fs from 'node:fs';
import {openInstallationStore} from '../../dist/installation-store.mjs';
import tuf from '../../dist/vendor/tuf-js/dist/index.js';
import {fixedTime} from './tuf-repository.mjs';
const [directory, fixture] = process.argv.slice(2);
const files = new Map(JSON.parse(fs.readFileSync(fixture, 'utf8')).map(([name, bytes]) => [name, Buffer.from(bytes, 'base64')]));
const store = openInstallationStore(directory);
const session = store.trust.openVerification({trust_domain_id: 'synthetic', session_id: 'child.synthetic', fixed_reference_time: fixedTime,
  context: {anchor_id: 'anchor.synthetic', evidence_reference: 'evidence.synthetic', profile_id: 'profile.synthetic'}, metadata_base_url: 'https://synthetic.invalid/',
  fetcher: {async downloadBytes(url) {
    const name = new URL(url).pathname.split('/').at(-1);
    if (name === '3.root.json') {
      process.stdout.write(JSON.stringify(store.trust.current('synthetic')) + '\n');
      await new Promise(() => { setInterval(() => {}, 1000); });
    }
    const bytes = files.get(name); if (!bytes) throw new tuf.DownloadHTTPError('not found', 404); return bytes;
  }}});
try { await session.refresh(); } finally { session.close(); store.close(); }
