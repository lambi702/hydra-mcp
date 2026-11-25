import { DragEvent, FormEvent, useMemo, useState } from "react";
import { Account, api, Client, ClientKey, Grant, GrantMode, Upstream } from "../api";
import { Avatar } from "../components/Avatar";
import { ErrorBanner } from "../components/ErrorBanner";
import { goTo } from "../nav";
import { useLoad } from "../useLoad";

const DRAG_TYPE = "application/x-hydra-account";

interface Drag {
  accountId: string;
  from: { clientId: string; mode: GrantMode } | null; // null: from the accounts palette
}

function slug(name: string): string {
  return name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32) || "client";
}

/**
 * Who may use what. Each client is a bubble split in two: accounts dropped on the left are
 * read only (only tools the server marks read-only), on the right read + write. Changes save
 * immediately; the proxy re-checks them on every tool call.
 */
export function Clients() {
  const clients = useLoad(api.clients);
  const accounts = useLoad(api.accounts);
  const upstreams = useLoad(api.upstreams);
  const tokens = useLoad(api.accountsStatus);
  const keys = useLoad(api.clientsWithKey);
  const logins = useLoad(api.appLogins);
  const loginsOf = (clientId: string) => (logins.data ?? []).filter((l) => l.client_id === clientId);

  async function signOut(id: string, name: string) {
    if (!window.confirm(`Sign ${name} out? It must log in again to use hydra-mcp.`)) return;
    try {
      await api.deleteAppLogin(id);
      await logins.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [setup, setSetup] = useState<{ client: Client; key: ClientKey | null } | null>(null);
  const [creating, setCreating] = useState(false);

  const upstreamOf = useMemo(() => {
    const byId = new Map((upstreams.data ?? []).map((u) => [u.id, u]));
    return (a: Account) => byId.get(a.upstream_id);
  }, [upstreams.data]);
  const accountById = useMemo(() => new Map((accounts.data ?? []).map((a) => [a.id, a])), [accounts.data]);

  // Palette: connected accounts first, grouped by connector.
  const palette = useMemo(() => {
    const groups = new Map<string, { id: string; upstream: Upstream | undefined; accounts: Account[] }>();
    for (const a of accounts.data ?? []) {
      const g = groups.get(a.upstream_id) ?? { id: a.upstream_id, upstream: upstreamOf(a), accounts: [] };
      g.accounts.push(a);
      groups.set(a.upstream_id, g);
    }
    return [...groups.values()].sort((x, y) => (x.upstream?.name ?? x.id).localeCompare(y.upstream?.name ?? y.id));
  }, [accounts.data, upstreamOf]);

  async function save(next: Client, note: string) {
    // Optimistic: show the change at once; the reload below brings back the stored truth.
    clients.setData((clients.data ?? []).map((c) => (c.id === next.id ? next : c)));
    try {
      await api.putClient(next);
      setSaved(note);
      window.setTimeout(() => setSaved(null), 1800);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    await clients.reload();
  }

  function grant(client: Client, accountId: string, mode: GrantMode) {
    const existing = client.grants.find((g) => g.account_id === accountId);
    if (existing?.mode === mode) return;
    const grants: Grant[] = [
      ...client.grants.filter((g) => g.account_id !== accountId),
      { account_id: accountId, tools: existing?.tools ?? "*", mode },
    ];
    const a = accountById.get(accountId);
    void save({ ...client, grants }, `${client.name}: ${a?.alias ?? accountId} → ${mode === "read" ? "read only" : "read + write"}`);
  }

  function revoke(client: Client, accountId: string) {
    const a = accountById.get(accountId);
    void save({ ...client, grants: client.grants.filter((g) => g.account_id !== accountId) }, `${client.name}: ${a?.alias ?? accountId} removed`);
  }

  function setPattern(client: Client, g: Grant) {
    const tools = window.prompt(
      "Only tools matching this pattern (e.g. search_* or get*). * means every tool.",
      g.tools,
    );
    if (tools === null || !tools.trim()) return;
    void save(
      { ...client, grants: client.grants.map((x) => (x.account_id === g.account_id ? { ...x, tools: tools.trim() } : x)) },
      `${client.name}: tools limited to ${tools.trim()}`,
    );
  }

  async function create(name: string) {
    const taken = new Set((clients.data ?? []).map((c) => c.id));
    let id = slug(name);
    for (let i = 2; taken.has(id); i++) id = `${slug(name)}-${i}`;
    try {
      await api.putClient({ id, name, grants: [] });
      setCreating(false);
      await clients.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function remove(c: Client) {
    if (!window.confirm(`Delete "${c.name}"? It loses access to hydra-mcp at once.`)) return;
    await api.deleteClient(c.id).catch((err: Error) => setError(err.message));
    if (setup?.client.id === c.id) setSetup(null);
    await Promise.all([clients.reload(), keys.reload()]);
  }

  async function rename(c: Client) {
    const name = window.prompt("Client name", c.name);
    if (name && name.trim() && name.trim() !== c.name) await save({ ...c, name: name.trim() }, "Renamed");
  }

  async function showSetup(c: Client) {
    try {
      setSetup({ client: c, key: await api.setupInfo() });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function newKey(c: Client) {
    if (
      keys.data?.includes(c.id) &&
      !window.confirm(
        `Replace the key of "${c.name}"? Every app using the current key (Claude Code, Cursor, Claude Desktop…) stops working until you paste the new one. To see the setup without changing the key, use "Setup".`,
      )
    )
      return;
    try {
      setSetup({ client: c, key: await api.createClientKey(c.id) });
      await keys.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h2>Clients</h2>
          <p className="muted">
            One client per AI app. Drag an account into it (left: read only, right: read + write), then click{" "}
            <strong>Get setup</strong> to install it.
          </p>
        </div>
        <button className="primary" onClick={() => setCreating(true)}>
          + New client
        </button>
      </div>
      {error && <ErrorBanner text={error} onClose={() => setError(null)} />}
      {saved && <div className="toast">✓ {saved}</div>}

      <div className="clients-layout">
        <aside className="palette card">
          <h3>Your accounts</h3>
          {(accounts.loading || upstreams.loading) && <p className="muted small">Loading…</p>}
          {!accounts.loading && palette.length === 0 && (
            <p className="muted small">
              No accounts yet. <button className="linkish" onClick={() => goTo("connections")}>Connect one in Connections</button>{" "}
              first, then drag it into a client.
            </p>
          )}
          {palette.map((g) => (
            <div key={g.id} className="palette-group">
              <div className="palette-head">
                <Avatar name={g.upstream?.name ?? g.id} size={20} />
                <span>{g.upstream?.name ?? g.id}</span>
              </div>
              {g.accounts.map((a) => (
                <AccountChip
                  key={a.id}
                  account={a}
                  upstream={g.upstream}
                  dim={!tokens.data?.[a.id]}
                  drag={{ accountId: a.id, from: null }}
                />
              ))}
            </div>
          ))}
        </aside>

        <div className="client-list">
          {creating && <NewClient onCreate={(n) => void create(n)} onCancel={() => setCreating(false)} />}
          {clients.data?.length === 0 && !creating && (
            <div className="card empty">
              <p>No clients yet. A client is one AI app (Claude Code, Cursor, VS Code…) with its own key.</p>
              <button className="primary" onClick={() => setCreating(true)}>
                Create your first client
              </button>
            </div>
          )}
          {clients.data?.map((c) => (
            <article key={c.id} className="card client">
              <header className="client-head">
                <div>
                  <h3>{c.name}</h3>
                  {(keys.data?.includes(c.id) || loginsOf(c.id).length === 0) && (
                    <span className={`pill ${keys.data?.includes(c.id) ? "pill-ok" : "pill-warn"}`}>
                      {keys.data?.includes(c.id) ? "key set" : "no key yet"}
                    </span>
                  )}
                  {loginsOf(c.id).map((l) => (
                    <span key={l.id} className="pill pill-ok" title={`via ${l.redirect_uris[0] ?? "OAuth"}`}>
                      {l.app_name} signed in
                      <button className="chip-x" aria-label={`Sign ${l.app_name} out`} onClick={() => void signOut(l.id, l.app_name)}>
                        ×
                      </button>
                    </span>
                  ))}
                </div>
                <div className="actions">
                  {keys.data?.includes(c.id) || loginsOf(c.id).length > 0 ? (
                    <>
                      <button className="primary" onClick={() => void showSetup(c)}>
                        Setup
                      </button>
                      <button onClick={() => void newKey(c)}>New key</button>
                    </>
                  ) : (
                    <button className="primary" onClick={() => void newKey(c)}>
                      Get setup
                    </button>
                  )}
                  <button onClick={() => void rename(c)}>Rename</button>
                  <button className="danger" onClick={() => void remove(c)}>
                    Delete
                  </button>
                </div>
              </header>
              <div className="bubble">
                {(["read", "write"] as GrantMode[]).map((mode) => (
                  <Zone
                    key={mode}
                    mode={mode}
                    client={c}
                    accounts={accounts.data ?? []}
                    upstreamOf={upstreamOf}
                    tokens={tokens.data ?? {}}
                    onDrop={(d) => grant(c, d.accountId, mode)}
                    onAdd={(accountId) => grant(c, accountId, mode)}
                    onRemove={(accountId) => revoke(c, accountId)}
                    onPattern={(g) => setPattern(c, g)}
                  />
                ))}
              </div>
              {setup?.client.id === c.id && setup.key && (
                <KeyCard client={c} created={setup.key} onClose={() => setSetup(null)} />
              )}
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function AccountChip({
  account,
  upstream,
  dim,
  drag,
  grant,
  onRemove,
  onPattern,
}: {
  account: Account;
  upstream?: Upstream;
  dim?: boolean;
  drag: Drag;
  grant?: Grant;
  onRemove?: () => void;
  onPattern?: () => void;
}) {
  function onDragStart(e: DragEvent) {
    e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(drag));
    e.dataTransfer.effectAllowed = "move";
  }
  return (
    <div
      className={`chip${dim ? " dim" : ""}`}
      draggable
      onDragStart={onDragStart}
      title={`${upstream?.name ?? ""} · ${account.alias}${account.identity ? ` (${account.identity})` : ""}${dim ? " — not connected" : ""}`}
    >
      <Avatar name={upstream?.name ?? "?"} size={20} />
      <span className="chip-text">
        <strong>{account.alias}</strong>
        {account.identity && <span className="muted small">{account.identity}</span>}
      </span>
      {grant && grant.tools !== "*" && (
        <button className="chip-badge" onClick={onPattern} title="Tool filter">
          {grant.tools}
        </button>
      )}
      {onPattern && grant?.tools === "*" && (
        <button className="chip-x" onClick={onPattern} title="Limit to some tools" aria-label="Limit tools">
          ⋯
        </button>
      )}
      {onRemove && (
        <button className="chip-x" onClick={onRemove} title="Remove access" aria-label="Remove access">
          ×
        </button>
      )}
    </div>
  );
}

function Zone({
  mode,
  client,
  accounts,
  upstreamOf,
  tokens,
  onDrop,
  onAdd,
  onRemove,
  onPattern,
}: {
  mode: GrantMode;
  client: Client;
  accounts: Account[];
  upstreamOf: (a: Account) => Upstream | undefined;
  tokens: Record<string, unknown>;
  onDrop: (d: Drag) => void;
  onAdd: (accountId: string) => void;
  onRemove: (accountId: string) => void;
  onPattern: (g: Grant) => void;
}) {
  const [over, setOver] = useState(false);
  const grants = client.grants.filter((g) => g.mode === mode);
  const granted = new Set(client.grants.filter((g) => g.mode === mode).map((g) => g.account_id));
  const addable = accounts.filter((a) => !granted.has(a.id));

  return (
    <div
      className={`zone zone-${mode}${over ? " over" : ""}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(DRAG_TYPE)) {
          e.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const raw = e.dataTransfer.getData(DRAG_TYPE);
        if (raw) onDrop(JSON.parse(raw) as Drag);
      }}
    >
      <div className="zone-head">
        <span className="zone-title">{mode === "read" ? "👁 Read only" : "✎ Read + write"}</span>
        {addable.length > 0 && (
          <select
            aria-label={`Add an account as ${mode}`}
            value=""
            onChange={(e) => e.target.value && onAdd(e.target.value)}
          >
            <option value="">+ add</option>
            {addable.map((a) => (
              <option key={a.id} value={a.id}>
                {upstreamOf(a)?.name} · {a.alias}
              </option>
            ))}
          </select>
        )}
      </div>
      {grants.length === 0 && <p className="zone-empty">Drop accounts here</p>}
      {grants.map((g) => {
        const a = accounts.find((x) => x.id === g.account_id);
        if (!a) return null;
        return (
          <AccountChip
            key={g.account_id}
            account={a}
            upstream={upstreamOf(a)}
            dim={!tokens[a.id]}
            grant={g}
            drag={{ accountId: a.id, from: { clientId: client.id, mode } }}
            onRemove={() => onRemove(a.id)}
            onPattern={() => onPattern(g)}
          />
        );
      })}
    </div>
  );
}

function NewClient({ onCreate, onCancel }: { onCreate: (name: string) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const presets = ["Claude Code", "Cursor", "VS Code", "Claude Desktop"];
  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) onCreate(name.trim());
  }
  return (
    <form className="card highlight" onSubmit={submit}>
      <h3>New client</h3>
      <div className="presets">
        {presets.map((p) => (
          <button type="button" key={p} className={name === p ? "selected" : ""} onClick={() => setName(p)}>
            {p}
          </button>
        ))}
      </div>
      <label>
        Name
        <input autoFocus required placeholder="e.g. Claude Code on my laptop" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="actions">
        <button type="submit" className="primary">
          Create
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Shown once, right after creation: only the key's hash is stored on the proxy. */
function KeyCard({ client, created, onClose }: { client: Client; created: ClientKey; onClose: () => void }) {
  // Without a fresh key (Setup on a client that already has one), snippets show a placeholder:
  // the proxy only keeps the key's hash, so it cannot show the current key again.
  const key = created.key ?? "hmcp_PASTE_THIS_CLIENTS_KEY";
  const auth = `Bearer ${key}`;
  const claude = `claude mcp add --scope user --transport http hydra ${created.endpoint} --header "Authorization: ${auth}"`;
  const cursor = JSON.stringify({ mcpServers: { hydra: { url: created.endpoint, headers: { Authorization: auth } } } }, null, 2);
  const vscode = JSON.stringify({ servers: { hydra: { type: "http", url: created.endpoint, headers: { Authorization: auth } } } }, null, 2);
  const desktop = JSON.stringify(
    {
      mcpServers: {
        hydra: {
          command: created.bridge_command ?? "hydra-mcp",
          args: created.bridge_args ?? ["bridge"],
          env: { HYDRA_MCP_KEY: key, HYDRA_MCP_URL: created.endpoint },
        },
      },
    },
    null,
    2,
  );
  const lower = client.name.toLowerCase();
  const base = ["claude", "desktop", "web", "vscode", "cursor"];
  const first = lower.includes("cursor")
    ? "cursor"
    : lower.includes("vs")
      ? "vscode"
      : lower.includes("desktop")
        ? "desktop"
        : lower.includes("claude.ai") || lower.includes("web")
          ? "web"
          : "claude";
  const order = [first, ...base.filter((k) => k !== first)];
  const snippets: Record<string, { label: string; where: string; text: string }> = {
    claude: {
      label: "Claude Code",
      where: "Run this in a terminal. --scope user makes it available in every folder.",
      text: claude,
    },
    vscode: {
      label: "VS Code",
      where: "Paste into .vscode/mcp.json (this project) or run 'MCP: Open User Configuration' (everywhere).",
      text: vscode,
    },
    cursor: {
      label: "Cursor",
      where: "Paste into ~/.cursor/mcp.json (everywhere) or .cursor/mcp.json (this project), then enable 'hydra' in Settings, MCP.",
      text: cursor,
    },
    desktop: {
      label: "Claude Desktop",
      where:
        "Claude Desktop, Settings, Developer, Edit Config: merge this into claude_desktop_config.json, save, then quit and reopen Claude Desktop. It runs locally, no tunnel needed; keep hydra-mcp running.",
      text: desktop,
    },
    web: {
      label: "claude.ai",
      where: created.external_endpoint
        ? "claude.ai, Settings, Connectors, Add custom connector: paste this URL, leave the OAuth fields empty, then Connect. On hydra-mcp's page, pick this client and type your admin token. No key needed."
        : "claude.ai connects from Anthropic's servers, so it needs hydra-mcp on a public HTTPS URL (a tunnel) and HYDRA_MCP_EXTERNAL_URL set to it. See docs/clients/claude-ai.md, then come back here.",
      text: created.external_endpoint ?? "HYDRA_MCP_EXTERNAL_URL=https://<your tunnel host>",
    },
    other: {
      label: "Other app",
      where: "Any MCP client that supports Streamable HTTP with a custom header.",
      text: `URL: ${created.endpoint}\nHeader: Authorization: ${auth}`,
    },
  };
  const [shown, setShown] = useState(order[0]);
  const current = snippets[shown];
  return (
    <div className="setup">
      {created.key ? (
        <p className="warn-text">Copy it now: the key is not stored and will not be shown again.</p>
      ) : (
        <p className="muted small">
          Replace <code>hmcp_PASTE_THIS_CLIENTS_KEY</code> with this client's key (the one you copied when you created it).
          Lost it? <strong>New key</strong> makes a new one, and the apps using the old one must get the new one.
        </p>
      )}
      <div className="seg" role="tablist">
        {[...order, "other"].map((k) => (
          <button key={k} role="tab" aria-selected={k === shown} className={k === shown ? "active" : ""} onClick={() => setShown(k)}>
            {snippets[k].label}
          </button>
        ))}
      </div>
      <Snippet key={shown} label={current.where} text={current.text} />
      <p className="muted small">
        Then ask your AI something like "list my Jira issues": it picks the account by its friendly name.
      </p>
      <button onClick={onClose}>Done</button>
    </div>
  );
}

function Snippet({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="snippet">
      <div className="snippet-head">
        <strong>{label}</strong>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(text);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copied ✓" : "Copy"}
        </button>
      </div>
      <pre>{text}</pre>
    </div>
  );
}
