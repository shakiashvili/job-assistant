// Minimal Node globals for Vitest fixture tests without pulling @types/node into browser builds
declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf-8'): string;
  const fs: { readFileSync: typeof readFileSync };
  export default fs;
}

declare module 'node:path' {
  export function resolve(...paths: string[]): string;
  const path: { resolve: typeof resolve };
  export default path;
}

declare const require: (id: string) => unknown;
declare const __dirname: string;
