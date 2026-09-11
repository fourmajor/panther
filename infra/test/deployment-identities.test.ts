import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";
import { loadIdentities, validateIdentities } from "../lib/deployment-identities";

const example = {schemaVersion:1, users:["sample-owner","sample-member"],
  publishers:["sample-owner"], workers:["sample-owner"], migrationAdmins:["sample-owner"]};

test("real-account synthesis requires private identity inputs; only isolated CI gets fictional defaults", () => {
  assert.throws(()=>loadIdentities("123456789012"), /PANTHER_IDENTITIES_FILE/);
  assert.equal(loadIdentities("000000000000").users.length,3);
  assert.throws(()=>loadIdentities("123456789012",__filename), /outside the repository/);
});

test("identity configuration rejects malformed names, duplicate accounts and implicit grants", () => {
  assert.deepEqual(validateIdentities(example),example);
  for (const bad of [null, {}, {...example,schemaVersion:2}, {...example,users:[]},
    {...example,users:["sample-owner","sample-owner"]}, {...example,users:["comma,name"]},
    {...example,publishers:["not-provisioned"]}, {...example,password:"do-not-store"}]) {
    assert.throws(()=>validateIdentities(bad));
  }
});

test("private file loads exact values, refuses broad permissions, and fails closed when missing", () => {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"panther-synthetic-identities-"));
  const file=path.join(dir,"identities.json");
  try {
    fs.writeFileSync(file,JSON.stringify(example),{mode:0o600});
    assert.deepEqual(loadIdentities("123456789012",file),example);
    fs.chmodSync(file,0o644);
    assert.throws(()=>loadIdentities("123456789012",file), /owner-only/);
    assert.throws(()=>loadIdentities("123456789012",path.join(dir,"missing.json")));
  } finally { fs.rmSync(dir,{recursive:true}); }
});
