import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";

import YamlWorker from "@/workers/yaml.worker?worker";

self.MonacoEnvironment = {
  getWorker(_moduleId, label) {
    if (label === "yaml") return new YamlWorker();
    if (label === "json") return new JsonWorker();
    return new EditorWorker();
  },
};
