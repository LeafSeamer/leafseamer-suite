import crypto from 'node:crypto';
import {canonical, digest, requireValue as need} from './import-input.mjs';
import {inspectMetadata} from './tuf-input.mjs';
import {decodeReleaseManifest, decodeReleaseExtensionBinding, releaseManifestSelection} from './sdk/release-manifest.mjs';
const hash = bytes => 'sha256:' + crypto.createHash('sha256').update(bytes).digest('hex');
const exact = (value, keys) => value && Object.keys(value).sort().join(',') === keys.split(',').sort().join(',');

// 发行签名验证的持久结果；安装操作者、目标管理权及运行批准由各自权威另核。
export function releaseAuthorizer({db, one, transact, state, installationIdentity, currentSession}) {
  const reference = row => ({kind:'release_authorization', authority_service_id:installationIdentity.authority_service_id,
    database_instance_id:installationIdentity.database_instance_id, object_id:row.authorization_id, revision:'1', digest:row.body_digest});
  function read(ref) {
    need(exact(ref,'kind,authority_service_id,database_instance_id,object_id,revision,digest') && ref.kind === 'release_authorization' &&
      ref.authority_service_id === installationIdentity.authority_service_id && ref.database_instance_id === installationIdentity.database_instance_id && ref.revision === '1', 'trust_authorization_reference');
    need(typeof ref.object_id === 'string' && /^[0-9a-f-]{36}$/.test(ref.object_id) && typeof ref.digest === 'string' && /^sha256:[0-9a-f]{64}(?![\s\S])/.test(ref.digest),'trust_authorization_reference');
    const row = one('SELECT * FROM trust_release_authorization WHERE authorization_id=?', ref.object_id);
    need(row && row.body_digest === ref.digest && hash(row.body) === row.body_digest, 'trust_authorization_reference');
    return {row, body:JSON.parse(row.body)};
  }
  function notRevoked(domain, manifest, profile, manifestDigest) {
    const denied = (kind,value) => one('SELECT 1 FROM trust_revocation_record WHERE trust_domain_id=? AND kind=? AND value=?',domain,kind,value);
    need(!denied('release_id',manifest.release_id) && !denied('manifest_digest',manifestDigest), 'trust_release_revoked');
    const selected = new Set(profile.artifact_refs);
    for (const artifact of manifest.artifacts) if (selected.has(artifact.artifact_id)) need(!denied('artifact_digest',artifact.sha256), 'trust_release_revoked');
  }
  const latest = (domain, channel, profile) => one(`SELECT * FROM trust_release_approval WHERE trust_domain_id=? AND channel=? AND target_profile_id=?
    ORDER BY length(release_sequence) DESC,release_sequence DESC LIMIT 1`,domain,channel,profile);
  function topTargets(domain, current) {
    const metadata = one(`SELECT m.* FROM trust_metadata_head h JOIN trusted_metadata m USING(metadata_id)
      WHERE h.trust_domain_id=? AND h.role='targets' AND h.epoch=?`,domain,current.metadata_epoch);
    need(metadata && hash(metadata.body) === metadata.digest, 'trust_metadata_integrity');
    return {metadata, targets:inspectMetadata(metadata.body).signed.targets};
  }
  const api={
    historical(ref) { return transact(() => read(ref).body); },
    currentForArtifact(originalRef,expected){
      const original=read(originalRef).body;
      const row=one(`SELECT * FROM trust_release_authorization WHERE
        json_extract(CAST(body AS TEXT),'$.trust_domain_id')=? AND json_extract(CAST(body AS TEXT),'$.channel')=?
        AND json_extract(CAST(body AS TEXT),'$.target_profile_id')=? AND json_extract(CAST(body AS TEXT),'$.deployment_profile_id')=?
        AND json_extract(CAST(body AS TEXT),'$.package_digest')=? AND json_extract(CAST(body AS TEXT),'$.package_bytes')=?
        AND json_extract(CAST(body AS TEXT),'$.expected_manifest_digest')=? ORDER BY rowid DESC LIMIT 1`,
        original.trust_domain_id,original.channel,original.target_profile_id,original.deployment_profile_id,
        expected.package_digest,expected.package_bytes,expected.expected_manifest_digest);
      need(row,'trust_authorization_unavailable');const selected=reference(row);
      return {reference:selected,body:api.assertCurrent(selected,expected)};
    },
    assertCurrent(ref, expected) {
      const {row,body} = read(ref); currentSession(row.session_id,body.trust_domain_id);
      const current = state(body.trust_domain_id);
      need(!current.reset_pending && current.metadata_epoch === body.metadata_epoch && current.digest === body.root_digest, 'trust_authorization_obsolete');
      const {metadata} = topTargets(body.trust_domain_id,current);
      need(metadata.digest === body.targets_digest, 'trust_authorization_obsolete');
      const revocation = one(`SELECT * FROM trust_revocation_snapshot WHERE trust_domain_id=? ORDER BY length(revision) DESC,revision DESC LIMIT 1`,body.trust_domain_id);
      const adoption = one('SELECT * FROM trust_revocation_adoption WHERE adoption_id=?',row.revocation_adoption_id);
      need(revocation && adoption && revocation.snapshot_id === adoption.snapshot_id && adoption.session_id === row.session_id, 'trust_authorization_obsolete');
      need(latest(body.trust_domain_id,body.channel,body.target_profile_id)?.approval_id === row.approval_id, 'trust_release_rollback');
      const document = one('SELECT * FROM trust_release_document WHERE document_id=?',row.release_document_id);
      need(document && hash(document.body) === body.release_manifest_digest, 'trust_document_integrity');
      const manifest = JSON.parse(document.body), profile = manifest.deployment_profiles.find(p=>p.profile_id===body.deployment_profile_id);
      need(profile, 'trust_release_profile'); notRevoked(body.trust_domain_id,manifest,profile,body.release_manifest_digest);
      need(expected.package_digest === body.package_digest && expected.package_bytes === body.package_bytes &&
        expected.expected_manifest_digest === body.expected_manifest_digest, 'trust_authorization_package');
      currentSession(row.session_id,body.trust_domain_id);
      return body;
    },
    async authorize({domain,sessionId,check,getTarget,releaseDocumentId,packageDownloadId}) {
      const source = transact(() => {
        check();
        const document = one(`SELECT d.*,a.session_id,a.target_path FROM trust_release_document d JOIN trust_download_attempt a USING(download_id) WHERE d.document_id=?`,releaseDocumentId);
        const archive = one(`SELECT a.* FROM trust_download_attempt a JOIN trust_download_receipt r USING(download_id) WHERE a.download_id=?`,packageDownloadId);
        need(document && document.kind === 'release' && document.session_id === sessionId && archive && archive.session_id === sessionId &&
          document.decoder_id === releaseManifestSelection.contract_id && document.decoder_digest === releaseManifestSelection.contract_digest &&
          hash(document.body) === document.package_digest, 'trust_release_source');
        return {document,archive};
      });
      const manifest = await decodeReleaseManifest(source.document.body); check();
      const archiveTarget = await getTarget(source.archive.target_path), manifestTarget = await getTarget(source.document.target_path); check();
      const matches = (target,record) => target && target.length === record.package_bytes && 'sha256:'+target.hashes.sha256 === record.package_digest;
      need(matches(archiveTarget,source.archive) && matches(manifestTarget,source.document), 'trust_release_target');
      const binding = await decodeReleaseExtensionBinding(Buffer.from(canonical(archiveTarget.unrecognizedFields.custom?.leafseamer ?? null))); check();
      need(binding.release_manifest.target_path === source.document.target_path && binding.release_manifest.digest === source.document.package_digest &&
        binding.release_manifest.size_bytes === source.document.package_bytes, 'trust_release_binding');
      const artifact = manifest.artifacts.find(a=>a.artifact_id===binding.artifact_id), profile = manifest.deployment_profiles.find(p=>p.profile_id===binding.deployment_profile_id);
      need(artifact?.role === 'extension_archive' && artifact.sha256 === source.archive.package_digest && artifact.size_bytes === source.archive.package_bytes &&
        profile?.artifact_refs.includes(artifact.artifact_id), 'trust_release_artifact');
      return transact(() => {
        check(); const current = state(domain); need(!current.reset_pending,'trust_rotation_pending');
        const {metadata,targets} = topTargets(domain,current);
        need(matches(targets[source.document.target_path],source.document) && matches(targets[source.archive.target_path],source.archive) &&
          digest(targets[source.archive.target_path].custom?.leafseamer ?? null) === digest(binding), 'trust_release_authority');
        const revocation = one(`SELECT * FROM trust_revocation_snapshot WHERE trust_domain_id=? ORDER BY length(revision) DESC,revision DESC LIMIT 1`,domain);
        const adoption = revocation && one(`SELECT a.*,d.target_path,d.package_bytes,d.package_digest FROM trust_revocation_adoption a
          JOIN trust_release_document r ON r.document_id=a.document_id JOIN trust_download_attempt d USING(download_id)
          WHERE a.session_id=? AND a.snapshot_id=? ORDER BY a.adoption_id LIMIT 1`,sessionId,revocation.snapshot_id);
        need(adoption && adoption.metadata_epoch === current.metadata_epoch && matches(targets[adoption.target_path],adoption), 'trust_release_revocations');
        notRevoked(domain,manifest,profile,source.document.package_digest);
        const floor = latest(domain,manifest.channel,manifest.target_profile_id);
        if (floor) {
          need(BigInt(manifest.release_sequence)>=BigInt(floor.release_sequence),'trust_release_rollback');
          if (manifest.release_sequence===floor.release_sequence) need(floor.document_digest===source.document.package_digest,'trust_release_sequence_conflict');
        }
        const identity = one('SELECT * FROM trust_release_approval WHERE trust_domain_id=? AND release_id=?',domain,manifest.release_id);
        if (identity) need(identity.document_digest===source.document.package_digest,'trust_release_identity_conflict');
        check();
        const approvalId = identity?.approval_id ?? crypto.randomUUID();
        if (!identity) db.prepare('INSERT INTO trust_release_approval VALUES (?,?,?,?,?,?,?,?)').run(approvalId,domain,manifest.release_id,
          manifest.release_sequence,manifest.channel,manifest.target_profile_id,releaseDocumentId,source.document.package_digest);
        const prior = one('SELECT * FROM trust_release_authorization WHERE session_id=? AND release_document_id=? AND package_download_id=?',sessionId,releaseDocumentId,packageDownloadId);
        const body = {format:'leafseamer.release-authorization/1',trust_domain_id:domain,approval_id:approvalId,session_id:sessionId,
          release_document_id:releaseDocumentId,package_download_id:packageDownloadId,revocation_adoption_id:prior?.revocation_adoption_id ?? adoption.adoption_id,
          release_id:manifest.release_id,release_sequence:manifest.release_sequence,
          channel:manifest.channel,target_profile_id:manifest.target_profile_id,release_manifest_digest:source.document.package_digest,
          package_digest:source.archive.package_digest,package_bytes:String(source.archive.package_bytes),expected_manifest_digest:binding.extension_manifest_digest,
          artifact_id:binding.artifact_id,deployment_profile_id:binding.deployment_profile_id,target:{os:manifest.target.os,arch:manifest.target.arch,libc:manifest.target.libc},
          root_digest:current.digest,targets_digest:metadata.digest,metadata_epoch:current.metadata_epoch};
        if (prior) {
          const originalAdoption=one('SELECT snapshot_id FROM trust_revocation_adoption WHERE adoption_id=?',prior.revocation_adoption_id);
          need(prior.body_digest===digest(body) && originalAdoption?.snapshot_id===adoption.snapshot_id,'trust_authorization_conflict');
          return {reference:reference(prior),body};
        }
        const authorizationId = crypto.randomUUID();
        db.prepare('INSERT INTO trust_release_authorization VALUES (?,?,?,?,?,?,?,?,?)').run(authorizationId,approvalId,sessionId,releaseDocumentId,packageDownloadId,
          adoption.adoption_id,Buffer.from(canonical(body)),digest(body),current.metadata_epoch);
        return {reference:reference({authorization_id:authorizationId,body_digest:digest(body)}),body};
      });
    }
  };return Object.freeze(api);
}
