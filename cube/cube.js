const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const modelRoot = path.join(
  __dirname,
  process.env.CUBEJS_SCHEMA_PATH || "model",
);
const modelExtensions = new Set([".js", ".json", ".yaml", ".yml"]);

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
};
