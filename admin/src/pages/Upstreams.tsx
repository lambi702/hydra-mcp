import { FormEvent, useState } from "react";
import { api, ProbeResult, Upstream, UpstreamOAuth } from "../api";
import { SetupWizard } from "../components/SetupWizard";
import { useLoad } from "../useLoad";

const EMPTY: Upstream = { id: "", name: "", url: "" };

export function Upstreams() {
  const { data, error, reload, setError } = useLoad(api.upstreams);
  const [draft, setDraft] = useState<Upstream>(EMPTY);
  const [probe, setProbe] = useState<{ id: string; result: ProbeResult } | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api.putUpstream(draft);
      setDraft(EMPTY);
      await reload();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    }
  }

  async function remove(id: string) {
    if (!window.confirm(`Delete upstream "${id}" and all its accounts?`)) return;
    await api.deleteUpstream(id).catch((err: Error) => setError(err.message));
    await reload();
  }

  const [oauth, setOauth] = useState<{ id: string; info: UpstreamOAuth } | null>(null);
  const [manual, setManual] = useState({ client_id: "", client_secret: "" });

  async function openOAuth(id: string) {
    try {
      setOauth({ id, info: await api.upstreamOAuth(id) });
      setManual({ client_id: "", client_secret: "" });
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    }
  }

  async function saveManual(e: FormEvent) {
    e.preventDefault();
    if (!oauth) return;
    try {
      const info = await api.setUpstreamOAuth(oauth.id, manual.client_id, manual.client_secret);
      setOauth({ id: oauth.id, info });
      setManual({ client_id: "", client_secret: "" });
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    }
  }

  async function resetOAuth(id: string) {
    if (!window.confirm(`Forget the OAuth client of "${id}"? Accounts stay connected until refresh.`))
      return;
    await api.resetUpstreamOAuth(id).catch((err: Error) => setError(err.message));
    await openOAuth(id);
  }

  async function runProbe(id: string) {
    setProbe({ id, result: await api.probeUpstream(id) });
  }

  return (
    <section>
      <h2>Upstreams</h2>
      <p className="muted">An upstream is one MCP server URL. Accounts are identities on it.</p>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>Id</th>
            <th>Name</th>
            <th>URL</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data?.map((u) => (
            <tr key={u.id}>
              <td>{u.id}</td>
              <td>{u.name}</td>
              <td>
                <code>{u.transport === "stdio" ? `${u.command} ${(u.args ?? []).join(" ")}` : u.url}</code>
              </td>
              <td className="actions">
                {u.transport !== "stdio" && (
                  <>
                    <button onClick={() => void runProbe(u.id)}>Probe auth</button>
                    <button onClick={() => void openOAuth(u.id)}>OAuth client</button>
                    <button onClick={() => setDraft(u)}>Edit</button>
                  </>
                )}
                <button className="danger" onClick={() => void remove(u.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {probe && (
        <div className="card">
          <h3>Auth discovery for {probe.id}</h3>
          {probe.result.ok ? (
            <pre>{JSON.stringify(probe.result, null, 2)}</pre>
          ) : (
            <p className="error">{probe.result.error}</p>
          )}
          <button onClick={() => setProbe(null)}>Close</button>
        </div>
      )}

      {oauth && !oauth.info.registered && (
        <SetupWizard
          upstreamId={oauth.id}
          guide={oauth.info.guide}
          submitLabel="Save client"
          openTab={false}
          onSaved={() => openOAuth(oauth.id)}
          onClose={() => setOauth(null)}
        />
      )}
      {oauth && oauth.info.registered && (
        <form className="card" onSubmit={(e) => void saveManual(e)}>
          <h3>OAuth client of hydra-mcp at {oauth.id}</h3>
          {oauth.info.registered ? (
            <p>
              Registered {oauth.info.registration === "dcr" ? "automatically (DCR)" : "by hand"} at{" "}
              <code>{oauth.info.issuer}</code> as <code>{oauth.info.client_id}</code>
              {oauth.info.has_secret ? " (with a secret, stored encrypted)" : " (public client)"}.
            </p>
          ) : (
            <p className="muted">
              Nothing registered yet. Most providers register hydra-mcp automatically on the first
              Connect. Some (Google) need a client created in their console.
            </p>
          )}
          <p className="muted">
            For a manual client, create a “Web application” OAuth client at the provider with this
            redirect URI: <code>{oauth.info.redirect_uri}</code>
          </p>
          <label>
            Client ID
            <input
              required
              value={manual.client_id}
              onChange={(e) => setManual({ ...manual, client_id: e.target.value })}
            />
          </label>
          <label>
            Client secret (optional)
            <input
              type="password"
              autoComplete="off"
              value={manual.client_secret}
              onChange={(e) => setManual({ ...manual, client_secret: e.target.value })}
            />
          </label>
          <div className="actions">
            <button type="submit">Save manual client</button>
            {oauth.info.registered && (
              <button type="button" className="danger" onClick={() => void resetOAuth(oauth.id)}>
                Forget client
              </button>
            )}
            <button type="button" onClick={() => setOauth(null)}>
              Close
            </button>
          </div>
        </form>
      )}

      <form className="card" onSubmit={(e) => void save(e)}>
        <h3>Add or update an upstream</h3>
        <label>
          Id
          <input
            required
            placeholder="gmail"
            value={draft.id}
            onChange={(e) => setDraft({ ...draft, id: e.target.value })}
          />
        </label>
        <label>
          Name
          <input
            required
            placeholder="Gmail"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </label>
        <label>
          MCP URL
          <input
            required
            type="url"
            placeholder="https://…/mcp"
            value={draft.url ?? ""}
            onChange={(e) => setDraft({ ...draft, url: e.target.value })}
          />
        </label>
        <button type="submit">Save</button>
      </form>
    </section>
  );
}
