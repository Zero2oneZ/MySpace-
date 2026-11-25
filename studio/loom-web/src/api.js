// Thin client over the existing Python JSON API. Tenant is carried on every
// request via X-Loom-Tenant (?tenant= in the URL chooses the clone).
const tenant = new URLSearchParams(location.search).get("tenant") || "root";
const H = { "Content-Type": "application/json", "X-Loom-Tenant": tenant };

async function jget(path) {
  const r = await fetch(path, { headers: { "X-Loom-Tenant": tenant } });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}
async function jpost(path, body) {
  const r = await fetch(path, { method: "POST", headers: H, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

export const api = {
  tenant,
  scopes: () => jget("/dapp/api/loom/scopes").then((d) => d.scopes || []),
  scope: (id) => jget(`/dapp/api/loom/scope?id=${encodeURIComponent(id)}`),
  channels: () => jget("/dapp/api/loom/channels").then((d) => d.channels || []),
  messages: (ch) => jget(`/dapp/api/loom/messages?channel=${encodeURIComponent(ch)}`).then((d) => d.messages || []),
  post: (channel, text) => jpost("/dapp/api/loom/post", { channel, text }),
  mint: (intent, label, chain_spec) => jpost("/dapp/api/loom/mint", { intent, label, chain_spec }),
  connect: (service, kind) => jpost("/dapp/api/loom/connect", { service, kind }),
  connections: () => jget("/dapp/api/loom/connections").then((d) => d.connections || []),
  tenants: () => jget("/dapp/api/loom/tenants").then((d) => d.tenants || []),
};
