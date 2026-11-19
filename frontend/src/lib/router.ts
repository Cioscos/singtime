// Navigazione tramite la parte dopo # dell'indirizzo: funziona senza configurare il server.

export type Route =
  | { name: "library" }
  | { name: "edit"; id: string }
  | { name: "verify"; id: string }
  | { name: "game"; id: string }
  | { name: "result"; id: string }
  | { name: "settings" }
  | { name: "calibration" };

const WITH_ID = new Set(["edit", "verify", "game", "result"]);
const WITHOUT_ID = new Set(["library", "settings", "calibration"]);

export function parseHash(hash: string): Route {
  const [name, rawId] = hash.replace(/^#\/?/, "").split("/");
  if (WITH_ID.has(name) && rawId) {
    return { name, id: decodeURIComponent(rawId) } as Route;
  }
  if (WITHOUT_ID.has(name) && rawId === undefined) {
    return { name } as Route;
  }
  return { name: "library" };
}

export function toHash(route: Route): string {
  return "id" in route ? `#/${route.name}/${encodeURIComponent(route.id)}` : `#/${route.name}`;
}

export function navigate(route: Route): void {
  location.hash = toHash(route);
}
