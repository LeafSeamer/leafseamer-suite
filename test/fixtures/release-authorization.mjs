import crypto from 'node:crypto';
import {repository,rawHash,fixedTime} from './tuf-repository.mjs';
import {releaseFixture} from './release-manifest.mjs';
export function releaseRepository(bytes, extensionDigest, {manifest = releaseFixture(), revocations, repo = repository(), version = 1, online = '1', mutateBinding = () => {}} = {}) {
  const archive = {artifact_id:'extension',path:'extensions/extension.zip',size_bytes:bytes.length,sha256:rawHash(bytes),role:'extension_archive',
    component:'leafseamer-suite',abi:{kind:'none'},requires:[],dynamic_dependencies:[]};
  manifest.artifacts.push(archive); manifest.component_bindings.find(c=>c.component_id==='leafseamer-suite').artifact_refs.push('extension');
  manifest.deployment_profiles[0].artifact_refs.push('extension');
  const manifestBytes = Buffer.from(JSON.stringify(manifest));
  const binding = {format:'leafseamer.release-extension/1',release_manifest:{target_path:'manifest.json',size_bytes:manifestBytes.length,digest:rawHash(manifestBytes)},
    artifact_id:'extension',deployment_profile_id:manifest.deployment_profiles[0].profile_id,extension_manifest_digest:extensionDigest};
  mutateBinding(binding);
  const revoked = revocations ?? {format:'release-revocations/1',revision:'1',revoked_release_ids:[],revoked_manifest_digests:[],revoked_artifact_digests:[]};
  const payloads = new Map([['extension.zip',bytes],['manifest.json',manifestBytes],['revocations.json',Buffer.from(JSON.stringify(revoked))]]);
  const custom = new Map([['extension.zip',{leafseamer:binding}]]);
  const files = repo.current(version,online,['t1','t2'],payloads,custom);
  const fetcher = repo.fetcher(files);
  fetcher.streamTarget = async function* (url) {
    const name = new URL(url).pathname.slice('/targets/'.length), match = [...payloads].find(([path,body])=>name===rawHash(body).slice(7)+'.'+path);
    if (!match) throw new Error('fixture_target_missing');
    for (let offset=0;offset<match[1].length;offset+=65536) yield match[1].subarray(offset,offset+65536);
  };
  return {repo,manifest,binding,payloads,custom,files,fetcher};
}
export function initializeReleaseFixture(store, repo, domain='release.synthetic') {
  const root = repo.root();
  store.trust.initialize(domain,root,{host_installation_id:store.identity.host_installation_id,bootstrap_operation_id:'bootstrap.synthetic',
    channel_kind:'independent_authenticated_channel',initial_root_digest:rawHash(root),verifier_digest:rawHash(Buffer.from('fixture')),approval_reference:'approval.synthetic'});
  store.trust.configureRevocations(domain,{target_path:'revocations.json',approval_reference:'approval.synthetic'});
}
export async function openReleaseFixture(store, release, {domain='release.synthetic',adoptRevocations=true,...transport} = {}) {
  const session = store.trust.openVerification({trust_domain_id:domain,session_id:crypto.randomUUID(),fixed_reference_time:fixedTime,
    context:{anchor_id:'anchor.synthetic',evidence_reference:'evidence.synthetic',profile_id:'profile.synthetic'},
    metadata_base_url:'https://synthetic.invalid/metadata/',target_base_url:'https://synthetic.invalid/targets/',fetcher:release.fetcher,...transport});
  try {
    await session.refresh();
    const revocations = await session.download('revocations.json'), revocationDocument = await store.trust.inspectDownloadedDocument(revocations.download_id,'revocations');
    if(adoptRevocations)await session.adoptRevocations(revocationDocument.document_id);
    const manifest = await session.download('manifest.json'), document = await store.trust.inspectDownloadedDocument(manifest.download_id,'release');
    const archive = await session.download('extension.zip');
    return {session,document,archive,authorize:()=>session.authorizeExtension({release_document_id:document.document_id,package_download_id:archive.download_id})};
  } catch(error) {session.close();throw error;}
}
export async function authorizeFixture(store, bytes, expectedManifestDigest) {
  const release = releaseRepository(bytes,expectedManifestDigest);
  initializeReleaseFixture(store,release.repo);
  const opened = await openReleaseFixture(store,release);
  try {return {...opened,release,result:await opened.authorize(),validationPolicy:validationPolicyFixture(store)};} catch(error) {opened.session.close();throw error;}
}
export function validationPolicyFixture(store){return store.validationPolicies.configure({policy_id:'policy.synthetic',approval_reference:'approval.synthetic'});}
