#!/usr/bin/env python3
# Copyright 2026 Dylan Stephano-Shachter
# See LICENSE file for licensing details.

"""Minimal test charm that requires the ingress interface via IngressPerAppRequirer."""

import ops
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer


class IngressRequirerCharm(ops.CharmBase):
    """Test charm that requires ingress using the ingress library."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.ingress = IngressPerAppRequirer(self, port=80)
        framework.observe(self.ingress.on.ready, self._on_ingress_ready)
        framework.observe(self.ingress.on.revoked, self._on_ingress_revoked)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _):
        """Set active status on start."""
        self.unit.status = ops.ActiveStatus()

    def _on_ingress_ready(self, _):
        """Handle ingress ready event."""
        self.unit.status = ops.ActiveStatus()

    def _on_ingress_revoked(self, _):
        """Handle ingress revoked event."""
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(IngressRequirerCharm)
