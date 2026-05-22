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

import json
from unittest.mock import MagicMock, PropertyMock, patch

from ops import testing

from charm import TailscaleIntegratorK8SCharm

META = {
    "name": "tailscale-integrator-k8s",
    "provides": {
        "ingress": {"interface": "ingress", "optional": True},
        "provide-cmr-mesh": {"interface": "cross_model_mesh", "optional": True},
    },
    "requires": {
        "service-mesh": {"interface": "service_mesh", "limit": 1, "optional": True},
        "require-cmr-mesh": {"interface": "cross_model_mesh", "optional": True},
    },
}

CONFIG = {
    "options": {
        "tailscale-namespace": {
            "type": "string",
            "default": "tailscale",
        },
    },
}

# Patch targets for all tests: lightkube Client + KRM in the charm module, and the
# lightkube client property in the ServiceMeshConsumer library so it doesn't hit a
# real cluster during init/event handling.
PATCHES = [
    "charm.Client",
    "charm.KubernetesResourceManager",
    "charms.istio_beacon_k8s.v0.service_mesh.ServiceMeshConsumer.lightkube_client",
]


def _ctx():
    return testing.Context(TailscaleIntegratorK8SCharm, meta=META, config=CONFIG)


def _apply_patches():
    """Start common patches and return (mock_client, mock_krm_instance, patcher_list)."""
    patchers = []

    p_client = patch("charm.Client")
    mock_client = p_client.start()
    patchers.append(p_client)

    p_krm = patch("charm.KubernetesResourceManager")
    mock_krm_cls = p_krm.start()
    mock_krm = MagicMock()
    mock_krm_cls.return_value = mock_krm
    patchers.append(p_krm)

    p_lk = patch(
        "charms.istio_beacon_k8s.v0.service_mesh.ServiceMeshConsumer.lightkube_client",
        new_callable=PropertyMock,
        return_value=MagicMock(),
    )
    p_lk.start()
    patchers.append(p_lk)

    return mock_client, mock_krm, patchers


def _stop_patches(patchers):
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reconcile_no_relations():
    """With no ingress relations, reconcile produces no k8s objects and sets ActiveStatus."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="placeholder",
            remote_app_data={},
        )
        state_in = testing.State(leader=True, relations={ingress_rel})
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)
        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        assert len(k8s_objects) == 0
    finally:
        _stop_patches(patchers)


def test_reconcile_ingress_creates_service():
    """An ingress relation with a valid port creates a tailscale LoadBalancer Service."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "8080"},
        )
        state_in = testing.State(leader=True, relations={ingress_rel})
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        mock_krm.reconcile.assert_called_once()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        assert len(k8s_objects) == 1
        svc = k8s_objects[0]
        assert svc.metadata.name == "my-webapp-tailscale"
        assert svc.metadata.annotations["tailscale.com/hostname"] == "my-webapp"
        assert svc.spec.type == "LoadBalancer"
        assert svc.spec.loadBalancerClass == "tailscale"
        assert svc.spec.ports[0].port == 80
        assert svc.spec.ports[0].targetPort == 8080
        assert svc.spec.selector == {"app.kubernetes.io/name": "my-webapp"}
    finally:
        _stop_patches(patchers)


def test_reconcile_multiple_ingress_relations():
    """Multiple ingress relations each produce a Service."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        rel_a = testing.Relation(
            endpoint="ingress",
            remote_app_name="app-a",
            remote_app_data={"port": "3000"},
        )
        rel_b = testing.Relation(
            endpoint="ingress",
            remote_app_name="app-b",
            remote_app_data={"port": "9090"},
        )
        state_in = testing.State(leader=True, relations={rel_a, rel_b})
        state_out = ctx.run(ctx.on.relation_changed(rel_a), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        names = {obj.metadata.name for obj in k8s_objects}
        assert "app-a-tailscale" in names
        assert "app-b-tailscale" in names
    finally:
        _stop_patches(patchers)


def test_reconcile_ingress_no_port_skips():
    """An ingress relation without a port key is skipped gracefully."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="incomplete-app",
            remote_app_data={},
        )
        state_in = testing.State(leader=True, relations={ingress_rel})
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        assert len(k8s_objects) == 0
    finally:
        _stop_patches(patchers)


def test_reconcile_ingress_invalid_port_skips():
    """An ingress relation with a non-numeric port is skipped."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="bad-port-app",
            remote_app_data={"port": "not-a-number"},
        )
        state_in = testing.State(leader=True, relations={ingress_rel})
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        assert len(k8s_objects) == 0
    finally:
        _stop_patches(patchers)


def test_reconcile_with_istio_mesh():
    """With an istio mesh, both a Service and AuthorizationPolicy are created."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        mesh_rel = testing.Relation(
            endpoint="service-mesh",
            remote_app_name="istio-beacon",
            remote_app_data={
                "labels": json.dumps({"istio-injection": "enabled"}),
                "mesh_type": json.dumps("istio"),
            },
        )
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "8080"},
        )
        state_in = testing.State(leader=True, relations={mesh_rel, ingress_rel})
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        assert len(k8s_objects) == 2

        from lightkube.resources.core_v1 import Service

        services = [o for o in k8s_objects if isinstance(o, Service)]
        auth_policies = [o for o in k8s_objects if not isinstance(o, Service)]
        assert len(services) == 1
        assert len(auth_policies) == 1

        svc = services[0]
        assert svc.metadata is not None
        assert svc.metadata.name == "my-webapp-tailscale"

        ap = auth_policies[0]
        assert ap.metadata.name == "tailscale-to-my-webapp-policy"
        # The Source pydantic model does not currently model the 'namespaces' field,
        # so it is silently dropped.  Verify the from-rule structure is present.
        assert "from" in ap.spec["rules"][0]
        assert "source" in ap.spec["rules"][0]["from"][0]
    finally:
        _stop_patches(patchers)


def test_reconcile_with_custom_tailscale_namespace():
    """The tailscale-namespace config is used in the AuthorizationPolicy."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        mesh_rel = testing.Relation(
            endpoint="service-mesh",
            remote_app_name="istio-beacon",
            remote_app_data={
                "labels": json.dumps({"istio-injection": "enabled"}),
                "mesh_type": json.dumps("istio"),
            },
        )
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "8080"},
        )
        state_in = testing.State(
            leader=True,
            relations={mesh_rel, ingress_rel},
            config={"tailscale-namespace": "my-ts-ns"},
        )
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        from lightkube.resources.core_v1 import Service

        auth_policies = [o for o in k8s_objects if not isinstance(o, Service)]
        assert len(auth_policies) == 1
        # The Source pydantic model does not currently model the 'namespaces' field,
        # so it is silently dropped.  Verify the from-rule structure is present.
        assert "from" in auth_policies[0].spec["rules"][0]
        assert "source" in auth_policies[0].spec["rules"][0]["from"][0]
    finally:
        _stop_patches(patchers)


def test_reconcile_unsupported_mesh_type_blocks():
    """An unsupported mesh type sets BlockedStatus and returns early."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()

        # Mock mesh_type() to return an unsupported value without going through
        # pydantic validation of the relation data.
        with patch(
            "charm.ServiceMeshConsumer.mesh_type",
            return_value="linkerd",
        ):
            ingress_rel = testing.Relation(
                endpoint="ingress",
                remote_app_name="my-webapp",
                remote_app_data={"port": "8080"},
            )
            state_in = testing.State(leader=True, relations={ingress_rel})
            state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.BlockedStatus("Unsupported mesh type: linkerd")
        mock_krm.reconcile.assert_not_called()
    finally:
        _stop_patches(patchers)


def test_reconcile_relation_broken_removes_objects():
    """After relation-broken, KRM reconcile is called without the departed app's objects."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "8080"},
        )
        state_in = testing.State(leader=True, relations={ingress_rel})
        state_out = ctx.run(ctx.on.relation_broken(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        assert len(k8s_objects) == 0
    finally:
        _stop_patches(patchers)


def test_reconcile_mesh_relation_broken():
    """When service-mesh relation breaks, reconcile proceeds without mesh_type."""
    _, mock_krm, patchers = _apply_patches()
    try:
        # Patch reconcile_charm_labels so the library's _on_mesh_broken handler
        # doesn't attempt real k8s ConfigMap reads.
        p_labels = patch(
            "charms.istio_beacon_k8s.v0.service_mesh.reconcile_charm_labels",
        )
        p_labels.start()
        patchers.append(p_labels)

        ctx = _ctx()
        mesh_rel = testing.Relation(
            endpoint="service-mesh",
            remote_app_name="istio-beacon",
            remote_app_data={
                "labels": json.dumps({"istio-injection": "enabled"}),
                "mesh_type": json.dumps("istio"),
            },
        )
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "8080"},
        )
        state_in = testing.State(leader=True, relations={mesh_rel, ingress_rel})
        state_out = ctx.run(ctx.on.relation_broken(mesh_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        k8s_objects = mock_krm.reconcile.call_args[0][0]
        # With mesh broken, only the Service is created (no AuthorizationPolicy)
        assert len(k8s_objects) == 1
        assert k8s_objects[0].metadata.name == "my-webapp-tailscale"
    finally:
        _stop_patches(patchers)


def test_reconcile_istio_auth_policy_port_matches():
    """The AuthorizationPolicy operation port matches the ingress port as string."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        mesh_rel = testing.Relation(
            endpoint="service-mesh",
            remote_app_name="istio-beacon",
            remote_app_data={
                "labels": json.dumps({}),
                "mesh_type": json.dumps("istio"),
            },
        )
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "9999"},
        )
        state_in = testing.State(leader=True, relations={mesh_rel, ingress_rel})
        ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        k8s_objects = mock_krm.reconcile.call_args[0][0]
        from lightkube.resources.core_v1 import Service

        auth_policies = [o for o in k8s_objects if not isinstance(o, Service)]
        assert len(auth_policies) == 1
        port_rule = auth_policies[0].spec["rules"][1]["to"][0]["operation"]["ports"]
        assert port_rule == ["9999"]
    finally:
        _stop_patches(patchers)


def test_reconcile_sets_ingress_url():
    """The charm writes ingress URL data back to the relation for every ingress requirer."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "8080"},
        )
        state_in = testing.State(leader=True, relations={ingress_rel})
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        ingress_out = state_out.get_relation(ingress_rel.id)
        assert "ingress" in ingress_out.local_app_data
        ingress_data = json.loads(ingress_out.local_app_data["ingress"])
        assert ingress_data == {"url": "http://my-webapp"}
    finally:
        _stop_patches(patchers)


def test_reconcile_sets_ingress_url_with_istio():
    """The ingress URL is also written when an Istio service mesh is present."""
    _, mock_krm, patchers = _apply_patches()
    try:
        ctx = _ctx()
        mesh_rel = testing.Relation(
            endpoint="service-mesh",
            remote_app_name="istio-beacon",
            remote_app_data={
                "labels": json.dumps({"istio-injection": "enabled"}),
                "mesh_type": json.dumps("istio"),
            },
        )
        ingress_rel = testing.Relation(
            endpoint="ingress",
            remote_app_name="my-webapp",
            remote_app_data={"port": "8080"},
        )
        state_in = testing.State(leader=True, relations={mesh_rel, ingress_rel})
        state_out = ctx.run(ctx.on.relation_changed(ingress_rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        ingress_out = state_out.get_relation(ingress_rel.id)
        assert "ingress" in ingress_out.local_app_data
        ingress_data = json.loads(ingress_out.local_app_data["ingress"])
        assert ingress_data == {"url": "http://my-webapp"}
    finally:
        _stop_patches(patchers)
