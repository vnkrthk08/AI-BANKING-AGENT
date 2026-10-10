/** Hub visibility derived from the server-issued permission list (single source of truth). */
export const HUBS = [
  { key: "executive", path: "/executive", permission: "dashboard:view" },
  { key: "test-console", path: "/test-console", permission: "voice:operate" },
  { key: "calls", path: "/calls", permission: "call:read" },
  { key: "work", path: "/work", permission: "case:read" },
  { key: "campaigns", path: "/campaigns", permission: "campaign:read" },
  { key: "team", path: "/team", permission: "agent:read" },
  { key: "governance", path: "/governance", permission: "system:read" },
] as const;
export type HubKey = (typeof HUBS)[number]["key"];
export function allowedHubs(permissions: string[] | undefined): HubKey[] {
  return HUBS.filter((h) => permissions?.includes(h.permission)).map((h) => h.key);
}
export function homePath(permissions: string[] | undefined): string {
  const order: HubKey[] = ["executive", "work", "governance", "test-console"];
  const allowed = allowedHubs(permissions);
  const key = order.find((k) => allowed.includes(k)) ?? allowed[0];
  return HUBS.find((h) => h.key === key)?.path ?? "/governance";
}
