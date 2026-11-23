# How game characters are actually built — and why our "one big mesh" route is wrong

**Researched 2026-11-23.** This corrects the approach in `tools/blender/aaa_rebuild.py`: the AAA tier was
being produced as a single monolithic mesh with one atlas and one bake. That is not how characters are
built in modern game development, and it is the reason every material decision in this pipeline is a
global compromise instead of a per-part one.

---

## 1. What the industry actually does

### Modular characters are multiple skeletal meshes

Epic's own documentation for Unreal Engine, "Modular Characters in Unreal Engine":

> "Describes the different methods you can use to create modular characters comprised of **multiple
> Skeletal Meshes**." — [dev.epicgames.com, Modular Characters](https://dev.epicgames.com/documentation/en-us/unreal-engine/modular-characters-in-unreal-engine) (retrieved 2026-11-23; the page is
> client-rendered, so the statement is taken from Epic's own document summary)

The methods it covers exist precisely because a character is assembled, not sculpted as one object: a
body mesh plus separate meshes for helmet, torso armour, arms, legs, and gear, all bound to one
skeleton and combined at runtime.

### Gear attaches to sockets, not to the mesh

Epic, "Skeletal Mesh Sockets":

> "Once set up, you can attach your objects, weapons, and other actors to the Socket."
> — [dev.epicgames.com, Skeletal Mesh Sockets](https://dev.epicgames.com/documentation/unreal-engine/skeletal-mesh-sockets-in-unreal-engine)

Sockets live on the **skeleton**, so any asset sharing that skeleton can carry any weapon, backpack,
pauldron or VFX emitter at a known transform. A practitioner summary states the engineering reason
plainly: without sockets, "attaching a prop to a moving character means writing fragile offset code that
breaks every time an animator tweaks the rig."

### The consequences for asset production

| practice | why it exists |
|---|---|
| one shared skeleton, many meshes | every unit, variant and DLC piece animates from the same clip set |
| per-part meshes | each part gets its own triangle budget, UV layout, material and LOD |
| per-part materials | cloth, ceramite, brass and leather each get correct roughness/metallic instead of one averaged value |
| sockets for gear | weapons and equipment are swappable without re-authoring the character |
| LOD per part | a pauldron can drop to 200 tris while the torso stays high — you cannot do that inside one mesh |
| kitbash / modular kits | new variants come from recomposing existing parts, not re-modelling |

## 2. What we do instead — measured

`tools/blender/aaa_rebuild.py` (reference-base route) produces:

- **one** mesh: subdivide the whole body to 120,000 tris;
- **one** atlas: a single 4K normal/AO baked across the entire figure;
- **one** material decision per slot name, applied globally (`SLOT_SURFACE`);
- **one** LOD chain for the whole body;
- gear fused into the body, positioned by the sculpt rather than by a socket.

That is why the material work kept failing: with the whole figure in one bake and one atlas, the
trousers, the pauldron and the rifle share one texel budget and one normal map, and every per-slot
tuning is a compromise against the other three.

## 3. Our own repo already proves the modular route wins

`TODO.md` scores the DoW2 import — which is *modular assembly* — at **85–95 % per unit**, and
`AGENTS.md` G3 states the rule explicitly:

> "**Assemble from the shipped wargear `render_models` list**, de-duplicating quality tiers."

The DoW2 units are body + wargear armour + weapon, assembled from shipped parts, each with its own
mesh, material and (where shipped) clips. That path scores 85–95 %. The monolithic AAA route is the
one that needed six iterations to stop looking wrong.

The competition does the same thing from the other direction: Tripo and Meshy both sell **segmentation**
as the step *before* rigging — "separate rigid parts before rigging for cleaner deformation" and
"break characters into modular equipment pieces" (`docs/AGENTIC_3D_RESEARCH.md` §2.3).

## 4. The change this implies

Produce a **part set**, not a single GLB:

```
<unit>/
  skeleton.glb            one shared rig; sockets named (hand_r, head, back, hips)
  body.glb                base body, own UV/material/LOD chain
  gear/pauldron_l.glb     attached at socket, own budget + material
  gear/pauldron_r.glb
  gear/helmet.glb
  gear/weapon.glb         at hand_r socket
  unit.manifest.json      parts, sockets, per-part budgets, materials, LODs
```

Rules that follow from the research:

1. **Per-part budgets.** A pauldron is not 1/6 of a hero character's 120,000 tris; it is 3,000–8,000
   with its own LODs.
2. **Per-part materials.** Ceramite, brass, cloth and leather get their own roughness/metallic ranges,
   not a global `SLOT_SURFACE` table applied to one atlas.
3. **Sockets on the skeleton.** Gear position comes from a named bone socket, so a new pauldron needs no
   re-bake of the body.
4. **Per-part bakes.** The normal bake is per part against that part's high-poly source, which is also
   what makes a 4K map affordable: a pauldron at 4K is far denser in texels than a whole body at 4K.
5. **Assembly is data.** The manifest is what the engine reads; recomposing a variant is editing the
   manifest, not rebuilding a mesh.

## 5. What this does not change

The band numbers in `docs/STYLE_BANDS.md` still apply — they now apply **per part** rather than per
figure. The gates still apply: contract, texel floor, baked normal, vision review. The generator is
still the geometry source. What changes is the unit of production.

## 6. Tripwire

Re-check if the engine side adopts a virtualised-geometry pipeline (Nanite) for characters, which
removes the per-part LOD incentive but not the per-part material and socket ones.
