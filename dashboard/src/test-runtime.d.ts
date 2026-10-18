// The browser TS configuration intentionally excludes the full Node type surface.
// App tests use this native controller so Node Request and AbortSignal agree.
declare module "node:util" {
  export function transferableAbortController(): AbortController;
}
