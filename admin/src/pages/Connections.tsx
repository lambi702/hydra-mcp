import { FormEvent, useEffect, useMemo, useState } from "react";
import { Account, api, ApiError, Connector, SetupGuide, TokenStatus, Upstream } from "../api";
import { Avatar } from "../components/Avatar";
import { ConnectorGuide, TokenForm } from "../components/ConnectorGuide";
import { ErrorBanner } from "../components/ErrorBanner";
import { SetupWizard } from "../components/SetupWizard";
import { StdioForm } from "../components/StdioForm";
import { useLoad } from "../useLoad";

type ConnectBody = Parameters<typeof api.connect>[0];

/**
 * The main page: add a connector, log in at the provider, name the account.
 *
 * Nothing is listed until a login succeeded: the account is created by the OAuth callback,
 * which comes back here with ?connected=<id>&new=1 so the new account can be named.
 */
export function Connections() {
  const upstreams = useLoad(api.upstreams);
  const accounts = useLoad(api.accounts);
  const tokens = useLoad(api.accountsStatus);
  const catalog = useLoad(api.catalog);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [wizard, setWizard] = useState<{ upstreamId: string; guide: SetupGuide } | null>(null);
  const [naming, setNaming] = useState<{ id: string; isNew: boolean } | null>(null);
  const [picking, setPicking] = useState(false);
  // The guide of one connector: before a first connection ("new"), or later from its card.
  const [guide, setGuide] = useState<{ connector: Connector; token?: boolean } | null>(null);
  const [tokenFor, setTokenFor] = useState<Account | null>(null);
  // Local (stdio) servers: a new server, another account of one, or new secrets for an account.
  const [local, setLocal] = useState<{ upstream?: Upstream; account?: Account } | null>(null);

  async function localDone(accountId: string, created: boolean) {
    setLocal(null);
    await Promise.all([upstreams.reload(), accounts.reload(), tokens.reload()]);
    if (created) setNaming({ id: accountId, isNew: true });
  }

  const clients = useLoad(api.clients);
  const usedBy = (accountId: string) =>
    (clients.data ?? []).flatMap((c) =>
      c.grants.filter((g) => g.account_id === accountId).map((g) => ({ name: c.name, mode: g.mode })),
    );

  const connectorFor = (upstreamId: string) =>
    catalog.data?.connectors.find((c) => c.installed_as === upstreamId);

  async function connectWithToken(body: { connector_id?: string; upstream_id?: string; account_id?: string }, token: string) {
    const r = await api.connectToken({ ...body, token });
    setGuide(null);
    setTokenFor(null);
    await Promise.all([upstreams.reload(), accounts.reload(), tokens.reload(), catalog.reload()]);
    setNaming({ id: r.account.id, isNew: r.created });
  }

  // Accounts connected before the proxy learned to ask "which site is this?": ask once now.
  const [probed, setProbed] = useState(false);
  useEffect(() => {
    if (probed || !accounts.data || !tokens.data) return;
    setProbed(true);
    const unknown = accounts.data.filter((a) => !a.identity && tokens.data?.[a.id]);
    if (unknown.length === 0) return;
    void Promise.allSettled(unknown.map((a) => api.refreshIdentity(a.id))).then((rs) => {
      if (rs.some((r) => r.status === "fulfilled" && r.value.changed)) void accounts.reload();
    });
  }, [accounts.data, tokens.data, probed, accounts]);

  // Back from the provider's login page.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const id = q.get("connected");
    if (id) {
      setNaming({ id, isNew: q.get("new") === "1" });
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  const groups = useMemo(() => {
    const byUpstream = new Map<string, Account[]>();
    for (const a of accounts.data ?? []) {
      byUpstream.set(a.upstream_id, [...(byUpstream.get(a.upstream_id) ?? []), a]);
    }
    // Servers without accounts are plumbing (they keep the proxy's OAuth registration): hidden.
    return (upstreams.data ?? [])
      .filter((u) => byUpstream.has(u.id))
      .map((u) => ({ upstream: u, accounts: byUpstream.get(u.id)! }));
  }, [upstreams.data, accounts.data]);

  async function startConnect(body: ConnectBody, label: string) {
    setError(null);
    setBusy(label);
    try {
      const { authorize_url } = await api.connect(body);
      window.location.href = authorize_url; // same tab: the provider sends us back here
    } catch (err) {
      setBusy(null);
      if (err instanceof ApiError && err.status === 409 && err.data.guide) {
        setWizard({ upstreamId: String(err.data.upstream_id), guide: err.data.guide as SetupGuide });
        setPicking(false);
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function reconnect(a: Account) {
    setBusy(a.id);
    try {
      window.location.href = (await api.linkAccount(a.id)).authorize_url;
    } catch (err) {
      setBusy(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function remove(a: Account) {
    if (!window.confirm(`Remove "${a.alias}"${a.identity ? ` (${a.identity})` : ""}? Its token is deleted.`)) return;
    try {
      await api.deleteAccount(a.id);
      await Promise.all([accounts.reload(), tokens.reload()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const named = naming ? accounts.data?.find((a) => a.id === naming.id) : undefined;

  return (
    <section>
      <div className="page-head">
        <div>
          <h2>Connections</h2>
          <p className="muted">
            Log in happens on each provider's own page; hydra-mcp keeps the token, encrypted.
            Choose which client sees which account in Clients.
          </p>
        </div>
        <button className="primary" onClick={() => setPicking(true)}>
          + Add a connector
        </button>
      </div>
      {error && <ErrorBanner text={error} onClose={() => setError(null)} />}
      {busy && <p className="callout callout-ok">Opening the sign-in page…</p>}

      {named && naming && (
        <NameDialog
          account={named}
          upstream={upstreams.data?.find((u) => u.id === named.upstream_id)}
          isNew={naming.isNew}
          onDone={async () => {
            setNaming(null);
            await accounts.reload();
          }}
        />
      )}

      {wizard && (
        <SetupWizard
          upstreamId={wizard.upstreamId}
          guide={wizard.guide}
          submitLabel="Save and sign in"
          openTab={false}
          onSaved={() => startConnect({ upstream_id: wizard.upstreamId }, wizard.upstreamId)}
          onClose={() => setWizard(null)}
          onUseToken={(() => {
            const c = connectorFor(wizard.upstreamId);
            return c?.guide?.token
              ? () => {
                  setWizard(null);
                  setGuide({ connector: c, token: true });
                }
              : undefined;
          })()}
        />
      )}

      {guide && (
        <ConnectorGuide
          connector={guide.connector}
          checkedAt={catalog.data?.checked_at}
          startWithToken={guide.token}
          signInLabel={
            guide.connector.auth === "oauth_preregistered" && !guide.connector.installed_as
              ? `Set up ${guide.connector.vendor} sign-in`
              : `Sign in with ${guide.connector.vendor}`
          }
          onSignIn={() => {
            const c = guide.connector;
            setGuide(null);
            void startConnect({ connector_id: c.id }, c.id);
          }}
          onToken={(token) => connectWithToken({ connector_id: guide.connector.id }, token)}
          onClose={() => setGuide(null)}
        />
      )}

      {picking && (
        <Picker
          connectors={catalog.data?.connectors ?? []}
          onPick={(c) => {
            setPicking(false);
            setGuide({ connector: c });
          }}
          onCustom={(name, url) => void startConnect({ name, url }, url)}
          onLocal={() => {
            setPicking(false);
            setLocal({});
          }}
          onClose={() => setPicking(false)}
        />
      )}

      {local && (
        <StdioForm
          upstream={local.upstream}
          account={local.account}
          onDone={(id, created) => void localDone(id, created)}
          onCancel={() => setLocal(null)}
        />
      )}

      {(accounts.loading || upstreams.loading) && <p className="muted">Loading…</p>}

      {groups.length === 0 && !picking && !guide && !wizard && !local && accounts.data && (
        // First visit: the library itself is the empty state, one click from a first login.
        <Picker
          title="Connect your first account"
          connectors={catalog.data?.connectors ?? []}
          onPick={(c) => setGuide({ connector: c })}
          onCustom={(name, url) => void startConnect({ name, url }, url)}
          onLocal={() => setLocal({})}
        />
      )}

      {groups.map(({ upstream, accounts: list }) => (
        <article key={upstream.id} className="card">
          <div className="page-head">
            <div className="conn-head">
              <Avatar name={upstream.name} size={32} />
              <div>
                <h3>{upstream.name}</h3>
                <span className="muted small">
                  {list.length} account{list.length > 1 ? "s" : ""}
                  {upstream.transport === "stdio" && " · local server"}
                </span>
              </div>
            </div>
            <div className="actions">
              {connectorFor(upstream.id) && (
                <button onClick={() => setGuide({ connector: connectorFor(upstream.id)! })}>Guide</button>
              )}
              <button
                onClick={() =>
                  upstream.transport === "stdio"
                    ? setLocal({ upstream })
                    : void startConnect({ upstream_id: upstream.id }, upstream.id)
                }
              >
                + Add another account
              </button>
            </div>
          </div>
          <ul className="account-list">
            {list.map((a) => {
              const status = tokens.data?.[a.id];
              const users = usedBy(a.id);
              return (
                <li key={a.id} className={status ? "" : "disconnected"}>
                  <Avatar name={a.alias} size={34} />
                  <div className="account-main">
                    <div className="account-title">
                      <strong>{a.alias}</strong>
                      <Status status={status} />
                    </div>
                    {a.identity !== a.alias && (a.identity || upstream.transport !== "stdio") && (
                      <div className="muted small">{a.identity || "identity unknown"}</div>
                    )}
                    <div className="small usage">
                      {users.length === 0 ? (
                        <span className="muted">
                          No client uses it yet. <a href="#clients">Give access in Clients →</a>
                        </span>
                      ) : (
                        users.map((u) => (
                          <span key={u.name} className={`pill ${u.mode === "write" ? "pill-write" : "pill-read"}`}>
                            {u.name} · {u.mode === "write" ? "read + write" : "read"}
                          </span>
                        ))
                      )}
                    </div>
                  </div>
                  <div className="account-actions">
                    {upstream.transport === "stdio" ? (
                      <button className={status ? "ghost" : "primary"} onClick={() => setLocal({ account: a })}>
                        New secrets
                      </button>
                    ) : (
                      !status && (
                      <button className="primary" onClick={() => void reconnect(a)}>
                        Reconnect
                      </button>
                      )
                    )}
                    <button className="ghost" onClick={() => setNaming({ id: a.id, isNew: false })}>
                      Rename
                    </button>
                    {status && upstream.transport !== "stdio" && (
                      <button className="ghost" onClick={() => void reconnect(a)}>
                        Reconnect
                      </button>
                    )}
                    {connectorFor(upstream.id)?.guide?.token && (
                      <button className="ghost" onClick={() => setTokenFor(a)}>
                        New token
                      </button>
                    )}
                    <button className="ghost danger" onClick={() => void remove(a)}>
                      Remove
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
          {tokenFor && tokenFor.upstream_id === upstream.id && connectorFor(upstream.id)?.guide?.token && (
            <TokenForm
              option={connectorFor(upstream.id)!.guide!.token!}
              provider={connectorFor(upstream.id)!.vendor}
              submitLabel={`Check and save for ${tokenFor.alias}`}
              onSubmit={(token) => connectWithToken({ account_id: tokenFor.id }, token)}
              onCancel={() => setTokenFor(null)}
            />
          )}
        </article>
      ))}
    </section>
  );
}

function Status({ status }: { status?: TokenStatus }) {
  if (!status) return <span className="status error">not connected</span>;
  const title =
    status.expires_at === null
      ? "Token without expiry (or a pasted token)"
      : `Token renewed automatically; current one valid until ${new Date(status.expires_at * 1000).toLocaleString()}`;
  return (
    <span className="status ok" title={title}>
      connected
    </span>
  );
}

function NameDialog({
  account,
  upstream,
  isNew,
  onDone,
}: {
  account: Account;
  upstream?: Upstream;
  isNew: boolean;
  onDone: () => Promise<void>;
}) {
  const [alias, setAlias] = useState(account.alias);
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    const value = alias.trim();
    if (!value) return;
    try {
      if (value !== account.alias) await api.putAccount({ ...account, alias: value });
      await onDone();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? `Another ${upstream?.name ?? ""} account is already called "${value}".`
          : String(err instanceof Error ? err.message : err),
      );
    }
  }

  return (
    <form className="card highlight" onSubmit={(e) => void save(e)}>
      <h3>
        {isNew ? "Connected" : "Rename"}: {upstream?.name ?? account.upstream_id}
        {account.identity ? ` as ${account.identity}` : ""}
      </h3>
      <label>
        Friendly name
        <input autoFocus required value={alias} onChange={(e) => setAlias(e.target.value)} />
      </label>
      <p className="muted small">
        Your AI picks accounts by this name, e.g. <code>work</code>, <code>perso</code>,{" "}
        <code>client-acme</code>. Short and distinct works best.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="submit" className="primary">
          Save
        </button>
        {!isNew && (
          <button type="button" onClick={() => void onDone()}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function Picker({
  connectors,
  onPick,
  onCustom,
  onLocal,
  onClose,
  title = "Add a connector",
}: {
  title?: string;
  connectors: Connector[];
  onPick: (c: Connector) => void;
  onCustom: (name: string, url: string) => void;
  onLocal: () => void;
  onClose?: () => void;
}) {
  const [filter, setFilter] = useState("");
  const [custom, setCustom] = useState({ name: "", url: "" });
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const rank = (c: Connector) => (c.status === "preview" ? 2 : 0) + (c.auth === "oauth_preregistered" ? 1 : 0);
    // Already used first, then one-click, then one-time setup, then previews.
    const sorted = [...connectors].sort(
      (x, y) => Number(!x.installed_as) - Number(!y.installed_as) || rank(x) - rank(y) || x.name.localeCompare(y.name),
    );
    return q ? sorted.filter((c) => `${c.name} ${c.vendor} ${c.category}`.toLowerCase().includes(q)) : sorted;
  }, [connectors, filter]);

  return (
    <div className="card highlight">
      <div className="page-head">
        <h3>{title}</h3>
        {onClose && <button onClick={onClose}>Close</button>}
      </div>
      <input autoFocus placeholder="Search: Atlassian, Gmail, Linear…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="grid">
        {shown.map((c) => (
          <button key={c.id} className="tile" onClick={() => onPick(c)}>
            <Avatar name={c.name} size={32} />
            <strong>{c.name}</strong>
            <span className="tile-badges">
              <span className="muted small">{c.category}</span>
              {c.installed_as && <span className="badge">+ another account</span>}
              {c.auth === "oauth_preregistered" ? (
                <span className="badge warn">one-time setup</span>
              ) : (
                <span className="badge ok">1-click</span>
              )}
              {c.guide?.token && <span className="badge">token</span>}
              {c.status === "preview" && <span className="badge">preview</span>}
            </span>
          </button>
        ))}
      </div>
      <details>
        <summary>Another MCP server (by URL)</summary>
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            onCustom(custom.name.trim(), custom.url.trim());
          }}
        >
          <input required placeholder="Name" value={custom.name} onChange={(e) => setCustom({ ...custom, name: e.target.value })} />
          <input required type="url" placeholder="https://…/mcp" value={custom.url} onChange={(e) => setCustom({ ...custom, url: e.target.value })} />
          <button type="submit">Connect</button>
        </form>
      </details>
      <details>
        <summary>A local server you run with a command (stdio)</summary>
        <p className="muted small">
          For MCP servers installed on this machine (<code>npx …</code>, <code>uvx …</code>, a
          binary). hydra-mcp starts one copy per account, each with its own secrets.
        </p>
        <button onClick={onLocal}>Add a local server</button>
      </details>
    </div>
  );
}
