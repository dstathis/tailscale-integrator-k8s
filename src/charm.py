#!/usr/bin/env python3
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

"""Tailscale Integrator for Kubernetes."""

import json
import logging

import ops
from charmed_service_mesh_helpers.models import (
    AuthorizationPolicySpec,
    From,
    Operation,
    Rule,
    Source,
    To,
    WorkloadSelector,
)
from charms.istio_beacon_k8s.v0.service_mesh import ServiceMeshConsumer
from lightkube import Client
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from lightkube_extensions.batch import KubernetesResourceManager
from lightkube_extensions.types import AuthorizationPolicy

logger = logging.getLogger(__name__)


class TailscaleIntegratorK8SCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.mesh = ServiceMeshConsumer(self)
        framework.observe(self.on.config_changed, self.reconcile)
        framework.observe(self.on["ingress"].relation_changed, self.reconcile)
        framework.observe(self.on["ingress"].relation_broken, self.reconcile)
        framework.observe(self.on["service-mesh"].relation_changed, self.reconcile)
        framework.observe(self.on["service-mesh"].relation_broken, self.reconcile)

    def reconcile(self, _):
        """Reconcile the charm."""
        k8s_objects = []
        if mesh_type := self.mesh.mesh_type():
            if mesh_type != "istio":
                logger.error(f"Unsupported mesh type: {mesh_type}")
                # Set Blocked status since we don't know how to handle this mesh type.
                self.unit.status = ops.BlockedStatus(f"Unsupported mesh type: {mesh_type}")
                return
        for rel in self.model.relations["ingress"]:
            app_name = rel.app.name
            try:
                relation_port = rel.data[rel.app]["port"]
            except KeyError:
                logger.info(f"Ingress relation for {rel.app.name} not ready. Skipping.")
                continue
            try:
                port = int(relation_port)
            except (TypeError, ValueError):
                logger.warning(
                    f"Invalid ingress port '{relation_port}' for {rel.app.name}. Skipping."
                )
                continue
            k8s_objects.append(
                Service(
                    metadata=ObjectMeta(
                        name=f"{app_name}-tailscale",
                        namespace=self.model.name,
                        annotations={"tailscale.com/hostname": app_name},
                    ),
                    spec=ServiceSpec(
                        selector={"app.kubernetes.io/name": app_name},
                        ports=[ServicePort(protocol="TCP", port=80, targetPort=port)],
                        type="LoadBalancer",
                        loadBalancerClass="tailscale",
                    ),
                )
            )
            if mesh_type == "istio":
                k8s_objects.append(
                    AuthorizationPolicy(
                        metadata=ObjectMeta(
                            name=f"tailscale-to-{app_name}-policy",
                            namespace=self.model.name,
                        ),
                        spec=AuthorizationPolicySpec(
                            selector=WorkloadSelector(
                                matchLabels={"app.kubernetes.io/name": app_name}
                            ),
                            rules=[
                                Rule(
                                    # Rule uses populate_by_name=True so pydantic accepts
                                    # `from_` at runtime, but pyright only sees the
                                    # "from" alias and rejects `from_` as unknown.
                                    from_=[  # type: ignore[call-arg]
                                        From(
                                            source=Source(
                                                # The upstream Source model doesn't declare
                                                # `namespaces`, but pydantic passes it through
                                                # to the Istio AuthorizationPolicy spec.
                                                namespaces=[self.config["tailscale-namespace"]]  # type: ignore[call-arg]
                                            )
                                        )
                                    ]
                                ),
                                Rule(to=[To(operation=Operation(ports=[str(port)]))]),
                            ],
                        ).model_dump(by_alias=True, exclude_unset=True, exclude_none=True),
                    )
                )
            rel.data[self.app]["ingress"] = json.dumps({"url": f"http://{app_name}"})
        # Scope ownership to this specific charm instance, not just the app name.
        # get_deployed_resources() lists across all namespaces (namespace="*") and
        # reconcile() deletes anything carrying these labels that isn't in the desired
        # set. The app name alone is identical for every instance of this charm on the
        # cluster (e.g. the same charm in a "prod" and a "staging" model), so a bare
        # {"krm_owner": app} selector makes each instance garbage-collect the other
        # instances' Services. Including the model name makes the selector unique per
        # instance (namespaces, and therefore model names, are unique within a cluster).
        instance_id = f"{self.app.name}-{self.model.name}"
        lightkube_client = Client(namespace=self.model.name, field_manager=instance_id)
        resource_types: set[type] = {Service}
        if mesh_type == "istio":
            resource_types.add(AuthorizationPolicy)
        krm = KubernetesResourceManager(
            labels={"krm_owner": instance_id},
            lightkube_client=lightkube_client,
            logger=logger,
            resource_types=resource_types,
        )
        krm.reconcile(k8s_objects)
        self.model.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(TailscaleIntegratorK8SCharm)
