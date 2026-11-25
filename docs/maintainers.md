# Maintainers guide

## Repository settings

Most settings are applied by a script, so they are reviewable and repeatable:

```bash
gh auth login               # as a repository admin
scripts/setup-github.sh     # safe to run again; REPO=owner/name to target another repo
```

| Setting | Value | Why |
| --- | --- | --- |
| Merge methods | squash only, PR title as commit title, delete branch on merge | linear, readable history; one commit per change |
| Ruleset on `main` | no deletion, no force push, linear history, pull request required (0 approvals, conversations resolved), CI checks required and up to date | nothing reaches `main` without passing CI; a solo maintainer can still merge |
| Dependabot alerts and security updates | on | vulnerable dependencies get a PR automatically |
| Dependabot version updates | weekly, grouped (`.github/dependabot.yml`) | few, reviewable PRs |
| Private vulnerability reporting | on | `SECURITY.md` points reporters to it |
| Secret scanning and push protection | on (public repository) | blocks pushes that contain known token formats |
| CodeQL | `security-extended`, Python, TypeScript and Actions (`.github/workflows/codeql.yml`) | static analysis on every PR and weekly |
| Dependency review | fails PRs adding a dependency with a high-severity advisory | |
| Actions token | read-only by default, workflows cannot approve PRs | limits what a compromised workflow can do |
| Workflows | `permissions: contents: read`, `persist-credentials: false` on checkout | least privilege |
| Labels | `bug`, `enhancement`, `connector`, `documentation`, `security`, `good first issue`, `help wanted`, `triage`, `dependencies`, `question` | used by the issue templates |
| Topics, description, Discussions | set | discoverability, a place for questions |

### Settings the script cannot apply

- **Your account**: two-factor authentication on, and a passkey or security key if you have one.
- **Social preview**: Settings, General, Social preview: upload `docs/assets/social-preview.png`
  (1280×640).
- **Discussions**: create the categories *Q&A*, *Ideas*, *Show and tell*; pin a welcome post.
- **Actions, General**: *Require approval for all outside collaborators* for fork PR workflows.
- **Releases**: enable *Immutable releases* if offered on your plan.
- After making the repository public, run `scripts/setup-github.sh` again: secret scanning and
  push protection only apply to public repositories on the free plan.

## Before the repository goes public

1. Search the history for anything private:
   `git log -p | grep -iE "token|secret|password|@[a-z0-9-]+\.(com|be|io)"`. If something
   personal ever landed in a commit, publish a fresh history instead
   (`git checkout --orphan public && git commit -m "Initial public release"`).
2. Check that the CI is green on `main` and the README renders (images, badges, links).
3. Tag the first release (below).

## Releasing

Releases are built by [`.github/workflows/release.yml`](../.github/workflows/release.yml): the
wheel and sdist (with the admin page inside, checked by `scripts/check-dist.sh`) go to PyPI, and
the Docker image (linux/amd64 and arm64) to `ghcr.io/lambi702/hydra-mcp`.

### One-time setup (before the first PyPI release)

1. **PyPI trusted publisher**: on pypi.org, *Your projects*, *Publishing*, *Add a new pending
   publisher*: project `hydra-mcp`, owner `lambi702`, repository `hydra-mcp`, workflow
   `release.yml`, environment `pypi`. No API token is created or stored.
2. **GitHub environment**: Settings, Environments, *New environment* `pypi`. Add yourself as a
   required reviewer: every PyPI upload then waits for one click.
3. **Image visibility**: after the first image push, set the `hydra-mcp` package on GitHub to
   public (Packages, Package settings) and link it to the repository if it is not.

### Each release

1. Move the *Unreleased* entries of `CHANGELOG.md` under a new version heading with the date.
2. Bump `version` in `proxy/pyproject.toml`, `proxy/src/hydra_mcp/__init__.py` and
   `admin/package.json` (the workflow refuses a tag that does not match).
3. Merge that as a PR titled `Release vX.Y.Z`.
4. Tag and publish: `git tag -s vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`, then
   `gh release create vX.Y.Z --notes-from-tag` (or paste the changelog section). Publishing the
   release starts the workflow; approve the `pypi` deployment when asked.
5. Check: `uvx hydra-mcp@X.Y.Z --version` and
   `docker run --rm ghcr.io/lambi702/hydra-mcp:X.Y.Z --version`.

To rehearse without publishing, run the workflow by hand (Actions, Release, *Run workflow*): it
builds and checks the package and the image, and pushes nothing.

### The README GIF

`docs/assets/demo.gif` is recorded from the demo, so it can be redone after any UI change:

```bash
uvx hydra-mcp demo --no-open          # or: make demo, in a checkout
node scripts/record-demo.mjs "<admin page link it printed>" docs/assets/demo.gif
```

The script needs Playwright with Chromium and ffmpeg. It drives the real admin page and the
real OAuth flow, and its last scene shows real responses from the proxy.

## Triage

- New issues arrive with `triage`. Within a week: reproduce or ask for details, set the type
  label, remove `triage`.
- Connector requests: verify the URL and the vendor docs, then label `help wanted` if someone can
  test with a real account.
- Questions go to Discussions; convert the issue.
- A vulnerability filed publicly by mistake: hide the comment or lock the issue, copy the report
  into a private advisory, and thank the reporter.
