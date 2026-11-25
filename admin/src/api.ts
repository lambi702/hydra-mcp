// Typed client for the proxy's admin API (/admin/api). Mirrors proxy/src/hydra_mcp/models.py.

export interface Upstream {
  id: string;
  name: string;
  url: string;
}

export interface Account {
  id: string;
  upstream_id: string;
  alias: string;
  identity: string;
  enabled: boolean;
}

export type GrantMode = "read" | "write";

export interface Grant {
  account_id: string;
  tools: string;
  mode: GrantMode;
}

export interface Client {
  id: string;
  name: string;
  grants: Grant[];
}

export interface Status {
  version: string;
  modes: string[];
  public_url: string;
  broker_endpoint: string;
  endpoints: Record<string, string>;
}

/** Broker mode: one row per connected account (the token itself never leaves the proxy). */
export interface TokenStatus {
  account_id: string;
  expires_at: number | null;
  identity: string;
  updated_at: number;
}

export interface CopyField {
  label: string;
  value: string;
}

export interface SetupStep {
  title: string;
  text: string;
  link?: string | null;
  copy?: string;
  fields?: CopyField[];
}

/** The provider also accepts a static token (PAT, API key) as a bearer token. */
export interface TokenOption {
  name: string;
  create_url: string;
  how: string;
}

export interface ConnectorGuide {
  summary: string;
  before: string[];
  accounts: string;
  gotchas: string[];
  token: TokenOption | null;
  links: { label: string; url: string }[];
}

/** How to create an OAuth client by hand, for providers without dynamic registration. */
export interface SetupGuide {
  provider: string;
  client_type: string | null;
  redirect_uri: string;
  docs: string | null;
  steps: SetupStep[];
  token?: TokenOption | null;
}

export interface UpstreamOAuth {
  registered: boolean;
  redirect_uri: string;
  guide: SetupGuide;
  registration?: "dcr" | "manual";
  issuer?: string;
  client_id?: string;
  has_secret?: boolean;
}

export interface ClientKey {
  key: string;
  endpoint: string;
}

export interface ProbeResult {
  ok: boolean;
  error?: string;
  protected_resource?: Record<string, unknown>;
  authorization_servers?: Array<Record<string, unknown>>;
}

export type AuthKind = "oauth_dcr" | "oauth" | "oauth_preregistered" | "bearer";

export interface Connector {
  id: string;
  name: string;
  vendor: string;
  category: string;
  url: string;
  auth: AuthKind;
  status: "ga" | "preview" | string;
  scopes: string[];
  notes: string;
  docs: string;
  guide: ConnectorGuide | null;
  installed_as: string | null;
  /** Each workspace needs its own OAuth client, hence its own server row (Slack). */
  one_client_per_workspace?: boolean;
}

export interface Catalog {
  checked_at: string;
  connectors: Connector[];
}

const TOKEN_KEY = "hydra-mcp-admin-token";

/** Fired when the proxy rejects the stored admin token. */
export const UNAUTHORIZED_EVENT = "hydra-mcp-unauthorized";

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage unavailable: the token lives only for this page view
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/admin/api${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${getToken()}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (resp.status === 401) {
    // Wrong or rotated admin token: back to the login card instead of errors on every page.
    setToken("");
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (resp.status === 204) return undefined as T;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.join(".")}: ${d.msg}`).join("; ")
      : "";
    throw new ApiError(resp.status, [data.error ?? resp.statusText, detail].filter(Boolean).join(" — "), data);
  }
  return data as T;
}

export const api = {
  status: () => call<Status>("GET", "/status"),
  catalog: () => call<Catalog>("GET", "/catalog"),
  installConnector: (id: string, upstreamId?: string) =>
    call<Upstream>("POST", `/catalog/${id}/install`, upstreamId ? { id: upstreamId } : undefined),
  upstreams: () => call<Upstream[]>("GET", "/upstreams"),
  putUpstream: (u: Upstream) => call<Upstream>("PUT", "/upstreams", u),
  deleteUpstream: (id: string) => call<void>("DELETE", `/upstreams/${id}`),
  probeUpstream: (id: string) => call<ProbeResult>("POST", `/upstreams/${id}/probe`),
  accounts: () => call<Account[]>("GET", "/accounts"),
  putAccount: (a: Account) => call<Account>("PUT", "/accounts", a),
  deleteAccount: (id: string) => call<void>("DELETE", `/accounts/${id}`),
  accountsStatus: () => call<Record<string, TokenStatus>>("GET", "/accounts-status"),
  connect: (body: {
    connector_id?: string;
    upstream_id?: string;
    name?: string;
    url?: string;
    /** a second server row with its own OAuth client (another Slack workspace) */
    new_upstream?: boolean;
  }) =>
    call<{ authorize_url: string; upstream_id: string }>("POST", "/connect", body),
  connectToken: (body: {
    token: string;
    connector_id?: string;
    upstream_id?: string;
    account_id?: string;
  }) => call<{ account: Account; created: boolean; upstream_id: string }>("POST", "/connect-token", body),
  linkAccount: (id: string) => call<{ authorize_url: string }>("POST", `/accounts/${id}/link`),
  refreshIdentity: (id: string) =>
    call<{ identity: string; changed: boolean }>("POST", `/accounts/${id}/identity`),
  unlinkAccount: (id: string) => call<void>("DELETE", `/accounts/${id}/link`),
  upstreamOAuth: (id: string) => call<UpstreamOAuth>("GET", `/upstreams/${id}/oauth`),
  setUpstreamOAuth: (id: string, client_id: string, client_secret: string) =>
    call<UpstreamOAuth>("PUT", `/upstreams/${id}/oauth`, { client_id, client_secret }),
  resetUpstreamOAuth: (id: string) => call<void>("DELETE", `/upstreams/${id}/oauth`),
  clients: () => call<Client[]>("GET", "/clients"),
  clientsWithKey: () => call<string[]>("GET", "/clients-with-key"),
  createClientKey: (id: string) => call<ClientKey>("POST", `/clients/${id}/key`),
  revokeClientKey: (id: string) => call<void>("DELETE", `/clients/${id}/key`),
  putClient: (c: Client) => call<Client>("PUT", "/clients", c),
  deleteClient: (id: string) => call<void>("DELETE", `/clients/${id}`),
};
