export function releaseFixture(os = 'windows') {
  const hash = 'sha256:' + '1'.repeat(64), platform = {os, arch: 'x64', libc: os === 'windows' ? null : 'glibc'};
  const names = ['leafseamer','leafseamer-controller','leafseamer-gui','leafseamer-sdk','leafseamer-suite'];
  const a = (artifact_id, role, component = 'leafseamer-suite', abi = {kind: 'none'}) => ({artifact_id, path: artifact_id + '.bin', size_bytes: 1, sha256: hash, role, component, abi, requires: [], dynamic_dependencies: []});
  const artifacts = [a('node','runtime'), a('driver','native_addon','leafseamer-suite',{kind:'node_api',napi_version:8}),
    a('report','report'),a('toolchain','build_metadata'),a('license','license'),a('sbom','sbom'),a('provenance','provenance'),
    a('schema','protocol_schema','leafseamer-sdk'),a('controller','app','leafseamer-controller'),a('seamer','app','leafseamer'),
    a('gui','gui','leafseamer-gui'),a('agent','app')];
  for (const file of artifacts) if (['controller','seamer','agent'].includes(file.artifact_id)) file.requires.push('driver');
  const entry = (entrypoint_id, component_id, artifact_ref, kind = 'service') => ({entrypoint_id, component_id, artifact_ref, kind,
    runtime_ref: kind === 'static_gui' ? null : 'node', requires: [], protocol_refs: [], storage_refs: []});
  const entries = [entry('controller','leafseamer-controller','controller'),entry('seamer','leafseamer','seamer'),entry('gui','leafseamer-gui','gui','static_gui'),entry('agent','leafseamer-suite','agent','tool')];
  const protocols = ['http','human_events','service_events'].map(kind => {
    const left = kind === 'service_events' ? 'seamer' : 'gui';
    entries.find(e=>e.entrypoint_id===left).protocol_refs.push(kind); entries[0].protocol_refs.push(kind);
    return {channel_id: kind, kind, contract_id: 'public.synthetic', contract_digest: hash, schema_artifact_ref: 'schema',
      components: [entries.find(e=>e.entrypoint_id===left).component_id,'leafseamer-controller'], endpoints: [
        {endpoint_id:'client',entrypoint_ref:left,role:'client',peer_endpoint_ref:'server',direction:'bidirectional',contract_id:'public.synthetic',contract_digest:hash},
        {endpoint_id:'server',entrypoint_ref:'controller',role:'server',peer_endpoint_ref:'client',direction:'bidirectional',contract_id:'public.synthetic',contract_digest:hash}
      ]};
  });
  const stores = [
    ['controller','controller_business','controller','leafseamer-controller','business'],
    ['seamer','seamer_business','seamer','leafseamer','business'],
    ['journal','supervisor_journal','supervisor','leafseamer-controller','journal'],
    ['installation','installation','suite_agent','leafseamer-suite','business']
  ].map(([storage_id,store_kind,owner_role,owner_component,connection_profile_ref])=>({storage_id,store_kind,owner_role,owner_component,
    schema_id:storage_id+'.schema',read_schema_revisions:['1'],write_schema_revisions:['1'],engine_ref:'sqlite',connection_profile_ref,migration_refs:[],report_artifact_ref:'report'}));
  entries[0].storage_refs=['controller','journal'];entries[1].storage_refs=['seamer'];entries[3].storage_refs=['installation'];
  const value = {
    manifest_schema:'native-release/0.2.0-draft.1', release_id:'synthetic.release', release_sequence:'9007199254740993', channel:'preview',created_at:'2020-01-01T00:00:00Z',target_profile_id:'synthetic.'+os,
    target:{...platform,tested_environment_ref:'report.bin',required_cpu_features:[]},
    build:{toolchain_manifest_path:'toolchain.bin'},artifacts,
    capabilities:{argon2:{reference_commit:'1'.repeat(40),report_path:'report.bin'},clock:{adapter_abi:'synthetic',backend_profile_id:'synthetic',report_path:'report.bin'}},
    reports:{sbom_path:'sbom.bin',license_bundle_path:'license.bin',acceptance_path:'report.bin',provenance_path:'provenance.bin'},
    reproducibility:{status:'unverified',comparison_target:'unsigned_payload',report_path:null},
    component_bindings:names.map(component_id=>({component_id,version:'0.1.0',source_commit:'1'.repeat(40),source_archive_sha256:hash,lockfile_sha256:hash,
      artifact_refs:artifacts.filter(a=>a.component===component_id).map(a=>a.artifact_id),entrypoints:entries.filter(e=>e.component_id===component_id).map(e=>e.entrypoint_id),
      requires:['leafseamer','leafseamer-controller'].includes(component_id)?['leafseamer-sdk','leafseamer-suite']:component_id==='leafseamer-sdk'?[]:['leafseamer-sdk']})),
    entrypoints:entries,protocol_bindings:protocols,
    runtime_bindings:[{runtime_id:'node',kind:'node',version:'24.22.0',artifact_ref:'node',abi:{node_api_version:8,node_module_abi:137,native_abi_id:null},platform,components:['leafseamer','leafseamer-controller','leafseamer-suite'],host_runtime_ref:null,report_artifact_ref:'report'}],
    storage_engines:[{engine_id:'sqlite',kind:'sqlite',binary_artifact_ref:'driver',driver_artifact_ref:'driver',version:'3.53.4',source_id:'synthetic',compile_options_digest:hash,report_artifact_ref:'report'}],
    connection_profiles:['business','journal'].map(profile_id=>({profile_id,kind:'sqlite',journal_mode:profile_id==='business'?'wal':'delete',synchronous:profile_id==='business'?'FULL':'EXTRA',foreign_keys:true,busy_timeout:0,wal_autocheckpoint:0,recursive_triggers:true,trusted_schema:false,report_artifact_ref:'report'})),
    storage_bindings:stores,migration_bindings:[],container_bindings:[],
    deployment_profiles:[{profile_id:'all',kind:'native',component_refs:names,entrypoint_refs:entries.map(e=>e.entrypoint_id),protocol_refs:protocols.map(p=>p.channel_id),storage_refs:stores.map(s=>s.storage_id),runtime_refs:['node'],container_refs:[],artifact_refs:artifacts.map(a=>a.artifact_id),optional_capabilities:[],host_prerequisites:[],report_refs:['report']}]
  };
  return value;
}
