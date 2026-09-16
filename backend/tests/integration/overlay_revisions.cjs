// Exercise the configured repository without touching runtime models or data.
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { compile } = require("@cubejs-backend/schema-compiler");

const original = [
  "# Keep this authored comment and file formatting exactly.",
  "cubes:",
  "  - name: RevisionFixture",
  '    sql_table: \'"fixture"."rows"\'',
  "    meta: &shared_meta",
  "      settra: &shared_settra",
  "        compiled_model_revision: user_supplied_value",
  "        validation_token: validation_fixture",
  "        connection_id: 1",
  "    dimensions:",
  "      - name: id",
  "        sql: '\"id\"'",
  "        type: string",
  "        primary_key: true",
  "views:",
  "  - name: RevisionView",
  "    meta:",
  "      <<: *shared_meta",
  "      settra:",
  "        <<: *shared_settra",
  "        extra_evidence: preserved",
  "    cubes:",
  "      - join_path: RevisionFixture",
  "        includes: [id]",
  "",
].join("\n");

function revision(content) {
  return crypto.createHash("sha256").update(content).digest("hex");
}

async function main() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "settra-revisions-"));
  const previousCwd = process.cwd();
  const previousSchemaPath = process.env.CUBEJS_SCHEMA_PATH;
  try {
    process.chdir(root);
    process.env.CUBEJS_SCHEMA_PATH = "model";
    fs.mkdirSync("model");
    const file = "model/fixture.yml";
    fs.writeFileSync(file, original);
    const config = require("/cube/conf/cube.js");

    async function metadata() {
      const compilers = await compile(config.repositoryFactory(), {
        standalone: true,
      });
      return compilers.metaTransformer.cubes.map((cube) => cube.config);
    }
    const first = await metadata();
    for (const model of first) {
      assert.equal(
        model.meta.settra.compiled_model_revision,
        revision(original),
      );
    }
    assert.equal(first.length, 2);
    assert.equal(first[0].meta.settra.validation_token, "validation_fixture");
    assert.equal(first[1].meta.settra.connection_id, 1);
    assert.equal(first[1].meta.settra.extra_evidence, "preserved");
    assert.equal(fs.readFileSync(file, "utf8"), original);

    // The public names are unchanged; SQL changes must change the evidence.
    const updated = original.replace("sql: '\"id\"'", "sql: '\"renamed_id\"'");
    fs.writeFileSync(file, updated);
    const second = await metadata();
    assert.deepEqual(
      second.map((cube) => cube.name),
      first.map((cube) => cube.name),
    );
    for (const model of second) {
      assert.equal(
        model.meta.settra.compiled_model_revision,
        revision(updated),
      );
      assert.notEqual(
        model.meta.settra.compiled_model_revision,
        revision(original),
      );
    }
    assert.equal(fs.readFileSync(file, "utf8"), updated);

    fs.writeFileSync(file, original);
    const restored = await metadata();
    for (const model of restored) {
      assert.equal(
        model.meta.settra.compiled_model_revision,
        revision(original),
      );
    }
    assert.equal(fs.readFileSync(file, "utf8"), original);
    console.log(
      "Cube identifies exact compiled YAML revisions for cubes and views without altering authored files.",
    );
  } finally {
    process.chdir(previousCwd);
    if (previousSchemaPath === undefined) delete process.env.CUBEJS_SCHEMA_PATH;
    else process.env.CUBEJS_SCHEMA_PATH = previousSchemaPath;
    fs.rmSync(root, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
