#!/bin/sh
set -eu
export XDG_CONFIG_HOME=/tmp/obs-profile
export XDG_RUNTIME_DIR=/tmp/obs-runtime
export DISPLAY=:41
export LIBGL_ALWAYS_SOFTWARE=1
password=$(cat /proc/sys/kernel/random/uuid)
port=4457
transition=${OBS_FIXTURE_TRANSITION:-Cut}
case "$transition" in Cut|Fade) ;; *) exit 2 ;; esac
mkdir -m 700 "$XDG_RUNTIME_DIR"
mkdir -p "$XDG_CONFIG_HOME/obs-studio/plugin_config/obs-websocket" "$XDG_CONFIG_HOME/obs-studio/basic/scenes"
umask 077
cat > "$XDG_CONFIG_HOME/obs-studio/plugin_config/obs-websocket/config.json" <<EOF
{"first_load":false,"server_enabled":true,"server_port":$port,"alerts_enabled":false,"auth_required":true,"server_password":"$password"}
EOF
cat > "$XDG_CONFIG_HOME/obs-studio/global.ini" <<'EOF'
[General]
FirstRun=false
LastVersion=536871936

[Basic]
SceneCollection=LeafSeamer
SceneCollectionFile=LeafSeamer

[BasicWindow]
PreviewEnabled=false
EOF
cp "$XDG_CONFIG_HOME/obs-studio/global.ini" "$XDG_CONFIG_HOME/obs-studio/user.ini"
cat > "$XDG_CONFIG_HOME/obs-studio/basic/scenes/LeafSeamer.json" <<EOF
{
 "name":"LeafSeamer",
 "current_transition":"$transition",
 "current_scene":"Static A",
 "current_program_scene":"Static A",
 "scene_order":[{"name":"Static A"},{"name":"Static B"}],
 "sources":[
  {"id":"scene","versioned_id":"scene","name":"Static A","uuid":"ebc75716-e090-42b1-b9e5-ee8a1dd15879","settings":{"items":[]}},
  {"id":"scene","versioned_id":"scene","name":"Static B","uuid":"c3a343d6-9f64-4862-a151-baf6201a5ae6","settings":{"items":[]}}
 ]
}
EOF
if [ "${OBS_FIXTURE_REGISTER_RESOURCE:-0}" = 1 ]; then
 sed 's/"name":"LeafSeamer"/"name":"Alternate"/' "$XDG_CONFIG_HOME/obs-studio/basic/scenes/LeafSeamer.json" \
  > "$XDG_CONFIG_HOME/obs-studio/basic/scenes/Alternate.json"
fi
Xvfb :41 -screen 0 1280x720x24 -nolisten tcp > /tmp/obs-xvfb.log 2>&1 &
display_pid=$!
obs_pid=
cleanup(){
 if [ -n "$obs_pid" ]; then kill "$obs_pid" 2>/dev/null || :; fi
 kill "$display_pid" 2>/dev/null || :
}
trap cleanup EXIT
i=0
until [ -S /tmp/.X11-unix/X41 ]; do
 i=$((i+1))
 if [ "$i" -eq 30 ]; then cat /tmp/obs-xvfb.log; exit 1; fi
 sleep 0.2
done
obs --multi --disable-shutdown-check --collection LeafSeamer >/tmp/obs-process.log 2>&1 &
obs_pid=$!
i=0
until grep -q 'Server started successfully on port 4457' /tmp/obs-process.log; do
 i=$((i+1))
 if [ "$i" -eq 60 ] || ! kill -0 "$obs_pid" 2>/dev/null; then tail -n 55 /tmp/obs-process.log; exit 1; fi
 sleep 0.5
done
printf '{"port":%s,"password":"%s"}' "$port" "$password" |
 node --disallow-code-generation-from-strings /controller/dist/cli.mjs inspect-obs |
 tee /tmp/obs-discovery-result.json
node --input-type=module - <<'JS'
import assert from 'node:assert/strict';
import fs from 'node:fs';
const result=JSON.parse(fs.readFileSync('/tmp/obs-discovery-result.json','utf8'));
assert.equal(result.event,'obs_discovered');
assert.equal(result.obs_version,'32.0.4');
assert.equal(result.collection_name,'LeafSeamer');
assert.equal(result.rpc_version,1);
assert.equal(result.program_scene_uuid,'ebc75716-e090-42b1-b9e5-ee8a1dd15879');
assert.deepEqual(result.scenes.map(x=>x.display_name).sort(),['Static A','Static B']);
JS
if bash -o pipefail -c 'printf "%s" "{\"port\":4457,\"password\":\"incorrect-synthetic-password\"}" | node /controller/dist/cli.mjs inspect-obs 2>&1 | tee /tmp/obs-denied.json > /dev/null'; then
 exit 1
fi
grep -q '"error":"obs_authentication"' /tmp/obs-denied.json
printf '%s\n' 'OBS 隔离夹具只读发现和错误密码拒绝均通过'
inspect_cut(){
 printf '{"port":%s,"password":"%s"}' "$port" "$password" |
  bash -o pipefail -c 'node --disallow-code-generation-from-strings /controller/dist/cli.mjs inspect-obs-cut 2>&1 | tee /tmp/obs-cut-result.json >/dev/null'
}
if [ "$transition" = Cut ]; then
 if ! inspect_cut; then cat /tmp/obs-cut-result.json; exit 1; fi
 node --input-type=module - <<'JS'
import assert from 'node:assert/strict';
import fs from 'node:fs';
const result=JSON.parse(fs.readFileSync('/tmp/obs-cut-result.json','utf8'));
assert.equal(result.event,'obs_cut_checked');
assert.equal(result.profile,'obs_isolated_empty_cut/1');
assert.equal(result.program_scene_uuid,'ebc75716-e090-42b1-b9e5-ee8a1dd15879');
assert.deepEqual(result.scenes.map(x=>x.obs_scene_uuid).sort(),[
 'c3a343d6-9f64-4862-a151-baf6201a5ae6','ebc75716-e090-42b1-b9e5-ee8a1dd15879'
]);
JS
 printf '%s\n' 'OBS Cut 配置只读检查通过'
 if [ "${OBS_FIXTURE_REGISTER_RESOURCE:-0}" = 1 ]; then
  printf '{"port":%s,"password":"%s","obs_pid":%s}' "$port" "$password" "$obs_pid" |
   node --disallow-code-generation-from-strings "$(dirname "$0")/obs-resource-registration.mjs"
 fi
else
 if inspect_cut; then exit 1; fi
 grep -qx '{"error":"obs_cut_profile_transition"}' /tmp/obs-cut-result.json
 printf '%s\n' 'OBS Fade 配置已拒绝'
fi
