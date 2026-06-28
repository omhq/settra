import "@/lib/monaco-environment";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import Editor, { loader, type OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api.js";
import { configureMonacoYaml } from "monaco-yaml";

import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution";
import "monaco-editor/esm/vs/editor/contrib/bracketMatching/browser/bracketMatching";
import "monaco-editor/esm/vs/editor/contrib/clipboard/browser/clipboard";
import "monaco-editor/esm/vs/editor/contrib/contextmenu/browser/contextmenu";
import "monaco-editor/esm/vs/editor/contrib/cursorUndo/browser/cursorUndo";
import "monaco-editor/esm/vs/editor/contrib/find/browser/findController";
import "monaco-editor/esm/vs/editor/contrib/folding/browser/folding";
import "monaco-editor/esm/vs/editor/contrib/format/browser/formatActions";
import "monaco-editor/esm/vs/editor/contrib/gotoError/browser/gotoError";
import "monaco-editor/esm/vs/editor/contrib/hover/browser/hoverContribution";
import "monaco-editor/esm/vs/editor/contrib/indentation/browser/indentation";
import "monaco-editor/esm/vs/editor/contrib/linesOperations/browser/linesOperations";
import "monaco-editor/esm/vs/editor/contrib/links/browser/links";
import "monaco-editor/esm/vs/editor/contrib/multicursor/browser/multicursor";
import "monaco-editor/esm/vs/editor/contrib/snippet/browser/snippetController2";
import "monaco-editor/esm/vs/editor/contrib/stickyScroll/browser/stickyScrollContribution";
import "monaco-editor/esm/vs/editor/contrib/suggest/browser/suggestController";
import "monaco-editor/esm/vs/editor/contrib/toggleTabFocusMode/browser/toggleTabFocusMode";
import "monaco-editor/esm/vs/editor/contrib/wordHighlighter/browser/wordHighlighter";
import "monaco-editor/esm/vs/editor/contrib/wordOperations/browser/wordOperations";

loader.config({ monaco });

configureMonacoYaml(monaco, {
  completion: true,
  enableSchemaRequest: false,
  format: {
    enable: true,
    printWidth: 100,
    proseWrap: "preserve",
  },
  hover: true,
  indentation: "  ",
  validate: true,
  yamlVersion: "1.2",
});

const YAML_EDITOR_OPTIONS: monaco.editor.IStandaloneEditorConstructionOptions =
  {
    accessibilitySupport: "auto",
    ariaLabel: "Cube YAML model",
    automaticLayout: true,
    bracketPairColorization: { enabled: true },
    detectIndentation: false,
    folding: true,
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 13,
    formatOnPaste: false,
    formatOnType: false,
    guides: { bracketPairs: true, indentation: true },
    insertSpaces: true,
    lineHeight: 20,
    lineNumbersMinChars: 3,
    minimap: { enabled: false },
    overviewRulerBorder: false,
    padding: { bottom: 12, top: 12 },
    renderValidationDecorations: "on",
    scrollBeyondLastLine: false,
    smoothScrolling: true,
    stickyScroll: { enabled: true },
    tabSize: 2,
    wordWrap: "on",
  };

export interface YamlEditorHandle {
  focus: () => void;
  format: () => Promise<boolean>;
}

interface YamlEditorProps {
  path: string;
  value: string;
  onChange: (value: string) => void;
}

export const YamlEditor = forwardRef<YamlEditorHandle, YamlEditorProps>(
  function YamlEditor({ path, value, onChange }, ref) {
    const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
    const isDark = useDarkMode();

    useImperativeHandle(
      ref,
      () => ({
        focus() {
          editorRef.current?.focus();
        },
        async format() {
          const editor = editorRef.current;
          const action = editor?.getAction("editor.action.formatDocument");

          if (!editor || !action) return false;

          await action.run();
          editor.focus();
          return true;
        },
      }),
      [],
    );

    const handleMount: OnMount = (editor) => {
      editorRef.current = editor;
    };

    useEffect(
      () => () => {
        editorRef.current = null;
      },
      [],
    );

    return (
      <Editor
        height="100%"
        language="yaml"
        path={modelPath(path)}
        value={value}
        theme={isDark ? "vs-dark" : "light"}
        loading={
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Loading YAML editor
          </div>
        }
        options={YAML_EDITOR_OPTIONS}
        saveViewState
        onChange={(nextValue) => onChange(nextValue ?? "")}
        onMount={handleMount}
      />
    );
  },
);

function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );

  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => {
      setIsDark(root.classList.contains("dark"));
    });

    observer.observe(root, { attributeFilter: ["class"], attributes: true });
    return () => observer.disconnect();
  }, []);

  return isDark;
}

function modelPath(path: string): string {
  return `file:///cube-model/${path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/")}`;
}
