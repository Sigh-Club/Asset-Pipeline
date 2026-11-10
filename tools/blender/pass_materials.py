"""pass_materials.py — the data-pass (mask) material builders shared by every
pixel-master renderer.

Two bugs were paid for here and must not come back:

  * a normal mask saved through a filmic/AgX view transform decodes to
    non-unit vectors (observed 0.575–0.748). Data passes are rendered with
    `view_transform = "Raw"`;
  * an AO/normal threshold applied after 0..1 normalisation silently produces an
    empty mask. Thresholds are applied to the uint8 image.

A third variant of the same bug: a scene `view_settings.exposure` is applied even
under the Raw transform, so grading the beauty render by -0.65 EV baked a 0.64x
multiply into every normal mask (decoded lengths 0.58-0.75). Data passes must
zero the exposure as well as the view transform.

Every renderer in this repo that emits normal/AO/emission masks imports these
functions rather than re-implementing them.
"""
from __future__ import annotations

import bpy


def _emission_material(name: str):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat, nt, em


def normal_material():
    mat, nt, em = _emission_material("pass_normal")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mul = nt.nodes.new("ShaderNodeVectorMath"); mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = nt.nodes.new("ShaderNodeVectorMath"); add.operation = "ADD"
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    nt.links.new(geo.outputs["Normal"], mul.inputs[0])
    nt.links.new(mul.outputs["Vector"], add.inputs[0])
    nt.links.new(add.outputs["Vector"], em.inputs["Color"])
    em.inputs["Strength"].default_value = 1.0
    return mat


def ao_material(distance: float = 0.35):
    mat, nt, em = _emission_material("pass_ao")
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao.inputs["Distance"].default_value = distance
    ao.only_local = True
    nt.links.new(ao.outputs["Color"], em.inputs["Color"])
    em.inputs["Strength"].default_value = 1.0
    return mat


def _emissive_texture(materials):
    for m in materials:
        if not (m and m.use_nodes):
            continue
        for n in m.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image and (
                    "emissiv" in n.image.name.lower() or "emission" in n.image.name.lower()):
                return n.image
    return None


def emission_material(slot_mats, fallback_atlas=None):
    """Emission-only pass: sample the material's emissive texture, or a supplied
    emission atlas, so the mask is derived from real authored data."""
    mat, nt, em = _emission_material("pass_emission")
    tex = _emissive_texture(slot_mats) or fallback_atlas
    if tex is not None:
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = tex
        node.interpolation = "Closest"
        nt.links.new(node.outputs["Color"], em.inputs["Color"])
    else:
        em.inputs["Color"].default_value = (0, 0, 0, 1)
    return mat


def render_mask(objs, kind: str, path, fallback_atlas=None, ao_distance: float = 0.35):
    """Render one data pass over one or more mesh objects, restoring the scene's
    view transform afterwards."""
    if not isinstance(objs, (list, tuple)):
        objs = [objs]
    meshes = [o for o in objs if o.type == "MESH" and o.data.materials]
    if not meshes:
        raise SystemExit("render_mask: no material-bearing mesh to mask")
    saved = {o.name: list(o.data.materials) for o in meshes}
    slot_mats = [m for o in meshes for m in o.data.materials if m]
    mat = {"normal": normal_material,
           "ao": lambda: ao_material(ao_distance),
           "emission": lambda: emission_material(slot_mats, fallback_atlas)}[kind]()
    for o in meshes:
        for i in range(len(o.data.materials)):
            o.data.materials[i] = mat
    scene = bpy.context.scene
    prev = (scene.view_settings.view_transform, scene.view_settings.look,
            scene.view_settings.exposure)
    try:
        scene.view_settings.view_transform = "Raw"
    except TypeError:
        scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    try:
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
    finally:
        scene.view_settings.view_transform = prev[0]
        scene.view_settings.look = prev[1]
        scene.view_settings.exposure = prev[2]
    for o in meshes:
        for i, m in enumerate(saved[o.name]):
            o.data.materials[i] = m
