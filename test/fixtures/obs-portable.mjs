import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {once} from 'node:events';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {setTimeout as wait} from 'node:timers/promises';

const collection_name = 'LeafSeamer';
const scenes = [
  ['Static A', 'ebc75716-e090-42b1-b9e5-ee8a1dd15879'],
  ['Static B', 'c3a343d6-9f64-4862-a151-baf6201a5ae6']
];

export async function startPortableObs(t, root, inspect) {
  assert.ok(path.isAbsolute(root));
  const work = path.join(root, 'bin', '64bit');
  const executable = path.join(work, 'obs64.exe');
  assert.ok(fs.statSync(executable).isFile());
  const configRoot = path.join(root, 'config');
  fs.mkdirSync(configRoot);
  const config = path.join(configRoot, 'obs-studio');
  const settings = path.join(config, 'plugin_config', 'obs-websocket');
  const scenePath = path.join(config, 'basic', 'scenes');
  let stop = async () => {};
  t.after(async () => {
    try { await stop(); }
    finally { fs.rmSync(configRoot, {recursive:true, force:true, maxRetries:8, retryDelay:125}); }
  });
  fs.mkdirSync(settings, {recursive:true});
  fs.mkdirSync(scenePath, {recursive:true});
  const socket = net.createServer().listen(0, '127.0.0.1');
  await once(socket, 'listening');
  const {port} = socket.address();
  await new Promise(resolve => socket.close(resolve));
  const password = randomBytes(24).toString('base64url');
  const profile = '[General]\nFirstRun=false\nLastVersion=536871936\n[Basic]\nSceneCollection=LeafSeamer\nSceneCollectionFile=LeafSeamer\n[BasicWindow]\nPreviewEnabled=false\n';
  for (const file of ['global.ini','user.ini']) fs.writeFileSync(path.join(config,file), profile);
  fs.writeFileSync(path.join(scenePath, collection_name+'.json'), JSON.stringify({
    name:collection_name, current_transition:'Cut', current_scene:'Static A', current_program_scene:'Static A',
    scene_order:scenes.map(([name]) => ({name})),
    sources:scenes.map(([name,uuid]) => ({id:'scene',versioned_id:'scene',name,uuid,settings:{items:[]}}))
  }));
  fs.writeFileSync(path.join(settings,'config.json'), JSON.stringify({first_load:false,server_enabled:true,
    server_port:port,alerts_enabled:false,auth_required:true,server_password:password}));
  const obs = spawn(executable, ['--portable','--multi','--disable-updater','--collection',collection_name,
    '--minimize-to-tray','--websocket_ipv4_only'], {cwd:work,stdio:'ignore',windowsHide:true});
  const ended = once(obs,'close');
  stop = async () => { if (obs.exitCode===null && obs.signalCode===null) obs.kill(); await ended; };
  await once(obs,'spawn');
  const until = performance.now()+20000;
  for (;;) {
    assert.equal(obs.exitCode,null,'OBS portable exited during startup');
    try {
      await inspect({port,password});
      await wait(250);
      const discovery = await inspect({port,password});
      assert.equal(discovery.collection_name,collection_name);
      return {port,password,collection_name,scene_uuids:scenes.map(([,uuid]) => uuid).sort(),
        program_scene_uuid:discovery.program_scene_uuid,stop};
    } catch (error) {
      if (performance.now()>=until || !['obs_transport','obs_request','obs_observation_changed','obs_timeout'].includes(error.code)) throw error;
      await wait(250);
    }
  }
}
