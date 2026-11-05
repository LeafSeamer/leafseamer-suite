import fs from 'node:fs';
import path from 'node:path';
import {execFileSync, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const checkout = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('Provide the fixed upstream checkout with its locked test dependencies installed and built');
const lock = JSON.parse(fs.readFileSync(path.join(root, 'tuf-inputs.json'), 'utf8'));
const git = args => execFileSync('git', ['-C', checkout, ...args], {encoding: 'utf8', windowsHide: true}).trim();
if (git(['rev-parse', 'HEAD']) !== lock.upstream.commit) throw new Error('tuf_test_commit');
git(['diff', '--exit-code', 'HEAD']);
const tests = git(['ls-files', 'packages/client/tests']).split('\n').filter(name => name.endsWith('.test.ts')).map(name => path.join(checkout, name));
if (!tests.length) throw new Error('tuf_test_inputs');
const config = {
  rootDir: checkout,
  moduleNameMapper: Object.fromEntries([
    ['^\\.\\./src$', path.join(root, 'dist/vendor/tuf-js/dist/index.js')],
    ['^\\.\\./src/(.*)$', path.join(root, 'dist/vendor/tuf-js/dist/$1.js')],
    ['^\\.\\./\\.\\./src/(.*)$', path.join(root, 'dist/vendor/tuf-js/dist/$1.js')]
  ]),
  transform: {'^.+\\.tsx?$': [path.join(checkout, 'node_modules/ts-jest'), {tsconfig: path.join(checkout, 'packages/client/tsconfig.json')}]},
  moduleDirectories: ['node_modules', path.join(checkout, 'node_modules')]
};
const result = spawnSync(process.execPath, [path.join(checkout, 'node_modules/jest/bin/jest.js'), '--config', JSON.stringify(config), '--runInBand', '--runTestsByPath', ...tests],
  {cwd: checkout, windowsHide: true, stdio: 'inherit'});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
