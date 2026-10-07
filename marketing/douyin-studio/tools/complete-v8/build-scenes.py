"""Seven original film sets. Blender only; no imported models or third-party add-ons."""
from pathlib import Path
import bpy
import json
import math
import os
import sys
import time
from mathutils import Vector

OUT=Path(os.environ.get('JIEJING_V8_OUTPUT','/workspace/jiejing-deliverables/11.0/20261007-complete-v8'))
ARGS=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
OUT.mkdir(parents=True,exist_ok=True)
if (OUT/'jiejing-v8-seven-sets.blend').exists():
    raise FileExistsError('Preserve existing scene; use a new JIEJING_V8_OUTPUT directory.')
bpy.ops.wm.read_factory_settings(use_empty=True)
FONT=bpy.data.fonts.load('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6/assets/release-v6/bold.otf')
FONT.pack()


def mat(name,color,rough=.45,metal=0,emit=0):
    m=bpy.data.materials.new(name);m.use_nodes=True
    bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1)
    bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal
    if emit:bs.inputs['Emission Color'].default_value=(*color,1);bs.inputs['Emission Strength'].default_value=emit
    return m


PAPER=mat('Warm cotton paper',(.79,.76,.68),.87)
WHITE=mat('Porcelain white',(.90,.91,.90),.35)
BLUE=mat('Cobalt enamel',(.012,.042,.24),.27,.25)
NAVY=mat('Midnight stage',(.008,.017,.04),.52)
INK=mat('Ink graphite',(.025,.034,.041),.62)
ORANGE=mat('Vermilion accent',(.85,.16,.045),.4)
METAL=mat('Satin aluminium',(.53,.59,.63),.26,.88)
WARM=mat('Warm stone',(.55,.48,.36),.81)
GLOW=mat('Warm signal',(.94,.50,.19),.35,0,1.3)
LIGHT=mat('Cool white signal',(.65,.84,1),.4,0,1.1)
SCENES=[]


def cube(name,loc,size,material,bevel=.04):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(material)
    if bevel:
        m=o.modifiers.new('Manufactured edges','BEVEL');m.width=bevel;m.segments=3
        o.modifiers.new('Surface normals','WEIGHTED_NORMAL')
    return o


def sphere(name,loc,radius,material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=16,radius=radius,location=loc)
    o=bpy.context.object;o.name=name;o.data.materials.append(material)
    for p in o.data.polygons:p.use_smooth=True
    return o


def curve(name,points,material,width=.025):
    c=bpy.data.curves.new(name,'CURVE');c.dimensions='3D';c.bevel_depth=width;c.bevel_resolution=3
    s=c.splines.new('POLY');s.points.add(len(points)-1)
    for p,xyz in zip(s.points,points):p.co=(*xyz,1)
    o=bpy.data.objects.new(name,c);bpy.context.scene.collection.objects.link(o);c.materials.append(material);return o


def text3d(name,body,loc,size,material,rotation=(math.pi/2,0,0),extrude=.012):
    c=bpy.data.curves.new(name,'FONT');c.body=body;c.font=FONT;c.size=size;c.align_x='CENTER';c.align_y='CENTER'
    c.extrude=extrude;c.bevel_depth=.002;c.bevel_resolution=2
    o=bpy.data.objects.new(name,c);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=rotation;c.materials.append(material);return o


def light(name,loc,target,power,size,color):
    bpy.ops.object.light_add(type='AREA',location=loc);o=bpy.context.object;o.name=name;o.data.energy=power;o.data.shape='DISK';o.data.size=size;o.data.color=color
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()


def scene(name,frames,dark=False):
    s=bpy.data.scenes.new(name);bpy.context.window.scene=s;SCENES.append(s)
    s.render.engine='CYCLES';s.cycles.device='CPU';s.cycles.samples=6;s.cycles.use_denoising=True;s.cycles.max_bounces=4
    s.render.threads_mode='FIXED';s.render.threads=4;s.render.use_persistent_data=True
    s.render.resolution_x=720;s.render.resolution_y=1280;s.render.resolution_percentage=100;s.render.fps=24
    s.frame_start=1;s.frame_end=frames;s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGB'
    s.render.image_settings.compression=30;s.view_settings.view_transform='AgX';s.view_settings.look='AgX - Medium High Contrast'
    w=bpy.data.worlds.new(name+' atmosphere');s.world=w;w.use_nodes=True
    w.node_tree.nodes['Background'].inputs[0].default_value=(.26,.33,.47,1) if dark else (.8,.84,.91,1)
    w.node_tree.nodes['Background'].inputs[1].default_value=.22
    cube(name+' stage',(0,0,-.22),(30,30,.4),NAVY if dark else PAPER)
    cube(name+' seamless wall',(0,5,5),(30,.3,14),NAVY if dark else PAPER)
    light('Window key',(-3,-4,6),(0,0,1),1050 if not dark else 700,4,(1,.83,.64))
    light('Cool edge',(3,1,4),(0,0,1),850,3,(.60,.75,1))
    return s


def ease(t):return t*t*(3-2*t)
def mix(a,b,t):return tuple(x+(y-x)*t for x,y in zip(a,b))


def camera(s,start,end,target,target_end=None,lens=48):
    bpy.ops.object.camera_add();c=bpy.context.object;c.name=s.name+' camera';s.camera=c;c.data.lens=lens;c.data.sensor_width=36
    for f in range(1,s.frame_end+1):
        t=ease((f-1)/(s.frame_end-1));c.location=mix(start,end,t);aim=mix(target,target_end or target,t)
        c.rotation_euler=(Vector(aim)-c.location).to_track_quat('-Z','Y').to_euler()
        c.keyframe_insert(data_path='location',frame=f);c.keyframe_insert(data_path='rotation_euler',frame=f)


def pose(o,frame,loc=None,rot=None,scale=None):
    if loc is not None:o.location=loc;o.keyframe_insert(data_path='location',frame=frame)
    if rot is not None:o.rotation_euler=rot;o.keyframe_insert(data_path='rotation_euler',frame=frame)
    if scale is not None:o.scale=scale;o.keyframe_insert(data_path='scale',frame=frame)


def photo(name,loc,angle,material=BLUE):
    o=cube(name,loc,(1.03,1.29,.018),WHITE,.008);o.rotation_euler[2]=angle
    inner=cube(name+' abstract image',(0,0,.017),(.87,.94,.008),material,.004);inner.parent=o;inner.location=(0,.08,.017)
    # Original geometric photographic metaphor, not a product result.
    ring=curve(name+' exposure',[(.26*math.cos(a),.08+.26*math.sin(a),.025) for a in [i*math.tau/64 for i in range(65)]],WHITE,.009);ring.parent=o
    return o


# 1. Merchant's working materials, not a product-category beauty shot.
s=scene('01_materials',80)
for i in range(6):
    o=cube('Loose document '+str(i),(-.72+i*.19,.2+i*.08,.045+i*.025),(1.6,2.03,.016),PAPER,.012);o.rotation_euler[2]=-.38+i*.14
    for j in range(5):
        line=cube('Printed paragraph',(0,0,0),(.85-(j%2)*.18,.024,.001),INK,0);line.parent=o;line.location=(.05,-.15+j*.17,.011)
    pose(o,1,rot=(0,0,-.38+i*.14));pose(o,80,rot=(0,0,-.48+i*.20),loc=(-.9+i*.24,.35+i*.1,.045+i*.025))
photo('Reference photograph',(.78,-.3,.13),-.22)
photo('Source sheet',(-1.1,-1.0,.10),.14,ORANGE)
cube('Closed notebook',(1.35,1.15,.16),(1.12,1.65,.27),BLUE,.07)
curve('Braided charging cable',[(1.3*math.sin(i*.13),-1.55+.23*math.cos(i*.2),.07) for i in range(45)],INK,.035)
cube('Pencil',(-.3,-1.22,.12),(.07,1.8,.07),METAL,.018).rotation_euler[2]=.9
for x in [-1.7,-.8,.1,.95]:
    flag=cube('Window flag',(x,.3,4),(.11,6,.05),INK,.001);flag.visible_camera=False
camera(s,(2.25,-4.7,5.5),(.65,-3.9,5.0),(0,0,.13),lens=46)

# 2. A brand space with depth and a ribbon passing through a doorway.
s=scene('02_brand',90,True)
for x in [-1.05,1.05]:cube('Portal upright',(x,.7,1.52),(.28,.42,3.1),METAL,.12)
cube('Portal top',(0,.7,3.0),(2.35,.42,.28),METAL,.12)
text3d('Jiejing wordmark','捷境',(0,-.05,1.62),1.12,WHITE,extrude=.035)
text3d('Brand roman','J I E J I N G',(0,-.03,.79),.22,METAL)
ribbon=curve('Cobalt orbit',[(-2.8+i*.05,.18+.62*math.sin(i*.08),.20+i*.019) for i in range(113)],BLUE,.10)
o=sphere('Amber signal',(-2,0,.3),.075,GLOW)
for f in range(1,91):
    t=(f-1)/89;pose(o,f,loc=(-2.8+5.6*t,.18+.62*math.sin(t*8.96),.20+2.13*t))
camera(s,(1.25,-6.5,2.2),(-.2,-5.5,2.0),(0,.1,1.53),lens=49)

# 3. One real input example in a physical workspace, no fabricated AI answer.
s=scene('03_input',84)
cube('Graphite screen body',(0,0,1.55),(3.72,.15,1.25),INK,.1)
cube('Screen foot',(0,.25,.25),(1.05,.9,.16),METAL,.08)
cube('Screen stand',(0,.3,.79),(.15,.15,1.03),METAL,.03)
im=bpy.data.images.load('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6/assets/release-v6/workspace-goal.png');im.pack()
m=bpy.data.materials.new('Actual retained goal crop');m.use_nodes=True;n=m.node_tree.nodes;n.clear();tex=n.new('ShaderNodeTexImage');tex.image=im
em=n.new('ShaderNodeEmission');em.inputs[1].default_value=.9;m.node_tree.links.new(tex.outputs['Color'],em.inputs[0]);out=n.new('ShaderNodeOutputMaterial');m.node_tree.links.new(em.outputs[0],out.inputs[0])
mesh=bpy.data.meshes.new('Actual input surface');mesh.from_pydata([(-1.74,-.087,1.24),(1.74,-.087,1.24),(1.74,-.087,1.86),(-1.74,-.087,1.86)],[],[(0,1,2,3)]);mesh.update();uv=mesh.uv_layers.new()
for loop,xy in zip(mesh.loops,[(.29,.065),(.68,.065),(.68,.145),(.29,.145)]):uv.data[loop.index].uv=xy
ob=bpy.data.objects.new('Exact real UI input',mesh);s.collection.objects.link(ob);mesh.materials.append(m)
for i in range(3):
    o=photo('Supporting material '+str(i),(-1.5+i*1.25,-1.0,.05+i*.01),-.08+i*.15,BLUE if i!=1 else ORANGE)
    pose(o,1,loc=(-1.5+i*1.25,-1.0,.05+i*.01));pose(o,84,loc=(-1.4+i*1.3,-.65,.08+i*.04),rot=(.08,0,.04+i*.12))
camera(s,(.20,-6.4,3.80),(-.20,-6.2,3.25),(0,0,1.18),lens=36)

# 4. Editorial studio: content is assembled and inspected, not fake software output.
s=scene('04_editorial',92)
cube('Editorial slab',(0,.2,.12),(2.7,2.25,.28),WARM,.09)
pages=[]
for i in range(5):
    o=cube('Bound page '+str(i),(0,.1,.30+i*.032),(1.75,2.15,.018),WHITE,.008);pages.append(o)
    for j in range(4):
        line=cube('Editorial baseline',(0,0,0),(.75-j*.04,.024,.001),INK,0);line.parent=o;line.location=(.29,-.35+j*.17,.014)
    picture=cube('Image placeholder',(0,0,0),(.47,.55,.004),BLUE,.008);picture.parent=o;picture.location=(-.45,.44,.014)
    pose(o,1,loc=(0,.1,.30+i*.032),rot=(0,0,-.08));pose(o,92,loc=((i-2)*.16,.10+i*.09,.35+i*.17),rot=(.07*i,-.08*i,-.19+i*.1))
for x in [-1.12,1.12]:cube('Scan rail',(x,.2,.4),(.075,2.7,.10),METAL,.02)
scanner=cube('Inspection bar',(0,-1.0,.60),(2.5,.075,.12),METAL,.03)
strip=cube('Scan illumination',(0,0,0),(2.30,.015,.035),LIGHT,.006);strip.parent=scanner;strip.location=(0,-.03,-.04)
pose(scanner,1,loc=(0,-1.0,.6));pose(scanner,92,loc=(0,1.2,1.1))
camera(s,(2.25,-4.6,4.65),(-1.20,-4.3,4.1),(0,.10,.7),lens=49)

# 5. A physical confirmation passage; illustrative, not a real publish event.
s=scene('05_confirm',90,True)
cube('Threshold base',(0,0,.06),(3.5,2.3,.15),METAL,.07)
for x in [-1.05,1.05]:cube('Passage pillar',(x,.2,1.55),(.23,.6,3.0),WHITE,.065)
cube('Lintel',(0,.2,3.0),(2.3,.6,.20),WHITE,.055)
left=cube('Left approval gate',(-.49,.13,1.5),(.94,.11,2.7),BLUE,.03)
right=cube('Right approval gate',(.49,.13,1.5),(.94,.11,2.7),BLUE,.03)
for o,sign in [(left,-1),(right,1)]:
    pose(o,1,loc=(sign*.49,.13,1.5));pose(o,43,loc=(sign*.49,.13,1.5));pose(o,76,loc=(sign*1.45,.13,1.5));pose(o,90,loc=(sign*1.45,.13,1.5))
curve('Path before confirmation',[(0,-3.0,.15),(0,2.9,.15)],GLOW,.024)
token=sphere('Decision token',(0,-1.6,.18),.10,ORANGE)
pose(token,1,loc=(0,-1.6,.18));pose(token,43,loc=(0,-.72,.18));pose(token,90,loc=(0,2.0,.18))
light('Light beyond gate',(0,3,2.0),(0,-2,1.0),600,1.4,(1,.75,.42))
camera(s,(1.15,-6.8,2.5),(.1,-5.0,1.7),(0,.2,1.42),lens=47)

# 6. Abstract global direction, no unsupported platform integration claims.
s=scene('06_world',70,True)
bpy.ops.object.empty_add();globe=bpy.context.object;globe.name='Rotating meridian assembly';globe.location=(0,0,1.65)
for lat in [-60,-30,0,30,60]:
    a=math.radians(lat);rad=1.28*math.cos(a);z=1.28*math.sin(a)
    ob=curve('Latitude',[(rad*math.cos(i*math.tau/96),rad*math.sin(i*math.tau/96),z) for i in range(97)],METAL,.011);ob.parent=globe
for lon in range(0,180,30):
    a=math.radians(lon);ob=curve('Meridian',[(1.28*math.sin(i*math.tau/96)*math.cos(a),1.28*math.sin(i*math.tau/96)*math.sin(a),1.28*math.cos(i*math.tau/96)) for i in range(97)],BLUE,.018);ob.parent=globe
curve('Single supported route',[(1.56*math.cos(i*math.tau/96),1.4*math.sin(i*math.tau/96),1.65+.5*math.sin(i*math.tau/96)) for i in range(97)],GLOW,.026)
pose(globe,1,rot=(.16,.1,-.35));pose(globe,70,rot=(.16,.1,.35))
camera(s,(2.3,-6.9,3.1),(.8,-6.7,2.4),(0,0,1.7),lens=48)

# 7. Calm architectural ending. Clear type is composited at native output resolution.
s=scene('07_open_path',166)
for i in range(6):
    y=i*.72
    for x in [-1.5,1.5]:cube('Architectural frame',(x,y,1.8),(.14,.16,3.65),BLUE if i==0 else WHITE,.045)
    cube('Frame crown',(0,y,3.6),(3.14,.16,.14),BLUE if i==0 else WHITE,.045)
curve('Continuous amber thread',[(0,-3,.09),(0,5,.09)],ORANGE,.028)
camera(s,(.66,-6.8,2.35),(.05,-5.5,1.9),(0,1.0,1.77),lens=46)

for s in SCENES:
    for ob in s.objects:
        if ob.animation_data and ob.animation_data.action:
            for fc in ob.animation_data.action.fcurves:
                for point in fc.keyframe_points:point.interpolation='BEZIER' if len(fc.keyframe_points)<8 else 'LINEAR'
    s.frame_set(1)
bpy.context.window.scene=SCENES[0]
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'jiejing-v8-seven-sets.blend'))
story=[{'scene':s.name,'frames':s.frame_end,'seconds':s.frame_end/24,'native_resolution':[720,1280]} for s in SCENES]
(OUT/'SCENES.safe.json').write_text(json.dumps({'fps':24,'total_frames':sum(s.frame_end for s in SCENES),'shots':story,'cups_or_product_category_rotation':False},indent=2)+'\n')
if '--preview' in ARGS:
    for s in SCENES:
        bpy.context.window.scene=s;s.frame_set(round(s.frame_end*.55));s.render.filepath=str(OUT/(s.name+'-preview.png'));bpy.ops.render.render(write_still=True)
elif '--render' in ARGS:
    records=[];begin=time.monotonic()
    for s in SCENES:
        bpy.context.window.scene=s;folder=OUT/'frames'/s.name;folder.mkdir(parents=True,exist_ok=True)
        frames=sorted(set(range(1,s.frame_end+1,4))|{s.frame_end})
        for f in frames:
            dest=folder/f'{f:04d}.png'
            if dest.exists():raise FileExistsError(str(dest))
            s.frame_set(f);s.render.filepath=str(dest);bpy.ops.render.render(write_still=True)
        records.append({'scene':s.name,'frames':frames,'timeline_frames':s.frame_end})
        (OUT/'RENDER_PROGRESS.safe.json').write_text(json.dumps({'completed':records,'seconds':time.monotonic()-begin},indent=2)+'\n')
    (OUT/'RENDER.safe.json').write_text(json.dumps({'exit_code':0,'shots':records,'samples':6,'cpu_threads':4,'native_resolution':[720,1280],'sample_every_nth_frame':4,'timeline_fps':24,'full_native24fps':False,'elapsed_seconds':time.monotonic()-begin},indent=2)+'\n')
print('V8_SEVEN_SETS_READY')
