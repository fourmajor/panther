"""Run only with Blender's Python, --disable-autoexec, against a private candidate folder."""

import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

folder = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
bpy.ops.wm.open_mainfile(filepath=str(folder / "model.blend"))
source_meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
assert source_meshes, "Editable source contains no meshes"
for img in bpy.data.images:
    if img.source == "FILE" and img.users:
        assert img.packed_file or img.packed_files, "Source has unpacked dependencies"
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(folder / "model.glb"))
objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
assert objects, "GLB contains no meshes"
triangles = 0
points = []
for obj in objects:
    obj.data.calc_loop_triangles()
    triangles += len(obj.data.loop_triangles)
    for vertex in obj.data.vertices:
        point = obj.matrix_world @ vertex.co
        assert all(math.isfinite(x) for x in point), "Nonfinite geometry"
    points.extend(obj.matrix_world @ Vector(c) for c in obj.bound_box)
assert 0 < triangles <= 200000, "Triangle budget exceeded"
lower = Vector(tuple(min(p[i] for p in points) for i in range(3)))
upper = Vector(tuple(max(p[i] for p in points) for i in range(3)))
size = upper - lower
assert all(0.01 < value < 20 for value in size), "Invalid model dimensions"
target = (upper + lower) / 2
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 24
scene.cycles.use_denoising = True
scene.render.resolution_x = 600
scene.render.resolution_y = 800
scene.render.resolution_percentage = 100
scene.world = bpy.data.worlds.new("Inspection World")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.65, 0.65, 0.65, 1)
scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.7
bpy.ops.object.light_add(type="AREA", location=target + Vector((3, -4, 5)))
bpy.context.object.data.energy = 700
bpy.context.object.data.shape = "DISK"
bpy.context.object.data.size = 5
bpy.ops.object.camera_add()
camera = bpy.context.object
scene.camera = camera
camera.data.type = "ORTHO"
camera.data.ortho_scale = max(size.z * 1.3, max(size.x, size.y) * 1.9)
renders = folder / "renders"
renders.mkdir(exist_ok=True)
views = ("front", "front-right", "right", "back-right", "back", "back-left", "left", "front-left")
for index, view in enumerate(views):
    angle = index * math.pi / 4
    camera.location = target + Vector((math.sin(angle) * 5, -math.cos(angle) * 5, 0.15))
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(renders / f"{view}.png")
    bpy.ops.render.render(write_still=True)
(folder / "validation.json").write_text(
    json.dumps(
        {
            "triangles": triangles,
            "dimensions": list(size),
            "freshSourceOpen": True,
            "freshGlbImport": True,
            "blenderVersion": bpy.app.version_string,
            "views": list(views),
        },
        indent=2,
    )
)
