# Blender MCP — what it is for, how we run it, and what it must not be used for

> Audience: agents and developers working on the DoW2 import / rig / animation pipeline.
> Verified on this machine 2026-11-17 against `MCP for Blender` 1.30.0, Blender 5.1.0, and pi's
> `mcp-bridge` extension. Every command below was run and its output is quoted.

---

## 1. What it actually is

MCP is a **transport**: a protocol for exposing tools to a language model. For Blender the tools are
"get scene info", "execute Python", "look at the scene as an image", "generate a model". It is not a
different modelling engine, not a different exporter, and it changes nothing about glTF, skinning,
Havok, or the file formats we import.

> "MCP is a bridge, so the model sees only what the protocol exposes and every operation is a round
> trip. That makes it strong at scene setup and parametric scripting, and weak at long passes, heavy
> operations and anything iterative." — [Mixar, Blender MCP guide](https://www.mixar.app/blender-agent/blender-mcp-guide)

That sentence is the whole policy in one line. Our pipeline is a *long pass* over 145 units; our
diagnosis is *iterative and visual*. MCP is the right tool for the second and the wrong tool for the
first.

## 2. Our use case: investigation only

Use MCP when the question is **"what is actually in the scene / what does it look like"** and the
answer is not already measured by a script. Concretely, the things that cost this project days:

- "is the bind pose intact while the pose shatters?" — one `look` after importing, one after posing.
- "which bone owns this cluster?" — one `execute_blender_code` that prints ownership distances.
- "does the imported GLB carry textures and UVs?" — one call, instead of a script, a run and a grep.
- "why did the import fail?" — the addon returns the traceback to the caller immediately.

The verified capability that matters most is **`look`**: it returns the scene as an image. Judging a
rig by numbers is what let a mis-scaled Carnifex and a 0 %-tear-but-frozen mesh ship; judging it by
image is the gate that actually works.

## 3. What must NOT use it

| do not use MCP for | why |
|---|---|
| the 145-unit build pipeline | every action is a round trip; the pipeline is a deterministic batch that must run unattended and be reproducible from a command line |
| CI gates | a chat session is not a gate. `rig_fidelity.py`, `audit_rig.py`, `guard:glb`, jest and the Go suite are the gates |
| anything whose output must be byte-identical between runs | the model chooses the calls; the same intent can produce different scripts |
| long numeric scans | a 4,000-vertex ownership table belongs in a script, not in a conversation |
| asset *authoring* at scale | the scripts encode the rules once; MCP would re-derive them each session |

The rule that follows: **MCP finds the cause, a script encodes the fix, a gate proves it.** Never let
a finding live only in a chat.

## 4. Install (as done on this machine)

Two halves: a Blender addon that opens a socket inside Blender, and an MCP server that bridges the
protocol to that socket.

```bash
# 1. the addon, version-matched to the server (installs blender_mcp.py into Blender's user addons)
uvx mcp-for-blender install-addon

# 2. the MCP server is run on demand by the bridge; no global install needed
uvx mcp-for-blender --help
```

`uvx mcp-for-blender install-addon` reported:

```
Installed MCP for Blender addon to /home/talzanar/.config/blender/5.1/scripts/addons/blender_mcp.py
```

Do not keep a hand-copied `mcp_for_blender.py` alongside it — two registered copies of the same addon
is a needless failure mode (removed during this install).

## 5. Run it (headless host, the way our tooling needs it)

The addon **refuses to start under `blender -b`**, and it is right to:

```
BlenderMCP: cannot start server in background mode (blender -b) - commands would never execute
BlenderMCP: run Blender with a GUI, or use a virtual display: xvfb-run -a blender
```

It queues commands to Blender's **main thread** and drains the queue from a `bpy.app.timers`
callback. `blender -b` has no event loop, so timers never fire and every call times out. Verified
directly: a headless Blender with a 1 s heartbeat timer wrote `boot` and no ticks.

So the host is a **GUI-mode Blender under a virtual display**, and the script must **return** rather
than block — blocking the main thread stops the queue drain just as effectively:

```bash
# /tmp/mcp_serve.py  — start the server, then hand control back to Blender's event loop
setsid xvfb-run -a blender --python /tmp/mcp_serve.py -- --secs 1800 \
    </dev/null >/tmp/blender_mcp.log 2>&1 &
```

```python
import bpy, addon_utils, os, sys, time
addon_utils.enable("blender_mcp", default_set=True, persistent=True)
bpy.ops.blendermcp.start_server()          # GUI mode only; returns immediately
open("/tmp/blender-mcp.state", "w").write("running=%s\n" % bpy.context.scene.blendermcp_server_running)
t0 = time.time()
def _tick():                                # bounded lifetime, and a stop sentinel for the agent
    if os.path.exists("/tmp/blender-mcp.stop") or (time.time() - t0) > 1800:
        bpy.ops.wm.quit_blender(); return None
    return 1.0
bpy.app.timers.register(_tick, first_interval=2.0)
```

Operational rules learned the hard way in one session:

- **Never `sleep`-loop in the host script.** It blocks the main thread and every command times out
  with no error on the client side.
- **Always give the host a lifetime** (`--secs`) and a stop sentinel. A host left running holds a
  Blender process and port 9876, and a stale listener looks like a working server.
- **Write the host script to a real path and check it exists before launching.** A heredoc in a
  command that gets aborted leaves the file missing, and the failure appears only as
  `Python file ... could not be opened` in a log you are not reading.
- **Launch detached** (`setsid ... </dev/null >log 2>&1 &`) and verify in a *separate* command; a
  launch-and-sleep chain can be killed with its process group.

## 6. Wire it to pi

pi has no built-in MCP; the `mcp-bridge` extension republishes server tools as
`mcp__<server>__<tool>`. Add the stdio server to `~/.pi/agent/mcp-servers.json`:

```json
"blender": {
  "command": "uvx",
  "args": ["mcp-for-blender"],
  "env": { "BLENDER_HOST": "localhost", "BLENDER_PORT": "9876" },
  "enabled": true
}
```

Verify without starting pi:

```bash
cd ~/.pi/agent/extensions/mcp-bridge && node selftest.mjs --server blender
```

Measured output:

```
server: {"name":"MCP for Blender","version":"1.30.0"} protocol: 2025-06-18
tools: 10
  - get_addon_status
  - get_scene_info
  - execute_blender_code
  - look
  ...
```

`look` is the one to reach for when a rig has to be judged rather than counted.

## 7. Known traps of the addon itself

| trap | evidence | handling |
|---|---|---|
| `blender -b` cannot host it | addon prints the refusal; heartbeat timer wrote `boot` and no ticks | run GUI-mode under `xvfb-run` |
| blocking the main thread deadlocks every call | first host script used `while True: sleep()`; `get_scene_info` timed out with no reply | return from the script, drive shutdown from a timer |
| `bpy.ops.import_scene.gltf` fails with no active object | `AttributeError: 'Context' object has no attribute 'object'` at `armature_display` | create/select an object first: `bpy.ops.mesh.primitive_cube_add()` then set `view_layer.objects.active` |
| the socket server can stop after a command raises | port closed while the Blender process was still alive | restart the host between investigations; treat a refused connection as "restart", not "retry" |
| stdout is buffered into the log | `print` output appears late or not at all | write state to a file (`/tmp/blender-mcp.state`) rather than trusting the log |
| an unrelated addon can spam the log | `blender_dow` → `PIL` → `libtiff-fc87e79d.so.6.2.0` ImportError on every start | harmless; ignore it, and do not mistake it for the MCP addon failing |

## 8. The workflow this gives us

1. **Investigate with MCP.** Load the asset, `look` at it, print the measurement that decides the
   question. This is where "bind is fine / pose is broken" or "this bone owns vertices 1 m away" gets
   found in minutes instead of after a dozen rebuilds.
2. **Encode the finding as a script.** Every finding becomes a rule in
   `tools/blender/dow2_build_unit.py` or a check in `tools/rig_fidelity.py`.
3. **Prove it with a gate.** `rig_fidelity.py` (tear / inversion / interpenetration / displacement),
   `audit_rig.py`, `guard:glb`, and the rendered proof. A gate that a chat session satisfied is not a
   gate.

## 9. Sources

- MCP for Blender (addon + server, MIT): <https://github.com/ahujasid/mcp-for-blender> — the addon's
  own refusal message and `start()` guard are the authority on the `-b` limitation.
- "MCP is a bridge… strong at scene setup and parametric scripting, weak at long passes":
  <https://www.mixar.app/blender-agent/blender-mcp-guide>
- Blender's own MCP server (official, natural-language access to the Python API):
  <https://www.blender.org/lab/mcp-server/>
- The inspect → act → screenshot loop as an architecture:
  <https://devtalk.blender.org/t/3d-agent-blender-ai-assistant-built-a-multi-agent-system-on-top-of-blenders-mcp-and-python-api-and-sharing-architecture-learnings-for-the-lab-discussion/44260>
- pi's `mcp-bridge` extension: `~/.pi/agent/extensions/mcp-bridge/README.md`
