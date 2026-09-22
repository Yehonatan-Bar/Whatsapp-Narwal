# Narwal Flow Local-Control and Reverse-Engineering Engineering Report

**Research snapshot: September 22, 2026.** This report treats the current open-source implementations themselves as protocol documentation and distinguishes verified behavior from developer reports and inference.

Evidence labels used throughout:

- **[C] Confirmed** — source code plus hardware tests, or multiple independent hardware reports.
- **[S] Strong evidence** — implemented in open source and technically well supported, but hardware coverage is limited.
- **[R] Reported** — one or a small number of user/developer reports.
- **[I] Inferred** — conclusion from code/protocol behavior that has not been independently validated.
- **[U] Unknown** — no reliable evidence found.

## Executive technical findings

The most important conclusion is that **a standard Narwal Flow / AX12 can currently be controlled locally over the LAN without logging into Narwal's cloud from the controller**. The best-documented implementation is [`sjmotew/NarwalIntegration`](https://github.com/sjmotew/NarwalIntegration), currently v1.0.10. It talks directly to the robot at `ws://<robot-ip>:9002`, uses a small Narwal framing layer wrapped around protobuf-encoded messages, receives pushed status/map broadcasts, and does not perform an authentication exchange. Its README explicitly describes it as local/cloud-independent, and its current source separates the reverse-engineered client into a top-level `narwal_client/` package rather than burying all protocol logic in Home Assistant. citeturn18view0turn24view0turn21view1

That result does **not** mean every Narwal product using the same phone application implements that protocol. Freo X Ultra, for example, is documented as a different platform using ZeroMQ/ZMTP on port 6789 and cloud services; some older J/T models are cloud-only; and one device reported by its owner as a “Flow compact version” had TCP 9002 closed on firmware `01.06.22.17`. Protocol compatibility must therefore be established by model/product key/firmware, not by mobile-app family. citeturn18view0turn27view0

The local Flow protocol has an unusually favorable reverse-engineering property: **there is no cryptographic local pairing secret in the current AX12 implementation**. The client opens an ordinary non-TLS WebSocket, can query or discover the device identity, subscribes to broadcasts, and sends protobuf commands. That makes a standalone controller materially simpler than integrations for vendors that require cloud-derived device keys. The downside is security: LAN access effectively becomes the security boundary. citeturn21view1turn21view4turn21view5turn21view6

The current mainline HA project also contains the strongest Git-history evidence about what was previously misunderstood. In particular, room cleaning was broken for a long time because integrations sent room payloads to `clean/plan/start`. That topic actually launches a plan already stored on the robot and can return success while ignoring the room payload. Independent work by `jgus`, `Sean-StarLabs`, and `sytchi` established that the correct command is `clean/start_clean` with a reconstructed `CleanTask`. That correction was merged in PR #49 and verified on both Flow AX12 and AX26 hardware. citeturn18view0turn27view1turn27view2

For an experienced engineer, the practical recommendation is therefore:

**For Home Assistant:** use `sjmotew/NarwalIntegration` as the default AX12 integration. It has native HA `vacuum.clean_area`, the broadest recent testing, the best protocol notes, live map/state support, and the cleanest separation of the protocol client. Use `sytchi/NarwalIntegration` instead, or port its code, when arbitrary rectangular zone cleaning is a hard requirement today. citeturn18view0turn22view6turn27view9

**For custom software:** start from the MIT-licensed top-level `narwal_client/` package in the sjmotew repository. It is already close to the library boundary this report would otherwise recommend extracting. Its declared dependencies are `websockets`, `protobuf`, `bbpb`, and Pillow; the runtime client itself contains the WebSocket/session/protobuf logic and does not inherently require the HA entity layer. citeturn19view2turn24view0turn20view0

**For missing local capabilities:** fall back selectively to the cloud API rather than making the whole controller cloud-dependent. `nadavbau/narwal-integration` documents Narwal REST authentication and MQTT5/TLS and is useful as a cloud-protocol reference, although its hardware focus has been Freo X Ultra rather than Flow AX12. citeturn27view10

The answers to the requested decision questions are:

| Question | Current answer |
|---|---|
| Can Flow be controlled entirely locally? | **[C] Yes, after it is already provisioned onto Wi-Fi.** Core control, state, rooms and maps work over LAN. The open-source local controller itself uses no Narwal account. A completely cloud-free factory-reset-to-Wi-Fi provisioning path has not been established. citeturn18view0 |
| Which operations work without cloud? | **[C]** Start, pause, resume, stop/cancel, return, locate, whole-home clean, room clean, cleaning parameters, map retrieval, robot position, several dock tasks, status/telemetry and debug images. citeturn18view0turn25view4turn27view6 |
| Ports? | **[C]** AX12 local control is TCP/9002 WebSocket. mDNS discovery uses `_narwal_sweeper._tcp.local.`. No second Flow-specific control port is established. citeturn18view0 |
| Discovery? | **[C]** mDNS/DNS-SD plus DHCP-hostname fallback; manual IP also works. citeturn18view0 |
| Protocol? | **[C]** WebSocket binary frames containing a proprietary Narwal envelope plus protobuf payloads. citeturn21view5turn21view6 |
| WebSocket? | **[C] Yes**, `ws://IP:9002`. citeturn21view1 |
| Protobuf? | **[C] Yes.** Current client uses schema-less protobuf decoding plus reconstructed message builders rather than relying on one authoritative published `.proto` set. citeturn21view1turn19view2 |
| Authentication required locally? | **[C] No application-level authentication has been found on AX12's port 9002.** citeturn21view1 |
| Credentials? | **[C] None for normal Flow LAN access.** Product key/device ID identify the addressable topic but are not shown to function as secrets. The device ID can be discovered from the robot. citeturn21view1 |
| Can custom software connect directly? | **[C] Yes.** The integration's own pure client does exactly that. citeturn24view0turn20view0 |
| Reusable Python library? | **[S] Yes at source level:** `narwal_client/` is an importable pure-Python client. I found no evidence that it is maintained as a separately stable public PyPI API. citeturn24view0turn19view2 |
| HA coupling? | **[C] Low in the protocol layer.** `custom_components/narwal/*` is HA-specific; the root `narwal_client/*` contains transport/protocol/models. citeturn24view0turn20view2turn20view3 |
| Rooms retrievable/cleanable? | **[C] Yes.** Room IDs/names come from `map/get_map`; ordered room cleaning is confirmed. citeturn22view6turn27view8 |
| Arbitrary zones? | **[C for rectangles in sytchi fork]** One or more rectangular world-coordinate zones work. Arbitrary polygons are not established. citeturn27view9 |
| Maps local? | **[C] Yes**, including `map/get_map`, reduced maps, editable representation and live `display_map`. citeturn27view6 |
| Robot position local? | **[C] Yes**, from `map/display_map`. |
| No-go zones read/write? | **[U]** The editable-map protocol gives a promising reverse-engineering surface, but the current Flow integrations do not establish reliable local read/write APIs for restricted areas. |
| Dock controllable? | **[C] Yes through the robot's WebSocket**, not through a separately discovered dock network endpoint. Wash/dry/dust operations are implemented. citeturn25view4turn18view0 |
| Camera image retrieval? | **[S] Partially.** `developer/take_picture` returns a frame and `developer/get_robot_debug_image` provides clear debug PNG data; object-detection imagery is not locally available through `get_vision_image`. citeturn27view6turn27view7 |
| Camera images decoded? | **[R/S] Not the normal `take_picture` camera frame.** Project work reports an encrypted payload without a recovered key. Debug images are different and already cleartext. Live-video protocol remains unresolved. |
| Two controllers? | **[C] Same-source-IP duplicate connections are not safe**; server behavior closes an older connection when another appears from that source. Different-source-IP concurrency is less well established. The HA README therefore recommends closing the app to avoid conflicts. citeturn18view0 |
| Official app conflict? | **[R/S] It can.** Avoid designing around multiple concurrent clients; a single daemon is more robust. citeturn18view0 |
| Deep sleep? | **[C]** Broadcasts can disappear; connection/wake logic must handle this. citeturn21view1 |
| Wake mechanism? | **[S/C implementation]** Send app-open notification, subscription, heartbeat and on-demand base-status query; retry/reconnect. Very deep sleep remains unreliable. citeturn21view1turn21view4 |
| Cross-VLAN? | **[R] Not directly on at least one tested deployment.** The robot received SYNs from a foreign subnet but emitted no SYN-ACK. citeturn27view3 |
| SNAT? | **[R] Required on that tested routed/VLAN deployment**, because the robot appeared to filter foreign-subnet source addresses. It is unnecessary when the client is already on the robot subnet and should not be generalized to every firmware without testing. citeturn18view0turn27view3 |
| HA actions/entities? | **[C]** Native vacuum control, `vacuum.clean_area`, settings entities, state sensors, binary sensors, map camera(s), dock controls and per-room profiles. citeturn18view0turn22view6 |
| Known Flow firmware? | **[C]** AX12 `v01.08.03.07` is strongly validated. Behavior changes around `v01.07.22+`; protocol captures also exist from `v01.09.05.01`. citeturn18view0turn27view1 |
| Firmware breakages? | **[C/R]** `v01.07.22+` changed whole-house-start assumptions by requiring a loaded map. The largest room-clean failure was an integration/protocol-understanding bug rather than a firmware regression. citeturn18view0turn27view1 |
| Smallest independent controller? | **[C/S]** IP discovery + one WebSocket connection + Narwal frame parser/builder + identity/topic handling + subscription + serialized command-response queue + state parser. |
| Best foundation files? | `narwal_client/client.py`, `protocol.py`, `models.py`, `const.py`, plus `docs/PROTOCOL.md`. citeturn20view0turn20view1turn24view2 |
| Important unknowns? | Restricted-area writes, full map-editor schema, live camera/video and camera crypto, complete error/status enums, some consumable semantics, exact multi-client limits, completely local initial provisioning, and firmware-wide VLAN behavior. citeturn27view5 |

## Device identity, model compatibility, and open-source ecosystem

The commercial **Narwal Flow corresponds to the AX12 family** in the best current local integration. A known AX12 product key is `QoEsI5qYXO`. The fact that product keys, internal hardware model names, cloud identities and commercial names do not form a simple one-to-one mapping is visible elsewhere in the ecosystem: CX7 can present a J5 cloud identity, AX26 appears under Z10 Pro/Turbo naming, and Flow 2 has multiple observed product keys. citeturn18view0

The important engineering rule is therefore: **detect protocol family, not marketing name**. Port 9002 plus the Narwal mDNS service is substantially stronger evidence of compatibility than “uses the Narwal app.” citeturn18view0

**Model/protocol compatibility matrix**

| Commercial model | Internal/product identity | Known firmware evidence | Protocol compatibility |
|---|---|---|---|
| Narwal Flow | **AX12**, product key `QoEsI5qYXO` | `v01.08.03.07` confirmed room cleaning; behavior documented on `v01.07.22+`; later captures around `v01.09.05.01` | **[C] Local WebSocket 9002; primary development target.** citeturn18view0turn27view1 |
| “Narwal Flow compact version” | Internal ID and product key **unknown** | `01.06.22.17` in one report | **[R] TCP 9002 closed on that unit. Do not assume standard AX12 compatibility.** citeturn27view0 |
| Narwal Flow 2 | Product keys `QxMSPG6VSO`, `iSuVlI1If2`, `mkbqaprvrb`; internal model not established in reviewed source | Several community devices | **[C/S] Current mainline marks working; room-clean fix shared with AX12 family.** citeturn18view0 |
| Freo Z10 Ultra | CX4 | Community reports | **[S] 9002 family, working.** citeturn18view0 |
| Freo Z10 Pro / Turbo | AX26 | `v01.02.00.15` | **[C] 9002 family; room cleaning hardware-tested.** citeturn18view0 |
| Freo X10 Pro | AX15 | Community tested | **[S] 9002 family.** citeturn18view0 |
| Freo Z Ultra | CX7; tested cloud identity J5; product key `hEA7OEshlx` | `v01.13.11.02` | **[C on tested variant] 9002 works, but device ID must be supplied and broadcasts are absent.** citeturn18view0 |
| Freo Z Ultra alternate identity | CX7-like; key `BYWBPqSxeC` | `1.12.10.02` reported | **[R/U] Local addressed commands not universally confirmed.** citeturn18view0 |
| Freo Z10 plain | Distinct from Pro/Ultra | Current reports | **[R] advertises Narwal mDNS but 9002 refuses connections.** citeturn18view0 |
| Freo X Ultra | AX18/AX19 | Multiple reports | **[C] Not this protocol: ZMTP/ZeroMQ on 6789 plus cloud/Tuya architecture.** citeturn18view0 |
| Freo X Plus | — | — | **[S] cloud-only in current integration knowledge.** citeturn18view0 |
| J1 / T10 | related international hardware | Packet capture/full port scan referenced by project | **[R/S] no 9002; app-cloud architecture.** citeturn18view0 |
| J4 | — | — | **[S] Tuya/cloud-oriented.** citeturn18view0 |
| Narwal JX | distinct product key | community test | **[R] 9002 connects and map works; broader commands not comprehensively tested.** citeturn18view0 |
| Freo 20 | product key `fjhpiem4ba` | `v01.00.35.03`, `v01.00.36.11` | **[R/S] maps, current room, cleaning area, dock state verified locally.** citeturn18view0 |

The “Flow Compact” question therefore has a concrete but limited answer: **one self-identified Compact unit is demonstrably not drop-in compatible with the standard Flow integration because nothing was listening on 9002**. That could be a different hardware platform, regional firmware, or merely a product variant whose local service is disabled; current public evidence does not distinguish those possibilities. citeturn27view0

The ecosystem has three repositories that matter materially.

| Repository | Maintainer | Flow support | Local | Map | Rooms | Zones | Current relevance | License |
|---|---|---:|---:|---:|---:|---:|---|---|
| [`sjmotew/NarwalIntegration`](https://github.com/sjmotew/NarwalIntegration) | `sjmotew` + contributors | **AX12 hardware-tested** | Yes | Yes | Yes | Mainline room support | **Best general AX12 foundation; v1.0.10 released Sep. 14, 2026** | MIT citeturn18view0turn19view3 |
| [`sytchi/NarwalIntegration`](https://github.com/sytchi/NarwalIntegration) | `sytchi` | **Flow AX12 tested, notably v01.08.03.x** | Yes | Rich HD map | Yes | **Yes, multi-rectangle** | Active fork, especially valuable for zone protocol | MIT citeturn27view9 |
| [`nadavbau/narwal-integration`](https://github.com/nadavbau/narwal-integration) | `nadavbau` | Flow not its principal validated target | **Cloud-oriented** | Cloud parsing/rendering | protocol support varies | not the reason to choose it | Best current Narwal REST/MQTT5 cloud reference; WIP | MIT; cloud client architecture documented citeturn27view10 |

The sjmotew repository is notably more than a Home Assistant wrapper. The root contains:

```text
narwal_client/
    __init__.py
    client.py
    const.py
    models.py
    protocol.py
```

while Home Assistant-facing code lives separately under:

```text
custom_components/narwal/
```

The package publicly exports `NarwalClient`, state/model classes, enums and the low-level `build_frame`/`parse_frame` functions. This is already essentially the extraction boundary one would design for a standalone library. citeturn24view0

Its project metadata declares Python 3.12+ and:

```text
websockets >= 12,<14
protobuf >= 4.25,<6
bbpb >= 1.4
Pillow >= 9
```

and the repository is MIT-licensed, allowing use, modification, redistribution and sublicensing provided the copyright/license notice is preserved. citeturn19view2turn19view3

`bbpb` is significant because much of the reverse engineering deliberately avoids pretending that an authoritative schema exists. Received payloads are frequently decoded schema-less through the `blackboxprotobuf` API while known outbound messages are encoded from reconstructed structures. `NarwalClient._decode_protobuf()` shows that directly. citeturn21view1

**Git-history archaeology is essential here.** Issue #66 provides an unusually useful history of parallel research. `jgus` produced a series of APK/protobuf-evidenced PRs, `Sean-StarLabs` independently built and hardware-tested related changes on two Flow 2 units, `StratoGh0st99` contributed Flow 2 discovery/live-state work, and `sytchi` independently reached the correct room/zone-clean model on Flow 1. The maintainer deliberately consolidated these instead of blindly merging a multi-thousand-line fork. citeturn27view1

Several prior “facts” were later proved wrong:

| Earlier belief | What evidence showed |
|---|---|
| `clean/plan/start` was a room-cleaning API | False. It is a stored-plan runner. `clean/start_clean` is the actual structured clean command. citeturn27view1turn27view7 |
| Room naming varied by model | False. The underlying app function takes only the room enum; the project's table was shifted. citeturn27view1turn27view8 |
| Cleaning area was correctly decoded | False in older releases; an unrelated station timer field was being interpreted as area. citeturn27view1 |
| Several `robot_base_status` fields were battery/session/timestamp values | Later field audits identified them as different station/account fields. citeturn27view1 |
| Empty consumable arrays meant “nothing needs replacement” | Decoder mishandled packed repeated varints and could silently report healthy consumables. citeturn27view5 |

That history is exactly why a new controller should preserve raw packets and unknown fields rather than immediately mapping every integer to a confident semantic name.

## LAN discovery, transport, authentication, and VLAN behavior

A standard Flow AX12 advertises the DNS-SD service:

```text
_narwal_sweeper._tcp.local.
```

with an instance resembling:

```text
_app_wss_server_<6hex>
```

and hostname:

```text
NARWAL_<6hex>.local.
```

on TCP port `9002`. The six hex digits correspond to the tail of the device ID. The HA integration additionally recognizes a lower-cased DHCP hostname pattern `narwal_*`. No reliable public documentation for meaningful TXT records was found. citeturn18view0

**Port/protocol table**

| Port | Protocol | Purpose | Local/cloud | Evidence |
|---:|---|---|---|---|
| 9002/TCP | WebSocket over clear TCP | Flow-family local control, state, maps | Local | **[C] AX12.** citeturn18view0turn21view1 |
| 5353/UDP | mDNS/DNS-SD multicast | Discovery of `_narwal_sweeper._tcp` | Local | **[C service advertisement; standard mDNS transport].** citeturn18view0 |
| 6789/TCP | ZMTP/ZeroMQ | Freo X Ultra family, **not AX12** | Local portion of different architecture | **[C/S]** citeturn18view0 |
| 8883/TCP | MQTT5 over TLS | Narwal cloud messaging in cloud integration | Cloud | **[S] reverse-engineered cloud implementation.** citeturn27view10 |
| HTTPS/443 | HTTPS REST | Narwal authentication/account APIs | Cloud | **[S] reverse-engineered client.** citeturn27view10 |

No credible evidence was found for SSDP/UPnP discovery, a proprietary UDP broadcast protocol, a stable MAC OUI that should be used for device identification, or a second Flow control port. Those remain **[U]**, and implementing discovery by MAC vendor would be less robust than the actual DNS-SD service.

Useful on-network tests are:

```bash
# Linux / Avahi
avahi-browse -rt _narwal_sweeper._tcp

# macOS
dns-sd -B _narwal_sweeper._tcp local.
dns-sd -L _app_wss_server_ABCDEF _narwal_sweeper._tcp local.

# Verify that this specific model exposes the Flow-family API
nmap -Pn -sT -p 9002 ROBOT_IP

# Observe discovery plus the local socket
sudo tcpdump -ni any \
  'udp port 5353 or (host ROBOT_IP and tcp port 9002)'

# Similar tshark filter
sudo tshark -i any \
  -f 'udp port 5353 or (host ROBOT_IP and tcp port 9002)'
```

The project itself recommends `nmap -p 9002 <robot-ip>` as the first compatibility test for an unrecognized model. citeturn18view0turn27view5

A minimal standalone DNS-SD probe can be as simple as:

```python
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf


SERVICE = "_narwal_sweeper._tcp.local."


class Listener(ServiceListener):
    def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        info = zc.get_service_info(service_type, name)
        if info is None:
            return

        addresses = info.parsed_addresses()
        print(
            {
                "instance": name,
                "host": info.server,
                "port": info.port,
                "addresses": addresses,
                "txt": info.properties,
            }
        )

    def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        self.add_service(zc, service_type, name)

    def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        pass


zc = Zeroconf()
browser = ServiceBrowser(zc, SERVICE, Listener())

try:
    input("Press Enter to stop\n")
finally:
    zc.close()
```

The service's behavior during the robot's deepest sleep state has not been cleanly characterized. The client code clearly distinguishes a still-connected WebSocket from the robot's application processor actually publishing useful state, but that does not prove whether the Wi-Fi module continues answering mDNS indefinitely. Treat sleep-time DNS-SD presence as **[U]** and persist the last known IP/device identity rather than requiring rediscovery on every startup. citeturn21view1

**WebSocket transport.** Current code opens:

```text
ws://<robot-ip>:9002
```

with no TLS. The sjmotew client calls `websockets.connect(self.url, ping_interval=30, ping_timeout=10)` and supplies no special authentication headers or subprotocol in that path. Thus the implemented connection is a normal HTTP WebSocket upgrade to the default path, with ordinary WebSocket ping/pong in addition to Narwal's own application-level wake/subscription traffic. citeturn21view1

There is no certificate to validate because this is `ws://`, not `wss://`.

After the WebSocket layer, each binary message uses a small Narwal envelope. The current parser/builder reconstructs it approximately as:

```text
offset  size     meaning
------  -------  ---------------------------------------
0       1        0x01
1       1        topic_length + 2
2       1        protobuf field tag:
                  0x22 => field 4, request/broadcast
                  0x2a => field 5, command response
3       1        topic UTF-8 byte length
4       N        topic string
4 + N   rest     protobuf payload
```

The `build_frame()` and `parse_frame()` implementations live in `narwal_client/protocol.py`. citeturn21view5turn21view6

A successful empty-topic command response has been observed in this shape:

```text
01 02 2a 00 08 01
```

where the protobuf data corresponds to result code `1`, success. The critical architectural consequence is that **responses cannot always be correlated by response topic**. The client therefore serializes command transactions with a command lock and routes field-5 frames to a dedicated queue. A new implementation should copy this design rather than permit multiple coroutines to issue commands concurrently and guess which reply belongs to which request. citeturn22view3

The practical connection sequence reconstructed from the current client is:

```text
Controller                                         Flow AX12
    |                                                  |
    |-- DNS-SD _narwal_sweeper._tcp ----------------->|
    |<-- instance / hostname / TCP 9002 ---------------|
    |                                                  |
    |-- TCP 9002 ------------------------------------->|
    |-- HTTP Upgrade: WebSocket ---------------------->|
    |<------------- 101 / WebSocket -------------------|
    |                                                  |
    |-- common/notify_app_event {1:1} ---------------->|
    |-- common/active_robot_publish {subscriptions} -->|
    |-- common/active_robot_publish {duration:600} --->|
    |-- status/app_status_heartbeat {1:1} ------------>|
    |-- status/get_device_base_status ---------------->|
    |                                                  |
    |<-- status/robot_base_status broadcasts ----------|
    |<-- status/working_status broadcasts -------------|
    |<-- map/display_map broadcasts -------------------|
    |                                                  |
    |-- command topic + protobuf payload ------------->|
    |<-- field-5 result frame -------------------------|
    |<-- later asynchronous state broadcasts ----------|
    |                                                  |
    |-- renew subscriptions before 600 s expiry ------>|
    |-- WS ping + app-level keepalive ---------------->|
```

The source uses a 600-second subscription duration and renews before expiry; current code has an eight-minute renewal interval. This was not theoretical: an older integration froze mid-clean because `working_status` and `display_map` stopped when the ten-minute subscription expired even though the WebSocket itself remained open. citeturn18view0turn21view1

**Authentication is almost conspicuous by its absence.** For AX12 there is no login, account token, session token, HMAC, challenge-response, TLS client certificate, local shared key or cloud-fetched secret in the implemented local path. `discover_device_id()` explicitly documents that the server processes the relevant command even while the device ID is not yet known and can return the real device ID; broadcasts also reveal the full addressed topic. citeturn21view1

The full topic form is:

```text
/<product_key>/<device_id>/<category>/<message>
```

The product key and device ID are routing identity, not demonstrated cryptographic credentials.

That means the answer to “where should my custom controller obtain credentials?” for a standard Flow is simply: **it should not need account credentials at all**. Discover the robot IP, determine product/device identity, and communicate directly.

A CX7 variant is a different case: it does not broadcast the identity needed for addressing, so the HA project asks the user for its 32-character cloud-assigned Device ID. The README documents both an account endpoint and MQTT capture as possible sources. That exception should not be generalized back to AX12. citeturn18view0

**Sleep/wake behavior** is more involved than the TCP/WebSocket handshake. The current client's wake burst contains:

```text
common/notify_app_event
common/active_robot_publish   # full topic subscription, 600 s
common/active_robot_publish   # simple duration variant
status/app_status_heartbeat
status/get_device_base_status
```

The last request is intentionally active: comments in the client state that passive subscription traffic can wake the network/WebSocket side without fully bringing the application processor into a command-ready state. The client sends the burst immediately after reconnect, retries wake attempts, and can use a fresh TCP connection as a further escalation. citeturn21view1turn21view4

Deep sleep is nevertheless explicitly listed as unreliable. Opening the official Narwal app can sometimes wake the robot when the independent integration fails to do so. Thus there is no known guaranteed LAN wake primitive equivalent to Wake-on-LAN. citeturn18view0

**VLAN behavior deserves special attention.** In issue #81, a cross-VLAN user captured the connection at the router's IoT interface. The TCP SYN reached the robot, but the robot emitted no SYN-ACK for the foreign-subnet source. The same robot demonstrably had a functioning default route for its cloud connections. That makes “missing return route” a poor explanation for that particular capture and strongly suggests source-subnet filtering. Source NAT to an address on the IoT subnet restored operation. citeturn18view0turn27view3

This is still a hardware/firmware report rather than a vendor specification, so the deployment rule should be:

```text
Main LAN
     |
Home Assistant / narwal-daemon
     |
     | routed TCP 9002
     v
Firewall/router
     |
     | SNAT to IoT-gateway address if the robot
     | refuses foreign-subnet source addresses
     v
IoT VLAN
     |
Narwal Flow
```

Minimum rules for a manually configured robot:

```text
Controller -> Flow_IP : TCP/9002       allow
Flow_IP -> Internet                    policy-dependent
Controller <-> mDNS reflector : UDP/5353   only if auto-discovery is desired
```

An example `nftables` SNAT rule, using placeholders deliberately, is:

```nft
table ip nat {
    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept;

        ip saddr HA_IP \
        ip daddr FLOW_IP \
        tcp dport 9002 \
        snat to IOT_ROUTER_IP
    }
}
```

Equivalent OpenWrt/pfSense behavior is “source-NAT HA-to-Flow TCP/9002 to the router's IoT-interface address.” An Avahi/mDNS reflector is additionally needed only if you want DNS-SD discovery to cross VLAN boundaries; a fixed IP bypasses that part. The tested issue showed that successful reflected mDNS does **not** imply unicast port 9002 will subsequently accept the foreign-subnet source. citeturn18view0turn27view3

One subtle consequence: if several clients are SNATed to the **same** IoT-router address, the robot sees them as the same source IP. Given the same-source connection replacement behavior, a single centralized daemon becomes even more attractive.

## Binary protocol, commands, state, rooms, maps, dock, camera, cloud, and APK findings

Current Flow work uses Protocol Buffers, but it is better described as a **partially reconstructed protobuf protocol** than as a complete schema. The code carries logical structures discovered from captures and APK analysis while `blackboxprotobuf`/`bbpb` handles unknown messages. That distinction matters because several bugs in this ecosystem were caused by assigning semantics too early to unknown fields. citeturn21view1turn27view5

The most important reconstructed cleaning structure is conceptually:

```text
CleanTask
  field 1: map_id
  field 2: repeated CleanItem
      field 1: ZoneOption
          field 1: zone type
          field 2: zone/room id for room cleaning
      field 2: CleanParam
      field 3: order
  field 3: TaskOption
  field 5: task_type
```

For room jobs, `ZoneOption.type == 1`; reverse-engineering work identifies type `2` with free-zone cleaning. `order` is one-based. The `map_id` must be the actual active map ID returned by `map/get_map`, not a constant such as `1`. Current research found that a wrong map ID can cause the clean to abort almost immediately. citeturn27view1turn27view8

The complete `CleanParam` field numbering should **not** be invented. Known parameters include cleaning/work mode, suction/fan, water/mop humidity, mop pressure/strength, repeat/pass count and routing/coverage precision. A later app-vs-builder capture identified protobuf tag 8 as a coverage precision/routing choice in that capture set, but this is not enough evidence to publish an imaginary complete `.proto`.

One very useful raw comparison from the protocol research showed a generated payload versus the official app payload:

```text
generated:
0a1c080112140a0408011003120a0804100418012003380318011a002804

app:
0a1e080112160a0408011003120c08041004180120033803400218011a002804
```

The important lesson is not to cargo-cult these complete byte strings; it is that controlled app captures can reveal a single protobuf field difference much more reliably than guessing based on command success.

**Command matrix**

All topic names below are suffixes of `/<product_key>/<device_id>/`.

| Feature | Protocol topic | Parameters / semantics | Flow tested | HA support |
|---|---|---|---|---|
| Device identity | `common/get_device_info` | Returns product key, device ID, firmware | **[C]** | Used internally |
| Discover capabilities | `common/get_feature_list` | Feature list/flags; semantics only partly mapped | **[S]** | Internal |
| Locate | `common/yell` | Robot announces location | **[C]** | `vacuum.locate` |
| Pause | `task/pause` | Current task | **[C]** | `vacuum.pause` |
| Resume | `task/resume` | Current paused task | **[C]** | `vacuum.start`/resume logic |
| Stop/end | `task/force_end` / task cancellation variants | Terminates task | **[C/S]** | Vacuum stop |
| Return to dock | `supply/recall` | Recall robot to base | **[C]** | `vacuum.return_to_base` |
| Whole-house / structured cleaning | `clean/start_clean` | `CleanTask` using current map | **[C]** | Vacuum start |
| Stored Narwal plan | `clean/plan/start` | Runs app-saved plan; does **not** consume arbitrary room payload | **[C]** | Deliberately not used for new room jobs |
| “Easy clean” | `clean/easy_clean/start` | Present/observed; semantics less completely documented | **[S]** | Not primary UI |
| Room cleaning | `clean/start_clean` | map ID + room `CleanItem`s + order + parameters | **[C] AX12** | Native `vacuum.clean_area` |
| Rectangular zones | `clean/start_clean` / zone-type payload | World-coordinate free zones in sytchi implementation | **[C in sytchi AX12]** | `narwal.clean_zone` in sytchi fork |
| Fan/suction | `clean/set_fan_level` | Current/live or pending-clean semantics depend on state | **[C]** | `vacuum.set_fan_speed` |
| Mop humidity/water | `clean/set_mop_humidity` | Humidity setting | **[C/S]** | Settings entity |
| Current clean task | `clean/current_clean_task/get` | Excellent reverse-engineering probe for current params | **[C]** | Internal |
| Wash mop | `supply/wash_mop` | Dock task | **[C/S]** | Dock control |
| Dry mop | `supply/dry_mop` | Dock task | **[C/S]** | Dock control |
| Empty/dust gather | `supply/dust_gathering` | Station dust collection | **[C/S]** | Dock control |
| Map | `map/get_map` | Full active map | **[C]** | Map camera/internal |
| Saved maps | `map/get_all_reduced_maps` | Reduced representations of saved maps | **[S]** | Main integration exposes one active map |
| Editable map | `map/get_editable_map` | Editor-oriented representation | **[S] read** | Not exposed as editor |
| Live map/state | `map/display_map` | Push position/path/overlay information | **[C]** | Live map |
| Consumable attention | `consumable/get_consumable_info` | Maintenance/replacement lists | **[C/S]** | Sensors/alerts |
| Reset consumable | `consumable/reset_consumable_info` | Known topic; user-facing maturity limited | **[S] topic** | Not a core recommended operation |
| Schedules | `schedule/clean_schedule/get` | Known topic; underexplored | **[S topic]** | Not comprehensive |
| Config | `config/get`, `config/set` | Generic config protocol | **[S topic]** | Selected settings only |
| Volume | `config/volume/set` | Known topic | **[S]** | Not core |
| Camera single frame | `developer/take_picture` | Returns a camera payload | **[S]** | Not a decoded camera entity |
| Debug imagery | `developer/get_robot_debug_image` | Carpet/planning debug PNGs | **[C/S]** | Carpet/debug camera |
| LED | `developer/led_control` | Robot LED command | **[S]** | Limited |
| Ping | `developer/ping` | Application-level ping | **[C]** | Internal |
| Vision/object image | `get_vision_image` | Returns `NOT_APPLICABLE` locally | **[C] local limitation** | No |
| Dynamic-map topic | `get_dynamic_map` | Local request times out | **[C/S]** | No |

The project protocol document enumerates these families and marks the subset actually exercised by the integration. citeturn25view4turn27view6turn27view7

The `clean/plan/start` versus `clean/start_clean` issue deserves special emphasis because it is the best example of why “command returned success” does not prove that your payload had meaning. The old implementation repeatedly changed the room payload and saw `SUCCESS`; the robot was simply ignoring it and running the saved plan. Independent contributors eventually compared APK definitions and actual behavior and replaced the topic. citeturn27view1turn27view7

For new code, the room-clean procedure should be:

```text
1. Wake robot.
2. Fetch map/get_map.
3. Read current map_id.
4. Validate requested room IDs against map field 2.12.
5. Build CleanTask.
6. Preserve caller's room order in CleanItem.order.
7. Send clean/start_clean.
8. Require a successful command result.
9. Also wait for asynchronous working_status/display_map evidence.
10. If command succeeds but state never transitions, treat that as failure/timeout.
```

That last distinction would have prevented several historical false-positive “fixes.”

The robot's result-code layer includes `1 = SUCCESS`; `2` is used as `NOT_APPLICABLE`; `3` is associated with conflict; code `4` has been seen in newer clean-start behavior as “not ready.” Whole-house/structured `clean/start_clean` may reject an off-dock start with `NOT_READY`, so a robust controller must not equate a connected idle robot with “clean may start now.” citeturn18view0

**State/telemetry matrix**

The strongest current AX12 decoding is:

| Field | Protocol field | Meaning | Unit / notes |
|---|---|---|---|
| Errors | `robot_base_status.1` | Error-code list | repeated values |
| Battery | `robot_base_status.2` | Battery level | `%`, float-like |
| Task/state container | `robot_base_status.3` | Nested working/task state | see below |
| Bound account | `robot_base_status.13` | Account UUID-like value | identifier; redact from debug exports |
| Dust box | `.20` | Dust-box state | enum-like |
| Dust bag | `.21` | Dust-bag state | not emitted on every AX12 firmware |
| Clean water | `.23` | Clean-water state | enum-like |
| Dirty/sewage water | `.24` | Dirty-water state | enum-like |
| Device status list | `.25` | Device-status codes | partially mapped |
| Active fan | `.26` | Fan setting | active-state field |
| Active mop humidity | `.29` | Mop humidity | active-state field |
| Station bag health | `.35` | Station bag health | `%` where emitted; absent on some AX12 firmware |
| Station bag reset time | `.36` | Reset timestamp | Unix-seconds interpretation not fully validated |
| Unknown | `.38` | Observed numeric value | semantics unresolved |
| Detergent remain | `.41` | Heavy-detergent remaining | `%` interpretation remains less strongly validated |
| Charging | `.47` | Charging state | enum-like |
| Progress | `working_status.1` | Cleaning progress | `0..1` |
| Covered area | `working_status.2` | Area cleaned | square meters |
| Elapsed | `working_status.3` | Elapsed task time | seconds |
| Remaining | `working_status.4` | Remaining time | seconds |
| Current room | `working_status.6` | Current room ID | Narwal map room ID |

Several of those mappings were corrected through field audits after older releases confidently assigned the wrong semantics. citeturn27view1turn24view2

The empirically useful working-state values in current protocol notes include:

| Numeric value | Current interpretation | Confidence |
|---:|---|---|
| 1 | Standby | **[C/S]** |
| 2 | Docked variant on newer firmware | **[R/S]** |
| 4 | Cleaning | **[C]** |
| 5 | Alternate/stuck-cleaning condition observed | **[R]** |
| 7 | Remapping | **[R/S]** |
| 10 | Docked | **[C]** |
| 14 | Charged | **[R/S]** |
| 19 | Task-completed transition | **[R/S]** |

A complete authoritative `WorkingStatus` enum has **not** been recovered publicly. The protocol documentation explicitly notes that values have been learned one hardware report at a time and still recommends obtaining the full enum from APK/protobuf metadata. citeturn27view5

The nested base-status task object also has useful booleans/substates for paused, returning and dock state. An independent implementation should retain the raw state number alongside its friendly interpretation so an unknown firmware value does not collapse into an incorrect `"idle"`.

**Map protocol.** Local map access is one of the strongest parts of the reverse engineering. `map/get_map` returns the active full map; current protocol notes describe responses around tens of kilobytes, while `map/get_all_reduced_maps` can return a much larger representation of all saved maps. `map/get_editable_map` exposes an editor-oriented representation but has not matured into local editing support. citeturn27view6

Important `get_map` subfields include:

| `map/get_map` field under response field 2 | Meaning |
|---:|---|
| `1` | active `map_id` |
| `3` | resolution |
| `4`, `5` | width, height |
| `6.1`, `6.3` | coordinate-origin terms |
| `8` | dock pose |
| `11` | door/room-boundary relationships |
| `12` | rooms |
| `13` | historical trajectory data |
| `17` | compressed floor-map data |
| `26` | room-boundary polygons/geometry |
| `32` | furniture/map annotations |
| `33` | map area |
| `34` | map-creation timestamp |

`MapData.from_response()` in `narwal_client/models.py` directly parses the active map ID, dimensions, rooms, compressed map, origins, dock coordinates and furniture/obstacle annotations. citeturn24view2

One important warning: do not assume every binary blob uses one compression wrapper simply because one capture did. A robust map decoder should inspect magic bytes and preserve raw field 17 when decompression fails. The current model code already retains a `raw` dictionary, which is the correct reverse-engineering design. citeturn24view2

`map/display_map` is the live-update side of the protocol. Reverse-engineering has identified robot X/Y and heading, rolling trajectory streams, dock reference data, a cleaned-area overlay, timestamp and active-room information. The project's state model merges these broadcasts into `MapDisplayData` and notifies the HA renderer. citeturn21view1

Coordinates are a trap. The protocol research specifically warns that `display_map`/dock-style positions use decimeter-scale world values while other map structures can use different units. Its documented rendering transform is:

```text
pixel = (value_dm * 10) / (resolution / 10) - origin
```

and the source explicitly cautions that mixing coordinate systems puts robot overlays in the wrong room. citeturn27view8

For a custom implementation, treat coordinate space as a type, not as a naked `float`. For example:

```python
@dataclass(frozen=True)
class WorldDm:
    x: float
    y: float

@dataclass(frozen=True)
class MapPixel:
    x: float
    y: float
```

That prevents the exact class of map/zone bugs that occur when all four values are represented as an untyped `list[float]`.

**Rooms.** `map/get_map` field `2.12` supplies:

```text
field 1  room_id
field 2  RoomType
field 3  UTF-8 user name
field 4  category (1 room, 2 utility/small space)
field 8  duplicate/instance index
```

The corrected RoomType mapping is:

```text
0  Room
1  Master bedroom
2  Secondary bedroom
3  Living room
4  Kitchen
5  Bathroom
6  Toilet
7  Balcony
8  Dining room
9  Closet
10 Corridor
11 Study
12 Kids' room
13 Entertainment room
14 Storage room
15 Others
```

This table was corrected by decompiling `MapEnginei18nConfiger.roomTypei18nKey(int)` and observing that it takes the enum but no model/product-key parameter, then resolves through shared localization resources. citeturn27view8turn27view1

The direct room-clean workflow is therefore fully understood at the architectural level:

```text
get_map
  ↓
MapData.rooms
  ↓
room_id + display_name
  ↓
CleanTask.items[]
      ZoneOption(type=room, zone_id=room_id)
      CleanParam(...)
      order
  ↓
clean/start_clean
```

Multiple rooms and explicit order work. The sjmotew mainline maps those segment IDs to HA Areas and sends the list in HA-specified order. citeturn18view0turn22view6

**Zone cleaning** is more mature in the sytchi fork than mainline sjmotew. Its current public service accepts one or more rectangles in **robot world/map-frame coordinates**:

```yaml
action: narwal.clean_zone
target:
  entity_id: vacuum.narwal_flow_vacuum
data:
  zone:
    - [-21, -23, 29, 29]
```

and the fork explicitly documents that negative coordinates are normal because this coordinate system is not map-image pixels. It also supports output from `xiaomi-vacuum-map-card` calibration and displays the requested rectangles on the HD map. citeturn27view9

The following should therefore be distinguished:

- **[C] multiple rectangular zones:** yes in the sytchi AX12 path. citeturn27view9
- **[U] arbitrary polygons:** no reliable implementation found.
- **[U] maximum rectangle count:** not reliably documented.
- **[C/S] map-coordinate dependency:** yes; use world/map frame, not rendered PNG pixels. citeturn27view9
- **[S] map ID required:** the same structured-clean machinery is map-specific.
- **[U] firmware-wide compatibility:** zone payload behavior has fewer independent firmware tests than room cleaning.

There has also been genuine disagreement over extra fields in zone-clean payloads. The sytchi work reported `NOT_APPLICABLE` without additional zone/task fields on Flow `v01.08.03.07`; subsequent mainline investigation found official-app captures in which an alleged mandatory ZoneOption field was absent. The correct conclusion is **not** “one fork is obviously wrong”; it is that the requirement may depend on payload shape/firmware, and a standalone implementation should preserve fixture captures for each supported firmware rather than bake the old hypothesis into its type system. Issue #66 records the exact uncertainty. citeturn27view1

**Map editing and restricted areas:** current public work is mainly read-oriented. There is evidence for `get_editable_map`, room geometry and map annotations, but no reliable local production implementation was found for writing room names, splitting/merging rooms, creating no-go/no-mop polygons, moving virtual walls or editing carpet regions. These should all be classified **[U] for write support** rather than inferred from the presence of an “editable” map request.

**Dock control** is transported over the robot's own addressed WebSocket topics. I found no evidence that the dock advertises its own IP API. The known local command set includes mop wash, mop dry and dust collection; newer HA mainline work also exposes additional station task controls where supported by the dock. citeturn25view4turn18view0

There is not yet equivalent evidence for every possible app maintenance operation. “Clean station,” automatic water refill, detergent maintenance and model-specific dock drying processes should therefore be implemented through feature detection rather than assumed universally available.

**Consumables** are another area where maintaining raw values is essential. `consumable/get_consumable_info` returns lists of maintenance/replacement item codes rather than a universally reliable “all accessories remaining percent” table. A historical parser bug treated packed protobuf varints incorrectly and silently turned non-empty attention lists into an apparently healthy state. citeturn27view5

Known maintenance-style codes include items such as dust box/filter, cleaning ribs, wheel/sensors and other washable modules; replacement lists include filter, mop, side brush, roller brush, detergent, bags and model-specific station components. Because the exact code set is model-dependent and continues to evolve, preserve unknown codes rather than dropping them.

No reliable local fields for robot temperature or Wi-Fi RSSI were established in the reviewed AX12 protocol. Those remain **[U]**.

**Camera protocol is currently incomplete.** Four interfaces must not be conflated:

| Interface | Current boundary |
|---|---|
| `developer/take_picture` | A single camera-frame response is obtainable locally. The project has not turned it into a decoded normal camera feed. citeturn27view6 |
| `developer/get_robot_debug_image` | Cleartext carpet/planning debug PNG-style imagery is obtainable and has been integrated as debugging/map imagery. citeturn27view6 |
| `get_vision_image` | Locally returns `NOT_APPLICABLE`; project analysis attributes the corresponding vision/object imagery to cloud processing. citeturn27view7 |
| Live camera/video | **[U]** No mature local live-video implementation was found. |

Project investigation describes the normal picture payload as encrypted and has not recovered the production key needed to turn it into a useful image. Public evidence is not yet strong enough to state a validated AES mode, key derivation or IV construction as fact. Therefore the correct current answer is:

```text
cipher family / encryption: partial evidence
exact key: unknown
key derivation: unknown
IV/nonces: unknown
successful decoded normal camera image: not established
live video: not reverse engineered
```

The most promising next step is to instrument the mobile application's image-decryption call site and capture the inputs to the crypto API, rather than trying arbitrary AES modes against the payload.

**Cloud protocol.** `nadavbau/narwal-integration` documents a completely different control path using HTTPS REST for account authentication and MQTT5/TLS for messaging. Its protocol reference currently lists regional hosts:

```text
US API:    us-app.narwaltech.com
US MQTT:   us-01.mqtt.narwaltech.com

IL API:    il-app.narwaltech.com
IL MQTT:   us-01.mqtt.narwaltech.com

EU API:    eu-app.narwaltech.com
EU MQTT:   eu-01.mqtt.narwaltech.com

CN API:    cn-app.narwaltech.com
CN MQTT:   cn-mqtt.narwaltech.com
```

The documented email login is:

```text
POST /user-authentication-server/v2/login/loginByEmail
```

with an email/password JSON body. A successful response contains an access JWT, refresh token and user UUID. Authenticated REST calls use an `Auth-Token` header rather than a Bearer `Authorization` header. Token refresh uses:

```text
POST /user-authentication-server/v1/token/refresh
```

with `refreshToken`. citeturn27view10

MQTT uses TLS port 8883, MQTT 5 semantics, user UUID/JWT authentication and topic paths containing product/device identity. This cloud implementation should be considered **strong reverse-engineered evidence, not an official Narwal API contract**, and its principal hardware testing has not been AX12. citeturn27view10

There is some evidence of multiple generations of cloud device-enumeration APIs. The nadav protocol reference describes device discovery through:

```text
GET /app-message-server/v1/device-message/listPage
```

while sjmotew documents `/user-device-platform-server/device-info/getDeviceInfoList` as a source for the 32-character device ID needed on CX7. Treat endpoint availability as region/app-version dependent. citeturn27view10turn18view0

For a Flow-centric project, cloud access is most justified for capabilities currently unavailable locally: cloud-managed scenes/shortcuts, portions of computer-vision imagery and potentially account/map functionality that has no established LAN write protocol. The local protocol notes specifically identify vision-image access and app scene/Alink functionality as cloud-side gaps. citeturn27view7

Cloud risks are straightforward: passwords, JWTs and refresh tokens become high-value secrets; endpoint/message schemas are unsupported and can change; rate limits are not publicly characterized; and the legal/terms-of-service status of automation against undocumented APIs should be evaluated against Narwal's current terms before deployment. No real user's credentials should ever appear in diagnostics.

**Android APK reverse engineering.** Public project archaeology proves that APK decompilation has already been useful. In particular, room types were corrected from `MapEnginei18nConfiger.roomTypei18nKey(int)` and shared `en-US.json`, and furniture metadata has been correlated against an APK `map_furniture.json` resource. citeturn27view8turn24view2

I did **not** find sufficiently reliable primary evidence to publish a package name as fact. Rather than guess, an engineer should identify the installed package from his own Android device:

```bash
adb shell pm list packages | grep -i narwal
adb shell pm path PACKAGE_NAME
adb pull /path/from/previous/command/base.apk
jadx -d narwal-jadx base.apk
```

Then search the resulting Java/Kotlin/resources/native strings with:

```bash
rg -n \
  '9002|_narwal_sweeper|app_wss_server|active_robot_publish|notify_app_event|\
clean/start_clean|clean/plan/start|current_clean_task|get_device_info|\
MapEnginei18nConfiger|roomTypei18nKey|map_furniture|take_picture|\
get_vision_image|get_dynamic_map|Auth-Token|mqtt|ResponseTopic|\
CorrelationData|Cipher\.getInstance|SecretKeySpec|IvParameterSpec|AES' \
  narwal-jadx/
```

Especially promising targets are:

```text
MapEnginei18nConfiger.roomTypei18nKey(int)
shared localization JSON
map_furniture.json
protobuf parseFrom()/toByteArray() call sites
clean/start_clean builders
active_robot_publish builders
developer/take_picture response consumer
get_vision_image consumer
javax.crypto.Cipher usage near image/camera code
OkHttp/WebSocket or native networking wrappers
Narwal cloud host constants
Alibaba/Alink scene code
```

For camera crypto, the important target is **not merely a string `"AES"`**. Find the function that receives the `take_picture` payload and trace dataflow into `Cipher.init(...)` or the native equivalent. Log algorithm, key bytes/handle, IV/nonce and transformed buffer length at that boundary.

## Home Assistant architecture and practical deployment

For a normal Flow AX12, `sjmotew/NarwalIntegration` is currently the strongest default HA implementation because it combines recent AX12 testing, native modern HA area cleaning, current protocol corrections and a reusable library boundary. v1.0.10 is the current release identified by the repository and includes an IPv6-discovery startup fix on top of earlier room/state work. citeturn18view0

The architecture is roughly:

```text
HA vacuum/sensor/camera/select/button/light entities
                   |
                   v
custom_components/narwal/vacuum.py
custom_components/narwal/coordinator.py
                   |
                   v
              NarwalClient
          narwal_client/client.py
                   |
          +--------+---------+
          |                  |
   protocol.py           models.py
 framing/topics       state/map decoding
          |                  |
          +--------+---------+
                   |
             WebSocket 9002
                   |
               Flow AX12
```

`custom_components/narwal/coordinator.py` defines `NarwalCoordinator`, while the protocol implementation is outside the HA layer. The vacuum platform maps HA operations onto that coordinator/client. citeturn21view8turn24view0

For native room cleaning, `vacuum.py` advertises `VacuumEntityFeature.CLEAN_AREA`, implements `async_get_segments()`, converts `RoomInfo` objects into HA Segment objects, and implements `async_clean_segments()`. Before dispatch it refreshes the map, validates every supplied room ID against the currently known map, obtains the selected clean settings and then hands the structured clean request to the client. citeturn22view6turn22view7

That makes the integration path concrete:

```text
vacuum.clean_area
      ↓
HA Area -> Segment mapping
      ↓
async_clean_segments()
      ↓
room IDs
      ↓
refresh get_map
      ↓
validate map ID / room IDs
      ↓
CleanTask
      ↓
clean/start_clean
```

**Home Assistant entity matrix**

Entity names are generated from the configured device name, so exact entity IDs vary. The platforms/capabilities do not.

| Entity/capability | Platform | Protocol source | Read/write |
|---|---|---|---|
| Main robot | `vacuum` | base/working status + task/clean/supply commands | R/W |
| Battery | vacuum/sensor state | `robot_base_status.2` | Read |
| Cleaning progress | vacuum attribute / sensor logic | `working_status.1` | Read |
| Cleaning area | sensor | `working_status.2` | Read |
| Cleaning time | sensor | `working_status.3` | Read |
| Current room | vacuum attribute | `working_status.6` | Read |
| Firmware | sensor | `common/get_device_info` | Read |
| Charging | sensor | `robot_base_status.47` | Read |
| Docked | binary sensor | task/base-status dock substate | Read |
| Clean-water state | binary/sensor | base status `.23` | Read |
| Dirty-water state | binary/sensor | base status `.24` | Read |
| Dust box/bag states | binary sensors | base status `.20/.21` | Read |
| Error | binary/sensor | base status `.1` | Read |
| Maintenance/replacement alerts | binary/sensor | `consumable/get_consumable_info` | Read |
| Clean mode | select | next `CleanParam` | R/W HA-side/pending |
| Water/humidity | select | `CleanParam` / `set_mop_humidity` | Write/pending |
| Mop strength | select | `CleanParam` | Write/pending |
| Pass count | number | `CleanParam` | Write/pending |
| Fan speed | vacuum fan-speed | `clean/set_fan_level` | **Write; current level is not reliably broadcast as an HA-readable setting** |
| Room selection/profiles | switch/select entities | per-room `CleanParam` builders | Write/pending |
| Floor map | camera | `map/get_map` + `map/display_map` | Read |
| Carpet/debug map | camera | `developer/get_robot_debug_image` | Read |
| Dock tasks | buttons/switch-style controls depending release/entity | `supply/*` local commands | Write |
| Dock ambient light | light/control entity | local station-control command | R/W where supported |

The integration README reports 28 entities on a Flow after the v1.0.2-era expansion, with newer releases additionally providing per-room profile controls that are disabled by default because a large map can otherwise produce hundreds of HA entities. citeturn18view0

Map rendering is fully local. The integration combines the persistent floor map with room labels, furniture/annotations, dock marker and Narwal's native live trajectory from `display_map`. A second debug/carpet image is available where supported. citeturn18view0turn24view2

**Installation path**

The repository's documented HACS route is a custom repository:

```text
HACS
  → Custom repositories
  → https://github.com/sjmotew/NarwalIntegration
  → category: Integration
  → download
  → restart Home Assistant
```

Manual installation is also possible by copying `custom_components/narwal/` into the HA configuration directory. citeturn18view0

Do not install the sjmotew local integration and `nadavbau/narwal-integration` simultaneously under the same HA instance: both historically use the `custom_components/narwal` integration domain/path, and the mainline README explicitly documents the HACS collision. citeturn18view0

**Discovery/pairing**

On the same LAN, HA should discover `_narwal_sweeper._tcp.local.` automatically. Otherwise add the integration manually and supply the robot IP/model. For AX12 there is no Narwal-account pairing dialog or local secret to enter. citeturn18view0

A DHCP reservation is advisable because it reduces reconnect/discovery complexity, although current discovery can update an existing entry when the address changes. citeturn18view0

**Room mapping and `vacuum.clean_area`.**

This requires Home Assistant 2026.3 or newer in the current implementation. HA cleans **Areas**, whereas Narwal exposes numeric map segments, so there is a one-time HA Area ↔ Narwal segment mapping in the vacuum entity's settings. Remapping the entire robot map can renumber segments and invalidate that mapping; the integration detects such changes and raises an HA repair issue. citeturn18view0turn22view6

The action payload currently expected by this integration is not the `areas:` example in the question. The documented form is:

```yaml
action:
  - action: vacuum.clean_area
    target:
      entity_id: vacuum.narwal_flow_vacuum
    data:
      cleaning_area_id:
        - kitchen
        - hallway
```

The values are **Home Assistant area IDs**, not `"Kitchen"` Narwal room-name strings. HA resolves those through the segment mapping, and the ordered list becomes the room-clean order. citeturn18view0

A complete clean-with-settings automation can therefore be:

```yaml
alias: Narwal kitchen then hallway
triggers:
  - trigger: time
    at: "09:30:00"

conditions:
  - condition: state
    entity_id: vacuum.narwal_flow_vacuum
    state: docked

actions:
  - action: select.select_option
    target:
      entity_id: select.narwal_flow_clean_mode
    data:
      option: Vacuum and mop

  - action: select.select_option
    target:
      entity_id: select.narwal_flow_mopping_humidity
    data:
      option: Slightly wet

  - action: select.select_option
    target:
      entity_id: select.narwal_flow_mop_strength
    data:
      option: High

  - action: number.set_value
    target:
      entity_id: number.narwal_flow_cleaning_passes
    data:
      value: 2

  - action: vacuum.set_fan_speed
    target:
      entity_id: vacuum.narwal_flow_vacuum
    data:
      fan_speed: Strong

  - action: vacuum.clean_area
    target:
      entity_id: vacuum.narwal_flow_vacuum
    data:
      cleaning_area_id:
        - kitchen
        - hallway

mode: single
```

That sequence mirrors the integration's model: pending clean settings are read when the job is constructed, so configure them **before** dispatching the clean. citeturn18view0

For arbitrary zones, the sytchi fork exposes its own service instead of relying solely on HA's room/area abstraction:

```yaml
action: narwal.clean_zone
target:
  entity_id: vacuum.narwal_flow_vacuum
data:
  zone:
    - [-21, -23, 29, 29]
```

Its v2 interface defines these as world coordinates rather than camera-image pixels. citeturn27view9

**Debug logging.** A useful HA starting point is:

```yaml
logger:
  default: info
  logs:
    custom_components.narwal: debug
    narwal_client: debug
```

The library itself uses module loggers via `logging.getLogger(__name__)`, and the client has explicit debug output for topics and decoded protobuf dumps. citeturn21view1turn24view2

Be careful with unrestricted protobuf dumps. `robot_base_status` can contain the bound account UUID, full message topics contain the device ID, and cloud diagnostics can contain much more sensitive JWT/account data. Safe debug exports should redact:

```text
email/password
Auth-Token/JWT
refresh token
account UUID
full device ID if publishing logs publicly
camera/image payloads
```

while retaining:

```text
short topic name
firmware
result code
numeric state code
map ID
room ID
field numbers
payload length
redacted/raw-hex slices necessary for protocol work
```

The protocol maintainer explicitly recommends preserving raw hex when investigating field interpretations because later semantic corrections can be applied to the original bytes, whereas a mistaken high-level summary permanently loses evidence. citeturn27view5

For updates, pin a known integration release in a reliability-sensitive installation, read release notes before changing versions, and keep a small acceptance suite that exercises connect, base status, map retrieval, one room clean, pause/resume and return-to-dock after both integration and robot-firmware updates.

Across VLANs, configure a fixed robot IP or an mDNS reflector for discovery, plus SNAT to the IoT-interface address if your unit exhibits the foreign-subnet behavior documented in issue #81. citeturn27view3

## Standalone controller, MQTT/REST bridge, and packet-capture architecture

The strongest finding for a non-HA implementation is that **you do not need to extract the client out of Home Assistant from scratch**. The sjmotew repository has already done most of that separation.

A sensible standalone project should look like:

```text
narwal_flow/
    discovery.py
    transport.py
    framing.py
    protocol/
        clean.py
        status.py
        map.py
        dock.py
        camera.py
    models.py
    state.py
    robot.py
    persistence.py
    compat.py
```

with responsibilities:

| Layer | Responsibility |
|---|---|
| `discovery.py` | DNS-SD, fixed-IP fallback, DHCP-name hints |
| `transport.py` | One WebSocket owner, reconnect, WS ping, send/receive task |
| `framing.py` | Narwal bytes 0–3 envelope, topic extraction, response detection |
| `protocol/*` | Hand-built known protobuf requests + schema-less decoding for unknown messages |
| `models.py` | Typed map/room/state/result structures |
| `state.py` | Merge `robot_base_status`, `working_status`, `display_map`; preserve unknown fields |
| `robot.py` | High-level semantic operations and allowed-state checks |
| `persistence.py` | product key, device ID, IP, last map ID, segment names, firmware |
| `compat.py` | model/product-key/firmware quirks rather than `if firmware` scattered through code |

That is very close to what the existing `narwal_client` already provides, so the practical engineering choice is to vendor or package that directory and refactor only after getting a hardware regression suite running. citeturn24view0turn20view0turn24view2

An ideal high-level API is reasonable:

```python
robot = await NarwalFlow.discover()
await robot.connect()

print(robot.state.battery)

await robot.clean_rooms(["Kitchen", "Hallway"])
await robot.pause()
await robot.return_to_dock()
```

but those names should be treated as **proposed public API**, not claims about current method names.

The smallest useful from-scratch client requires only:

```text
WebSocket connection
+
Narwal frame builder/parser
+
product key/device ID discovery
+
one receive loop
+
field-5 response queue
+
one command lock
+
topic subscription
+
protobuf encoder/decoder
```

A schematic implementation for a known identity looks like this:

```python
import asyncio
import websockets

from narwal_client.protocol import build_frame, parse_frame


async def pause_robot(
    host: str,
    product_key: str,
    device_id: str,
) -> None:
    uri = f"ws://{host}:9002"
    topic = f"/{product_key}/{device_id}/task/pause"

    async with websockets.connect(
        uri,
        ping_interval=30,
        ping_timeout=10,
    ) as ws:
        # task/pause has no complex CleanTask payload.
        await ws.send(build_frame(topic, b""))

        while True:
            raw = await ws.recv()
            if not isinstance(raw, bytes):
                continue

            message = parse_frame(raw)

            # 0x2A is the Narwal field-5 response envelope.
            # Broadcasts may arrive before the command response.
            if message.field_tag == 0x2A:
                print("Command response payload:", message.payload.hex())
                return


asyncio.run(
    pause_robot(
        host="192.168.1.100",
        product_key="QoEsI5qYXO",
        device_id="REPLACE_WITH_DISCOVERED_DEVICE_ID",
    )
)
```

This deliberately avoids inventing a `CleanTask` encoder. For actual room cleaning, reuse the current `NarwalClient` builder or reproduce it from PR #49 and the current source rather than copying a stale byte string. The framing implementation itself is documented in `protocol.py`. citeturn21view5turn21view6turn27view2

A production connection manager should have exactly **one coroutine reading the WebSocket**. It should classify incoming messages into:

```text
field 5 response
    -> pending-command queue

status/robot_base_status
    -> state cache

status/working_status
    -> state cache / event stream

map/display_map
    -> map-position cache

other topic
    -> raw event / decoder registry
```

Do not let each command call `recv()` independently. The current client has a command lock for precisely that race. citeturn22view3

A robust lifecycle is:

```text
connect
  ↓
discover/restore identity
  ↓
wake burst
  ↓
subscribe for 600 s
  ↓
start one receive task
  ↓
poll base status/map once for initial snapshot
  ↓
serve cached state
  ↓
renew subscription around 480 s
  ↓
if broadcasts stale:
    wake burst
  ↓
if still stale:
    reconnect
  ↓
exponential backoff + jitter
```

The mainline implementation already uses immediate wake-on-connect and exponential reconnect with jitter. citeturn21view1

A malformed Narwal header should be treated as a transport-level incident. Reverse-engineering notes report that malformed framing can trigger disconnect/refusal behavior for several seconds. Validate lengths before sending, and never fuzz the production robot from the same process that performs household automation.

**Recommended state-cache design**

```python
@dataclass
class RobotSnapshot:
    firmware: str | None
    battery_percent: float | None
    working_status_raw: int | None
    charging_status_raw: int | None

    progress: float | None
    cleaned_area_m2: float | None
    elapsed_seconds: int | None
    remaining_seconds: int | None

    map_id: int | None
    current_room_id: int | None
    robot_position: tuple[float, float] | None

    updated_at_monotonic: float

    # Do not discard fields you cannot decode yet.
    raw_base_status: dict
    raw_working_status: dict
```

Use timestamps per source topic. A fresh battery value does not imply that the live trajectory is fresh.

**An MQTT bridge is an especially good architecture for Narwal** because it makes a single process the only local WebSocket owner:

```text
               Narwal Flow
                    |
             WebSocket :9002
                    |
             narwal-daemon
             /     |     \
            /      |      \
       REST      MQTT      WS/SSE
         |         |         |
   custom apps     HA     dashboards
```

This addresses several protocol weaknesses at once:

- command responses with no useful response topic are serialized in one place;
- HA and custom programs never fight over the robot socket;
- deep-sleep recovery is centralized;
- subscriptions are renewed once;
- VLAN SNAT is required only for the daemon;
- firmware compatibility logic is not duplicated across every consumer.

A clean bridge namespace would be:

```text
narwal/<robot-id>/availability

narwal/<robot-id>/state
narwal/<robot-id>/state/battery
narwal/<robot-id>/state/working
narwal/<robot-id>/state/current_room

narwal/<robot-id>/map/meta
narwal/<robot-id>/map/position

narwal/<robot-id>/command/start
narwal/<robot-id>/command/pause
narwal/<robot-id>/command/resume
narwal/<robot-id>/command/return
narwal/<robot-id>/command/clean_rooms
narwal/<robot-id>/command/clean_zones

narwal/<robot-id>/event
```

State topics should generally be retained; command topics should not. A structured command should carry a caller-generated request ID so that:

```text
command/clean_rooms
{
  "request_id": "...",
  "rooms": [4, 7],
  "settings": {...}
}
```

can generate:

```text
event
{
  "request_id": "...",
  "type": "command_result",
  "result": "success"
}
```

followed independently by real robot-state events.

This separation is important: Narwal's synchronous `SUCCESS` means “command accepted” much more reliably than “desired physical outcome completed.”

A local REST/WebSocket bridge can use the same daemon core:

```text
GET  /api/robot/state
GET  /api/robot/map
GET  /api/robot/rooms

POST /api/robot/start
POST /api/robot/pause
POST /api/robot/resume
POST /api/robot/return

POST /api/robot/rooms/clean
POST /api/robot/zones/clean

GET  /api/events          # SSE
GET  /api/ws              # WebSocket event stream
```

The HTTP process should **not** know how protobuf is laid out. It should invoke semantic methods on the daemon's robot object. That keeps firmware-specific quirks below the application API.

For example:

```text
REST handler
   ↓
Robot.clean_rooms(room_ids, settings)
   ↓
compatibility policy
   ↓
get/refresh current map
   ↓
CleanTask builder
   ↓
serialized protocol transaction
   ↓
result
   ↓
state/event observer
```

**Packet-capture workflow.** Because AX12's local WebSocket is not TLS-protected, capturing the LAN protocol is much easier than the cloud path. Place the phone and robot behind an AP/router you control and capture on the bridge/AP interface:

```bash
tcpdump -i br-lan -s 0 -w narwal-local.pcap \
  'host ROBOT_IP and tcp port 9002'
```

For quick inspection:

```bash
tshark -r narwal-local.pcap \
  -Y 'tcp.port == 9002'
```

In Wireshark, ensure traffic is decoded as WebSocket after the HTTP upgrade and inspect binary frame payloads. The Narwal framing bytes make packet identification easy even when protobuf fields are unknown.

A disciplined experiment should change **one app setting at a time**:

```text
capture baseline current_clean_task
change one app setting
capture again
diff raw protobuf
restore
repeat
```

The project's protocol document explicitly recommends `clean/current_clean_task/get` plus raw-hex diffs for exactly this reason. citeturn27view5

Useful experiment sequence:

```text
idle docked
→ app open
→ start whole-house
→ pause
→ resume
→ return
→ single room
→ two rooms reversed order
→ one fan level change
→ one humidity change
→ 1 pass vs 2 passes
→ rectangular zone
→ mop wash
→ mop dry
→ empty
```

Save the PCAP, app action timestamp, robot firmware, app version, map ID and expected physical outcome together.

For **app ↔ cloud** capture:

```bash
tcpdump -i br-lan -s 0 -w narwal-cloud.pcap \
  'host PHONE_IP and not host ROBOT_IP'
```

You will primarily see TLS-encrypted HTTPS/MQTT traffic. The reverse-engineered cloud implementation demonstrates HTTPS plus MQTT/TLS rather than a cleartext cloud protocol. citeturn27view10

Use an interception proxy such as mitmproxy only if the application accepts your test CA. **I found no evidence sufficient to claim that current Narwal Android builds use certificate pinning.** Therefore the proper escalation path is:

```text
normal proxy + trusted test CA
        ↓ fails?
root/system trust store
        ↓ still fails?
instrument application TLS/client calls with Frida
        ↓
instrument native crypto/network code if necessary
```

Do not start from the assumption that pinning exists.

For protobuf reconstruction, also instrument serialization boundaries. Hooking a function immediately before `toByteArray()` or after `parseFrom()` is more useful than trying to infer field semantics solely from ciphertext/cloud captures.

For camera work:

```text
trigger take_picture
        ↓
capture local response bytes
        ↓
trace the app consumer
        ↓
locate image decrypt routine
        ↓
instrument key/IV/algorithm inputs
        ↓
save plaintext output before bitmap decode
```

That is the most direct route through the current camera-reverse-engineering boundary.

## Firmware risk, security, unresolved protocol areas, and recommended implementation

The ecosystem's failures are a useful guide to where compatibility layers belong.

**Firmware/integration compatibility matrix**

| Robot firmware/model | Integration/protocol state | Working/broken | Notes |
|---|---|---|---|
| Flow AX12 `v01.08.03.07` | sjmotew v1.0.2+ room protocol; v1.0.3+ subscription fix | **Working** | Hardware-confirmed ordered room cleaning; primary AX12 reference firmware. citeturn18view0 |
| Flow AX12 `v01.07.22+` | Older whole-house assumptions | **Behavior changed** | `vacuum.start` needs a loaded map under newer firmware behavior. citeturn18view0 |
| Flow AX12 `v01.09.05.01` capture set | reconstructed CleanParam comparison | **Protocol capture available** | Revealed an additional coverage/routing precision field difference; do not assume older builder emits every current-app field. |
| “Flow compact” `01.06.22.17` | local 9002 integration | **Broken/incompatible on reported unit** | Host reachable but TCP 9002 closed. citeturn27view0 |
| Flow / Flow 2 with integrations ≤ v1.0.1 mainline lineage | room cleaning | **Broken logically** | Wrong topic `clean/plan/start`; could return success but ignore room list. citeturn18view0turn27view1 |
| Flow mainline v1.0.2 | room cleaning | **Fixed** | Uses `clean/start_clean`. citeturn18view0turn27view2 |
| Flow mainline v1.0.2 | long-running push state | **Buggy** | 600-second subscription not renewed. citeturn18view0 |
| Flow mainline v1.0.3+ | long-running push state | **Fixed** | subscription renewal added after hardware reproduction. citeturn18view0 |
| Freo Z10 Pro/Turbo AX26 `v01.02.00.15` | `clean/start_clean` | **Working** | independent room-clean confirmation. citeturn18view0 |
| Freo 20 `v01.00.35.03` / `.36.11` | current local integration | **Working in reported features** | map/live room/area/dock state verified. citeturn18view0 |
| CX7 `v01.13.11.02`, key `hEA7OEshlx` | local integration with supplied device ID | **Working with limitation** | no broadcasts; polling only for state; no live cleaning metrics. citeturn18view0 |

The biggest documented failures were not transport-authentication changes; they were **semantic interpretation failures**:

```text
wrong topic
wrong protobuf field meaning
wrong room enum
expired subscription
wrong map context
packed-field parsing
```

That is good news for an independent implementation because it suggests the core WebSocket/framing layer is relatively stable, while the volatile pieces can be isolated.

A compatibility module should therefore key behavior by a structure such as:

```python
@dataclass(frozen=True)
class DeviceProfile:
    product_key: str
    model: str | None
    firmware: str | None

    websocket_local: bool
    broadcasts: bool
    room_clean_schema_version: str
    zone_clean_schema_version: str | None
    map_schema_version: str
```

Avoid code like:

```python
if firmware >= "1.8":
    ...
```

unless you have controlled captures proving the transition. Firmware strings are not necessarily suitable for lexical ordering, and product key can matter as much as version.

**Security consequences of the local protocol are significant.** Because the Flow LAN API is cleartext and apparently unauthenticated, a host that can establish the local connection potentially has robot-control capability. citeturn21view1turn21view5

For a hardened home installation:

```text
Internet
   |
Firewall
   |
+---------------- Main LAN ----------------+
|                                          |
| HA / narwal-daemon                       |
|                                          |
+-------------------|----------------------+
                    |
             controlled firewall
            TCP 9002 only + SNAT
                    |
+---------------- IoT VLAN ----------------+
|                                          |
| Narwal Flow                              |
|                                          |
+------------------------------------------+
```

Prefer the centralized daemon rather than permitting every workstation to TCP/9002. This simultaneously reduces attack surface and connection contention.

Do not expose port 9002 to the internet, and do not forward it from a WAN interface. There is no TLS/authentication layer that would make such exposure reasonable.

MIT licensing makes the sjmotew code particularly reusable. The MIT terms permit copying/modifying/redistribution provided the notice is retained. citeturn19view3

That license applies to the open-source project, not to Narwal's proprietary APK. For APK-derived findings, the safer engineering practice is clean reimplementation of observed wire behavior rather than copying decompiled proprietary source verbatim.

**Recommended implementation path**

For an engineer building both HA and non-HA support, I would structure the work this way:

```text
                 ┌─────────────────────┐
                 │  narwal-core Python │
                 │  no HA imports      │
                 └──────────┬──────────┘
                            │
           ┌────────────────┼────────────────┐
           │                │                │
       HA adapter       MQTT bridge       REST API
           │                │                │
           └────────────────┼────────────────┘
                            │
                       applications
```

The first implementation milestone should not be a prettier HA integration. It should be a **testable protocol package** that can:

```text
discover IP
connect
identify device
wake
subscribe
get base status
get map
pause/resume
return home
clean one known room
clean two ordered rooms
maintain push state for > 10 minutes
recover from disconnect
```

Once those work, wrap them in HA.

For an AX12, the existing `narwal_client` is already close enough that rewriting it immediately would add risk without adding knowledge. Start by vendoring it, build fixture tests from captured packets, then progressively move opaque encoding/decoding into typed protocol modules.

The highest-value tests are not generic unit tests; they are captured-wire regression tests:

```text
fixture_ax12_01_08_03_07_base_status.bin
fixture_ax12_01_08_03_07_get_map.bin
fixture_ax12_01_08_03_07_working_status.bin
fixture_ax12_01_09_05_01_clean_task_app.bin
fixture_ax26_01_02_00_15_room_clean.bin
```

Each test should assert both known semantics **and preservation of unknown fields**.

The following areas remain genuinely unresolved as of this research snapshot:

| Area | Current state | Best next investigation |
|---|---|---|
| Factory-reset / Wi-Fi provisioning with zero cloud/app involvement | **[U]** | Capture onboarding traffic, inspect BLE/SoftAP/provisioning components in APK |
| Flow Compact identity | **[U]** beyond one incompatible report | Capture mDNS/full port scan/product key/firmware from more units |
| Complete protobuf schema corpus | **[U/partial]** | Extract descriptors/builders from APK/native libraries |
| Full `WorkingStatus` enum | **[U/partial]** | APK enum recovery instead of incremental user reports |
| Error-code enum | **[partial]** | Correlate sytchi's readable error list with app resources/protobuf enums |
| Restricted-area reads | **[partial/unknown]** | Decode `get_editable_map` captures |
| Restricted-area writes | **[U]** | Capture app edits for one virtual wall/no-go zone at a time |
| Room rename/split/merge writes | **[U]** | Capture map-editor command topics and protobuf |
| Carpet-region editing | **[U]** | Map-editor/APK analysis |
| Maximum zone rectangles | **[U]** | Binary-search count using safe zone geometry |
| Camera frame crypto | **[U/partial]** | Instrument app decryption call site |
| Live camera/video protocol | **[U]** | Trigger app live view while capturing LAN/cloud and instrument signaling |
| Exact simultaneous-client limit | **[partial]** | Open sockets from two genuinely different LAN source IPs and observe |
| mDNS behavior in deepest sleep | **[U]** | Long-duration multicast capture while robot sleeps |
| Cross-VLAN restriction across all AX12 firmware | **[R only]** | Repeat issue #81 test on multiple firmware versions/regions |
| Per-consumable lifetime percentages | **[partial/unknown]** | Controlled worn-consumable captures + cloud/local comparison |
| Robot Wi-Fi RSSI/temperature | **[U]** | `get_feature_list`, config/status exhaustive field correlation |
| Scene/shortcut local equivalents | **[U; presently treated cloud-side]** | APK/Alink tracing |

## Source-code index and implementation decision

The following files are the most valuable starting points for an independent controller.

| Feature | Repository | File | Function/class / reason to study |
|---|---|---|---|
| Main local client | [`sjmotew/NarwalIntegration`](https://github.com/sjmotew/NarwalIntegration) | [`narwal_client/client.py`](https://github.com/sjmotew/NarwalIntegration/blob/master/narwal_client/client.py) | `NarwalClient`; connection, identity, receive loop, response queue, subscriptions, wake/reconnect. citeturn20view0turn21view1 |
| Frame parser | same | [`narwal_client/protocol.py`](https://github.com/sjmotew/NarwalIntegration/blob/master/narwal_client/protocol.py) | `parse_frame()`; validates Narwal envelope and extracts topic/payload. citeturn21view6 |
| Frame builder | same | same | `build_frame()`; outbound Narwal binary envelope. citeturn21view5 |
| Public standalone API | same | [`narwal_client/__init__.py`](https://github.com/sjmotew/NarwalIntegration/blob/master/narwal_client/__init__.py) | Shows intended exports: `NarwalClient`, models, enums, framing helpers. citeturn24view0 |
| State/map parsing | same | [`narwal_client/models.py`](https://github.com/sjmotew/NarwalIntegration/blob/master/narwal_client/models.py) | `NarwalState`, `MapData`, `RoomInfo`, map/trajectory and consumable parsing. citeturn24view2 |
| Room names | same | same | `RoomInfo.ROOM_TYPE_NAMES`, `display_name`; corrected app-derived enum. citeturn24view2turn27view8 |
| Map parser | same | same | `MapData.from_response()`; rooms, map ID, origin, dock and annotations. citeturn24view2 |
| HA vacuum adapter | same | [`custom_components/narwal/vacuum.py`](https://github.com/sjmotew/NarwalIntegration/blob/master/custom_components/narwal/vacuum.py) | HA state/actions, `async_get_segments()`, `async_clean_segments()`, native CLEAN_AREA. citeturn22view6 |
| HA coordinator | same | [`custom_components/narwal/coordinator.py`](https://github.com/sjmotew/NarwalIntegration/blob/master/custom_components/narwal/coordinator.py) | `NarwalCoordinator`; push/state lifecycle and HA coordination. citeturn21view8 |
| Protocol reference | same | [`docs/PROTOCOL.md`](https://github.com/sjmotew/NarwalIntegration/blob/master/docs/PROTOCOL.md) | Best current consolidated topic/map/state/reverse-engineering notes. citeturn25view4turn27view5 |
| Room-clean correction | same | [`PR #49`](https://github.com/sjmotew/NarwalIntegration/pull/49) | Correct `clean/start_clean` implementation and parameterized `CleanParam`. citeturn27view2 |
| Fork archaeology | same | [`Issue #66`](https://github.com/sjmotew/NarwalIntegration/issues/66) | Consolidates independent discoveries and explains why old room protocol was wrong. citeturn27view1 |
| VLAN behavior | same | [`Issue #81`](https://github.com/sjmotew/NarwalIntegration/issues/81) | Packet-capture evidence for foreign-subnet refusal and SNAT workaround. citeturn27view3 |
| Flow Compact incompatibility | same | [`Issue #15`](https://github.com/sjmotew/NarwalIntegration/issues/15) | Compact-labelled device, firmware `01.06.22.17`, port 9002 closed. citeturn27view0 |
| Rectangular zone control | [`sytchi/NarwalIntegration`](https://github.com/sytchi/NarwalIntegration) | fork's local client/service implementation; README documents current API | `narwal.clean_zone`, room-clean extensions, HD map calibration. citeturn27view9 |
| Cloud REST/MQTT protocol | [`nadavbau/narwal-integration`](https://github.com/nadavbau/narwal-integration) | [`PROTOCOL_REFERENCE.md`](https://github.com/nadavbau/narwal-integration/blob/main/PROTOCOL_REFERENCE.md) | Regional hosts, login, refresh, MQTT5 details. citeturn27view10 |
| Cloud client | same | `custom_components/narwal/narwal_client/client.py` | MQTT client / cloud message transport |
| Cloud auth | same | `custom_components/narwal/narwal_client/cloud.py` | REST authentication/token handling |
| Cloud constants | same | `custom_components/narwal/narwal_client/const.py` | API/protocol constants |
| Cloud models | same | `custom_components/narwal/narwal_client/models.py` | Cloud response/state parsers |
| Cloud map renderer | same | `custom_components/narwal/narwal_client/map_renderer.py` | Cloud-side map rendering reference |

The final engineering decision is therefore unusually clear.

For a **standard Narwal Flow AX12**, do **not** begin by reverse engineering Narwal cloud authentication. The most capable control surface is already local:

```text
mDNS
   ↓
Flow IP
   ↓
ws://Flow:9002
   ↓
Narwal envelope
   ↓
protobuf
   ↓
status / maps / CleanTask / dock
```

The controller needs no cloud token and no local pairing key. The main technical risks are semantic protobuf evolution, robot sleep behavior, room/map identity changes, single-source connection contention and the reported subnet-source filter—not cryptographic authentication. citeturn18view0turn21view1

For **Home Assistant**, `sjmotew/NarwalIntegration` is the most defensible baseline as of September 2026 because it is the primary AX12 development target, incorporates the independent room-clean discoveries, implements HA's modern segment/area API and keeps its protocol client separable. `sytchi/NarwalIntegration` remains particularly valuable as the reference implementation for rectangular zone cleaning and richer zone/map UI. citeturn18view0turn27view1turn27view9

For **custom software**, the best first move is to package or vendor `sjmotew/NarwalIntegration/narwal_client`, retain its command serialization and wake/subscription machinery, then remove any remaining assumptions that exist solely for HA. The MIT license permits that with preservation of the license notice. citeturn24view0turn19view3

For a household in which HA, scripts and other applications all need Narwal access, the cleanest long-term design is a **single `narwal-daemon` speaking port 9002 to the robot and publishing a stable local REST/MQTT/WebSocket API**. That gives one owner of the fragile connection, one firmware-compatibility layer, one state cache, one place to handle sleep/reconnection, and one point at which cross-VLAN SNAT can be applied.

The areas that still justify fresh reverse engineering are no longer the basic robot-control path. They are the edges: **map editing and restricted areas, camera crypto/live video, complete protobuf/enumeration recovery, completely local initial provisioning, and precise firmware/model differences**. Those are the places where new APK instrumentation and controlled packet capture are most likely to produce information not already available in the current open-source implementations.