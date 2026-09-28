# Evidence: main is protected

Captured 2026-09-28T19:37:05Z from the GitHub API:

```json
{"allow_deletions":false,"allow_force_pushes":false,"enforce_admins":true,"required_conversation_resolution":true,"required_pull_request_reviews":{"dismiss_stale_reviews":true,"required_approving_review_count":1},"required_status_checks":{"contexts":["lint and type check","backend tests","frontend tests","build images (no push)","trivy image scan","validate k8s manifests","compose integration smoke"],"strict":true}}
```

## What each setting buys

| Setting | Value | Why |
|---|---|---|
| `enforce_admins` | `true` | The repository owner cannot push to `main` either. Without this, protection is a suggestion for everyone who matters. |
| `required_approving_review_count` | `1` | A human other than the author has to look. |
| `dismiss_stale_reviews` | `true` | Pushing new commits after an approval drops it — otherwise "approved" can mean "approved something else". |
| `strict` (up to date) | `true` | The branch must be rebased on `main` before merging, so the checks ran against what will actually land. |
| `allow_force_pushes` | `false` | History on `main` cannot be rewritten. |
| `required_conversation_resolution` | `true` | Review comments must be resolved, not merged past. |

## Required checks

All seven CI jobs must pass before the merge button enables. These are the exact job names from
`.github/workflows/ci.yml`, which is why a renamed job silently stops being required — a real
footgun worth knowing about.

## Screenshot

`docs/evidence/branch-protection.png` — the Settings → Branches page showing these rules, and
`docs/evidence/blocked-merge.png` — a PR with the merge button disabled pending checks and review.
