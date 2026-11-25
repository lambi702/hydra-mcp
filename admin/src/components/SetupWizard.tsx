import { FormEvent, useState } from "react";
import { api, SetupGuide } from "../api";

/**
 * One-time setup for providers that refuse automatic registration (Google): hosted apps like
 * Claude created their OAuth client once for all users; a self-hosted proxy is its own app, so
 * its owner creates one. This walks through it with direct links and values to copy.
 *
 * `onSaved` receives a tab opened synchronously inside the click (a tab opened after an await
 * is a blocked popup), so the caller can send it straight to the provider's sign-in page.
 */
export function SetupWizard({
  upstreamId,
  guide,
  submitLabel,
  openTab,
  onSaved,
  onClose,
  onUseToken,
}: {
  upstreamId: string;
  guide: SetupGuide;
  submitLabel: string;
  openTab: boolean;
  onSaved: (tab: Window | null) => Promise<void> | void;
  onClose: () => void;
  /** Offered when the provider also accepts a pasted token (e.g. a GitHub PAT). */
  onUseToken?: () => void;
}) {
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Set<number>>(new Set());

  async function submit(e: FormEvent) {
    e.preventDefault();
    const tab = openTab ? window.open("about:blank", "_blank") : null;
    try {
      await api.setUpstreamOAuth(upstreamId, clientId.trim(), secret.trim());
      await onSaved(tab);
    } catch (err) {
      tab?.close();
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const toggle = (i: number) =>
    setDone((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  return (
    <form className="card wizard" onSubmit={(e) => void submit(e)}>
      <h3>One-time setup: let hydra-mcp sign in to {guide.provider}</h3>
      <p className="muted">
        {guide.provider} does not let new apps register themselves. Claude did this step once for
        all its users; hydra-mcp runs on your machine, so it is yours to do, once
        {guide.client_type ? ` (a ${guide.client_type})` : ""}. After that, every account connects
        in one click.
      </p>
      {guide.token && onUseToken && (
        <div className="callout callout-ok">
          <strong>In a hurry?</strong>
          <span>
            Skip this setup: {guide.provider} also accepts a {guide.token.name}.{" "}
            <button type="button" className="linkish" onClick={onUseToken}>
              Use a token instead
            </button>
          </span>
        </div>
      )}
      <ol className="steps">
        {guide.steps.map((step, i) => (
          <li key={i} className={done.has(i) ? "done" : ""}>
            <label className="step-head">
              <input type="checkbox" checked={done.has(i)} onChange={() => toggle(i)} />
              <strong>{step.title}</strong>
            </label>
            <p>{step.text}</p>
            <div className="step-actions">
              {step.link && (
                <a className="button" href={step.link} target="_blank" rel="noreferrer">
                  Open ↗
                </a>
              )}
            </div>
            {[...(step.copy ? [{ label: "", value: step.copy }] : []), ...(step.fields ?? [])].map((f) => (
              <CopyRow key={`${f.label}${f.value}`} label={f.label} value={f.value} />
            ))}
          </li>
        ))}
      </ol>
      <label>
        Client ID
        <input required autoComplete="off" value={clientId} onChange={(e) => setClientId(e.target.value)} />
      </label>
      <label>
        Client secret
        <input type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button type="submit" className="primary">
          {submitLabel}
        </button>
        <button type="button" onClick={onClose}>
          Cancel
        </button>
        {guide.docs && (
          <a href={guide.docs} target="_blank" rel="noreferrer" className="muted">
            Provider docs ↗
          </a>
        )}
      </div>
    </form>
  );
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="copy-row">
      {label && <span className="muted small">{label}</span>}
      {value.includes("\n") ? <pre className="copy-block">{value}</pre> : <code>{value}</code>}
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(value).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          });
        }}
      >
        {copied ? "Copied ✓" : "Copy"}
      </button>
    </div>
  );
}
