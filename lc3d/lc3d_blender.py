"""LC3D — rendu photo-réaliste avec Blender (bpy). Lancé par lc3d.py dans un Python qui a bpy :
    python lc3d_blender.py rendu scene.json sortie.png
scene.json : {"pieces": [{"stl": "...", "couleur": [r,g,b], "matiere": "plastique|metal|mat"}], "vue": "iso", "taille": [1600,1200], "echantillons": 96}
Aussi : nettoyage d'un maillage organique (figurine) : python lc3d_blender.py nettoyer entree.stl sortie.stl [--lisser 2] [--faces 200000]
"""
import json, math, sys
import bpy
from mathutils import Vector


def _vider():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _importer_stl(chemin):
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=chemin)
    else:
        bpy.ops.import_mesh.stl(filepath=chemin)
    return bpy.context.selected_objects[0]


def _matiere(nom, couleur, genre):
    m = bpy.data.materials.new(nom); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*couleur, 1.0)
    if genre == "metal":
        b.inputs["Metallic"].default_value = 1.0; b.inputs["Roughness"].default_value = 0.28
    elif genre == "mat":
        b.inputs["Roughness"].default_value = 0.75
    else:   # plastique imprimé (PETG/PLA) : un peu satiné, pas un miroir
        b.inputs["Roughness"].default_value = 0.42
        if "Coat Weight" in b.inputs: b.inputs["Coat Weight"].default_value = 0.08
    return m


def rendu(scene_json, sortie):
    S = json.load(open(scene_json))
    _vider()
    sc = bpy.context.scene
    objets = []
    for i, p in enumerate(S["pieces"]):
        o = _importer_stl(p["stl"])
        o.data.materials.append(_matiere(f"m{i}", p.get("couleur", [0.85, 0.45, 0.15]), p.get("matiere", "plastique")))
        for poly in o.data.polygons: poly.use_smooth = False
        mod = o.modifiers.new("lisse", "EDGE_SPLIT"); mod.split_angle = math.radians(30)
        bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
        bpy.ops.object.shade_smooth()
        objets.append(o)
    # boîte englobante de la scène
    pts = [o.matrix_world @ Vector(c) for o in objets for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    c = (lo + hi) / 2; r = (hi - lo).length / 2
    # studio : fond courbe (cyclorama) gris clair
    bpy.ops.mesh.primitive_plane_add(size=r * 14, location=(c.x, c.y, lo.z - 0.01))
    sol = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.subdivide(number_cuts=40); bpy.ops.object.mode_set(mode="OBJECT")
    for v in sol.data.vertices:   # remonte l'arrière en courbe douce
        y = v.co.y
        if y > r * 1.5: v.co.z = (y - r * 1.5) ** 2 / (r * 2.5)
    sol.data.materials.append(_matiere("fond", S.get("fond", [0.93, 0.93, 0.94]), "mat"))
    bpy.ops.object.shade_smooth()
    # éclairage 3 points (boîtes à lumière)
    for nom, pos, puiss, taille in (("cle", (1.4, -1.6, 1.8), 2400, 1.4), ("remplissage", (-1.8, -1.0, 0.9), 900, 2.2), ("contre", (0.2, 2.0, 1.6), 1300, 1.0)):
        bpy.ops.object.light_add(type="AREA", location=c + Vector(pos) * r * 2.4)
        L = bpy.context.active_object; L.data.energy = puiss * (r / 25) ** 2; L.data.size = taille * r
        d = c - L.location; L.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    w = bpy.data.worlds.new("monde"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.91, 0.93, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.8
    # caméra
    vues = {"iso": (1.0, -1.25, 0.85), "avant": (0.0, -1.0, 0.25), "dessus": (0.05, -0.15, 1.0), "trois-quarts": (-1.1, -1.0, 0.7)}
    dirv = Vector(vues.get(S.get("vue", "iso"), vues["iso"])).normalized()
    bpy.ops.object.camera_add(location=c + dirv * r * 3.9)
    cam = bpy.context.active_object; cam.data.lens = 70
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    # Cycles CPU + débruitage
    sc.render.engine = "CYCLES"; sc.cycles.device = "CPU"; sc.cycles.samples = int(S.get("echantillons", 96))
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = S.get("taille", [1600, 1200]); sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "AgX" if "AgX" in [x.identifier for x in type(sc.view_settings).bl_rna.properties["view_transform"].enum_items] else "Filmic"
    sc.render.filepath = sortie; sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(json.dumps(dict(image=sortie)))


def nettoyer(entree, sortie, lisser=1, faces=200000):
    """Figurine / scan : fusionne les doublons, bouche les trous, lisse doucement, réduit à 'faces', remet étanche (remesh voxel)."""
    _vider()
    o = _importer_stl(entree)
    bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.01); bpy.ops.mesh.fill_holes(sides=0); bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    dims = max(o.dimensions)
    rm = o.modifiers.new("etanche", "REMESH"); rm.mode = "VOXEL"; rm.voxel_size = max(0.15, dims / 400); rm.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=rm.name)
    if lisser:
        sm = o.modifiers.new("lisse", "CORRECTIVE_SMOOTH"); sm.iterations = int(lisser) * 5; sm.factor = 0.5
        bpy.ops.object.modifier_apply(modifier=sm.name)
    if len(o.data.polygons) > faces:
        dec = o.modifiers.new("reduit", "DECIMATE"); dec.ratio = faces / len(o.data.polygons)
        bpy.ops.object.modifier_apply(modifier=dec.name)
    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(filepath=sortie, export_selected_objects=True)
    else:
        bpy.ops.export_mesh.stl(filepath=sortie, use_selection=True)
    print(json.dumps(dict(stl=sortie, faces=len(o.data.polygons), dims=[round(x, 2) for x in o.dimensions])))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "rendu":
        rendu(a[1], a[2])
    elif a and a[0] == "nettoyer":
        kw = {}
        if "--lisser" in a: kw["lisser"] = int(a[a.index("--lisser") + 1])
        if "--faces" in a: kw["faces"] = int(a[a.index("--faces") + 1])
        nettoyer(a[1], a[2], **kw)
    else:
        print(__doc__)
