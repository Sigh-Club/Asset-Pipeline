import bpy, math, addon_utils, sys
from mathutils import Vector, Matrix
sys.path.insert(0,'/run/media/talzanar/games/Projects/IoA/asset-pipeline/tools/blender')
import parametric_unit as pu

addon_utils.enable('rigify', default_set=True)
bpy.ops.wm.open_mainfile(filepath='/run/media/talzanar/games/Projects/IoA/asset-pipeline/assets/base_meshes/human-base-meshes-bundle-v1.4.1/human_base_meshes_bundle.blend')
body=bpy.data.objects.get('GEO-body_male_stylized')
for o in list(bpy.data.objects):
    if o.type=='MESH' and o is not body: bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.objects.active=body; body.select_set(True)
m=body.modifiers.new('dec','DECIMATE'); m.ratio=9000/max(1,sum(len(p.vertices)-2 for p in body.data.polygons)); bpy.ops.object.modifier_apply(modifier=m.name)
def bounds(o):
    cs=[o.matrix_world@Vector(c) for c in o.bound_box]
    return (Vector((min(c.x for c in cs),min(c.y for c in cs),min(c.z for c in cs))),Vector((max(c.x for c in cs),max(c.y for c in cs),max(c.z for c in cs))))
lo,hi=bounds(body); s=1.9/(hi.z-lo.z); body.scale=(s,s,s); bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
lo,hi=bounds(body); body.location=(-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z); bpy.ops.object.transform_apply(location=True,rotation=False,scale=False)
# metarig
bpy.context.scene.cursor.location=(0,0,0)
bpy.ops.object.select_all(action='DESELECT'); bpy.ops.object.armature_human_metarig_add(); meta=bpy.context.object; meta.location=(0,0,0)
lo,hi=bounds(meta); s=1.9/(hi.z-lo.z); meta.scale=(s,s,s); bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
lo,hi=bounds(meta); meta.location=(-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z); bpy.ops.object.transform_apply(location=True,rotation=False,scale=False)
bpy.ops.object.select_all(action='DESELECT'); body.select_set(True); meta.select_set(True); bpy.context.view_layer.objects.active=meta
bpy.ops.object.parent_set(type='ARMATURE_AUTO')
# pre-bend and IK
bpy.context.view_layer.objects.active=meta; bpy.ops.object.mode_set(mode='POSE')
for n in ('forearm.R','forearm.L'):
    pb=meta.pose.bones.get(n)
    if pb: pb.rotation_mode='XYZ'; pb.rotation_euler=(0.45,0,0)
bpy.ops.object.mode_set(mode='OBJECT')
for side,pt in (('R',(-0.10,-0.28,1.38)),('L',(0.04,-0.52,1.34))):
    tgt=bpy.data.objects.new(f'ik_{side}',None); tgt.location=pt; bpy.context.collection.objects.link(tgt)
    bpy.context.view_layer.objects.active=meta; bpy.ops.object.mode_set(mode='POSE')
    name=f'forearm.{"L" if side=="L" else "R"}'
    pb=meta.pose.bones.get(name)
    c=pb.constraints.new('IK'); c.target=tgt; c.chain_count=2
    bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
def bp(name):
    pb=meta.pose.bones[name]
    return (meta.matrix_world@pb.head), (meta.matrix_world@pb.tail)

# find the posed chest centre so the armour is built on the body, not at world 0
deps=bpy.context.evaluated_depsgraph_get(); ev=body.evaluated_get(deps); me=ev.to_mesh()
pts=[ev.matrix_world@v.co for v in me.vertices if 1.20 < (ev.matrix_world@v.co).z < 1.50 and abs((ev.matrix_world@v.co).x) < 0.25 and abs((ev.matrix_world@v.co).y) < 0.30]
centre=sum(pts,Vector((0,0,0)))/max(1,len(pts))
print('CHEST_CENTRE',centre)
before=set(bpy.data.objects)
deps=bpy.context.evaluated_depsgraph_get(); ev=body.evaluated_get(deps); me=ev.to_mesh()
hpts=[ev.matrix_world@v.co for v in me.vertices if (ev.matrix_world@v.co).z > 1.62]
hc=sum(hpts,Vector((0,0,0)))/max(1,len(hpts))
print('HEAD_BODY',hc,'HEAD_BONE',meta.matrix_world@meta.pose.bones['spine.006'].head,'BODY_LOC',body.matrix_world.translation)
# ---------------- armour fitted to the actual posed body surface ----------------
deps=bpy.context.evaluated_depsgraph_get(); ev=body.evaluated_get(deps); me=ev.to_mesh()
def centroid(zmin,zmax,xmin=-9,xmax=9,ymin=-9,ymax=9):
    pts=[]
    for v in me.vertices:
        w=ev.matrix_world@v.co
        if zmin<=w.z<=zmax and xmin<=w.x<=xmax and ymin<=w.y<=ymax:
            pts.append(w)
    return sum(pts,Vector((0,0,0)))/max(1,len(pts))
head=centroid(1.62,2.0); chest=centroid(1.24,1.50,-0.22,0.22); hips=centroid(0.95,1.10,-0.22,0.22)
shL=centroid(1.40,1.60,0.05,0.5); shR=centroid(1.40,1.60,-0.5,-0.05)
if shR.length<0.05: shR=Vector((-shL.x,shL.y,shL.z))
handL=centroid(1.15,1.55,0.03,0.5,-9,-0.20); handR=centroid(1.15,1.55,-0.5,-0.03,-9,-0.20)
thighL=centroid(0.55,0.92,0.01,0.5); thighR=centroid(0.55,0.92,-0.5,-0.01)
shinL=centroid(0.14,0.50,0.01,0.5); shinR=centroid(0.14,0.50,-0.5,-0.01)
footL=centroid(0.0,0.14,0.01,0.5); footR=centroid(0.0,0.14,-0.5,-0.01)
print('CENTROIDS',head,chest,hips,handL,handR,'SH',shL,shR)
pu.part("Spine1","armour_primary","cuirass").wedge((0.42,0.30,0.22),(chest.x,chest.y-0.01,chest.z-0.02),slope="front",amount=0.25).emit(0.02)
pu.part("Spine2","armour_primary","chestplate").wedge((0.44,0.32,0.18),(chest.x,chest.y-0.02,chest.z+0.14),slope="front",amount=0.32).emit(0.02)
pu.part("Spine","underlayer","abdomen").prism(6,0.16,0.16,(hips.x,hips.y,hips.z+0.10),taper=1.05).emit(0)
pu.part("Hips","armour_secondary","belt").wedge((0.38,0.28,0.10),(hips.x,hips.y,hips.z+0.02),slope="front",amount=0.25).emit(0.02)
pu.part("Spine2","metal_trim","collar").wedge((0.26,0.22,0.07),(chest.x,chest.y,chest.z+0.21),slope="back",amount=0.4).emit(0)
pu.part("Spine2","accent_emissive","chest_light").box((0.06,0.06,0.06),(chest.x,chest.y-0.14,chest.z+0.08)).emit(0)
for side,sh,hand,thigh,shin,foot,sx in (("Left",shL,handL,thighL,shinL,footL,1),("Right",shR,handR,thighR,shinR,footR,-1)):
    pu.part(f"{side}Shoulder","armour_primary","pauldron").wedge((0.20,0.26,0.18),(sh.x,sh.y,sh.z+0.03),slope="outer" if sx>0 else "inner",amount=0.42).emit(0.02)
    pu.part(f"{side}Shoulder","metal_trim","pauldron_rim").wedge((0.21,0.27,0.04),(sh.x,sh.y,sh.z+0.12),slope="outer" if sx>0 else "inner",amount=0.3).emit(0)
    pu.part(f"{side}ForeArm","armour_secondary","vambrace").limb_prism((sh.x,sh.y,sh.z-0.02),hand,0.075,sides=6,taper=0.9).emit(0.015)
    pu.part(f"{side}Hand","armour_secondary","gauntlet").wedge((0.11,0.14,0.10),(hand.x,hand.y,hand.z),slope="front",amount=0.3).emit(0.01)
    pu.part(f"{side}UpLeg","armour_secondary","thigh_plate").wedge((0.17,0.18,0.24),(thigh.x,thigh.y-0.02,thigh.z),slope="front",amount=0.25).emit(0.02)
    pu.part(f"{side}Leg","armour_primary","greave").wedge((0.16,0.18,0.28),(shin.x,shin.y-0.02,shin.z),slope="front",amount=0.3).emit(0.02)
    pu.part(f"{side}Foot","armour_secondary","boot").wedge((0.16,0.30,0.15),(foot.x,foot.y-0.06,foot.z+0.02),slope="front",amount=0.35).emit(0.02)
pu.part("Head","armour_primary","helm").prism(8,0.125,0.26,(head.x,head.y,head.z+0.03),taper=0.78).emit(0.02)
pu.part("Head","armour_secondary","brow").wedge((0.22,0.12,0.06),(head.x,head.y-0.09,head.z+0.09),slope="front",amount=0.5).emit(0.015)
pu.part("Head","metal_trim","jaw").wedge((0.18,0.22,0.08),(head.x,head.y-0.03,head.z-0.09),slope="front",amount=0.3).emit(0)
pu.part("Head","accent_emissive","visor").box((0.18,0.06,0.04),(head.x,head.y-0.10,head.z+0.03)).emit(0)
pu.part("Head","metal_trim","crest").wedge((0.03,0.14,0.18),(head.x,head.y+0.02,head.z+0.21),slope="back",amount=0.5).emit(0)
pu.part("Spine2","armour_secondary","backpack").wedge((0.30,0.18,0.30),(chest.x,chest.y+0.16,chest.z),slope="back",amount=0.2).emit(0.02)
pu.part("Spine2","metal_trim","pack_vents").box((0.22,0.04,0.06),(chest.x,chest.y+0.25,chest.z-0.06)).emit(0)

# ---------------- weapon at the IK wrist targets -------------
grip=Vector((-0.10,-0.28,1.38)); fore=Vector((0.04,-0.52,1.34))
axis=(fore-grip).normalized()
pu.part("RightHand","metal_trim","stock").limb(grip-axis*0.22, grip-axis*0.02, 0.09, 0.13).emit(0.01)
pu.part("RightHand","metal_trim","receiver").limb(grip-axis*0.02, fore, 0.10, 0.14).emit(0.01)
pu.part("RightHand","metal_trim","barrel").limb(fore, fore+axis*0.40, 0.045, 0.045).emit(0)
pu.part("RightHand","metal_trim","muzzle").wedge((0.08,0.08,0.08), fore+axis*0.43, slope="front", amount=0.2).emit(0)
mid=grip.lerp(fore,0.45)
pu.part("RightHand","armour_primary","magazine").wedge((0.08,0.10,0.22), mid+Vector((0,0,-0.12)), slope="front", amount=0.2).emit(0.01)
pu.part("RightHand","metal_trim","sight").box((0.04,0.06,0.05), mid+Vector((0,0,0.10))).emit(0)
pu.part("RightHand","armour_secondary","grip").wedge((0.07,0.08,0.12), grip+Vector((0,0,-0.06)), slope="front", amount=0.3).emit(0)
pu.part("RightHand","metal_trim","trigger_guard").box((0.07,0.10,0.02), grip+axis*0.06+Vector((0,0,-0.05))).emit(0)

# ---------------- clay render ----------------
allm=[o for o in bpy.context.scene.objects if o.type=='MESH']
mat=bpy.data.materials.new('clay'); mat.use_nodes=True
bsdf=mat.node_tree.nodes.get('Principled BSDF'); bsdf.inputs['Base Color'].default_value=(0.45,0.47,0.52,1); bsdf.inputs['Roughness'].default_value=0.8
for o in allm:
    o.data.materials.clear(); o.data.materials.append(mat)
    for p in o.data.polygons: p.use_smooth=False
world=bpy.data.worlds.new('w'); world.use_nodes=True
world.node_tree.nodes['Background'].inputs[0].default_value=(0.08,0.09,0.11,1); world.node_tree.nodes['Background'].inputs[1].default_value=1.0
bpy.context.scene.world=world
key=bpy.data.lights.new('key','AREA'); key.energy=1000; key.size=4
ko=bpy.data.objects.new('key',key); ko.location=(2,-3,4); ko.rotation_euler=(0.7,0.2,0.5); bpy.context.collection.objects.link(ko)
rim=bpy.data.lights.new('rim','AREA'); rim.energy=550; rim.size=3
ro=bpy.data.objects.new('rim',rim); ro.location=(-3,2,3); ro.rotation_euler=(1.1,0,-2.2); bpy.context.collection.objects.link(ro)
cam_data=bpy.data.cameras.new('cam'); cam_data.type='ORTHO'; cam_data.ortho_scale=2.35
cam=bpy.data.objects.new('cam',cam_data); bpy.context.collection.objects.link(cam); bpy.context.scene.camera=cam
centre=Vector((0,0,0.95))
for name,off in {'front':(0,-4,0),'side':(4,0,0),'threeq':(3,-3,0.4)}.items():
    cam.location=centre+Vector(off); cam.rotation_euler=(centre-cam.location).to_track_quat('-Z','Y').to_euler()
    sc=bpy.context.scene; sc.render.engine='BLENDER_EEVEE' if 'BLENDER_EEVEE' in [e.identifier for e in sc.render.bl_rna.properties['engine'].enum_items] else 'BLENDER_EEVEE_NEXT'
    sc.render.resolution_x=420; sc.render.resolution_y=560; sc.render.filepath=f'/tmp/cmp3d/fullproof_{name}.png'; bpy.ops.render.render(write_still=True)
print('LARGE', sorted([(round(max(o.dimensions),2),o.name) for o in allm], reverse=True)[:8])
print('TRIS_BODY',sum(len(p.vertices)-2 for p in body.data.polygons),'TOTAL',sum(len(p.vertices)-2 for o in allm for p in o.data.polygons))
