import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {Readable} from 'node:stream';
import {Metadata, MetadataKind} from '@tufjs/models';
import tuf from './vendor/tuf-js/dist/index.js';
import {inspectMetadata} from './tuf-input.mjs';
import {releaseAuthorizer} from './release-authorization.mjs';
import {requireValue as need, canonical, digest} from './import-input.mjs';
import {decodeReleaseManifest, decodeReleaseRevocations, releaseManifestSelection} from './sdk/release-manifest.mjs';

const hash = bytes => 'sha256:' + crypto.createHash('sha256').update(bytes).digest('hex');
const id = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}(?![\s\S])/.test(value);
const rawHash = value => typeof value === 'string' && /^sha256:[0-9a-f]{64}(?![\s\S])/.test(value);
const isTargetPath = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9/_.-]{0,239}$/.test(value) && value.trim() === value && value.split('/').every(part => part && part !== '.' && part !== '..');
function rootProfile(document) {
  const signed = document.signed;
  need(signed._type === 'root' && signed.consistent_snapshot === true, 'trust_root_profile');
  const material = new Set();
  for (const role of ['root', 'targets', 'timestamp', 'snapshot']) {
    const entry = signed.roles?.[role], offline = ['root', 'targets'].includes(role);
    need(entry && entry.threshold === (offline ? 2 : 1) && entry.keyids.length === (offline ? 3 : 1) && new Set(entry.keyids).size === entry.keyids.length, 'trust_root_threshold');
    for (const keyid of entry.keyids) {
      const key = signed.keys?.[keyid]; need(key && typeof key.keyval?.public === 'string', 'trust_root_key');
      const value = canonical({keytype: key.keytype, scheme: key.scheme, public: key.keyval.public});
      need(!material.has(value), 'trust_root_key_reuse'); material.add(value);
    }
  }
}

// 仅供已验证本机安装入口调用。这里持久保存认证结果，不把字段格式当作外部身份或时间证明。
export function trustMetadataStore({db, transact, installationIdentity, staging}) {
  const active = new Map(), sessionChecks = new Map(), documents = new Set();
  const one = (sql, ...values) => {
    const statement = db.prepare(sql), columns = statement.columns().map(column => column.name), row = statement.raw().get(...values);
    return row && Object.fromEntries(columns.map((name, index) => [name, row[index]]));
  };
  function state(domain) {
    const row = one('SELECT s.*,m.version,m.body,m.digest FROM trust_root_state s JOIN trusted_metadata m USING(metadata_id) WHERE s.trust_domain_id=?', domain);
    need(row && hash(row.body) === row.digest, 'trust_domain_unavailable'); return row;
  }
  function save(domain, role, epoch, bytes, document) {
    const metadataId = crypto.randomUUID();
    db.prepare('INSERT INTO trusted_metadata VALUES (?,?,?,?,?,?,?)').run(metadataId, domain, role, epoch, document.signed.version, bytes, hash(bytes));
    return metadataId;
  }
  const authorizer = releaseAuthorizer({db,one,transact,state,installationIdentity,currentSession(sessionId,domain) {
    need(active.get(domain) === sessionId && sessionChecks.has(sessionId),'trust_session_unavailable'); sessionChecks.get(sessionId)();
  }});
  return Object.freeze({
    get activeCount() { return active.size + documents.size; },
    releaseAuthorization(ref) { return authorizer.historical(ref); },
    assertCurrentRelease(ref, expected) { const verify = () => authorizer.assertCurrent(ref, expected); return db.inTransaction ? verify() : transact(verify); },
    currentReleaseForArtifact(ref,expected){const verify=()=>authorizer.currentForArtifact(ref,expected);return db.inTransaction?verify():transact(verify);},
    configureRevocations(domain, policy) {
      need(id(domain) && policy && Object.keys(policy).sort().join(',') === 'approval_reference,target_path' &&
        isTargetPath(policy.target_path) && id(policy.approval_reference), 'trust_revocation_policy');
      // 可信安装配置指定全局撤销路径，不能取自待安装包或普通调用者。
      return transact(() => {
        state(domain); need(!active.has(domain), 'trust_verification_in_progress');
        const prior = one('SELECT * FROM trust_revocation_policy WHERE trust_domain_id=?', domain);
        if (prior) need(prior.target_path === policy.target_path && prior.approval_reference === policy.approval_reference, 'trust_revocation_policy_conflict');
        else db.prepare('INSERT INTO trust_revocation_policy VALUES (?,?,?)').run(domain, policy.target_path, policy.approval_reference);
        return {trust_domain_id: domain, ...policy};
      });
    },
    initialize(domain, rootBytes, bootstrap) {
      need(id(domain), 'trust_domain_id'); rootBytes = Buffer.from(rootBytes);
      const document = inspectMetadata(rootBytes); rootProfile(document);
      const root = Metadata.fromJSON(MetadataKind.Root, document); root.verifyDelegate(MetadataKind.Root, root);
      need(bootstrap && Object.keys(bootstrap).sort().join(',') === 'approval_reference,bootstrap_operation_id,channel_kind,host_installation_id,initial_root_digest,verifier_digest' &&
        bootstrap.host_installation_id === installationIdentity.host_installation_id && bootstrap.initial_root_digest === hash(rootBytes) && rawHash(bootstrap.verifier_digest) &&
        id(bootstrap.bootstrap_operation_id) && id(bootstrap.approval_reference) && ['platform_verified_installer', 'independent_authenticated_channel'].includes(bootstrap.channel_kind), 'trust_bootstrap_context');
      const body = Buffer.from(canonical(bootstrap));
      return transact(() => {
        const prior = one('SELECT * FROM trust_domain WHERE trust_domain_id=?', domain);
        if (prior) { need(prior.bootstrap_digest === digest(bootstrap), 'trust_bootstrap_conflict'); return {trust_domain_id: domain, root_digest: state(domain).digest}; }
        db.prepare('INSERT INTO trust_domain VALUES (?,?,?)').run(domain, body, digest(bootstrap));
        const metadataId = save(domain, 'root', 0, rootBytes, document);
        db.prepare('INSERT INTO trust_root_state VALUES (?,?,?,?,?,?)').run(domain, 'root', 0, metadataId, 1, 0);
        return {trust_domain_id: domain, root_digest: hash(rootBytes)};
      });
    },
    openVerification({trust_domain_id: domain, session_id: sessionId, fixed_reference_time: referenceTime, context, metadata_base_url: baseUrl, target_base_url: targetBaseUrl, fetcher}) {
      need(id(domain) && id(sessionId) && Number.isSafeInteger(referenceTime) && Math.abs(referenceTime) <= 8640000000000000, 'trust_session_context');
      need(context && Object.keys(context).sort().join(',') === 'anchor_id,evidence_reference,profile_id' && Object.values(context).every(id), 'trust_time_context');
      const url = new URL(baseUrl); need(url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash, 'trust_metadata_url');
      const targetBase = targetBaseUrl === undefined ? null : new URL(targetBaseUrl);
      if (targetBase) need(targetBase.protocol === 'https:' && !targetBase.username && !targetBase.password && !targetBase.search && !targetBase.hash && targetBase.pathname.endsWith('/'), 'trust_target_url');
      need(!active.has(domain), 'trust_verification_in_progress');
      const started = performance.now(), abort = new AbortController(); let timer, closed = false, ready = false, busy = false, refreshed = false;
      const check = () => { need(!closed && performance.now() - started < 600000, 'trust_session_unavailable'); };
      const close = () => { closed = true; clearTimeout(timer); abort.abort(new Error('trust_session_closed')); sessionChecks.delete(sessionId); if (active.get(domain) === sessionId) active.delete(domain); };
      transact(() => {
        state(domain);
        need(!one('SELECT 1 FROM trust_verification_session WHERE session_id=?', sessionId), 'trust_session_reused');
        db.prepare('INSERT INTO trust_verification_session VALUES (?,?,?,?,?)').run(sessionId, domain, referenceTime, Buffer.from(canonical(context)), digest(context));
      });
      active.set(domain, sessionId);
      sessionChecks.set(sessionId, () => { check(); need(ready && !busy,'trust_session_unavailable'); });
      timer = setTimeout(close, 600000); timer.unref();
      const storage = {
        loadTrusted(role) {
          check();
          return transact(() => {
            const current = state(domain); if (role === 'root') return Buffer.from(current.body);
            need(!current.reset_pending, 'trust_rotation_pending');
            const row = one('SELECT m.* FROM trust_metadata_head h JOIN trusted_metadata m USING(metadata_id) WHERE h.trust_domain_id=? AND h.role=? AND h.epoch=?', domain, role, current.metadata_epoch);
            if (!row) return null;
            need(hash(row.body) === row.digest, 'trust_metadata_integrity'); inspectMetadata(row.body); return Buffer.from(row.body);
          });
        },
        persistVerified(role, bytes, transition) {
          check(); const document = inspectMetadata(bytes);
          if (role === 'root') rootProfile(document);
          transact(() => {
            const current = state(domain);
            if (role === 'root') {
              need(transition.kind === 'root' && transition.previous_version === current.version && transition.version === current.version + 1 &&
                hash(transition.previous_bytes) === current.digest && document.signed.version === transition.version, 'trust_root_preimage');
              const metadataId = save(domain, role, 0, bytes, document);
              db.prepare('INSERT INTO trust_root_transition VALUES (?,?,?,?,?)').run(crypto.randomUUID(), domain, current.metadata_id, metadataId, Number(transition.online_keys_changed));
            } else {
              need(transition.kind === 'metadata' && !current.reset_pending, 'trust_rotation_pending');
              need(role === document.signed._type || document.signed._type === 'targets', 'trust_metadata_role');
              const prior = one('SELECT m.* FROM trust_metadata_head h JOIN trusted_metadata m USING(metadata_id) WHERE h.trust_domain_id=? AND h.role=? AND h.epoch=?', domain, role, current.metadata_epoch);
              if (prior?.version === document.signed.version) { need(prior.digest === hash(bytes), 'trust_metadata_conflict'); return; }
              const metadataId = save(domain, role, current.metadata_epoch, bytes, document);
              db.prepare('INSERT INTO trust_metadata_head VALUES (?,?,?,?) ON CONFLICT(trust_domain_id,role,epoch) DO UPDATE SET metadata_id=excluded.metadata_id').run(domain, role, current.metadata_epoch, metadataId);
            }
          });
        },
        finalizeRootPhase(root) {
          check(); transact(() => {
            const current = state(domain); need(root.version === current.version && hash(root.bytes) === current.digest, 'trust_root_preimage');
            if (current.reset_pending) db.prepare('INSERT INTO trust_rotation VALUES (?,?,?,?,?)').run(crypto.randomUUID(), domain, current.metadata_id, current.metadata_epoch, current.metadata_epoch + 1);
          });
        }
      };
      let updater;
      try {
        need(fetcher && typeof fetcher.downloadBytes === 'function', 'trust_fetcher_required');
        // 安装器提供受控传输；本模块不从发行输入构造任意网络访问。
        const wrapped = {
          async downloadBytes(...args) {
            check(); const input = await fetcher.downloadBytes(...args, abort.signal); check(); need(Buffer.isBuffer(input), 'trust_metadata_bytes');
            const bytes = Buffer.from(input); inspectMetadata(bytes); return bytes;
          },
          downloadFile() { throw new Error('Target download is not exposed by metadata verification'); }
        };
        updater = new tuf.Updater({metadataDir: '', metadataBaseUrl: url.href, fixedReferenceTime: referenceTime, metadataStorage: storage, fetcher: wrapped,
          config: {rootMaxLength: 4194304, timestampMaxLength: 4194304, snapshotMaxLength: 4194304, targetsMaxLength: 4194304, maxRootRotations: 32, maxDelegations: 32}});
      } catch (error) { close(); throw error; }
      const targetPath = value => need(isTargetPath(value), 'trust_target_request');
      const checkedTarget = async value => {
        const target = await updater.getTargetInfo(value); check(); if (!target) return null;
        need(Number.isSafeInteger(target.length) && target.length >= 0 && target.length <= 536870912 && rawHash('sha256:' + target.hashes.sha256), 'trust_target_profile');
        return target;
      };
      return Object.freeze({
        async refresh() {
          check(); need(!busy && !refreshed, 'trust_refresh_once'); busy = true; refreshed = true;
          try { await updater.refresh(); check(); ready = true; return transact(() => ({session_id: sessionId, root_digest: state(domain).digest, metadata_epoch: state(domain).metadata_epoch})); }
          catch (error) { close(); throw error; } finally { busy = false; }
        },
        async target(path) {
          check(); need(ready && !busy, 'trust_target_request'); targetPath(path); busy = true;
          try {
            const target = await checkedTarget(path); if (!target) return null;
            return structuredClone({session_id: sessionId, path: target.path, length: target.length, hashes: target.hashes, custom: target.unrecognizedFields.custom ?? null});
          } catch (error) { close(); throw error; } finally { busy = false; }
        },
        async download(targetName) {
          check(); need(ready && !busy && targetBase && typeof fetcher.streamTarget === 'function', 'trust_target_download'); targetPath(targetName); busy = true;
          let output;
          try {
            const target = await checkedTarget(targetName); need(target, 'trust_target_unavailable');
            const downloadId = crypto.randomUUID(), packageDigest = 'sha256:' + target.hashes.sha256;
            const filename = path.join(staging, downloadId + '.target'), targetDocument = target.toJSON();
            transact(() => {
              const current = state(domain);
              const metadata = db.prepare('SELECT h.role,m.version,m.digest,m.metadata_id FROM trust_metadata_head h JOIN trusted_metadata m USING(metadata_id) WHERE h.trust_domain_id=? AND h.epoch=? ORDER BY h.role').raw().all(domain, current.metadata_epoch);
              metadata.unshift(['root', current.version, current.digest, current.metadata_id]);
              db.prepare('INSERT INTO trust_download_attempt VALUES (?,?,?,?,?,?,?,?,?)').run(downloadId, sessionId, targetName, target.length, packageDigest,
                Buffer.from(canonical(targetDocument)), digest(targetDocument), Buffer.from(canonical(metadata)), digest(metadata));
            });
            output = await fs.open(filename, 'wx+'); check();
            // consistent snapshots使用当前TargetFile的SHA256前缀，不能采用调用者提交的hash或URL。
            const parts = targetName.split('/'); parts[parts.length - 1] = target.hashes.sha256 + '.' + parts.at(-1);
            const targetUrl = new URL(parts.join('/'), targetBase).href; let count = 0;
            for await (const input of fetcher.streamTarget(targetUrl, target.length, abort.signal)) {
              check(); need(input instanceof Uint8Array && input.byteLength <= 1048576, 'trust_target_chunk'); const chunk = Buffer.from(input);
              count += chunk.length; need(count <= target.length, 'trust_target_length'); transact(() => state(domain));
              let offset = 0;
              while (offset < chunk.length) { check(); const result = await output.write(chunk, offset, chunk.length - offset); need(result.bytesWritten > 0, 'trust_target_write'); offset += result.bytesWritten; }
            }
            check(); need(count === target.length, 'trust_target_length');
            const handle = output;
            await target.verify(Readable.from((async function* () {
              for (let offset = 0; offset < target.length;) {
                check(); const buffer = Buffer.alloc(Math.min(65536, target.length - offset));
                const result = await handle.read(buffer, 0, buffer.length, offset); need(result.bytesRead > 0, 'trust_target_length');
                offset += result.bytesRead; yield buffer.subarray(0, result.bytesRead);
              }
            })(), {objectMode: false}));
            const stat = await output.stat(); need(stat.isFile() && stat.nlink === 1 && stat.size === target.length, 'trust_target_file');
            await output.sync(); await output.close(); output = undefined; check();
            transact(() => { db.prepare('INSERT INTO trust_download_receipt VALUES (?,?,?)').run(downloadId, target.length, packageDigest); });
            return {download_id: downloadId, session_id: sessionId, target_path: targetName, package_bytes: String(target.length), package_digest: packageDigest};
          } catch (error) { close(); throw error; } finally { try { await output?.close(); } finally { busy = false; } }
        },
        async authorizeExtension(input) {
          need(input && Object.keys(input).sort().join(',') === 'package_download_id,release_document_id','trust_release_request');
          const {release_document_id: releaseDocumentId, package_download_id: packageDownloadId} = input;
          check(); need(ready && !busy && id(releaseDocumentId) && id(packageDownloadId),'trust_release_request'); busy = true;
          try { return await authorizer.authorize({domain,sessionId,check,getTarget:checkedTarget,releaseDocumentId,packageDownloadId}); }
          catch (error) { close(); throw error; } finally { busy = false; }
        },
        async adoptRevocations(documentId) {
          check(); need(ready && !busy && id(documentId), 'trust_revocation_request'); busy = true;
          try {
            const source = transact(() => {
              const row = one(`SELECT d.*,a.session_id,a.target_path FROM trust_release_document d
                JOIN trust_download_attempt a USING(download_id) WHERE d.document_id=?`, documentId);
              const policy = one('SELECT * FROM trust_revocation_policy WHERE trust_domain_id=?', domain);
              need(row && policy && row.kind === 'revocations' && row.session_id === sessionId && row.target_path === policy.target_path &&
                row.decoder_id === releaseManifestSelection.contract_id && row.decoder_digest === releaseManifestSelection.contract_digest &&
                hash(row.body) === row.package_digest, 'trust_revocation_source');
              return row;
            });
            const value = await decodeReleaseRevocations(source.body); check();
            const target = await checkedTarget(source.target_path); check();
            need(target && target.length === source.package_bytes && 'sha256:' + target.hashes.sha256 === source.package_digest, 'trust_revocation_target');
            return transact(() => {
              check(); const current = state(domain); need(!current.reset_pending, 'trust_rotation_pending');
              const metadata = one(`SELECT m.* FROM trust_metadata_head h JOIN trusted_metadata m USING(metadata_id)
                WHERE h.trust_domain_id=? AND h.role='targets' AND h.epoch=?`, domain, current.metadata_epoch);
              need(metadata && hash(metadata.body) === metadata.digest, 'trust_metadata_integrity');
              // 全域撤销只能由根授权的顶层targets签发，不能由局部委托扩展到全域。
              const signedTarget = inspectMetadata(metadata.body).signed.targets[source.target_path];
              need(signedTarget && signedTarget.length === source.package_bytes && 'sha256:' + signedTarget.hashes?.sha256 === source.package_digest, 'trust_revocation_authority');
              const latest = one('SELECT * FROM trust_revocation_snapshot WHERE trust_domain_id=? ORDER BY length(revision) DESC,revision DESC LIMIT 1', domain);
              if (latest) {
                need(BigInt(value.revision) >= BigInt(latest.revision), 'trust_revocation_rollback');
                if (value.revision === latest.revision) need(latest.document_digest === source.package_digest, 'trust_revocation_conflict');
              }
              const snapshotId = latest?.revision === value.revision ? latest.snapshot_id : crypto.randomUUID();
              if (snapshotId !== latest?.snapshot_id) db.prepare('INSERT INTO trust_revocation_snapshot VALUES (?,?,?,?,?)')
                .run(snapshotId, domain, value.revision, documentId, source.package_digest);
              const prior = one('SELECT * FROM trust_revocation_adoption WHERE session_id=? AND document_id=?', sessionId, documentId);
              const adoptionId = prior?.adoption_id ?? crypto.randomUUID();
              if (!prior) db.prepare('INSERT INTO trust_revocation_adoption VALUES (?,?,?,?,?,?,?)')
                .run(adoptionId, domain, sessionId, documentId, snapshotId, source.package_digest, current.metadata_epoch);
              return {adoption_id: adoptionId, snapshot_id: snapshotId, trust_domain_id: domain, session_id: sessionId,
                document_id: documentId, revision: value.revision, document_digest: source.package_digest, metadata_epoch: current.metadata_epoch};
            });
          } catch (error) { close(); throw error; } finally { busy = false; }
        },
        close
      });
    },
    current(domain) { return transact(() => { const s = state(domain); return {root_version: s.version, root_digest: s.digest, metadata_epoch: s.metadata_epoch, reset_pending: s.reset_pending === 1}; }); },
    lookupRevocation(domain, kind, value) {
      need(id(domain) && ['release_id', 'manifest_digest', 'artifact_digest'].includes(kind) && (kind === 'release_id' ? id(value) : rawHash(value)), 'trust_revocation_lookup');
      return transact(() => { state(domain); return one('SELECT * FROM trust_revocation_record WHERE trust_domain_id=? AND kind=? AND value=?', domain, kind, value) ?? null; });
    },
    async inspectDownloadedDocument(downloadId, kind) {
      need(id(downloadId) && ['release', 'revocations'].includes(kind), 'trust_document_request');
      const ticket = {}; documents.add(ticket);
      try {
        const initial = transact(() => {
          const download = one('SELECT a.* FROM trust_download_attempt a JOIN trust_download_receipt r USING(download_id) WHERE a.download_id=?', downloadId);
          need(download && download.package_bytes > 0 && download.package_bytes <= 4194304, 'trust_document_unavailable');
          const prior = one('SELECT * FROM trust_release_document WHERE download_id=? AND kind=? AND decoder_digest=?', downloadId, kind, releaseManifestSelection.contract_digest);
          if (prior) need(prior.decoder_id === releaseManifestSelection.contract_id && prior.package_digest === download.package_digest && hash(prior.body) === prior.package_digest, 'trust_document_integrity');
          return {download, prior};
        });
        let bytes = initial.prior?.body;
        if (!bytes) {
          const handle = await fs.open(path.join(staging, downloadId + '.target'), 'r');
          try {
            const before = await handle.stat(); need(before.isFile() && before.nlink === 1 && before.size === initial.download.package_bytes, 'trust_document_file');
            bytes = Buffer.alloc(before.size); let offset = 0;
            while (offset < bytes.length) {
              transact(() => state(one('SELECT trust_domain_id FROM trust_verification_session WHERE session_id=?', initial.download.session_id).trust_domain_id));
              const result = await handle.read(bytes, offset, Math.min(65536, bytes.length - offset), offset); need(result.bytesRead > 0, 'trust_document_file'); offset += result.bytesRead;
            }
            const after = await handle.stat(); need(after.size === before.size && after.nlink === 1 && hash(bytes) === initial.download.package_digest, 'trust_document_digest');
          } finally { await handle.close(); }
        }
        const document = await (kind === 'release' ? decodeReleaseManifest(bytes) : decodeReleaseRevocations(bytes));
        return transact(() => {
          const prior = one('SELECT * FROM trust_release_document WHERE download_id=? AND kind=? AND decoder_digest=?', downloadId, kind, releaseManifestSelection.contract_digest);
          const documentId = prior?.document_id ?? crypto.randomUUID();
          if (prior) need(prior.package_digest === initial.download.package_digest && hash(prior.body) === prior.package_digest, 'trust_document_integrity');
          else db.prepare('INSERT INTO trust_release_document VALUES (?,?,?,?,?,?,?,?)').run(documentId, downloadId, kind, releaseManifestSelection.contract_id,
            releaseManifestSelection.contract_digest, initial.download.package_bytes, initial.download.package_digest, bytes);
          return {document_id: documentId, download_id: downloadId, kind, package_digest: initial.download.package_digest, decoder_selection: releaseManifestSelection, document};
        });
      } finally { documents.delete(ticket); }
    },
    downloadedArtifact(downloadId) {
      need(typeof downloadId === 'string' && /^[0-9a-f-]{36}$/.test(downloadId), 'trust_download_id');
      return transact(() => {
        const row = one('SELECT a.* FROM trust_download_attempt a JOIN trust_download_receipt r USING(download_id) WHERE a.download_id=?', downloadId);
        need(row, 'trust_download_unavailable');
        const target = JSON.parse(row.target_body), metadata = JSON.parse(row.metadata_body);
        need(digest(target) === row.target_digest && digest(metadata) === row.metadata_digest, 'trust_download_integrity');
        return {download_id: downloadId, session_id: row.session_id, target_path: row.target_path, package_bytes: String(row.package_bytes), package_digest: row.package_digest,
          target, metadata, filename: path.join(staging, downloadId + '.target')};
      });
    }
  });
}
