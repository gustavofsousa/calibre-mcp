# AGENTS.md — calibre-mcp

> Repo constitution. Read it before you touch this repo. The global `AGENTS.md` still applies; this
> file adds only what is specific to this project.

## Constitution

```yaml
type: pessoal             # my own Calibre library; named by the owner on 2026-10-14
open-source: true
rigor:                      # off | designed | enforced; types, defaults and events: _hq/ia/catalogs/project-types.md
  auth: designed
  privacy: off
  tests: designed
  ci: designed               # a CI workflow runs on push (README badge)
  observability: off
  scale: off
```

- **Promotion is an event the owner names.** Never change `type` or raise an axis on your own.
  Types, defaults and events: `_hq/ia/catalogs/project-types.md`.
