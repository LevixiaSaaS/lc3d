"""LC3D — export OpenSCAD paramétrique (les cotes deviennent des variables en tête du fichier).

Gestes bloc / cylindre / trou → cube / cylinder, combinés dans l'ORDRE EXACT des gestes (union / difference).
Arrondis et chanfreins sur un bloc seul (arêtes |X, |Y, |Z, >Z, <Z) : exacts et paramétriques
(intersection de 3 profils extrudés : chaque arête du bloc reçoit son coin rond / chanfreiné / vif).
Arrondi ou chanfrein sur une pièce déjà complexe : OpenSCAD n'a pas d'outil pour ça → la pièce est FIGÉE à partir
de ce geste (import d'un STL exact de l'état après le geste) et c'est signalé : les cotes d'avant ne la changent plus.
Gestes fixes / remplace : importés depuis un STL voisin (import()).
"""
import os, re


def _e(x):
    return re.sub(r"Parametres\.p_(\w+)", r"\1", str(x))


# coins d'un profil : ordre (+,+) (-,+) (-,-) (+,-)
_HAUT, _BAS = (0, 1), (2, 3)


def _traiter(info, sel, typ, taille):
    """Ajoute un traitement d'arêtes au bloc. False si la combinaison n'est pas exacte en OpenSCAD."""
    t = info.setdefault("traits", {"X": [None] * 4, "Y": [None] * 4, "Z": [None] * 4})
    cibles = {"|Z": [("Z", range(4))], "|X": [("X", range(4))], "|Y": [("Y", range(4))],
              ">Z": [("X", _HAUT), ("Y", _HAUT)], "<Z": [("X", _BAS), ("Y", _BAS)]}.get(sel)
    if not cibles: return False
    autres_z = any(v for v in t["X"] + t["Y"]); deja_z = any(v for v in t["Z"])
    if (sel == "|Z" and autres_z) or (sel != "|Z" and deja_z): return False     # coins à 3 arêtes : pas exact
    for prof, coins in cibles:
        for i in coins:
            if t[prof][i] is not None: return False                         # arête déjà traitée
    for prof, coins in cibles:
        for i in coins:
            t[prof][i] = (typ, taille)
    return True


def _num(expr, params):
    return float(eval(str(expr), {"__builtins__": {}}, {k: v for k, v in params.items() if isinstance(v, (int, float))}))


def _emboites(blocs, params, r):
    """Vrai si deux blocs qui se chevauchent en hauteur sont l'un strictement DANS l'autre : alors arrondir chaque coin
    vertical de chaque bloc donne exactement la pièce de CadQuery (aucun coin à 3 arêtes, aucune arête coupée)."""
    try:
        rr = _num(r, params)
        B = [(_num(b["x"], params), _num(b["y"], params), _num(b["z"], params), _num(b["Lx"], params), _num(b["Ly"], params), _num(b["h"], params)) for b in blocs]
    except Exception:
        return False
    if any(b.get("traits") for b in blocs): return False
    if any(L_ < 2 * rr - 1e-6 or l_ < 2 * rr - 1e-6 for (_, _, _, L_, l_, _) in B): return False     # coin plus grand que le côté
    for i in range(len(B)):
        for j in range(i + 1, len(B)):
            xi, yi, zi, Li, li, hi_ = B[i]; xj, yj, zj, Lj, lj, hj = B[j]
            if min(zi + hi_, zj + hj) - max(zi, zj) <= 1e-6:          # pas de chevauchement en hauteur : indépendants
                continue
            def dedans(xa, ya, La, la, xb, yb, Lb, lb):            # a strictement dans b (ses arêtes verticales restent entières)
                m = 1e-3
                return (xa - La / 2 >= xb - Lb / 2 + m and xa + La / 2 <= xb + Lb / 2 - m and
                        ya - la / 2 >= yb - lb / 2 + m and ya + la / 2 <= yb + lb / 2 - m)
            if not (dedans(xi, yi, Li, li, xj, yj, Lj, lj) or dedans(xj, yj, Lj, lj, xi, yi, Li, li)):
                return False
    return True


def _profil_txt(traits):
    return "[" + ", ".join(f"[{c[0]}, {c[1]}]" if c else "[0, 0]" for c in traits) + "]"


def exporter(recettes, params, nom, dossier, stl_fixes=None, figer=None, boites=None):
    """figer(piece, i) -> chemin STL de l'état exact après le geste i (pour les gestes non traduisibles).
    Retourne (chemin .scad, rapport) ; rapport = {figes: [(piece, titre)]}."""
    L = [f"// {nom} — généré par LC3D. Changer une variable recalcule la pièce.", "$fn = 96;", ""]
    for k, v in params.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            L.append(f"{k} = {v};")
    L.append("")
    noms_mod = [re.sub(r'[^A-Za-z0-9_]', '_', n) for n in recettes]
    if len(noms_mod) > 1:
        L += [f'piece = "toutes";   // "toutes" (côte à côte) ou une seule : ' + ", ".join(f'"{n}"' for n in noms_mod), ""]
    figes, figes_idx = [], []      # figes_idx : (pièce, n° du geste figé) — les cotes utilisées jusque-là ne peuvent plus suivre
    decalage = 0.0
    for nom_p, gestes in recettes.items():
        L.append(f"// ---- pièce : {nom_p}")
        corps = []           # [(op, code, info_bloc)]
        for i, g in enumerate(gestes):
            t = g["type"]; info = None
            if t == "bloc":
                Lx, Ly, h = _e(g["L"]), _e(g["l"]), _e(g["h"]); x, y, z = (_e(p) for p in g["pos"])
                code = f"translate([({x}) - ({Lx}) / 2, ({y}) - ({Ly}) / 2, {z}]) cube([{Lx}, {Ly}, {h}]);"
                info = dict(Lx=Lx, Ly=Ly, h=h, x=x, y=y, z=z, titre=g.get("titre", ""))
            elif t == "cylindre":
                d, h = _e(g["d"]), _e(g["h"]); x, y, z = (_e(p) for p in g["pos"])
                rot = {"Z": "", "X": "rotate([0, 90, 0]) ", "Y": "rotate([-90, 0, 0]) "}[g.get("axe", "Z")]
                code = f"translate([{x}, {y}, {z}]) {rot}cylinder(d = {d}, h = {h});"
            elif t in ("arrondi", "chanfrein"):
                b = corps[0][2] if len(corps) == 1 and corps[0][0] == "ajout" else None
                if b is not None and _traiter(b, g.get("selecteur"), 1 if t == "arrondi" else 2, _e(g["r"])):
                    tr = b["traits"]
                    code = (f"translate([{b['x']}, {b['y']}, {b['z']}]) bloc_traite({b['Lx']}, {b['Ly']}, {b['h']}, "
                            f"{_profil_txt(tr['X'])}, {_profil_txt(tr['Y'])}, {_profil_txt(tr['Z'])});")
                    b["titres"] = b.get("titres", [b["titre"]]) + [g.get("titre", "")]
                    corps[0] = ("ajout", f"{code}  // {' + '.join(b['titres'])}", b)
                    continue
                # cas très courant : boîte + cavité, couvercle + lèvre — que des blocs EMBOÎTÉS, arrondi « |Z » : chaque coin vertical
                # (dehors comme dedans) devient un rectangle arrondi exact, et tout reste paramétrique
                if g.get("selecteur") == "|Z" and corps and all(c[2] is not None for c in corps) and _emboites([c[2] for c in corps], params, _e(g["r"])):
                    for k_, (o_, c_, b_) in enumerate(corps):
                        tr = b_.setdefault("traits", {"X": [None] * 4, "Y": [None] * 4, "Z": [None] * 4})
                        tr["Z"] = [(1 if t == "arrondi" else 2, _e(g["r"]))] * 4
                        code_ = (f"translate([{b_['x']}, {b_['y']}, {b_['z']}]) bloc_traite({b_['Lx']}, {b_['Ly']}, {b_['h']}, "
                                 f"{_profil_txt(tr['X'])}, {_profil_txt(tr['Y'])}, {_profil_txt(tr['Z'])});")
                        b_["titres"] = b_.get("titres", [b_["titre"]]) + [g.get("titre", "")]
                        corps[k_] = (o_, f"{code_}  // {' + '.join(b_['titres'])}", b_)
                    continue
                if figer is None:
                    raise ValueError(f"geste « {g.get('titre')} » non traduisible en OpenSCAD et rien pour le figer")
                code = f'import("{os.path.basename(figer(nom_p, i))}");'
                corps = [("ajout", f"{code}  // FIGÉ à partir de « {g.get('titre', '')} » (arrondi sur forme complexe)", None)]
                figes.append((nom_p, g.get("titre", ""))); figes_idx.append((nom_p, i))
                continue
            elif t in ("fixe", "remplace") and stl_fixes and (nom_p, i) in stl_fixes:
                code = f'import("{os.path.basename(stl_fixes[(nom_p, i)])}");'
                if t == "remplace": corps = []
            else:
                raise ValueError(f"geste « {g.get('titre')} » ({t}) inconnu de l'export OpenSCAD")
            corps.append((g.get("op", "ajout") if t != "remplace" else "ajout", f"{code}  // {g.get('titre', '')}", info))
        # CSG dans l'ordre EXACT des gestes
        expr = None
        for o, c, _ in corps:
            if expr is None: expr = [c]; continue
            expr = (["union() {"] if o == "ajout" else ["difference() {"]) + ["  " + x for x in expr] + ["  " + c, "}"]
        mod = re.sub(r'[^A-Za-z0-9_]', '_', nom_p)
        L.append(f"module {mod}() {{"); L += ["  " + x for x in (expr or [])]; L.append("}")
        if len(noms_mod) > 1:
            b = (boites or {}).get(nom_p)          # côte à côte pour la vue d'ensemble ; une pièce seule reste à sa vraie place
            dx = (decalage - b[0]) if b else decalage
            L.append(f'if (piece == "{mod}") {mod}();')
            L.append(f'if (piece == "toutes") translate([{dx:.2f}, 0, 0]) {mod}();')
            decalage += ((b[3] - b[0]) if b else 60.0) + 15.0
        else:
            L.append(f"{mod}();")
        L.append("")
    L += [
        "// profil a × b centré ; coins (+,+) (-,+) (-,-) (+,-) : [0,0] vif, [1,r] rond, [2,c] chanfrein",
        "module profil(a, b, t) {",
        "  hull() for (i = [0:3]) {",
        "    sx = [1, -1, -1, 1][i]; sy = [1, 1, -1, -1][i]; s = t[i][1];",
        "    if (t[i][0] == 1) translate([sx * (a / 2 - s), sy * (b / 2 - s)]) circle(r = s);",
        "    else if (t[i][0] == 2) polygon([[sx * (a / 2 - s), sy * b / 2], [sx * a / 2, sy * (b / 2 - s)], [sx * (a / 2 - s), sy * (b / 2 - s)]]);",
        "    else polygon([[sx * a / 2, sy * b / 2], [sx * (a / 2 - 0.01), sy * b / 2], [sx * a / 2, sy * (b / 2 - 0.01)]]);",
        "  }",
        "}",
        "// bloc Lx × Ly × h centré en X/Y, de z = 0 à h ; tX : arêtes le long de X (profil Y-Z), tY : le long de Y (profil X-Z), tZ : verticales",
        "module bloc_traite(Lx, Ly, h, tX, tY, tZ) {",
        "  intersection() {",
        "    linear_extrude(h) profil(Lx, Ly, tZ);",
        "    translate([-Lx / 2, 0, h / 2]) rotate([90, 0, 90]) linear_extrude(Lx) profil(Ly, h, tX);",
        "    translate([0, Ly / 2, h / 2]) rotate([90, 0, 0]) linear_extrude(Ly) profil(Lx, h, tY);",
        "  }",
        "}",
    ]
    f = os.path.join(dossier, f"{nom}.scad"); open(f, "w").write("\n".join(L))
    return f, dict(figes=figes, figes_idx=figes_idx)
