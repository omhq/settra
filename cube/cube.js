const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const YAML = require("yaml");
const { FileRepository } = require("@cubejs-backend/server-core");

const modelRoot = path.join(
  __dirname,
  process.env.CUBEJS_SCHEMA_PATH || "model",
);
const modelExtensions = new Set([".js", ".json", ".yaml", ".yml"]);

class RevisionedFileRepository extends FileRepository {
  async dataSchemaFiles(...args) {
    const files = await super.dataSchemaFiles(...args);
    return files.map((file) => {
      if (!/\.ya?ml$/.test(file.fileName)) return file;
      const parsed = YAML.parse(file.content, { version: "1.1", merge: true });
      const revision = crypto
        .createHash("sha256")
        .update(file.content)
        .digest("hex");

      for (const kind of ["cubes", "views"]) {
        const models = parsed?.[kind];
        if (!Array.isArray(models)) continue;
        for (const model of models) {
          if (!isMapping(model)) continue;
          model.meta ??= {};
          if (!isMapping(model.meta)) continue;
          model.meta.settra ??= {};
          if (!isMapping(model.meta.settra)) continue;
          // Identify the authored snapshot read by the compiler; keep disk unchanged.
          model.meta.settra.compiled_model_revision = revision;
        }
      }
      return { ...file, content: YAML.stringify(parsed, { version: "1.1" }) };
    });
  }
}

function isMapping(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function modelFingerprint() {
  const hash = crypto.createHash("sha256");

  function visit(directory) {
    if (!fs.existsSync(directory)) return;

    for (const entry of fs
      .readdirSync(directory, { withFileTypes: true })
      .sort((left, right) => left.name.localeCompare(right.name))) {
      const absolutePath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(absolutePath);
      } else if (
        entry.isFile() &&
        modelExtensions.has(path.extname(entry.name))
      ) {
        hash.update(path.relative(modelRoot, absolutePath));
        hash.update("\0");
        hash.update(fs.readFileSync(absolutePath));
        hash.update("\0");
      }
    }
  }

  visit(modelRoot);
  return hash.digest("hex");
}

module.exports = {
  schemaVersion: modelFingerprint,
  repositoryFactory: () =>
    new RevisionedFileRepository(process.env.CUBEJS_SCHEMA_PATH || "model"),
};
