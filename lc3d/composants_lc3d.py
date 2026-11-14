"""LC3D — catalogue de composants réutilisables (« mets le clip n° 1 »).
Chaque composant : une fonction paramétrique qui renvoie les formes CadQuery + ses cotes + ses forces calculées.
Statut : « calculé » (passe les vérifs LC3D) → « validé » seulement après une VRAIE impression réussie (photo à l'appui)
(lc3d.py composant valider <numéro> --projet ...). Les numéros ne changent jamais.
"""
import json, math, os, time
import cadquery as cq

FICHIER_STATUTS = os.path.join(os.path.expanduser("~"), ".lc3d", "composants.json")


def _statuts():
    try: return json.load(open(FICHIER_STATUTS))
    except Exception: return {}


def valider(numero, projet, note=""):
    s = _statuts(); s[str(numero)] = dict(statut="validé (impression réelle)", projet=projet, note=note, date=time.strftime("%Y-%m-%d"))
    os.makedirs(os.path.dirname(FICHIER_STATUTS), exist_ok=True); json.dump(s, open(FICHIER_STATUTS, "w"), ensure_ascii=False, indent=1)
    return s[str(numero)]


# ------------------------------------------------------------------ n° 1 : clip en porte-à-faux (face carrée + rampe 30°)
def clip_1(L=12.0, h=1.6, w=6.0, accroche=1.0, rampe=30.0, retenue=90.0, jeu=0.3, mur=2.0, materiau="PETG"):
    """Bras flexible qui clipse dans une fenêtre. Retourne dict(bras, fenetre_a_soustraire, logement_flexion, cotes, calcul).
    Repère : base du bras à z = 0 (sur la pièce porteuse), bras vers -Z, crochet vers +X. La fenêtre est dans la paroi en face."""
    import lc3d
    bras = cq.Workplane("XY").box(h, w, L).translate((0, 0, -L / 2))
    hc = accroche / math.tan(math.radians(rampe))         # hauteur de la rampe d'entrée
    zt = -L + hc + 1.0                                   # haut du plat du crochet
    monte = 0.0 if retenue >= 89.9 else accroche / math.tan(math.radians(retenue))
    crochet = (cq.Workplane("XZ").polyline([(h / 2, zt + monte), (h / 2 + accroche, zt), (h / 2 + accroche, -L + hc), (h / 2, -L)])
               .close().extrude(w / 2, both=True))
    # face de retenue (haut du crochet) : 90° = permanent; 45° = s'enlève en tirant fort; 30° = s'ouvre à la main (calcul : calc_snap alpha_out)
    bras = bras.union(crochet)
    lx = accroche + jeu + mur + 1.0   # traverse tout le mur : une vraie fenêtre, pas une peau mince au fond
    # hauteur de la fenêtre = rampe + plat + MONTÉE de la face de retenue (face < 90° : elle monte de accroche/tan(retenue))
    # + jeu en haut et en bas. Sans « monte », un crochet à 45° restait enfoncé ~0,4 mm fermé (bras plié en permanence, vu en essai réel).
    hf = hc + 1.0 + monte
    fenetre = cq.Workplane("XY").box(lx, w + 2 * jeu, hf + 2 * jeu).translate((h / 2 + lx / 2 - 0.25, 0, -L + hf / 2))
    flexion = cq.Workplane("XY").box(accroche + 0.3, w + 2 * jeu, L).translate((-h / 2 - (accroche + 0.3) / 2, 0, -L / 2))   # vide derrière le bras pour plier
    calc = lc3d.calc_snap(L, h, w, accroche, materiau, rampe, retenue)
    return dict(bras=bras, fenetre_a_soustraire=fenetre, logement_flexion=flexion, calcul=calc,
                cotes=dict(L=L, h=h, w=w, accroche=accroche, rampe=rampe, retenue=retenue, jeu=jeu, hauteur_fenetre=round(hf + 2 * jeu, 2)), numero=1, nom="clip en porte-à-faux")


# ------------------------------------------------------------------ n° 2 : bossage pour insert à chaud
def bossage_insert_2(taille="M3", hauteur=8.0):
    import lc3d
    c = lc3d.calc_bossage(taille, "insert")
    boss = cq.Workplane("XY").circle(c["diametre_bossage_min"] / 2).extrude(hauteur)
    trou = lc3d.trou_vis(taille, "insert", profondeur=c["profondeur_trou"], z=hauteur)
    return dict(bossage=boss.cut(trou), trou_a_soustraire=trou, cotes=c, numero=2, nom=f"bossage insert {taille}")


# ------------------------------------------------------------------ n° 3 : logement d'écrou captif (inséré par le côté)
def ecrou_captif_3(taille="M3", ouverture="cote", longueur_fente=10.0):
    import lc3d
    V = lc3d.VIS_ISO[taille]; e = V["ecrou"] + lc3d.JEU_ECROU; hn = V["h_ecrou"] + 0.4
    poche = cq.Workplane("XY").polygon(6, e / math.cos(math.radians(30))).extrude(hn)
    if ouverture == "cote":   # fente pour glisser l'écrou de côté (imprimable sans support si le plafond fait ≤ 12 mm)
        poche = poche.union(cq.Workplane("XY").box(longueur_fente, e, hn).translate((longueur_fente / 2, 0, hn / 2)))
    trou = cq.Workplane("XY").circle(lc3d.TROUS_FDM["passage"][taille] / 2).extrude(30).translate((0, 0, -15))
    return dict(a_soustraire=poche.union(trou), cotes=dict(entre_plats=e, hauteur=hn), numero=3, nom=f"écrou captif {taille}")


# ------------------------------------------------------------------ n° 4 : logement de roulement
def logement_roulement_4(ref="608", serrage="leger"):
    import lc3d
    L = lc3d.logement_roulement(ref, serrage)
    return dict(a_soustraire=cq.Workplane("XY").circle(L["diametre"] / 2).extrude(L["profondeur"]).translate((0, 0, -L["profondeur"])), cotes=L, numero=4, nom=f"logement {ref}")


# ------------------------------------------------------------------ n° 5 : couvercle vissé (filet imprimé)
def couvercle_filete_5(diametre=40.0, pas=4.0, hauteur_filet=14.0, jeu=0.3, paroi=2.0, plafond=2.0, prof=0.8, entree=False, sommet=0.2):
    """Pot + couvercle vissé, imprimable debout SANS support : filet trapézoïdal à flancs de 45°, 2 filets dans un pas avec jeu.
    Engagement radial = prof − jeu (0,5 mm par défaut). Filet du couvercle placé pour 0,2 mm de jeu axial, arrêté à 1,3 mm du plafond (pas de fente)."""
    t = float(sommet)                                   # plat au sommet du filet (≥ 0,9 : 2 lignes de buse, aussi en hauteur — essai réel)
    base = 2 * prof + t                                 # 45° : le flanc monte autant qu'il avance
    if base > 0.47 * pas: raise ValueError(f"filet trop profond pour ce pas : base {base:.2f} > 0,47 × pas")
    def helice(r_base, sortant, h, z0=0.0):
        s_ = 1 if sortant else -1
        pts = [(r_base, 0), (r_base + s_ * prof, prof), (r_base + s_ * prof, prof + t), (r_base, base)]
        hel = cq.Wire.makeHelix(pas, h, r_base)
        return cq.Workplane("XZ").polyline(pts).close().sweep(cq.Workplane("XY").add(hel), isFrenet=True).translate((0, 0, z0))
    r_col = diametre / 2
    col = cq.Workplane("XY").circle(r_col).circle(r_col - paroi).extrude(hauteur_filet)
    # v3 essai réel : le filet du col monte jusqu'à 0,8 mm du haut (avant : s'arrêtait 1 pas plus bas → prise réelle ≈ 0,6 tour)
    h_col = hauteur_filet - base - 1.1 if entree else hauteur_filet - pas - base
    col = col.union(helice(r_col - 0.01, True, h_col, z0=0.3))
    r_int = r_col + jeu
    couv = cq.Workplane("XY").circle(r_int + paroi + prof).extrude(hauteur_filet + plafond).cut(cq.Workplane("XY").circle(r_int + prof).extrude(hauteur_filet))
    # placement axial : flancs parallèles à 45°, 0,2 mm de jeu axial en tirant (le couvercle ne branle pas)
    z0v = 0.3 + jeu + pas - prof - t - 0.2
    h_couv = hauteur_filet - 1.3 - base - z0v
    couv = couv.union(helice(r_int + prof + 0.01, False, h_couv, z0=z0v))
    if entree:
        # ENTRÉE CHANFREINÉE (v2, revue du 28 oct.) : le 1er filet ne commence plus par une marche franche.
        # Col : cône 45° qui rabote le haut du filet sur sa dernière profondeur. Couvercle : même cône au début du filet.
        z_haut = 0.3 + h_col + base
        zone = cq.Workplane("XY").add(cq.Solid.makeCylinder(r_col + prof + 3, hauteur_filet + 2 - (z_haut - prof), cq.Vector(0, 0, z_haut - prof)))
        zone = zone.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(r_col - 0.005, hauteur_filet + 4, cq.Vector(0, 0, z_haut - prof - 1))))
        cone = cq.Workplane("XY").add(cq.Solid.makeCone(r_col + prof + 0.01, r_col - 0.01, prof + 0.01, cq.Vector(0, 0, z_haut - prof)))
        col = col.cut(zone.cut(cone), clean=False)
        cone_c = cq.Workplane("XY").add(cq.Solid.makeCone(r_int + prof + 0.01, r_int - 0.01, prof + 0.02, cq.Vector(0, 0, z0v - 0.01)))
        couv = couv.cut(cone_c, clean=False)
    return dict(col=col, couvercle=couv, cotes=dict(diametre=diametre, pas=pas, jeu_radial=jeu, profondeur_filet=prof, engagement=round(prof - jeu, 2),
                tours_col=round(h_col / pas, 2), tours_couvercle=round(h_couv / pas, 2)), numero=5, nom="couvercle vissé")


# ------------------------------------------------------------------ n° 6 : poche d'aimant (insérée en pause ou serrée)
def poche_aimant_6(d=6.0, e=2.0, serrage="serre"):
    j = {"serre": 0.10, "colle": 0.20}[serrage]
    return dict(a_soustraire=cq.Workplane("XY").circle(d / 2 + j + 0.075).extrude(e + 0.2).translate((0, 0, -(e + 0.2))),
                cotes=dict(diametre=d + 2 * j + 0.15, profondeur=e + 0.2, note="+0,15 de compensation trou FDM"), numero=6, nom=f"poche aimant {d}×{e}")


# ------------------------------------------------------------------ n° 7 : goupille d'alignement + trous
def goupille_alignement_7(d=4.0, longueur=10.0, jeu=0.15):
    g = cq.Workplane("XY").circle(d / 2).extrude(longueur).faces(">Z or <Z").chamfer(0.4)
    t = cq.Workplane("XY").circle(d / 2 + jeu + 0.075).extrude(longueur / 2 + 0.3).translate((0, 0, -(longueur / 2 + 0.3)))
    return dict(goupille=g, trou_a_soustraire=t, cotes=dict(d=d, trou=d + 2 * jeu + 0.15), numero=7, nom=f"goupille Ø{d}")


CATALOGUE_COMPOSANTS = {1: clip_1, 2: bossage_insert_2, 3: ecrou_captif_3, 4: logement_roulement_4, 5: couvercle_filete_5, 6: poche_aimant_6, 7: goupille_alignement_7}


def liste():
    s = _statuts()
    noms = {1: "clip en porte-à-faux (face carrée/45°/30° + rampe 30°)", 2: "bossage pour insert à chaud", 3: "logement d'écrou captif (fente latérale)",
            4: "logement de roulement (presse/léger/libre)", 5: "pot + couvercle vissé (filet 45°, sans support)", 6: "poche d'aimant", 7: "goupille d'alignement + trous"}
    return [dict(numero=n, nom=noms.get(n, f.__name__), fonction=f.__name__, statut=s.get(str(n), {}).get("statut", "calculé (passe les vérifs LC3D, pas encore imprimé)"))
            for n, f in CATALOGUE_COMPOSANTS.items()]
