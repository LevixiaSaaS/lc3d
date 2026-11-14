"""LC3D — export vers FreeCAD avec l'HISTOIRE modifiable (arbre de construction + tableau de paramètres).

Le modèle est construit avec Atelier (lc3d) en utilisant ses gestes paramétriques :
    a = Atelier("corps")
    a.bloc(p["L"], p["l"], p["h"], titre="Tracer le bloc")
    a.trou(p["d"], p["l"] + 2, pos=(0, 0, p["h"] / 2), axe="Y", titre="Percer le trou")
    a.arrondir("|Z", p["r"], titre="Arrondir les coins")
Les valeurs de `p` sont des « Valeur » : des nombres qui se souviennent de leur formule (L - 2 * mur…).
Dans FreeCAD : feuille « Parametres » (L, l, h…) → Bloc (Longueur = Parametres.p_L) → Perçage → Congé.
Change L dans la feuille, tout se recalcule.

Les gestes génériques (a.ajouter(forme quelconque) / a.couper(...)) sont exportés comme formes FIXES dans l'arbre
(visibles, mais pas modifiables par cote). Le rapport dit quelle part de la pièce est vraiment paramétrique.
Limite connue de toutes les CAO (« nommage topologique ») : un congé posé sur des arêtes peut se perdre si une
cote change beaucoup la forme. LC3D teste chaque fichier : il change chaque cote de +10 % et vérifie que tout se recalcule.
"""
import json, os, subprocess, tempfile, math

FREECAD = os.environ.get("LC3D_FREECAD", os.path.join(os.path.expanduser("~"), ".lc3d", "freecad", "squashfs-root", "usr", "bin", "freecadcmd"))


# ------------------------------------------------------------------ nombres qui se souviennent de leur formule
class Valeur(float):
    def __new__(cls, v, expr=None):
        o = float.__new__(cls, v); o.expr = expr if expr is not None else _num(v); return o

    def _op(self, autre, sym, f, inverse=False):
        e2 = autre.expr if isinstance(autre, Valeur) else _num(autre)
        e = f"({e2} {sym} {self.expr})" if inverse else f"({self.expr} {sym} {e2})"
        return Valeur(f(float(autre), float(self)) if inverse else f(float(self), float(autre)), e)

    def __add__(s, o): return s._op(o, "+", lambda a, b: a + b)
    def __radd__(s, o): return s._op(o, "+", lambda a, b: a + b, True)
    def __sub__(s, o): return s._op(o, "-", lambda a, b: a - b)
    def __rsub__(s, o): return s._op(o, "-", lambda a, b: a - b, True)
    def __mul__(s, o): return s._op(o, "*", lambda a, b: a * b)
    def __rmul__(s, o): return s._op(o, "*", lambda a, b: a * b, True)
    def __truediv__(s, o): return s._op(o, "/", lambda a, b: a / b)
    def __rtruediv__(s, o): return s._op(o, "/", lambda a, b: a / b, True)
    def __neg__(s): return Valeur(-float(s), f"(-{s.expr})")
    def __pos__(s): return s


def _num(v):
    return repr(round(float(v), 6))


def expr(v):
    """Formule FreeCAD d'une valeur (nombre ou Valeur)."""
    return v.expr if isinstance(v, Valeur) else _num(v)


def params_parametriques(PARAMS):
    """{L: 60} → {L: Valeur(60, 'Parametres.p_L')} ; les textes / booléens restent tels quels."""
    out = {}
    for k, v in PARAMS.items():
        out[k] = Valeur(v, f"Parametres.p_{k}") if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    return out


# ------------------------------------------------------------------ script exécuté DANS FreeCAD
_SCRIPT_FC = r'''
import json, sys, FreeCAD as App, Part
D = json.load(open(sys.argv[-1] if sys.argv[-1].endswith(".json") else __import__("os").environ["LC3D_RECETTE"]))
doc = App.newDocument(D["nom"])
ss = doc.addObject("Spreadsheet::Sheet", "Parametres"); ss.Label = "Paramètres"
for i, (k, v) in enumerate(D["params"].items(), start=1):
    ss.set(f"A{i}", k); ss.set(f"B{i}", str(v)); ss.setAlias(f"B{i}", "p_" + k)
doc.recompute()
rapport = {"pieces": {}}
AXES = {"X": App.Rotation(App.Vector(0, 1, 0), 90), "Y": App.Rotation(App.Vector(1, 0, 0), -90), "Z": App.Rotation()}

def fixe(nom, brep, label):
    o = doc.addObject("Part::Feature", nom); s = Part.Shape(); s.importBrep(brep); o.Shape = s; o.Label = label; return o

def aretes(forme, sel):
    """Même sélecteur que CadQuery : |X |Y |Z (arêtes droites parallèles), >Z <Z (arêtes du haut / du bas)."""
    out = []
    if sel[0] in "<>":
        # >Z / <Z : EXACTEMENT la règle de CadQuery (DirectionMinMaxSelector) : centre de masse de chaque arête, groupe du
        # plus haut / plus bas à 1e-4 près. (Avant : « tous les sommets au plus haut de la boîte » → un arc qui plonge, ex.
        # l'arche d'un cylindre Y coupé sous la pièce, était aussi arrondi dans FreeCAD mais pas dans LC3D.)
        ax = sel[1].lower()
        cs = [(k, getattr(e.CenterOfMass, ax)) for k, e in enumerate(forme.Edges, start=1) if not getattr(e, "Degenerated", False)]
        if not cs: return out
        m = max(c for _, c in cs) if sel[0] == ">" else min(c for _, c in cs)
        return [k for k, c in cs if abs(c - m) < 1e-4]
    for k, e in enumerate(forme.Edges, start=1):
        # arête dégénérée (pôle d'une sphère, pointe d'un cône) : pas une vraie arête — e.Curve plante
        # (« undefined curve type ») et tout l'export FreeCAD tombait dès qu'une sphère précédait un congé/chanfrein
        if getattr(e, "Degenerated", False): continue
        if sel[0] == "|":
            if not isinstance(e.Curve, Part.Line): continue
            d = e.Vertexes[-1].Point - e.Vertexes[0].Point
            if d.Length < 1e-6: continue
            d.normalize(); a = {"X": abs(d.x), "Y": abs(d.y), "Z": abs(d.z)}[sel[1]]
            # même tolérance que CadQuery (ParallelDirSelector : sinus de l'angle < 1e-4). Avant : 0,999 (≈ 2,5°) → une arête
            # en dépouille de 1° était aussi arrondie dans FreeCAD mais pas dans LC3D
            if a > 1 - 5e-9: out.append(k)
    return out

def mesurer(sh, a):
    # boîte EXACTE : sh.BoundBox prend les pôles des BSplines (filet, hélice → jusqu'à +9 mm de trop)
    try: bb = sh.optimalBoundingBox(False, False)
    except Exception: bb = sh.BoundBox
    sol = sh.Solids or [sh]; vt = sum(s.Volume for s in sol) or 1e-9
    cm = App.Vector(0, 0, 0)
    for s in sol: cm = cm + s.CenterOfMass * (s.Volume / vt)     # centre pondéré des solides (pas celui du compound)
    boite = [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]
    ev = 100 * abs(sh.Volume - a["volume"]) / max(a["volume"], 1e-9)
    ec = max(abs(x - y) for x, y in zip([cm.x, cm.y, cm.z], a["centre"])); eb = max(abs(x - y) for x, y in zip(boite, a["boite"]))
    out = dict(ok=bool(ev < 0.5 and ec < 0.1 and eb < 0.1), volume_pct=round(ev, 3), centre_mm=round(ec, 3), boite_mm=round(eb, 3))
    if a.get("faces") is not None:      # un arrondi sur une arête de trop change à peine le volume, mais pas le nombre de faces
        nfs = {len(sh.Faces)}
        try: nfs.add(len(sh.removeSplitter().Faces))      # FreeCAD et CadQuery ne fusionnent pas toujours les faces coplanaires pareil
        except Exception: pass
        nf = min(nfs, key=lambda x: abs(x - int(a["faces"])))
        out["faces"] = nf; out["faces_attendues"] = int(a["faces"])
        if nf != int(a["faces"]):
            if ev < 0.002 and ec < 0.002 and eb < 0.002:
                # géométrie identique à 0,002 % / 0,002 mm près (un congé de trop ou de moins change le volume d'au moins ~0,02 %) :
                # seul le découpage des faces diffère (FreeCAD / CadQuery fusionnent les faces coplanaires ou cylindriques différemment)
                out["note_faces"] = f"{nf} faces au lieu de {int(a['faces'])} : découpage différent, géométrie identique"
            else:
                out["ok"] = False; out["note_faces"] = "arêtes traitées différentes (nombre de faces ≠ LC3D)"
    return out

def place(o, pos, centre_xy=None, axe="Z"):
    o.Placement.Rotation = AXES.get(axe, App.Rotation())
    for i, c in enumerate("xyz"):
        e = pos[i]
        if centre_xy and c in "xy":
            e = f"({e}) - ({centre_xy[c]}) / 2"
        try: o.setExpression(f".Placement.Base.{c}", str(e))
        except Exception: setattr(o.Placement.Base, c, float(eval(str(e).replace("Parametres.p_", "P_"), {}, {"P_" + k: v for k, v in D["params"].items()})))

for nom_p, gestes in D["pieces"].items():
    courant = None; n_param = 0; n_fixe = 0
    for i, g in enumerate(gestes):
        t = g["type"]; base = f"{nom_p}_{i:02d}"
        if t in ("bloc", "cylindre"):
            if t == "bloc":
                o = doc.addObject("Part::Box", base + "_forme")
                o.setExpression("Length", g["L"]); o.setExpression("Width", g["l"]); o.setExpression("Height", g["h"])
                place(o, g["pos"], centre_xy={"x": g["L"], "y": g["l"]})
            else:
                o = doc.addObject("Part::Cylinder", base + "_forme")
                o.setExpression("Radius", f"({g['d']}) / 2"); o.setExpression("Height", g["h"])
                place(o, g["pos"], axe=g.get("axe", "Z"))
            n_param += 1
        elif t == "fixe":
            o = fixe(base + "_forme", g["brep"], g["titre"]); n_fixe += 1
        elif t in ("arrondi", "chanfrein"):
            if courant is None: continue
            doc.recompute()
            if len(courant.Shape.Solids) > 1 and g.get("brep_apres"):
                # PartDesign ne garde qu'UN solide : sur une pièce à plusieurs corps séparés, le congé jetait les autres corps
                # (−55 % de volume). La pièce exacte de LC3D est reprise figée à partir d'ici (signalée), la suite reste paramétrique.
                o = fixe(base + "_fige", g["brep_apres"], "FIGÉ (plusieurs corps) — " + g["titre"]); n_fixe += 1
                rapport.setdefault("figes", []).append([nom_p, g["titre"]])
                courant.Visibility = False; courant = o
                continue
            # PartDesign : le rayon / la taille est une FORMULE (Part::Fillet ne l'accepte pas)
            corps = doc.addObject("PartDesign::Body", base + "_corps"); corps.BaseFeature = courant; doc.recompute()
            o = corps.newObject("PartDesign::Fillet" if t == "arrondi" else "PartDesign::Chamfer", base)
            o.Base = (corps.BaseFeature, [f"Edge{k}" for k in aretes(courant.Shape, g["selecteur"])])
            o.setExpression("Radius" if t == "arrondi" else "Size", str(g["r"]))
            o.Label = g["titre"]; corps.Label = "Corps — " + g["titre"]
            courant.Visibility = False; courant = corps; n_param += 1
            continue
        elif t == "remplace":
            o = fixe(base, g["brep"], g["titre"]); n_fixe += 1
            if courant is not None: courant.Visibility = False
            courant = o; continue
        else:
            continue
        o.Label = g["titre"] if g.get("op", "ajout") == "ajout" and courant is None else "Outil — " + g["titre"]
        op = g.get("op", "ajout")
        if courant is None:
            courant = o; o.Label = g["titre"]
        else:
            b = doc.addObject("Part::Fuse" if op == "ajout" else "Part::Cut", base)
            b.Base = courant; b.Tool = o; b.Label = g["titre"]; b.Refine = True
            doc.recompute()
            if b.Shape.isNull() or not b.Shape.isValid():   # cas limite (surfaces tangentes) : « Refine » rend la forme invalide → sans
                b.Refine = False; doc.recompute()
            if (b.Shape.isNull() or not b.Shape.isValid()) and t in ("bloc", "cylindre"):
                # faces qui se touchent pile (tenon posé sur le dessus) : FreeCAD (OpenCascade) rate l'union → l'outil entre de
                # 0,001 mm dans la pièce (invisible, volume identique à 0,0001 % près), les cotes restent des formules
                ax = 2 if t == "bloc" else "XYZ".index(g.get("axe", "Z"))
                pos2 = list(g["pos"]); pos2[ax] = f"({pos2[ax]}) - 0.001"
                o.setExpression("Height", f"({g['h']}) + 0.002")
                if t == "bloc": place(o, pos2, centre_xy={"x": g["L"], "y": g["l"]})
                else: place(o, pos2, axe=g.get("axe", "Z"))
                doc.recompute()
            if (b.Shape.isNull() or not b.Shape.isValid()) and g.get("brep_apres"):
                # FreeCAD (OpenCascade) ne sait pas faire cette opération (ex. surfaces tangentes laissées par un geste d'avant) :
                # la pièce EXACTE de LC3D est importée à partir d'ici (figée, signalée), et les gestes suivants restent paramétriques
                doc.removeObject(b.Name); o.Visibility = False
                b = fixe(base + "_fige", g["brep_apres"], "FIGÉ — " + g["titre"]); n_fixe += 1
                rapport.setdefault("figes", []).append([nom_p, g["titre"]])
            courant.Visibility = False; o.Visibility = False; courant = b
    if courant is not None:
        courant.Label = courant.Label + f"  [{nom_p}]"
    doc.recompute()
    rapport["pieces"][nom_p] = dict(volume=courant.Shape.Volume if courant else 0, valide=bool(courant and courant.Shape.isValid()),
                                    gestes_parametriques=n_param, gestes_fixes=n_fixe, dernier=courant.Name if courant else None)

for pn, r in rapport["pieces"].items():
    b = ((D.get("attendus") or {}).get("base") or {}).get(pn)
    if b and r["dernier"]: r["controle"] = mesurer(doc.getObject(r["dernier"]).Shape, b)
# essai : chaque cote +10 %, tout doit se recalculer
essais = {}
for i, (k, v) in enumerate(D["params"].items(), start=1):
    if not isinstance(v, (int, float)) or isinstance(v, bool): continue
    ss.set(f"B{i}", str(v * 1.1)); doc.recompute()
    ok = all(doc.getObject(r["dernier"]).Shape.isValid() and doc.getObject(r["dernier"]).Shape.Volume > 0 for r in rapport["pieces"].values() if r["dernier"])
    erreurs = [o.Label for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]
    att = ((D.get("attendus") or {}).get("essais") or {}).get(k) or {}
    ecarts = {}
    if att.get("mesures") and not att.get("touche_fixe"):
        for pn, r in rapport["pieces"].items():
            if r["dernier"] and pn in att["mesures"]:
                ecarts[pn] = mesurer(doc.getObject(r["dernier"]).Shape, att["mesures"][pn])
    figees = {pn for pn, _ in rapport.get("figes", [])}
    bon_volume = all(e["ok"] or pn in figees for pn, e in ecarts.items())
    if any(not e["ok"] and pn in figees for pn, e in ecarts.items()): att = dict(att, touche_fixe=True)
    essais[k] = dict(ok=ok and not erreurs and bon_volume, erreurs=erreurs[:3], ecarts=ecarts,
                     note=("pièce figée dans FreeCAD avant cette cote" if any(pn in figees for pn in ecarts) and att.get("touche_fixe") else
                           "touche une forme fixe (ne suit pas)") if att.get("touche_fixe") else "")
    ss.set(f"B{i}", str(v)); doc.recompute()
rapport["essais_cotes"] = essais
doc.saveAs(D["sortie"])
json.dump(rapport, open(D["sortie"] + ".json", "w"))
'''


def exporter(recettes, params, nom, chemin_fcstd, attendus=None):
    """recettes : {piece: [gestes]} ; params : PARAMS numériques. Lance FreeCAD sans écran. Retourne le rapport."""
    if not os.path.exists(FREECAD):
        return dict(ok=False, erreur="FreeCAD non installé (lc3d.py freecad-installer)")
    d = tempfile.mkdtemp()
    js = os.path.join(d, "recette.json"); sc = os.path.join(d, "fc.py")
    json.dump(dict(nom=nom.replace(" ", "_"), params={k: v for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
                   pieces=recettes, sortie=os.path.abspath(chemin_fcstd), attendus=attendus), open(js, "w"))
    open(sc, "w").write(_SCRIPT_FC)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", LANG="C.UTF-8", LC3D_RECETTE=js)
    p = subprocess.run([FREECAD, sc], capture_output=True, text=True, timeout=600, env=env)
    try:
        r = json.load(open(chemin_fcstd + ".json")); os.unlink(chemin_fcstd + ".json")
        r["ok"] = True; return r
    except Exception:
        txt = (p.stdout + p.stderr).replace("\r", "\n")
        return dict(ok=False, erreur=[l for l in txt.splitlines() if "rror" in l or "xception" in l][-4:] or txt[-600:])


def installer(version="1.0.2"):
    d = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(FREECAD)))); os.makedirs(d, exist_ok=True)
    ai = os.path.join(d, "fc.AppImage")
    url = f"https://github.com/FreeCAD/FreeCAD/releases/download/{version}/FreeCAD_{version}-conda-Linux-x86_64-py311.AppImage"
    subprocess.run(["curl", "-sL", "-o", ai, url], check=True); os.chmod(ai, 0o755)
    subprocess.run([ai, "--appimage-extract"], cwd=d, check=True, capture_output=True); os.unlink(ai)
    return os.path.exists(FREECAD)
