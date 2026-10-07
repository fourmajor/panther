"""Trusted declarative procedural renderer, invoked with Blender's Python only.

No downloaded scripts, external images, assets, drivers, handlers or add-ons.
"""

import json
import math
from pathlib import Path
import sys


def build(value, folder):
    import bpy
    from mathutils import Vector

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.resolution_percentage = 100
    scene.render.fps = value["fps"]
    scene.frame_start, scene.frame_end = 1, round(value["duration"] * value["fps"])
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (.035, .045, .065)
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    materials = {}

    def material(color, emission=0):
        key = (*color, emission)
        if key not in materials:
            mat = bpy.data.materials.new("Procedural material")
            mat.use_nodes = True
            shader = mat.node_tree.nodes.get("Principled BSDF")
            shader.inputs["Base Color"].default_value = (*color, 1)
            shader.inputs["Roughness"].default_value = .5
            shader.inputs["Emission Color"].default_value = (*color, 1)
            shader.inputs["Emission Strength"].default_value = emission
            materials[key] = mat
        return materials[key]

    def primitive(shape, name, pos, scale, color, parent=None, emission=0):
        if shape == "box":
            bpy.ops.mesh.primitive_cube_add(size=1)
        elif shape == "sphere":
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=.5)
        elif shape == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=.5, depth=1)
        elif shape == "cone":
            bpy.ops.mesh.primitive_cone_add(vertices=16, radius1=.5, radius2=.15, depth=1)
        elif shape == "torus":
            bpy.ops.mesh.primitive_torus_add(major_segments=24, minor_segments=8, major_radius=.4, minor_radius=.06)
        else:
            raise ValueError("Unsupported procedural primitive")
        obj = bpy.context.object
        obj.name, obj.parent, obj.location, obj.scale = name, parent, pos, scale
        obj.data.materials.append(material(color, emission))
        for polygon in obj.data.polygons:
            polygon.use_smooth = shape != "box"
        if shape == "box":
            bevel = obj.modifiers.new("Soft edges", "BEVEL")
            bevel.width, bevel.segments = .04, 2
        return obj

    def actor(item):
        root = bpy.data.objects.new(item["id"], None)
        scene.collection.objects.link(root)
        color, features = item["color"], item["features"]
        skin, dark = (.48, .29, .19), (.04, .035, .04)
        primitive("cone", "Torso", (0, 0, 1.1), (.65, .4, .8), color, root)
        primitive("sphere", "Hips", (0, 0, .66), (.5, .34, .28), color, root)
        primitive("cylinder", "Neck", (0, 0, 1.55), (.17, .17, .22), skin, root)
        primitive("sphere", "Head", (0, -.02, 1.78), (.38, .35, .44), skin, root)
        for x in (-.075, .075):
            primitive("sphere", "Eye", (x, -.18, 1.8), (.038, .028, .04), dark, root)
        for x in (-.19, .19):
            primitive("cylinder", "Boot", (x, 0, .3), (.19, .22, .55), dark, root)
        for x in (-.37, .37):
            primitive("sphere", "Shoulder", (x*.82, 0, 1.4), (.25, .28, .28), color, root)
            primitive("cylinder", "Arm", (x, -.02, 1.14), (.16, .18, .62), color, root)
            primitive("sphere", "Hand", (x, -.04, .84), (.17, .16, .19), skin, root)
        if "cloak" in features:
            primitive("cone", "Cloak", (0, .2, .9), (.75, .22, 1.2), [c*.6 for c in color], root)
        if "long-hair" in features or "short-hair" in features:
            hair = (.025, .02, .018)
            primitive("sphere", "Hair cap", (0, .02, 1.97), (.41, .34, .18), hair, root)
            if "long-hair" in features:
                primitive("sphere", "Hair back", (0, .16, 1.78), (.4, .22, .48), hair, root)
        if "tricorn" in features:
            hat = primitive("cone", "Tricorn", (0, 0, 2.02), (.65, .58, .18), (.22, .025, .3), root)
            # Deliberately triangular silhouette, not an accidental round helmet.
            bpy.data.objects.remove(hat, do_unlink=True)
            bpy.ops.mesh.primitive_cone_add(vertices=3, radius1=.4, radius2=.2, depth=.15)
            hat = bpy.context.object
            hat.parent, hat.location = root, (0, 0, 2.04)
            hat.data.materials.append(material((.22, .025, .3)))
        if "feather" in features:
            plume = primitive("sphere", "Vertical feather", (.12, .04, 2.32), (.12, .065, .58), (.85, .8, .65), root)
            plume.rotation_euler.y = -.2
        if "shield" in features:
            shield = primitive("cylinder", "Left shield", (.45, -.18, 1), (.62, .62, .1), (.12, .18, .24), root)
            shield.rotation_euler.x = math.pi/2
        for weapon in set(features) & {"sword", "rapier", "staff"}:
            # Facing -Y: anatomical right is -X, not screen-right +X.
            primitive("cylinder", "Right " + weapon, (-.39, -.05, 1.43), (.035 if weapon == "rapier" else .065, .035, 1.4), (.62, .67, .73), root)
            if weapon != "staff":
                primitive("box", "Weapon guard", (-.39, -.05, .91), (.25, .09, .045), (.7, .48, .12), root)
        # Actor origin is its centre, one unit above its feet, like other primitives.
        for child in root.children:
            child.location.z -= 1
        return root

    for item in value["scene"]["objects"]:
        if item["shape"] == "actor":
            obj = actor(item)
        elif item["shape"] == "curve":
            data = bpy.data.curves.new(item["id"], "CURVE")
            data.dimensions, data.bevel_depth, data.bevel_resolution = "3D", .035, 2
            spline = data.splines.new("POLY")
            spline.points.add(len(item["points"])-1)
            for p, point in zip(spline.points, item["points"], strict=True):
                p.co = (*point, 1)
            obj = bpy.data.objects.new(item["id"], data)
            scene.collection.objects.link(obj)
            data.materials.append(material(item["color"], item["emission"]))
        else:
            obj = primitive(item["shape"], item["id"], item["position"], item["scale"], item["color"], emission=item["emission"])
        obj.location, obj.rotation_euler, obj.scale = item["position"], item["rotation"], item["scale"]
        for key in item["keyframes"]:
            obj.location, obj.rotation_euler, obj.scale = key["position"], key["rotation"], key["scale"]
            frame = 1 + round(key["time"] * value["fps"])
            for path in ("location", "rotation_euler", "scale"):
                obj.keyframe_insert(data_path=path, frame=frame)

    camera = value["scene"]["camera"]
    bpy.ops.object.camera_add(location=camera["position"])
    scene.camera = bpy.context.object
    scene.camera.data.lens = camera["lens"]
    for frame, position in [(1, camera["position"]), (scene.frame_end, camera["endPosition"])]:
        scene.camera.location = position
        scene.camera.rotation_euler = (Vector(camera["target"])-scene.camera.location).to_track_quat("-Z", "Y").to_euler()
        scene.camera.keyframe_insert(data_path="location", frame=frame)
        scene.camera.keyframe_insert(data_path="rotation_euler", frame=frame)
    for pos, color, factor in [((-3,-4,7), (1,.65,.35) if value["scene"]["lighting"]["warm"] else (.6,.75,1), 1), ((4,2,5), (.4,.6,1), .6)]:
        bpy.ops.object.light_add(type="AREA", location=pos)
        lamp = bpy.context.object
        lamp.data.energy, lamp.data.color, lamp.data.size = value["scene"]["lighting"]["power"]*factor, color, 5
        lamp.rotation_euler = (Vector(camera["target"])-lamp.location).to_track_quat("-Z", "Y").to_euler()
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "scene.blend"))
    # Fresh reopen with auto-execution disabled; no persistent Python handlers.
    bpy.ops.wm.open_mainfile(filepath=str(folder / "scene.blend"))
    scene = bpy.context.scene
    if any(n.type == "TEX_IMAGE" for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes):
        raise ValueError("Procedural renderer must not depend on image textures")
    for obj in scene.objects:
        if not all(math.isfinite(v) for v in (*obj.location, *obj.scale)):
            raise ValueError("Nonfinite procedural geometry")
    frames = folder / "frames"
    frames.mkdir(exist_ok=True)
    for frame in range(1, scene.frame_end + 1):
        target = frames / f"{frame:06d}.png"
        if not target.exists():
            scene.frame_set(frame)
            scene.render.filepath = str(target)
            bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    manifest, directory = sys.argv[sys.argv.index("--")+1:]
    build(json.loads(Path(manifest).read_text()), Path(directory))
