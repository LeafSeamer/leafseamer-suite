// 只运行独立合成内存库；报告真实Node内置SQLite，不冒充所选原生依赖。
const fs = require('node:fs');
const path = require('node:path');
const {DatabaseSync} = require('node:sqlite');
const vectors = JSON.parse(fs.readFileSync(path.join(__dirname, 'fk-seal-vectors.json'), 'utf8'));
const results = [];
let engine;
for (const [shape, ddl] of Object.entries(vectors.schemas)) {
  for (const test of vectors.cases) {
    const db = new DatabaseSync(':memory:');
    try {
      db.exec(ddl);
      engine = db.prepare('SELECT sqlite_version() AS version, sqlite_source_id() AS source').get();
      db.exec('BEGIN');
      if (test.parent) db.exec("INSERT INTO parent VALUES('parent')");
      if (test.child) db.exec("INSERT INTO child VALUES('child','parent')");
      db.exec("INSERT INTO seal(id) VALUES('seal')");
      if (shape === 'split_seal' && test.marker) db.exec("INSERT INTO seal_commit(id) VALUES('seal')");
      if (test.seal) db.exec("UPDATE seal SET sealed=1 WHERE id='seal'");
      const violations = db.prepare('PRAGMA foreign_key_check').all().map(x => ({table:x.table,parent:x.parent,fkid:x.fkid}));
      let committed = true;
      try { db.exec('COMMIT'); }
      catch (error) {
        if (!String(error.message).includes('FOREIGN KEY constraint failed')) throw error;
        committed = false;
        db.exec('ROLLBACK');
      }
      // 原自引用结构不存在独立marker；该用例只对新结构定义期望。
      const expected = shape === 'mutable_self' && test.name === 'missing_marker' ? true : test.expected_commit;
      results.push({shape,case:test.name,committed,expected_commit:expected,conforms:committed===expected,violations});
    } finally { db.close(); }
  }
}
process.stdout.write(JSON.stringify({runtime:process.version,engine,results}));
