"""Original tactile film study. Run with Blender 4.3; no external add-ons or downloaded code."""
import bpy
import math
import os
import sys
from pathlib import Path
from mathutils import Vector

OUT = Path(os.environ.get('JIEJING_V7_OUTPUT', '/workspace/jiejing-deliverables/11.0/20261007-creative-reset-v7'))
if (OUT/'jiejing-tactile-v7.blend').exists():
 raise FileExistsError('Preserve the saved scene. Set JIEJING_V7_OUTPUT to a new version directory before rebuilding.')
OUT.mkdir(parents=True, exist_ok=True)
(OUT/'frames').mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene
scene.render.engine='CYCLES'
scene.cycles.device='CPU'
scene.cycles.samples=20
scene.cycles.use_denoising=True
scene.cycles.max_bounces=6
scene.render.threads_mode='FIXED'
scene.render.threads=3
scene.render.use_persistent_data=True
scene.render.resolution_x=720
scene.render.resolution_y=1280
scene.render.resolution_percentage=100
scene.render.fps=24
scene.frame_start=1
scene.frame_end=342
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGB'
scene.render.image_settings.compression=25
scene.world=bpy.data.worlds.new('warm_environment')
scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.66,.72,.82,1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value=.27
scene.view_settings.view_transform='AgX'
scene.view_settings.look='AgX - Medium High Contrast'


def material(name,color,rough=.4,metal=0):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal
 return m


def textured(name,low,high,scale,rough=.5,bump=.03):
 m=material(name,low,rough);n=m.node_tree.nodes;l=m.node_tree.links;bs=n.get('Principled BSDF')
 noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=scale;noise.inputs['Detail'].default_value=3
 ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=.22;ramp.color_ramp.elements[0].color=(*low,1);ramp.color_ramp.elements[1].position=.8;ramp.color_ramp.elements[1].color=(*high,1)
 l.new(noise.outputs['Fac'],ramp.inputs[0]);l.new(ramp.outputs[0],bs.inputs['Base Color'])
 b=n.new('ShaderNodeBump');b.inputs['Strength'].default_value=bump;b.inputs['Distance'].default_value=.018;l.new(noise.outputs['Fac'],b.inputs['Height']);l.new(b.outputs[0],bs.inputs['Normal'])
 return m


blue=textured('Deep cobalt ceramic glaze',(.009,.018,.070),(.031,.09,.29),90,.24,.18)
clay=textured('Unglazed clay foot',(.26,.11,.055),(.57,.30,.12),115,.8,.2)
paper=textured('Natural cotton paper',(.72,.67,.56),(.92,.88,.77),190,.9,.1)
stone=textured('Travertine set',(.44,.37,.26),(.73,.66,.51),85,.79,.15)
wood=textured('Warm walnut',(.09,.038,.014),(.31,.15,.051),4,.42,.15)
nodes=wood.node_tree.nodes;links=wood.node_tree.links
tex=nodes.new('ShaderNodeTexCoord');mapping=nodes.new('ShaderNodeMapping');mapping.inputs['Scale'].default_value=(1,35,5);links.new(tex.outputs['Generated'],mapping.inputs['Vector']);links.new(mapping.outputs['Vector'],next(n for n in nodes if n.type=='TEX_NOISE').inputs['Vector'])
silver=material('Brushed aluminium',(.55,.58,.62),.25,.92)
dark=material('Graphite device',(.018,.019,.021),.3,.6)
cream=material('Warm plaster',(.65,.58,.46),.83)
orange=material('Terracotta',(.45,.105,.043),.74)
ink=material('Printed charcoal',(.035,.036,.033),.85)
coffee=material('Coffee beans',(.055,.015,.008),.29)


def cube(name,loc,dim,mat,bevel=.02):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=dim;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
 o.data.materials.append(mat)
 if bevel:
  mod=o.modifiers.new('Soft manufactured edges','BEVEL');mod.width=bevel;mod.segments=3
  mod=o.modifiers.new('Weighted surface normals','WEIGHTED_NORMAL')
 return o


def lathe(name,profile,loc,mat):
 count=96;verts=[];faces=[]
 for radius,z in profile:
  verts.extend([(loc[0]+radius*math.cos(i*2*math.pi/count),loc[1]+radius*math.sin(i*2*math.pi/count),loc[2]+z) for i in range(count)])
 for ring in range(len(profile)-1):
  for j in range(count):faces.append((ring*count+j,ring*count+(j+1)%count,(ring+1)*count+(j+1)%count,(ring+1)*count+j))
 mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update();o=bpy.data.objects.new(name,mesh);scene.collection.objects.link(o);o.data.materials.append(mat)
 for poly in mesh.polygons:poly.use_smooth=True
 return o


def cup(x,y,z,name):
 body=lathe(name,[(0,0),(.53,0),(.58,.07),(.595,1.14),(.59,1.22),(.575,1.245),(.515,1.245),(.50,1.21),(.50,.18),(0,.18)],(x,y,z),blue)
 lathe(name+' raw ceramic base',[(0,0),(.529,0),(.558,.06),(.558,.135),(.535,.155),(0,.155)],(x,y,z-.002),clay)
 return body


def curve(name,points,mat,thickness=.014):
 data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D';data.resolution_u=24;data.bevel_depth=thickness;data.bevel_resolution=4
 sp=data.splines.new('BEZIER');sp.bezier_points.add(len(points)-1)
 for p,co in zip(sp.bezier_points,points):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
 ob=bpy.data.objects.new(name,data);scene.collection.objects.link(ob);ob.data.materials.append(mat);return ob


def light(name,center,position,energy,size,color):
 data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.shape='DISK';data.size=size;data.color=color
 o=bpy.data.objects.new(name,data);scene.collection.objects.link(o);o.location=position;o.rotation_euler=(Vector(center)-o.location).to_track_quat('-Z','Y').to_euler()


def folded_sheet(name,center,angle,width=1.2,height=2.2):
 verts=[];faces=[];rows=24
 for i in range(rows+1):
  t=i/rows;z=height*t;bulge=.45*math.sin(t*math.pi)
  for j in range(2):verts.append(((j-.5)*width,bulge,z))
 for i in range(rows):faces.append((i*2,i*2+1,i*2+3,i*2+2))
 mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update();o=bpy.data.objects.new(name,mesh);scene.collection.objects.link(o);o.location=center;o.rotation_euler[2]=angle;o.data.materials.append(paper)
 mod=o.modifiers.new('Paper thickness','SOLIDIFY');mod.thickness=.006
 for poly in mesh.polygons:poly.use_smooth=True
 return o


# Set A: warm physical merchant workbench. Generic illustrative props, no merchant facts.
cube('Walnut workbench',(0,0,-.15),(12,10,.3),wood,.06)
cube('Warm workroom background',(0,4.5,4),(18,.2,10),cream,.04)
cup(0,0,0,'Workbench cobalt vessel')
cube('Kraft shipping parcel',(.95,1.1,.44),(1.4,.9,.88),paper,.03)
cube('Parcel paper tape',(.95,1.1,.892),(.16,.94,.01),stone,.001)
for i in range(5):
 o=cube('Cotton reference paper '+str(i),(-.93+.04*i,.3-.03*i,.025+i*.017),(1.2,1.62,.012),paper,.006);o.rotation_euler[2]=-.17+i*.08
 for j in range(4):
  line=cube('Printed rule '+str(i)+' '+str(j),(-1.01+.04*i,.08+j*.17,.037+i*.017),(.53-.06*(j%2),.018,.001),ink,.001)
lathe('Measuring spoon bowl',[(0,0),(.23,0),(.29,.07),(.30,.18),(.29,.22),(.265,.22),(.255,.09),(0,.065)],(.86,-.85,.04),silver)
handle=cube('Spoon metal handle',(1.41,-.85,.14),(.86,.14,.045),silver,.05)
for i in range(11):
 a=i*2.4;bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12,radius=.075,location=(math.cos(a)*.6-.48,math.sin(a)*.4-.92,.065));ob=bpy.context.object;ob.name='Coffee prop';ob.scale=(1,.64,.45);ob.rotation_euler[2]=a;ob.data.materials.append(coffee)
# Out-of-focus foreground device edges give spatial depth.
dev=cube('Foreground closed laptop edge',(-.7,-2,.13),(3,1.5,.09),dark,.065);dev.rotation_euler[2]=.16
light('Sunlit window A',(0,0,.6),(-3,-2,6),900,2.2,(1,.80,.56))
light('Cool room fill A',(0,0,.7),(3,2,4),220,4,(.69,.80,1))
for i in range(4):cube('Window shadow slat '+str(i),(-1.9+i*.4,-.6,3.5),(.15,3,.05),dark,.001)

# Set B: sculptural material choreography. An original film metaphor, never fake UI.
cube('Studio cyclorama base',(25,0,-.2),(14,14,.35),cream,.05)
cube('Studio seamless backdrop',(25,5,4),(18,.2,10),cream,.04)
cube('Travertine plinth',(25,0,.14),(2.15,1.65,.30),stone,.035)
cup(25,0,.29,'Studio cobalt vessel')
lathe('Terracotta accent vase',[(0,0),(.35,0),(.42,.18),(.38,.45),(.18,.7),(.16,1.05),(.14,1.08),(.11,1.08),(.12,.73),(.25,.4),(0,.12)],(26.22,.6,0),orange)
sheets=[]
for i,(pos,ang,h) in enumerate([((23.85,.62,.04),-.5,2.7),((25.6,.97,.04),.6,2.3),((24.08,-.52,.04),-1.0,1.55)]):sheets.append(folded_sheet('Sculpted cotton sheet '+str(i),pos,ang,1.3,h))
# Broad, reflective metal ribbon with physical thickness.
verts=[];faces=[]
for i in range(81):
 t=i/80;a=-.6+t*4.4;r=1.57
 for edge in [-.22,.22]:verts.append((25+r*math.cos(a),r*math.sin(a),.15+2.65*t+edge))
for i in range(80):faces.append((2*i,2*i+1,2*i+3,2*i+2))
mesh=bpy.data.meshes.new('Continuous aluminium ribbon');mesh.from_pydata(verts,[],faces);mesh.update();ribbon=bpy.data.objects.new('Continuous aluminium ribbon',mesh);scene.collection.objects.link(ribbon);mesh.materials.append(silver)
for poly in mesh.polygons:poly.use_smooth=True
mod=ribbon.modifiers.new('Metal thickness','SOLIDIFY');mod.thickness=.009
light('Large warm softbox B',(25,0,1),(21,-3,6),1200,4,(1,.85,.65))
light('Rim strip B',(25,0,1),(28,3,4),800,3,(.74,.84,1))

# Set C: retained, actual local product UI photographed as a physical screen.
cube('Device desk',(50,0,-.18),(12,12,.35),cream,.07)
cube('Device backdrop',(50,5,4),(18,.2,10),cream,.04)
tablet=cube('Actual UI graphite bezel',(50,0,1.75),(3.14,.13,2.71),dark,.09)
cube('Tablet support',(50,.36,.48),(1.0,.8,.12),silver,.04)
cube('Tablet support stem',(50,.35,.90),(.17,.16,.83),silver,.03)
image=bpy.data.images.load('/workspace/jiejing-deliverables/11.0/20261007-release-film-v6/assets/release-v6/workspace-goal.png');image.pack()
m=material('Actual retained local input screen',(1,1,1),.6);n=m.node_tree.nodes;l=m.node_tree.links
tex=n.new('ShaderNodeTexImage');tex.image=image;bs=n.get('Principled BSDF');l.new(tex.outputs['Color'],bs.inputs['Base Color']);l.new(tex.outputs['Color'],bs.inputs['Emission Color']);bs.inputs['Emission Strength'].default_value=.35
w,h=2.93,2.483;z=1.75;y=-.074;mesh=bpy.data.meshes.new('Actual screenshot surface');mesh.from_pydata([(50-w/2,y,z-h/2),(50+w/2,y,z-h/2),(50+w/2,y,z+h/2),(50-w/2,y,z+h/2)],[],[(0,1,2,3)]);mesh.update();uv=mesh.uv_layers.new()
for loop,xy in zip(mesh.loops,[(0,0),(1,0),(1,1),(0,1)]):uv.data[loop.index].uv=xy
o=bpy.data.objects.new('Actual screenshot surface',mesh);scene.collection.objects.link(o);mesh.materials.append(m)
cup(48.15,-.65,0,'Foreground vessel by device')
light('Device soft window',(50,0,1),(47,-3,6),950,3.5,(1,.87,.7))
light('Device edge light',(50,0,1),(53,2,4),450,3,(.71,.82,1))

bpy.ops.object.camera_add();cam=bpy.context.object;cam.name='Cinematography';scene.camera=cam;cam.data.sensor_width=36;cam.data.dof.use_dof=True;cam.data.dof.aperture_fstop=5.6
bpy.ops.object.empty_add(type='PLAIN_AXES');focus=bpy.context.object;focus.name='Camera focus';cam.data.dof.focus_object=focus


def smooth(t):return t*t*(3-2*t)
def mix(a,b,t):return tuple(x+(y-x)*t for x,y in zip(a,b))


for f in range(1,343):
 t=(f-1)/24
 if t<3.35:
  q=smooth(t/3.35);loc=mix((2.55,-3.9,2.15),(1.78,-4.9,3.0),q);target=(.03,-.06,.64);lens=58-6*q;fstop=4.8
 elif t<7.1:
  q=smooth((t-3.35)/3.75);loc=mix((27.6,-5.8,3.8),(25.7,-5.0,2.5),q);target=(25,0,1.38);lens=49;fstop=6.3
 elif t<10.55:
  q=smooth((t-7.1)/3.45);loc=mix((50.40,-4.2,2.35),(50.02,-2.65,1.08),q);target=mix((50,0,1.20),(50,0,.85),q);lens=48;fstop=32
 else:
  q=smooth((t-10.55)/3.7);loc=mix((22.9,-4.3,4.5),(24.3,-5.2,3.5),q);target=(25,0,1.0);lens=45;fstop=7.1
 cam.location=loc;focus.location=target;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=lens;cam.data.dof.aperture_fstop=fstop
 for path in ['location','rotation_euler']:cam.keyframe_insert(data_path=path,frame=f)
 cam.data.keyframe_insert(data_path='lens',frame=f);cam.data.dof.keyframe_insert(data_path='aperture_fstop',frame=f);focus.keyframe_insert(data_path='location',frame=f)
 for i,o in enumerate(sheets):
  o.rotation_euler[2]=[-.5,.6,-1.0][i]+.12*math.sin(t*.7+i);o.keyframe_insert(data_path='rotation_euler',frame=f)
for ob in list(bpy.data.objects)+[cam.data]:
 if ob.animation_data and ob.animation_data.action:
  for fc in ob.animation_data.action.fcurves:
   for key in fc.keyframe_points:key.interpolation='LINEAR'
scene.render.filepath=str(OUT/'frames/frame-')
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'jiejing-tactile-v7.blend'))
args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
if '--render-study' in args:
 scene.cycles.samples=4
 scene.render.threads=4
 frames=sorted(set(list(range(1,343,6))+[80,81,82,170,171,172,253,254,255,342]))
 import json,time
 begin=time.monotonic()
 for frame in frames:
  path=OUT/'frames'/f'frame-{frame:04d}.png'
  if path.is_file():raise RuntimeError(f'Existing rendered frame must be reviewed before overwrite: {path}')
  scene.frame_set(frame);scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
 (OUT/'RENDER_FRAMES.safe.json').write_text(json.dumps({'exit_code':0,'frames':frames,'timeline_fps':24,'timeline_frames':342,'native_size':[720,1280],'render_samples':4,'cpu_threads':4,'temporal_sampling':'Every sixth timeline frame plus cut/end boundaries; interpolate motion per shot for visual study','wall_seconds':time.monotonic()-begin},indent=2)+'\n')
elif '--preview' in args:
 for frame in [1,108,212,300]:
  scene.frame_set(frame);scene.render.filepath=str(OUT/f'preview-{frame}.png');bpy.ops.render.render(write_still=True)
elif '--render' in args:
 bpy.ops.render.render(animation=True)
print('TACTILE_SCENE_SAVED')
