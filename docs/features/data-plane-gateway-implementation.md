# Rust Data Plane Gateway implementation

This change adds a reusable `data-plane-gateway` consisting of an Edge Frontend,
a Node Proxy, and a generic workload-to-target CONNECT contract. The sandbox
route adapter is its first consumer. It runs alongside the legacy Go
`frontend/pkg/frontend/sandboxrouter` implementation and FunctionProxy tunnel.

The workload topology, configuration, security controls, rollout, drain, and
rollback contract are specified in
[`data-plane-gateway-deployment.md`](data-plane-gateway-deployment.md).

## Contract

The reusable Node protocol carries `workloadID`, `targetIP`, and `targetPort`.
It does not contain sandbox or bridge terminology. Admission is bounded by
`YR_DATA_PLANE_ALLOWED_TARGET_CIDRS`.

The first sandbox adapter maps `sandboxID -> workloadID` and
`sandboxIP -> targetIP`. FunctionSystem publishes `RouteInfo` under
`/yr/route/business/yrk/{instanceID}`
with the existing `instanceStatus` plus `sandboxID`, `nodeProxyAddress`, and
`sandboxIP`. Edge also accepts a future
`portForwardRoutes` list whose entries bind `targetPort` to `NONE` or `TOKEN`
authentication. Missing entries default to anonymous port-forwarding. A token
entry is accepted only on the TLS listener. sandboxd or runtime-launcher returns the
latter values from `StartResponse`; neither backend interprets application
protocols or exposed ports. runtime-launcher resolves Docker/Podman bridge and
custom-network addresses with backend inspect; host, none, and container-shared
modes do not publish a Gateway endpoint. Before FunctionProxy asks sandboxd to
delete a sandbox, it synchronously retires that workload from Node Proxy over
the node-local route-control UDS. This admission barrier prevents a recycled
sandbox IP from inheriting the deleted workload's route without adding a
generation token to the public contracts.

## Data path

The Edge `RouteStore` performs a list followed by a revisioned watch. A cache
miss can issue one coalesced point-get. The production Edge listener calls
`EdgeRouteResolver`, then the shared `DataPlaneL4Connector`, which creates one
HTTP/2 `CONNECT` stream per workload TCP connection. The Node Proxy validates the
explicit target IP against configured CIDRs, rejects reserved addresses and
invalid ports, then relays opaque bytes with H2 flow control. HTTP, WebSocket,
SSH, TLS passthrough, database sessions and port-forwarding therefore use
the same connector; the Node never parses those protocols.

The HTTP listener implements direct HTTP streaming, WebSocket/HTTP upgrade,
and standard HTTP CONNECT. `yr-data-plane-forward` opens CONNECT and adapts the
returned byte stream to stdin/stdout or a local TCP port for native SSH/database
clients. Route deletion, terminal instance status, or target change stops new
admissions and actively closes matching sessions.

The same TLS listener contains a configurable static control-plane router that replaces the
Traefik path rules. Its `exact:/path` and boundary-aware `prefix:/path` entries
forward only the configured control API surface to the
configured Frontend address, preserves client credentials for Frontend to
authenticate, and never captures `/direct`, `/tunnel`, or instance-port paths.
Routes are deployment configuration and take effect after Edge restart; they
do not require a code change.

Ingress policy is selected by the parsed `AccessKind`, not by a caller-provided
tenant header. `/direct` always requires TLS and a validated Bearer token.
`/tunnel`, CONNECT port-forwarding and SSH default to anonymous access on the
plaintext or TLS listener. A `portForwardRoutes` entry in `/yr/route` can set
`authMode=TOKEN` for one sandbox target port; that port is then admitted only
on TLS and requires a tenant-bound token. The SDK/Create request projection is
deliberately deferred, so the current implementation consumes the route field
without claiming an external configuration API that does not exist yet.
The canonical header names follow Frontend's `X-*-Id` style (for example,
`X-Yr-Instance-Id` and `X-Request-Id`). Their HTTP/2 wire encoding is lowercase
as required by RFC 9113.

## Deployment

Phase 1 is process-mode deployment for the sandbox adapter. On a sandbox node, the optional
`yr-node-proxy` is supervised as an independent, off-by-default
component of the existing `yr start` agent or single-node master session. The
Edge Frontend is deliberately not added to master or agent mode; the CLI provides
a separate `yr start --edge` session. That process owns the production route
watcher, HTTP/CONNECT listener, H2 pool, readiness, metrics, and graceful drain. Kubernetes
workload manifests are a later packaging adapter. See
[`data-plane-gateway-deployment.md`](data-plane-gateway-deployment.md) for the
startup, environment, firewall, drain, and rollback contract.

`YR_DATA_PLANE_EDGE_FRONTEND_NODE_SECURITY_MODE` selects `network` or `mtls`. `network`
is the default optimized path and uses plaintext H2/TCP under the explicit
assumption that sandbox egress cannot reach protected internal CIDRs and Node
admits only configured Edge CIDRs. mTLS mode requires the Node server
certificate/client CA and the Edge client certificate/Node CA.
`YR_DATA_PLANE_ALLOWED_TARGET_CIDRS` is mandatory in production. For the
current sandbox route adapter it contains the node-local bridge CIDRs and
should be combined with
the platform's NetworkPolicy/security-group rules. `YR_NODE_PROXY_ADDRESS`
is projected by FunctionSystem into each instance route. `YR_DATA_PLANE_NODE_PROXY_MAX_STREAMS`
provides an optional hard overload limit; zero means the process resource
budget is the only limit.

The old Go watcher, `/sn/instance` contract and FunctionProxy tunnel are not
modified, allowing an independent feature-flagged rollout.

## Security boundary

Edge-to-Node network isolation and mTLS are mutually exclusive deployment modes. Both Node peer CIDRs and Edge client
CIDRs are checked before protocol processing. Unrestricted ACL flags remain
development-only and must be explicit. Node accepts only the route-projected target IP and a
TCP port and rejects targets outside configured sandbox CIDRs or reserved
addresses.

Edge is the data-plane authentication boundary. Its canonical credential is
`Authorization: Bearer <JWT>`, and it also accepts Frontend-compatible
`X-Auth: <JWT>`. When both are present, their token values must match; a conflict
returns `400` instead of choosing one implicitly. Both forms share the same
expiry, subject, bounded IAM-cache, and RouteInfo authorization checks.
Authorization, `X-Auth`, and query `token` credentials are stripped before
workload forwarding, and no user token is sent in the Edge-to-Node protocol.

External TLS terminates in Edge Frontend. Direct and all static control-plane
routes use only that TLS listener. Tunnel and CONNECT port-forwarding may also
use the plaintext listener when their resolved route does not require a token.
`yr-data-plane-forward` supports TLS to the CONNECT entry with an explicit CA
and server name. Edge-to-Node mTLS is an independent optional hardening choice.

## Security TODO: protected sandbox egress

Before `network` mode is enabled for production, the platform must install an
immutable sandbox-egress baseline that denies Node, Pod, Service, sandbox
bridge, VPC/peered, carrier-grade NAT, link-local/metadata, and corresponding
IPv6 internal CIDRs. Only platform-managed DNS and required runtime-control
endpoints may be exempted. The rule must be installed before a sandbox becomes
runnable, updated atomically, and remain stronger than user NetworkPolicy.

Current sandboxd policy matching cannot directly represent this contract with
a broad CIDR deny plus narrower allow exceptions. The follow-up must add a
separate managed-policy layer with CIDR matching and explicit platform-exception
precedence (for example an eBPF LPM trie), and must reject untrusted host-network
sandboxes. Until that follow-up lands, deployment-provided sandbox-veth and host
firewall rules are a required external prerequisite rather than an implemented
Gateway guarantee.

## Activity and idle lifecycle

The node proxy reports one complete batch per gateway process, containing
`(instanceID, activeStreamCount)` entries plus
`gatewayEpoch` and `timestampMs`. This avoids one RPC per instance and makes
retries idempotent: the gateway keeps the latest counts in memory while the
UDS is unavailable, then republishes the newest full snapshot after reconnect.
Stream open/close events trigger publication through a 10 ms coalescing
window; a 30-second periodic publication refreshes the lease when there are no
events. While disconnected, the publisher retries at most once per second and
does not block stream admission or relay.
FunctionSystem exposes `DataPlaneGatewayActivityService` on a dedicated
node-local UDS configured by `YR_DATA_PLANE_NODE_PROXY_ACTIVITY_UDS_DIR`; it never
shares the POSIX data-plane server.

FunctionProxy traffic and exec sessions remain independent busy sources. Any
non-zero source cancels the existing idle timer; the timer can start only when
all sources are idle. FunctionSystem keeps a lease per gateway epoch and
expires it after 90 seconds without a heartbeat. Expiry does not turn the
count into zero: when no valid gateway snapshot is available,
`IdleMgr::GatewayActivityUnavailable` pauses idle reclamation until a complete
batch is received. This protects against evicting a sandbox while a gateway
is disconnected, without stopping or degrading the gateway data plane.

The additional idle source is activated only when
`YR_DATA_PLANE_NODE_PROXY_ENABLED=true` explicitly enables the new gateway path;
when it is disabled, the legacy idle behavior is unchanged. Enabling it also
requires a non-empty `YR_NODE_PROXY_ADDRESS`. If its dedicated
UDS is absent or cannot start, gateway activity stays unknown and idle
reclamation remains paused. The UDS listener may start earlier, but returns
`UNAVAILABLE` until `LocalSchedDriver::ToReady`, which is invoked only after
module Sync and Recover. At that transition FunctionSystem first marks gateway
activity unknown synchronously and only then accepts snapshots, so startup
reports cannot race with proxy instance-state synchronization.

## Validation

`tests/mock_e2e.rs` starts real Node and Edge serving loops with mock sandbox
HTTP/upgrade and raw TCP services. It verifies direct HTTP, WebSocket,
CONNECT tunnel, port-forwarding, SSH/raw TCP, arbitrary target ports, readiness,
tenant/status errors, route cancellation, Node drain, H2
physical-connection reuse, and activity-count convergence. This complements
the unit tests for route aliases, resolver status preservation, configuration,
protocol admission, and activity batching.

`make data-plane-gateway-mock-e2e` adds a process-level gate: it launches the
release Node, Edge, and forwarding binaries against a temporary Docker etcd and
local mock sandbox. This verifies the production resolver call path, initial
list/readiness, live status watch, direct HTTP, and SSH-classified CONNECT path.
