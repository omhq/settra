import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

import YamlWorker from "@/workers/yaml.worker?worker";

self.MonacoEnvironment = {
  getWorker(_moduleId, label) {
    return label === "yaml" ? new YamlWorker() : new EditorWorker();
  },
};
