# Third-party components

This project reuses the following open-source components as dependencies (not vendored/copied — installed via pip). Per project policy (see `CLAUDE.md`), licenses and authorship are preserved here.

| Component | Purpose in RADAR | License | Source |
|---|---|---|---|
| [courlan](https://github.com/adbar/courlan) by Adrien Barbaresi | URL canonicalization / cleaning for signal dedup | Apache-2.0 | pip: `courlan` |
| [datasketch](https://github.com/ekzhu/datasketch) by Eric Zhu | MinHash / LSH near-duplicate text detection | MIT | pip: `datasketch` |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | Fuzzy string similarity (secondary dedup confirmation) | MIT | pip: `rapidfuzz` |
| [PyYAML](https://pyyaml.org/) | Parsing OpenCLI's YAML output | MIT | pip: `pyyaml` |
| [Agent Reach](https://github.com/Panniantong/Agent-Reach) + OpenCLI | X/Twitter and Reddit collection (browser-session backend) | see upstream repo | external CLI, invoked as subprocess |
| [ruptures](https://github.com/deepcharles/ruptures) by Charles Truong et al. | Change-point detection for velocity/saturation trend classification | BSD-2-Clause | pip: `ruptures` |
| [Apprise](https://github.com/caronc/apprise) by Chris Caron | Unified alert dispatch (desktop, and any of 100+ services incl. WhatsApp/Slack/email once configured) | BSD-2-Clause | pip: `apprise` |
| [APScheduler](https://github.com/agronholm/apscheduler) by Alex Grönholm | Periodic job scheduling (pinned to stable 3.x line) | MIT | pip: `apscheduler<4` |
| [win10toast-persist](https://github.com/GitBib/win10toast-persist) | Windows toast notification backend used by Apprise's `windows://` target | MIT | pip: `win10toast-persist` |
| [psutil](https://github.com/giampaolo/psutil) | CPU/RAM measurement for benchmarking | BSD-3-Clause | pip: `psutil` |
| [feedparser](https://github.com/kurtmckee/feedparser) by Kurt McKee | RSS/Atom feed collection | BSD-2-Clause | pip: `feedparser` |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube search collection (flat metadata extraction, no API key) | Unlicense | pip: `yt-dlp` |
| [requests](https://github.com/psf/requests) | HTTP client (Hacker News Algolia API) | Apache-2.0 | pip: `requests` |
| [GitHub CLI (`gh`)](https://github.com/cli/cli) | GitHub repo search collection (already authenticated on this machine) | MIT | external CLI, invoked as subprocess |
| [HN Algolia Search API](https://hn.algolia.com/api) | Hacker News story search | official public API, no separate license needed (no code reused) | HTTPS, no auth |

No source code from these projects is copied into this repository. They are used as-is via their public APIs/CLIs under their respective licenses.
