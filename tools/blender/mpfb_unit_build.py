"""mpfb_unit_build.py — pixel unit from the MakeHuman MPFB base and standard rig.

Standards route: a real human base with an anatomical skeleton (137 bones incl.
5x3 finger bones), skin weights, decimation after rigging, gear built to the
skeleton, pose solved with IK and baked. Replaces the CC0-base centroid-fit
metarig route (see docs/CHARACTER_PIPELINE.md).
"""
import argparse, bpy, math, addon_utils, statistics, json
from pathlib import Path
from mathutils import Vector, Matrix

_argv=__import__('sys').argv
_args=_argv[_argv.index('--')+1:] if '--' in _argv else []
_ap=argparse.ArgumentParser()
_ap.add_argument('--faction', default='iron_directorate')
_ap.add_argument('--unit', default='line_infantry')
_ap.add_argument('--id', default=None)
_ap.add_argument('--out', default=None)
_ap.add_argument('--decimate', type=float, default=0.34)
_ap.add_argument('--height', type=float, default=1.90)
_ap.add_argument('--render', action='store_true')
_ap.add_argument('--export', action='store_true')
_ap.add_argument('--helm', default=None); _ap.add_argument('--shoulders', default=None)
_ap.add_argument('--back', default=None); _ap.add_argument('--weapon', default=None)
_ap.add_argument('--cloak', action='store_true'); _ap.add_argument('--robe', action='store_true')
_ap.add_argument('--crest', action='store_true'); _ap.add_argument('--horns', action='store_true')
_ap.add_argument('--shield', default=None)
A=_ap.parse_args(_args)
_CFG_PATH=Path('configs/units')/f'{A.faction}.json'
_CFG=json.loads(_CFG_PATH.read_text()).get('units',{}).get(A.unit,{}) if _CFG_PATH.exists() else {}
def _v(n,d): return getattr(A,n,None) or _CFG.get(n,d)
HELM=_v('helm','visor'); SHOULDERS=_v('shoulders','block'); BACK=_v('back','pack')
WEAPON=_v('weapon','rifle'); SHIELD=_v('shield',None)
print('FLAGS ROBE',bool(A.robe or _CFG.get('robe')),'CLOAK',bool(A.cloak or _CFG.get('cloak')))
CLOAK=bool(A.cloak or _CFG.get('cloak')); ROBE=bool(A.robe or _CFG.get('robe'))
CREST=bool(A.crest or _CFG.get('crest')); HORNS=bool(A.horns or _CFG.get('horns'))
BODY=_v('body','standard')
HEIGHT={'light':1.82,'standard':A.height,'heavy':1.98,'monolith':2.15}.get(BODY,A.height)
HS=HEIGHT/1.90

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.preferences.addon_enable(module='bl_ext.user_default.mpfb')
bpy.ops.mpfb.create_human()
body=bpy.data.objects['Human']
bpy.context.view_layer.objects.active=body
try:
    bpy.context.scene.mpfb_macropanel_gender=1.0
    bpy.context.scene.mpfb_macropanel_muscle=0.45
    print('GENDER set',bpy.context.scene.mpfb_macropanel_gender)
except Exception as _e:
    print('GENDER skip',_e)
# scale the mesh to the target height BEFORE rigging, so the rig is generated
# for the final proportions and the skin bind is correct
lo=min(v.co.z for v in body.data.vertices); hi=max(v.co.z for v in body.data.vertices)
s=HEIGHT/(hi-lo)
body.scale=(s,s,s); body.location=(body.location.x,body.location.y,body.location.z*s)
bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
bpy.context.view_layer.objects.active=body
bpy.ops.mpfb.add_standard_rig()
arm=[o for o in bpy.data.objects if o.type=='ARMATURE'][0]
print('MPFB human verts',len(body.data.vertices),'bones',len(arm.data.bones))
# uniform decimate. Vertex-group protection and hand separation were both
# measured to fight the ratio (0.20 and 0.34 produced near-identical counts), so
# the body is decimated plainly; the anatomy gate measures the result.
if A.decimate>0 and A.decimate<1.0:
    if body.data.shape_keys: body.shape_key_clear()
    bpy.context.view_layer.objects.active=body
    dm=body.modifiers.new('dec','DECIMATE'); dm.ratio=A.decimate; dm.use_collapse_triangulate=True
    bpy.ops.object.modifier_apply(modifier=dm.name)
    print('DECIMATED ratio',A.decimate,'polys',len(body.data.polygons),'verts',len(body.data.vertices))
# landmarks from the skeleton (anatomical joints, not surface centroids)
def bh(n): return arm.data.bones[n].head_local.copy()
def bt(n): return arm.data.bones[n].tail_local.copy()
Lm={}
for side in ('L','R'):
    Lm[side]={'shoulder':bh(f'upperarm01.{side}'),'elbow':bh(f'lowerarm01.{side}'),
              'wrist':bh(f'wrist.{side}'),'hand':bt(f'wrist.{side}'),
              'hip':bh(f'upperleg01.{side}'),'knee':bh(f'lowerleg01.{side}'),
              'ankle':bh(f'foot.{side}'),'toe':bh(f'toe1-1.{side}')}
print('LANDMARKS',{k:(round(v.x,3),round(v.y,3),round(v.z,3)) for k,v in Lm['L'].items()})
# ---------------- P2 pose ----------------
BLADE = WEAPON in ('blade','chainblade')
if BLADE:
    stock=Vector((-0.10,-0.28,1.34))
    grip=Vector((-0.14,-0.30,1.34))
    fore=Vector((0.19,-0.02,1.02))
    muzzle=Vector((0.0,0.0,0.0))
    axis=Vector((0.0,-1.0,0.0))
    poles={'R':Vector((-0.45,0.05,1.15)),'L':Vector((0.45,0.12,1.05))}
else:
    stock=Vector((-0.18,0.06,1.44))
    axis=Vector((0.50,-0.86,-0.02)).normalized()
    grip=stock+axis*0.21+Vector((0,0,-0.07))
    fore=stock+axis*0.44+Vector((0,0,-0.05))
    muzzle=stock+axis*0.82
    poles={'R':Vector((-0.45,0.10,1.20)),'L':Vector((0.40,-0.10,1.15))}
print('WEAPON stock',stock,'grip',grip,'fore',fore,'muzzle',muzzle,'sep',(fore-grip).length)
targets={'R':grip,'L':fore}
bpy.context.view_layer.objects.active=arm; bpy.ops.object.mode_set(mode='POSE')
for side in ('R','L'):
    tgt=bpy.data.objects.new(f'ik_{side}',None); tgt.location=targets[side]; bpy.context.collection.objects.link(tgt)
    pol=bpy.data.objects.new(f'pole_{side}',None); pol.location=poles[side]; bpy.context.collection.objects.link(pol)
    pb=arm.pose.bones[f'lowerarm02.{side}']
    c=pb.constraints.new('IK'); c.target=tgt; c.chain_count=4; c.pole_target=pol; c.pole_angle=(0.0 if side=='R' else math.pi)
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()
deps=bpy.context.evaluated_depsgraph_get(); ae=arm.evaluated_get(deps)
for side in ('R','L'):
    h=ae.matrix_world@ae.pose.bones[f'wrist.{side}'].head
    print(f'HAND {side} at ({h.x:+.3f},{h.y:+.3f},{h.z:+.3f}) target ({targets[side].x:+.3f},{targets[side].y:+.3f},{targets[side].z:+.3f}) err={(h-targets[side]).length:.3f}')
# ---- curl the real finger bones around the grip ----
for side in ('L','R'):
    for f in range(1,6):
        for k,ang in ((1,55),(2,65),(3,45)):
            pb=arm.pose.bones.get(f'finger{f}-{k}.{side}')
            if pb:
                pb.rotation_mode='XYZ'
                pb.rotation_euler.z=math.radians(-ang)
bpy.context.view_layer.update()

# ================= P3/P4 armour + weapon =================
import bmesh
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
    if len(d.data.polygons)>200:
        dm=d.modifiers.new('dec','DECIMATE'); dm.ratio=max(dec,0.50)
    if material:
        d.data.materials.clear(); d.data.materials.append(material)
    return d

L=Lm
def torso_ok(p): return 1.0<p.z<1.5 and math.hypot(p.x,p.y)<0.30
dup_region('cuirass',torso_ok,0.024,0.20,M['steel'])
for i,(z0,z1) in enumerate([(1.03,1.085),(1.095,1.15),(1.16,1.215)]):
    dup_region(f'lame{i}',lambda p,z0=z0,z1=z1: z0<p.z<z1 and abs(p.x)<0.28 and -0.24<p.y<0.24,0.018,0.35,M['dark'])
for side,sgn in (('L',1),('R',-1)):
    dup_region(f'tasset_{side}',lambda p,sgn=sgn: 0.84<p.z<1.03 and 0.03<sgn*p.x<0.28 and p.y<0.12,0.02,0.35,M['steel'])
    a,b=Lm[side]['hip'],Lm[side]['knee']
    dup_region(f'thighsuit_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.095 and 0.08<segd(p,a,b)[1]<0.92,0.012,0.30,M['dark'])
    dup_region(f'thighplate_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.095 and 0.12<segd(p,a,b)[1]<0.85 and p.y<0.0,0.02,0.35,M['steel'])
    a,b=Lm[side]['knee'],Lm[side]['ankle']
    dup_region(f'greave_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.09 and 0.10<segd(p,a,b)[1]<0.92 and p.y<0.02,0.022,0.35,M['steel'])
    a,b=Lm[side]['shoulder'],Lm[side]['elbow']
    dup_region(f'rerebrace_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.085 and 0.20<segd(p,a,b)[1]<0.95,0.016,0.35,M['dark'])
    a,b=Lm[side]['elbow'],Lm[side]['wrist']
    dup_region(f'vambrace_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.08 and 0.25<segd(p,a,b)[1]<0.98,0.02,0.35,M['dark'])
    a,b=Lm[side]['wrist'],Lm[side]['hand']
    dup_region(f'gauntlet_{side}',lambda p,a=a,b=b: segd(p,a,b)[0]<0.085 and 0.0<segd(p,a,b)[1]<0.85,0.018,0.35,M['steel'])
    dup_region(f'boot_{side}',lambda p,sgn=sgn: p.z<0.16 and 0.02<sgn*p.x<0.28,0.028,0.4,M['dark'])

# ---- posed joint positions for rigid plates ----
deps=bpy.context.evaluated_depsgraph_get(); ae=arm.evaluated_get(deps)
def pj(n,head=True):
    b=ae.pose.bones[n]; return ae.matrix_world@(b.head if head else b.tail)
shoulder={s:pj(f'upperarm02.{s}') for s in ('L','R')}
elbow={s:pj(f'lowerarm02.{s}') for s in ('L','R')}
knee={s:pj(f'lowerleg02.{s}') for s in ('L','R')}
hand_b={s:ae.matrix_world@ae.pose.bones[f'wrist.{s}'].head for s in ('L','R')}
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

def add_cone(name,c,r1,r2,d,material,seg=12):
    bm=bmesh.new(); bmesh.ops.create_cone(bm,cap_ends=True,segments=seg,radius1=r1,radius2=r2,depth=d)
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
def rm(names):
    for n in names:
        o=bpy.data.objects.get(n)
        if o: bpy.data.objects.remove(o,do_unlink=True)
for side,sgn in (('L',1),('R',-1)):
    c=shoulder[side]
    bevel(add_box(f'pauldron_{side}',c+Vector((sgn*0.0,0.0,0.015)),(0.16,0.22,0.08),M['steel'],pitch=-6,roll=sgn*18,taper=0.78,taper_y=0.82))
    bevel(add_box(f'pauldron2_{side}',c+Vector((sgn*0.02,0.0,-0.045)),(0.145,0.20,0.065),M['dark'],pitch=-4,roll=sgn*30,taper=0.8,taper_y=0.85))
    bevel(add_box(f'pauldronrim_{side}',c+Vector((sgn*0.035,0.0,-0.10)),(0.12,0.17,0.04),M['steel'],roll=sgn*38,taper=0.85))
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
for _n in ('helmet','brow','mask','visor','visorhood','respL','respR','resphose','cheekL','cheekR','jawguard'):
    _o=bpy.data.objects.get(_n)
    if _o:
        _c=Vector((0,0,1.79))
        for _v in _o.data.vertices: _v.co=(_v.co-_c)*0.86+_c
if HELM=='cap':
    rm(['mask','visor','visorhood','respL','respR','resphose','jawguard','cheekL','cheekR','brow'])
    add_cyl('brim',(0,-0.02,1.835),0.165,0.02,M['steel'],axis=Vector((0,0,1)),seg=12)
    bevel(add_box('chin',(0,-0.09,1.70),(0.13,0.08,0.04),M['dark']),0.008)
elif HELM=='brim':
    add_cyl('brim',(0,-0.02,1.845),0.21,0.028,M['steel'],axis=Vector((0,0,1)),seg=14)
elif HELM=='slab':
    rm(['mask','visor','visorhood','cheekL','cheekR'])
    bevel(add_box('slab',(0,-0.10,1.77),(0.19,0.10,0.20),M['steel'],pitch=-4),0.014)
    add_box('slabvisor',(0,-0.16,1.80),(0.16,0.02,0.024),M['visor'])
elif HELM=='hood':
    rm(['helmet','brow','mask','visor','visorhood','respL','respR','resphose','cheekL','cheekR','jawguard'])
    add_cap('hood',(0,0.0,1.80),(0.145,0.155,0.15),-0.10,M['cloth'],seg=10,rings=5)
    bevel(add_box('hoodmask',(0,-0.10,1.755),(0.16,0.11,0.17),M['dark'],pitch=-4),0.012)
    add_box('eyeL',(0.045,-0.158,1.80),(0.04,0.02,0.018),M['visor'])
    add_box('eyeR',(-0.045,-0.158,1.80),(0.04,0.02,0.018),M['visor'])
if CREST:
    bevel(add_box('crest',(0,0.01,1.905),(0.03,0.16,0.055),M['brass']),0.008)
if HORNS:
    for sgn in (1,-1):
        add_cyl(f'horn{sgn}',(sgn*0.10,0.0,1.91),0.032,0.24,M['dark'],axis=Vector((sgn*0.5,0.1,1.0)),seg=8)

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
bevel(add_box('chestpouchL',(0.145,-0.13,1.24),(0.075,0.055,0.075),M['leather']),0.008)
bevel(add_box('chestpouchR',(-0.145,-0.13,1.24),(0.075,0.055,0.075),M['leather']),0.008)
# pauldron rim band
for side,sgn in (('L',1),('R',-1)):
    c=shoulder[side]
    bevel(add_box(f'pauldronband_{side}',c+Vector((sgn*0.06,0.0,-0.125)),(0.155,0.215,0.022),M['steel'],roll=sgn*38),0.006)
if SHOULDERS=='none':
    rm([f'{p}_{s}' for p in ('pauldron','pauldron2','pauldronrim','pauldronband') for s in ('L','R')])
elif SHOULDERS=='plate':
    rm([f'{p}_{s}' for p in ('pauldron2','pauldronrim','pauldronband') for s in ('L','R')])
elif SHOULDERS=='asym':
    rm(['pauldron2_R','pauldronrim_R','pauldronband_R','pauldron_R'])
    c=shoulder['L']
    bevel(add_box('pauldronbig_L',c+Vector((0.02,0.0,0.01)),(0.24,0.30,0.13),M['steel'],pitch=-8,roll=22,taper=0.75),0.014)
    for i,(dx,dy,dz) in enumerate([(0.10,-0.06,0.08),(0.13,0.04,0.06),(0.07,0.12,0.04)]):
        add_cyl(f'spike{i}',c+Vector((dx,dy,dz)),0.03,0.16,M['dark'],axis=Vector((0.7,dy,0.7)),seg=6)
add_cyl('ventL',(0.075,0.242,1.40),0.036,0.06,M['steel'],axis=Vector((0,1,0)))
add_cyl('ventR',(-0.075,0.242,1.40),0.036,0.06,M['steel'],axis=Vector((0,1,0)))
add_box('packtop',(0,0.19,1.50),(0.20,0.11,0.045),M['steel'])
if BACK=='none':
    rm(['backpack','packspine','canL','canR','packvent','bedroll','ventL','ventR','packtop'])
elif BACK=='jump':
    for sgn in (1,-1):
        add_cyl(f'thruster{sgn}',(sgn*0.11,0.19,1.24),0.055,0.20,M['dark'],axis=Vector((0,0,1)),seg=10)
        add_cyl(f'nozzle{sgn}',(sgn*0.11,0.19,1.13),0.045,0.06,M['gun'],axis=Vector((0,0,1)),seg=10)
elif BACK=='ammo':
    rm(['canL','canR','bedroll'])
    bevel(add_box('ammobox',(0,0.24,1.30),(0.30,0.14,0.30),M['dark']),0.012)
    for i in range(4):
        add_cyl(f'round{i}',(0.10-i*0.06,0.295,1.30),0.020,0.24,M['brass'],axis=Vector((0,0,1)),seg=6)
elif BACK=='servo':
    rm(['canR','bedroll'])
    for i,(a,b) in enumerate([((0.12,0.22,1.45),(0.28,0.10,1.55)),((0.28,0.10,1.55),(0.34,-0.08,1.36)),((0.34,-0.08,1.36),(0.30,-0.20,1.20))]):
        d=Vector(b)-Vector(a); add_cyl(f'servo{i}',(Vector(a)+Vector(b))/2,0.032,d.length,M['steel'],axis=d.normalized(),seg=8)
elif BACK=='banner':
    add_cyl('bannerpole',(0.10,0.20,1.55),0.028,1.0,M['dark'],axis=Vector((0,0,1)),seg=8)
    add_box('bannercloth',(0.10,0.18,1.85),(0.03,0.28,0.36),M['cloth'])
bevel(add_box('chestridge',(0,-0.145,1.33),(0.20,0.05,0.16),M['steel'],pitch=-6),0.012)
bevel(add_box('gorget',(0,-0.02,1.505),(0.26,0.14,0.06),M['dark'],pitch=-8),0.012)
bevel(add_box('strapL',(0.10,-0.135,1.43),(0.05,0.04,0.20),M['leather'],roll=8),0.008)
bevel(add_box('strapR',(-0.10,-0.135,1.43),(0.05,0.04,0.20),M['leather'],roll=-8),0.008)
add_cyl('emblem',(0,-0.172,1.33),0.045,0.018,M['brass'],axis=Vector((0,1,0)),seg=12)
bevel(add_box('holster',(-0.14,-0.02,0.90),(0.08,0.10,0.16),M['leather'],pitch=6),0.01)
for side,sgn in (('L',1),('R',-1)):
    hp,kp=Lm[side]["hip"],Lm[side]["knee"]
    mid=(hp+kp)*0.5
    bevel(add_box(f'thighplate_{side}',mid+Vector((sgn*0.015,-0.095,0.02)),(0.125,0.075,0.32),M['steel'],pitch=-5,taper=0.85),0.012)
    bevel(add_box(f'thighrim_{side}',mid+Vector((sgn*0.015,-0.10,-0.145)),(0.13,0.07,0.05),M['dark'],pitch=-5),0.008)
    sh,el=shoulder[side],elbow[side]
    am=(sh+el)*0.5
    bevel(add_box(f'armplate_{side}',am+Vector((sgn*0.055,0.0,0.0)),(0.075,0.115,0.17),M['steel'],pitch=50,taper=0.8),0.01)
add_cyl('belt',(0,0.0,1.035),0.19,0.05,M['leather'],axis=Vector((0,0,1)),seg=18)
add_box('buckle',(0,-0.152,1.035),(0.07,0.022,0.055),M['brass'])
for i,(x,y) in enumerate([(-0.13,-0.135),(0.0,-0.155),(0.13,-0.135)]):
    add_box(f'pouch{i}',(x,y,0.985),(0.075,0.05,0.095),M['leather'])
    add_box(f'pouchflap{i}',(x,y-0.005,1.035),(0.08,0.055,0.025),M['dark'])
add_box('tabard',(0,-0.13,0.885),(0.135,0.02,0.29),M['cloth'])
if ROBE:
    add_cone('robe',(0,0.0,0.62*HS),0.27*HS,0.18*HS,0.86*HS,M['cloth'],seg=14)
    add_box('robesash',(0,-0.02,1.02),(0.30,0.30,0.06),M['leather'])
if CLOAK:
    bevel(add_box('cloak',(0,0.17*HS,1.05*HS),(0.38*HS,0.03,0.95*HS),M['cloth'],pitch=4),0.01)
    add_box('cloakcollar',(0,0.10,1.52),(0.36,0.10,0.08),M['dark'])
if SHIELD=='tower':
    bevel(add_box('shield',(0.30,-0.16,1.14),(0.06,0.34,0.64),M['steel'],pitch=6,roll=8),0.014)
    add_box('shieldboss',(0.34,-0.16,1.14),(0.03,0.10,0.10),M['brass'])
for side in ('L','R'):
    _ax=Lm[side]['ankle'].x
    _ay=Lm[side]['ankle'].y; _ty=Lm[side]['toe'].y; _tz=Lm[side]['toe'].z
    _len=abs(_ty-_ay)
    add_box(f'toecap_{side}',(_ax,_ty-0.02,_tz+0.045),(0.105,0.12,0.08),M['dark'])
    add_box(f'sole_{side}',(_ax,(_ay+_ty)/2,_tz+0.012),(0.125,_len+0.10,0.028),M['gun'])
add_box('seal',(0.10,-0.155,1.30),(0.035,0.012,0.045),M['brass'])
add_box('sealribbon',(0.10,-0.152,1.255),(0.028,0.008,0.055),M['cloth'])

# ---- P4 rifle built on the posed palms ----
wristR=ae.matrix_world@ae.pose.bones['wrist.R'].head
wristL=ae.matrix_world@ae.pose.bones['wrist.L'].head
palmR=ae.matrix_world@ae.pose.bones['wrist.R'].tail+(ae.matrix_world@ae.pose.bones['wrist.R'].tail-ae.matrix_world@ae.pose.bones['wrist.R'].head).normalized()*0.025
palmL=ae.matrix_world@ae.pose.bones['wrist.L'].tail+(ae.matrix_world@ae.pose.bones['wrist.L'].tail-ae.matrix_world@ae.pose.bones['wrist.L'].head).normalized()*0.025
if BLADE:
    axis=Vector((-0.12,-0.58,0.81)).normalized(); up0=Vector((0,0,1))
    right=axis.cross(up0).normalized(); up=right.cross(axis).normalized()
    bore=palmR
else:
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
if WEAPON=='longrifle': BL,BR,ML,SC=0.78,0.034,0.10,True
elif WEAPON=='heavy_stubber': BL,BR,ML,SC=0.30,0.048,0.12,False
elif WEAPON=='autocannon': BL,BR,ML,SC=0.62,0.055,0.14,False
else: BL,BR,ML,SC=0.52,0.030,0.10,True
if BLADE:
    wcyl(-0.16,0,0,0.024,0.20,M['leather'])                 # grip
    wcyl(-0.27,0,0,0.034,0.06,M['brass'])                   # pommel
    wbox(0.02,0,0,(0.16,0.06,0.05),M['brass'])              # guard
    wbox(0.34,0,0,(0.025,0.56,0.10),M['steel'],taper=0.92)  # blade
    wbox(0.64,0,0,(0.02,0.08,0.06),M['steel'])              # tip
    if WEAPON=='chainblade':
        wbox(0.34,0.035,0,(0.02,0.52,0.10),M['gun'])        # spine
        for i in range(8):
            wbox(0.14+i*0.06,-0.062,0,(0.02,0.04,0.03),M['gun'])
        wcyl(-0.02,0.05,0,0.045,0.14,M['dark'],pitch=90)    # motor
    wbox(0.0,0,0,(0.11,0.13,0.115),M['steel'],taper=0.82,name='fistR')
    bevel(add_box('fistL',palmL,(0.10,0.12,0.11),M['steel'],taper=0.85),0.01)
    bevel(add_box('cuffR',wristR,(0.11,0.11,0.09),M['dark']),0.008)
    bevel(add_box('cuffL',wristL,(0.11,0.11,0.09),M['dark']),0.008)
else:
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
    wcyl(thg+0.14+BL/2,0,0.0,BR,BL,M['gun'])                   # barrel
    wcyl(thg+0.14+BL-0.02,0,0.0,BR*1.35,ML,M['dark'])          # muzzle
    wbox(thg+0.26,0,0.04,(0.02,0.04,0.06),M['dark'])
    wbox(thg+0.14+BL*0.55,0,-0.005,(0.06,0.14,0.06),M['dark']) # front sight
    wbox(-0.03,0,0.085,(0.035,0.045,0.04),M['dark'])          # rear sight
    if SC: wbox(-0.02,0,0.115,(0.05,0.20,0.05),M['dark'])            # scope body
    if SC: wbox(-0.02,0.0,0.085,(0.035,0.07,0.05),M['steel'])        # scope mount
    if SC: wcyl(-0.02+0.075,0,0.115,0.028,0.03,M['gun'])   # scope objective
    if SC: wcyl(-0.02-0.085,0,0.115,0.024,0.03,M['gun'])    # scope ocular
    wbox(0.05,0,-0.075,(0.02,0.46,0.016),M['leather'])        # sling strap
    wcyl(tg-0.19,0,-0.03,0.012,0.03,M['dark'],pitch=90)       # sling loop rear
    # gauntlet fists wrapping the weapon (weapon-frame boxes)
    bevel(add_box('cuffR',wristR,(0.11,0.11,0.09),M['dark'],pitch=10),0.008)
    bevel(add_box('cuffL',wristL,(0.11,0.11,0.09),M['dark'],pitch=-6),0.008)
    wcyl(thg+0.14,0,-0.06,0.012,0.03,M['dark'],pitch=90)      # sling loop front

if not A.render:
    # ---- bind gear, join, keyframe aim/idle, export ----
    def bone_for(n):
        l=n.lower()
        if l.startswith(('fistr','w_','wpn')): return 'wrist.R'
        if l.startswith('fistl'): return 'wrist.L'
        for k in ('helmet','mask','visor','brow','resp','cheek','jaw','crest','neck','collar','hood','hose','brim','chin','slab','horn','eye'):
            if l.startswith(k): return 'head'
        for s in ('L','R'):
            sf=s.lower()
            if l.startswith(('pauldron',)) and l.endswith(sf): return f'upperarm01.{s}'
            if l.startswith(('armplate','elbowpad')) and l.endswith(sf): return f'upperarm02.{s}'
            if l.startswith(('cuff','shield')) and l.endswith(sf): return f'lowerarm02.{s}'
            if l.startswith(('thighplate','thighrim')) and l.endswith(sf): return f'upperleg02.{s}'
            if l.startswith(('kneepad','greave','shin')) and l.endswith(sf): return f'lowerleg02.{s}'
            if l.startswith(('boot','toecap','sole')) and l.endswith(sf): return f'foot.{s}'
        for k in ('backpack','packspine','packvent','can','bedroll','antenna','vent','aquila','wing','emblem','chest','strap','gorget','cuirass','seal','thruster','nozzle','ammo','round','servo','banner'):
            if l.startswith(k): return 'spine04'
        for k in ('belt','buckle','pouch','tabard','holster','tasset','robe','cloak'):
            if l.startswith(k): return 'pelvis.L'
        return 'spine04'
        for k in ('belt','buckle','pouch','tabard','holster','tasset','robe','cloak'):
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
    print('GEARNAMES',[o.name for o in gear])
    for o in gear: o.select_set(True)
    body.select_set(True); bpy.context.view_layer.objects.active=body
    bpy.ops.object.join()
    print('JOINED tris',len(body.data.polygons),'verts',len(body.data.vertices),'slots',[m.name for m in body.data.materials])

    # pose as an aim action (and idle) so the master render can pose it
    arm.animation_data_create()
    act=bpy.data.actions.new('aim'); arm.animation_data.action=act
    bpy.context.view_layer.objects.active=arm
    # bake the IK result into the action and drop the constraints, otherwise the
    # exporter writes the constrained pose as the "rest" node transforms and every
    # bone-to-mesh measurement is meaningless.
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.nla.bake(frame_start=1,frame_end=1,step=1,only_selected=False,
                     visual_keying=True,clear_constraints=True,clear_parents=False,
                     use_current_action=True,bake_types={'POSE'})
    bpy.ops.object.mode_set(mode='OBJECT')
    print('BAKED aim action, constraints cleared')
    for _n in ('idle','walk','run','fire','reload','hit','death','melee'):
        _a=act.copy(); _a.name=_n
    bpy.context.scene.frame_set(1)
    # ship the GLB in BIND pose: the aim pose lives only in the action. Exporting
    # the posed skeleton made every bone-to-mesh check meaningless and gave the
    # model a default aim state instead of a rest state.
    arm.animation_data.action=None
    bpy.context.view_layer.objects.active=arm
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pose.transforms_clear()
    bpy.ops.object.mode_set(mode='OBJECT')
    arm.data.pose_position='REST'   # force bind-pose node transforms in the GLB
    bpy.context.view_layer.update()
    print('BIND pose cleared for export')

    if A.export:
        uid=A.id or A.unit
        out=Path(A.out) if A.out else Path('output/units')/A.faction/uid
        out.mkdir(parents=True,exist_ok=True)
        bpy.ops.object.select_all(action='DESELECT')
        body.select_set(True); arm.select_set(True)
        bpy.context.view_layer.objects.active=arm
        dest=out/f'{uid}_rigged.glb'
        bpy.ops.export_scene.gltf(filepath=str(dest),export_format='GLB',use_selection=True,
            export_animations=True,export_animation_mode='ACTIONS',export_anim_slide_to_zero=True,export_rest_position_armature=True)
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
