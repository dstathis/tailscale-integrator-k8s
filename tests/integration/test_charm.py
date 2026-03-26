# Copyright 2026 Dylan Stephano-Shachter
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/

"""Integration tests for tailscale-integrator-k8s."""

import json
import logging
import pathlib
import subprocess

import jubilant

logger = logging.getLogger(__name__)

APP_NAME = "tailscale-integrator-k8s"
REQUIRER_APP = "ingress-requirer"


# ---------------------------------------------------------------------------
# Deploy & basic config
# ---------------------------------------------------------------------------


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm and verify it reaches active status."""
    juju.deploy(charm.resolve(), app=APP_NAME, trust=True)
    juju.wait(jubilant.all_active)
    status = juju.status()
    assert status.apps[APP_NAME].app_status.current == "active"


def test_config_tailscale_namespace(juju: jubilant.Juju):
    """Verify the tailscale-namespace config option can be set and reset."""
    juju.config(APP_NAME, {"tailscale-namespace": "custom-ns"})
    config = juju.config(APP_NAME)
    assert config["tailscale-namespace"] == "custom-ns"

    # Reset to default
    juju.config(APP_NAME, reset="tailscale-namespace")
    config = juju.config(APP_NAME)
    assert config["tailscale-namespace"] == "tailscale"


# ---------------------------------------------------------------------------
# Ingress relation workflow
# ---------------------------------------------------------------------------


def test_ingress_relation(juju: jubilant.Juju, ingress_requirer_charm: pathlib.Path):
    """Deploy the ingress-requirer tester and integrate over ingress.

    The tester charm sets ``port: 80`` in its app relation data.
    The tailscale-integrator should create a LoadBalancer Service for it.
    """
    juju.deploy(ingress_requirer_charm.resolve(), app=REQUIRER_APP)
    juju.wait(jubilant.all_active)

    juju.integrate(f"{APP_NAME}:ingress", f"{REQUIRER_APP}:ingress")
    juju.wait(jubilant.all_active)

    # Verify the relation shows up in status.
    status = juju.status()
    app_relations = status.apps[APP_NAME].relations
    assert "ingress" in app_relations, f"Expected 'ingress' relation, got: {app_relations}"

    # Verify a tailscale LoadBalancer Service was created in the model namespace.
    model = juju.model
    assert model is not None
    svc_name = f"{REQUIRER_APP}-tailscale"
    result = subprocess.run(
        ["kubectl", "get", "svc", svc_name, "-n", model, "-o", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Expected k8s Service '{svc_name}' in namespace '{model}', stderr: {result.stderr}"
    )
    svc = json.loads(result.stdout)
    assert svc["spec"]["type"] == "LoadBalancer"
    assert svc["spec"]["loadBalancerClass"] == "tailscale"
    assert svc["spec"]["ports"][0]["port"] == 80
    assert svc["spec"]["ports"][0]["targetPort"] == 80


def test_ingress_relation_removal(juju: jubilant.Juju):
    """Remove the ingress relation and verify the Service is cleaned up."""
    juju.remove_relation(f"{APP_NAME}:ingress", f"{REQUIRER_APP}:ingress")
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME),
        error=lambda status: jubilant.any_error(status, APP_NAME),
    )

    # The LoadBalancer Service should have been removed by KRM reconcile.
    model = juju.model
    assert model is not None
    svc_name = f"{REQUIRER_APP}-tailscale"
    result = subprocess.run(
        ["kubectl", "get", "svc", svc_name, "-n", model, "-o", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        f"Service '{svc_name}' should have been removed after relation broken"
    )


# ---------------------------------------------------------------------------
# Service mesh integration
# ---------------------------------------------------------------------------


def test_service_mesh_integration(juju: jubilant.Juju):
    """Integrate with istio-beacon-k8s over the service-mesh relation.

    This verifies that the tailscale-integrator-k8s charm can establish
    a service-mesh relation and remains active.  The istio-beacon charm
    itself may not reach active without a full Istio installation, so we
    only assert on the tailscale-integrator's status.
    """
    juju.deploy(
        "istio-beacon-k8s",
        app="istio-beacon",
        trust=True,
        channel="2/stable",
    )
    juju.integrate(f"{APP_NAME}:service-mesh", "istio-beacon:service-mesh")

    # Wait for the tailscale-integrator to settle; istio-beacon may not be active.
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME),
        error=lambda status: jubilant.any_error(status, APP_NAME),
    )

    # Verify the service-mesh relation exists.
    status = juju.status()
    app_relations = status.apps[APP_NAME].relations
    assert "service-mesh" in app_relations, (
        f"Expected 'service-mesh' relation, got: {app_relations}"
    )


def test_service_mesh_with_ingress(juju: jubilant.Juju, ingress_requirer_charm: pathlib.Path):
    """With both service-mesh and ingress active, verify the charm handles both.

    Re-integrate the ingress-requirer (from the earlier test) and confirm
    the tailscale-integrator stays active while related to both endpoints.
    """
    juju.integrate(f"{APP_NAME}:ingress", f"{REQUIRER_APP}:ingress")
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME),
        error=lambda status: jubilant.any_error(status, APP_NAME),
    )

    status = juju.status()
    app_relations = status.apps[APP_NAME].relations
    assert "ingress" in app_relations
    assert "service-mesh" in app_relations
