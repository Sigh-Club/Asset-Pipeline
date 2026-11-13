"""base_unit_build.py — authored base-mesh unit -> rigged, posed, palette-ready GLB.

Builds a pixel-tier humanoid from the CC0 Blender Studio base mesh instead of the
primitive kit: real anatomy, a fitted Rigify metarig with heat weights, a
two-handed shouldered weapon pose solved with IK and baked to an `aim` action,
body-derived armour shells plus hard-surface gear bound rigidly to their bones,
and an export with library-compatible material slots for the pixel atlas bake.

    blender -b -P tools/blender/base_unit_build.py -- \
        --faction iron_directorate --unit line_infantry --export

Then run tools/build_pixel_authored_unit.sh with PROFILE=pixel_3d_hi and
MATERIAL_MAP=configs/materials/base_unit_material_map.json.
"""
import argparse, bpy, math, addon_utils, statistics
_argv=__import__('sys').argv
_args=_argv[_argv.index('--')+1:] if '--' in _argv else []
_ap=argparse.ArgumentParser()
_ap.add_argument('--faction', default='iron_directorate')
_ap.add_argument('--unit', default='line_infantry')
_ap.add_argument('--id', default=None)
_ap.add_argument('--out', default=None)
_ap.add_argument('--decimate', type=float, default=0.36)
_ap.add_argument('--render', action='store_true')
_ap.add_argument('--export', action='store_true')
A=_ap.parse_args(_args)
from mathutils import Vector, Matrix
addon_utils.enable('rigify', default_set=True)
bpy.ops.wm.open_mainfile(filepath='/run/media/talzanar/games/Projects/IoA/asset-pipeline/assets/base_meshes/human-base-meshes-bundle-v1.4.1/human_base_meshes_bundle.blend')
body=bpy.data.objects['GEO-body_male_stylized']
for o in list(bpy.data.objects):
    if o.type=='MESH' and o is not body: bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.objects.active=body; body.select_set(True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
co=[v.co.copy() for v in body.data.vertices]
torso=[c for c in co if 1.15<c.z<1.55]
mx=statistics.median(c.x for c in torso); my=statistics.median(c.y for c in torso)
for v in body.data.vertices: v.co.x-=mx; v.co.y-=my
body.data.update()
co=[v.co.copy() for v in body.data.vertices]
lo=min(c.z for c in co); hi=max(c.z for c in co); s=1.9/(hi-lo)
for v in body.data.vertices: v.co*=s; v.co.z-=lo*s
body.data.update()
co=[v.co.copy() for v in body.data.vertices]
def cen(zmin,zmax,xmin,xmax):
    pts=[c for c in co if zmin<c.z<zmax and xmin<c.x<xmax]
    return sum(pts,Vector())/len(pts)
L={}
for side,sgn in (('L',1),('R',-1)):
    def X(a,b): return (a,b) if sgn>0 else (-b,-a)
    L[side]={
      'shoulder':cen(1.44,1.56,*X(0.18,0.55)),
      'elbow':cen(1.13,1.28,*X(0.30,0.62)),
      'wrist':cen(0.98,1.10,*X(0.35,0.65)),
      'hand':cen(0.82,0.98,*X(0.35,0.70)),
      'hip':cen(0.95,1.10,*X(0.04,0.28)),
      'knee':cen(0.45,0.62,*X(0.04,0.28)),
      'ankle':cen(0.06,0.16,*X(0.04,0.28)),
      'toe':cen(0.0,0.06,*X(0.04,0.28)),
    }
print('LANDMARKS', {k:(round(v.x,3),round(v.y,3),round(v.z,3)) for k,v in L['L'].items()})
# decimate to the pixel-tier body budget before binding
if A.decimate>0 and A.decimate<1.0:
    dm=body.modifiers.new('dec','DECIMATE'); dm.ratio=A.decimate; dm.use_collapse_triangulate=True
    bpy.context.view_layer.objects.active=body
    bpy.ops.object.modifier_apply(modifier=dm.name)
    print('DECIMATED tris', len(body.data.polygons))
# metarig
bpy.context.scene.cursor.location=(0,0,0)
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.object.armature_human_metarig_add(); arm=bpy.context.object; arm.location=(0,0,0)
# scale metarig to 1.9 by bbox
cs=[arm.matrix_world@Vector(c) for c in arm.bound_box]
zlo=min(c.z for c in cs); zhi=max(c.z for c in cs); s2=1.9/(zhi-zlo)
arm.scale=(s2,s2,s2); bpy.ops.object.transform_apply(scale=True)
cs=[arm.matrix_world@Vector(c) for c in arm.bound_box]
zlo=min(c.z for c in cs); arm.location=(0,0,-zlo); bpy.ops.object.transform_apply(location=True)
bpy.context.view_layer.objects.active=arm; bpy.ops.object.mode_set(mode='EDIT')
eb=arm.data.edit_bones
def setb(n,h,t):
    b=eb.get(n)
    if not b: print('MISSING',n); return
    b.head=Vector(h); b.tail=Vector(t)
# spine / head
setb('spine',(0,0,1.03),(0,0,1.16)); setb('spine.001',(0,0,1.16),(0,0,1.29))
setb('spine.002',(0,0,1.29),(0,0,1.46)); setb('spine.003',(0,0,1.46),(0,0,1.56))
setb('spine.004',(0,0,1.56),(0,0,1.63)); setb('spine.005',(0,0,1.63),(0,0,1.70))
setb('spine.006',(0,0,1.70),(0,0,1.90))
for side,sgn in (('L',1),('R',-1)):
    p=L[side]
    setb(f'shoulder.{side}',(sgn*0.02,0,1.50),(p['shoulder'].x,p['shoulder'].y,p['shoulder'].z))
    setb(f'upper_arm.{side}',(p['shoulder'].x,p['shoulder'].y,p['shoulder'].z),(p['elbow'].x,p['elbow'].y,p['elbow'].z))
    setb(f'forearm.{side}',(p['elbow'].x,p['elbow'].y,p['elbow'].z),(p['wrist'].x,p['wrist'].y,p['wrist'].z))
    setb(f'hand.{side}',(p['wrist'].x,p['wrist'].y,p['wrist'].z),(p['hand'].x,p['hand'].y,p['hand'].z))
    setb(f'thigh.{side}',(p['hip'].x,p['hip'].y,p['hip'].z),(p['knee'].x,p['knee'].y,p['knee'].z))
    setb(f'shin.{side}',(p['knee'].x,p['knee'].y,p['knee'].z),(p['ankle'].x,p['ankle'].y,p['ankle'].z))
    setb(f'foot.{side}',(p['ankle'].x,p['ankle'].y,p['ankle'].z),(p['toe'].x,p['toe'].y,p['toe'].z))
    setb(f'toe.{side}',(p['toe'].x,p['toe'].y,p['toe'].z),(p['toe'].x,p['toe'].y-0.08,0.02))
bpy.ops.object.mode_set(mode='OBJECT')
for n in ['upper_arm.L','forearm.L','hand.L','thigh.L','shin.L','foot.L']:
    b=arm.data.bones[n]; print(f'FIT {n} h=({b.head_local.x:+.3f},{b.head_local.y:+.3f},{b.head_local.z:+.3f}) t=({b.tail_local.x:+.3f},{b.tail_local.y:+.3f},{b.tail_local.z:+.3f})')
# bind
bpy.ops.object.select_all(action='DESELECT'); body.select_set(True); arm.select_set(True); bpy.context.view_layer.objects.active=arm
bpy.ops.object.parent_set(type='ARMATURE_AUTO')
print('VGROUPS',len(body.vertex_groups))
print('MODS',[(m.name,m.type,m.object.name if getattr(m,'object',None) else '-') for m in body.modifiers])
import mathutils
for tgt in [(0.28,0.0,1.35),(0.39,0.0,1.10),(0.42,0.0,0.90),(0.05,0.0,1.30),(0.0,0.0,1.75)]:
    tv=mathutils.Vector(tgt)
    vi=min(range(len(body.data.vertices)), key=lambda i:(body.matrix_world@body.data.vertices[i].co-tv).length)
    v=body.data.vertices[vi]
    ws=sorted([(g.weight, body.vertex_groups[g.group].name) for g in v.groups], reverse=True)[:5]
    print('WEIGHTS near',tgt,'->',[(round(w,3),n) for w,n in ws])
# ---------------- P2 two-handed shouldered pose ----------------
stock=Vector((-0.18,0.06,1.44))
axis=Vector((0.50,-0.86,-0.02)).normalized()
grip=stock+axis*0.21+Vector((0,0,-0.07))
fore=stock+axis*0.44+Vector((0,0,-0.05))
muzzle=stock+axis*0.82
print('WEAPON stock',stock,'grip',grip,'fore',fore,'muzzle',muzzle,'sep',(fore-grip).length)
poles={'R':Vector((-0.45,0.10,1.20)),'L':Vector((0.40,-0.10,1.15))}
targets={'R':grip,'L':fore}
bpy.context.view_layer.objects.active=arm; bpy.ops.object.mode_set(mode='POSE')
for side in ('R','L'):
    tgt=bpy.data.objects.new(f'ik_{side}',None); tgt.location=targets[side]; bpy.context.collection.objects.link(tgt)
    pol=bpy.data.objects.new(f'pole_{side}',None); pol.location=poles[side]; bpy.context.collection.objects.link(pol)
    pb=arm.pose.bones[f'forearm.{side}']
    c=pb.constraints.new('IK'); c.target=tgt; c.chain_count=2; c.pole_target=pol; c.pole_angle=(0.0 if side=='R' else math.pi)
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
deps=bpy.context.evaluated_depsgraph_get(); ae=arm.evaluated_get(deps)
for side in ('R','L'):
    h=ae.matrix_world@ae.pose.bones[f'hand.{side}'].head
    print(f'HAND {side} at ({h.x:+.3f},{h.y:+.3f},{h.z:+.3f}) target ({targets[side].x:+.3f},{targets[side].y:+.3f},{targets[side].z:+.3f}) err={(h-targets[side]).length:.3f}')
# ================= P3/P4 armour + weapon =================
import bmesh
from pathlib import Path
from mathutils import Vector, Matrix

def mkmat(name,rgb,rough=0.6,metal=0.0,emit=None):
    m=bpy.data.materials.new(name); m.use_nodes=True
    b=m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value=(rgb[0],rgb[1],rgb[2],1)
    b.inputs['Roughness'].default_value=rough
    b.inputs['Metallic'].default_value=metal
    if emit:
        b.inputs['Emission Color'].default_value=(emit[0],emit[1],emit[2],1)
        b.inputs['Emission Strength'].default_value=2.5
    return m
M={
 'suit':mkmat('underlayer',(0.075,0.080,0.095),0.9),
 'steel':mkmat('armour_primary',(0.26,0.28,0.32),0.55,0.30),
 'dark':mkmat('armour_secondary',(0.11,0.12,0.15),0.62,0.25),
 'cloth':mkmat('IOA_cloth_canvas',(0.075,0.105,0.17),0.95),
 'leather':mkmat('IOA_leather_tan',(0.12,0.09,0.07),0.85),
 'gun':mkmat('IOA_gunmetal_worn',(0.10,0.11,0.13),0.38,0.7),
 'brass':mkmat('IOA_brass_tarnished',(0.50,0.38,0.18),0.4,0.7),
 'visor':mkmat('accent_emissive',(0.95,0.40,0.10),0.25,0.1,(1.0,0.45,0.10)),
}
body.data.materials.clear(); body.data.materials.append(M['suit'])

def segd(p,a,b):
    ab=b-a; t=max(0.0,min(1.0,(p-a).dot(ab)/ab.length_squared)); q=a+ab*t
    return (p-q).length,t

def dup_region(name,keep,thick=0.022,dec=0.25,material=None):
    d=body.copy(); d.data=body.data.copy(); d.name=name
    bpy.context.collection.objects.link(d)
    bm=bmesh.new(); bm.from_mesh(d.data)
    dead=[v for v in bm.verts if not keep(v.co)]
    if dead: bmesh.ops.delete(bm,geom=dead,context='VERTS')
    if len(bm.verts)==0:
        bm.free(); bpy.data.objects.remove(d,do_unlink=True); return None
    bm.to_mesh(d.data); bm.free()
    s=d.modifiers.new('sol','SOLIDIFY'); s.thickness=thick; s.offset=1.0; s.use_rim=True
    dm=d.modifiers.new('dec','DECIMATE'); dm.ratio=dec
    if material:
        d.data.materials.clear(); d.data.materials.append(material)
    return d

Lm=L
def torso_ok(p): return 1.04<p.z<1.46 and abs(p.x)<0.235 and -0.17<p.y<0.19
dup_region('cuirass',torso_ok,0.024,0.20,M['steel'])
for i,(z0,z1) in enumerate([(1.03,1.085),(1.095,1.15),(1.16,1.215)]):
    dup_region(f'lame{i}',lambda p,z0=z0,z1=z1: z0<p.z<z1 and abs(p.x)<0.225 and -0.17<p.y<0.18,0.018,0.35,M['dark'])
for side,sgn in (('L',1),('R',-1)):
    dup_region(f'tasset_{side}',lambda p,sgn=sgn: 0.86<p.z<1.03 and 0.04<sgn*p.x<0.23 and p.y<0.07,0.02,0.35,M['steel'])
    a,b=Lm[side]['hip'],Lm[side]['knee']
    dup_region(f'thighsuit_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.105 and 0.08<segd(p,a,b)[1]<0.92,0.012,0.30,M['dark'])
    dup_region(f'thighplate_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.105 and 0.12<segd(p,a,b)[1]<0.85 and p.y<0.0,0.02,0.35,M['steel'])
    a,b=Lm[side]['knee'],Lm[side]['ankle']
    dup_region(f'greave_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.095 and 0.10<segd(p,a,b)[1]<0.92 and p.y<0.02,0.022,0.35,M['steel'])
    a,b=Lm[side]['shoulder'],Lm[side]['elbow']
    dup_region(f'rerebrace_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.085 and 0.20<segd(p,a,b)[1]<0.95,0.016,0.35,M['dark'])
    a,b=Lm[side]['elbow'],Lm[side]['wrist']
    dup_region(f'vambrace_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.078 and 0.25<segd(p,a,b)[1]<0.98,0.02,0.35,M['dark'])
    a,b=Lm[side]['wrist'],Lm[side]['hand']
    dup_region(f'gauntlet_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.088 and 0.0<segd(p,a,b)[1]<0.85,0.018,0.35,M['steel'])
    dup_region(f'boot_{side}',lambda p,sgn=sgn: p.z<0.155 and 0.03<sgn*p.x<0.23,0.028,0.4,M['dark'])

# ---- posed joint positions for rigid plates ----
deps=bpy.context.evaluated_depsgraph_get(); ae=arm.evaluated_get(deps)
def pj(n,head=True):
    b=ae.pose.bones[n]; return ae.matrix_world@(b.head if head else b.tail)
shoulder={s:pj(f'upper_arm.{s}') for s in ('L','R')}
elbow={s:pj(f'forearm.{s}') for s in ('L','R')}
knee={s:pj(f'shin.{s}') for s in ('L','R')}
hand_b={s:ae.matrix_world@ae.pose.bones[f'hand.{s}'].head for s in ('L','R')}
print('POSED shoulder',{k:tuple(round(x,3) for x in v) for k,v in shoulder.items()})
print('POSED elbow',{k:tuple(round(x,3) for x in v) for k,v in elbow.items()})

def new_obj(name,bm,material):
    me=bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o=bpy.data.objects.new(name,me); bpy.context.collection.objects.link(o)
    o.data.materials.append(material)
    for p in o.data.polygons: p.use_smooth=False
    return o

def add_box(name,c,s,material,pitch=0.0,roll=0.0,taper=1.0,taper_y=None):
    bm=bmesh.new(); ret=bmesh.ops.create_cube(bm,size=1.0); vs=ret['verts']
    bmesh.ops.scale(bm,vec=s,verts=vs)
    if taper!=1.0:
        ty=taper if taper_y is None else taper_y
        for v in vs:
            if v.co.z>0: v.co.x*=taper; v.co.y*=ty
    if pitch: bmesh.ops.transform(bm,matrix=Matrix.Rotation(math.radians(pitch),4,'X'),verts=vs)
    if roll: bmesh.ops.transform(bm,matrix=Matrix.Rotation(math.radians(roll),4,'Y'),verts=vs)
    bmesh.ops.translate(bm,vec=c,verts=vs)
    return new_obj(name,bm,material)

def add_cyl(name,c,r,d,material,axis=Vector((0,0,1)),seg=10):
    bm=bmesh.new(); bmesh.ops.create_cone(bm,cap_ends=True,segments=seg,radius1=r,radius2=r,depth=d)
    R=axis.to_track_quat('Z','Y').to_matrix().to_4x4()
    bmesh.ops.transform(bm,matrix=R,verts=bm.verts)
    bmesh.ops.translate(bm,vec=c,verts=bm.verts)
    return new_obj(name,bm,material)

def add_cap(name,c,rad,cut,material,seg=14,rings=8):
    bm=bmesh.new(); bmesh.ops.create_uvsphere(bm,u_segments=seg,v_segments=rings,radius=1.0)
    for v in bm.verts: v.co=Vector((v.co.x*rad[0],v.co.y*rad[1],v.co.z*rad[2]))
    dead=[v for v in bm.verts if v.co.z<cut]
    if dead: bmesh.ops.delete(bm,geom=dead,context='VERTS')
    bmesh.ops.translate(bm,vec=c,verts=bm.verts)
    o=new_obj(name,bm,material)
    s=o.modifiers.new('sol','SOLIDIFY'); s.thickness=0.02; s.offset=1.0
    return o

# pauldrons: angular layered plates
def bevel(o,w=0.012):
    b=o.modifiers.new('bev','BEVEL'); b.width=w; b.segments=1; b.limit_method='ANGLE'; return o
for side,sgn in (('L',1),('R',-1)):
    c=shoulder[side]
    bevel(add_box(f'pauldron_{side}',c+Vector((sgn*0.01,0.0,0.015)),(0.19,0.25,0.09),M['steel'],pitch=-6,roll=sgn*18,taper=0.78,taper_y=0.82))
    bevel(add_box(f'pauldron2_{side}',c+Vector((sgn*0.035,0.0,-0.045)),(0.17,0.23,0.075),M['dark'],pitch=-4,roll=sgn*30,taper=0.8,taper_y=0.85))
    bevel(add_box(f'pauldronrim_{side}',c+Vector((sgn*0.055,0.0,-0.10)),(0.14,0.20,0.045),M['steel'],roll=sgn*38,taper=0.85))
    bevel(add_cap(f'kneepad_{side}',knee[side]+Vector((0,-0.06,0.0)),(0.075,0.07,0.075),-0.02,M['steel']))
    bevel(add_cap(f'elbowpad_{side}',elbow[side]+Vector((sgn*0.035,0.02,0.0)),(0.07,0.07,0.07),-0.02,M['dark']))

# helmet
hc=Vector((0,-0.005,1.80))
add_cap('helmet',hc,(0.118,0.132,0.125),-0.06,M['steel'],seg=8,rings=4)
bevel(add_box('brow',(0,-0.105,1.845),(0.195,0.075,0.05),M['dark'],pitch=-12),0.01)
bevel(add_box('mask',(0,-0.105,1.775),(0.175,0.115,0.205),M['steel'],pitch=-4),0.014)
add_box('visor',(0,-0.168,1.815),(0.15,0.02,0.032),M['visor'])
add_box('visorhood',(0,-0.158,1.848),(0.17,0.032,0.022),M['dark'])
add_cyl('respL',(0.055,-0.158,1.705),0.032,0.08,M['steel'],axis=Vector((0,1,0)))
add_cyl('respR',(-0.055,-0.158,1.705),0.032,0.08,M['steel'],axis=Vector((0,1,0)))
add_box('resphose',(0,-0.19,1.70),(0.10,0.03,0.03),M['dark'])
bevel(add_box('cheekL',(0.088,-0.075,1.755),(0.04,0.13,0.15),M['dark'],pitch=-6),0.01)
bevel(add_box('cheekR',(-0.088,-0.075,1.755),(0.04,0.13,0.15),M['dark'],pitch=-6),0.01)
bevel(add_box('jawguard',(0,-0.075,1.675),(0.155,0.15,0.06),M['steel'],pitch=6),0.01)
add_cyl('neck',(0,0.01,1.655),0.075,0.11,M['suit'],axis=Vector((0,0,1)))
add_cyl('collar',(0,0.01,1.575),0.118,0.09,M['dark'],axis=Vector((0,0,1)),seg=14)

# backpack, belt, pouches, tabard
bevel(add_box('backpack',(0,0.165,1.30),(0.26,0.14,0.34),M['dark']),0.015)
bevel(add_box('packspine',(0,0.225,1.30),(0.09,0.05,0.30),M['steel']),0.008)
add_cyl('canL',(0.105,0.20,1.28),0.037,0.22,M['steel'],axis=Vector((0,0,1)),seg=10)
add_cyl('canR',(-0.105,0.20,1.28),0.037,0.22,M['steel'],axis=Vector((0,0,1)),seg=10)
bevel(add_box('packvent',(0,0.17,1.47),(0.16,0.10,0.05),M['dark']),0.008)
add_cyl('bedroll',(0,0.19,1.505),0.045,0.30,M['cloth'],axis=Vector((1,0,0)),seg=10)
hose=[Vector((0.062,-0.205,1.70)),Vector((0.145,-0.075,1.60)),Vector((0.135,0.09,1.45)),Vector((0.105,0.18,1.36))]
for i,(a,b) in enumerate(zip(hose,hose[1:])):
    d=b-a
    add_cyl(f'hose{i}',(a+b)*0.5,0.026,d.length,M['dark'],axis=d.normalized(),seg=8)
# chest insignia + pouches
bevel(add_box('aquila',(0,-0.178,1.335),(0.11,0.02,0.035),M['brass']),0.006)
bevel(add_box('wingL',(0.075,-0.172,1.34),(0.05,0.018,0.02),M['brass'],roll=14),0.005)
bevel(add_box('wingR',(-0.075,-0.172,1.34),(0.05,0.018,0.02),M['brass'],roll=-14),0.005)
bevel(add_box('chestpouchL',(0.115,-0.15,1.24),(0.075,0.055,0.075),M['leather']),0.008)
bevel(add_box('chestpouchR',(-0.115,-0.15,1.24),(0.075,0.055,0.075),M['leather']),0.008)
# pauldron rim band
for side,sgn in (('L',1),('R',-1)):
    c=shoulder[side]
    bevel(add_box(f'pauldronband_{side}',c+Vector((sgn*0.06,0.0,-0.125)),(0.155,0.215,0.022),M['steel'],roll=sgn*38),0.006)
add_cyl('ventL',(0.075,0.242,1.40),0.036,0.06,M['steel'],axis=Vector((0,1,0)))
add_cyl('ventR',(-0.075,0.242,1.40),0.036,0.06,M['steel'],axis=Vector((0,1,0)))
add_box('packtop',(0,0.19,1.50),(0.20,0.11,0.045),M['steel'])
bevel(add_box('chestridge',(0,-0.145,1.33),(0.20,0.05,0.16),M['steel'],pitch=-6),0.012)
bevel(add_box('gorget',(0,-0.02,1.505),(0.26,0.14,0.06),M['dark'],pitch=-8),0.012)
bevel(add_box('strapL',(0.10,-0.135,1.43),(0.05,0.04,0.20),M['leather'],roll=8),0.008)
bevel(add_box('strapR',(-0.10,-0.135,1.43),(0.05,0.04,0.20),M['leather'],roll=-8),0.008)
add_cyl('emblem',(0,-0.172,1.33),0.045,0.018,M['brass'],axis=Vector((0,1,0)),seg=12)
bevel(add_box('holster',(-0.16,-0.02,0.90),(0.08,0.10,0.16),M['leather'],pitch=6),0.01)
for side,sgn in (('L',1),('R',-1)):
    hp,kp=Lm[side]["hip"],Lm[side]["knee"]
    mid=(hp+kp)*0.5
    bevel(add_box(f'thighplate_{side}',mid+Vector((sgn*0.015,-0.095,0.02)),(0.125,0.075,0.32),M['steel'],pitch=-5,taper=0.85),0.012)
    bevel(add_box(f'thighrim_{side}',mid+Vector((sgn*0.015,-0.10,-0.145)),(0.13,0.07,0.05),M['dark'],pitch=-5),0.008)
    sh,el=shoulder[side],elbow[side]
    am=(sh+el)*0.5
    bevel(add_box(f'armplate_{side}',am+Vector((sgn*0.055,0.0,0.0)),(0.075,0.115,0.17),M['steel'],pitch=50,taper=0.8),0.01)
add_cyl('belt',(0,0.0,1.035),0.20,0.05,M['leather'],axis=Vector((0,0,1)),seg=18)
add_box('buckle',(0,-0.152,1.035),(0.07,0.022,0.055),M['brass'])
for i,(x,y) in enumerate([(-0.13,-0.135),(0.0,-0.155),(0.13,-0.135)]):
    add_box(f'pouch{i}',(x,y,0.985),(0.075,0.05,0.095),M['leather'])
    add_box(f'pouchflap{i}',(x,y-0.005,1.035),(0.08,0.055,0.025),M['dark'])
add_box('tabard',(0,-0.15,0.885),(0.135,0.02,0.29),M['cloth'])
for side,sgn in (('L',1),('R',-1)):
    add_box(f'toecap_{side}',(sgn*0.135,-0.115,0.055),(0.105,0.13,0.09),M['dark'])
    add_box(f'sole_{side}',(sgn*0.135,-0.045,0.018),(0.125,0.26,0.035),M['gun'])
add_box('seal',(0.10,-0.155,1.30),(0.035,0.012,0.045),M['brass'])
add_box('sealribbon',(0.10,-0.152,1.255),(0.028,0.008,0.055),M['cloth'])

# ---- P4 rifle built on the posed palms ----
wristR=ae.matrix_world@ae.pose.bones['hand.R'].head
wristL=ae.matrix_world@ae.pose.bones['hand.L'].head
palmR=(ae.matrix_world@ae.pose.bones['hand.R'].head+ae.matrix_world@ae.pose.bones['hand.R'].tail)/2
palmL=(ae.matrix_world@ae.pose.bones['hand.L'].head+ae.matrix_world@ae.pose.bones['hand.L'].tail)/2
axis=(wristL-wristR).normalized(); up0=Vector((0,0,1))
right=axis.cross(up0).normalized(); up=right.cross(axis).normalized()
bore=palmR+up*0.07
frame=Matrix((right,axis,up)).transposed().to_4x4()
print('RIFLE palmR',tuple(round(x,3) for x in palmR),'palmL',tuple(round(x,3) for x in palmL),'axis',tuple(round(x,3) for x in axis),'len',round((palmL-palmR).length,3))
def wbox(t,u,v,s,material,pitch=0.0,taper=1.0,name=None):
    bm=bmesh.new(); ret=bmesh.ops.create_cube(bm,size=1.0); vs=ret['verts']
    bmesh.ops.scale(bm,vec=s,verts=vs)
    if taper!=1.0:
        for vv in vs:
            if vv.co.z>0: vv.co.x*=taper; vv.co.y*=taper
    if pitch: bmesh.ops.transform(bm,matrix=Matrix.Rotation(math.radians(pitch),4,'X'),verts=vs)
    Mw=frame.copy(); Mw.translation=bore+axis*t+right*u+up*v
    bmesh.ops.transform(bm,matrix=Mw,verts=vs)
    return new_obj(name or f'w_{t:+.2f}_{u:+.2f}_{v:+.2f}',bm,material)
def wcyl(t,u,v,r,d,material,pitch=0.0):
    bm=bmesh.new(); bmesh.ops.create_cone(bm,cap_ends=True,segments=10,radius1=r,radius2=r,depth=d)
    R=Matrix.Rotation(math.radians(-90),4,'X')
    bmesh.ops.transform(bm,matrix=R,verts=bm.verts)
    if pitch: bmesh.ops.transform(bm,matrix=Matrix.Rotation(math.radians(pitch),4,'X'),verts=bm.verts)
    Mw=frame.copy(); Mw.translation=bore+axis*t+right*u+up*v
    bmesh.ops.transform(bm,matrix=Mw,verts=bm.verts)
    return new_obj(f'wc_{t:+.2f}',bm,material)
tg=-0.03; thg=0.23
wbox(tg-0.245,0,0.03,(0.075,0.06,0.13),M['gun'])          # buttplate
wbox(tg-0.175,0,0.015,(0.075,0.19,0.11),M['gun'])         # stock
wbox(tg-0.155,0,0.085,(0.065,0.21,0.05),M['gun'])          # comb
wbox(-0.01,0,0.0,(0.095,0.31,0.14),M['gun'])              # receiver
wbox(0.02,0.045,0.015,(0.012,0.08,0.045),M['dark'])       # ejection port
wcyl(0.10,0.052,0.03,0.009,0.055,M['dark'])               # charging handle
wbox(tg,0,-0.095,(0.055,0.075,0.15),M['dark'],pitch=16)   # pistol grip
wbox(0.03,0,-0.19,(0.075,0.13,0.20),M['gun'],pitch=-9)     # magazine
wbox(0.035,0,-0.17,(0.062,0.075,0.02),M['brass'],pitch=-9) # mag base
wbox(0.0,0,-0.065,(0.035,0.09,0.014),M['gun'])            # trigger guard
wbox(thg,0,-0.02,(0.08,0.34,0.125),M['dark'])            # handguard
wbox(thg+0.02,0.038,-0.02,(0.012,0.24,0.075),M['gun'])    # rail R
wbox(thg+0.02,-0.038,-0.02,(0.012,0.24,0.075),M['gun'])   # rail L
wbox(thg+0.18,0,0.0,(0.045,0.06,0.06),M['gun'])           # gas block
wcyl(thg+0.40,0,0.0,0.030,0.52,M['gun'])                  # barrel
wcyl(thg+0.69,0,0.0,0.042,0.10,M['dark'])                 # muzzle
wbox(thg+0.26,0,0.04,(0.02,0.04,0.06),M['dark'])
wbox(thg+0.40,0,-0.005,(0.06,0.14,0.06),M['dark'])       # front sight
wbox(-0.03,0,0.085,(0.035,0.045,0.04),M['dark'])          # rear sight
wbox(-0.02,0,0.115,(0.05,0.20,0.05),M['dark'])            # scope body
wbox(-0.02,0.0,0.085,(0.035,0.07,0.05),M['steel'])        # scope mount
wcyl(-0.02+0.075,0,0.115,0.028,0.03,M['gun'])   # scope objective
wcyl(-0.02-0.085,0,0.115,0.024,0.03,M['gun'])    # scope ocular
wbox(0.05,0,-0.075,(0.02,0.46,0.016),M['leather'])        # sling strap
wcyl(tg-0.19,0,-0.03,0.012,0.03,M['dark'],pitch=90)       # sling loop rear
# gauntlet fists wrapping the weapon (weapon-frame boxes)
wbox(tg,0,-0.03,(0.115,0.13,0.115),M['steel'],taper=0.82,name='fistR')
wbox(tg+0.075,0,-0.015,(0.10,0.045,0.115),M['dark'])
wbox(thg+0.02,0,-0.035,(0.115,0.14,0.12),M['steel'],taper=0.82,name='fistL')
wbox(thg+0.105,0,-0.02,(0.105,0.05,0.12),M['dark'])
for v in (-0.05,-0.012,0.026):
    wbox(tg+0.068,0,v,(0.02,0.095,0.014),M['dark'])
    wbox(thg+0.02+0.077,0,v,(0.02,0.10,0.014),M['dark'])
bevel(add_box('cuffR',wristR,(0.11,0.11,0.09),M['dark'],pitch=10),0.008)
bevel(add_box('cuffL',wristL,(0.11,0.11,0.09),M['dark'],pitch=-6),0.008)
wcyl(thg+0.14,0,-0.06,0.012,0.03,M['dark'],pitch=90)      # sling loop front

# ---- bind gear, join, keyframe aim/idle, export ----
def bone_for(n):
    l=n.lower()
    if l.startswith('fistr'): return 'hand.R'
    if l.startswith('fistl'): return 'hand.L'
    if l.startswith('w_') or l.startswith('wpn'): return 'hand.R'
    for k in ('helmet','mask','visor','brow','resp','cheek','jaw','crest','neck','collar','hood','hose'):
        if l.startswith(k): return 'spine.006'
    for s in ('L','R'):
        sf=s.lower()
        if l.startswith(('pauldron',)) and l.endswith(sf): return f'shoulder.{s}'
        if l.startswith(('armplate','elbowpad')) and l.endswith(sf): return f'upper_arm.{s}'
        if l.startswith(('cuff',)) and l.endswith(sf): return f'forearm.{s}'
        if l.startswith(('thighplate','thighrim')) and l.endswith(sf): return f'thigh.{s}'
        if l.startswith(('kneepad','greave','shin')) and l.endswith(sf): return f'shin.{s}'
        if l.startswith(('boot','toecap','sole')) and l.endswith(sf): return f'foot.{s}'
    for k in ('backpack','packspine','packvent','can','bedroll','antenna','vent','aquila','wing','emblem','chest','strap','gorget','cuirass','seal'):
        if l.startswith(k): return 'spine.003'
    for k in ('belt','buckle','pouch','tabard','holster','tasset'):
        if l.startswith(k): return 'spine'
    return 'spine.003'

# pose delta per bone: gear authored at posed positions must be pre-transformed
# by the inverse delta so the armature's aim pose lands it back on the body.
D={}
for b in arm.data.bones:
    pb=arm.pose.bones.get(b.name)
    if pb: D[b.name]=pb.matrix @ b.matrix_local.inverted()
gear=[o for o in bpy.data.objects if o.type=='MESH' and o is not body]
for o in gear:
    if o.vertex_groups and any(m.type=='ARMATURE' for m in o.modifiers):
        continue
    bn=bone_for(o.name)
    if bn in D:
        inv=D[bn].inverted()
        for v in o.data.vertices: v.co=inv @ v.co
    vg=o.vertex_groups.new(name=bn)
    vg.add(list(range(len(o.data.vertices))),1.0,'REPLACE')
bpy.ops.object.select_all(action='DESELECT')
for o in gear: o.select_set(True)
body.select_set(True); bpy.context.view_layer.objects.active=body
bpy.ops.object.join()
print('JOINED tris',len(body.data.polygons),'verts',len(body.data.vertices),'slots',[m.name for m in body.data.materials])

# pose as an aim action (and idle) so the master render can pose it
arm.animation_data_create()
act=bpy.data.actions.new('aim'); arm.animation_data.action=act
bpy.context.view_layer.objects.active=arm
bpy.ops.object.mode_set(mode='POSE')
bpy.ops.pose.select_all(action='SELECT')
bpy.ops.nla.bake(frame_start=1,frame_end=1,step=1,only_selected=False,
                 visual_keying=True,clear_constraints=True,clear_parents=False,
                 use_current_action=True,bake_types={'POSE'})
bpy.ops.object.mode_set(mode='OBJECT')
print('BAKED aim keyframes')
for _n in ('idle','walk','run','fire','reload','hit','death','melee'):
    _a=act.copy(); _a.name=_n
bpy.context.scene.frame_set(1)

if A.export:
    uid=A.id or A.unit
    out=Path(A.out) if A.out else Path('output/units')/A.faction/uid
    out.mkdir(parents=True,exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True); arm.select_set(True)
    bpy.context.view_layer.objects.active=arm
    dest=out/f'{uid}_rigged.glb'
    bpy.ops.export_scene.gltf(filepath=str(dest),export_format='GLB',use_selection=True,
        export_animations=True,export_animation_mode='ACTIONS',export_anim_slide_to_zero=True)
    print('EXPORTED',dest)

if A.render:
  # ---- render ----
  mat_bg=(0.10,0.11,0.13)
  world=bpy.data.worlds.new('w'); world.use_nodes=True
  world.node_tree.nodes['Background'].inputs[0].default_value=(*mat_bg,1); world.node_tree.nodes['Background'].inputs[1].default_value=0.35
  bpy.context.scene.world=world
  key=bpy.data.lights.new('key','AREA'); key.energy=320; key.size=4
  ko=bpy.data.objects.new('key',key); ko.location=(2,-3,4); ko.rotation_euler=(0.7,0.2,0.5); bpy.context.collection.objects.link(ko)
  rim=bpy.data.lights.new('rim','AREA'); rim.energy=220; rim.size=3
  ro=bpy.data.objects.new('rim',rim); ro.location=(-3,2,3); ro.rotation_euler=(1.1,0,-2.2); bpy.context.collection.objects.link(ro)
  fill=bpy.data.lights.new('fill','AREA'); fill.energy=90; fill.size=5
  fo=bpy.data.objects.new('fill',fill); fo.location=(0,-3,-1); fo.rotation_euler=(1.4,0,0); bpy.context.collection.objects.link(fo)
  cam_data=bpy.data.cameras.new('cam'); cam_data.type='ORTHO'; cam_data.ortho_scale=2.35
  cam=bpy.data.objects.new('cam',cam_data); bpy.context.collection.objects.link(cam); bpy.context.scene.camera=cam
  centre=Vector((0,0,0.95))
  for name,off in {'front':(0,-4,0),'side':(4,0,0),'threeq':(3,-3,0.4)}.items():
      cam.location=centre+Vector(off); cam.rotation_euler=(centre-cam.location).to_track_quat('-Z','Y').to_euler()
      sc=bpy.context.scene; sc.render.engine='BLENDER_EEVEE'
      sc.render.resolution_x=420; sc.render.resolution_y=560; sc.render.filepath=f'/tmp/cmp3d/unit_{name}.png'
      sc.view_settings.view_transform='Standard'
      bpy.ops.render.render(write_still=True)
  deps=bpy.context.evaluated_depsgraph_get(); total=0
  for o in bpy.context.scene.objects:
      if o.type=='MESH':
          eo=o.evaluated_get(deps); me=eo.to_mesh()
          total+=sum(len(p.vertices)-2 for p in me.polygons); eo.to_mesh_clear()
  print('TOTAL TRIS',total)
  print('DONE')
