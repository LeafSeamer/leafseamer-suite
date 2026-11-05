import fs from 'node:fs';
import {openInstallationStore} from '../../dist/installation-store.mjs';
const [directory, filename, identity] = process.argv.slice(2);
const store = openInstallationStore(directory), fd = fs.openSync(filename, 'r'), key = JSON.parse(identity);
const copy = store.copyImport(key, fd);
process.stdout.write(JSON.stringify(store.queryImport(key)) + '\n');
try { await copy; } finally { fs.closeSync(fd); store.close(); }
