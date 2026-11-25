import { FormEvent, useState } from "react";
import { Account, api, Upstream } from "../api";
import { ErrorBanner } from "./ErrorBanner";

/** `KEY=value` lines <-> an object. Blank lines and `# comments` are ignored. */
export function parseEnv(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) throw new Error(`"${line}" is not KEY=value`);
    out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
  }
  return out;
}

/**
 * Add a local (stdio) server account. Three uses:
 *  - no `upstream`: a new server (command, arguments, shared settings) and its first account;
 *  - `upstream`: another account of a server already added (alias + its secrets);
 *  - `account`: replace the secrets of one account (the old values are never shown).
 *
 * hydra-mcp starts the program once with these settings and lists its tools before saving.
 */
export function StdioForm({
  upstream,
  account,
  onDone,
  onCancel,
}: {
  upstream?: Upstream;
  account?: Account;
  onDone: (accountId: string, created: boolean) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [shared, setShared] = useState("");
  const [isolate, setIsolate] = useState(false);
  const [alias, setAlias] = useState("");
  const [secrets, setSecrets] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const account_env = parseEnv(secrets);
      const r = await api.connectStdio(
        account
          ? { account_id: account.id, account_env }
          : upstream
            ? { upstream_id: upstream.id, alias: alias.trim(), account_env }
            : {
                name: name.trim(),
                command: command.trim(),
                args: args.split("\n").map((a) => a.trim()).filter(Boolean),
                env: parseEnv(shared),
                isolate_home: isolate,
                alias: alias.trim(),
                account_env,
              },
      );
      onDone(r.account.id, r.created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const title = account
    ? `New settings for ${account.alias}`
    : upstream
      ? `Another ${upstream.name} account`
      : "A local MCP server (stdio)";

  return (
    <form className="card highlight stack" onSubmit={submit}>
      <div className="page-head">
        <h3>{title}</h3>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {!upstream && !account && (
        <>
          <p className="muted small">
            hydra-mcp starts this program itself, once per account, each copy with its own secrets.
            It is run directly, not through a shell: give the full path if it is not on the PATH of
            hydra-mcp, and no quotes, <code>~</code> or <code>$VAR</code>.
          </p>
          <label>
            Name
            <input required placeholder="GitHub (local)" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Command
            <input required placeholder="npx" value={command} onChange={(e) => setCommand(e.target.value)} />
          </label>
          <label>
            Arguments, one per line
            <textarea rows={3} placeholder={"-y\n@modelcontextprotocol/server-github"} value={args} onChange={(e) => setArgs(e.target.value)} />
          </label>
          <label>
            <span>
              Shared settings (not secret), <code>KEY=value</code> per line
            </span>
            <textarea rows={2} placeholder="LOG_LEVEL=info" value={shared} onChange={(e) => setShared(e.target.value)} />
          </label>
          <label className="check">
            <input type="checkbox" checked={isolate} onChange={(e) => setIsolate(e.target.checked)} />
            Separate home folder per account (for servers that save a browser login under ~)
          </label>
        </>
      )}
      {!account && (
        <label>
          Account name (what your AI picks)
          <input required placeholder="work" value={alias} onChange={(e) => setAlias(e.target.value)} />
        </label>
      )}
      <label>
        <span>
          Secrets of this account, <code>KEY=value</code> per line (stored encrypted, never shown
          again)
        </span>
        <textarea
          rows={3}
          className="secret"
          spellCheck={false}
          autoComplete="off"
          placeholder="GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_…"
          value={secrets}
          onChange={(e) => setSecrets(e.target.value)}
        />
      </label>
      {error && <ErrorBanner text={error} onClose={() => setError(null)} />}
      <div className="actions">
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Starting it to check…" : "Check and save"}
        </button>
      </div>
    </form>
  );
}
