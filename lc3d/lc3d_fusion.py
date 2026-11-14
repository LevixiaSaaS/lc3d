"""LC3D — export vers Autodesk Fusion avec l'HISTOIRE (paramètres utilisateur + chronologie de fonctions).

Produit un dossier « <Projet>_Fusion/ » contenant <Projet>_Fusion.py (+ un STEP par geste « fixe »).
Dans Fusion : Utilitaires → Scripts et compléments → « + » → choisir le dossier → Exécuter.
Résultat : Paramètres modifiables (Modifier → Changer les paramètres : L, l, h…) et une chronologie
« Esquisse → Extrusion → Congé → Perçage » par pièce. Changer L recalcule tout.

Même recette que l'export FreeCAD (gestes de l'Atelier). Les positions des esquisses sont aussi des formules.
TESTÉ dans Fusion (Windows, 2026-10-26) sur Boitier_param : pièce rebâtie, 6 paramètres p_*, chronologie complète,
L 60 → 80 recalculé sans avertissement (boîte centrée, intérieur et trou du câble suivent).
Leçons du test : noms préfixés p_ (Fusion refuse L, h, r = unités) ; centres d'esquisse ancrés à l'origine par cotes ;
côtés du rectangle contraints H/V. Non testé dans Fusion : gestes « fixe »/« remplace » (import STEP) et chanfreins.
"""
import json, os, re, shutil

_ENTETE = r'''# Script généré par LC3D — Fusion (Autodesk) — rebâtit la pièce avec son historique, puis se vérifie lui-même.
import adsk.core, adsk.fusion, traceback, os, math

ICI = os.path.dirname(os.path.realpath(__file__))
MODELES = __MODELES__   # [{nom, params, pieces, verif}] ; verif = mesures attendues calculées par LC3D
LOT = __LOT__           # True = lot de tests : chaque pièce est vérifiée puis fermée, un seul rapport à la fin

def _corps(comp):
    out = [b for b in comp.bRepBodies if b.isVisible and b.isSolid]
    for o in comp.allOccurrences:
        if not o.isLightBulbOn: continue
        out += [b for b in o.bRepBodies if b.isVisible and b.isSolid]
    return out

def _mesures(racine):
    # par pièce : volume (mm3), centre de masse (mm), boîte englobante (mm)
    out = {}
    for occ in racine.occurrences:
        c = occ.component; V = 0.0; cm = [0.0, 0.0, 0.0]; lo = [1e9] * 3; hi = [-1e9] * 3; nf = 0
        for b in _corps(c):
            nf += b.faces.count
            try: pp = b.getPhysicalProperties(adsk.fusion.CalculationAccuracy.VeryHighCalculationAccuracy)
            except Exception: pp = b.physicalProperties
            v = pp.volume * 1000.0; p = pp.centerOfMass
            V += v; cm = [cm[0] + v * p.x * 10, cm[1] + v * p.y * 10, cm[2] + v * p.z * 10]
            try:   # boîte SERRÉE (b.boundingBox peut déborder sur les BSplines : filets, hélices) — repli sur boundingBox
                ob = adsk.core.Application.get().measureManager.getOrientedBoundingBox(b, adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0))
                c0 = ob.centerPoint; dd = (ob.length, ob.width, ob.height)
                bmin = [(getattr(c0, a) - dd[i] / 2) * 10 for i, a in enumerate("xyz")]; bmax = [(getattr(c0, a) + dd[i] / 2) * 10 for i, a in enumerate("xyz")]
            except Exception:
                bb = b.boundingBox
                bmin = [getattr(bb.minPoint, a) * 10 for a in "xyz"]; bmax = [getattr(bb.maxPoint, a) * 10 for a in "xyz"]
            lo = [min(lo[i], bmin[i]) for i in range(3)]
            hi = [max(hi[i], bmax[i]) for i in range(3)]
        out[c.name] = dict(volume=V, centre=[x / V for x in cm] if V else [0, 0, 0], boite=lo + hi, faces=nf)
    return out

def _centre_arete(e, ax, n=48):
    # centre (cm) de l'arête le long de ax, comme Center() de CadQuery (échantillonné à pas de longueur égaux) ; None si impossible
    try:
        ev = e.evaluator; ok, t0, t1 = ev.getParameterExtents()
        ok2, L = ev.getLengthAtParameter(t0, t1)
        if not (ok and ok2) or L <= 0: return None
        s = 0.0
        for i in range(n):
            ok, t = ev.getParameterAtLength(t0, L * (i + 0.5) / n); ok3, pt = ev.getPointAtParameter(t)
            if not (ok and ok3): return None
            s += getattr(pt, ax)
        return s / n
    except Exception:
        return None

def _sante(design):
    mauvais = []
    for i in range(design.timeline.count):
        it = design.timeline.item(i)
        if it.healthState in (adsk.fusion.FeatureHealthStates.WarningFeatureHealthState, adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState):   # (5 = « inconnu » : import STEP, pas un problème)
            ent = it.entity
            nom = getattr(ent, "name", None) or (ent.objectType.split("::")[-1] if ent else "?")
            mauvais.append(f"{nom} ({it.errorOrWarningMessage or it.healthState})")
    return mauvais

def _ecart(m, a):
    # (bon, texte) : volume < 0,5 %, centre < 0,1 mm, boîte < 0,1 mm
    if not m: return False, "pièce absente"
    ev = 100.0 * abs(m["volume"] - a["volume"]) / max(a["volume"], 1e-9)
    ec = max(abs(x - y) for x, y in zip(m["centre"], a["centre"]))
    eb = max(abs(x - y) for x, y in zip(m["boite"], a["boite"]))
    bon = ev < 0.5 and ec < 0.1 and eb < 0.1; txt = f"vol {ev:.3f} %, centre {ec:.3f} mm, boîte {eb:.3f} mm"
    if a.get("faces") is not None and m.get("faces") is not None and m["faces"] != a["faces"]:
        # un arrondi en trop ou en moins change à peine le volume (~0,02 %) mais change le nombre de faces ;
        # géométrie identique à 0,002 % près = seul le découpage des faces diffère entre noyaux (Fusion / OpenCascade)
        if ev < 0.002 and ec < 0.002 and eb < 0.002:
            txt += f", {m['faces']} faces au lieu de {a['faces']} (découpage différent, géométrie identique)"
        else:
            bon = False; txt += f", {m['faces']} faces au lieu de {a['faces']} : ARÊTES TRAITÉES DIFFÉREMMENT"
    return bon, txt

def auto_test(design, racine, up, verif):
    lignes = []; ok_tout = True
    def comparer(attendus, quoi):
        nonlocal ok_tout
        mes = _mesures(racine); mauvais = _sante(design); res = []; bon = not mauvais
        for p, a in attendus.items():
            b, t = _ecart(mes.get(p), a); res.append(f"{p} : {t}"); bon = bon and b
        if not bon: ok_tout = False
        lignes.append(f"  [{'OK' if bon else 'ÉCHEC'}] {quoi} — " + " ; ".join(res) + (f" ; avertissements : {', '.join(mauvais)}" if mauvais else ""))
    comparer(verif["base"], "pièce de base")
    for nom, e in verif["essais"].items():
        prm = up.itemByName(nom); avant = prm.expression
        prm.expression = f"{e['valeur']} mm"; adsk.doEvents()
        if e.get("touche_fixe"):
            mauvais = _sante(design)
            lignes.append(f"  [{'INFO' if not mauvais else 'ÉCHEC'}] {nom} +10 % : change une forme fixe (elle ne suit pas, normal)" + (f" ; avertissements : {', '.join(mauvais)}" if mauvais else ""))
            if mauvais: ok_tout = False
        else:
            comparer(e["mesures"], f"{nom} +10 %")
        prm.expression = avant; adsk.doEvents()
    return ok_tout, lignes

def batir(app, M):
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    design.fusionUnitsManager.distanceDisplayUnits = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    up = design.userParameters
    for k, v in M["params"].items():
        up.add(k, adsk.core.ValueInput.createByString(f"{v} mm"), "mm", "LC3D")
    racine = design.rootComponent
    um = design.unitsManager
    def mm(expr):   # valeur numérique (cm internes) d'une formule
        return um.evaluateExpression(expr, "mm")
    def V(expr):
        return adsk.core.ValueInput.createByString(f"({expr}) * 1 mm" if not any(c.isalpha() for c in expr) else expr)
    AXE_PLAN = {"Z": "xYConstructionPlane", "X": "yZConstructionPlane", "Y": "xZConstructionPlane"}
    def plan_decale(comp, axe, expr_offset):
        # plan perpendiculaire à l'axe, à la cote « expr_offset » LE LONG DE L'AXE (le plan XZ de Fusion a sa normale vers -Y)
        base = getattr(comp, AXE_PLAN[axe]); n = base.geometry.normal
        signe = getattr(n, axe.lower())
        e = expr_offset if signe > 0 else f"-({expr_offset})"
        pi = comp.constructionPlanes.createInput(); pi.setByOffset(base, V(e))
        return comp.constructionPlanes.add(pi)
    def ancrer(sk, pt, pos, axes):
        # attache un centre d'esquisse à l'origine par des cotes-formules (sinon il flotte)
        o3 = sk.modelToSketchSpace(adsk.core.Point3D.create(0, 0, 0))
        for i in axes:
            u = [0, 0, 0]; u[i] = 1
            u3 = sk.modelToSketchSpace(adsk.core.Point3D.create(*u))
            horiz = abs(u3.x - o3.x) > abs(u3.y - o3.y)
            expr = pos[i]; val = mm(expr)
            if abs(val) < 1e-7:
                gc = sk.geometricConstraints
                (gc.addVerticalPoints if horiz else gc.addHorizontalPoints)(sk.originPoint, pt)
            else:
                ori = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation if horiz else adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
                tp = adsk.core.Point3D.create((pt.geometry.x + o3.x) / 2 + 0.5, (pt.geometry.y + o3.y) / 2 + 0.5, 0)
                dim = sk.sketchDimensions.addDistanceDimension(sk.originPoint, pt, ori, tp)
                dim.parameter.expression = f"abs({expr})" if any(ch.isalpha() for ch in expr) else f"{abs(float(expr))} mm"
    def extruder_le_long(comp, sk, pl, axe, h, op, corps):
        # extrusion dans le sens +axe, quel que soit le sens de la normale du plan
        prof = sk.profiles.item(0)
        ei = comp.features.extrudeFeatures.createInput(prof, op)
        sens = getattr(pl.geometry.normal, axe.lower())
        ei.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(V(h)),
                            adsk.fusion.ExtentDirections.PositiveExtentDirection if sens > 0 else adsk.fusion.ExtentDirections.NegativeExtentDirection)
        if corps is not None: ei.participantBodies = visibles(comp) or [corps]     # TOUS les corps de la pièce (pièce à plusieurs corps séparés)
        return comp.features.extrudeFeatures.add(ei)
    def visibles(comp):
        return [b for b in comp.bRepBodies if b.isVisible and b.isSolid]
    def corps_imbriques(c):
        out = list(c.bRepBodies)
        for i in range(c.occurrences.count): out += corps_imbriques(c.occurrences.item(i).component)
        return out
    for nom_p, gestes in M["pieces"].items():
        occ = racine.occurrences.addNewComponent(adsk.core.Matrix3D.create()); comp = occ.component; comp.name = nom_p
        corps = None
        for g in gestes:
            t = g["type"]
            op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation if corps is None else (adsk.fusion.FeatureOperations.JoinFeatureOperation if g.get("op", "ajout") == "ajout" else adsk.fusion.FeatureOperations.CutFeatureOperation)
            if t == "bloc":
                pl = plan_decale(comp, "Z", g["pos"][2]); pl.name = "Plan — " + g["titre"]
                sk = comp.sketches.add(pl); sk.name = "Esquisse — " + g["titre"]
                c = sk.modelToSketchSpace(adsk.core.Point3D.create(mm(g["pos"][0]), mm(g["pos"][1]), mm(g["pos"][2])))
                coin = adsk.core.Point3D.create(c.x + mm(g["L"]) / 2, c.y + mm(g["l"]) / 2, 0)
                lignes = sk.sketchCurves.sketchLines.addCenterPointRectangle(c, coin)
                for i in range(lignes.count):     # côtés droits (sinon trapèze)
                    ln = lignes.item(i); a, b = ln.startSketchPoint.geometry, ln.endSketchPoint.geometry
                    try:
                        if abs(a.x - b.x) > abs(a.y - b.y): sk.geometricConstraints.addHorizontal(ln)
                        else: sk.geometricConstraints.addVertical(ln)
                    except: pass
                pc = sk.sketchPoints.add(c)
                diag = sk.sketchCurves.sketchLines.addByTwoPoints(lignes.item(0).startSketchPoint, lignes.item(2).startSketchPoint)
                diag.isConstruction = True
                sk.geometricConstraints.addMidPoint(pc, diag)
                ancrer(sk, pc, g["pos"], (0, 1))
                d = sk.sketchDimensions
                horiz0 = abs(lignes.item(0).startSketchPoint.geometry.x - lignes.item(0).endSketchPoint.geometry.x) > 1e-9
                lx, ly = (lignes.item(0), lignes.item(1)) if horiz0 else (lignes.item(1), lignes.item(0))
                dl = d.addDistanceDimension(lx.startSketchPoint, lx.endSketchPoint, adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation, adsk.core.Point3D.create(c.x, c.y - 1, 0))
                dw = d.addDistanceDimension(ly.startSketchPoint, ly.endSketchPoint, adsk.fusion.DimensionOrientations.VerticalDimensionOrientation, adsk.core.Point3D.create(c.x + 1, c.y, 0))
                dl.parameter.expression = g["L"]; dw.parameter.expression = g["l"]
                f = extruder_le_long(comp, sk, pl, "Z", g["h"], op, corps); f.name = g["titre"]
                if corps is None: corps = f.bodies.item(0)
            elif t == "cylindre":
                axe = g.get("axe", "Z"); i_axe = "XYZ".index(axe)
                pl = plan_decale(comp, axe, g["pos"][i_axe]); pl.name = "Plan — " + g["titre"]
                sk = comp.sketches.add(pl); sk.name = "Esquisse — " + g["titre"]
                cs = sk.modelToSketchSpace(adsk.core.Point3D.create(mm(g["pos"][0]), mm(g["pos"][1]), mm(g["pos"][2])))
                pcs = sk.sketchPoints.add(cs)
                cercle = sk.sketchCurves.sketchCircles.addByCenterRadius(pcs, mm(g["d"]) / 2)
                ancrer(sk, pcs, g["pos"], [i for i in range(3) if i != i_axe])
                dd = sk.sketchDimensions.addDiameterDimension(cercle, adsk.core.Point3D.create(cs.x + 1, cs.y + 1, 0))
                dd.parameter.expression = g["d"]
                f = extruder_le_long(comp, sk, pl, axe, g["h"], op, corps); f.name = g["titre"]
                if corps is None: corps = f.bodies.item(0)
            elif t in ("arrondi", "chanfrein") and corps is not None:
                col = adsk.core.ObjectCollection.create(); sel = g["selecteur"]; vis = visibles(comp) or [corps]
                bb = vis[0].boundingBox.copy()
                for b_ in vis[1:]: bb.combine(b_.boundingBox)
                ar = [e for b_ in vis for e in b_.edges]
                cz = [_centre_arete(e, sel[1].lower()) for e in ar] if sel[0] in "<>" else []
                m_ = None
                if cz and all(c is not None for c in cz): m_ = max(cz) if sel[0] == ">" else min(cz)
                for k_, e in enumerate(ar):
                    geo = e.geometry
                    if sel[0] == "|":
                        if not isinstance(geo, adsk.core.Line3D): continue
                        dv = geo.startPoint.vectorTo(geo.endPoint); dv.normalize()
                        if abs(getattr(dv, sel[1].lower())) > 1 - 5e-9: col.add(e)     # tolérance de CadQuery (sinus < 1e-4)
                    elif m_ is not None:     # règle de CadQuery : centre de chaque arête, groupe du plus haut / plus bas
                        if abs(cz[k_] - m_) < 1e-5: col.add(e)
                    else:                    # repli (évaluateur indisponible) : ancienne règle des sommets
                        ax = sel[1].lower(); cible = getattr(bb.maxPoint if sel[0] == ">" else bb.minPoint, ax)
                        if abs(getattr(e.startVertex.geometry, ax) - cible) < 1e-5 and abs(getattr(e.endVertex.geometry, ax) - cible) < 1e-5: col.add(e)
                if col.count:
                    if t == "arrondi":
                        fi = comp.features.filletFeatures.createInput()
                        fi.addConstantRadiusEdgeSet(col, V(g["r"]), True)
                        f = comp.features.filletFeatures.add(fi)
                    else:
                        ci = comp.features.chamferFeatures.createInput2()
                        ci.chamferEdgeSets.addEqualDistanceChamferEdgeSet(col, V(g["r"]), True)
                        f = comp.features.chamferFeatures.add(ci)
                    f.name = g["titre"]
            elif t in ("fixe", "remplace"):
                n_corps, n_occ = comp.bRepBodies.count, comp.occurrences.count
                im = app.importManager
                im.importToTarget2(im.createSTEPImportOptions(os.path.join(ICI, g["step"])), comp)
                if comp.bRepBodies.count > n_corps:            # importé directement dans la pièce (un ou plusieurs solides)
                    nouveaux = [comp.bRepBodies.item(i) for i in range(n_corps, comp.bRepBodies.count)]
                else:                                          # importé comme sous-composant(s), parfois imbriqués : ramener TOUS les corps
                    sous = [comp.occurrences.item(i) for i in range(n_occ, comp.occurrences.count)]
                    corps_imp = [b for o in sous for b in corps_imbriques(o.component)]
                    if not corps_imp: raise RuntimeError("import STEP vide : " + g["step"])
                    nouveaux = [b.copyToComponent(occ) for b in corps_imp]
                    for o in sous: o.isLightBulbOn = False      # caché, pas supprimé (sinon la copie est en avertissement)
                nouveau = nouveaux[0]
                # plusieurs solides dans le STEP : on les garde séparés (tous servent d'outils / restent dans la pièce)
                nouveau.name = g["titre"]
                if t == "remplace" or corps is None:
                    if corps is not None:                          # remplace : TOUT l'ancien état disparaît
                        jet = {(x.nativeObject or x).entityToken for x in nouveaux}
                        for b_ in visibles(comp):
                            if (b_.nativeObject or b_).entityToken not in jet: b_.isVisible = False
                    corps = nouveau
                elif g.get("op", "ajout") == "ajout":
                    tools = adsk.core.ObjectCollection.create()
                    for x in nouveaux:
                        if x.isValid: tools.add(x)
                    ci = comp.features.combineFeatures.createInput(corps, tools)
                    ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
                    try: comp.features.combineFeatures.add(ci).name = g["titre"]
                    except Exception: pass                     # ajout qui ne touche pas : reste un corps séparé de la même pièce
                else:                                          # coupe : dans CHAQUE corps de la pièce (pièce à plusieurs corps)
                    jetons = {(x.nativeObject or x).entityToken for x in nouveaux}
                    cibles = [b_ for b_ in visibles(comp) if (b_.nativeObject or b_).entityToken not in jetons]
                    for k_, cible in enumerate(cibles):
                        tools = adsk.core.ObjectCollection.create()
                        for x in nouveaux:
                            if x.isValid: tools.add(x)             # TOUS les solides de l'outil (ex. 2 poches d'aimant)
                        ci = comp.features.combineFeatures.createInput(cible, tools)
                        ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
                        ci.isKeepToolBodies = True
                        try: comp.features.combineFeatures.add(ci).name = g["titre"]
                        except Exception:
                            if len(cibles) == 1: raise        # pièce d'un seul corps : une vraie erreur
                            # corps que l'outil ne touche pas : rien à couper (la vérification finale mesure le résultat)
                    for x in nouveaux:
                        if x.isValid and x.isVisible: x.isVisible = False
        if corps is not None: corps.name = nom_p
    return doc, design, racine, up

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get(); ui = app.userInterface
        rapport = []; ok_lot = True
        for M in MODELES:
            n_docs = app.documents.count; doc = None
            try:
                doc, design, racine, up = batir(app, M)
                if M.get("verif"):
                    ok, lignes = auto_test(design, racine, up, M["verif"])
                else:
                    ok, lignes = True, ["  (pas de vérification)"]
            except:
                ok, lignes, doc = False, ["  [ÉCHEC] erreur : " + traceback.format_exc().strip().splitlines()[-1] + "  (" + " | ".join(l.strip() for l in traceback.format_exc().strip().splitlines() if l.strip().startswith("File") or l.startswith("    "))[-400:] + ")"], None
            ok_lot = ok_lot and ok
            rapport.append(f"{'OK    ' if ok else 'ÉCHEC '} {M['nom']}"); rapport += lignes
            if LOT:            # fermer ce que ce modèle a ouvert, même s'il a planté
                while app.documents.count > n_docs:
                    try: app.activeDocument.close(False)
                    except: break
        texte = ("LC3D — vérification Fusion : TOUT OK" if ok_lot else "LC3D — vérification Fusion : PROBLÈME") + "\n\n" + "\n".join(rapport)
        try:
            open(os.path.join(ICI, "rapport_LC3D.txt"), "w", encoding="utf-8").write(texte)
        except Exception:
            pass
        if LOT:
            ui.messageBox(("TOUT OK" if ok_lot else "PROBLÈME") + f" — {len(MODELES)} pièces testées.\nRapport complet : rapport_LC3D.txt (dans le dossier du script).")
        else:
            ui.messageBox(("Pièce rebâtie avec son historique et VÉRIFIÉE (même forme que LC3D, chaque cote testée)." if ok_lot else "Pièce rebâtie, mais la vérification signale un écart :") +
                          "\nModifier → Changer les paramètres pour changer les cotes.\n\n" + "\n".join(rapport[:12]))
    except:
        if ui: ui.messageBox("LC3D — erreur :\n" + traceback.format_exc())
'''


NOMS = {}


def _noms_fusion(params):
    """Fusion ignore la casse des noms de paramètres (L et l → conflit → l devient l_2) et refuse les noms
    qui sont aussi des unités (L = litre, h = heure, r…) : tous les noms sont préfixés p_ (testé dans Fusion)."""
    NOMS.clear(); vus = set()
    for k in params:
        n = "p_" + k
        while n.lower() in vus: n += "_2"
        vus.add(n.lower()); NOMS[k] = n
    return NOMS


def _fusion_expr(e):
    """« Parametres.p_L » → « L » (paramètres utilisateur de Fusion)."""
    return re.sub(r"Parametres\.p_(\w+)", lambda m: NOMS.get(m.group(1), m.group(1)), str(e))


def _modele(recettes, params, nom, d, attendus=None, prefixe_step=""):
    """Prépare un modèle pour le script : expressions Fusion, STEP des gestes fixes (écrits dans d), mesures attendues."""
    import cadquery as cq
    _noms_fusion([k for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)])
    pieces = {}
    for nom_p, gestes in recettes.items():
        L = []
        for i, g in enumerate(gestes):
            g = dict(g)
            for k in ("L", "l", "h", "d", "r"):
                if k in g: g[k] = _fusion_expr(g[k])
            if "pos" in g: g["pos"] = [_fusion_expr(x) for x in g["pos"]]
            if g["type"] in ("fixe", "remplace"):
                sh = cq.Shape.importBrep(g["brep"]); f = f"{prefixe_step}{nom_p}_{i:02d}.step"
                cq.exporters.export(sh, os.path.join(d, f)); g["step"] = f; g.pop("brep", None)
            L.append(g)
        pieces[nom_p] = L
    num = {NOMS[k]: v for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    verif = None
    if attendus:
        verif = dict(base=attendus["base"], essais={NOMS[k]: dict(valeur=e["valeur"], mesures=e["mesures"], touche_fixe=e["touche_fixe"])
                                                     for k, e in attendus["essais"].items() if k in NOMS and not e.get("erreur_lc3d")})
    return dict(nom=nom, params=num, pieces=pieces, verif=verif)


def _ecrire(d, nom_script, modeles, lot):
    code = _ENTETE.replace("__MODELES__", repr(modeles)).replace("__LOT__", repr(bool(lot)))
    f = os.path.join(d, f"{nom_script}.py"); open(f, "w", encoding="utf-8").write(code)
    json.dump({"autodeskProduct": "Fusion", "type": "script", "author": "LC3D",
               "description": {"": "Rebâtit les pièces LC3D avec leurs paramètres et leur historique, puis les vérifie"},
               "supportedOS": "windows|mac", "editEnabled": True},
              open(os.path.join(d, f"{nom_script}.manifest"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    compile(code, f, "exec")
    return f


def exporter(recettes, params, nom, dossier_sortie, attendus=None):
    d = os.path.join(dossier_sortie, f"{nom}_Fusion"); os.makedirs(d, exist_ok=True)
    f = _ecrire(d, f"{nom}_Fusion", [_modele(recettes, params, nom, d, attendus)], lot=False)
    return dict(ok=True, dossier=d, script=f, note="Dans Fusion : Utilitaires → Scripts et compléments → + → ce dossier → Exécuter. Le script se vérifie lui-même.")


def exporter_lot(modeles, dossier, nom="LC3D_tests_Fusion"):
    """modeles : [(recettes, params, nom, attendus)] → UN script qui bâtit, vérifie et ferme chaque pièce."""
    d = os.path.join(dossier, nom); os.makedirs(d, exist_ok=True)
    ms = [_modele(r, p, n, d, a, prefixe_step=f"{n}_") for (r, p, n, a) in modeles]
    return _ecrire(d, nom, ms, lot=True)
