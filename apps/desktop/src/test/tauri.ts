import { vi } from "vitest";

type Handler = (args: Record<string, unknown>) => unknown;

/** In-memory stand-in for the Tauri shell: commands, engine RPC, and events. */
export const shell = {
  commands: new Map<string, Handler>(),
  methods: new Map<string, Handler>(),
  listeners: new Map<string, Set<(event: { payload: unknown }) => void>>(),
  calls: [] as { method: string; params: Record<string, unknown> }[],
  reset() {
    this.commands.clear();
    this.methods.clear();
    this.listeners.clear();
    this.calls = [];
  },
  emit(name: string, payload: unknown) {
    for (const listener of this.listeners.get(name) ?? []) listener({ payload });
  },
};

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd: string, args: Record<string, unknown> = {}) => {
    if (cmd === "engine_call") {
      const method = args.method as string;
      const params = (args.params as Record<string, unknown>) ?? {};
      shell.calls.push({ method, params });
      const handler = shell.methods.get(method);
      if (!handler) throw { code: -32601, message: `unmocked ${method}`, data: { code: "x" } };
      return handler(params);
    }
    const handler = shell.commands.get(cmd);
    if (!handler) throw { code: -1, message: `unmocked ${cmd}`, data: { code: "x" } };
    return handler(args);
  }),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (name: string, cb: (event: { payload: unknown }) => void) => {
    const set = shell.listeners.get(name) ?? new Set();
    set.add(cb);
    shell.listeners.set(name, set);
    return () => set.delete(cb);
  }),
}));
