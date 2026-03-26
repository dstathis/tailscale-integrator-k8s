# tailscale-integrator-k8s

Add Kubernetes charms to your [Tailscale](https://tailscale.com/) tailnet. This charm integrates over the `ingress` relation to automatically create Tailscale-backed `LoadBalancer` services for related applications. It also supports the `service-mesh` relation for environments running [Istio](https://istio.io/), where it creates `AuthorizationPolicy` resources to allow traffic from the Tailscale namespace.

## Usage

Deploy the charm and relate it to any application that provides the `ingress` interface:

```bash
juju deploy tailscale-integrator-k8s --trust
juju integrate tailscale-integrator-k8s:ingress my-app:ingress
```

The charm will create a Kubernetes `Service` of type `LoadBalancer` with `loadBalancerClass: tailscale` for each related application, making it accessible on your tailnet.

### With a service mesh

If you are running Istio via `istio-beacon-k8s`, integrate over the `service-mesh` endpoint:

```bash
juju integrate tailscale-integrator-k8s:service-mesh istio-beacon:service-mesh
```

When a service mesh is detected, the charm additionally creates Istio `AuthorizationPolicy` resources to permit traffic from the Tailscale namespace to reach the target workloads.

## Configuration

| Option                | Type   | Default      | Description                               |
|-----------------------|--------|--------------|-------------------------------------------|
| `tailscale-namespace` | string | `tailscale`  | Namespace containing Tailscale resources. |

## Relations

| Endpoint           | Interface          | Role     | Description                                                  |
|--------------------|--------------------|----------|--------------------------------------------------------------|
| `ingress`          | `ingress`          | Provider | Creates Tailscale-backed LoadBalancer services for requirers. |
| `service-mesh`     | `service_mesh`     | Requirer | Detects mesh type and creates AuthorizationPolicy resources.  |

## Other resources

- [Contributing](CONTRIBUTING.md)
- [Juju documentation](https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/)

## License

This project is licensed under the GNU Affero General Public License v3.0 only. See [LICENSE](LICENSE).
