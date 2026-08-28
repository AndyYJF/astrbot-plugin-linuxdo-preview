# Byparr attribution and license notice

The `sidecar/` adapter imports and extends Byparr internals and is distributed
under the GNU General Public License, version 3 only (`GPL-3.0-only`). The rest
of this repository is a separate HTTP client/plugin aggregation and is not
relicensed by this notice.

Upstream project: [ThePhaseless/Byparr](https://github.com/ThePhaseless/Byparr)

- Version: `v3.0.4`
- Source commit: `cb2a862386e92f141e8aa3b58f8532ef2fc36ed0`
- Container image: `ghcr.io/thephaseless/byparr:3.0.4`
- Pinned multi-architecture digest:
  `sha256:874f719518f617d03a60e03411fc5d090647e1a877041e81f8dc965927c7deb6`
- Upstream license: GNU General Public License, version 3

The complete GPLv3 text is provided in
[`LICENSE.GPL-3.0.txt`](./LICENSE.GPL-3.0.txt). The pinned upstream container
also carries its source tree and upstream `LICENSE` under `/app`.

Source corresponding to the pinned upstream version is available from the
[v3.0.4 tag](https://github.com/ThePhaseless/Byparr/tree/v3.0.4). Modified
adapter source is the `sidecar/` directory in this repository. The adapter
reproduces the pinned upstream browser-launch options so it can pass a
Playwright `storage_state` object into a fresh context; it does not expose raw
cookies, arbitrary URLs, or a general browser-control endpoint.
