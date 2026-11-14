#!/usr/bin/env python3
"""LC3D — conception, vérification et livraison de pièces imprimées en 3D (FDM). Auteur : LevixiaSaaS.
Principales commandes :
  python lc3d.py run modele.py [--out dossier] [--imprimante "x1c"] [--studio --photo --zip Projet_v1]   vérifie tout + livre
  python lc3d.py apercu modele.py --out ap                         aperçu rapide pour le Studio (sans vérification)
  python lc3d.py cao modele.py --out cao                            FreeCAD / Fusion / OpenSCAD / STEP / IGES (vérifiés)
  python lc3d.py retour modele.py boite=boite.step                  la pièce revient de SolidWorks / Fusion : tout revérifier
  python lc3d.py imprimante "prusa core one"                        trouver une machine (~1 150 profils)
  python lc3d.py check piece.stl · calc snap L=12 h=1.6 w=6 y=1.0 · composants · composant fiche 8 · miroir · variantes
  python lc3d.py orca-installer · bambu-installer · freecad-installer
Le fichier modèle définit PARAMS (dict), build(p) -> {nom: Piece|forme}, et optionnellement assembly(p, pieces) -> Assemblage.
"""
from __future__ import annotations
import argparse, glob, importlib.util, json, math, os, re, sys, tempfile, time, traceback, zipfile
from dataclasses import dataclass, field
import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

# ----------------------------------------------------------------------------
# Machine, matériaux, règles
# ----------------------------------------------------------------------------
MACHINE = dict(nom="Bambu Lab P2S", lit=(256.0, 256.0, 256.0), buse=0.4, largeur_ligne=0.42,
               couche=0.2, parois=2, remplissage=0.15, couches_pleines=4)

MATERIAUX = {  # E (MPa), limite (MPa), deformation admissible snap-fit, densite, frottement
    "PLA":  dict(E=3500, sigma=50, eps=0.015, rho=1.24, mu=0.35, note="rigide, cassant; snap-fit court"),
    "PETG": dict(E=2000, sigma=50, eps=0.025, rho=1.27, mu=0.30, note="bon pour clips et lames"),
    "ABS":  dict(E=2200, sigma=40, eps=0.025, rho=1.04, mu=0.30, note="enceinte fermée"),
    "ASA":  dict(E=2200, sigma=45, eps=0.025, rho=1.07, mu=0.30, note="extérieur, UV"),
    "PA":   dict(E=1800, sigma=55, eps=0.04, rho=1.12, mu=0.25, note="nylon, très tenace, sécher"),
    "TPU":  dict(E=26,   sigma=35, eps=0.50, rho=1.21, mu=0.60, note="flexible 95A"),
    # pièces achetées (masse / centre de gravité seulement)
    "acier":     dict(E=200000, sigma=400, eps=0.002, rho=7.85, mu=0.15, note="vis, roulements, ressorts"),
    "aluminium": dict(E=69000, sigma=150, eps=0.002, rho=2.70, mu=0.30, note=""),
    "laiton":    dict(E=100000, sigma=200, eps=0.002, rho=8.50, mu=0.30, note="inserts"),
    "neodyme":   dict(E=160000, sigma=80, eps=0.0005, rho=7.50, mu=0.30, note="aimants"),
}

# --- Noms de matériaux : tout ce que les gens écrivent (insensible à la casse) -> nom canonique, type du profil de filament
# des logiciels (filament_type de Bambu Studio / OrcaSlicer) et famille mécanique (MATERIAUX). Jamais de substitution en
# silence : une variante sans profil propre (PLA+, Silk, TPU 85A) prend le profil de sa famille AVEC une note dans le rapport.
# (motif, canonique, type de profil, famille mécanique, abrasif, note)
_NOMS_MATERIAUX = [
    (r"(pa|nylon|pa6|pa12|paht|pa ?6|pa ?12)[\s_-]*cf", "PA-CF", "PA-CF", "PA", True, None),
    (r"(pa|nylon|pa6|pa12)[\s_-]*gf", "PA-GF", "PA-GF", "PA", True, None),
    (r"pla[\s_-]*cf", "PLA-CF", "PLA-CF", "PLA", True, None),
    (r"petg[\s_-]*cf", "PETG-CF", "PETG-CF", "PETG", True, None),
    (r"pet[\s_-]*cf", "PET-CF", "PET-CF", "PETG", True, None),
    (r"asa[\s_-]*cf", "ASA-CF", "ASA-CF", "ASA", True, None),
    (r"abs[\s_-]*gf", "ABS-GF", "ABS-GF", "ABS", True, None),
    (r"ppa[\s_-]*cf", "PPA-CF", "PPA-CF", "PA", True, None),
    (r"(pla[\s_-]*(\+|plus|pro|tough\+?)|pla\+)", "PLA+", "PLA", "PLA", False, "PLA+ : pas de profil « PLA+ » dans les logiciels : profil PLA de la même famille (températures PLA, régler +5 à +10 °C si le fabricant le demande)"),
    (r"(silk[\s_-]*pla|pla[\s_-]*silk)", "PLA Silk", "PLA", "PLA", False, "PLA Silk : profil PLA (Silk si la machine en a un); plus fragile que le PLA ordinaire"),
    (r"pla[\s_-]*matt?e", "PLA Matte", "PLA", "PLA", False, None),
    (r"pla[\s_-]*(generique|générique|generic)", "PLA générique", "PLA", "PLA", False, None),
    (r"pla", "PLA", "PLA", "PLA", False, None),
    (r"petg[\s_-]*basic", "PETG Basic", "PETG", "PETG", False, None),
    (r"petg[\s_-]*(generique|générique|generic)", "PETG générique", "PETG", "PETG", False, None),
    (r"petg([\s_-]*hf)?", "PETG", "PETG", "PETG", False, None),
    (r"pctg", "PCTG", "PCTG", "PETG", False, None),
    (r"abs", "ABS", "ABS", "ABS", False, None),
    (r"asa", "ASA", "ASA", "ASA", False, None),
    (r"(pc|polycarbonate?)", "PC", "PC", "PC", False, None),
    (r"(pa|nylon|pa6|pa12|polyamide)", "PA", "PA", "PA", False, None),
    (r"(tpu[\s_-]*(85|87|90) ?a?)", "TPU 85A-90A", "TPU", "TPU", False, "TPU plus mou que 95A : profil TPU (95A) de la machine — imprimer lentement (≤ 3 mm³/s), extrudeur direct, jamais par l'AMS"),
    (r"(tpu([\s_-]*9[58] ?a?)?|flex)", "TPU", "TPU", "TPU", False, None),
    (r"pva", "PVA", "PVA", None, False, None),
    (r"hips", "HIPS", "HIPS", None, False, None),
    (r"pp", "PP", "PP", None, False, None),
]


def normaliser_materiau(texte):
    """« pla », « Nylon », « pa6-cf », « TPU 95A »… -> dict(nom, type, famille, abrasif, note). ValueError si inconnu."""
    t = str(texte or "").strip().lower().replace("é", "e").replace("è", "e")
    t = re.sub(r"\s+", " ", t)
    for motif, canon, typ, fam, abr, note in _NOMS_MATERIAUX:
        if re.fullmatch(motif.replace("générique", "generique"), t):
            return dict(nom=canon, type=typ, famille=fam, abrasif=abr, note=note, ecrit=texte)
    connus = "PLA, PLA+, PLA-CF, PLA Silk, PETG, PETG-CF, PCTG, ABS, ASA, PC, PA (Nylon), PA-CF, TPU (95A, 85A), PVA, HIPS, PP"
    raise ValueError(f"matériau « {texte} » inconnu de LC3D (ni profil de filament ni propriétés mécaniques). Matériaux reconnus : {connus}.")


def proprietes_materiau(texte, defaut="PETG"):
    """Propriétés mécaniques (MATERIAUX) de la famille du matériau, sinon celles de `defaut`."""
    if texte in MATERIAUX: return MATERIAUX[texte]
    try:
        f = normaliser_materiau(texte)["famille"]
        return MATERIAUX.get(f, MATERIAUX[defaut])
    except ValueError:
        return MATERIAUX[defaut]


REGLES = dict(mur_min=1.5, mur_absolu=0.84, mur_physique=0.78, pont_max_importe=50.0, fente_min=1.2, jeu_mobile=0.5, accroche_min=1.0,
              bec_min=2.0, surplomb_max=45.0, pont_max=12.0, ilot_aire_min=0.05,
              contrainte_maintenue=25.0, contrainte_momentanee=35.0, contrainte_fatigue=20.0)
REGLES_DEFAUT = dict(REGLES)


# ----------------------------------------------------------------------------
# Garde-fous : chaque vérification LOURDE tourne dans un sous-processus plafonné (mémoire + temps).
# Si elle dépasse : ligne « non vérifié (trop lourd / trop long) » ⚠️ et le run CONTINUE (jamais tué par la mémoire).
# Plafond mémoire = mémoire virtuelle déjà occupée + GARDE["mem_mo"] (RLIMIT_AS). Réglable : LC3D_MEM_MO, LC3D_DELAI_S.
# ----------------------------------------------------------------------------
GARDE = dict(actif=os.name == "posix" and hasattr(os, "fork") and os.environ.get("LC3D_GARDE", "1") != "0",
             mem_mo=int(os.environ.get("LC3D_MEM_MO", 2048)), delai_s=float(os.environ.get("LC3D_DELAI_S", 150)))
# mode rapide (run --rapide / apercu --verif) : vérifs essentielles à pas grossier pour itérer en 1-2 min
RAPIDE = dict(actif=False, affiner_faces=50000, rayons_faces=120000, points_diag=60000, points_locaux=12000, couches_max=160, pas_montage_mm=2.0,
              arc_max=1.5, delai_s=45.0, mem_mo=1536)
_GARDE_FILS = dict(dans=False, fin=None)
NON_VERIFIES = []          # [(nom, raison)] du run en cours


class NonVerifie(Exception):
    """Vérification abandonnée par le garde-fou (trop lourde ou trop longue)."""


def _vm_octets():
    try:
        return int(open("/proc/self/statm").read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        return 0


def _etat_picklable(d):
    import pickle
    out = {}
    for k, v in d.items():
        try: pickle.dumps(v); out[k] = v
        except Exception: pass
    return out


def garde(nom, fn, *a, etat=None, mem_mo=None, delai_s=None, **k):
    """Exécute fn(*a, **k) dans un sous-processus (fork) plafonné en mémoire et en temps. Retourne sa valeur.
    etat = objet (ex. Assemblage) dont les attributs modifiés par fn sont recopiés dans le processus principal.
    Dépassement : lève NonVerifie(raison). Une erreur normale de fn est relancée telle quelle."""
    import pickle, select, signal, resource, warnings
    if RAPIDE["actif"]:
        mem_mo = min(mem_mo or RAPIDE["mem_mo"], RAPIDE["mem_mo"]); delai_s = min(delai_s or RAPIDE["delai_s"], RAPIDE["delai_s"])
    mem_mo = mem_mo or GARDE["mem_mo"]; delai_s = delai_s or GARDE["delai_s"]
    if _GARDE_FILS["fin"] is not None:               # garde imbriquée : jamais plus long que ce qui reste au parent
        delai_s = min(delai_s, max(1.0, _GARDE_FILS["fin"] - time.time() - 2.0))
    if not GARDE["actif"] or _GARDE_FILS["dans"]:      # déjà dans un sous-processus plafonné : pas de fork imbriqué (risque de blocage)
        return fn(*a, **k)
    r, w = os.pipe()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pid = os.fork()
    if pid == 0:                                      # ---- sous-processus
        os.close(r)
        try:
            lim = _vm_octets() + int(mem_mo) * 2 ** 20
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            if soft != resource.RLIM_INFINITY: lim = min(lim, soft)
            resource.setrlimit(resource.RLIMIT_AS, (lim, hard))
            _GARDE_FILS.update(dans=True, fin=time.time() + delai_s)
            try:
                v = fn(*a, **k)
                d = pickle.dumps(("ok", v, _etat_picklable(etat.__dict__) if etat is not None else None), protocol=pickle.HIGHEST_PROTOCOL)
            except MemoryError:
                d = pickle.dumps(("mem", None, None))
            except BaseException as e:
                try: d = pickle.dumps(("err", e, traceback.format_exc()[-1500:]))
                except Exception: d = pickle.dumps(("err", RuntimeError(f"{type(e).__name__}: {e}"), traceback.format_exc()[-1500:]))
            with os.fdopen(w, "wb") as f: f.write(d)
        except MemoryError:
            pass
        except BaseException:
            pass
        os._exit(0)
    os.close(w)                                       # ---- processus principal
    morceaux = []; fin = time.time() + delai_s; raison = None
    try:
        while True:
            reste = fin - time.time()
            if reste <= 0: raison = f"trop long : > {delai_s:.0f} s"; break
            prets, _, _ = select.select([r], [], [], min(reste, 1.0))
            if prets:
                c = os.read(r, 1 << 22)
                if not c: break
                morceaux.append(c)
    finally:
        os.close(r)
        if raison:
            try: os.kill(pid, signal.SIGKILL)
            except Exception: pass
        try: _, statut = os.waitpid(pid, 0)
        except Exception: statut = 0
    if raison is None:
        if not morceaux:
            raison = f"trop lourd : mémoire > {mem_mo} Mo" + (f" (sous-processus tué, signal {os.WTERMSIG(statut)})" if os.WIFSIGNALED(statut) else "")
        else:
            try:
                st, v, ex = pickle.loads(b"".join(morceaux))
            except Exception as e:
                st, v, ex = "mem", None, None
            if st == "ok":
                if etat is not None and ex: etat.__dict__.update(ex)
                return v
            if st == "mem": raison = f"trop lourd : mémoire > {mem_mo} Mo"
            else:
                if ex: setattr(v, "trace_fils", ex)
                raise v
    NON_VERIFIES.append((nom, raison))
    raise NonVerifie(raison)


def res_non_verifie(nom, raison):
    return res(f"{nom} : NON VÉRIFIÉ", AVERT, f"non vérifié ({raison}) — le run a continué sans ce contrôle",
               conseil="Ce point n'est PAS prouvé. Relancer plus large (LC3D_MEM_MO=4096 LC3D_DELAI_S=400), ou vérifier cette pièce / ce sous-ensemble seul.")


def garde_res(nom, fn, *a, **k):
    """garde() pour une vérification qui retourne une liste de lignes res : en cas de dépassement, une ligne ⚠️ « non vérifié »."""
    try:
        return garde(nom, fn, *a, **k)
    except NonVerifie as e:
        return [res_non_verifie(nom, str(e))]


@dataclass
class Piece:
    """Une pièce à imprimer. forme = CadQuery Workplane/Shape, build123d, ou trimesh."""
    nom: str
    forme: object
    materiau: str = "PETG"
    copies: int = 1
    role: str = "rigide"            # rigide | flexible (lames/clips: murs minces permis)
    mur_min: float | None = None    # surcharge de la règle globale pour cette pièce
    axe_flexion: tuple | None = None  # axe long des lames, doit être dans le plan XY à l'impression
    orientation: object = "auto"    # "auto" | "telle" | matrice 4x4 | (axe, angle_deg)
    couleur: tuple = (0.75, 0.78, 0.82)
    mesh: trimesh.Trimesh | None = None
    usage: str | None = None        # ex. "enfant_moins_3" : vérif petites pièces (16 CFR 1501 / EN 71-1) + arêtes vives
    connecteurs: list | None = None  # pièce achetée : prises (USB, jack…) vérifiées AUTOMATIQUEMENT (fiche réelle doit les atteindre)
    imprimer_avec: object = None     # nom d'une autre pièce : imprimées ENSEMBLE, déjà montées (charnière print-in-place), positions du modèle gardées
    cretes_voulues: object = None   # crêtes/sommets minces VOULUS : True (toute la pièce) ou [((x0,y0,z0),(x1,y1,z1)), ...] (repère du modèle) -> ⚠️ au lieu de ❌
    importee: bool | None = None    # pièce de tiers (STL/STEP importé, retour CAO) : limites PHYSIQUES d'impression, pas les règles de conception LC3D.
                                    # None = automatique (forme donnée en maillage = importée)


@dataclass
class Assemblage:
    """Position finale des pièces + contraintes + chemins de montage."""
    poses: dict = field(default_factory=dict)        # nom -> 4x4 (position finale)
    jeux: list = field(default_factory=list)          # (a, b, jeu_min)
    clips: list = field(default_factory=list)         # (a, b, accroche_attendue_mm)
    sequence: list = field(default_factory=list)      # étapes de montage
    etats: list = field(default_factory=list)         # (nom_etat, {piece: 4x4 relatif})

    def place(self, nom, x=0, y=0, z=0, rot=None):
        M = trimesh.transformations.translation_matrix((x, y, z))
        if rot is not None:
            axe, ang = rot
            M = M @ trimesh.transformations.rotation_matrix(math.radians(ang), axe)
        self.poses[nom] = M
        return self

    def jeu(self, a, b, minimum=None, maximum=None):
        """Jeu entre a et b : minimum (défaut : jeu mobile 0,5 mm) et, si donné, maximum (sinon trop lâche : ça ballotte)."""
        self.jeux.append((a, b, REGLES["jeu_mobile"] if minimum is None else minimum))
        if maximum is not None: self.__dict__.setdefault("jeux_max", {})[frozenset((a, b))] = float(maximum)
        return self

    def ajustement(self, a, b, type="glissant"):
        """Ajustement voulu entre a et b (calc_ajustement) : presse_forte, presse, glissant_dur, glissant, libre, mobile, lache.
        Le jeu mesuré (par côté, dessiné) doit être dans la fourchette de ce type."""
        c = normaliser_cible(type); seuils = [(j, normaliser_cible(n.split(" (")[0])) for j, n in AJUSTEMENTS_FDM]
        k = next((i for i, (_, n) in enumerate(seuils) if n == c), None)
        if k is None: raise ValueError(f"ajustement « {type} » inconnu : {', '.join(n for _, n in seuils)}")
        mini = seuils[k][0]; maxi = seuils[k + 1][0] if k + 1 < len(seuils) else None
        self.__dict__.setdefault("ajustements", []).append(dict(a=a, b=b, type=c, mini=mini, maxi=maxi)); return self

    def bec(self, piece, zone, minimum=2.0):
        """Bec / languette pour l'ongle (ou pour ouvrir) : zone = ((x0, y0, z0), (x1, y1, z1)) dans le repère de la pièce.
        Son épaisseur doit être ≥ minimum (2 mm : en dessous il casse ou plie)."""
        self.__dict__.setdefault("becs", []).append(dict(piece=piece, zone=zone, minimum=minimum)); return self

    def clip(self, a, b, accroche=1.0, L=None, h=None, w=None, mat="PETG", alpha_in=30.0, alpha_out=90.0, usage="momentane", conique=False, demontable=None):
        """Clip de la pièce a qui plie en passant sur b. Avec L/h/w (bras en porte-à-faux), la force et la contrainte
        sont calculées avec la flexion RÉELLE mesurée pendant la simulation du montage.
        demontable=True : on doit pouvoir le déclipser sans rien briser (retenue < 90° et retrait ≤ 30 N, sinon ❌);
        demontable=False : fermeture permanente voulue."""
        self.clips.append((a, b, accroche))
        self.clips_calc = getattr(self, "clips_calc", {})
        self.__dict__.setdefault("clips_info", {})[frozenset((a, b))] = dict(a=a, b=b, alpha_out=alpha_out, demontable=demontable)
        if L and h and w:
            self.clips_calc[frozenset((a, b))] = dict(L=L, h=h, w=w, mat=mat, alpha_in=alpha_in, alpha_out=alpha_out, usage=usage, conique=conique, accroche=accroche)
        return self

    def connecteur(self, piece, type, position, direction, haut=None, nom=None):
        """Prise d'une pièce achetée INCONNUE du catalogue (ou ajoutée) : type = usb_a | usb_b | usb_c | micro_usb | barillet_5.5;
        position = centre de la face d'entrée de la prise, direction = vers où sort la fiche (vers l'extérieur), dans le repère de la pièce;
        haut = sens de la hauteur de la fiche (défaut +Z). LC3D vérifie tout seul qu'une VRAIE fiche de câble (surmoulage) l'atteint."""
        if _type_fiche(type) is None: raise ValueError(f"connecteur « {type} » inconnu : {', '.join(FICHES_CABLE)}")
        self.__dict__.setdefault("connecteurs", []).append(dict(piece=piece, type=_type_fiche(type), pos=tuple(map(float, position)),
                                                                 dir=tuple(map(float, direction)), haut=None if haut is None else tuple(map(float, haut)), nom=nom))
        return self

    def contact(self, a, b, zone, raison="contact voulu (lame-ressort sur son patin, butée)"):
        """Contact VOULU entre a et b pendant un mouvement, limité à une boîte zone=((x0,y0,z0),(x1,y1,z1)) dans le repère
        ASSEMBLÉ : ce qui se chevauche DANS la boîte n'est pas une collision (le reste l'est toujours)."""
        self.__dict__.setdefault("contacts", []).append(dict(a=a, b=b, zone=(tuple(map(float, zone[0])), tuple(map(float, zone[1]))), raison=raison))
        return self

    def serrage(self, a, b, interference_mm, force_max_N=None):
        """Ajustement SERRÉ voulu (arbre de 8,1 dans un roulement 608, bouton emmanché sur son axe) : a et b se chevauchent
        EXPRÈS de interference_mm (au rayon). Ce n'est pas une collision : LC3D vérifie que l'interférence mesurée ≈ celle
        déclarée (±0,05 mm), laisse le montage entrer en forçant, et estime la force d'emmanchement."""
        self.__dict__.setdefault("serrages", []).append(dict(a=a, b=b, i=float(interference_mm), force_max_N=force_max_N)); return self

    def inserer(self, nom, depuis=(0, 0, 40), pas=40):
        """La pièce arrive en ligne droite depuis 'depuis' (relatif à sa pose finale)."""
        self.sequence.append(dict(type="translation", piece=nom, depuis=tuple(depuis), pas=pas)); return self

    def pivoter(self, nom, pivot, axe, angle, pas=36):
        """La pièce arrive en tournant de 'angle' degrés autour de pivot/axe jusqu'à sa pose."""
        self.sequence.append(dict(type="rotation", piece=nom, pivot=tuple(pivot), axe=tuple(axe), angle=angle, pas=pas)); return self

    def etat(self, nom, deplacements):
        """État de fonctionnement (ex. bouton enfoncé). deplacements: {piece: (dx,dy,dz) ou 4x4}."""
        self.etats.append((nom, deplacements)); return self

    def ressort(self, nom, frottement_N, type="lame", precharge=0.0, course=0.0, mat="PETG", L=None, h=None, w=None,
                d_fil=None, D_moyen=None, spires=None, usage="fatigue"):
        """Tout ce qui doit revenir tout seul (bouton, poussoir, cliquet). Vérifié AUTOMATIQUEMENT :
        force à la position la PLUS DÉTENDUE (la précharge) ≥ 3× les frottements, et contrainte à pleine course.
        type='lame' (L, h, w en mm, plastique) ou 'helice' (acier : d_fil, D_moyen, spires).
        precharge = flèche déjà présente au repos (mm) : sans précharge, la force tombe à 0 en fin de retour."""
        self.__dict__.setdefault("ressorts", []).append(dict(nom=nom, frottement_N=frottement_N, type=type, precharge=precharge, course=course,
                                                              mat=mat, L=L, h=h, w=w, d_fil=d_fil, D_moyen=D_moyen, spires=spires, usage=usage))
        return self



# ----------------------------------------------------------------------------
# Atelier : construire une pièce GESTE PAR GESTE (le Studio rejoue chaque geste
# comme quelqu'un qui dessine : croquis tracé, extrusion qui monte, perçage qui entre)
# ----------------------------------------------------------------------------
JOURNAL = []          # [{piece, titre, op, outil, apres}] rempli pendant build()


class Atelier:
    """a = Atelier("corps"); a.ajouter(forme, "Bloc 60 × 40"); a.couper(trou, "Trou Ø10"); a.modifier(lambda f: f.edges("|Z").fillet(3), "Arrondis R3")
    a.forme = la forme courante (CadQuery Workplane). Les mêmes opérations que d'habitude, mais chaque geste est noté."""
    def __init__(self, piece, forme=None):
        self.piece, self.forme = piece, forme

    def _noter(self, titre, op, outil):
        JOURNAL.append(dict(piece=self.piece, titre=titre, op=op, outil=outil, apres=self.forme))

    @staticmethod
    def _lourd(outil):
        # filets, hélices, textes : des centaines de faces. Le « clean » d'OpenCascade (fusion des faces coplanaires)
        # peut alors exploser en mémoire (vu : taraudage M27 → > 7 Go). On le saute pour ces outils-là.
        try:
            o = outil.val() if hasattr(outil, "val") else outil
            fs = o.Faces()
            return len(fs) > 150 or any(f.geomType() in ("BSPLINE", "BEZIER", "OFFSET", "OTHER") for f in fs)
        except Exception:
            return False

    def ajouter(self, outil, titre="Ajouter"):
        self.forme = outil if self.forme is None else self.forme.union(outil, clean=not self._lourd(outil))
        self._noter(titre, "ajout", outil); return self

    def couper(self, outil, titre="Couper"):
        self.forme = self.forme.cut(outil, clean=not self._lourd(outil))
        self._noter(titre, "coupe", outil); return self

    def tarauder(self, taille="M8", longueur=10.0, pos=(0, 0, 0), compensation=None, titre=None):
        """Taraudage ISO vertical (+Z depuis pos) : alésage au Ø nominal puis ajout des filets.
        Plus sûr que couper(filet(..., externe=False)) pour les gros Ø : solide valide, peu de mémoire."""
        import cadquery as cq
        from bd_warehouse.thread import IsoThread
        D = float(taille[1:]); P = VIS_ISO.get(taille, dict(pas=None))["pas"] or {10: 1.5, 12: 1.75}.get(int(D), 1.5)
        c = 0.15 if compensation is None else compensation
        if D < 5: raise ValueError("Filets imprimés < M5 : trop fins pour une buse 0,4 — utiliser un insert.")
        fil = cq.Shape.cast(IsoThread(major_diameter=D, pitch=P, length=float(longueur), external=False,
                                      end_finishes=("square", "square"), manufacturing_compensation=c).wrapped)
        r = min(fil.BoundingBox().xmax, fil.BoundingBox().ymax) - 0.05
        x, y, z = map(float, pos)
        self.forme = self.forme.cut(cq.Workplane("XY").add(cq.Solid.makeCylinder(r, float(longueur), cq.Vector(x, y, z))))
        self.forme = self.forme.union(cq.Workplane("XY").add(fil.translate(cq.Vector(x, y, z))), clean=False)
        self._noter(titre or f"Tarauder {taille} × {P:g}", "coupe", None); return self

    def modifier(self, f, titre="Modifier"):
        self.forme = f(self.forme)
        self._noter(titre, "modif", None); JOURNAL[-1]["recette"] = dict(type="remplace"); return self

    # --- gestes PARAMÉTRIQUES (exportés vers FreeCAD avec leurs formules : changer une cote recalcule tout)
    def _rec(self, **r):
        JOURNAL[-1]["recette"] = r

    def bloc(self, L, l, h, pos=(0, 0, 0), titre=None, op="ajout"):
        """Bloc L (X) × l (Y) × h (Z), centré en X/Y sur pos, posé à z = pos[2]."""
        import cadquery as cq
        o = cq.Workplane("XY").box(float(L), float(l), float(h)).translate((float(pos[0]), float(pos[1]), float(pos[2]) + float(h) / 2))
        (self.ajouter if op == "ajout" else self.couper)(o, titre or f"Bloc {float(L):g} × {float(l):g} × {float(h):g}")
        from lc3d_freecad import expr as E
        self._rec(type="bloc", op=op, L=E(L), l=E(l), h=E(h), pos=[E(x) for x in pos]); return self

    def cylindre(self, d, h, pos=(0, 0, 0), axe="Z", titre=None, op="ajout"):
        """Cylindre Ø d, longueur h, qui part de pos le long de +axe (X, Y ou Z)."""
        import cadquery as cq
        dirv = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[axe]
        o = cq.Workplane("XY").add(cq.Solid.makeCylinder(float(d) / 2, float(h), cq.Vector(*map(float, pos)), cq.Vector(*dirv)))
        (self.ajouter if op == "ajout" else self.couper)(o, titre or f"Cylindre Ø{float(d):g}")
        from lc3d_freecad import expr as E
        self._rec(type="cylindre", op=op, d=E(d), h=E(h), pos=[E(x) for x in pos], axe=axe); return self

    def trou(self, d, prof, pos=(0, 0, 0), axe="Z", titre=None):
        """Perçage Ø d de profondeur prof, qui part de pos le long de +axe."""
        return self.cylindre(d, prof, pos, axe, titre or f"Percer Ø{float(d):g}", op="coupe")

    def arrondir(self, selecteur, r, titre=None):
        """Congé de rayon r sur les arêtes « |X », « |Y », « |Z », « >Z » ou « <Z »."""
        try:
            self.forme = self.forme.edges(selecteur).fillet(float(r))
        except Exception as e:
            raise ValueError(_conge_impossible(self.forme, selecteur, float(r), "arrondi", e)) from None
        self._noter(titre or f"Arrondir R{float(r):g}", "modif", None)
        from lc3d_freecad import expr as E
        self._rec(type="arrondi", selecteur=selecteur, r=E(r), r_val=float(r)); return self

    def chanfreiner(self, selecteur, c, titre=None):
        try:
            self.forme = self.forme.edges(selecteur).chamfer(float(c))
        except Exception as e:
            raise ValueError(_conge_impossible(self.forme, selecteur, float(c), "chanfrein", e)) from None
        self._noter(titre or f"Chanfrein {float(c):g}", "modif", None)
        from lc3d_freecad import expr as E
        self._rec(type="chanfrein", selecteur=selecteur, r=E(c), r_val=float(c)); return self

    def chanfreiner_surplombs(self, taille=1.5, titre=None):
        """Chanfrein 45° AJOUTÉ sous les surplombs simples : chaque face plate tournée vers le bas (au-dessus du plateau)
        reçoit un congé à 45° le long de ses arêtes rentrantes (là où le mur qui la porte descend) : la matière ajoutée
        transforme le plafond en pente imprimable. Essaie taille, puis 2/3 et 40 % si OpenCascade refuse. Retourne le nombre d'arêtes."""
        import cadquery as cq
        sh = self.forme.val() if isinstance(self.forme, cq.Workplane) else self.forme
        bb = sh.BoundingBox(); zmin = bb.zmin
        aretes = []
        faces = sh.Faces()
        for F in faces:
            try:
                n = F.normalAt(); c = F.Center()
            except Exception:
                continue
            if n.z > -0.99 or c.z < zmin + 0.3: continue
            for E in F.Edges():
                for G in faces:
                    if G.isSame(F) or not any(E.isSame(x) for x in G.Edges()): continue
                    if G.Center().z < c.z - 0.05 and abs(G.normalAt().z) < 0.5:      # mur qui descend sous la face : arête rentrante
                        aretes.append(E)
        if not aretes: return 0
        for t in (taille, taille * 2 / 3, taille * 0.4):
            try:
                nouveau = sh.chamfer(float(t), None, aretes) if hasattr(sh, "chamfer") else None
                if nouveau is None or not nouveau.isValid(): continue
                self.forme = cq.Workplane("XY").add(nouveau) if isinstance(self.forme, cq.Workplane) else nouveau
                self._noter(titre or f"Chanfrein 45° sous les surplombs ({len(aretes)} arêtes, {t:g} mm)", "ajout", None)
                return len(aretes)
            except Exception:
                continue
        return 0



def _conge_impossible(forme, selecteur, r, quoi, err):
    """Message clair quand OpenCascade refuse un arrondi/chanfrein (au lieu de « StdFail_NotDone » brut)."""
    try:
        aretes = forme.edges(selecteur).vals()
        courtes = sorted(a.Length() for a in aretes)
        n, lmin = len(aretes), (courtes[0] if courtes else 0.0)
    except Exception:
        n, lmin = 0, 0.0
    if n == 0:
        return f"{quoi} R{r:g} sur « {selecteur} » : aucune arête de ce type sur la pièce."
    return (f"{quoi} R{r:g} impossible sur « {selecteur} » ({n} arêtes, la plus courte {lmin:.2f} mm). Causes habituelles : "
            f"rayon trop grand pour un côté ou un creux (garder R < moitié du plus petit côté touché), ou arêtes DÉJÀ arrondies "
            f"sélectionnées une 2e fois (un 2e arrondir(\"|Z\") reprend les lignes de raccord du 1er). Solution : un SEUL "
            f"arrondir(\"|Z\", r) à la FIN, après avoir creusé (il arrondit dehors ET dedans, mur constant), ou un rayon plus petit. "
            f"[{type(err).__name__}]")

def _mesh_b64(forme, faces_max=12000):
    m = vers_mesh(forme, tol=0.05, ang=0.25)
    if len(m.faces) > faces_max:
        try: m = m.simplify_quadric_decimation(face_count=faces_max)
        except Exception: pass
    return dict(v=_b64.b64encode(np.asarray(m.vertices, np.float32).tobytes()).decode(),
                f=_b64.b64encode(np.asarray(m.faces, np.uint32).tobytes()).decode())


def _mesh_plein_b64(forme):
    m = vers_mesh(forme, tol=0.05, ang=0.25); m.merge_vertices()
    return dict(v=_b64.b64encode(np.asarray(m.vertices, np.float32).tobytes()).decode(),
                f=_b64.b64encode(np.asarray(m.faces, np.uint32).tobytes()).decode())


def live_studio(mod, p):
    """Gestes rejouables DANS la page (éditeur en temps réel du Studio, moteur Manifold) :
    blocs / cylindres / perçages avec leurs FORMULES (p_nom), outils fixes en maillage, arrondis/chanfreins ignorés en direct.
    lents = cotes qui changent une forme fixe (filet, composant) : elles se recalculent à la validation, pas en direct."""
    import lc3d_freecad as F
    def journal(params):
        JOURNAL.clear(); mod.build(params); return [dict(g) for g in JOURNAL]
    try:
        J = journal(F.params_parametriques(p))
    except Exception as e:
        JOURNAL.clear(); return dict(ok=False, raison=f"modèle non paramétrable en direct : {str(e)[:160]}")
    pieces, signes = {}, {}
    for g in J:
        r = g.get("recette") or {}; L = pieces.setdefault(g["piece"], [])
        if r.get("type") in ("bloc", "cylindre"):
            L.append(dict(t=r["type"], op=r.get("op", "ajout"), **{k: r[k] for k in ("L", "l", "h", "d", "pos", "axe") if k in r}))
        elif r.get("type") in ("arrondi", "chanfrein"):
            L.append(dict(t="ignore", titre=g["titre"]))
        elif r.get("type") == "remplace" or g["outil"] is None:
            L.append(dict(t="fige", m=_mesh_plein_b64(g["apres"])))
        else:
            L.append(dict(t="fixe", op="coupe" if g["op"] == "coupe" else "ajout", m=_mesh_plein_b64(g["outil"])))
            try:
                o = g["outil"].val() if hasattr(g["outil"], "val") else g["outil"]; c = o.Center()
                signes[(g["piece"], len(L) - 1)] = (round(o.Volume(), 1), round(c.x, 2), round(c.y, 2), round(c.z, 2))
            except Exception: pass
    lents = []
    for k, v in p.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool): continue
        q = dict(p); q[k] = v * 1.05 + 0.5
        try: J2 = journal(q)
        except Exception: lents.append(k); continue
        idx = {}
        for g in J2:
            idx.setdefault(g["piece"], []).append(g)
        for (pc, i), sg in signes.items():
            try:
                g = idx[pc][i]; o = g["outil"].val() if hasattr(g["outil"], "val") else g["outil"]; c = o.Center()
                if (round(o.Volume(), 1), round(c.x, 2), round(c.y, 2), round(c.z, 2)) != sg: lents.append(k); break
            except Exception:
                lents.append(k); break
    JOURNAL.clear(); journal(p)          # le journal de la vraie construction pour la suite (gestes du Studio)
    return dict(ok=True, pieces=pieces, lents=sorted(set(lents)))


def gestes_pour_studio(max_gestes=14):
    """Les derniers gestes notés, prêts pour scene.json (maillages légers)."""
    out = []
    for i, g in enumerate(JOURNAL[-max_gestes:], start=max(0, len(JOURNAL) - max_gestes)):
        try:
            d = dict(n=i, piece=g["piece"], titre=g["titre"], op=g["op"], apres=_mesh_b64(g["apres"]))
            if g["outil"] is not None: d["outil"] = _mesh_b64(g["outil"], 6000)
            out.append(d)
        except Exception:
            pass
    return out, len(JOURNAL)

# ----------------------------------------------------------------------------
# Conversion vers maillage
# ----------------------------------------------------------------------------
def vers_mesh(forme, tol=0.01, ang=0.1) -> trimesh.Trimesh:
    if isinstance(forme, trimesh.Trimesh):
        return forme.copy()
    if isinstance(forme, trimesh.Scene):
        return forme.dump(concatenate=True)
    try:
        import cadquery as cq
        if isinstance(forme, cq.Workplane):
            forme = forme.val() if len(forme.vals()) == 1 else cq.Compound.makeCompound(forme.vals())
        if hasattr(forme, "wrapped") and isinstance(forme, cq.Shape):
            with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
                chemin = f.name
            cq.exporters.export(forme, chemin, tolerance=tol, angularTolerance=ang)
            m = trimesh.load(chemin, force="mesh"); os.unlink(chemin); return m
    except ImportError:
        pass
    if hasattr(forme, "export_stl") or type(forme).__module__.startswith("build123d"):
        import build123d as bd
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            chemin = f.name
        bd.export_stl(forme, chemin, tolerance=tol, angular_tolerance=ang)
        m = trimesh.load(chemin, force="mesh"); os.unlink(chemin); return m
    raise TypeError(f"Forme non reconnue : {type(forme)}")


def _manifold(m):
    import manifold3d as mf
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                               tri_verts=np.asarray(m.faces, np.uint32)))


def _de_manifold(M):
    mm = M.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)


# ----------------------------------------------------------------------------
# Résultats
# ----------------------------------------------------------------------------
OK, AVERT, ECHEC, INFO = "✅", "⚠️", "❌", "ℹ️"


def res(nom, statut, detail, valeur=None, conseil=None, lieux=None, exigence=None, mesure=None, unite=None):
    """exigence = nom de l'exigence que cette ligne MESURE (tableau « Exigences : mesuré / non mesuré » du rapport);
    mesure = "forme" (mesuré sur la géométrie) | "parametres" (évalué sur les PARAMS, pas sur la forme)."""
    d = dict(verif=nom, statut=statut, detail=detail)
    if valeur is not None: d["valeur"] = valeur
    if exigence: d["exigence"] = exigence
    if mesure: d["mesure"] = mesure
    if unite: d["unite"] = unite
    if conseil: d["conseil"] = conseil
    if lieux: d["lieux"] = lieux
    return d


def _pt(p):
    return [round(float(v), 2) for v in p]


def affiner(m, max_faces=160000):
    """Subdivise les grandes faces pour que les cartes (épaisseur, surplombs) soient localisées au mm près."""
    taille = max(0.5, math.sqrt(3.0 * float(m.area) / max_faces), float(m.extents.max()) / 150)
    for _ in range(4):
        try:
            v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=taille, max_iter=14)
            if len(f) <= max_faces * 1.6:
                return trimesh.Trimesh(v, f, process=True)
        except Exception:
            pass
        taille *= 1.5
    return m


# ----------------------------------------------------------------------------
# Vérifications d'une pièce
# ----------------------------------------------------------------------------
def _fusionner_corps(m):
    """Pièce de tiers faite de corps qui se chevauchent sans être fusionnés (STL Prusa) : union Manifold, comme le font les slicers.
    Retourne (maillage, nb de corps fusionnés)."""
    try:
        corps = m.split(only_watertight=False)
        if len(corps) < 2 or not all(c.is_watertight for c in corps): return m, 0
        M = _manifold(corps[0])
        for c in corps[1:]: M = M + _manifold(c)
        r = _de_manifold(M)
        if not len(r.faces): return m, 0
        return r, len(corps) - len(r.split(only_watertight=False))
    except Exception:
        return m, 0


def verif_integrite(m: trimesh.Trimesh, importee=False):
    out = []
    edges = m.edges_sorted
    _, cnt = np.unique(edges, axis=0, return_counts=True)
    non_manif = int((cnt > 2).sum()); bords = int((cnt == 1).sum())
    degeneres = int((m.area_faces < 1e-10).sum())
    if m.is_watertight and m.is_winding_consistent and non_manif == 0:
        out.append(res("Maillage étanche", OK, f"{len(m.faces)} faces, étanche, orientation cohérente, aucune arête à plus de 2 faces"))
    else:
        out.append(res("Maillage étanche", AVERT if importee else ECHEC,
                       f"étanche={m.is_watertight}, orientation={m.is_winding_consistent}, arêtes ouvertes={bords}, arêtes >2 faces={non_manif}"
                       + (" — fichier de tiers : à réparer (le slicer le répare en général tout seul)" if importee else ""),
                       conseil="Fusionner les corps (union) au lieu de les juxtaposer; éviter les faces qui se touchent exactement; refaire l'export."))
    if degeneres:
        out.append(res("Faces dégénérées", AVERT, f"{degeneres} faces d'aire nulle", conseil="Tolérance d'export trop fine ou géométrie qui se touche en un point/arête."))
    vol = float(m.volume) if m.is_watertight else float("nan")
    if m.is_watertight and vol <= 0:
        out.append(res("Volume", ECHEC, f"volume négatif ({vol:.1f} mm³) : normales inversées", conseil="Inverser les faces (m.invert())."))
    corps = m.split(only_watertight=False)
    if len(corps) > 1:
        out.append(res("Corps séparés", AVERT, f"{len(corps)} corps dans une seule pièce",
                       conseil="Normal si voulu (ex. plusieurs copies). Sinon un morceau ne touche pas le reste.",
                       lieux=[_pt(c.centroid) for c in corps[:8]]))
    try:
        _manifold(m)
        out.append(res("Auto-intersection", OK, "le noyau Manifold accepte la pièce (aucune auto-intersection bloquante)"))
    except Exception as e:
        out.append(res("Auto-intersection", AVERT, f"le noyau Manifold refuse le maillage : {e}", conseil="Réparer : union booléenne propre des sous-formes."))
    return out


def verif_lit(m):
    ext = m.extents; lit = MACHINE["lit"]
    if all(ext[i] <= lit[i] for i in range(3)):
        return [res("Taille sur le plateau", OK, f"{ext[0]:.1f} × {ext[1]:.1f} × {ext[2]:.1f} mm (plateau {lit[0]:.0f}³)")]
    return [res("Taille sur le plateau", ECHEC, f"{ext[0]:.1f} × {ext[1]:.1f} × {ext[2]:.1f} mm dépasse le plateau {lit}",
                conseil="Couper la pièce en morceaux avec des tenons d'alignement, ou réorienter.")]


def _rayons(m, origines, directions):
    hits, rays, faces = m.ray.intersects_location(origines, directions, multiple_hits=False)
    return hits, rays, faces


def epaisseurs_par_face(m, max_faces=400000):
    """Épaisseur locale (rayon vers l'intérieur jusqu'à la paroi opposée) et fente (rayon vers l'extérieur jusqu'à
    une paroi qui fait face). Retourne aussi le cosinus entre les deux faces : ≈ -1 = parois parallèles (vrai mur ou
    vraie fente); > -0,92 = les faces se rejoignent en angle (biseau ou coin en V : normal, pas un défaut)."""
    n = len(m.faces)
    idx = np.arange(n) if n <= max_faces else np.random.default_rng(0).choice(n, max_faces, replace=False)
    idx = idx[m.area_faces[idx] > 2e-3]          # ignore les éclats de triangles (bruit numérique)
    c = m.triangles_center[idx]; nn = m.face_normals[idx]
    eps = 1e-3
    ep = np.full(n, np.nan); fe = np.full(n, np.nan); pe = np.full(n, np.nan); pf = np.full(n, np.nan)
    for sens, cible, para in ((-1, ep, pe), (1, fe, pf)):
        h, r, f = _rayons(m, c + sens * nn * eps, sens * nn)
        if len(r):
            d = np.linalg.norm(h - c[r], axis=1)
            dot = np.einsum("ij,ij->i", m.face_normals[f], nn[r])
            opp = dot < -0.5
            cible[idx[r[opp]]] = d[opp]; para[idx[r[opp]]] = dot[opp]
    return ep, fe, pe, pf


PARALLELE = -0.92   # cos(157°) : en dessous, les deux parois sont quasi parallèles


def murs_minces_en_angle(m, seuil, n_points=60000):
    """Murs minces que les rayons perpendiculaires ratent : deux faces EN ANGLE (ex. coin intérieur carré face à un
    arrondi extérieur) avec de la matière entre elles. Paires de points à moins de `seuil` mm, normales opposées
    mais non parallèles (−0,92 < cos < −0,3), la matière étant entre les deux. Une zone dont l'épaisseur descend
    à ~0 est un biseau (deux faces qui se rejoignent en arête) : normal, ignoré.
    Retourne [dict(epaisseur, centre, aire_mm2)] des vraies zones minces."""
    from scipy.spatial import cKDTree
    try:
        pts, fid = trimesh.sample.sample_surface_even(m, n_points, seed=0)
    except TypeError:
        pts, fid = trimesh.sample.sample_surface_even(m, n_points)
    if len(pts) < 10: return []
    nn = m.face_normals[fid]; T = cKDTree(pts)
    pas = float(np.sqrt(m.area / max(len(pts), 1)))          # écart moyen entre deux points
    ep = np.full(len(pts), np.inf)
    for d0 in range(0, len(pts), 4000):               # par paquets : mémoire bornée même sur une grosse pièce
        idx = np.arange(d0, min(d0 + 4000, len(pts)))
        voisins = T.query_ball_point(pts[idx], seuil)
        I = np.repeat(idx, [len(v) for v in voisins]); J = np.fromiter((j for v in voisins for j in v), dtype=np.int64, count=len(I))
        if not len(I): continue
        garde = J > I
        I, J = I[garde], J[garde]
        dot = np.einsum("ij,ij->i", nn[I], nn[J])
        v = pts[J] - pts[I]
        entre = (np.einsum("ij,ij->i", v, nn[I]) < 0) & (np.einsum("ij,ij->i", -v, nn[J]) < 0)   # la matière est entre p et q
        g_ = (dot > PARALLELE) & (dot < -0.3) & entre
        if not g_.any(): continue
        I, J = I[g_], J[g_]; d = np.linalg.norm(pts[J] - pts[I], axis=1)
        np.minimum.at(ep, I, d); np.minimum.at(ep, J, d)
    minces = np.where(np.isfinite(ep))[0]
    # zones : points minces voisins (1 mm)
    Tm = cKDTree(pts[minces]); grp = -np.ones(len(minces), int); g = 0
    for k in range(len(minces)):
        if grp[k] >= 0: continue
        pile = [k]; grp[k] = g
        while pile:
            a = pile.pop()
            for b in Tm.query_ball_point(pts[minces[a]], 1.0):
                if grp[b] < 0: grp[b] = g; pile.append(b)
        g += 1
    aire_pt = m.area / len(pts); out = []
    for z in range(g):
        ids = minces[grp == z]; e = ep[ids]
        if len(ids) * aire_pt < 0.3: continue                                          # bruit
        if e.min() < max(0.15, 2.5 * pas):
            # sur une grande pièce l'échantillonnage est grossier : on REMESURE la zone finement avant de conclure.
            # Un biseau (deux faces qui se rejoignent en arête) descend à ~0 ; un vrai mur mince garde son épaisseur.
            fin = _epaisseur_locale(m, pts[ids], seuil, max_points=RAPIDE["points_locaux"] if RAPIDE["actif"] else 40000)
            if fin is None or fin < 0.15: continue
            emin = fin
        else:
            emin = float(e.min())
        out.append(dict(epaisseur=round(emin, 2), centre=_pt(pts[ids[np.argmin(e)]]), aire_mm2=round(len(ids) * aire_pt, 1)))
    return sorted(out, key=lambda x: x["epaisseur"])


def _epaisseur_locale(m, zone_pts, seuil, pas_fin=0.05, max_points=40000):
    """Épaisseur minimale (mêmes critères que murs_minces_en_angle) remesurée finement autour d'une zone."""
    from scipy.spatial import cKDTree
    c = m.triangles_center; r = float(np.linalg.norm(zone_pts.max(0) - zone_pts.min(0))) / 2 + seuil + 1.0
    sel = np.where(np.linalg.norm(c - zone_pts.mean(0), axis=1) < r)[0]
    if not len(sel): return None
    sub = m.submesh([sel], append=True)
    n = int(min(max_points, max(2000, sub.area / (pas_fin ** 2))))
    try:
        p, f = trimesh.sample.sample_surface_even(sub, n, seed=1)
    except TypeError:
        p, f = trimesh.sample.sample_surface_even(sub, n)
    if len(p) < 10: return None
    nn = sub.face_normals[f]; T = cKDTree(p); best = np.inf
    for d0 in range(0, len(p), 500):      # paquets de 500 points (avant 4 000 : ~10 M paires = 1 Go de mémoire sur les pièces denses)
        idx = np.arange(d0, min(d0 + 500, len(p)))
        vs = T.query_ball_point(p[idx], seuil)
        I = np.repeat(idx, [len(v) for v in vs]); J = np.fromiter((j for v in vs for j in v), dtype=np.int64, count=len(I))
        g = J > I; I, J = I[g], J[g]
        if not len(I): continue
        dot = np.einsum("ij,ij->i", nn[I], nn[J]); v = p[J] - p[I]
        ok = (dot > PARALLELE) & (dot < -0.3) & (np.einsum("ij,ij->i", v, nn[I]) < 0) & (np.einsum("ij,ij->i", -v, nn[J]) < 0)
        if ok.any(): best = min(best, float(np.linalg.norm(v[ok], axis=1).min()))
    return best if np.isfinite(best) else None


def _composantes(m, masque):
    if not masque.any(): return []
    sel = np.where(masque)[0]
    adj = m.face_adjacency
    garde = masque[adj[:, 0]] & masque[adj[:, 1]]
    import networkx as nx
    G = nx.Graph(); G.add_nodes_from(sel.tolist()); G.add_edges_from(adj[garde].tolist())
    return sorted((list(c) for c in nx.connected_components(G)), key=lambda s: -m.area_faces[s].sum())


def _grappes(m, masque, max_n=8, comps=None):
    """Regroupe les faces fautives en zones (composantes connexes) et donne leur centre."""
    comps = _composantes(m, masque) if comps is None else comps
    return [dict(centre=_pt(m.triangles_center[ids].mean(0)), aire_mm2=round(float(m.area_faces[ids].sum()), 1)) for ids in comps[:max_n]]


def verif_epaisseurs(m, piece: Piece, ep, fe, pe=None, pf=None):
    out = []
    pe = np.full(len(ep), -1.0) if pe is None else pe
    pf = np.full(len(fe), -1.0) if pf is None else pf
    mur_min = piece.mur_min if piece.mur_min is not None else (REGLES["mur_absolu"] if piece.role == "flexible" else REGLES["mur_min"])
    impose = "mur_min" in EXIGENCES_ACTIVES and piece.mur_min is None and piece.role != "flexible" and not getattr(piece, "importee", False)
    valides = ~np.isnan(ep)
    if valides.any():
        mince = valides & (ep < mur_min - 0.02)
        vrais = [ids for ids in _composantes(m, mince & (pe <= PARALLELE)) if m.area_faces[ids].sum() >= 1.0]
        biseaux = [ids for ids in _composantes(m, mince & (pe > PARALLELE)) if m.area_faces[ids].sum() >= 1.0]
        # épaisseur mesurée à la VERTICALE (plaque horizontale, membrane, rebord de 1re couche) : la limite physique est la COUCHE
        # (≥ 1 couche s'imprime : membrane sacrificielle, « oreilles de souris »), pas la largeur de ligne
        horiz = [ids for ids in vrais if float(np.abs(m.face_normals[ids, 2]).mean()) > 0.9]
        vrais = [ids for ids in vrais if float(np.abs(m.face_normals[ids, 2]).mean()) <= 0.9]
        if getattr(piece, "importee", False):   # fichier de tiers : biseau des 3 premières couches (anti « patte d'éléphant ») = voulu
            z_b = float(m.bounds[0, 2]) + 1.0 + 0.05      # chanfrein de base typique : 0,4 à 1 mm
            bas = [ids for ids in vrais if float(m.triangles_center[ids][:, 2].max()) <= z_b]
            vrais = [ids for ids in vrais if float(m.triangles_center[ids][:, 2].max()) > z_b]
            if bas:
                out.append(res("Biseau de première couche", INFO, f"{len(bas)} zone(s) minces au bas de la pièce (chanfrein anti « patte d'éléphant » du fichier) — normal",
                               lieux=_grappes(m, None, comps=bas, max_n=4)))
        if horiz:
            hmin = float(min(np.nanpercentile(ep[ids], 3) for ids in horiz)); h_c = MACHINE["couche"]
            imp = bool(getattr(piece, "importee", False))
            st = ECHEC if (hmin < 0.9 * h_c and not imp) else AVERT
            out.append(res("Épaisseur des plaques horizontales", st,
                           f"plaque/membrane horizontale de {hmin:.2f} mm (couche {h_c} mm)" + (" : plus mince qu'une couche, le slicer l'ignore" if hmin < 0.9 * h_c else
                           " : imprimable (≥ 1 couche), fragile si elle porte (membrane sacrificielle ou rebord voulu ?)"),
                           valeur=round(hmin, 2), lieux=_grappes(m, None, comps=horiz),
                           conseil="Si elle doit tenir : ≥ 3-4 couches (0,6-0,8 mm). Membrane sacrificielle au-dessus d'un trou : normal, à percer."))
        if biseaux:
            out.append(res("Arêtes en biseau", INFO, f"{len(biseaux)} bord(s) en biseau (chanfrein/congé qui finit en pointe) — normal, le slicer arrondit la pointe",
                           lieux=_grappes(m, None, comps=biseaux, max_n=5)))
        if vrais:
            tous = np.concatenate(vrais)
            emin = float(min(np.nanpercentile(ep[ids], 3) for ids in vrais))   # min robuste (ignore 3 % de valeurs aberrantes)
            # deux niveaux : LIMITE PHYSIQUE d'impression (2 lignes = 2 × buse, ❌) et RÈGLE DE CONCEPTION LC3D (1,5 mm, ⚠️ seulement)
            critique = emin < REGLES["mur_physique"]
            aire = float(m.area_faces[tous].sum())
            imp = bool(getattr(piece, "importee", False))
            if critique and imp and emin >= MACHINE["largeur_ligne"] * 0.8:
                # fichier de tiers déjà prouvé : une zone d'UNE ligne (0,34-0,78 mm avec buse 0,4) s'imprime (Arachne) ;
                # l'auteur l'a peut-être prévue pour une buse plus fine. Le tranchage réel du 3MF tranche la question.
                out.append(res("Épaisseur des murs", AVERT,
                               f"zone de {emin:.2f} mm sur {aire:.0f} mm² : une seule ligne avec la buse {MACHINE['buse']} (fragile) — "
                               f"normal si la pièce a été conçue pour une buse plus fine ou si la zone ne porte pas d'effort",
                               valeur=round(emin, 2), conseil=f"Avec une buse {round(emin / 2, 2):.2f} ou plus fine, c'est 2 lignes. Sinon : vérifier que la zone ne porte pas.",
                               lieux=_grappes(m, None, comps=vrais)))
            elif critique:
                out.append(res("Épaisseur des murs", ECHEC,
                               f"mur de {emin:.2f} mm < {REGLES['mur_physique'] + 0.02:.2f} mm (2 lignes de buse {MACHINE['buse']}) sur {aire:.0f} mm² — ça ne s'imprimera pas bien ou cassera"
                               + (f" (avec une buse {round(emin / 2, 2):.2f} ce serait imprimable)" if emin >= 0.3 else ""),
                               valeur=round(emin, 2), conseil=f"Épaissir à ≥ {2 * MACHINE['buse']:.2f} mm minimum (idéalement ≥ 1,5 mm), ou role='flexible' + calcul si c'est une lame voulue.",
                               lieux=_grappes(m, None, comps=vrais)))
            elif impose:
                out.append(res("Épaisseur des murs", ECHEC,
                               f"mur de {emin:.2f} mm < {mur_min:g} mm IMPOSÉ par la consigne (mur_min) sur {aire:.0f} mm²",
                               valeur=round(emin, 2), conseil=f"Épaissir à ≥ {mur_min:g} mm à ces endroits (ou exempter la pièce : Piece(..., mur_min=...)).",
                               lieux=_grappes(m, None, comps=vrais)))
            else:
                out.append(res("Épaisseur des murs", AVERT,
                               f"mur de {emin:.2f} mm < règle de conception {mur_min} mm sur {aire:.0f} mm² (imprimable : ≥ 2 lignes) — plus fragile que la règle",
                               valeur=round(emin, 2), conseil="OK si la zone ne porte pas d'effort; sinon épaissir à ≥ 1,5 mm, ou role='flexible' si c'est une lame voulue (et la calculer).",
                               lieux=_grappes(m, None, comps=vrais)))
        else:
            reste = ep[valides & ~mince]
            emin = float(np.nanmin(reste)) if len(reste) else float("nan")
            try:
                diag = garde("Murs en diagonale", murs_minces_en_angle, m, mur_min - 0.02, RAPIDE["points_diag"] if RAPIDE["actif"] else 60000)
            except NonVerifie as e_:
                diag = None; out.append(res_non_verifie("Épaisseur des murs en diagonale", str(e_)))
            if diag:
                e = diag[0]["epaisseur"]; critique = e < REGLES["mur_physique"]
                st = ECHEC if (critique or impose) else AVERT        # < 2 lignes de buse : ne s'imprime pas ; sinon : à regarder (bout de dent, coin)
                if getattr(piece, "importee", False) and st == ECHEC and e >= MACHINE["largeur_ligne"]:
                    st = AVERT       # fichier de tiers : mesure en diagonale approximative, ≥ 1 ligne s'imprime (Arachne) -> à regarder
                out.append(res("Épaisseur des murs", st,
                               f"mur de {e:.2f} mm en diagonale (deux faces en angle, ex. coin intérieur carré face à un arrondi extérieur) < règle {mur_min} mm",
                               valeur=e, lieux=[dict(centre=z["centre"], aire_mm2=z["aire_mm2"]) for z in diag[:5]],
                               conseil="Arrondir aussi le coin intérieur (rayon intérieur = rayon extérieur − épaisseur du mur), ou épaissir à cet endroit."))
            elif diag is not None:
                out.append(res("Épaisseur des murs", OK, f"murs ≥ {mur_min} mm partout, y compris en diagonale (min perpendiculaire {emin:.2f} mm)", valeur=round(emin, 2)))
    validf = ~np.isnan(fe)
    if validf.any():
        etroite = validf & (fe < REGLES["fente_min"] - 0.02)
        vraies = [ids for ids in _composantes(m, etroite & (pf <= PARALLELE)) if m.area_faces[ids].sum() >= 0.5]
        coins = [ids for ids in _composantes(m, etroite & (pf > PARALLELE)) if m.area_faces[ids].sum() >= 0.5]
        if coins:
            out.append(res("Coins rentrants en V", INFO, f"{len(coins)} coin(s) en V (deux faces qui se rejoignent en angle aigu) — se remplit à l'impression, normal",
                           lieux=_grappes(m, None, comps=coins, max_n=5)))
        if vraies:
            tous = np.concatenate(vraies); fmin = float(np.nanmin(fe[tous]))
            imp = bool(getattr(piece, "importee", False))
            out.append(res("Fentes et interstices", AVERT if imp else ECHEC,      # règle de conception LC3D (vécu) : sous 1,2 mm une fente se soude
                           f"fente de {fmin:.2f} mm < {REGLES['fente_min']} mm : risque de se souder à l'impression" + (" — fichier de tiers : jeu de serrage voulu ?" if imp else ""),
                           valeur=round(fmin, 2), conseil="Élargir à ≥ 1,2 mm, ou fusionner franchement les deux surfaces si elles doivent être collées (chevauchement ≥ 0,3 mm).",
                           lieux=_grappes(m, None, comps=vraies)))
        else:
            fe_ok = fe[validf & (pf <= PARALLELE)]
            fmin_ = float(np.nanmin(fe_ok)) if len(fe_ok) else None
            out.append(res("Fentes et interstices", OK, f"aucune fente interne < {REGLES['fente_min']} mm" + (f" (la plus étroite mesurée : {fmin_:.2f} mm)" if fmin_ is not None else ""),
                           valeur=None if fmin_ is None else round(fmin_, 2)))
    for r in out:      # lignes qui MESURENT une exigence (tableau « Exigences : mesuré / non mesuré »)
        if r["verif"] == "Épaisseur des murs" and "valeur" in r: r.update(exigence="mur_min", mesure="forme", unite="mm")
        if r["verif"] == "Fentes et interstices" and "valeur" in r: r.update(exigence="fente_min", mesure="forme", unite="mm")
    return out


def verif_becs_detectes(m, ep, piece, bec_min=2.0):
    """Languette / bec en porte-à-faux, détecté(e) par la FORME (sans dépendre du nom d'un paramètre) : dessous horizontal en l'air
    (rien en dessous jusqu'au plateau), plaque plus mince que bec_min, petite (≤ 25 mm de large). Règle : bec ≥ 2 mm."""
    if getattr(piece, "importee", False) or piece.role == "flexible": return []
    nz = m.face_normals[:, 2]; zc = m.triangles_center[:, 2]; zmin = m.bounds[0, 2]
    cand = (nz < -0.9) & (zc > zmin + 0.3) & ~np.isnan(ep) & (ep >= REGLES["mur_physique"]) & (ep < bec_min - 0.02)
    if not cand.any(): return []
    trouves = []
    for ids in _composantes(m, cand):
        aire = float(m.area_faces[ids].sum())
        if aire < 4.0: continue
        P = m.triangles_center[ids]; e_ = P.max(0) - P.min(0)
        if min(e_[0], e_[1]) > 25.0: continue
        o = P - [0, 0, 0.05]
        try:
            touche = m.ray.intersects_any(o, np.tile([0, 0, -1.0], (len(o), 1)))
        except Exception:
            continue
        if (~touche).mean() < 0.8: continue          # quelque chose dessous : ce n'est pas une languette libre
        trouves.append((float(np.nanpercentile(ep[ids], 3)), ids))
    if not trouves: return []
    e = min(t[0] for t in trouves)
    return [res("Bec / languette (détecté par la forme)", AVERT, f"{len(trouves)} languette(s) en porte-à-faux de {e:.2f} mm d'épais (< {bec_min} mm) : plie ou casse à l'usage (bec pour l'ongle : ≥ 2 mm)",
                valeur=round(e, 2), lieux=_grappes(m, None, comps=[i for _, i in trouves]),
                conseil="Épaissir à ≥ 2 mm, ou déclarer A.bec(piece, zone) pour la vérifier exactement.")]


def verif_surplombs(m, angle_max=None):
    angle_max = angle_max or REGLES["surplomb_max"]
    nz = m.face_normals[:, 2]
    zmin = m.bounds[0, 2]
    zc = m.triangles_center[:, 2]
    # angle par rapport à la verticale : face vers le bas avec |nz| > cos(90-angle_max)
    seuil = math.cos(math.radians(90 - angle_max - 1.0))   # 1° de tolérance : un chanfrein à 45° pile est correct
    en_l_air = zc > zmin + MACHINE["couche"] * 1.5
    surpl = (nz < -seuil) & en_l_air
    # plafonds plats (> ~86° de la verticale) : déjà jugés par l'analyse couche par couche (ponts / porte-à-faux) -> pas comptés ici
    plafond = (nz < -0.998) & en_l_air
    incline = surpl & ~plafond
    aire = float(m.area_faces[incline].sum()); aire_plat = float(m.area_faces[plafond].sum())
    if aire < 1.0:
        return [res("Surplombs", OK, f"aucun surplomb incliné > {angle_max:.0f}°" + (f" ({aire_plat:.0f} mm² de plafonds plats : voir Ponts / Porte-à-faux)" if aire_plat >= 1 else ""))], surpl
    # surplomb très couché (≥ 75° de la verticale) sur une vraie surface (≥ 4 mm dans les deux sens, ≥ 20 mm²) : ne s'imprime pas sans support
    tres = incline & (nz < -math.sin(math.radians(75.0)))
    graves = []
    if tres.any():
        for ids in _composantes(m, tres):
            if m.area_faces[ids].sum() < 20.0: continue
            P = m.triangles_center[ids][:, :2]; e_ = P.max(0) - P.min(0)
            if min(e_) >= 4.0: graves.append(ids)
    lieux = _grappes(m, incline)
    angle_vu = float(np.degrees(np.arcsin(np.clip(-nz[incline], 0, 1))).max())
    detail = f"{aire:.0f} mm² de surface inclinée à plus de {angle_max:.0f}° (jusqu'à {angle_vu:.0f}° de la verticale)" + (f"; {aire_plat:.0f} mm² de plafonds plats jugés à part (Ponts)" if aire_plat >= 1 else "")
    if graves:
        ag = float(sum(m.area_faces[ids].sum() for ids in graves))
        return [res("Surplombs", ECHEC, f"{ag:.0f} mm² de surplomb à ≥ 75° de la verticale, sans pont : ne s'imprime pas sans support — " + detail, valeur=round(aire, 1),
                    conseil="Chanfrein ≤ 45° dessous, réorienter, ou support ciblé.", lieux=_grappes(m, None, comps=graves))], surpl
    if "surplomb_max" in EXIGENCES_ACTIVES:
        return [res("Surplombs", ECHEC, f"surplomb au-delà de {angle_max:.0f}° IMPOSÉ par la consigne — " + detail, valeur=round(aire, 1),
                    conseil="Chanfrein 45° dessous (Atelier : a.chanfreiner_surplombs()), réorienter, ou trou en goutte.", lieux=lieux)], surpl
    return [res("Surplombs", AVERT, detail, valeur=round(aire, 1),
                conseil="Jusqu'à ~60° ça passe souvent avec un bon refroidissement; sinon chanfrein 45° (Atelier : a.chanfreiner_surplombs()), réorienter ou ajouter un support.",
                lieux=lieux)], surpl


def _polys_section(m, z):
    s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if s is None: return None
    try:
        p2, T = s.to_2D(to_2D=np.eye(4)) if hasattr(s, "to_2D") else s.to_planar(to_2D=np.eye(4))
    except Exception:
        p2, T = s.to_planar(to_2D=np.eye(4))
    polys = [p.buffer(0) for p in p2.polygons_full]
    if not polys: return None
    u = unary_union(polys)
    return u if not u.is_empty else None


def _appuis_disjoints(g, appui):
    """Nombre de zones d'appui séparées sur le contour d'une région non supportée (2+ = pont).
    Une région tenue sur plus de la moitié de son contour (ex. plafond d'un trou) compte comme un pont."""
    bord = g.boundary.intersection(appui)
    if bord.is_empty: return 0
    lignes = [l for l in getattr(bord, "geoms", [bord]) if l.length > 0.3]
    if not lignes: return 0
    if sum(l.length for l in lignes) > 0.5 * g.boundary.length: return 2
    u = unary_union(lignes).buffer(0.15)
    return len(u.geoms) if hasattr(u, "geoms") else 1



def _portee_pont(g, appui, pas=0.5):
    """Vraie portée d'un pont : la distance que le fil parcourt dans le vide entre deux appuis.
    Le point libre le plus loin de tout appui est au milieu du pont : portée ≈ 2 × cette distance.
    (L'ancienne mesure, le petit côté du rectangle, ratait un pont de 30 mm sur une poutre de 10 mm de large.)"""
    import shapely
    x0, y0, x1, y1 = g.bounds
    xs = np.arange(x0 + pas / 2, x1, pas); ys = np.arange(y0 + pas / 2, y1, pas)
    if not len(xs) or not len(ys): return 0.0
    X, Y = np.meshgrid(xs, ys); P = shapely.points(X.ravel(), Y.ravel())
    dedans = shapely.contains(g, P)
    if not dedans.any(): return 0.0
    d = shapely.distance(P[dedans], appui)
    return float(2 * d.max() + pas)

def analyse_couches(m, h=None, nb_max=900):
    """Tranche la pièce couche par couche (comme le slicer) : îlots flottants, porte-à-faux, ponts,
    détails trop fins en XY, contact au plateau, et estimation de temps/filament."""
    h = h or MACHINE["couche"]
    z0, z1 = m.bounds[0, 2], m.bounds[1, 2]
    n = int(math.ceil((z1 - z0) / h))
    pas = max(1, int(math.ceil(n / nb_max)))
    zs = [float(z0 + h * (i + 0.5)) for i in range(0, n, pas)]
    hh = h * pas
    couches = [(z, _polys_section(m, z)) for z in zs]
    tolere = hh * math.tan(math.radians(REGLES["surplomb_max"])) + 0.05
    lw = MACHINE["largeur_ligne"]
    flott, porte, ponts, fins = [], [], [], []
    chemin = 0.0; prec = None
    for i, (z, P) in enumerate(couches):
        if P is None:
            prec = None; continue
        comps = list(P.geoms) if isinstance(P, MultiPolygon) else [P]
        if prec is not None and i > 0:
            appui = prec.buffer(tolere)
            for c in comps:
                if c.area < REGLES["ilot_aire_min"]: continue
                if c.intersection(prec).area < 0.02 * c.area:
                    # vide d'UNE seule couche sous l'îlot (couche sacrificielle au-dessus d'un trou/écrou, astuce Prusa) : appuyé en pratique
                    dessous2 = couches[i - 2][1] if (pas == 1 and i >= 2) else None
                    sacrif = dessous2 is not None and c.intersection(dessous2).area >= 0.5 * c.area
                    flott.append(dict(z=round(z, 2), centre=_pt(c.centroid.coords[0]), aire_mm2=round(c.area, 2), sacrificielle=bool(sacrif)))
                    continue
                libre = c.difference(appui)
                if libre.area > 0.3:
                    for g in (libre.geoms if hasattr(libre, "geoms") else [libre]):
                        if g.area < 0.3: continue
                        morceaux = _appuis_disjoints(g, prec.buffer(tolere + 0.05))
                        rr = g.minimum_rotated_rectangle
                        xs, ys = rr.exterior.coords.xy
                        cotes = sorted({round(math.dist((xs[k], ys[k]), (xs[k + 1], ys[k + 1])), 2) for k in range(4)})
                        portee = _portee_pont(g, appui) if morceaux >= 2 else (cotes[0] if cotes else 0)
                        e = dict(z=round(z, 2), centre=_pt(g.centroid.coords[0]), aire_mm2=round(g.area, 1), portee_mm=round(portee, 1))
                        (ponts if morceaux >= 2 else porte).append(e)
        for c in comps:  # détails trop fins en XY : < 1 ligne (le slicer les saute) ou < 2 lignes (fragiles)
            perdu_tout = c.difference(c.buffer(-lw).buffer(lw + 0.01))
            if perdu_tout.area > 0.4:
                critique_tout = c.difference(c.buffer(-lw / 2).buffer(lw / 2 + 0.01))
                # chaque zone mince séparément (ex. 40 pointes de dents de 0,02 mm² chacune ≠ un vrai détail fragile)
                for perdu in (perdu_tout.geoms if hasattr(perdu_tout, "geoms") else [perdu_tout]):
                    if perdu.area <= 0.4: continue
                    critique = critique_tout.intersection(perdu.buffer(0.05))
                    fins.append(dict(z=round(z, 2), centre=_pt(perdu.centroid.coords[0]), aire_mm2=round(perdu.area, 2),
                                     sous_1_ligne=bool(critique.area > 0.4), _i=i, _g=perdu))
        # chemin d'extrusion approximatif
        per = P.boundary.length
        chemin += per * MACHINE["parois"]
        dedans = P.buffer(-MACHINE["parois"] * lw)
        if not dedans.is_empty:
            pleine = i < MACHINE["couches_pleines"] or i >= len(couches) - MACHINE["couches_pleines"]
            if not pleine:
                autour = [couches[k][1] for k in (i - MACHINE["couches_pleines"], i + MACHINE["couches_pleines"]) if 0 <= k < len(couches)]
                expose = dedans
                for a in autour:
                    expose = expose.difference(a) if a is not None else expose
                    if a is None: break
                plein = expose.area if not expose.is_empty else 0
            else:
                plein = dedans.area
            chemin += (plein + (dedans.area - plein) * MACHINE["remplissage"]) / lw
        prec = P
    # crête qui s'affine (ex. arête en toit, lèvre) : 1 mm plus bas, la même zone est pleine et épaisse -> normal
    cretes, vrais_fins = [], []
    dk = max(1, int(round(1.0 / hh)))
    for f in fins:
        j = f["_i"] - dk; g = f.pop("_g"); f.pop("_i")
        dessous = couches[j][1] if j >= 0 else None
        ok_dessous = False
        if dessous is not None and dessous.buffer(0.08).contains(g):
            perdu_dessous = dessous.difference(dessous.buffer(-lw).buffer(lw + 0.01))
            ok_dessous = perdu_dessous.intersection(g.buffer(0.05)).area < 0.2 * g.area
        (cretes if ok_dessous else vrais_fins).append(f)
    fins = vrais_fins
    base = couches[0][1] if couches and couches[0][1] is not None else None
    contact = base.area if base is not None else 0.0
    vol_extrude = chemin * pas * lw * h
    temps_min = (chemin * pas / 110.0 + len(zs) * pas * 0.6) / 60.0
    return dict(flottants=flott, porte_a_faux=porte, ponts=ponts, fins=fins, cretes=cretes, contact_plateau_mm2=round(contact, 1),
                hauteur=round(z1 - z0, 2), nb_couches=n, temps_min=round(temps_min, 0), volume_extrude_mm3=round(vol_extrude, 0))


def verif_couches(m, piece: Piece, A):
    out = []
    imp = bool(getattr(piece, "importee", False))
    vrais_fl = [f for f in A["flottants"] if not f.get("sacrificielle")]
    sacr = [f for f in A["flottants"] if f.get("sacrificielle")]
    if vrais_fl:
        out.append(res("Régions flottantes (couche par couche)", ECHEC,
                       f"{len(vrais_fl)} îlot(s) qui commencent dans le vide (1er à z={vrais_fl[0]['z']} mm)",
                       conseil="Relier l'îlot au reste par le bas (chanfrein 45°, cône), réorienter, ou prévoir un support.",
                       lieux=vrais_fl[:8]))
    if sacr:
        out.append(res("Couche sacrificielle", AVERT, f"{len(sacr)} îlot(s) au-dessus d'un vide d'UNE seule couche (1er à z={sacr[0]['z']} mm) : "
                       "pont posé presque sur la couche d'en dessous (astuce voulue au-dessus des trous/écrous) — s'imprime, à percer après si besoin",
                       lieux=sacr[:8]))
    if not A["flottants"]:
        out.append(res("Régions flottantes (couche par couche)", OK, f"{A['nb_couches']} couches vérifiées, aucun îlot dans le vide"))
    gros = [p for p in A["porte_a_faux"] if p["aire_mm2"] > 2]
    if gros:
        out.append(res("Porte-à-faux sans appui", AVERT, f"{len(gros)} zone(s) en porte-à-faux (> 45°, tenues d'un seul côté)",
                       conseil="Chanfrein 45° dessous (pièce faite avec l'Atelier : a.chanfreiner_surplombs() le fait tout seul), réorienter, ou support ciblé.", lieux=sorted(gros, key=lambda e: -e["aire_mm2"])[:8]))
    else:
        out.append(res("Porte-à-faux sans appui", OK, "aucun porte-à-faux significatif"))
    longs = [p for p in A["ponts"] if p["portee_mm"] > REGLES["pont_max"]]
    # pièce de tiers : 12 mm est la règle PRUDENTE de LC3D (⚠️) ; la limite physique d'un pont refroidi est ~50 mm (❌ au-delà).
    # Pièce conçue par LC3D : la règle documentée (≤ 12 mm) reste ❌.
    tres_longs = [p for p in longs if p["portee_mm"] > REGLES["pont_max_importe"]]
    if longs and imp and not tres_longs:
        out.append(res("Ponts", AVERT, f"{len(longs)} pont(s) de plus de {REGLES['pont_max']} mm (max {max(p['portee_mm'] for p in longs)} mm) — fichier de tiers : "
                       f"imprimable avec un bon refroidissement (≤ {REGLES['pont_max_importe']:.0f} mm), le dessous peut pendre un peu",
                       conseil="Ventilation à fond sur les ponts; sinon support.", lieux=longs[:8]))
    elif longs:
        out.append(res("Ponts", ECHEC, f"{len(longs)} pont(s) de plus de {REGLES['pont_max']} mm (max {max(p['portee_mm'] for p in longs)} mm) : le dessous va pendre",
                       conseil="Réduire la portée, ajouter un pilier, ou mettre la forme en arche/ogive.", lieux=longs[:8]))
    elif A["ponts"]:
        out.append(res("Ponts", OK, f"{len(A['ponts'])} pont(s), portée max {max(p['portee_mm'] for p in A['ponts'])} mm ≤ {REGLES['pont_max']} mm"))
    if A.get("cretes"):
        out.append(res("Crêtes qui s'affinent", INFO, f"{len(A['cretes'])} couche(s) où une arête de toit/lèvre devient plus fine que la buse — la pointe sera légèrement arrondie, normal",
                       lieux=A["cretes"][:4]))
    crit = [f for f in A["fins"] if f.get("sous_1_ligne")]
    if imp:     # fichier de tiers : bords en biseau des 3 premières couches (chanfrein anti « patte d'éléphant ») = voulu
        z_b = A.get("z_bas", 0.0) + 3 * MACHINE["couche"] + 0.05
        crit = [f for f in crit if f["z"] > z_b]
    fragiles = [f for f in A["fins"] if not f.get("sous_1_ligne")]
    if crit:
        out.append(res("Détails plus fins que la buse", ECHEC,
                       f"{len(crit)} zone(s) plus minces qu'une ligne ({MACHINE['largeur_ligne']} mm) en XY : le slicer va les sauter",
                       conseil="Grossir le détail à ≥ 0,84 mm (2 lignes).", lieux=crit[:8]))
    if fragiles:
        conçue = not imp and piece.role != "flexible" and (piece.mur_min is None or piece.mur_min >= 2 * MACHINE["largeur_ligne"])
        out.append(res("Détails sous 2 lignes", ECHEC if conçue else AVERT,      # pièce CONÇUE : < 2 lignes = ❌ (fichier de tiers / lame voulue : ⚠️)
                       f"{len(fragiles)} zone(s) entre 1 et 2 lignes (< 0,84 mm) en XY : une seule ligne de plastique, fragile",
                       conseil="Grossir à ≥ 0,84 mm, ou role='flexible' + calcul si c'est voulu.", lieux=fragiles[:8]))
    if not A["fins"]:
        out.append(res("Détails plus fins que la buse (coupes horizontales)", OK, f"aucun détail sous 2 lignes ({2 * MACHINE['largeur_ligne']:.2f} mm) dans les coupes XY couche par couche — "
                       "la minceur VERTICALE (sommet de dent, crête) est mesurée à part : « Détails fins en 3D »"))
    ratio = A["hauteur"] / max(math.sqrt(A["contact_plateau_mm2"]), 1)
    if (A["contact_plateau_mm2"] < 50 or ratio > 4) and besoin_bordure(m):
        out.append(res("Stabilité / adhérence", INFO, f"contact plateau {A['contact_plateau_mm2']:.0f} mm², hauteur/base ≈ {ratio:.1f} — corrigé : "
                       "bordure (brim) mise d'office dans le 3MF livré"))
    elif A["contact_plateau_mm2"] < 50 or ratio > 4:
        out.append(res("Stabilité / adhérence", AVERT, f"contact plateau {A['contact_plateau_mm2']:.0f} mm², hauteur/base ≈ {ratio:.1f}",
                       conseil="Ajouter une bordure (brim) ou coucher la pièce."))
    else:
        out.append(res("Stabilité / adhérence", OK, f"contact plateau {A['contact_plateau_mm2']:.0f} mm², hauteur/base ≈ {ratio:.1f}"))
    return out



def _corde(m, q, t):
    """Longueur de matière traversée par la droite (q, ±t) : distance à la sortie dans les deux sens (inf si on ne sort pas)."""
    tot = np.zeros(len(q))
    for s_ in (1.0, -1.0):
        d = np.full(len(q), np.inf)
        if len(q):
            loc, ri, fi = m.ray.intersects_location(q, s_ * t, multiple_hits=False)
            if len(ri):
                sortie = np.einsum("ij,ij->i", m.face_normals[fi], s_ * t[ri]) > 0      # on SORT de la matière (sinon q était dehors)
                d[ri[sortie]] = np.linalg.norm(loc[sortie] - q[ri[sortie]], axis=1)
        tot += d
    return tot


def cretes_minces_3d(m, seuil=None, delta=None, n_points=None, k_dir=6, d_max=4.0, saut=1.5):
    """ÉPAISSEUR DES DÉTAILS EN 3D (sommets de dent, crêtes, nervures, lettres en relief) — ce que les coupes horizontales ratent
    quand la minceur est VERTICALE (ex. sommet de filet de 0,2 mm de haut : en coupe XY c'est un anneau de 1,2 mm).
    Méthode : pour chaque point de surface p (normale n), on descend de `delta` (½ ligne) sous la surface et on mesure la
    LARGEUR de matière dans le plan tangent (corde la plus courte sur k_dir directions). Largeur < seuil = détail mince.
    Pour ne pas confondre avec un simple coin de corps (arête chanfreinée d'une boîte), on continue de descendre :
    une vraie crête a un PIED (la largeur saute de > `saut` mm d'un coup avant d_max mm) ; un coin de corps s'élargit sans saut.
    Retourne dict(zones=[dict(largeur, largeur_surface, hauteur, centre, aire_mm2)], n_points, ecartes)."""
    lw = MACHINE["largeur_ligne"]
    seuil = 2 * lw if seuil is None else seuil
    delta = lw / 2 if delta is None else delta
    if n_points is None:
        n_points = int(min(RAPIDE["points_diag"] if RAPIDE["actif"] else 60000, max(20000, m.area / 0.25)))
    try:
        pts, fid = trimesh.sample.sample_surface_even(m, n_points, seed=0)
    except TypeError:
        pts, fid = trimesh.sample.sample_surface_even(m, n_points)
    if len(pts) < 10: return dict(zones=[], n_points=len(pts), ecartes=0)
    nn = m.face_normals[fid]
    a = np.where(np.abs(nn[:, 0:1]) < 0.9, np.array([[1.0, 0, 0]]), np.array([[0, 1.0, 0]]))
    u = np.cross(nn, a); u /= np.linalg.norm(u, axis=1)[:, None]; v = np.cross(nn, u)
    q = pts - nn * delta
    best = np.full(len(pts), np.inf); bt = np.zeros_like(pts)
    for k in range(k_dir):
        th = math.pi * k / k_dir
        t = math.cos(th) * u + math.sin(th) * v
        w = _corde(m, q, t)
        b = w < best; best[b] = w[b]; bt[b] = t[b]
    cand = np.where(best < seuil)[0]
    if not len(cand): return dict(zones=[], n_points=len(pts), ecartes=0)
    garde_ = np.zeros(len(cand), bool); haut = np.full(len(cand), np.nan)
    prev = best[cand].copy(); vivant = np.ones(len(cand), bool)
    for d in np.arange(delta + 0.2, d_max + 1e-9, 0.2):
        w = _corde(m, pts[cand] - nn[cand] * d, bt[cand])
        s_ = vivant & np.isfinite(w) & (w - prev > saut)
        garde_ |= s_; haut[s_ & np.isnan(haut)] = d
        vivant &= ~s_ & np.isfinite(w)
        prev = np.where(np.isfinite(w), w, prev)
    ids = cand[garde_]; H = haut[garde_]
    if not len(ids): return dict(zones=[], n_points=len(pts), ecartes=int(len(cand)))
    w0 = _corde(m, pts[ids] - nn[ids] * min(0.05, delta), bt[ids])         # largeur juste sous la surface (comme une coupe du juge)
    # zones : points voisins (1 mm)
    from scipy.spatial import cKDTree
    T = cKDTree(pts[ids]); grp = -np.ones(len(ids), int); g = 0
    for k in range(len(ids)):
        if grp[k] >= 0: continue
        pile = [k]; grp[k] = g
        while pile:
            a_ = pile.pop()
            for b_ in T.query_ball_point(pts[ids[a_]], 1.0):
                if grp[b_] < 0: grp[b_] = g; pile.append(b_)
        g += 1
    aire_pt = m.area / len(pts); zones = []
    for z in range(g):
        sel = np.where(grp == z)[0]
        if len(sel) * aire_pt < 0.05: continue                                   # un point isolé : bruit
        j = sel[np.argmin(best[ids[sel]])]
        w0s = w0[sel][np.isfinite(w0[sel])]
        zones.append(dict(largeur=round(float(np.percentile(best[ids[sel]], 10)), 2), largeur_min=round(float(best[ids[sel]].min()), 2),
                          largeur_surface=round(float(np.percentile(w0s, 10)), 2) if len(w0s) else None,
                          hauteur=round(float(np.nanmedian(H[sel])), 1), centre=_pt(pts[ids[j]]), aire_mm2=round(len(sel) * aire_pt, 1),
                          _pts=pts[ids[sel]]))
    return dict(zones=sorted(zones, key=lambda x: x["largeur"]), n_points=len(pts), ecartes=int(len(cand) - len(ids)))


def _dans_boites(pts, boites):
    if boites is True: return np.ones(len(pts), bool)
    ok = np.zeros(len(pts), bool)
    for b0, b1 in (boites or []):
        b0 = np.minimum(b0, b1); b1 = np.maximum(b0, b1)
        ok |= np.all((pts >= np.asarray(b0) - 1e-6) & (pts <= np.asarray(b1) + 1e-6), axis=1)
    return ok


def verif_details_3d(m_modele, piece: Piece):
    """Détails fins mesurés EN 3D (voir cretes_minces_3d) sur la pièce dans le repère du MODÈLE.
    Pièce conçue : ❌ sous 2 lignes; crête voulue déclarée (Piece(cretes_voulues=...)) ou fichier de tiers : ⚠️."""
    if piece.role in ("flexible", "achetee"): return []
    e = EXIGENCES_ACTIVES.get("detail_min") or {}
    seuil = e.get("mini") or 2 * MACHINE["largeur_ligne"]
    R = cretes_minces_3d(m_modele, seuil=seuil)
    titre = "Détails fins en 3D (crêtes, sommets de dent, nervures)"
    meth = f"largeur de matière mesurée en 3D à {MACHINE['largeur_ligne'] / 2:.2f} mm sous la surface, {R['n_points']} points"
    if not R["zones"]:
        return [res(titre, OK, f"aucune crête ni sommet plus étroit que {seuil:.2f} mm ({meth})" + (f"; {R['ecartes']} point(s) d'arête de corps (coin chanfreiné/arrondi) écartés" if R["ecartes"] else ""),
                    exigence="detail_min", mesure="forme", unite="mm")]
    imp = bool(getattr(piece, "importee", False))
    voulues = [z for z in R["zones"] if piece.cretes_voulues and _dans_boites(z["_pts"], piece.cretes_voulues).mean() > 0.5]
    autres = [z for z in R["zones"] if z not in voulues]
    for z in R["zones"]: z.pop("_pts", None)
    out = []
    def txt(zs):
        z = zs[0]
        return (f"{len(zs)} zone(s) ; la plus mince : {z['largeur']:.2f} mm de large à {MACHINE['largeur_ligne'] / 2:.2f} mm sous la surface"
                + (f" ({z['largeur_surface']:.2f} mm juste sous le sommet)" if z.get("largeur_surface") is not None else "")
                + f", haute de ~{z['hauteur']:g} mm, sur {sum(x['aire_mm2'] for x in zs):.0f} mm² (repère du modèle, {meth})")
    dents = len(autres) >= 8 and float(np.median([z["aire_mm2"] for z in autres])) <= 0.6 and max(z["aire_mm2"] for z in autres) <= 2.0   # sommets de dents répétés (engrenage, crantage) : pointes arrondies à l'impression
    if autres and dents:
        out.append(res(titre + " — sommets de dents", AVERT, txt(autres) + f" < {seuil:.2f} mm : {len(autres)} petites pointes répétées (sommets de dents) — elles sortiront arrondies, l'engrènement est vérifié à part",
                       valeur=autres[0]["largeur"], lieux=[{k: v for k, v in z.items()} for z in autres[:6]], exigence="detail_min", mesure="forme", unite="mm"))
        autres = []
    if autres:
        st = AVERT if imp else ECHEC
        out.append(res(titre, st, txt(autres) + f" < {seuil:.2f} mm ({seuil / MACHINE['largeur_ligne']:.0f} lignes)" + (" — fichier de tiers" if imp else ""),
                       valeur=autres[0]["largeur"], lieux=[{k: v for k, v in z.items()} for z in autres[:6]], exigence="detail_min", mesure="forme", unite="mm",
                       conseil="Élargir le sommet (plat de crête ≥ 0,9 mm, ex. filet : t ≥ 0,9) ou déclarer Piece(cretes_voulues=...) si c'est voulu (bout de filet en biseau, arête décorative) et l'écrire dans le rapport."))
    if voulues:
        out.append(res(titre + " — crêtes voulues déclarées", AVERT, txt(voulues) + f" < {seuil:.2f} mm, déclaré voulu (Piece.cretes_voulues) : à écrire tel quel dans le rapport",
                       valeur=voulues[0]["largeur"], lieux=voulues[:6], exigence="detail_min", mesure="forme", unite="mm"))
    return out


def verif_flexion(axe, role="rigide"):
    if axe is None:
        return [res("Orientation des lames", AVERT, "pièce flexible sans axe_flexion déclaré : impossible de vérifier que les lames sont à plat",
                    conseil="Déclarer axe_flexion=(x, y, z) (axe long des lames dans le modèle).")] if role == "flexible" else []
    a = np.asarray(axe, float); a /= np.linalg.norm(a)
    ang = math.degrees(math.asin(min(1.0, abs(a[2]))))
    if ang <= 15:
        return [res("Orientation des lames", OK, f"axe des lames à {ang:.0f}° du plateau (dans le plan des couches)")]
    return [res("Orientation des lames", ECHEC, f"axe des lames à {ang:.0f}° du plateau : elles plient à travers les couches et cassent ~2× plus vite",
                conseil="Coucher la pièce pour que les lames soient à plat sur le plateau.")]


def choisir_orientation(m, angle_max=45.0, axe_flexion=None):
    """Teste 6 orientations à plat. Priorité : lames dans le plan des couches (si axe_flexion), puis le moins de
    surface à supporter, puis la plus grande base à plat, puis la plus basse hauteur."""
    cands = [("telle", np.eye(4))]
    R = trimesh.transformations.rotation_matrix
    for nom, M in [("sur le dos", R(math.pi, [1, 0, 0])), ("sur la face avant", R(math.pi / 2, [1, 0, 0])),
                   ("sur la face arrière", R(-math.pi / 2, [1, 0, 0])), ("sur le côté droit", R(math.pi / 2, [0, 1, 0])),
                   ("sur le côté gauche", R(-math.pi / 2, [0, 1, 0]))]:
        cands.append((nom, M))
    seuil = math.cos(math.radians(90 - angle_max))
    meilleurs = []
    for nom, M in cands:
        mm = m.copy(); mm.apply_transform(M)
        nz = mm.face_normals[:, 2]; zc = mm.triangles_center[:, 2]; zmin = mm.bounds[0, 2]
        sup = float(mm.area_faces[(nz < -seuil) & (zc > zmin + 0.3)].sum())
        base = float(mm.area_faces[(nz < -0.999) & (zc < zmin + 0.05)].sum())
        flex_ok = True
        if axe_flexion is not None:
            a = (M[:3, :3] @ np.asarray(axe_flexion, float)); a /= np.linalg.norm(a)
            flex_ok = abs(a[2]) <= math.sin(math.radians(15))
        elance = float(mm.extents[2]) / max(1e-6, float(min(mm.extents[0], mm.extents[1])))
        meilleurs.append(dict(nom=nom, M=M, support=sup, hauteur=float(mm.extents[2]), base=base, flex_ok=flex_ok, elance=elance))
    # debout sur la tranche (hauteur > 3 × le petit côté de la base) : la pièce oscille, se décolle, et le TPU plie sous la buse
    # élancement 3-6 : debout reste bon AVEC la bordure automatique (elle est mise d'office > 2,5) — on ne couche la pièce
    # que si ça n'ajoute pas de surface à supporter (un tube fileté couché = filets dans le vide). > 6 : trop instable, on couche.
    meilleurs.sort(key=lambda d: (not d["flex_ok"], d["elance"] > 6.0, round(d["support"], -1), d["elance"] > 3.0, -round(d["base"], -1), d["hauteur"]))
    return meilleurs


def poser_sur_plateau(m):
    m = m.copy()
    m.apply_translation([-m.bounds[0, 0] - m.extents[0] / 2, -m.bounds[0, 1] - m.extents[1] / 2, -m.bounds[0, 2]])
    return m


# ----------------------------------------------------------------------------
# Assemblage : collisions, jeux, chemin de montage, états
# ----------------------------------------------------------------------------
def _vol_inter(a, b):
    try:
        I = _manifold(a) ^ _manifold(b)
        return float(I.volume()), I
    except Exception:
        return float("nan"), None


def _penetration(a, b, n=3000):
    """Profondeur max de A dans B (mm), par échantillonnage de la surface de A."""
    pts, _ = trimesh.sample.sample_surface(a, n, seed=1)
    pts = np.vstack([pts, a.vertices])
    dedans = b.contains(pts)
    if not dedans.any(): return 0.0
    _, d, _ = trimesh.proximity.closest_point(b, pts[dedans])
    return float(d.max())


def _distance_min(a, b, n=6000):
    pa, _ = trimesh.sample.sample_surface(a, n, seed=2)
    pa = np.vstack([pa, a.vertices])
    _, d, _ = trimesh.proximity.closest_point(b, pa)
    i = int(np.argmin(d))
    return float(d[i]), _pt(pa[i])


def _pose(M):
    return np.asarray(M, float) if not isinstance(M, (tuple, list)) or len(M) != 3 else trimesh.transformations.translation_matrix(M)


def _collision(a, b):
    """(volume en commun mm³, profondeur mm) — profondeur seulement s'il y a collision."""
    v, _ = _vol_inter(a, b)
    return v, (max(_penetration(a, b), _penetration(b, a)) if v > 0.01 else 0.0)


def _inserer_une(s, base, Mf, presentes, clips, serrages):
    """Simule l'arrivée d'UNE pièce sur son chemin de montage. Fonction pure (tourne sous garde-fou)."""
    premier = None; pire = 0.0; pire_par = {}; max_coll = (0.0, 0); bloc = None
    n_pas = s["pas"]
    if RAPIDE["actif"]:          # pas grossier : au plus RAPIDE["pas_montage_mm"] mm (ou 6°) par pas
        L_ = float(np.linalg.norm(s["depuis"])) if s["type"] == "translation" else abs(s["angle"]) / 6.0 * RAPIDE["pas_montage_mm"]
        n_pas = min(n_pas, max(4, int(math.ceil(L_ / RAPIDE["pas_montage_mm"]))))
    for k in range(n_pas + 1):
        t = 1 - k / n_pas
        if s["type"] == "translation":
            Mk = trimesh.transformations.translation_matrix(np.asarray(s["depuis"]) * t) @ Mf
        else:
            Mk = trimesh.transformations.rotation_matrix(math.radians(s["angle"] * t), s["axe"], s["pivot"]) @ Mf
        mk = base.copy(); mk.apply_transform(Mk)
        for autre, mo in presentes.items():
            if not (mk.bounds[0] <= mo.bounds[1] + 0.01).all() or not (mo.bounds[0] <= mk.bounds[1] + 0.01).all():
                continue
            v, I = _vol_inter(mk, mo)
            if v > 0.01:
                p = max(_penetration(mk, mo), _penetration(mo, mk))
                cle_ = frozenset((s["piece"], autre))
                voulu = cle_ in clips or cle_ in serrages
                pire = max(pire, p)
                if cle_ in clips: pire_par[autre] = max(pire_par.get(autre, 0.0), p)
                if not voulu and v > max_coll[0]: max_coll = (v, round((1 - t) * 100))
                tol_ = clips.get(cle_, 0) + 0.3 if cle_ in clips else (serrages[cle_]["i"] + 0.05 if cle_ in serrages else 0)
                if premier is None and (not voulu or p > tol_):
                    Im = _de_manifold(I) if I is not None else None
                    lieu = _pt(Im.centroid) if Im is not None and len(Im.faces) else None
                    premier = (round((1 - t) * 100), autre, v, p, lieu)
                    bloc = (t, Im)
    return premier, pire, pire_par, max_coll, bloc


def verif_assemblage(meshes: dict, A: Assemblage):
    out = []; en_place = {}
    for nom, m in meshes.items():
        mm = m.copy(); mm.apply_transform(A.poses.get(nom, np.eye(4))); en_place[nom] = mm
    tous = list(en_place.values())
    ensemble = trimesh.util.concatenate(tous)
    e = ensemble.extents
    out.append(res("Taille totale du produit", INFO, f"{e[0]:.1f} × {e[1]:.1f} × {e[2]:.1f} mm assemblé"))
    clips = {frozenset((a, b)): acc for a, b, acc in A.clips}
    serrages = {frozenset((d["a"], d["b"])): d for d in getattr(A, "serrages", [])}
    noms = list(en_place)
    # 1) position finale
    for i in range(len(noms)):
        for j in range(i + 1, len(noms)):
            a, b = noms[i], noms[j]
            if not (en_place[a].bounds[0] <= en_place[b].bounds[1] + 0.01).all() or not (en_place[b].bounds[0] <= en_place[a].bounds[1] + 0.01).all():
                continue
            try:
                v, p = garde(f"Collision {a} / {b}", _collision, en_place[a], en_place[b])
            except NonVerifie as e_:
                out.append(res_non_verifie(f"Position finale {a} / {b}", str(e_))); continue
            if v > 0.01:
                if any({x["a"], x["b"]} == {a, b} and x["mini"] < 0 for x in getattr(A, "ajustements", [])):
                    out.append(res(f"Position finale {a} / {b}", INFO, f"interférence voulue (ajustement pressé) : {v:.2f} mm³, profondeur {p:.2f} mm — vérifiée par « Ajustement »"))
                elif frozenset((a, b)) in serrages:
                    d_ = serrages[frozenset((a, b))]
                    ok_ = p <= d_["i"] + 0.05
                    out.append(res(f"Serrage {a} / {b}", OK if ok_ else ECHEC, f"ajustement serré voulu : interférence mesurée {p:.2f} mm (déclarée {d_['i']:.2f} mm), {v:.2f} mm³",
                                   valeur=round(p, 3), conseil=None if ok_ else f"L'interférence réelle dépasse la déclarée de {p - d_['i']:.2f} mm : réduire la cote, ou déclarer la vraie valeur."))
                    d_["mesure"] = p; d_["volume"] = v
                elif frozenset((a, b)) in clips:
                    out.append(_clip_ferme(A, a, b, p, v, "position finale montée"))
                else:
                    out.append(res(f"Position finale {a} / {b}", ECHEC, f"collision : {v:.2f} mm³, profondeur {p:.2f} mm",
                                   conseil="Retirer de la matière ou décaler; vérifier la cote qui chevauche."))
    if not any(r["verif"].startswith("Position finale") and r["statut"] == ECHEC for r in out):
        out.append(res("Position finale", OK, "aucune collision non voulue entre les pièces assemblées"))
    for k_, d_ in serrages.items():
        if "mesure" not in d_:
            out.append(res(f"Serrage {d_['a']} / {d_['b']}", AVERT, f"serrage de {d_['i']:.2f} mm déclaré, mais les deux pièces ne se chevauchent pas : c'est un jeu, pas un serrage",
                           conseil="Vérifier les cotes (diamètre de l'arbre / du trou) ou retirer A.serrage(...)."))
        else:      # force d'emmanchement (Lamé, moyeu épais, arbre plastique de Ø estimé par la boîte de la plus petite pièce)
            try:
                pa, pb = en_place[d_["a"]], en_place[d_["b"]]
                pt = pa if np.prod(pa.extents) < np.prod(pb.extents) else pb
                e_ = sorted(pt.extents); D_ = e_[1]
                mats_ = getattr(A, "_materiaux", {})
                mat_ = next((mats_.get(x) for x in (d_["a"], d_["b"]) if mats_.get(x) and mats_.get(x) not in ("acier", "aluminium", "laiton", "neodyme")), "PETG")
                M_ = proprietes_materiau(mat_); dlt = 2 * d_["mesure"]
                pression = M_["E"] * dlt / (2 * D_)          # MPa (moyeu épais, même matériau : p ≈ E·δ/(2d))
                Lc = d_.get("volume", 0) / (math.pi * D_ * max(d_["mesure"], 1e-3))       # longueur de contact = volume en commun / (π·d·interférence)
                F_ = pression * math.pi * D_ * Lc * M_["mu"]
                st_ = OK if (d_["force_max_N"] is None or F_ <= d_["force_max_N"]) else AVERT
                out.append(res(f"Serrage {d_['a']} / {d_['b']} : force d'emmanchement", INFO if st_ == OK else AVERT,
                               f"≈ {F_:.0f} N (≈ {F_ / 9.81:.1f} kg) au plus — borne haute élastique (le plastique imprimé s'écrase et flue : souvent 3 à 10× moins), "
                               f"Ø ≈ {D_:.1f} mm, contact ≈ {Lc:.1f} mm, pression ≈ {pression:.1f} MPa ({mat_})",
                               conseil=None if st_ == OK else "Trop dur à emmancher à la main : réduire l'interférence."))
            except Exception:
                pass
    # 2) jeux des pièces mobiles
    for a, b, jmin in A.jeux:
        # pièce POSÉE sur l'autre (assise déclarée) : la face d'appui touche exprès → on mesure le jeu des CÔTÉS
        # en soulevant la pièce posée de (jeu + 0,1) mm : les murs verticaux gardent exactement leur jeu, l'appui est exclu
        posee = next((s for s in getattr(A, "assises", []) if {s["a"], s["b"]} == {a, b}), None)
        ma, mb = en_place[a], en_place[b]; note = ""
        if posee:
            haut = posee["a"]; lev = trimesh.transformations.translation_matrix((0, 0, jmin + 0.1))
            if haut == a: ma = ma.copy(); ma.apply_transform(lev)
            else: mb = mb.copy(); mb.apply_transform(lev)
            note = f" — jeu des côtés (appui de {posee['a']} sur {posee['b']} vérifié à part)"
        try:
            d, ou = garde(f"Jeu {a} ↔ {b}", _distance_min, ma, mb)
        except NonVerifie as e_:
            out.append(res_non_verifie(f"Jeu {a} ↔ {b}", str(e_))); continue
        st = OK if d >= jmin - 0.02 else ECHEC
        jmax = getattr(A, "jeux_max", {}).get(frozenset((a, b)))
        if jmax is None and "jeu" in EXIGENCES_ACTIVES: jmax = EXIGENCES_ACTIVES["jeu"]["maxi"]
        trop = jmax is not None and d > jmax + 0.02
        if trop: st = ECHEC
        jug = juger_exigence("jeu", d)
        if jug and jug[0] == AVERT and st == OK: st = AVERT; note += " — " + jug[1]
        out.append(res(f"Jeu {a} ↔ {b}", st, f"jeu min {d:.2f} mm mesuré ({'consigne' if 'jeu' in EXIGENCES_ACTIVES else 'règle'} {jmin}" + (f" à {jmax}" if jmax is not None else "") + f" mm){note}", valeur=round(d, 2), lieux=[ou] if st != OK else None,
                       conseil=None if st == OK else (f"Trop lâche : réduire le jeu de {d - jmax:.2f} mm par côté." if trop else f"Agrandir le logement ou réduire la pièce de {jmin - d:.2f} mm par côté.")))
    for aj in getattr(A, "ajustements", []):
        a, b = aj["a"], aj["b"]
        if a not in en_place or b not in en_place: continue
        v_, _ = _vol_inter(en_place[a], en_place[b])
        d = -max(_penetration(en_place[a], en_place[b]), _penetration(en_place[b], en_place[a])) if v_ > 0.01 else _distance_min(en_place[a], en_place[b])[0]
        ok_ = d >= aj["mini"] - 0.02 and (aj["maxi"] is None or d < aj["maxi"] + 0.02)
        out.append(res(f"Ajustement {a} ↔ {b} ({aj['type']})", OK if ok_ else ECHEC,
                       f"jeu dessiné {d:+.2f} mm par côté — fourchette « {aj['type']} » : {aj['mini']:+.2f} à " + (f"{aj['maxi']:+.2f}" if aj["maxi"] is not None else "∞") + " mm",
                       valeur=round(d, 3), conseil=None if ok_ else "Corriger le Ø (calc ajustement cible=... donne la cote à dessiner)."))
    # 3) chemin de montage, dans l'ordre
    presentes = {n: en_place[n] for n in noms if n not in {s['piece'] for s in A.sequence}}
    for s in A.sequence:
        nom = s["piece"]; base = meshes[nom]; Mf = A.poses.get(nom, np.eye(4))
        try:
            premier, pire, pire_par, max_coll, bloc = garde(f"Montage {nom}", _inserer_une, s, base, Mf, presentes, clips, serrages)
        except NonVerifie as e_:
            out.append(res_non_verifie(f"Montage : {nom}", str(e_))); presentes[nom] = en_place[nom]; continue
        if bloc: A.__dict__.setdefault("_blocages", {})[nom] = bloc
        if premier:
            pc, autre, v, p, lieu = premier
            pire_txt = f"; pire collision {max_coll[0]:.1f} mm³ à {max_coll[1]} %" if max_coll[0] > v * 1.5 else ""
            out.append(res(f"Montage : {nom}", ECHEC, f"bloque contre « {autre} » à {pc} % du chemin (première touche {v:.2f} mm³, profondeur {p:.2f} mm{pire_txt})",
                           conseil="Ouvrir le passage, changer l'ordre de montage, ou rendre la zone flexible (clip calculé).",
                           lieux=[lieu] if lieu else None))
        else:
            extra = f" (interférence de clip max {pire:.2f} mm, normale)" if pire > 0 else ""
            out.append(res(f"Montage : {nom}", OK, f"entre sur tout son chemin sans bloquer{extra}"))
        for autre, flex in pire_par.items():   # calcul du clip avec la flexion réellement mesurée
            cc = getattr(A, "clips_calc", {}).get(frozenset((nom, autre)))
            annoncee = clips.get(frozenset((nom, autre)))
            jug = juger_exigence("accroche", flex)
            A.__dict__.setdefault("accroches_mesurees", {})[f"{nom} → {autre}"] = dict(mesuree=round(flex, 3), annoncee=annoncee)
            if not cc or jug:
                st_ = jug[0] if jug else (AVERT if annoncee is not None and abs(flex - annoncee) > 0.05 else OK)
                out.append(res(f"Accroche mesurée {nom} → {autre}", st_,
                               f"accroche réelle {flex:.2f} mm (interférence max mesurée au montage), annoncée {annoncee} mm" + (f" → {jug[1]}" if jug else
                               (f" : écart {flex - annoncee:+.2f} mm, le rapport doit dire {flex:.2f}" if st_ == AVERT else "")), valeur=round(flex, 3),
                               exigence="accroche", mesure="forme", unite="mm",
                               conseil=None if st_ == OK else "Corriger la géométrie du crochet (pénétration radiale réelle), pas seulement la valeur déclarée."))
            if not cc: continue
            r = calc_snap(cc["L"], cc["h"], cc["w"], max(flex, cc["accroche"]), cc["mat"], cc["alpha_in"], cc["alpha_out"], usage=cc["usage"], conique=cc["conique"])
            if flex < REGLES["accroche_min"] - 1e-9:      # la résistance se calcule au pire, mais la TENUE dépend de l'accroche réelle
                r["verdict"] = ECHEC
                r["notes"] = [f"accroche réellement mesurée {flex:.2f} mm < {REGLES['accroche_min']} mm ({'consigne' if 'accroche' in EXIGENCES_ACTIVES else 'règle'}; déclarée {cc['accroche']} mm) : le clip ne retiendra pas"] + r["notes"]
            out.append(res(f"Clip {nom} → {autre} (calcul)", r["verdict"],
                           f"flexion mesurée {flex:.2f} mm (accroche annoncée {cc['accroche']} mm) · déformation {r['deformation_pct']} % (max {r['deformation_max_pct']:.0f} %) · contrainte {r['contrainte_MPa']} MPa (limite {r['limite_MPa']}) · "
                           f"poussée pour clipser {r['force_insertion_N']} N · retrait {r['force_retrait_N']}" + (" N" if not isinstance(r['force_retrait_N'], str) else ""),
                           conseil="; ".join(r["notes"]) or None))
        presentes[nom] = en_place[nom]
    # 4) états de fonctionnement
    for nom_etat, depl in A.etats:
        poses = {n: en_place[n] for n in noms}
        for n, M in depl.items():
            mm = meshes[n].copy(); mm.apply_transform(_pose(M) @ A.poses.get(n, np.eye(4))); poses[n] = mm
        pb = []; vus = set()
        for n in depl:
            for autre, mo in poses.items():
                if autre == n: continue
                v, _ = _vol_inter(poses[n], mo)
                if v > 0.01 and frozenset((n, autre)) not in clips and frozenset((n, autre)) not in serrages:
                    pb.append(f"{n}/{autre} {v:.2f} mm³")
        out.append(res(f"État « {nom_etat} »", ECHEC if pb else OK, "collisions : " + ", ".join(pb) if pb else "aucune collision dans cet état"))
        for k_ in clips:                     # clip FERMÉ dans cet état : le crochet reste-t-il enfoncé dans la paroi (bras plié en permanence) ?
            if len(k_) != 2 or not (k_ & set(depl)): continue
            a_, b_ = sorted(k_)
            if a_ not in poses or b_ not in poses or k_ in vus: continue
            vus.add(k_)
            v, _ = _vol_inter(poses[a_], poses[b_])
            if v > 0.01:
                p = max(_penetration(poses[a_], poses[b_]), _penetration(poses[b_], poses[a_]))
                out.append(_clip_ferme(A, a_, b_, p, v, f"état « {nom_etat} »"))
    return out, en_place


def _clip_ferme(A, a, b, p, v, ou):
    """Clip déclaré, une fois FERMÉ (position finale ou état) : interférence résiduelle crochet ↔ paroi. > 0,1 mm = le bras reste
    plié en permanence (fluage, perte de force) → ⚠️; ❌ si la contrainte permanente (calc_snap, flèche = p, usage « maintenue ») dépasse la limite."""
    seuil = REGLES.get("clip_residuel_max", 0.1)
    if p <= seuil:
        return res(f"Clip fermé {a} / {b}", INFO, f"{ou} : contact du clip {v:.2f} mm³, interférence résiduelle {p:.2f} mm (≤ {seuil} mm : le bras revient droit)")
    cc = getattr(A, "clips_calc", {}).get(frozenset((a, b)))
    cons = (f"Le crochet doit retomber dans sa fenêtre/derrière son rebord une fois fermé : décaler le crochet ou creuser la fenêtre de {p:.2f} mm "
            f"(+0,1-0,2 de jeu), pour qu'il ne reste plus appuyé sur la paroi.")
    if not cc:
        return res(f"Clip fermé {a} / {b}", AVERT, f"{ou} : le crochet reste enfoncé {p:.2f} mm dans la paroi ({v:.2f} mm³) → bras plié en permanence "
                   f"(fluage, perte de force); contrainte non calculée (clip sans L/h/w)", valeur=round(p, 2), conseil=cons)
    r = calc_snap(cc["L"], cc["h"], cc["w"], p, cc["mat"], cc["alpha_in"], cc["alpha_out"], usage="maintenue", conique=cc["conique"])
    trop = r["contrainte_MPa"] > r["limite_MPa"] or r["deformation_pct"] > r["deformation_max_pct"]
    return res(f"Clip fermé {a} / {b}", ECHEC if trop else AVERT,
               f"{ou} : le crochet reste enfoncé {p:.2f} mm dans la paroi → bras plié EN PERMANENCE : contrainte permanente {r['contrainte_MPa']} MPa "
               f"(limite « maintenue » {r['limite_MPa']} MPa), déformation {r['deformation_pct']} %" +
               (" : il va fluer/casser" if trop else " : il flue avec le temps et perd sa force de retenue"), valeur=round(p, 2), conseil=cons)


# ----------------------------------------------------------------------------
# Calculs mécaniques
# ----------------------------------------------------------------------------
def calc_snap(L, h, w, y, mat="PETG", alpha_in=30.0, alpha_out=90.0, mu=None, usage="momentane", conique=False):
    """Clip en porte-à-faux (rectangulaire). L longueur, h épaisseur à la racine, w largeur, y accroche (flèche).
    Formules standard (Bayer/BASF) : eps = 1,5·h·y/L² (constant) ; conique (h bout = h/2) : eps = h·y/(1,09·L²)."""
    M = MATERIAUX[mat]; E = M["E"]; mu = M["mu"] if mu is None else mu
    k_eps = 1 / 1.09 if conique else 1.5               # Bayer : conique y = 1,09·ε·L²/h → ε = h·y/(1,09·L²)
    eps = k_eps * h * y / L ** 2
    sigma = E * eps
    P = w * h ** 2 * E * eps / (6 * L)                  # force pour fléchir de y (N)
    k = E * w * h ** 3 / (4 * L ** 3)                    # raideur (N/mm)
    def pousse(a):
        ta = math.tan(math.radians(a))
        return float("inf") if mu * ta >= 1 else P * (mu + ta) / (1 - mu * ta)
    W_in = pousse(alpha_in); W_out = pousse(alpha_out) if alpha_out < 89.9 else float("inf")
    lim = {"maintenue": REGLES["contrainte_maintenue"], "momentane": REGLES["contrainte_momentanee"], "fatigue": REGLES["contrainte_fatigue"]}[usage]
    ok_eps = eps <= M["eps"]; ok_s = sigma <= lim
    return dict(deformation_pct=round(eps * 100, 2), deformation_max_pct=M["eps"] * 100, contrainte_MPa=round(sigma, 1), limite_MPa=lim,
                force_flexion_N=round(P, 2), raideur_N_mm=round(k, 2), force_insertion_N=round(W_in, 2),
                force_retrait_N=("permanent (outil requis)" if W_out == float("inf") else round(W_out, 2)),
                retrait_lecture=("permanent : il faut un outil pour défaire" if W_out == float("inf") else
                                 "s'ouvre très facilement (< 5 N) : risque de se défaire tout seul" if W_out < 5 else
                                 "s'ouvre à la main (5-15 N)" if W_out <= 15 else
                                 "ferme (15-30 N) : tirer fort" if W_out <= 30 else "très dur (> 30 N) : outil ou risque de casse"),
                verdict=OK if (ok_eps and ok_s and y >= REGLES["accroche_min"] - 1e-9) else ECHEC,
                notes=([] if y >= REGLES["accroche_min"] else [f"accroche {y} mm < {REGLES['accroche_min']} mm (règle)"]) +
                      ([] if ok_s else [f"contrainte {sigma:.0f} MPa > {lim} MPa : allonger L ou amincir h"]) +
                      ([] if ok_eps else [f"déformation {eps*100:.1f} % > {M['eps']*100:.0f} % : risque de casse"]))


def calc_lame(L, h, w, fleche, mat="PETG", frottement_N=0.0, usage="fatigue"):
    """Lame/bras de rappel : force au bout pour une flèche donnée, et marge vs frottements (règle ≥ 3×)."""
    M = MATERIAUX[mat]; E = M["E"]
    k = E * w * h ** 3 / (4 * L ** 3); F = k * fleche
    sigma = 3 * E * h * fleche / (2 * L ** 2)
    lim = {"maintenue": REGLES["contrainte_maintenue"], "momentane": REGLES["contrainte_momentanee"], "fatigue": REGLES["contrainte_fatigue"]}[usage]
    marge = (F / frottement_N) if frottement_N > 0 else None
    notes = []
    if sigma > lim: notes.append(f"contrainte {sigma:.0f} MPa > {lim} MPa ({usage}) : allonger la lame (σ baisse avec L²) ou l'amincir")
    if marge is not None and marge < 3: notes.append(f"force {F:.2f} N = {marge:.1f}× les frottements < 3× : lame plus large/épaisse ou ressort de métal")
    return dict(raideur_N_mm=round(k, 3), force_N=round(F, 3), contrainte_MPa=round(sigma, 1), limite_MPa=lim,
                marge_vs_frottement=None if marge is None else round(marge, 2), verdict=ECHEC if notes else OK, notes=notes)


def calc_ressort(d_fil, D_moyen, spires_actives, course, G=79000.0):
    """Ressort de compression en acier (G=79 GPa) : k = G·d⁴/(8·D³·n)."""
    k = G * d_fil ** 4 / (8 * D_moyen ** 3 * spires_actives)
    C = D_moyen / d_fil; Kw = (4 * C - 1) / (4 * C - 4) + 0.615 / C           # facteur de Wahl
    tau = Kw * 8 * k * course * D_moyen / (math.pi * d_fil ** 3)
    lim = 700.0   # corde à piano, usage répété (≈ 35-40 % de la rupture)
    return dict(raideur_N_mm=round(k, 3), force_N=round(k * course, 2), contrainte_MPa=round(tau, 0), limite_MPa=lim,
                verdict=OK if tau <= lim else ECHEC, notes=[] if tau <= lim else ["ressort trop sollicité : plus de spires ou fil plus gros"])


def calc_rampe(F, alpha, mu=0.3):
    t = math.tan(math.radians(alpha))
    return dict(retour_N=round(F * (t - mu) / (1 + mu * t), 2), poussee_N=round(F * (t + mu) / (1 - mu * t), 2) if mu * t < 1 else "bloqué")


TROUS = {  # diamètres conseillés FDM buse 0,4 (à confirmer sur la fiche du fabricant pour les inserts)
    "vis_passage": {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 8.8},
    "vis_autotaraudeuse_plastique": {"M2": 1.7, "M2.5": 2.1, "M3": 2.6, "M4": 3.5, "M5": 4.4},
    "ecrou_hex_logement_plat": {"M2": 4.4, "M2.5": 5.4, "M3": 5.9, "M4": 7.4, "M5": 8.4, "M6": 10.4},
    "insert_chaleur_court": {"M2": 3.2, "M2.5": 3.6, "M3": 4.0, "M4": 5.6, "M5": 6.4},
    "aimant_6x2": 6.2, "aimant_6x3": 6.2, "aimant_10x2": 10.2, "roulement_608_logement": 22.15,
}


# ----------------------------------------------------------------------------
# Rendu (rastériseur z-buffer, sans OpenGL)
# ----------------------------------------------------------------------------
try:
    from numba import njit
except ImportError:  # repli lent
    def njit(*a, **k):
        def d(f): return f
        return d(a[0]) if a and callable(a[0]) else d


@njit(cache=True)
def _raster(px, py, pz, F, col, W, H, img, zb, fid):
    for t in range(F.shape[0]):
        a, b, c = F[t, 0], F[t, 1], F[t, 2]
        x0, y0, x1, y1, x2, y2 = px[a], py[a], px[b], py[b], px[c], py[c]
        mnx = max(int(math.floor(min(x0, x1, x2))), 0); mxx = min(int(math.ceil(max(x0, x1, x2))), W - 1)
        mny = max(int(math.floor(min(y0, y1, y2))), 0); mxy = min(int(math.ceil(max(y0, y1, y2))), H - 1)
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-12: continue
        for yy in range(mny, mxy + 1):
            for xx in range(mnx, mxx + 1):
                fx = xx + 0.5; fy = yy + 0.5
                w0 = ((y1 - y2) * (fx - x2) + (x2 - x1) * (fy - y2)) / den
                w1 = ((y2 - y0) * (fx - x2) + (x0 - x2) * (fy - y2)) / den
                w2 = 1.0 - w0 - w1
                if w0 < 0 or w1 < 0 or w2 < 0: continue
                z = w0 * pz[a] + w1 * pz[b] + w2 * pz[c]
                if z > zb[yy, xx]:
                    zb[yy, xx] = z; fid[yy, xx] = t
                    img[yy, xx, 0] = col[t, 0]; img[yy, xx, 1] = col[t, 1]; img[yy, xx, 2] = col[t, 2]


VUES = {  # direction de regard (de la caméra vers l'objet), haut
    "Avant": ((0, 1, 0), (0, 0, 1)), "Arrière": ((0, -1, 0), (0, 0, 1)),
    "Gauche": ((1, 0, 0), (0, 0, 1)), "Droite": ((-1, 0, 0), (0, 0, 1)),
    "Dessus": ((0, 0, -1), (0, 1, 0)), "Dessous": ((0, 0, 1), (0, -1, 0)),
    "Iso avant": ((-1, 1, -0.8), (0, 0, 1)), "Iso arrière": ((1, -1, -0.8), (0, 0, 1)),
    "Iso dessous": ((-1, 1, 0.9), (0, 0, 1)),
}


def _camera(dirv, up):
    d = np.asarray(dirv, float); d /= np.linalg.norm(d)
    u = np.asarray(up, float); r = np.cross(d, u)
    if np.linalg.norm(r) < 1e-6: r = np.cross(d, [1, 0, 0])
    r /= np.linalg.norm(r); u = np.cross(r, d)
    return r, u, d


def rendre_vue(meshes_couleurs, vue, taille=520, ss=2, cadre=None):
    """meshes_couleurs : liste de (mesh, couleurs_par_face Nx3 ou rgb). Retourne image PIL."""
    from PIL import Image
    r, u, d = _camera(*VUES[vue]) if isinstance(vue, str) else _camera(*vue)
    V = np.vstack([m.vertices for m, _ in meshes_couleurs])
    if cadre is None:
        P = np.c_[V @ r, V @ u]
        lo, hi = P.min(0), P.max(0)
    else:
        lo, hi = cadre
    W = H = taille * ss
    ech = (W * 0.86) / max((hi - lo).max(), 1e-6)
    cx, cy = (lo + hi) / 2
    img = np.ones((H, W, 3), np.float64); zb = np.full((H, W), -1e18); fid = np.full((H, W), -1, np.int64)
    lum = -d * 0.75 - r * 0.35 + u * 0.55; lum /= np.linalg.norm(lum)
    decal = 0
    for m, c in meshes_couleurs:
        px = (m.vertices @ r - cx) * ech + W / 2
        py = H / 2 - (m.vertices @ u - cy) * ech
        pz = -(m.vertices @ d)
        n = m.face_normals
        visible_light = np.clip(n @ lum, 0, 1)
        base = np.broadcast_to(np.asarray(c, float), (len(m.faces), 3)) if np.ndim(c) == 1 else np.asarray(c, float)
        sh = (0.5 + 0.55 * visible_light)[:, None]
        col = np.clip(base * sh, 0, 1)
        _raster(px, py, pz, np.asarray(m.faces, np.int64) , col, W, H, img, zb, fid if decal == 0 else fid)
        decal += 1
    # contours : discontinuités de profondeur et de teinte (arêtes vives)
    g = np.zeros((H, W), bool)
    dz = np.abs(np.diff(zb, axis=0)); g[1:, :] |= dz > (0.6 / 1)  # en mm-ish relatif
    dz2 = np.abs(np.diff(zb, axis=1)); g[:, 1:] |= dz2 > 0.6
    lumi = img.mean(2)
    g[1:, :] |= np.abs(np.diff(lumi, axis=0)) > 0.10
    g[:, 1:] |= np.abs(np.diff(lumi, axis=1)) > 0.10
    img[g & (zb > -1e17)] *= 0.35
    bg = zb < -1e17
    img[bg] = (0.965, 0.965, 0.97)
    im = Image.fromarray((img * 255).astype(np.uint8)).resize((taille, taille), Image.LANCZOS)
    return im, (lo, hi), ech / ss


def couleurs_alerte(m, surpl=None, ep=None, piece=None, mode="normal", fe=None):
    base = np.tile(np.asarray(piece.couleur if piece else (0.75, 0.78, 0.82)), (len(m.faces), 1))
    if mode == "surplombs" and surpl is not None:
        base[surpl] = (0.95, 0.25, 0.2)
    if mode == "epaisseur" and ep is not None:
        if piece and piece.mur_min is not None: mur = piece.mur_min
        elif piece and piece.role == "flexible": mur = REGLES["mur_absolu"]
        else: mur = REGLES["mur_min"]
        bad = ~np.isnan(ep) & (ep < mur - 0.02)
        tres = ~np.isnan(ep) & (ep < REGLES["mur_absolu"])
        base[bad] = (1.0, 0.72, 0.1); base[tres] = (0.95, 0.2, 0.2)
        if fe is not None:
            base[~np.isnan(fe) & (fe < REGLES["fente_min"] - 0.02)] = (0.62, 0.3, 0.9)
    return base


def planche(m, piece, surpl, ep, titre, chemin, assemblage=None, fe=None):
    """Planche 3×3 : 6 vues + 2 iso + carte des problèmes, cotes et légende."""
    from PIL import Image, ImageDraw, ImageFont
    def fnt(s):
        for f in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]:
            if os.path.exists(f): return ImageFont.truetype(f, s)
        return ImageFont.load_default()
    T = 420
    fond = Image.new("RGB", (T * 3, T * 3 + 70), (255, 255, 255))
    dr = ImageDraw.Draw(fond)
    dr.text((14, 14), titre, fill=(20, 20, 30), font=fnt(26))
    e = m.extents
    dr.text((14, 46), f"{e[0]:.1f} × {e[1]:.1f} × {e[2]:.1f} mm  —  orange : mur < règle · rouge : trop mince · violet : fente < 1,2 mm · dernière case : surplombs vus de dessous", fill=(70, 70, 80), font=fnt(15))
    vues = ["Avant", "Droite", "Dessus", "Arrière", "Gauche", "Dessous", "Iso avant", "Iso arrière", None]
    for k, v in enumerate(vues):
        x, y = (k % 3) * T, 70 + (k // 3) * T
        if v is None:
            c = couleurs_alerte(m, surpl, ep, piece, "surplombs")
            im, _, _ = rendre_vue([(m, c)], "Iso dessous", T)
            lab = "Surplombs > 45° (rouge), vus de dessous"
        else:
            c = couleurs_alerte(m, surpl, ep, piece, "epaisseur", fe)
            im, _, _ = rendre_vue([(m, c)], v, T)
            lab = v
        fond.paste(im, (x, y))
        dr.text((x + 10, y + 8), lab, fill=(30, 30, 40), font=fnt(16))
        dr.rectangle([x, y, x + T - 1, y + T - 1], outline=(225, 225, 230))
    fond.save(chemin)
    return chemin


def coupes(m, chemin, nb=3, titre="Coupes"):
    """Vues en coupe (X, Y, Z au milieu et aux tiers) : murs internes, logements, jeux."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, nb, figsize=(4.2 * nb, 12))
    lo, hi = m.bounds
    for i, (axe, nrm) in enumerate([("X", [1, 0, 0]), ("Y", [0, 1, 0]), ("Z", [0, 0, 1])]):
        for j in range(nb):
            t = (j + 1) / (nb + 1)
            o = lo + (hi - lo) * t
            ax = axes[i, j]
            s = m.section(plane_origin=o, plane_normal=nrm)
            ax.set_title(f"Coupe {axe} = {o['XYZ'.index(axe)]:.1f} mm", fontsize=10)
            ax.set_aspect("equal"); ax.grid(alpha=0.25)
            if s is None: continue
            # coordonnées 2D lisibles : on projette sur les 2 autres axes
            k = "XYZ".index(axe); ax2 = [a for a in range(3) if a != k]
            boucles = sorted((Polygon(ent[:, ax2]).buffer(0) for ent in s.discrete if len(ent) >= 4), key=lambda p: -p.area)
            plein = Polygon()
            for b in boucles:       # pair-impair : une boucle dans une autre = un trou
                plein = plein.symmetric_difference(b)
            for g in getattr(plein, "geoms", [plein]):
                if g.is_empty or not hasattr(g, "exterior"): continue
                x, y = g.exterior.xy; ax.fill(x, y, color=(0.35, 0.5, 0.85, 0.45), lw=0); ax.plot(x, y, color=(0.1, 0.2, 0.5), lw=0.9)
                for h in g.interiors:
                    x, y = h.xy; ax.fill(x, y, color="white", lw=0); ax.plot(x, y, color=(0.1, 0.2, 0.5), lw=0.9)
            ax.set_xlim(lo[ax2[0]] - 1, hi[ax2[0]] + 1); ax.set_ylim(lo[ax2[1]] - 1, hi[ax2[1]] + 1)   # même échelle que la pièce entière
            ax.set_xlabel("XYZ"[ax2[0]] + " (mm)"); ax.set_ylabel("XYZ"[ax2[1]] + " (mm)")
    fig.suptitle(titre); fig.tight_layout(); fig.savefig(chemin, dpi=90); plt.close(fig)
    return chemin


# palette de l'identité LC3D (mêmes couleurs que les photos du catalogue) : orange, anthracite, crème, bleu, olive
PALETTE_STUDIO = [(0.85, 0.36, 0.11), (0.21, 0.24, 0.28), (0.90, 0.88, 0.84), (0.13, 0.36, 0.62), (0.40, 0.50, 0.25),
                  (0.62, 0.20, 0.18), (0.55, 0.47, 0.36)]
PALETTE = [(0.88, 0.55, 0.2), (0.3, 0.55, 0.88), (0.4, 0.75, 0.45), (0.82, 0.35, 0.5), (0.6, 0.5, 0.88),
           (0.88, 0.8, 0.3), (0.45, 0.75, 0.8), (0.7, 0.7, 0.7)]


def _fnt(s):
    from PIL import ImageFont
    for f in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(f): return ImageFont.truetype(f, s)
    return ImageFont.load_default()


def _couper(m, y_plan, *_):
    """Enlève la moitié avant (y < y_plan) pour voir l'intérieur d'un assemblage."""
    lo, hi = m.bounds
    if hi[1] <= y_plan: return trimesh.Trimesh()
    boite = trimesh.creation.box(extents=[hi[0] - lo[0] + 2, y_plan - lo[1] + 1, hi[2] - lo[2] + 2])
    boite.apply_translation([(lo[0] + hi[0]) / 2, (lo[1] - 1 + y_plan) / 2, (lo[2] + hi[2]) / 2])
    try:
        return _de_manifold(_manifold(m) - _manifold(boite))
    except Exception:
        return m


def planche_assemblage(en_place: dict, chemin, titre="Assemblage"):
    """Iso avant, iso arrière, coupe au milieu (on voit l'intérieur) et vue éclatée, avec légende des couleurs."""
    from PIL import Image, ImageDraw
    noms = list(en_place)
    cols = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(noms)}
    T = 540
    fond = Image.new("RGB", (T * 2, T * 2 + 90), "white"); dr = ImageDraw.Draw(fond)
    dr.text((12, 10), titre, fill=(20, 20, 30), font=_fnt(24))
    x = 12
    for n in noms:
        dr.rectangle([x, 52, x + 18, 70], fill=tuple(int(c * 255) for c in cols[n])); dr.text((x + 24, 50), n, fill=(30, 30, 40), font=_fnt(17))
        x += 34 + int(_fnt(17).getlength(n))
    ens = trimesh.util.concatenate(list(en_place.values()))
    vues = [("Iso avant", [(m, cols[n]) for n, m in en_place.items()]),
            ("Iso arrière", [(m, cols[n]) for n, m in en_place.items()]),
            ("Coupe au milieu (moitié avant enlevée)", [(_couper(m, float(ens.centroid[1]), 1), cols[n]) for n, m in en_place.items() if m.bounds[0, 1] < ens.centroid[1]] +
             [(m, cols[n]) for n, m in en_place.items() if m.bounds[0, 1] >= ens.centroid[1]]),
            ("Vue éclatée", [])]
    hz = float(ens.extents[2]) * 0.6 + 10
    ordre = sorted(noms, key=lambda n: en_place[n].bounds[0, 2])
    for k, n in enumerate(ordre):
        mm = en_place[n].copy(); mm.apply_translation([0, 0, k * hz]); vues[3][1].append((mm, cols[n]))
    for k, (lab, mc) in enumerate(vues):
        mc = [(m, c) for m, c in mc if len(m.faces)]
        if not mc: continue
        im, _, _ = rendre_vue(mc, "Iso arrière" if lab == "Iso arrière" else "Iso avant", T)
        x0, y0 = (k % 2) * T, 90 + (k // 2) * T
        fond.paste(im, (x0, y0)); dr.text((x0 + 10, y0 + 8), lab, fill=(30, 30, 40), font=_fnt(16))
        dr.rectangle([x0, y0, x0 + T - 1, y0 + T - 1], outline=(225, 225, 230))
    fond.save(chemin); return chemin


def planche_montage(meshes, A: Assemblage, chemin):
    """Bande dessinée du montage : pour chaque étape, 4 images (départ → arrivée) avec les pièces déjà en place."""
    from PIL import Image, ImageDraw
    if not A.sequence: return None
    noms = list(meshes); cols = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(noms)}
    places = {}
    for n, m in meshes.items():
        mm = m.copy(); mm.apply_transform(A.poses.get(n, np.eye(4))); places[n] = mm
    seq = {s["piece"] for s in A.sequence}
    presentes = [n for n in noms if n not in seq]
    T = 300; lignes = len(A.sequence)
    bloc = getattr(A, "_blocages", {})
    fond = Image.new("RGB", (T * (5 if bloc else 4), lignes * (T + 34) + 10), "white"); dr = ImageDraw.Draw(fond)
    for i, s in enumerate(A.sequence):
        n = s["piece"]; Mf = A.poses.get(n, np.eye(4))
        dr.text((10, i * (T + 34) + 8), f"Étape {i + 1} : {n} — " + ("arrive en ligne droite" if s["type"] == "translation" else f"arrive en pivotant de {s['angle']}°"), fill=(20, 20, 30), font=_fnt(17))
        for k, t in enumerate((1.0, 0.66, 0.33, 0.0)):
            if s["type"] == "translation":
                Mk = trimesh.transformations.translation_matrix(np.asarray(s["depuis"]) * t) @ Mf
            else:
                Mk = trimesh.transformations.rotation_matrix(math.radians(s["angle"] * t), s["axe"], s["pivot"]) @ Mf
            mk = meshes[n].copy(); mk.apply_transform(Mk)
            mc = [(places[p], tuple(0.55 + 0.45 * c for c in cols[p])) for p in presentes] + [(mk, cols[n])]
            if k == 0:
                Vall = np.vstack([m.vertices for m, _ in mc])
                r, u, d = _camera(*VUES["Iso avant"]); P = np.c_[Vall @ r, Vall @ u]
                Vend = np.vstack([places[p].vertices for p in presentes + [n]]); P2 = np.c_[Vend @ r, Vend @ u]
                cadre = (np.minimum(P.min(0), P2.min(0)), np.maximum(P.max(0), P2.max(0)))
            im, _, _ = rendre_vue(mc, "Iso avant", T, cadre=cadre)
            fond.paste(im, (k * T, i * (T + 34) + 34))
        if n in bloc:   # 5e case : l'endroit exact où ça bloque, en rouge
            t, Im = bloc[n]
            if s["type"] == "translation":
                Mk = trimesh.transformations.translation_matrix(np.asarray(s["depuis"]) * t) @ Mf
            else:
                Mk = trimesh.transformations.rotation_matrix(math.radians(s["angle"] * t), s["axe"], s["pivot"]) @ Mf
            mk = meshes[n].copy(); mk.apply_transform(Mk)
            mc = [(places[p], tuple(0.7 + 0.3 * c for c in cols[p])) for p in presentes] + [(mk, tuple(0.6 + 0.4 * c for c in cols[n]))]
            if Im is not None and len(Im.faces):
                gros = Im.copy(); gros.apply_scale(1.0)
                mc.append((gros, (0.95, 0.1, 0.1)))
            im, (lo2, hi2), ech = rendre_vue(mc, "Iso avant", T, cadre=cadre)
            if Im is not None and len(Im.faces):   # cercle rouge à l'endroit du blocage (visible même caché dans les pièces)
                r_, u_, d_ = _camera(*VUES["Iso avant"]); cxy = (lo2 + hi2) / 2; p = Im.centroid
                px = (p @ r_ - cxy[0]) * ech + T / 2; py = T / 2 - (p @ u_ - cxy[1]) * ech
                d2 = ImageDraw.Draw(im)
                for rr in (14, 15, 16): d2.ellipse([px - rr, py - rr, px + rr, py + rr], outline=(230, 20, 20))
            fond.paste(im, (4 * T, i * (T + 34) + 34))
            dr.text((4 * T + 8, i * (T + 34) + 38), f"BLOQUE à {round((1 - t) * 100)} % (cercle rouge)", fill=(200, 20, 20), font=_fnt(15))
        presentes.append(n)
    fond.save(chemin); return chemin


# ----------------------------------------------------------------------------
# Gridfinity (spec : gridfinity.xyz / gridfinity-rebuilt)
# ----------------------------------------------------------------------------
GF = dict(pas=42.0, unite_h=7.0, haut_base=7.0, cote_base=41.5, r_haut=3.75, profil=(0.8, 1.8, 2.15),
          mur=0.95, cloison=1.2, aimant_d=6.5, aimant_p=2.4, trou_vis_d=3.0, aimant_du_bord=8.0,
          levre=(0.7, 1.8, 1.9), levre_support=1.2, plaque_profil=(0.7, 1.8, 2.15))


def _wire_rr(cq, z, cx, cy, r):
    r = max(min(r, cx / 2 - 0.01, cy / 2 - 0.01), 0.05)
    w = cq.Workplane("XY").workplane(offset=z).rect(cx, cy).val()
    face = cq.Face.makeFromWires(w)
    face = face.fillet2D(r, face.Vertices())
    return face.outerWire()


def gridfinity_bac(nx=1, ny=1, nz=3, cases_x=1, cases_y=1, aimants=False, levre=True, etiquette=False, plein=False):
    """Bac Gridfinity conforme : base 0,8/1,8/2,15 à 45°, 41,5 mm par case, hauteur nz×7 mm (+ lèvre 4,4 mm)."""
    import cadquery as cq
    p0, p1, p2 = GF["profil"]; c = GF["cote_base"]; R = GF["r_haut"]
    H = nz * GF["unite_h"]
    Lx, Ly = nx * GF["pas"] - 0.5, ny * GF["pas"] - 0.5
    solide = None
    for i in range(nx):
        for j in range(ny):
            ox = (i - (nx - 1) / 2) * GF["pas"]; oy = (j - (ny - 1) / 2) * GF["pas"]
            s = cq.Solid.makeLoft([
                _wire_rr(cq, 0, c - 2 * (p0 + p2), c - 2 * (p0 + p2), R - p0 - p2),
                _wire_rr(cq, p0, c - 2 * p2, c - 2 * p2, R - p2),
                _wire_rr(cq, p0 + p1, c - 2 * p2, c - 2 * p2, R - p2),
                _wire_rr(cq, p0 + p1 + p2, c, c, R)], True).translate(cq.Vector(ox, oy, 0))
            solide = s if solide is None else solide.fuse(s)
    corps = cq.Workplane("XY").add(solide)
    zb = p0 + p1 + p2
    haut = cq.Workplane("XY").workplane(offset=zb).sketch().rect(Lx, Ly).vertices().fillet(R).finalize().extrude(H - zb)
    corps = corps.union(haut)
    crete = 0.9   # crête plate (≥ 2 lignes) : la pointe de la spec ne s'imprime pas et gênerait l'empilement
    if levre:
        l0, l1, l2 = GF["levre"]; tip = l0 + l2
        Lh = l0 + l1 + (tip - l0 - crete)          # 3,5 mm : le bac empilé s'appuie sur les pentes à 45°
        lev = cq.Workplane("XY").workplane(offset=H).sketch().rect(Lx, Ly).vertices().fillet(R).finalize().extrude(Lh)
        corps = corps.union(lev)
    if not plein:
        m = GF["mur"]
        sol = GF["haut_base"]
        if levre:
            l0, l1, l2 = GF["levre"]; tip = l0 + l2   # 2,6 mm
            z_a = H - GF["levre_support"] - (tip - m)
            z_c = H + Lh
            secs = [(sol, m), (z_a, m), (H - GF["levre_support"], tip), (H, tip), (H + l0, tip - l0), (H + l0 + l1, tip - l0), (z_c, crete)]
        else:
            secs = [(sol, m), (H + 0.01, m)]
        secs = [s for s in secs if s[0] >= sol]
        cav = cq.Solid.makeLoft([_wire_rr(cq, z, Lx - 2 * ins, Ly - 2 * ins, R - ins) for z, ins in secs], True)
        if levre:
            cav = cav.fuse(cq.Workplane("XY").workplane(offset=H + Lh - 0.001).rect(Lx + 2, Ly + 2).extrude(1).val())
        corps = corps.cut(cq.Workplane("XY").add(cav))
        # cloisons
        ix, iy = Lx - 2 * m, Ly - 2 * m
        for k in range(1, cases_x):
            x = -ix / 2 + ix * k / cases_x
            corps = corps.union(cq.Workplane("XY").workplane(offset=sol).center(x, 0).rect(GF["cloison"], iy).extrude(H - sol - 0.6))
        for k in range(1, cases_y):
            y = -iy / 2 + iy * k / cases_y
            corps = corps.union(cq.Workplane("XY").workplane(offset=sol).center(0, y).rect(ix, GF["cloison"]).extrude(H - sol - 0.6))
        if etiquette:
            d = 15.85; hh = math.tan(math.radians(36)) * d + 1.2
            z_top = (H - GF["levre_support"] - (GF["levre"][0] + GF["levre"][2] - m) + 0.3) if levre else H - 0.6   # soudé au support de la lèvre
            prof = (cq.Workplane("YZ").polyline([(0.4, z_top - hh), (0.4, z_top), (-d, z_top), (-d, z_top - 1.2)]).close()
                    .extrude(ix + 0.6).translate((-ix / 2 - 0.3, iy / 2, 0)))   # 0,4 mm noyé dans le mur : soudure franche
            enveloppe = cq.Workplane("XY").sketch().rect(Lx - 0.2, Ly - 0.2).vertices().fillet(R - 0.1).finalize().extrude(H + 10)
            corps = corps.union(prof.intersect(enveloppe))   # ne dépasse jamais du contour (coins arrondis)
    if aimants:
        dd = GF["pas"] / 2 - GF["aimant_du_bord"]
        pts = []
        for i in range(nx):
            for j in range(ny):
                ox = (i - (nx - 1) / 2) * GF["pas"]; oy = (j - (ny - 1) / 2) * GF["pas"]
                pts += [(ox + sx * dd, oy + sy * dd) for sx in (-1, 1) for sy in (-1, 1)]
        corps = corps.cut(cq.Workplane("XY").pushPoints(pts).circle(GF["aimant_d"] / 2).extrude(GF["aimant_p"]))
    return corps


def gridfinity_plaque(nx=1, ny=1):
    """Plaque de base Gridfinity (profil 0,7/1,8/2,15, ouverte dessous)."""
    import cadquery as cq
    q0, q1, q2 = GF["plaque_profil"]; Hp = q0 + q1 + q2; R = 4.0
    plaque = cq.Workplane("XY").sketch().rect(nx * GF["pas"], ny * GF["pas"]).vertices().fillet(R).finalize().extrude(Hp)
    for i in range(nx):
        for j in range(ny):
            ox = (i - (nx - 1) / 2) * GF["pas"]; oy = (j - (ny - 1) / 2) * GF["pas"]
            c = GF["pas"]
            poche = cq.Solid.makeLoft([
                _wire_rr(cq, -0.01, c - 2 * (q0 + q2), c - 2 * (q0 + q2), R - q0 - q2),
                _wire_rr(cq, q0, c - 2 * q2, c - 2 * q2, R - q2),
                _wire_rr(cq, q0 + q1, c - 2 * q2, c - 2 * q2, R - q2),
                _wire_rr(cq, Hp + 0.01, c, c, R)], True).translate(cq.Vector(ox, oy, 0))
            plaque = plaque.cut(cq.Workplane("XY").add(poche))
    return plaque


# ----------------------------------------------------------------------------
# Contour d'un objet réel : depuis un scan 3D ou une photo sur feuille
# ----------------------------------------------------------------------------
def contour_depuis_scan(chemin, jeu=0.5, a_plat=True, tranches=40, simplifier=0.1):
    """Empreinte réelle d'un objet scanné : union des coupes sur toute la hauteur (ombre portée),
    tournée à l'angle qui minimise le rectangle englobant, puis agrandie du jeu."""
    m = trimesh.load(chemin, force="mesh")
    if a_plat:
        T = m.principal_inertia_transform; m.apply_transform(T)
        # mettre le plus petit axe en Z
        ext = m.extents; k = int(np.argmin(ext))
        if k != 2:
            m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0] if k == 1 else [0, 1, 0]))
    m.apply_translation(-m.bounds[0])
    zs = np.linspace(m.bounds[0, 2] + 0.05, m.bounds[1, 2] - 0.05, tranches)
    polys = [p for z in zs if (p := _polys_section(m, z)) is not None]
    emp = unary_union(polys)
    mrr = emp.minimum_rotated_rectangle
    xs, ys = mrr.exterior.coords.xy
    ang = math.degrees(math.atan2(ys[1] - ys[0], xs[1] - xs[0]))
    from shapely import affinity
    emp = affinity.rotate(emp, -ang, origin="centroid")
    emp = emp.buffer(jeu, join_style=1).simplify(simplifier)
    emp = affinity.translate(emp, -emp.centroid.x, -emp.centroid.y)
    return emp, dict(hauteur=round(float(m.extents[2]), 2), angle=round(ang, 1), boite=[round(v, 2) for v in emp.bounds])


def contour_depuis_photo(chemin, ref="a4", mm_par_px=None, jeu=0.5, seuil=None):
    """Objet posé sur une feuille blanche (A4/Lettre) photographiée de haut. La feuille est détectée,
    redressée (perspective) à 10 px/mm, puis l'objet est détouré. Précision typique ±0,5 mm."""
    import cv2
    img = cv2.imread(chemin)
    if img is None: raise FileNotFoundError(chemin)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if mm_par_px is None:
        tailles = {"a4": (210.0, 297.0), "lettre": (215.9, 279.4)}
        Wmm, Hmm = tailles[ref]
        b = cv2.GaussianBlur(g, (5, 5), 0)
        _, th = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        feuille = max(cnts, key=cv2.contourArea)
        approx = cv2.approxPolyDP(feuille, 0.02 * cv2.arcLength(feuille, True), True)
        if len(approx) != 4:
            raise ValueError("Feuille non trouvée : prends la photo bien de haut, feuille entière visible sur fond foncé.")
        pts = approx.reshape(4, 2).astype(np.float32)
        s = pts.sum(1); d = np.diff(pts, axis=1).ravel()
        o = np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)
        largeur = np.linalg.norm(o[1] - o[0]); hauteur = np.linalg.norm(o[3] - o[0])
        if largeur > hauteur: Wmm, Hmm = Hmm, Wmm
        k = 10.0
        dst = np.array([[0, 0], [Wmm * k, 0], [Wmm * k, Hmm * k], [0, Hmm * k]], np.float32)
        P = cv2.getPerspectiveTransform(o, dst)
        g = cv2.warpPerspective(g, P, (int(Wmm * k), int(Hmm * k)))
        mm_par_px = 1 / k
        bord = int(4 * k); g = g[bord:-bord, bord:-bord]; decal = bord
    else:
        decal = 0
    b = cv2.GaussianBlur(g, (5, 5), 0)
    if seuil is None:
        _, th = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, th = cv2.threshold(b, seuil, 255, cv2.THRESH_BINARY_INV)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    obj = max(cnts, key=cv2.contourArea)
    pts = (obj.reshape(-1, 2) + decal) * mm_par_px
    pts[:, 1] = -pts[:, 1]
    P = Polygon(pts).buffer(0).buffer(jeu, join_style=1).simplify(0.1)
    from shapely import affinity
    P = affinity.translate(P, -P.centroid.x, -P.centroid.y)
    return P, dict(mm_par_px=mm_par_px, boite=[round(v, 2) for v in P.bounds])


def poche_cadquery(poly: Polygon, profondeur):
    """Transforme un contour shapely en solide CadQuery (à soustraire pour faire une poche)."""
    import cadquery as cq
    pts = list(poly.exterior.coords)[:-1]
    return cq.Workplane("XY").polyline(pts).close().extrude(profondeur)


def contour_svg(poly, chemin):
    xs, ys = poly.exterior.xy
    mnx, mny, mxx, mxy = poly.bounds
    w, h = mxx - mnx, mxy - mny
    d = "M " + " L ".join(f"{x - mnx:.3f},{mxy - y:.3f}" for x, y in zip(xs, ys)) + " Z"
    open(chemin, "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" viewBox="0 0 {w:.3f} {h:.3f}"><path d="{d}" fill="none" stroke="black" stroke-width="0.1"/></svg>')
    return chemin



def gravure_svg(forme_ou_maillage, chemin, z=None, remplir=True):
    """Fichier SVG à l'échelle réelle (mm) pour le laser (xTool Creative Space, LightBurn) : coupe la forme à la
    hauteur z (milieu par défaut) et écrit tous les contours, trous compris. remplir=True : zones pleines (gravure);
    False : traits (découpe)."""
    m = forme_ou_maillage if isinstance(forme_ou_maillage, trimesh.Trimesh) else vers_mesh(forme_ou_maillage)
    z = (m.bounds[0, 2] + m.bounds[1, 2]) / 2 if z is None else z
    s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    forme = Polygon()
    for b in s.discrete:
        P = Polygon(b[:, :2]).buffer(0)
        if not P.is_empty: forme = forme.symmetric_difference(P)
    mnx, mny, mxx, mxy = forme.bounds; w, h = mxx - mnx, mxy - mny
    def chemin_d(ring): return "M " + " L ".join(f"{x - mnx:.3f},{mxy - y:.3f}" for x, y in ring.coords) + " Z"
    polys = list(forme.geoms) if isinstance(forme, MultiPolygon) else [forme]
    d = " ".join(chemin_d(p.exterior) + " " + " ".join(chemin_d(i) for i in p.interiors) for p in polys)
    style = 'fill="black" fill-rule="evenodd" stroke="none"' if remplir else 'fill="none" stroke="red" stroke-width="0.1"'
    open(chemin, "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" viewBox="0 0 {w:.3f} {h:.3f}"><path d="{d}" {style}/></svg>')
    return dict(svg=chemin, largeur_mm=round(w, 2), hauteur_mm=round(h, 2), mode="gravure (plein)" if remplir else "découpe (traits rouges)")

# ----------------------------------------------------------------------------
# Livraison
# ----------------------------------------------------------------------------
def exporter_3mf(m: trimesh.Trimesh, copies: int, chemin):
    """Un seul fichier par pièce; si copies > 1, toutes les copies sont placées dans le même 3MF."""
    sc = trimesh.Scene()
    m = poser_sur_plateau(m)
    ex, ey = m.extents[0] + 6, m.extents[1] + 6
    cols = max(1, int(math.ceil(math.sqrt(copies))))
    for k in range(copies):
        c = m.copy()
        c.apply_translation([(k % cols - (cols - 1) / 2) * ex, (k // cols - (math.ceil(copies / cols) - 1) / 2) * ey, 0])
        sc.add_geometry(c, node_name=f"copie_{k + 1}")
    sc.export(chemin)
    return chemin


def livrer_multi(pieces_mesh: dict, pieces: dict, chemin):
    mats = {pieces[n].materiau for n in pieces_mesh}
    if "TPU" in mats and len(mats) > 1 and "Bambu" in MACHINE.get("nom", "") + MACHINE.get("profil", ""):
        raise ValueError("Sur une Bambu (AMS), le TPU ne passe pas dans l'AMS : imprimer les pièces en TPU à part (bobine externe). "
                         "Multi-matériaux avec TPU : Snapmaker U1 (4 têtes) ou machine à têtes multiples.")
    """UN 3MF avec toutes les pièces sur le plateau, chacune avec SON filament (PETG + TPU…) : AMS (Bambu),
    4 têtes (Snapmaker U1), MMU (Prusa). Retourne le chemin."""
    objets = [dict(nom=n, mesh=m, copies=pieces[n].copies, role=pieces[n].role, materiau=pieces[n].materiau) for n, m in pieces_mesh.items()]
    exporter_3mf_bambu(objets, chemin, objets[0]["materiau"], MACHINE["couche"])
    return chemin


def _hex(c):
    """Couleur -> « #RRGGBB » : « #hex », nom de filament (COULEURS_FILAMENT), ou (r, g, b) 0-1 ou 0-255."""
    if c is None: return None
    if isinstance(c, str):
        if c.startswith("#"): return c.upper()
        c = COULEURS_FILAMENT.get(c)
        if c is None: return None
    v = [float(x) for x in c][:3]
    if max(v) <= 1.0: v = [x * 255 for x in v]
    return "#" + "".join(f"{int(round(max(0, min(255, x)))):02X}" for x in v)


def reglages_bordure(m):
    """Réglages PAR OBJET du 3MF : bordure extérieure d'office si la pièce est haute sur une base étroite (besoin_bordure)."""
    b = besoin_bordure(m)
    return {"brim_type": "outer_only", "brim_width": f"{b['largeur_mm']:g}", "brim_object_gap": "0.1"} if b else {}


def _grouper_imprime_monte(meshes_poses, brut_meshes, pieces):
    """Pièces imprimées DÉJÀ MONTÉES (Piece(imprimer_avec="corps")) : un seul objet, les positions RELATIVES du modèle gardées
    (sinon le placement sur la plaque les écarte et la charnière imprimée en place est détruite — bug trouvé en essai réel)."""
    groupes = {}
    for n, pc in pieces.items():
        chef = getattr(pc, "imprimer_avec", None)
        if chef and chef in pieces and n in brut_meshes and chef in brut_meshes:
            groupes.setdefault(chef, [chef]).append(n)
    if not groupes: return meshes_poses, pieces
    mp, pc_out = dict(meshes_poses), dict(pieces)
    for chef, membres in groupes.items():
        tout = trimesh.util.concatenate([brut_meshes[m_] for m_ in membres])
        M = _matrice_orientation(pieces[chef], tout); tout = tout.copy(); tout.apply_transform(M); tout.apply_translation((0, 0, -tout.bounds[0][2]))
        nom = "_".join(membres)
        for m_ in membres: mp.pop(m_, None); pc_out.pop(m_, None)
        mp[nom] = tout; pc_out[nom] = pieces[chef]
    return mp, pc_out


def _maillage_propre(m):
    """Avant d'écrire un 3MF : sommets fusionnés, triangles dégénérés (aire nulle) et sommets orphelins retirés
    (un juge a compté 4 triangles dégénérés comme « non étanche » — essai réel)."""
    m = m.copy(); m.merge_vertices()
    try: m.update_faces(m.nondegenerate_faces(height=1e-7))
    except Exception:
        try: m.remove_degenerate_faces()
        except Exception: pass
    try: m.update_faces(m.unique_faces())
    except Exception: pass
    m.remove_unreferenced_vertices()
    try: trimesh.repair.fix_normals(m)
    except Exception: pass
    return m


def livrer(pieces_mesh: dict, pieces: dict, dossier, nom_projet, format="3mf", plateau_unique=False, couleurs=None):
    """Un seul zip, un seul fichier par pièce (copies incluses). 3MF = projet Bambu Studio avec la machine choisie, le profil,
    le filament et les réglages LC3D de la pièce déjà dedans. format='stl' ou 'step' sur demande.
    plateau_unique=True (run --plateau-unique, ou PLATEAU_UNIQUE = True dans le modèle) : UN 3MF avec toutes les pièces, chacune
    avec SON matériau et SA couleur (COULEURS = {piece: "#hex" | (r, g, b) | nom de filament} ou Piece(couleur=...)) : AMS, têtes multiples, MMU."""
    os.makedirs(dossier, exist_ok=True); livrer.orca = {}
    pieces_mesh = {n: _maillage_propre(m) for n, m in pieces_mesh.items()}
    zp = os.path.join(dossier, f"{nom_projet}.zip")
    if plateau_unique and format == "3mf":
        defaut = Piece.__dataclass_fields__["couleur"].default
        objets = []
        for nom, m in pieces_mesh.items():
            p = pieces[nom]
            c = (couleurs or {}).get(nom)
            if c is None and tuple(p.couleur) != tuple(defaut): c = p.couleur
            objets.append(dict(nom=nom, mesh=m, copies=p.copies, role=p.role, materiau=p.materiau, couleur=_hex(c), reglages=reglages_bordure(m)))
        mats_ = {normaliser_materiau(o["materiau"])["type"] for o in objets}
        if "TPU" in mats_ and len(mats_) > 1 and _est_bambu():
            raise ValueError("Sur une Bambu (AMS), le TPU ne passe pas dans l'AMS : imprimer les pièces en TPU à part (bobine externe). "
                             "Multi-matériaux avec TPU : Snapmaker U1 (4 têtes) ou machine à têtes multiples.")
        f = os.path.join(dossier, f"{nom_projet}.3mf")
        r = exporter_3mf_bambu(objets, f, objets[0]["materiau"], MACHINE["couche"])
        livrer.note_multi = r.get("note_multi")
        livrer.orca[nom_projet] = trancher_orca(f)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(f, arcname=f"{nom_projet}/{os.path.basename(f)}")
        os.unlink(f)
        return zp
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, m in pieces_mesh.items():
            p = pieces[nom]
            f = os.path.join(dossier, f"{nom}{'_x' + str(p.copies) if p.copies > 1 else ''}.{format}")
            if format == "3mf":
                # le VRAI matériau de la pièce (refus expliqué s'il n'a pas de profil sur cette machine, jamais du PETG en silence)
                exporter_3mf_bambu([dict(nom=nom, mesh=m, copies=p.copies, role=p.role, materiau=p.materiau, reglages=reglages_bordure(m))],
                                   f, p.materiau, MACHINE["couche"])
                livrer.orca[nom] = trancher_orca(f)
            elif format == "stl":
                copies = []
                for k in range(p.copies):
                    c = m.copy(); c.apply_translation([k * (m.extents[0] + 6), 0, 0]); copies.append(c)
                trimesh.util.concatenate(copies).export(f)
            elif format == "step":
                import cadquery as cq
                if isinstance(p.forme, trimesh.Trimesh): raise ValueError(f"{nom} : STEP impossible depuis un maillage (pièce non CAO)")
                cq.exporters.export(p.forme, f)
            z.write(f, arcname=f"{nom_projet}/{os.path.basename(f)}")
            os.unlink(f)
    return zp



# --- Tranchage EXACT du 3MF livré avec OrcaSlicer (gratuit) : mêmes réglages que ceux dans le fichier
ORCA_APP = os.environ.get("LC3D_ORCA", os.path.join(os.path.expanduser("~"), ".lc3d", "orcaslicer", "squashfs-root", "AppRun"))


def installer_orca(version="v2.4.2"):
    """Télécharge OrcaSlicer (AppImage officielle GitHub) dans ~/.lc3d/orcaslicer. Linux : il faut libwebkit2gtk-4.1-0."""
    import subprocess
    d = os.path.dirname(os.path.dirname(ORCA_APP)); os.makedirs(d, exist_ok=True)
    ai = os.path.join(d, "orca.AppImage")
    url = f"https://github.com/SoftFever/OrcaSlicer/releases/download/{version}/OrcaSlicer_Linux_AppImage_Ubuntu2404_{version.upper()}.AppImage"
    subprocess.run(["curl", "-sL", "-o", ai, url], check=True); os.chmod(ai, 0o755)
    subprocess.run([ai, "--appimage-extract"], cwd=d, check=True, capture_output=True)
    return os.path.exists(ORCA_APP)


def trancher_orca(chemin_3mf):
    """Tranche le 3MF tel quel. Retourne dict(ok, temps, grammes, avertissement, erreur).
    Machine Bambu Lab + Bambu Studio installé : tranché par Bambu Studio (le logiciel que l'utilisateur ouvrira)."""
    import subprocess, re as _re
    try:
        import lc3d_bambu as LB
        if "bambu" in (MACHINE.get("profil", PROFIL_MACHINE) + MACHINE.get("nom", "")).lower() and LB.disponible():
            r = LB.trancher(chemin_3mf); r.pop("gcode_cfg", None); r["logiciel"] = "Bambu Studio"; return r
    except Exception:
        pass
    if not os.path.exists(ORCA_APP):
        return dict(ok=None, erreur="OrcaSlicer non installé (lc3d.py orca-installer)")
    out = tempfile.mkdtemp()
    try:
        p = subprocess.run([ORCA_APP, "--slice", "0", "--outputdir", out, chemin_3mf], capture_output=True, text=True, timeout=600)
        txt = (p.stdout or "") + (p.stderr or "")
        res_ = {}
        try: res_ = json.load(open(os.path.join(out, "result.json")))
        except Exception: pass
        g = glob.glob(os.path.join(out, "*.gcode"))
        if p.returncode != 0 or not g:
            lignes = [l.strip() for l in txt.splitlines() if l.strip() and "found error" not in l and not l.startswith("[")]
            return dict(ok=False, erreur=" / ".join(lignes[-3:])[:400] or res_.get("error_string") or f"code {p.returncode}")
        brut = open(g[0], errors="ignore").read(); tete = brut[:200000] + brut[-300000:]
        t = _re.search(r"total estimated time: ([^;\n]+)", tete) or _re.search(r"estimated printing time \(normal mode\) = ([^\n]+)", tete); gr = _re.search(r"filament used \[g\] = ([\d.]+)", tete)
        av = "; ".join(x.get("warning_message", "") for x in res_.get("sliced_plates", []) if x.get("warning_message"))
        return dict(ok=True, temps=t.group(1).strip() if t else None, grammes=float(gr.group(1)) if gr else None, avertissement=av or None, logiciel="OrcaSlicer")
    except subprocess.TimeoutExpired:
        return dict(ok=False, erreur="OrcaSlicer : délai dépassé")
    finally:
        import shutil; shutil.rmtree(out, ignore_errors=True)


# --- Coût à l'unité (filament + électricité + usure), à partir du tranchage réel
COUTS = dict(filament_kg={"PETG": 25.0, "PLA": 22.0, "TPU": 35.0, "ABS": 25.0, "ASA": 30.0, "PA": 45.0, "PC": 40.0, "PA-CF": 70.0, "PLA-CF": 35.0, "PETG-CF": 40.0},
             kwh=0.08, puissance_kw=0.15, usure_heure=0.10, devise="$ CA")   # Québec : ~0,08 $/kWh; P2S ~150 W en moyenne


def _heures(t):
    import re as _re
    if not t: return None
    h = sum(float(n) * {"d": 24, "h": 1, "m": 1 / 60, "s": 1 / 3600}[u] for n, u in _re.findall(r"([\d.]+)\s*([dhms])", t))
    return h or None


def cout_unitaire(grammes, temps, materiau="PETG"):
    if grammes is None: return None
    h = _heures(temps) or 0.0
    try: i_ = normaliser_materiau(materiau or "PETG"); cles = (i_["nom"], i_["type"], i_["famille"])
    except ValueError: cles = ((materiau or "PETG").split()[0].upper(),)
    mat = next((COUTS["filament_kg"][k] for k in cles if k in COUTS["filament_kg"]), 25.0)
    c_fil = grammes / 1000 * mat; c_el = h * COUTS["puissance_kw"] * COUTS["kwh"]; c_us = h * COUTS["usure_heure"]
    return dict(total=round(c_fil + c_el + c_us, 2), filament=round(c_fil, 2), electricite=round(c_el, 2), usure=round(c_us, 2), heures=round(h, 2), devise=COUTS["devise"])


# --- Multi-filaments sur Bambu (AMS) : modèle de réglages ENREGISTRÉ PAR BAMBU STUDIO (2 filaments), généralisé à n
FICHIER_MODELE_MULTI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modele_multi_p2s.json")
_PAR_FILAMENT_SPECIAUX = {"default_filament_colour", "extruder_ams_count", "filament_colour_type", "filament_is_mixed", "filament_multi_colour",
                          "filament_nozzle_map", "filament_volume_map", "filament_ids", "filament_colour", "enable_pressure_advance", "pressure_advance",
                          "first_x_layer_part_fan_speed", "ironing_fan_speed", "overhang_threshold_participating_cooling", "enable_overhang_bridge_fan",
                          "filament_change_length_nc", "pre_start_fan_time"}
_COULEURS_FIL = ["#E2702A", "#2B2F33", "#F2F0EA", "#2C6CB0", "#5A8A3A", "#C0392B", "#8E44AD", "#F1C40F"]


def cfg_multi_bambu(materiaux):
    ref = json.load(open(FICHIER_MODELE_MULTI)); P = profils(); n = len(materiaux)
    noms = []
    for m in materiaux:
        i_ = normaliser_materiau(m); n_ = PROFIL_FILAMENT.get(i_["nom"]) or PROFIL_FILAMENT.get(i_["type"])
        if not n_: raise ValueError(f"matériau {i_['nom']} : pas de profil P2S connu sans Bambu Studio — pas de remplacement par un autre matériau")
        noms.append(n_)
    profs = [P.get(nm, {}) for nm in noms]
    cles_fil = set().union(*[set(p) for p in P.values() if p.get("_categorie") == "filament" or "filament_type" in p])
    cfg = dict(ref)
    for k, v in ref.items():
        if not isinstance(v, list) or len(v) < 2 or len(v) % 2: continue
        if k in ("flush_volumes_matrix", "flush_volumes_vector", "start_end_points", "nozzle_type"): continue
        if not (k in cles_fil or k.startswith("filament_") or k in _PAR_FILAMENT_SPECIAUX): continue
        g = len(v) // 2; out = []
        for j, pr in enumerate(profs):
            if k == "filament_self_index": bloc = [str(j + 1)] * g
            elif k in ("filament_colour", "filament_multi_colour"): bloc = [_COULEURS_FIL[j % len(_COULEURS_FIL)]] * g
            elif k == "filament_ids": bloc = [str(pr.get("filament_id", v[0]))] * g
            elif k == "filament_nozzle_map": bloc = [v[0] if j == 0 else v[-1]] * g
            elif k in pr:
                pv = pr[k] if isinstance(pr[k], list) else [pr[k]]
                pv = [str(x) for x in pv] or [v[0]]
                bloc = (pv + [pv[-1]] * g)[:g]
            else:
                bloc = v[:g]
            out += bloc
        cfg[k] = out
    cfg["filament_settings_id"] = noms
    cfg["flush_volumes_matrix"] = [("0" if i == j else "280") for i in range(n) for j in range(n)]
    cfg["flush_volumes_vector"] = ["140"] * (2 * n)
    cfg["filament_map"] = ["1"] * n
    return _completer_cfg(cfg)

# ----------------------------------------------------------------------------
# Rapport
# ----------------------------------------------------------------------------
def _non_prouve(logiciel=None):
    """Mêmes réserves, avec le nom de LA machine choisie et du logiciel qui a VRAIMENT tranché le fichier livré."""
    logi = logiciel or ("Bambu Studio" if _est_bambu() else "OrcaSlicer")
    return [x.replace("TA P2S", f"TA {MACHINE.get('nom', 'P2S')}").replace("donnés par OrcaSlicer", f"donnés par {logi}") for x in NON_PROUVE]


def rapport_md(R):
    L = [f"# Rapport LC3D — {R['projet']}", "", f"_Généré {R['date']} — {R['machine']}_", ""]
    L.append(f"**Verdict global : {R['verdict']}**  ({R['compte'][ECHEC]} ❌ · {R['compte'][AVERT]} ⚠️ · {R['compte'][OK]} ✅)")
    L.append("")
    if R.get("livre_avec_defauts"):
        L += ["## ❌ LIVRÉ AVEC DES DÉFAUTS (--livrer-quand-meme)", "", "Le zip a été fait malgré ces ❌ — à corriger ou à accepter en connaissance de cause :", ""] + \
             [f"- ❌ {x}" for x in R["livre_avec_defauts"]] + [""]
    if R.get("mode", "complet") != "complet":
        L += [f"> Mode **{R['mode']}**.", ""]
    if R.get("non_verifies"):
        L += ["## ⚠️ Non vérifié (trop lourd ou trop long — le run a continué)", ""] + [f"- {x}" for x in R["non_verifies"]] + [""]
    if (R.get("cotes_mesurees") or {}).get("accroches"):
        L += ["## Cotes MESURÉES sur le modèle livré", "", "| Clip | Accroche mesurée (mm) | Annoncée (mm) |", "|---|---|---|"] + \
             [f"| {k} | {v['mesuree']} | {v['annoncee']} |" for k, v in R["cotes_mesurees"]["accroches"].items()] + [""]
    for nom, P in R["pieces"].items():
        L += [f"## {nom}  ({P['materiau']}, ×{P['copies']}, rôle {P['role']})",
              f"Orientation d'impression : **{P['orientation']}** — {P['dims']} — ~{P['temps_min']:.0f} min, ~{P['filament_g']:.0f} g par copie (estimation, le slicer fait foi)", "",
              "| | Vérification | Détail | Quoi faire |", "|---|---|---|---|"]
        for r in P["resultats"]:
            L.append(f"| {r['statut']} | {r['verif']} | {r['detail']}" + (f" — lieux : {r['lieux'][:3]}" if r.get('lieux') else "") + f" | {r.get('conseil', '')} |")
        L.append("")
    if R.get("assemblage"):
        L += ["## Assemblage", "", "| | Vérification | Détail | Quoi faire |", "|---|---|---|---|"]
        for r in R["assemblage"]:
            L.append(f"| {r['statut']} | {r['verif']} | {r['detail']}" + (f" — lieu : {r['lieux']}" if r.get('lieux') else "") + f" | {r.get('conseil', '')} |")
        L.append("")
    if R.get("simulation"):
        S = R["simulation"]
        L += ["## 1 000 impressions simulées", "", f"**{S['reussite_pct']} %** fonctionnent (variations P2S : ±{S['hypotheses']['xy_sigma']} mm par surface, surfaces +{S['hypotheses']['xy_biais']} mm, trous −{S['hypotheses']['trou_biais']} mm).", "",
              "| Jeu | Nominal (mm) | Pire 1 % (mm) | Réussite |", "|---|---|---|---|"] + [f"| {d['nom']} | {d['nominal']} | {d['pire_1pct']} | {d['reussite_pct']} % |" for d in S["detail"]] + [""]
    if R.get("score_premiere_impression") is not None:
        L += [f"**Score première impression : {R['score_premiere_impression']} %**", ""]
    L += ["## Ce que ces vérifications NE prouvent PAS", ""] + [f"- {x}" for x in R.get("non_prouve", NON_PROUVE)] + [""]
    if R.get("erreurs"):
        L += ["## Erreurs", ""] + [f"- {e}" for e in R["erreurs"]]
    return "\n".join(L)


TRANCHER = True


def _note_piece(info):
    rs = info.get("resultats", [])
    return (sum(r["statut"] == ECHEC for r in rs), sum(r["statut"] == AVERT for r in rs))


def _auto_corriger_orientation(pc, brut, m, info, sortie, rendus):
    """Orientation « auto » qui laisse des ❌ : LC3D essaie lui-même les 3 orientations suivantes et garde la meilleure
    (moins de ❌, puis moins de ⚠️). Le rapport dit qu'il a corrigé. Rien ne change si l'orientation a été imposée."""
    if not (isinstance(pc.orientation, str) and pc.orientation.strip().lower() == "auto") or _note_piece(info)[0] == 0:
        return m, info
    import copy as _cp
    depart = (_note_piece(info), info.get("orientation"))
    meilleur = (depart[0], None)
    for c in choisir_orientation(brut, axe_flexion=pc.axe_flexion)[1:4]:
        p2 = _cp.copy(pc); p2.orientation = c["M"]; p2.mesh = brut.copy()
        try:
            _, i2 = verifier_piece(p2, None, False)
        except Exception:
            continue
        n2 = _note_piece(i2)
        if n2 < meilleur[0]: meilleur = (n2, c)
        if n2[0] == 0 and n2[1] == 0: break
    if meilleur[1] is None:
        return m, info
    c = meilleur[1]
    pc.orientation = c["M"]; pc.mesh = brut.copy()
    m, info = verifier_piece(pc, sortie, rendus)
    info["orientation"] = c["nom"]
    info["resultats"].insert(0, res("Orientation corrigée automatiquement", INFO,
        f"« {depart[1]} » laissait {depart[0][0]} ❌ / {depart[0][1]} ⚠️ → « {c['nom']} » : {meilleur[0][0]} ❌ / {meilleur[0][1]} ⚠️"))
    return m, info


def verifier_piece(piece: Piece, sortie=None, rendus=True):
    t0 = time.time()
    m = piece.mesh if piece.mesh is not None else vers_mesh(piece.forme)
    m.merge_vertices(); m.update_faces(m.nondegenerate_faces()) if hasattr(m, "nondegenerate_faces") else None
    if piece.importee is None:      # forme donnée en maillage (STL/3MF de tiers) = pièce importée
        piece.importee = isinstance(piece.forme, (trimesh.Trimesh, trimesh.Scene))
    fusion_note = None
    m_modele = m.copy()             # repère du modèle (les mesures 3D d'épaisseur ne dépendent pas de l'orientation)
    if piece.importee:              # corps qui se chevauchent sans être fusionnés : on fusionne AVANT de mesurer (comme le slicer)
        m2, n_f = _fusionner_corps(m)
        if n_f: m = m2; fusion_note = n_f
    orient_nom = "telle quelle"; Mo = np.eye(4)
    _ALIAS_OR = {"retourner": ((1, 0, 0), 180), "retournee": ((1, 0, 0), 180), "retournée": ((1, 0, 0), 180), "a l'envers": ((1, 0, 0), 180),
                 "à l'envers": ((1, 0, 0), 180), "dessus dessous": ((1, 0, 0), 180), "sur le dos": ((1, 0, 0), 180), "debout": "telle",
                 "couche": ((1, 0, 0), 90), "couché": ((1, 0, 0), 90), "couchee": ((1, 0, 0), 90), "couchée": ((1, 0, 0), 90)}
    if isinstance(piece.orientation, str) and piece.orientation.strip().lower() in _ALIAS_OR:
        piece.orientation = _ALIAS_OR[piece.orientation.strip().lower()]
    if isinstance(piece.orientation, str) and piece.orientation.strip().lower() not in ("auto", "telle", "telle quelle", "tel quel"):
        raise ValueError(f"orientation « {piece.orientation} » inconnue pour {piece.nom} : valeurs permises « auto » (LC3D choisit), "
                         f"« telle » (comme modélisée), (axe, angle_deg) ex. ((1, 0, 0), 90), ou une matrice 4×4.")
    if isinstance(piece.orientation, str) and piece.orientation.strip().lower() == "auto":
        choix = choisir_orientation(m, axe_flexion=piece.axe_flexion)
        Mo = choix[0]["M"]; orient_nom = choix[0]["nom"]
    elif isinstance(piece.orientation, tuple):
        axe, ang = piece.orientation
        Mo = trimesh.transformations.rotation_matrix(math.radians(ang), axe); orient_nom = f"rotation {ang}° autour de {axe}"
    elif piece.orientation is not None and not isinstance(piece.orientation, str):
        Mo = np.asarray(piece.orientation, float); orient_nom = "matrice donnée"
    m.apply_transform(Mo)
    axe_imprime = None if piece.axe_flexion is None else tuple(Mo[:3, :3] @ np.asarray(piece.axe_flexion, float))
    m = poser_sur_plateau(m)
    R = []
    if fusion_note:
        R.append(res("Corps fusionnés (fichier de tiers)", INFO, f"{fusion_note + 1} corps qui se chevauchaient fusionnés avant les mesures (le slicer fait pareil)"))
    R += verif_integrite(m, bool(piece.importee))
    R += verif_corps(m, piece)
    R += verif_lit(m)
    R += verif_materiau(piece)
    def _murs():
        ma = affiner(m, RAPIDE["affiner_faces"]) if RAPIDE["actif"] else affiner(m)
        ep, fe, pe, pf = epaisseurs_par_face(ma, RAPIDE["rayons_faces"]) if RAPIDE["actif"] else epaisseurs_par_face(ma)
        r_ = verif_epaisseurs(ma, piece, ep, fe, pe, pf)
        try: r_ += verif_becs_detectes(ma, ep, piece)
        except Exception: pass
        return ma, ep, fe, pe, pf, r_
    try:
        ma, ep, fe, pe, pf, r_ = garde(f"Murs et fentes de {piece.nom}", _murs)
        R += r_
    except NonVerifie as e:
        R.append(res_non_verifie("Épaisseur des murs et fentes", str(e)))
        ma = m; ep = fe = pe = pf = np.full(len(m.faces), np.nan)
    ep = np.where(pe <= PARALLELE, ep, np.nan); fe = np.where(pf <= PARALLELE, fe, np.nan)   # cartes : vrais murs/fentes seulement
    s, surpl = verif_surplombs(ma); R += s
    try:
        A, r_ = garde(f"Couches de {piece.nom}", lambda: (lambda A_: (A_, verif_couches(m, piece, A_)))(
            analyse_couches(m, nb_max=RAPIDE["couches_max"]) if RAPIDE["actif"] else analyse_couches(m)))
        R += r_
    except NonVerifie as e:
        R.append(res_non_verifie("Analyse couche par couche (îlots, ponts, porte-à-faux, détails fins)", str(e)))
        vol_ = float(m.volume) if m.is_watertight else 0.0
        A = dict(temps_min=round(vol_ / 1000 * 1.2, 0), volume_extrude_mm3=round(vol_ * 0.45, 0), hauteur=round(float(m.extents[2]), 2),
                 contact_plateau_mm2=0.0, flottants=[], porte_a_faux=[], ponts=[], fins=[])
    A["base_min_mm"] = A.get("base_min_mm")
    try:
        R += garde(f"Détails 3D de {piece.nom}", verif_details_3d, m_modele, piece)
    except NonVerifie as e:
        R.append(res_non_verifie("Détails fins en 3D (crêtes, sommets de dent)", str(e)))
    except Exception as e:
        R.append(res("Détails fins en 3D (crêtes, sommets de dent, nervures)", AVERT, f"non mesuré : {type(e).__name__}: {e}"))
    info_bordure = besoin_bordure(m)
    R += verif_flexion(axe_imprime, piece.role)
    mat = proprietes_materiau(piece.materiau)
    grammes = A["volume_extrude_mm3"] / 1000 * mat["rho"]
    if TRANCHER:
        try:
            rt, t = verif_tranchage(m, piece); R += rt
            if t.get("ok"):
                A["temps_min"] = t["temps_min"] or A["temps_min"]; grammes = t["filament_g"] or grammes
        except Exception as e:
            R.append(res("Tranchage réel", AVERT, f"impossible : {e}"))
    info = dict(materiau=piece.materiau, copies=piece.copies, role=piece.role, orientation=orient_nom,
                dims=f"{m.extents[0]:.1f} × {m.extents[1]:.1f} × {m.extents[2]:.1f} mm",
                temps_min=A["temps_min"], filament_g=round(grammes, 1), resultats=R, duree_s=round(time.time() - t0, 1))
    if info_bordure:
        info["bordure"] = info_bordure
        R.append(res("Bordure (brim) automatique", INFO, f"hauteur / plus petite largeur de base = {info_bordure['ratio']:.2f} > {SEUIL_BORDURE} : "
                     f"bordure de {info_bordure['largeur_mm']:.0f} mm mise d'office dans le 3MF livré (réglage de CETTE pièce)"))
    if sortie and rendus:
        os.makedirs(sortie, exist_ok=True)
        try:
            info["planche"] = garde(f"Planche {piece.nom}", planche, ma, piece, surpl, ep, f"{piece.nom} — orientation d'impression : {orient_nom}", os.path.join(sortie, f"{piece.nom}_vues.png"), fe=fe)
            info["coupes"] = garde(f"Coupes {piece.nom}", coupes, m, os.path.join(sortie, f"{piece.nom}_coupes.png"), titre=f"{piece.nom} — coupes")
        except NonVerifie as e:
            info["planche_absente"] = str(e)
    return m, info


PLAN_EXEMPTE = {"actif": False}      # retour CAO d'un exemple du dépôt


def _plan_projet(chemin_modele):
    """plan.json à côté du modèle : ce que l'IA a compris de l'objet AVANT de dessiner (et son coup d'œil final)."""
    f = os.path.join(os.path.dirname(os.path.abspath(chemin_modele)), "plan.json")
    try:
        plan = json.load(open(f, encoding="utf-8"))
        return (plan if isinstance(plan, dict) else dict(_erreur="plan.json doit être un objet { … }")), f
    except FileNotFoundError: return None, f
    except Exception as e: return dict(_erreur=f"plan.json illisible : {e}"), f


def plan_manquant(plan, final=False):
    """Champs du plan qui manquent (vide = plan complet). final=True : le coup d'œil final est exigé aussi."""
    if plan is None: return ["plan.json absent"]
    if plan.get("_erreur"): return [plan["_erreur"]]
    manque = [k for k in ("objet", "usage", "dimensions", "design") if not str(plan.get(k, "")).strip()]
    refs = plan.get("references") or []
    if not isinstance(refs, list) or len([r for r in refs if str(r).strip()]) < 2: manque.append("references (au moins 2 vrais produits ou modèles)")
    if final and not str(plan.get("coup_oeil", "")).strip(): manque.append("coup_oeil (regarder les rendus et dire si ça ressemble au vrai objet)")
    return manque


def verif_plan(chemin_modele):
    """❌ si on veut livrer sans avoir compris l'objet (plan.json) — les exemples du dépôt en sont exemptés."""
    if os.path.basename(os.path.dirname(os.path.abspath(chemin_modele))) == "exemples" or PLAN_EXEMPTE["actif"]: return []
    plan, f = _plan_projet(chemin_modele)
    manque = plan_manquant(plan)
    if manque:
        return [res("Plan de l'objet (comprendre avant de dessiner)", ECHEC, "manque : " + ", ".join(manque),
                    conseil=f"Écrire {f} : objet, usage, dimensions réelles, references (vrais produits), design (forme, arrondis, proportions). Voir SKILL.md, étape 4.")]
    return [res("Plan de l'objet (comprendre avant de dessiner)", OK, f"{plan['objet']} — {len(plan['references'])} références")]


def verif_finition(m, piece, raison=None):
    """Finition et design : une pièce brute (arêtes vives partout, rien d'arrondi ni de chanfreiné) → ❌.
    Mesuré sur le maillage posé sur le plateau : arêtes convexes vives (> 57°) hors plateau vs arêtes adoucies (congés, chanfreins)."""
    if piece.role == "achetee" or getattr(piece, "importee", False): return []
    if float(m.extents.max()) < 15: return []
    try:
        ang = m.face_adjacency_angles; cvx = m.face_adjacency_convex; e = m.face_adjacency_edges; v = m.vertices
    except Exception:
        return []
    L = np.linalg.norm(v[e[:, 0]] - v[e[:, 1]], axis=1)
    z0 = float(m.bounds[0, 2]) + 0.3
    plateau = (v[e[:, 0], 2] < z0) & (v[e[:, 1], 2] < z0)
    Lv = float(L[cvx & (ang > 1.0) & ~plateau].sum())                  # arêtes vives
    Ld = float(L[cvx & (ang > 0.02) & (ang <= 1.0)].sum())             # congés et chanfreins (et formes rondes)
    nom = "Finition et design"
    if raison:
        return [res(nom, INFO, f"arêtes vives voulues : {raison}")]
    if Lv < 40:
        return [res(nom, OK, "aucune arête vive marquée : pièce finie (arrondis, chanfreins ou formes rondes)")]
    w, d, h = (float(x) for x in m.extents)
    P = 4 * h + 2 * (w + d)                       # arêtes de la boîte englobante, sans celles du plateau
    part = Lv / P
    detail = f"{Lv:.0f} mm d'arêtes vives (≈ {100 * part:.0f} % du tour de la pièce)"
    conseil = ("Arrondir les arêtes extérieures (a.arrondir(\"|Z\", 2), a.arrondir(\">Z\", 1)) ou les chanfreiner : une pièce brute a l'air "
               "pas finie et ses coins s'écrasent. Si une arête doit rester vive (joint, face d'appui), le dire dans plan.json : \"aretes_vives\".")
    if Ld < 0.05 * Lv:
        return [res(nom, ECHEC, "pièce brute, rien d'arrondi ni de chanfreiné — " + detail, valeur=round(part, 2), conseil=conseil)]
    if part > 2.0:
        return [res(nom, AVERT, "beaucoup d'arêtes vives — " + detail, valeur=round(part, 2), conseil=conseil)]
    return [res(nom, OK, "arêtes finies — " + detail, valeur=round(part, 2))]


def verif_sobriete(m, piece, seuil_plein=0.40, epaisseur_utile=6.0):
    """Bloc plein inutile : une pièce non porteuse dont le volume dépasse ~40 % de son enveloppe et qui garde un gros cœur
    plein (matière à plus de `epaisseur_utile`/2 mm de toute surface) → ⚠️ avec le gain en grammes si on l'évide (coque de 3 mm)."""
    if piece.role in ("structure", "flexible", "achetee") or getattr(piece, "importee", False) or not m.is_watertight: return []
    V = float(m.volume); env = float(np.prod(m.extents))
    if V < 15000 or env <= 0 or V / env < seuil_plein: return []        # < 15 cm³ : sans enjeu
    pas = min(1.5, max(0.8, float(m.extents.max()) / 150))      # voxel fin : une plaque de 4 mm n'est pas un « bloc plein »
    try:
        vx = m.voxelized(pas).fill()
    except Exception:
        return []
    from scipy import ndimage
    dist = ndimage.distance_transform_edt(np.pad(vx.matrix, 1)) * pas      # bordure vide : sinon le bord compte comme « loin de la surface »
    coeur = float((dist > epaisseur_utile / 2 + 3.0 + pas).sum()) * pas ** 3      # + 1 voxel : la surface voxelisée déborde         # ce qu'une coque de 3 mm + remplissage laisserait creux
    if coeur < 0.15 * V: return []
    rho = proprietes_materiau(piece.materiau)["rho"]
    gain = coeur / 1000 * rho * MACHINE["remplissage"]          # le cœur est imprimé au remplissage : c'est ce qu'on économise
    if gain < 5: return []
    return [res("Sobriété (matière inutile)", AVERT, f"bloc plein : {V / 1000:.0f} cm³ pour une enveloppe de {env / 1000:.0f} cm³ ({100 * V / env:.0f} %), "
                f"cœur plein de ≈ {coeur / 1000:.0f} cm³ sans rôle de structure → ≈ {gain:.0f} g à gagner en évidant",
                valeur=round(gain, 1), conseil="Évider (coque 3 mm + nervures), ou alléger par des poches; si la masse est voulue (lest, rigidité), déclarer role=\"structure\".")]


SEUIL_BORDURE = 2.5       # hauteur / plus petite largeur de la base au-delà de laquelle la bordure est mise d'office (W, Q le font)


def besoin_bordure(m, seuil=None, largeur=5.0):
    """Pièce haute sur une base étroite (posée pour l'impression) : dict(ratio, base_mm, largeur_mm) si une bordure est nécessaire.
    Base = première couche (coupe à 0,1 mm) ; largeur = plus petit côté du rectangle minimal qui l'entoure."""
    seuil = SEUIL_BORDURE if seuil is None else seuil
    try:
        z0 = float(m.bounds[0, 2]); h = float(m.extents[2])
        P = _polys_section(m, z0 + min(0.1, h / 2))
        if P is None or P.area <= 0: return None
        rr = P.convex_hull.minimum_rotated_rectangle
        xs, ys = rr.exterior.coords.xy
        cotes = [math.dist((xs[k], ys[k]), (xs[k + 1], ys[k + 1])) for k in range(4)]
        b = max(min(cotes), 0.1)
        ratio = h / b
        if ratio > seuil or P.area < 50.0:
            return dict(ratio=round(ratio, 2), base_mm=round(b, 2), largeur_mm=largeur, contact_mm2=round(P.area, 1))
    except Exception:
        return None
    return None


def _charger_modele(chemin):
    spec = importlib.util.spec_from_file_location("modele", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["modele"] = mod
    sys.modules.setdefault("atelier3d", sys.modules[__name__]); sys.modules.setdefault("lc3d", sys.modules[__name__])
    spec.loader.exec_module(mod)
    return mod


PARAMS_STUDIO = dict(valeurs={}, pieces={}, aide={})     # PARAMS du modèle en cours (éditeur du Studio)


def _noter_params(mod, p):
    PARAMS_STUDIO["valeurs"] = {k: v for k, v in p.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    PARAMS_STUDIO["pieces"] = dict(getattr(mod, "PARAMS_PIECES", {}) or {})
    PARAMS_STUDIO["aide"] = dict(getattr(mod, "PARAMS_AIDE", {}) or {})


def mesures_piece(m):
    """Cotes principales d'une pièce, dans son repère : hauteur, Ø ou L × l extérieur, intérieur et mur (coupe à mi-hauteur).
    Pour le bouton « Cotes » du Studio : [{t: texte, a: [x,y,z], b: [x,y,z]}]."""
    out = []
    try:
        (x0, y0, z0), (x1, y1, z1) = m.bounds
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        dec = max(dx, dy) * 0.12 + 2
        out.append(dict(t=f"{dz:.1f}", a=[x1 + dec, cy, z0], b=[x1 + dec, cy, z1]))
        zc = None; ext = intr = None
        for f in (0.5, 0.35, 0.65, 0.2, 0.8):
            sec = m.section(plane_origin=(cx, cy, z0 + dz * f), plane_normal=(0, 0, 1))
            if sec is None: continue
            pl, T = sec.to_2D()
            polys = [g for g in pl.polygons_full if g.area > 1]
            if polys: zc = z0 + dz * f; break
        if polys:
            P = max(polys, key=lambda g: g.area)
            ext = P.exterior; bx0, by0, bx1, by1 = P.bounds
            rond = abs(P.convex_hull.area - math.pi * ((bx1 - bx0) / 2) ** 2) / max(P.convex_hull.area, 1e-6) < 0.03 and abs((bx1 - bx0) - (by1 - by0)) < 0.3
            if rond: out.append(dict(t=f"Ø {dx:.1f}", a=[x0, cy, z0 - dec * 0.3], b=[x1, cy, z0 - dec * 0.3]))
            else:
                out.append(dict(t=f"{dx:.1f}", a=[x0, y0 - dec * 0.5, z0], b=[x1, y0 - dec * 0.5, z0]))
                out.append(dict(t=f"{dy:.1f}", a=[x0 - dec * 0.5, y0, z0], b=[x0 - dec * 0.5, y1, z0]))
            if P.interiors:
                from shapely.geometry import Polygon as _Pg
                I = max((_Pg(r) for r in P.interiors), key=lambda g: g.area); ix0, iy0, ix1, iy1 = I.bounds
                rond_i = abs(I.area - math.pi * ((ix1 - ix0) / 2) ** 2) / max(I.area, 1e-6) < 0.03
                w3 = lambda u, v: (np.asarray(T) @ np.array([u, v, 0.0, 1.0]))[:3]
                pts = np.array([w3(ix0, iy0), w3(ix1, iy0), w3(ix1, iy1), w3(ix0, iy1)])
                X0, Y0 = pts[:, 0].min(), pts[:, 1].min(); X1, Y1 = pts[:, 0].max(), pts[:, 1].max(); ym = (Y0 + Y1) / 2
                lab = f"Ø int {X1 - X0:.1f}" if rond_i else f"int {X1 - X0:.1f} × {Y1 - Y0:.1f}"
                out.append(dict(t=lab, a=[float(X0), float(ym), zc], b=[float(X1), float(ym), zc]))
                mur = min(X0 - x0, x1 - X1)
                if mur > 0.2: out.append(dict(t=f"mur {mur:.1f}", a=[float(x0), float(ym), zc], b=[float(X0), float(ym), zc]))
    except Exception:
        pass
    return [dict(t=c["t"], a=[round(float(v), 3) for v in c["a"]], b=[round(float(v), 3) for v in c["b"]]) for c in out]


def _parse_set(vals, base):
    p = dict(base)
    for kv in vals or []:
        k, v = kv.split("=", 1)
        try: v = json.loads(v)
        except Exception: pass
        p[k] = v
    return p


def executer(chemin_modele, sets=None, sortie=None, livrer_zip=None, rendus=True, format="3mf", extras=(), rapide=False, livrer_quand_meme=False):
    """Boucle d'auto-correction : exécute le modèle, vérifie tout, rend les images, écrit rapport.json/.md.
    rapide=True : vérifs essentielles à pas grossier (sans rendus, FEM, 1 000 simulations, tranchage) pour itérer en 1-2 min.
    livrer_quand_meme=True : le zip est livré même avec des ❌ (chaque ❌ écrit en tête du rapport).
    Code de sortie 0 = tout ✅/ℹ️, 1 = avertissements, 2 = échecs, 3 = le modèle plante."""
    global TRANCHER
    ancien = dict(rapide=RAPIDE["actif"], trancher=TRANCHER)
    RAPIDE["actif"] = bool(rapide)
    if rapide: TRANCHER = False; rendus = False
    NON_VERIFIES.clear(); annuler_exigences()
    try:
        return _executer(chemin_modele, sets, sortie, livrer_zip, rendus, format, extras, bool(rapide), livrer_quand_meme)
    finally:
        RAPIDE["actif"] = ancien["rapide"]; TRANCHER = ancien["trancher"]; annuler_exigences()


def _executer(chemin_modele, sets, sortie, livrer_zip, rendus, format, extras, rapide, livrer_quand_meme):
    sortie = sortie or os.path.join(os.path.dirname(os.path.abspath(chemin_modele)), "sortie")
    os.makedirs(sortie, exist_ok=True)
    R = dict(projet=livrer_zip or os.path.splitext(os.path.basename(chemin_modele))[0].replace("retour_", ""), date=time.strftime("%Y-%m-%d %H:%M"),
             machine=f"{MACHINE['nom']}, buse {MACHINE['buse']}, couche {MACHINE['couche']}", pieces={}, erreurs=[])
    try:
        mod = _charger_modele(chemin_modele)
        p = _parse_set(sets, getattr(mod, "PARAMS", {}))
        _noter_params(mod, p)
        R["params"] = p
        R["mode"] = "rapide (vérifs essentielles, pas grossier — faire le run complet avant de livrer)" if rapide else "complet"
        R["consigne"] = appliquer_exigences(getattr(mod, "EXIGENCES", None) or {})
        JOURNAL.clear()
        brut = mod.build(p)
        pieces = {}
        for nom, v in (brut.items() if isinstance(brut, dict) else [(x.nom, x) for x in brut]):
            pieces[nom] = v if isinstance(v, Piece) else Piece(nom, v)
            pieces[nom].nom = nom
    except Exception as e:
        R["erreurs"].append(f"Le modèle plante : {type(e).__name__}: {e}")
        R["trace"] = traceback.format_exc()[-3000:]
        R["verdict"] = "❌ le modèle ne s'exécute pas"; R["compte"] = {OK: 0, AVERT: 0, ECHEC: 1}
        json.dump(R, open(os.path.join(sortie, "rapport.json"), "w"), ensure_ascii=False, indent=1, default=str)
        try: open(os.path.join(sortie, "rapport.md"), "w").write(rapport_md(R))
        except Exception: pass
        print(json.dumps(dict(verdict=R["verdict"], erreur=R["erreurs"][0], trace=R["trace"]), ensure_ascii=False, indent=1))
        return 3
    meshes_poses, brut_meshes = {}, {}
    pre = {}
    for nom, pc in list(pieces.items()):      # solide CAO invalide : ❌ (ou ⚠️ si shape.fix() le répare)
        try:
            rv, f_ = verif_validite(nom, pc.forme, list(JOURNAL))
            if rv: pre[nom] = rv; pc.forme = f_
        except Exception:
            pass
    for nom, pc in list(pieces.items()):      # échelle aberrante (STEP en mètres…) : arrêt AVANT de mailler (sinon mémoire épuisée)
        try:
            b_ = boite_forme(pc.forme)
            if b_ is not None: controle_echelle(b_, nom)
        except ValueError as e:
            R["erreurs"].append(str(e)); pieces.pop(nom)
        except Exception:
            pass
    for nom, pc in pieces.items():
        if pc.role == "achetee":   # vis, roulement, pile... : sert aux vérifs d'assemblage, jamais imprimée ni livrée
            try:
                brut_meshes[nom] = vers_mesh(pc.forme); R.setdefault("achetees", []).append(nom)
            except Exception as e:
                R["erreurs"].append(f"{nom} (pièce achetée) : {type(e).__name__}: {e}")
            continue
        try:
            brut_meshes[nom] = vers_mesh(pc.forme)
            pc.mesh = brut_meshes[nom].copy()
            m, info = verifier_piece(pc, sortie, rendus)
            m, info = _auto_corriger_orientation(pc, brut_meshes[nom], m, info, sortie, rendus)
            info["resultats"] = pre.get(nom, []) + info["resultats"]
            meshes_poses[nom] = m; R["pieces"][nom] = info
            for f in ("stl",):
                m.export(os.path.join(sortie, f"{nom}.stl"))
        except Exception as e:
            R["erreurs"].append(f"{nom} : {type(e).__name__}: {e}")
            R.setdefault("trace_" + nom, traceback.format_exc()[-2000:])
    A = None
    if hasattr(mod, "assembly"):
        try:
            A = mod.assembly(p, pieces)
            A._materiaux = {n: pc.materiau for n, pc in pieces.items()}
            res_a, en_place = verif_assemblage(brut_meshes, A)
            try:     # assemblage.3mf natif : toutes les pièces en position montée, même repère (pièces achetées : COMMERCE_<nom>)
                _sc = trimesh.Scene()
                for _n, _m in en_place.items():   # le nom d'OBJET 3MF vient de geom_name (node_name ne va que dans partnumber)
                    _nm = ("COMMERCE_" + _n) if pieces[_n].role == "achetee" and not _n.upper().startswith("COMMERCE_") else _n
                    _sc.add_geometry(_m, node_name=_nm, geom_name=_nm)
                _sc.export(os.path.join(sortie, "assemblage.3mf")); R["assemblage_3mf"] = os.path.join(sortie, "assemblage.3mf")
            except Exception as _e:
                R["erreurs"].append(f"assemblage.3mf : {type(_e).__name__}: {_e}")
            res_a += verif_mecanique(brut_meshes, pieces, A, en_place, R["pieces"])
            if rapide:
                if getattr(A, "charges", None): res_a.append(res("Résistance (éléments finis)", INFO, "sautée en mode rapide : faire le run complet"))
            else:
                res_a += garde_res("Résistance (éléments finis)", verif_resistance, pieces, A, sortie if rendus else None, etat=A, delai_s=max(GARDE["delai_s"], 300))
            res_a += verif_environnement(pieces, A)
            if getattr(A, "images_resistance", None): R["images_resistance"] = A.images_resistance
            R["assemblage"] = res_a
            if rendus:
                for cle_, f_, a_ in (("planche_assemblage", planche_assemblage, (en_place, os.path.join(sortie, "assemblage.png"))),
                                     ("planche_montage", planche_montage, (brut_meshes, A, os.path.join(sortie, "montage.png"))),
                                     ("planche_mouvements", planche_mouvements, (brut_meshes, A, os.path.join(sortie, "mouvements.png")))):
                    try: R[cle_] = garde(cle_, f_, *a_)
                    except NonVerifie as e_: R["erreurs"].append(f"Image {cle_} non faite ({e_})")
            if any(r["verif"].startswith("Montage") and r["statut"] == ECHEC for r in res_a):
                try: o = garde("Recherche d'un ordre de montage", chercher_ordre, brut_meshes, A, en_place)
                except NonVerifie as e_: o = None; res_a.append(res_non_verifie("Recherche d'un ordre de montage", str(e_)))
                if o and not o["bloque"]:
                    res_a.append(res("Ordre de montage trouvé par LC3D", INFO, " → ".join(f"{n} {d}" for n, d in o["ordre"]),
                                     conseil="Cet ordre (en ligne droite) entre sans rien toucher : l'utiliser dans assembly() si le produit le permet."))
                elif o:
                    res_a.append(res("Ordre de montage", ECHEC, f"aucun ordre en ligne droite ne marche pour : {', '.join(o['bloque'])}" + (f" (possible jusqu'à : {' → '.join(n for n, _ in o['ordre'])})" if o['ordre'] else ""),
                                     conseil="Il faut un pivot, une pièce flexible (clip calculé) ou couper une pièce en deux."))
            sim = None if rapide else simulation_impressions(mesures_depuis_resultats(res_a))
            if sim:
                R["simulation"] = sim
                faible = sim["detail"][0]
                st = OK if sim["reussite_pct"] >= 95 else (AVERT if sim["reussite_pct"] >= 80 else ECHEC)
                res_a.append(res("1 000 impressions simulées (tolérances P2S)", st,
                                 f"{sim['reussite_pct']} % des impressions fonctionnent; point le plus faible : {faible['nom']} ({faible['reussite_pct']} %, nominal {faible['nominal']} mm, pire 1 % : {faible['pire_1pct']} mm)",
                                 conseil=None if st == OK else "Ouvrir un peu ce jeu (ou réduire cette interférence) pour encaisser les variations d'impression."))
        except Exception as e:
            R["erreurs"].append(f"Assemblage : {type(e).__name__}: {e}")
            R["trace_assemblage"] = traceback.format_exc()[-2000:]
    if A is None and getattr(mod, "ENVIRONNEMENT", None):      # pièce seule : ENVIRONNEMENT = dict(temperature=65, ou="lave-vaisselle", soleil=False)
        try:
            A_env = Assemblage(); A_env.environnement(**mod.ENVIRONNEMENT)
            R["assemblage"] = R.get("assemblage", []) + verif_environnement(pieces, A_env)
        except Exception as e:
            R["erreurs"].append(f"Environnement : {type(e).__name__}: {e}")
    try:
        se = verif_securite_enfant(pieces, brut_meshes, getattr(mod, "USAGE", None), A)
        if se: R["assemblage"] = R.get("assemblage", []) + se
    except Exception as e:
        R["erreurs"].append(f"Sécurité enfant : {type(e).__name__}: {e}")
    regles = verif_regles(p, A)
    if regles:
        R["assemblage"] = R.get("assemblage", []) + regles
    for nom, pc in pieces.items():           # sobriété : bloc plein inutile → ⚠️ avec le gain en grammes
        if nom in meshes_poses and nom in R["pieces"]:
            try: R["pieces"][nom]["resultats"] += garde(f"Sobriété {nom}", verif_sobriete, meshes_poses[nom], pc)
            except Exception: pass
    _plan, _ = _plan_projet(chemin_modele)
    _vives = (_plan or {}).get("aretes_vives") if isinstance(_plan, dict) else None
    for nom, pc in pieces.items():           # finition et design : pièce brute → ❌
        if nom in meshes_poses and nom in R["pieces"]:
            try: R["pieces"][nom]["resultats"] += verif_finition(meshes_poses[nom], pc, (_vives.get(nom) if isinstance(_vives, dict) else _vives))
            except Exception: pass
    if livrer_zip:                           # livrer = avoir compris l'objet d'abord (plan.json)
        R["assemblage"] = verif_plan(chemin_modele) + R.get("assemblage", [])
    if A is not None and getattr(A, "_consigne", None): R["consigne"] = R.get("consigne", []) + A._consigne
    if A is not None and getattr(A, "accroches_mesurees", None): R["cotes_mesurees"] = dict(accroches=A.accroches_mesurees)
    if R.get("consigne"): R["assemblage"] = R["consigne"] + R.get("assemblage", [])
    if NON_VERIFIES: R["non_verifies"] = [f"{n} : {r}" for n, r in NON_VERIFIES]
    tous = [r for P in R["pieces"].values() for r in P["resultats"]] + R.get("assemblage", [])
    R["compte"] = {s: sum(r["statut"] == s for r in tous) for s in (OK, AVERT, ECHEC)}
    if R["erreurs"]: R["compte"][ECHEC] += len(R["erreurs"])
    R["verdict"] = ECHEC + " à corriger" if R["compte"][ECHEC] else (AVERT + " à revoir" if R["compte"][AVERT] else OK + " prêt (sous réserve de la revue humaine)")
    R["non_prouve"] = _non_prouve()
    R["score_premiere_impression"] = 0 if R["compte"][ECHEC] else (R.get("simulation") or {}).get("reussite_pct", None)
    R["a_corriger"] = [dict(piece=n, **r) for n, P in R["pieces"].items() for r in P["resultats"] if r["statut"] in (ECHEC, AVERT)] + \
                      [dict(piece="assemblage", **r) for r in R.get("assemblage", []) if r["statut"] in (ECHEC, AVERT)]
    # --- visuels (bloc 5)
    if rendus and brut_meshes:
        try:
            poses = A.poses if A is not None else {}
            R["visionneuse"] = visionneuse(os.path.join(sortie, "visionneuse.html"), brut_meshes, poses, getattr(A, "mouvements", []) if A is not None else [],
                                           R["projet"].replace("_", " "), R, achetees=R.get("achetees", []))["chemin"]
            places = {}
            for n, m in brut_meshes.items():
                mm = m.copy(); mm.apply_transform(poses.get(n, np.eye(4))); places[n] = mm
            ens = trimesh.util.concatenate(list(places.values()))
            R["grandeur_reelle"] = grandeur_reelle(ens, os.path.join(sortie, "grandeur_reelle.png"))
            if "photo" in extras:
                ph = rendu_photo(places, os.path.join(sortie, "photo.png"), couleurs=getattr(mod, "COULEURS", None), achetees=R.get("achetees", []), **(dict(taille=(1200, 900), echantillons=40) if "studio" in extras else {}))
                if ph.get("ok"): R["photo"] = ph["image"]
                else: R["erreurs"].append(f"Photo : {ph.get('note') or ph.get('erreur')}")
            if "plans" in extras:
                for n, pc in pieces.items():
                    if pc.role != "achetee" and not isinstance(pc.forme, trimesh.Trimesh):
                        R.setdefault("plans", []).append(plan_cote(pc.forme, os.path.join(sortie, f"plan_{n}.pdf"), n, materiau=pc.materiau))
            if "notice" in extras and A is not None and A.sequence:
                R["notice"] = notice_montage(brut_meshes, A, os.path.join(sortie, "notice_montage.pdf"), f"Notice — {R['projet']}")
        except Exception as e:
            R["erreurs"].append(f"Visuels : {type(e).__name__}: {e}")
    json.dump(R, open(os.path.join(sortie, "rapport.json"), "w"), ensure_ascii=False, indent=1, default=str)
    open(os.path.join(sortie, "rapport.md"), "w").write(rapport_md(R))
    if livrer_zip and R["compte"][ECHEC] and livrer_quand_meme:
        R["livre_avec_defauts"] = [f"{x['piece']} · {x['verif']} : {x['detail']}" for x in R["a_corriger"] if x["statut"] == ECHEC] + list(R["erreurs"])
        open(os.path.join(sortie, "rapport.md"), "w").write(rapport_md(R))
    if livrer_zip and (not R["compte"][ECHEC] or livrer_quand_meme):
        try:
            livrer.note_multi = None
            mp_, pc_ = _grouper_imprime_monte(meshes_poses, brut_meshes, pieces)
            R["zip"] = livrer(mp_, pc_, sortie, livrer_zip, format, plateau_unique=getattr(mod, "PLATEAU_UNIQUE", False) or "plateau_unique" in extras,
                              couleurs=getattr(mod, "COULEURS", None))
            if getattr(livrer, "note_multi", None):
                R["assemblage"] = R.get("assemblage", []) + [res("Plateau multi-filaments", INFO, livrer.note_multi)]
        except ValueError as e:      # refus expliqué (matériau sans profil, trop de filaments…) : une ligne ❌ dans le rapport, pas de zip
            R["assemblage"] = R.get("assemblage", []) + [res("Fichier 3MF", ECHEC, str(e))]
            R["compte"][ECHEC] += 1; R["verdict"] = ECHEC + " à corriger"; R["score_premiere_impression"] = 0
            R["zip_refuse"] = "zip non créé : " + str(e)[:200]; livrer.orca = {}
            json.dump(R, open(os.path.join(sortie, "rapport.json"), "w"), ensure_ascii=False, indent=1, default=str)
            open(os.path.join(sortie, "rapport.md"), "w").write(rapport_md(R))
        orca = getattr(livrer, "orca", {})
        if orca:
            for n, o in orca.items():
                if o.get("ok"): o["cout"] = cout_unitaire(o.get("grammes"), o.get("temps"), pieces[n].materiau if n in pieces else "PETG")
            couts = [o["cout"]["total"] for o in orca.values() if o.get("cout")]
            if couts: R["cout_total"] = dict(total=round(sum(couts), 2), devise=COUTS["devise"], note="filament + électricité + usure, par exemplaire du produit")
            R["tranchage_orca"] = orca; ajout = []
            for n, o in orca.items():
                if o.get("ok") is None: continue
                st = OK if o["ok"] and not o.get("avertissement") else (AVERT if o["ok"] else ECHEC)
                ajout.append(res(f"Fichier livré tranché par {o.get('logiciel', 'OrcaSlicer')} : {n}", st,
                                 f"{o.get('temps')} · {o.get('grammes')} g" + (f" · coût {o['cout']['total']} {o['cout']['devise']}" if o.get("cout") else "") + (f" · ⚠ {o['avertissement']}" if o.get("avertissement") else "") if o["ok"] else f"refusé : {o['erreur']}",
                                 conseil=None if st == OK else "Le 3MF livré ne passe pas tel quel dans le slicer : corriger les réglages du fichier."))
            R["non_prouve"] = _non_prouve(next((o.get("logiciel") for o in orca.values() if o.get("logiciel")), None))
            R["assemblage"] = R.get("assemblage", []) + ajout
            for r in ajout: R["compte"][r["statut"]] = R["compte"].get(r["statut"], 0) + 1
            if any(r["statut"] == ECHEC for r in ajout) and livrer_quand_meme:
                R.setdefault("livre_avec_defauts", []).extend(f"{r['verif']} : {r['detail']}" for r in ajout if r["statut"] == ECHEC)
                R["verdict"] = ECHEC + " livré QUAND MÊME (défauts en tête du rapport)"; R["score_premiere_impression"] = 0
            elif any(r["statut"] == ECHEC for r in ajout):
                os.unlink(R["zip"]); R["zip_refuse"] = f"zip retiré : {next((o.get('logiciel') for o in orca.values() if o.get('ok') is False and o.get('logiciel')), 'le trancheur')} refuse un des fichiers"; R.pop("zip")
                R["verdict"] = ECHEC + " à corriger"; R["score_premiere_impression"] = 0
            elif any(r["statut"] == AVERT for r in ajout) and R["verdict"].startswith(OK):
                R["verdict"] = AVERT + " à revoir"
            json.dump(R, open(os.path.join(sortie, "rapport.json"), "w"), ensure_ascii=False, indent=1, default=str)
            open(os.path.join(sortie, "rapport.md"), "w").write(rapport_md(R))
    elif livrer_zip:
        R["zip_refuse"] = "zip non créé : il reste des ❌"
    if "studio" in extras and brut_meshes:
        try:
            R["studio"] = exporter_studio(sortie, brut_meshes, A, R, R["projet"].replace("_", " "), achetees=R.get("achetees", []))
            try:      # gestes rejouables + éditeur en temps réel, comme l'aperçu
                _sc = json.load(open(R["studio"]["scene"])); _sc["live"] = live_studio(mod, p)
                _sc["gestes"], _sc["nb_gestes"] = gestes_pour_studio()
                json.dump(_sc, open(R["studio"]["scene"], "w"), ensure_ascii=False, separators=(",", ":"))
            except Exception as e2:
                R["erreurs"].append(f"Studio (gestes) : {type(e2).__name__}: {e2}")
        except Exception as e:
            R["erreurs"].append(f"Studio : {type(e).__name__}: {e}")
    if livrer_zip and R.get("studio") and os.environ.get("LC3D_SANS_STUDIO") != "1":    # le Studio, toujours : la personne voit la pièce et le rapport
        try:
            mv = re.match(r"^(.*?)[_ -](v\d+)$", livrer_zip)
            projet_, version_ = (mv.group(1), mv.group(2)) if mv else (livrer_zip, "v1")
            etat_ = dict(feu="vert" if not R["compte"][ECHEC] else "rouge", verdict=R["verdict"], compte=R["compte"])
            ok_ = not R["compte"][ECHEC]
            envoi = studio_pousser(sortie, projet_.replace("_", " "), version_, etat_,
                                   "Vérifié — dernier coup d'œil avant « Prêt »" if ok_ else "Il reste des ❌ : je corrige",
                                   MACHINE["nom"], "verification" if ok_ else "correction")
            R["studio_lien"] = envoi["studio"]
        except Exception as e:
            R["studio_lien"] = None; R["studio_erreur"] = str(e)[:300]
    court = dict(verdict=R["verdict"], compte=R["compte"], score_premiere_impression=R["score_premiere_impression"], a_corriger=[{k: v for k, v in r.items() if k in ("piece", "statut", "verif", "detail", "conseil", "lieux")} for r in R["a_corriger"]],
                 images=[i for i in [P.get("planche") for P in R["pieces"].values()] + [R.get("planche_assemblage"), R.get("planche_montage"), R.get("planche_mouvements")] + R.get("images_resistance", []) if i], rapport=os.path.join(sortie, "rapport.md"),
                 zip=R.get("zip") or R.get("zip_refuse"), erreurs=R["erreurs"], visionneuse=R.get("visionneuse"), photo=R.get("photo"),
                 grandeur_reelle=R.get("grandeur_reelle"), plans=R.get("plans"), notice=R.get("notice"), studio=R.get("studio"))
    if R.get("studio_lien"):
        court["studio_lien"] = R["studio_lien"]
        court["a_faire"] = ("DONNE CE LIEN À LA PERSONNE MAINTENANT (son Studio : la pièce en 3D + le rapport). Puis regarde les images, "
                            "écris coup_oeil dans plan.json et pousse l'étape « pret » avant de donner le zip.")
    elif R.get("studio_erreur"):
        court["studio_erreur"] = R["studio_erreur"] + " — dis-le à la personne et donne-lui le zip et les images."
    print(json.dumps(court, ensure_ascii=False, indent=1, default=str))
    return 2 if R["compte"][ECHEC] else (1 if R["compte"][AVERT] else 0)



# --- Résistance sous charge (éléments finis, lc3d_resistance)
def _resistance(self, piece, fixe, charge, force, axe_couches=(0, 0, 1), titre=None):
    """La pièce est tenue par les faces dans la boîte `fixe` et poussée par `force` (N) sur les faces dans `charge`.
    Boîtes ((x0,y0,z0),(x1,y1,z1)) dans le repère de la pièce (avant placement). 10 N ≈ 1 kg."""
    self.__dict__.setdefault("charges", []).append(dict(piece=piece, fixe=fixe, charge=charge, force=force, axe_couches=axe_couches,
                                                         titre=titre or f"Résistance {piece}"))
    return self


Assemblage.resistance = _resistance


def verif_resistance(pieces, A, sortie=None):
    out = []
    for i, c in enumerate(getattr(A, "charges", [])):
        pc = pieces.get(c["piece"])
        if pc is None:
            out.append(res(c["titre"], ECHEC, f"pièce « {c['piece']} » introuvable")); continue
        try:
            import lc3d_resistance as LR
            img = os.path.join(sortie, f"resistance_{c['piece']}_{i}.png") if sortie else None
            r = LR.resistance(pc.forme, c["fixe"], c["charge"], c["force"], materiau=pc.materiau, axe_couches=c["axe_couches"], image=img, titre=c["titre"])
            st = {"✅": OK, "⚠️": AVERT, "❌": ECHEC}[r["statut"]]
            plein = pc.role in ("structure", "flexible")
            det = (f"{abs(np.linalg.norm(c['force'])):.0f} N → facteur de sécurité {r['facteur_securite']} (visé ≥ {LR.SECURITE_VISEE}); "
                   f"contrainte {r['contrainte_max_MPa']} MPa / {r['limite_plan_MPa']}, entre couches {r['traction_couches_MPa']} MPa / {r['limite_couches_MPa']}; "
                   f"plie de {r['deformation_max_mm']} mm; casse d'abord {r['casse_d_abord']}")
            if not plein and st == OK and r["facteur_securite"] < 4:
                st = AVERT; det += " — calcul fait en plein, mais la pièce est livrée à 20 % de remplissage"
            out.append(res(c["titre"], st, det, valeur=r["facteur_securite"], lieux=[r["point_faible"]] if st != OK else None,
                           conseil=None if st == OK else ("Mettre la pièce en role=\"structure\" (100 %)" if not plein else
                                                           "Épaissir près du point faible, ajouter un congé, ou tourner la pièce pour que la force ne tire pas entre les couches.")))
            if img: A.__dict__.setdefault("images_resistance", []).append(img)
        except Exception as e:
            out.append(res(c["titre"], AVERT, f"calcul impossible : {type(e).__name__}: {e}"))
    return out


# --- Agent casseur (partie automatique) : chaleur d'utilisation vs température de ramollissement du plastique
TEMP_RAMOLLISSEMENT = {"PLA": 55, "PETG": 70, "PCTG": 70, "ABS": 95, "ASA": 95, "PA": 120, "PC": 130, "TPU": 60,   # HDT approx. (°C, 0,45 MPa)
                       "PLA+": 55, "PLA Silk": 55, "PLA Matte": 55, "PLA-CF": 55, "PETG-CF": 75, "PET-CF": 80, "ASA-CF": 100, "ABS-GF": 100,
                       "PA-CF": 150, "PA-GF": 140, "PPA-CF": 200, "HIPS": 85, "TPU 85A-90A": 55}   # fiches techniques (Bambu, Polymaker) : ordres de grandeur


def _securite_enfant(self, age=3):
    """Jouet / objet pour enfant : vérifie petites pièces (cylindre 31,7 mm), aimants et arêtes vives de TOUTES les pièces."""
    self.usage_enfant = age; return self


def _environnement(self, temperature=25, ou="", soleil=False):
    """Où la pièce vit : ex. temperature=70, ou="voiture en été" ; soleil=True ajoute les UV (PLA/PETG jaunissent)."""
    self.__dict__["_env"] = dict(temperature=temperature, ou=ou, soleil=soleil); return self


Assemblage.environnement = _environnement
Assemblage.securite_enfant = _securite_enfant


# --- Jouets / jeunes enfants : gabarit des petites pièces (16 CFR 1501.4 et EN 71-1 § 8.2 : cylindre Ø 31,7 mm (1,25 po),
# profondeur 25,4 mm (1 po) d'un côté à 57,1 mm (2,25 po) de l'autre, fond incliné à 45°). Une pièce qui y entre ENTIÈREMENT, dans
# n'importe quelle orientation, sans être comprimée = danger d'étouffement : interdit sous 3 ans.
GABARIT_PETITES_PIECES = dict(d=31.7, prof_min=25.4, prof_max=57.1)


def _age_usage(usage):
    if usage is None: return None
    if isinstance(usage, (int, float)): return float(usage)
    u = str(usage).lower()
    m_ = re.search(r"(\d+(?:[.,]\d+)?)", u)
    if m_: return float(m_.group(1).replace(",", "."))
    if any(k in u for k in ("enfant", "jouet", "bebe", "bébé", "toy", "child")): return 3.0      # sans âge : prudence (< 3 ans)
    return None


def entre_dans_gabarit(m, n_dir=500):
    """True (+ orientation) si le maillage entre ENTIÈREMENT dans le cylindre des petites pièces (fond incliné compris)."""
    G = GABARIT_PETITES_PIECES; Rr = G["d"] / 2; mil = (G["prof_min"] + G["prof_max"]) / 2; pente = (G["prof_max"] - G["prof_min"]) / G["d"]
    try: V = m.convex_hull.vertices
    except Exception: V = m.vertices
    V = V - V.mean(0)
    if np.linalg.norm(m.extents) > G["prof_max"] + G["d"] + 1: return False, None      # trop grande dans tous les sens
    import shapely
    from shapely.geometry import MultiPoint
    k = np.arange(n_dir) + 0.5; phi = np.arccos(1 - 2 * k / n_dir); th = np.pi * (1 + 5 ** 0.5) * k
    dirs = np.c_[np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)]
    for d in dirs:
        a = np.cross(d, [1, 0, 0] if abs(d[0]) < 0.9 else [0, 1, 0]); a /= np.linalg.norm(a); b = np.cross(d, a)
        P = np.c_[V @ a, V @ b]; z = V @ d
        mp = MultiPoint(P)
        if shapely.minimum_bounding_radius(mp) > Rr - 1e-6: continue
        c = np.array(shapely.minimum_bounding_circle(mp).centroid.coords[0]); P = P - c
        z = z - z.max()                         # le haut de la pièce au ras du bord du cylindre
        if -z.min() <= G["prof_min"]: return True, tuple(np.round(d, 3))
        if -z.min() > G["prof_max"]: continue
        for ang in np.linspace(0, 2 * np.pi, 24, endpoint=False):     # le fond incliné : tourner la pièce autour de l'axe
            x = P[:, 0] * np.cos(ang) - P[:, 1] * np.sin(ang)
            if np.all(z + mil - pente * x >= -1e-6): return True, tuple(np.round(d, 3))
    return False, None


def aretes_vives(m, angle_min=60.0):
    """Arêtes saillantes : (longueur des arêtes « couteau » (dièdre > 120°), longueur des arêtes vives ≥ angle_min sans congé)."""
    try:
        ang = np.degrees(m.face_adjacency_angles); cvx = m.face_adjacency_convex
        L_ = np.linalg.norm(m.vertices[m.face_adjacency_edges[:, 0]] - m.vertices[m.face_adjacency_edges[:, 1]], axis=1)
        return float(L_[cvx & (ang > 120.0)].sum()), float(L_[cvx & (ang >= angle_min)].sum())
    except Exception:
        return 0.0, 0.0


def verif_securite_enfant(pieces, meshes, usage_global=None, A=None):
    """Vérif optionnelle (Piece(usage="enfant_moins_3"), USAGE = "enfant_moins_3" dans le modèle, ou A.securite_enfant(age=3))."""
    out = []
    usage_A = getattr(A, "usage_enfant", None) if A is not None else None
    for n, pc in pieces.items():
        age = _age_usage(pc.usage or usage_A or usage_global)
        if age is None or n not in meshes: continue
        m = meshes[n]
        entre, d = entre_dans_gabarit(m)
        if entre:
            st = ECHEC if age <= 3 else AVERT       # 3 ans compris : prudence (frères et sœurs plus jeunes), au-delà : étiquette obligatoire
            out.append(res(f"Sécurité enfant : petite pièce ({n})", st,
                           f"{n} ({_pt(m.extents)} mm) entre entièrement dans le cylindre des petites pièces Ø 31,7 × 25,4-57,1 mm "
                           f"(16 CFR 1501 / EN 71-1) — risque d'étouffement" + (" : INTERDIT pour les 3 ans et moins." if age <= 3 else " (étiquette « ne convient pas aux moins de 3 ans »)."),
                           conseil="Agrandir la pièce (> Ø 31,7 mm et > 57 mm de long dans tous les sens) ou la rendre INDÉTACHABLE (pièce unique), "
                                   "jamais une vis, bille, aimant ou capuchon séparable."))
        elif pc.role != "achetee":
            out.append(res(f"Sécurité enfant : petite pièce ({n})", OK, f"{n} n'entre pas dans le cylindre Ø 31,7 mm (testé dans 500 orientations, fond incliné compris)"))
        if pc.role == "achetee":
            if (pc.materiau or "").lower() == "neodyme" or "aimant" in n.lower():
                out.append(res(f"Sécurité enfant : aimant ({n})", ECHEC, "aimant dans un jouet pour jeune enfant : deux aimants avalés se collent à travers l'intestin.",
                               conseil="Aucun aimant accessible ou détachable (EN 71-1 § 8.10 / ASTM F963)."))
            continue
        couteau, vives = aretes_vives(m)
        if couteau > 1.0:
            out.append(res(f"Sécurité enfant : arêtes coupantes ({n})", ECHEC, f"{couteau:.0f} mm d'arêtes en lame (angle < 60°) sur {n}.",
                           conseil="Arrondir toutes les arêtes (congé ≥ 0,5 mm, idéalement 1-2 mm) ou supprimer les pointes."))
        elif vives > 1.0:
            out.append(res(f"Sécurité enfant : arêtes vives ({n})", AVERT, f"{vives:.0f} mm d'arêtes vives (≥ 60°) sans congé sur {n}.",
                           conseil="Congé ≥ 0,5 mm sur toutes les arêtes extérieures (a.arrondir(...)) : une arête FDM brute peut couper."))
    if out:
        out.append(res("Sécurité enfant : limites", INFO, "Une impression maison n'est PAS un jouet certifié (pas d'essais de chute, morsure, traction). "
                       "PLA/PETG à la bouche : des bactéries restent entre les couches (non lavable à fond). Pas de petites pièces détachables, "
                       "pas d'aimants ni de piles accessibles."))
    return out


def verif_environnement(pieces, A):
    env = A.__dict__.get("_env")
    if not env: return []
    out = []
    for n, pc in pieces.items():
        if pc.role == "achetee": continue
        t = env["temperature"]; titre = f"Chaleur : {n} ({pc.materiau}) à {t} °C" + (f" — {env['ou']}" if env.get("ou") else "")
        try:
            i_ = normaliser_materiau(pc.materiau or "PETG"); mat = i_["nom"]
            hdt = next((TEMP_RAMOLLISSEMENT[k] for k in (i_["nom"], i_["type"], i_["famille"]) if k in TEMP_RAMOLLISSEMENT), None)
        except ValueError:
            mat, hdt, i_ = pc.materiau, None, dict(famille=None)
        if hdt is None:      # jamais une valeur inventée (avant : 70 °C par défaut)
            out.append(res(titre, ECHEC, f"température de ramollissement du « {pc.materiau} » inconnue de LC3D : la tenue à {t} °C n'est pas vérifiée.",
                           conseil="Écrire un matériau reconnu (PLA, PETG, ABS, ASA, PC, PA-CF…) ou vérifier la HDT sur la fiche technique du filament."))
            continue
        st = OK if t <= hdt - 15 else (AVERT if t <= hdt - 5 else ECHEC)
        uv = env.get("soleil") and i_.get("famille") in ("PLA", "PETG", "ABS", "PA", "TPU")
        # conseil : un matériau qui TIENT vraiment (marge 15 °C), et au soleil l'ASA (UV) en premier
        ordre = (["ASA", "ASA-CF", "PC", "PA-CF"] if env.get("soleil") else ["PETG", "ASA", "ABS", "PC", "PA-CF"])
        tiennent = [m_ for m_ in ordre if TEMP_RAMOLLISSEMENT[m_] - 15 >= t and m_ != mat]
        if st != OK and tiennent:
            conseil = f"Changer pour {tiennent[0]}" + (" (résiste aux UV)" if env.get("soleil") and tiennent[0].startswith("ASA") else "") + ", ou garder la pièce à l'ombre et au frais."
        elif st != OK:
            conseil = f"Aucun plastique FDM courant ne tient {t} °C avec une marge de 15 °C : pièce en métal, ou PEEK/PEI (machine industrielle)."
        elif uv:
            conseil = "Au soleil : passer à l'ASA (résiste aux UV)."
        else:
            conseil = None
        out.append(res(titre, AVERT if (st == OK and uv and i_.get("famille") in ("PLA", "ABS")) else st,
                       f"le {mat} ramollit vers {hdt} °C (marge {hdt - t} °C)" + ("; UV : ce plastique jaunit et fragilise au soleil, l'ASA résiste" if uv else ""),
                       conseil=conseil))
    return out

# ----------------------------------------------------------------------------
# BLOC 1 — Mécanique de fonctionnement : mouvement complet, engrenages,
# assise, alignement de trous, masse / centre de gravité / basculement
# ----------------------------------------------------------------------------
def _mvt(self, nom, type="rotation", pivot=(0, 0, 0), axe=(0, 0, 1), de=0.0, a=360.0, pas_deg=2.0, pas_mm=0.25,
         jeu_min=None, entraine=None, titre=None, pas_filet=None):
    """Mouvement de FONCTIONNEMENT (une fois monté) : la pièce balaie toute sa course et on vérifie, à chaque pas,
    qu'elle ne touche à rien et garde son jeu. type="rotation" (angles en degrés, pivot/axe en coordonnées assemblées)
    ou "translation" (de/a en mm le long de axe).
    entraine : liste de pièces menées, ex. engrenage {"piece": "roue", "type": "rotation", "pivot": (..), "axe": (..), "ratio": -20/40}
    ou crémaillère {"piece": "barre", "type": "translation", "axe": (1,0,0), "ratio": mm_par_degre}."""
    if type == "vissage" and not pas_filet: raise ValueError("vissage : donner pas_filet (mm par tour)")
    self.__dict__.setdefault("mouvements", []).append(dict(piece=nom, type=type, pivot=tuple(pivot), axe=tuple(axe), de=float(de), a=float(a), pas_filet=pas_filet,
                                                           pas_deg=pas_deg, pas_mm=pas_mm, jeu_min=jeu_min, entraine=list(entraine or []),
                                                           titre=titre or (f"{nom} : vissage {abs(de - a) / 360:.2g} tour(s), pas {pas_filet:g} mm" if type == "vissage" else f"{nom} : {'rotation' if type == 'rotation' else 'translation'} {de:g} → {a:g}{'°' if type == 'rotation' else ' mm'}")))
    return self


def _engrenage(self, a, b, module, za, zb, centre_a, centre_b, interne=False, jeu_entraxe=0.35):
    """Paire d'engrenages droits a/b (dents za, zb). centre_a/centre_b : centres des axes en coordonnées assemblées.
    Vérifie l'entraxe théorique + le jeu FDM, et donne le rapport pour le mouvement."""
    self.__dict__.setdefault("engrenages", []).append(dict(a=a, b=b, m=module, za=za, zb=zb, ca=tuple(centre_a), cb=tuple(centre_b),
                                                            interne=interne, jeu=jeu_entraxe))
    return self


def _assise(self, a, b="sol", aire_min=20.0, tol=0.08):
    """La pièce a doit s'asseoir à plat sur b (ou sur le sol) avec au moins aire_min mm² de contact."""
    self.__dict__.setdefault("assises", []).append(dict(a=a, b=b, aire_min=aire_min, tol=tol)); return self


def _aligner(self, a, b, tol=0.15, d_min=1.0):
    """Les trous / goupilles cylindriques de a et de b qui sont sur le même axe doivent être alignés à ±tol mm
    (vis qui passe droit à travers deux pièces, goupille dans son trou)."""
    self.__dict__.setdefault("alignements", []).append(dict(a=a, b=b, tol=tol, d_min=d_min)); return self


def _stabilite(self, angle_min=10.0, remplissage=None, quincaillerie=None):
    """L'objet assemblé, posé sur sa base, doit tenir debout : centre de gravité au-dessus de la base,
    angle de basculement ≥ angle_min degrés — au repos ET aux deux bouts de chaque mouvement.
    quincaillerie : {"2 piles AA": (46, (x, y, z)), ...} grammes et position des pièces achetées."""
    self.stab = dict(angle_min=angle_min, remplissage=remplissage, quincaillerie=quincaillerie); return self


def _retenue(self, nom, direction=(0, 0, 1), distance=5.0, pas=0.1):
    """La pièce doit TENIR : tirée en ligne droite dans 'direction', elle doit buter (clip, filet, rebord) avant 'distance' mm."""
    self.__dict__.setdefault("retenues", []).append(dict(piece=nom, direction=tuple(direction), distance=distance, pas=pas)); return self


Assemblage.retenue = _retenue
Assemblage.mouvement = _mvt
Assemblage.engrenage = _engrenage
Assemblage.assise = _assise
Assemblage.aligner = _aligner
Assemblage.stabilite = _stabilite


def _transfo_mvt(type_, pivot, axe, v, pas_filet=None):
    axe = np.asarray(axe, float); axe = axe / np.linalg.norm(axe)
    if type_ == "rotation":
        return trimesh.transformations.rotation_matrix(math.radians(v), axe, pivot)
    if type_ == "vissage":   # filet à droite : tourner de v degrés (sens trigo autour de l'axe) fait MONTER de v/360 × pas le long de l'axe
        return trimesh.transformations.translation_matrix(axe * v / 360.0 * pas_filet) @ trimesh.transformations.rotation_matrix(math.radians(v), axe, pivot)
    return trimesh.transformations.translation_matrix(axe * v)


def poses_mouvement(mv, v):
    """{piece: matrice relative} pour la valeur v du mouvement maître (pièce menante + pièces menées)."""
    out = {mv["piece"]: _transfo_mvt(mv["type"], mv["pivot"], mv["axe"], v, mv.get("pas_filet"))}
    for e in mv["entraine"]:
        out[e["piece"]] = _transfo_mvt(e.get("type", "rotation"), e.get("pivot", (0, 0, 0)), e.get("axe", (0, 0, 1)), v * e.get("ratio", 1.0))
    return out


def _paires_proches(ma, mb, marge=0.0):
    return (ma.bounds[0] <= mb.bounds[1] + marge).all() and (mb.bounds[0] <= ma.bounds[1] + marge).all()


def _rayon_max(meshes, mv):
    """Plus grand rayon (mm) d'une pièce qui tourne, mesuré depuis son axe : sert à limiter l'arc parcouru par pas."""
    R = 1.0
    for e in [dict(piece=mv["piece"], type=mv["type"], pivot=mv["pivot"], axe=mv["axe"], ratio=1.0)] + mv["entraine"]:
        if e.get("type", "rotation") != "rotation": continue
        V = meshes[e["piece"]].vertices; ax = np.asarray(e.get("axe", (0, 0, 1)), float); ax /= np.linalg.norm(ax)
        w = V - np.asarray(e.get("pivot", (0, 0, 0)), float)
        R = max(R, float(np.linalg.norm(w - np.outer(w @ ax, ax), axis=1).max()) * abs(e.get("ratio", 1.0)))
    return R


ARC_MAX = 0.6   # mm parcourus au plus par pas (moins que la moitié d'un mur de 1,2 mm : pas de « saut » à travers un mur)


def verif_mouvements(meshes, A, en_place, clips):
    out = []; ARC = RAPIDE["arc_max"] if RAPIDE["actif"] else ARC_MAX
    for mv in getattr(A, "mouvements", []):
        etendue = mv["a"] - mv["de"]
        if mv["type"] in ("rotation", "vissage"):
            pas = min(mv["pas_deg"], math.degrees(ARC / _rayon_max({n: en_place[n] for n in en_place}, dict(mv, type="rotation"))))
        else:
            ratios = [1.0] + [abs(e.get("ratio", 1.0)) for e in mv["entraine"] if e.get("type") == "translation"]
            pas = min(mv["pas_mm"], ARC / max(ratios))
        n = max(2, int(math.ceil(abs(etendue) / pas)))
        valeurs = [mv["de"] + etendue * k / n for k in range(n + 1)]
        bougent = [mv["piece"]] + [e["piece"] for e in mv["entraine"]]
        fixes = [x for x in en_place if x not in bougent]
        # clips : chevauchement permis seulement jusqu'à celui du repos (+0,05 mm³), jamais plus
        repos_clip = {}
        for b in bougent:
            for o in en_place:
                if o != b and frozenset((b, o)) in clips and _paires_proches(en_place[b], en_place[o]):
                    repos_clip[frozenset((b, o))] = _vol_inter(en_place[b], en_place[o])[0]
        premier = None; jeu_min_vu = (1e9, None, None, None); pires = {}; echecs_calc = []
        jm = mv["jeu_min"]
        pas_jeu = max(1, n // 120)
        for k, v in enumerate(valeurs):
            rel = poses_mouvement(mv, v)
            cour = {}
            for b in bougent:
                mk = meshes[b].copy(); mk.apply_transform(rel[b] @ A.poses.get(b, np.eye(4))); cour[b] = mk
            for b in bougent:
                autres = [(o, en_place[o]) for o in fixes] + [(o, cour[o]) for o in bougent if o != b and bougent.index(o) > bougent.index(b)]
                for o, mo in autres:
                    if not _paires_proches(cour[b], mo, 1.0): continue
                    vol, I = _vol_inter(cour[b], mo)
                    if vol != vol:   # NaN : le calcul booléen a échoué -> jamais un « OK » par défaut
                        echecs_calc.append((v, b, o)); continue
                    for ct in getattr(A, "contacts", []):            # contact VOULU déclaré (A.contact) : retiré seulement dans sa boîte
                        if {ct["a"], ct["b"]} == {b, o} and I is not None and vol > 0:
                            (x0, y0, z0), (x1, y1, z1) = ct["zone"]
                            bx = trimesh.creation.box(extents=(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))); bx.apply_translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
                            try: vol = max(0.0, vol - float((I ^ _manifold(bx)).volume()))
                            except Exception: pass
                    cle = frozenset((b, o))
                    permis = repos_clip.get(cle, 0.0) * 1.0 + 0.05 if cle in clips else 0.02
                    if cle in clips and vol > permis:          # passage du clip DÉCLARÉ : voulu (sa force/flexion est calculée à part)
                        pass_clip = A.__dict__.setdefault("_passage_clip", {}).setdefault(mv["titre"], [v, v, 0.0])
                        pass_clip[0] = min(pass_clip[0], v); pass_clip[1] = max(pass_clip[1], v); pass_clip[2] = max(pass_clip[2], vol)
                        continue
                    if vol > permis:
                        pires[(b, o)] = max(pires.get((b, o), 0), vol)
                        if premier is None:
                            Im = _de_manifold(I) if I is not None else None
                            premier = (v, b, o, vol, _pt(Im.centroid) if Im is not None and len(Im.faces) else None, Im, k)
                    if jm is not None and k % pas_jeu == 0 and vol <= 0.02 and cle not in clips:
                        try:      # distance EXACTE entre triangles (Manifold, rapide) ; l'endroit n'est cherché que pour un nouveau minimum
                            d = float(_manifold(cour[b]).min_gap(_manifold(mo), max(3.0 * jm, 3.0))); ou = None
                        except Exception:
                            d = None
                        if d is None or d < jeu_min_vu[0]:
                            d1, ou1 = _distance_min(cour[b], mo, 4000)
                            d2, ou2 = _distance_min(mo, cour[b], 4000)     # dans les 2 sens (coins vifs)
                            de, ou = (d1, ou1) if d1 <= d2 else (d2, ou2)
                            if d is None: d = de
                        if d < jeu_min_vu[0]: jeu_min_vu = (d, v, o, ou)
        unite = " mm" if mv["type"] == "translation" else "°"
        pc_ = getattr(A, "_passage_clip", {}).get(mv["titre"])
        if pc_:
            out.append(res(f"Passage du clip pendant « {mv['titre']} »", INFO, f"contact du clip déclaré entre {pc_[0]:.1f} et {pc_[1]:.1f}{unite} (voulu : c'est le clic ; flexion et force calculées à part)"))
        cert = f"vérifié à {len(valeurs)} positions, tous les {abs(etendue) / n:.2g}{unite} (≤ {ARC} mm de déplacement par pas)"
        if echecs_calc:
            v, b, o = echecs_calc[0]
            out.append(res(f"Mouvement « {mv['titre']} » (calcul)", ECHEC, f"collision impossible à calculer {len(echecs_calc)} fois ({b}/{o} à {v:.1f}{unite}) : maillage non étanche",
                           conseil="Réparer le maillage de la pièce (voir « Maillage étanche ») : sans ça, le mouvement n'est PAS vérifié."))
        if premier:
            v, b, o, vol, lieu, Im, k = premier
            out.append(res(f"Mouvement « {mv['titre']} »", ECHEC,
                           f"{b} touche {o} à {v:.1f}{unite} ({vol:.2f} mm³) — " + ", ".join(f"{x}/{y} max {z:.1f} mm³" for (x, y), z in list(pires.items())[:4]) + f" — {cert}",
                           conseil="Agrandir le dégagement sur la trajectoire, réduire la course, ou corriger le rapport/entraxe des pièces menées.",
                           lieux=[lieu] if lieu else None))
            A.__dict__.setdefault("_mvt_blocages", {})[mv["titre"]] = (v, Im)
        else:
            txt = f"course complète sans toucher — {cert}"
            if jm is not None and jeu_min_vu[1] is not None:
                d, v, o, ou = jeu_min_vu
                txt += f" · jeu le plus serré {d:.2f} mm (±0,05) contre {o} à {v:.1f}{unite} (règle {jm} mm)"
                if d < jm - 0.02:
                    txt = txt.replace("course complète sans toucher", "ne touche pas, mais JEU TROP SERRÉ", 1)
                    boule = trimesh.creation.icosphere(2, 0.8); boule.apply_translation(ou)   # point rouge à l'endroit serré
                    A.__dict__.setdefault("_mvt_blocages", {})[mv["titre"]] = (v, boule)
                    out.append(res(f"Mouvement « {mv['titre']} »", ECHEC, txt, lieux=[ou],
                                   conseil=f"Ouvrir le passage de {jm - d:.2f} mm à cet endroit."))
                    continue
            out.append(res(f"Mouvement « {mv['titre']} »", OK, txt))
        if mv["type"] == "vissage" and not premier:
            try: out += _verif_engagement(meshes, A, en_place, mv, fixes)
            except Exception as e: out.append(res(f"Prise réelle du filet ({mv['piece']})", AVERT, f"non mesurée : {type(e).__name__}"))
    return out


def _verif_engagement(meshes, A, en_place, mv, fixes):
    """PRISE RÉELLE d'un vissage : combien de tours, depuis la position serrée, avant que la pièce puisse sortir TOUT DROIT
    (le juge la mesure comme ça). Les tours de l'hélice dessinée ne comptent pas : seul le recouvrement des filets compte."""
    b = mv["piece"]; pas = mv.get("pas_filet") or 1.0
    ax = np.asarray(mv["axe"], float); ax /= np.linalg.norm(ax)
    proches = [o for o in fixes if _paires_proches(en_place[b], en_place[o], 1.0)]
    if not proches: return []
    Mf = {o: _manifold(en_place[o]) for o in proches}
    serre = 0.0 if min(mv["de"], mv["a"]) <= 0 <= max(mv["de"], mv["a"]) else mv["a"]
    sens = 1.0 if max(mv["de"], mv["a"]) > serre else -1.0       # sens qui dévisse (vers l'autre bout de la course)
    hmax = float(np.ptp(en_place[b].vertices @ ax)) + 2 * pas
    def bloquee(deg):
        rel = poses_mouvement(mv, serre + sens * deg)[b]
        m0 = meshes[b].copy(); m0.apply_transform(rel @ A.poses.get(b, np.eye(4)))
        for dz in np.arange(0.4, hmax, 0.4):
            mk = m0.copy(); mk.apply_translation(ax * dz * (1 if np.dot(ax, en_place[b].centroid - sum(en_place[o].centroid for o in proches) / len(proches)) >= 0 else -1))
            M = _manifold(mk)
            if any((M ^ Mf[o]).volume() > 0.05 for o in proches): return True
        return False
    if not bloquee(0): return [res(f"Prise réelle du filet ({b})", ECHEC, "la pièce sort tout droit sans dévisser : le filet ne retient pas", valeur=0.0, exigence="tours_vissage", mesure="forme", unite="tour(s)", conseil="Vérifier la position axiale et la profondeur des filets.")]
    lo, hi = 0.0, abs(mv["a"] - mv["de"]) + 360
    if bloquee(hi): lo = hi
    else:
        for _ in range(9):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if bloquee(mid) else (lo, mid)
    tours = lo / 360; dessine = abs(mv["a"] - mv["de"]) / 360
    e = EXIGENCES_ACTIVES.get("tours_vissage") or {}
    mini = e.get("mini") or 1.0
    st = OK if tours >= mini else ECHEC
    return [res(f"Prise réelle du filet ({b})", st, exigence="tours_vissage", mesure="forme", unite="tour(s)", detail=f"{tours:.2f} tour(s) de prise réelle avant que la pièce sorte tout droit (course dessinée : {dessine:.2f} tour(s)) — "
                f"annoncer {tours:.2f} tour(s)" + ("" if st == OK else f" : sous {mini:g} tour, le filet peut sauter"), valeur=round(tours, 2),
                conseil=None if st == OK else "Allonger la zone filetée ou faire monter le filet jusqu'en haut du col (composant n° 5 v3 : entree=True).")]


def calc_engrenage(module, za, zb, interne=False, angle_pression=20.0, jeu_entraxe=0.35):
    """Engrenages droits à développante. Diamètres, entraxe théorique et conseillé FDM, rapport, risque de dents trop fines."""
    m = module
    d = lambda z: m * z
    ent = m * (zb - za) / 2 if interne else m * (za + zb) / 2
    notes = []
    if m < 1.0: notes.append(f"module {m} < 1 : dents fines, fragiles et imprécises en FDM buse 0,4 — viser module ≥ 1,0 (idéal 1,5+).")
    for z in (za, zb):
        if z < 17 and not interne: notes.append(f"{z} dents < 17 : sous-coupe (dent creusée au pied) à 20° — viser ≥ 17 dents ou déport.")
    epaisseur_pied = math.pi * m / 2 * 0.8
    if epaisseur_pied < 1.2: notes.append(f"épaisseur de dent ~{epaisseur_pied:.2f} mm < 1,2 mm : moins de 3 lignes de buse.")
    return dict(diam_primitif_a=round(d(za), 3), diam_primitif_b=round(d(zb), 3), diam_tete_a=round(d(za) + 2 * m, 3),
                diam_tete_b=round(d(zb) + (-2 if interne else 2) * m, 3), entraxe_theorique=round(ent, 3),
                entraxe_conseille_FDM=round(ent + jeu_entraxe, 3), rapport_b_sur_a=round((-1 if not interne else 1) * za / zb, 5),
                verdict=AVERT if notes else OK, notes=notes)


def verif_engrenages(A, en_place=None):
    out = []
    for g in getattr(A, "engrenages", []):
        # le centre déclaré doit être le vrai centre de la roue (sinon l'entraxe vérifié est imaginaire)
        if en_place is not None:
            for nom, c in ((g["a"], g["ca"]), (g["b"], g["cb"])):
                if nom in en_place:
                    cm = en_place[nom].center_mass if en_place[nom].is_volume else en_place[nom].centroid
                    e = float(np.linalg.norm((cm - np.asarray(c))[:2]))
                    if e > 0.2 and not g["interne"]:
                        out.append(res(f"Engrenage {nom} : centre", ECHEC, f"centre déclaré {list(c)} ≠ centre réel de la roue {_pt(cm)} (écart {e:.2f} mm)",
                                       conseil="Donner le vrai centre de l'axe à A.engrenage(), ou corriger la position de la roue."))
        # le rapport utilisé dans le mouvement doit être celui des dents
        attendu = (1 if g["interne"] else -1) * g["za"] / g["zb"]
        for mv in getattr(A, "mouvements", []):
            for e in mv["entraine"]:
                if mv["piece"] == g["a"] and e["piece"] == g["b"] and e.get("type", "rotation") == "rotation":
                    if abs(e.get("ratio", 1.0) - attendu) > 1e-3:
                        out.append(res(f"Engrenage {g['a']} → {g['b']} : rapport", ECHEC, f"le mouvement « {mv['titre']} » utilise {e.get('ratio')} mais les dents donnent {attendu:.5f}",
                                       conseil="Corriger le ratio dans A.mouvement(entraine=...) : sinon la simulation ne représente pas les vrais engrenages."))
        c = calc_engrenage(g["m"], g["za"], g["zb"], g["interne"], jeu_entraxe=g["jeu"])
        reel = float(np.linalg.norm(np.asarray(g["ca"]) - np.asarray(g["cb"])))
        visee = c["entraxe_conseille_FDM"]; ecart = reel - c["entraxe_theorique"]
        if ecart < 0.15:
            st, cons = ECHEC, f"Entraxe trop serré : les dents vont coincer à l'impression. Viser {visee} mm."
        elif ecart > 0.6:
            st, cons = ECHEC, f"Entraxe trop grand : jeu énorme, les dents sautent sous charge. Viser {visee} mm."
        else:
            st, cons = c["verdict"], "; ".join(c["notes"]) or None
        out.append(res(f"Engrenage {g['a']} ↔ {g['b']}", st,
                       f"module {g['m']}, {g['za']}/{g['zb']} dents, rapport {c['rapport_b_sur_a']} · entraxe réel {reel:.3f} mm (théorique {c['entraxe_theorique']}, jeu FDM {ecart:+.2f} mm)",
                       conseil=cons))
    return out


def verif_assises(en_place, A):
    out = []
    for s in getattr(A, "assises", []):
        ma = en_place[s["a"]]
        pts, fid = trimesh.sample.sample_surface(ma, 8000 if RAPIDE["actif"] else 30000, seed=4)
        if s["b"] == "sol":
            zsol = min(m.bounds[0, 2] for m in en_place.values())
            d = pts[:, 2] - zsol
            d = np.where(ma.face_normals[fid][:, 2] < -0.95, d, 1e9)   # seulement les faces à plat vers le bas
        else:
            mb_ = en_place[s["b"]]; d = np.full(len(pts), 1e9)
            pres = np.all((pts >= mb_.bounds[0] - s["tol"] - 0.01) & (pts <= mb_.bounds[1] + s["tol"] + 0.01), axis=1)   # seuls les points près de b
            idx = np.where(pres)[0]
            for k0 in range(0, len(idx), 2000):        # paquets : mémoire bornée sur les grosses pièces (avant : 30 000 points d'un coup)
                ii = idx[k0:k0 + 2000]
                _, d[ii], _ = trimesh.proximity.closest_point(mb_, pts[ii])
        aire = float((d <= s["tol"]).mean() * ma.area)
        st = OK if aire >= s["aire_min"] else ECHEC
        out.append(res(f"Assise {s['a']} sur {s['b']}", st, f"surface de contact ≈ {aire:.0f} mm² (minimum {s['aire_min']:.0f} mm²)",
                       conseil=None if st == OK else "La pièce porte sur trop peu de surface (ou est bancale) : aplanir la face d'appui ou ajouter des pieds."))
    return out


def _cylindres(forme, M):
    """Axes et rayons des faces cylindriques d'une forme CadQuery/build123d, transformés par M."""
    try:
        import cadquery as cq
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cylinder
        if isinstance(forme, cq.Workplane):
            sh = cq.Compound.makeCompound([v for v in forme.vals() if isinstance(v, cq.Shape)])
        elif isinstance(forme, cq.Shape):
            sh = forme
        elif hasattr(forme, "wrapped"):
            sh = cq.Shape.cast(forme.wrapped)
        else:
            return []
        out = []
        for f in sh.Faces():
            ad = BRepAdaptor_Surface(f.wrapped)
            if ad.GetType() != GeomAbs_Cylinder: continue
            cy = ad.Cylinder(); ax = cy.Axis(); p = ax.Location(); dd = ax.Direction()
            P = (M @ np.r_[p.X(), p.Y(), p.Z(), 1.0])[:3]; D = M[:3, :3] @ np.array([dd.X(), dd.Y(), dd.Z()])
            out.append(dict(p=P, d=D / np.linalg.norm(D), r=cy.Radius(), centre=(M @ np.r_[*f.Center().toTuple(), 1.0])[:3]))
        return out
    except Exception:
        return []


def verif_alignements(pieces, A):
    out = []
    for al in getattr(A, "alignements", []):
        ca = _cylindres(pieces[al["a"]].forme, A.poses.get(al["a"], np.eye(4)))
        cb = _cylindres(pieces[al["b"]].forme, A.poses.get(al["b"], np.eye(4)))
        if not ca or not cb:
            out.append(res(f"Alignement {al['a']} / {al['b']}", AVERT, "pas de trous/goupilles cylindriques trouvés (forme non CAO ou maillage)")); continue
        paires = []
        for x in ca:
            if 2 * x["r"] < al["d_min"]: continue
            for y in cb:
                if 2 * y["r"] < al["d_min"]: continue
                if abs(2 * x["r"] - 2 * y["r"]) > 2.0: continue   # seulement goupille/trou, vis/trou ou trou/trou du même calibre
                if abs(abs(float(x["d"] @ y["d"])) - 1) > 1 - math.cos(math.radians(3)): continue
                w = y["p"] - x["p"]; ecart = float(np.linalg.norm(w - (w @ x["d"]) * x["d"]))
                if ecart <= 3 * max(x["r"], y["r"]):   # proche du même axe : aligné OU décalé (signalé)
                    paires.append((ecart, 2 * x["r"], 2 * y["r"], _pt(x["centre"])))
        if not paires:
            out.append(res(f"Alignement {al['a']} / {al['b']}", AVERT, "aucun trou de a n'est sur le même axe qu'un trou de b",
                           conseil="Vérifier que la vis/goupille traverse bien les deux pièces.")); continue
        vus = {}
        for e, da, db, c in paires:
            k = (round(da, 1), round(db, 1), tuple(round(v) for v in c))
            if k not in vus or e < vus[k][0]: vus[k] = (e, da, db, c)
        mauvais = [p for p in vus.values() if p[0] > al["tol"]]
        pire = max(vus.values(), key=lambda p: p[0])
        st = ECHEC if mauvais else OK
        out.append(res(f"Alignement {al['a']} / {al['b']}", st,
                       f"{len(vus)} axe(s) commun(s); pire décalage {pire[0]:.3f} mm (trou Ø{pire[1]:.2f} / Ø{pire[2]:.2f}), tolérance ±{al['tol']} mm",
                       lieux=[p[3] for p in mauvais][:4] or None,
                       conseil=None if st == OK else "Recentrer les trous : la vis ou la goupille va forcer de travers."))
    return out


def masse_et_cg(en_place, pieces, infos=None, remplissage=None):
    """Masse (g) par pièce et centre de gravité. Utilise l'estimation de filament (parois + remplissage) quand elle existe."""
    tot, mom, det = 0.0, np.zeros(3), {}
    for n, m in en_place.items():
        rho = proprietes_materiau(pieces[n].materiau)["rho"] if n in pieces else 1.25
        g = None
        if infos and n in infos and infos[n].get("filament_g"):
            g = float(infos[n]["filament_g"])
        if g is None:
            g = abs(float(m.volume)) / 1000 * rho * (remplissage if remplissage else 1.0)
        c = m.center_mass if m.is_volume else m.centroid
        det[n] = round(g, 1); tot += g; mom += g * np.asarray(c)
    return tot, (mom / tot if tot else np.zeros(3)), det


def _stab_une(en_place, pieces, infos, st_, extra):
    tot, cg, det = masse_et_cg(en_place, pieces, infos, st_.get("remplissage"))
    for nom_q, (g, pos) in extra.items():   # quincaillerie : aimants, piles, vis, plomb...
        cg = (cg * tot + np.asarray(pos, float) * g) / (tot + g); tot += g; det[nom_q] = g
    ens = trimesh.util.concatenate(list(en_place.values()))
    z0 = ens.bounds[0, 2]
    from shapely.geometry import MultiPoint, Point
    base = MultiPoint([tuple(q) for q in ens.vertices[ens.vertices[:, 2] <= z0 + 0.3][:, :2]]).convex_hull
    p = Point(cg[0], cg[1]); h = cg[2] - z0
    if not base.contains(p): return tot, cg, det, h, -1.0, None
    marge = base.exterior.distance(p)
    return tot, cg, det, h, math.degrees(math.atan2(marge, max(h, 1e-6))), marge


def verif_stabilite(en_place, pieces, A, infos, meshes=None):
    st_ = getattr(A, "stab", None)
    if not st_: return []
    extra = st_.get("quincaillerie") or {}
    cas = [("au repos", en_place)]
    if meshes is not None:   # aussi aux 2 bouts de chaque mouvement (ex. couvercle ouvert, bras sorti)
        for mv in getattr(A, "mouvements", []):
            for v in (mv["de"], mv["a"]):
                rel = poses_mouvement(mv, v); ep = dict(en_place)
                for b, M in rel.items():
                    mk = meshes[b].copy(); mk.apply_transform(M @ A.poses.get(b, np.eye(4))); ep[b] = mk
                cas.append((f"{mv['titre']} à {v:g}{'°' if mv['type'] == 'rotation' else ' mm'}", ep))
    pire = None
    for nom_cas, ep in cas:
        r = _stab_une(ep, pieces, infos, st_, extra)
        if pire is None or r[4] < pire[1][4]: pire = (nom_cas, r)
    nom_cas, (tot, cg, det, h, ang, marge) = pire
    detail_m = ", ".join(f"{k} {v} g" for k, v in det.items())
    pire_txt = f" — pire cas : {nom_cas}" if len(cas) > 1 else ""
    if ang < 0:
        return [res("Stabilité (tient debout)", ECHEC, f"centre de gravité ({_pt(cg)}) HORS de la base : l'objet tombe{pire_txt}. Masse ≈ {tot:.0f} g ({detail_m})",
                    conseil="Élargir la base, alourdir le bas (remplissage plus dense en bas) ou déplacer la masse.", lieux=[_pt(cg)])]
    st = OK if ang >= st_["angle_min"] else AVERT
    return [res("Stabilité (tient debout)", st, f"masse ≈ {tot:.0f} g ({detail_m}); centre de gravité à {h:.1f} mm de haut, {marge:.1f} mm du bord de la base "
                f"→ bascule à {ang:.0f}° d'inclinaison (minimum {st_['angle_min']:.0f}°){pire_txt}",
                conseil=None if st == OK else "Bascule facilement : élargir la base ou abaisser le centre de gravité.")]


def verif_jeu_ferme(meshes, A, en_place, pas=0.05, course=4.0):
    """Pièce CLIPSÉE, fermée : de combien elle bouge le long de son chemin de montage avant de buter (en reculant : le crochet
    contre sa fenêtre ; en avançant : l'appui). Un couvercle qui « branle » de 2 mm ne tient pas sa carte : le juge le mesure."""
    out = []; vus = set()
    seq = {s["piece"]: s for s in getattr(A, "sequence", []) if s.get("type") == "translation"}
    for a_, b_, _acc in getattr(A, "clips", []):
        if a_ in vus or a_ not in seq or a_ not in en_place or b_ not in en_place: continue
        vus.add(a_)
        d = np.asarray(seq[a_]["depuis"], float); n = np.linalg.norm(d)
        if n < 1e-6: continue
        d /= n                                   # direction d'arrivée inversée = vers où elle repart
        autres = [o for o in en_place if o != a_ and _paires_proches(en_place[a_], en_place[o], 1.5)]
        if not autres: continue
        Mo = {o: _manifold(en_place[o]) for o in autres}
        def vol(dz, dec=None):
            mk = en_place[a_].copy(); mk.apply_translation(d * dz + (0 if dec is None else dec)); M = _manifold(mk)
            return sum((M ^ Mo[o]).volume() for o in autres)
        v0 = vol(0.0)
        def libre(sens, dec=None, axe=None, cmax=None):
            ax_ = d if axe is None else axe; k = 1; base = vol(0.0, dec) if dec is not None else v0
            while k * pas <= (cmax or course):
                mk_dec = ax_ * sens * k * pas + (0 if dec is None else dec)
                mk = en_place[a_].copy(); mk.apply_translation(mk_dec); M = _manifold(mk)
                if sum((M ^ Mo[o]).volume() for o in autres) > max(v0, base) + 0.05: return (k - 1) * pas
                k += 1 if k < 10 else 2
            return None
        rec, av = libre(1.0), libre(-1.0)
        # PIRE CAS (essai réel) : la pièce posée au bout de son jeu de côté / en hauteur — le cran retient-il encore ?
        u = np.cross(d, [0, 0, 1.0]) if abs(d[2]) < 0.9 else np.cross(d, [1.0, 0, 0]); u /= np.linalg.norm(u); w = np.cross(d, u)
        jeux = {}
        for nom_ax, ax_ in (("u", u), ("w", w)):
            for sg in (1.0, -1.0):
                j_ = libre(sg, axe=ax_, cmax=2.0)
                jeux[(nom_ax, sg)] = 0.0 if j_ is None else j_       # None : rien ne la bloque à 2 mm → traité à part (pas un jeu de glissière)
        pire = None
        if rec is not None:
            for (nom_ax, sg), j_ in jeux.items():
                if j_ <= 0.02: continue
                dec = (u if nom_ax == "u" else w) * sg * j_
                r2 = libre(1.0, dec=dec)
                if r2 is None:
                    pire = (nom_ax, sg, j_); break
        if pire is not None:
            nom_ax, sg, j_ = pire
            vect = [round(float(x), 2) for x in ((u if nom_ax == "u" else w) * sg)]
            out.append(res(f"Retenue au pire cas {a_}", ECHEC, exigence="jeu_ferme", mesure="forme", unite="mm",
                           detail=f"décalée de {j_:.2f} mm dans son jeu (direction {vect}), {a_} SORT sans que le cran ou le crochet accroche : "
                                  f"le jeu dépasse la hauteur d'accroche — la pièce ne reste pas fermée",
                           conseil="Accroche plus haute que le jeu (accroche ≥ jeu + 0,2 mm), ou réduire le jeu dans cette direction (rainure plus juste, appui)."))
        if rec is None:
            out.append(res(f"Jeu fermé {a_}", ECHEC, f"en reculant de {course:g} mm le long de son montage, {a_} ne bute sur rien : les clips ne la retiennent pas",
                           conseil="Baisser la fenêtre du clip pour que le crochet appuie dès la fermeture.")); continue
        tot = rec + (av or 0.0)
        e = EXIGENCES_ACTIVES.get("jeu_ferme") or {}
        maxi = e.get("maxi") if e.get("maxi") is not None else 0.5
        st = OK if tot <= maxi + 1e-9 else AVERT
        out.append(res(f"Jeu fermé {a_}", st, exigence="jeu_ferme", mesure="forme", unite="mm", detail=f"fermée, {a_} bouge de {tot:.2f} mm le long de son montage (recul {rec:.2f} avant que les crochets accrochent, "
                       f"avance {0 if av is None else av:.2f}) — annoncer cette valeur" + ("" if st == OK else f" : plus que {maxi:g} mm, ça branle"),
                       valeur=round(tot, 2), conseil=None if st == OK else "Rapprocher la face de retenue de la fenêtre (crochet plaqué fermé) ou ajouter une butée / un poussoir."))
    return out


def verif_retenues(meshes, A, en_place):
    out = []
    for r in getattr(A, "retenues", []):
        d = np.asarray(r["direction"], float); d /= np.linalg.norm(d)
        bute = None
        for k in range(1, int(r["distance"] / r["pas"]) + 1):
            mk = meshes[r["piece"]].copy(); mk.apply_transform(trimesh.transformations.translation_matrix(d * k * r["pas"]) @ A.poses.get(r["piece"], np.eye(4)))
            for o, mo in en_place.items():
                if o == r["piece"] or not _paires_proches(mk, mo): continue
                if _vol_inter(mk, mo)[0] > 0.02: bute = (k * r["pas"], o); break
            if bute: break
        if bute:
            out.append(res(f"Tient en place : {r['piece']}", OK, f"tirée vers {list(r['direction'])}, elle bute contre « {bute[1]} » après {bute[0]:.1f} mm"))
        else:
            out.append(res(f"Tient en place : {r['piece']}", ECHEC, f"tirée vers {list(r['direction'])}, elle sort sur {r['distance']} mm sans rien accrocher",
                           conseil="Ajouter/agrandir l'accroche (clip ≥ 1 mm, filet engagé, rebord)."))
    return out


# --- Compléments (sabotage) : jeux des pièces achetées, engrenages mesurés, becs, clips démontables, contacts non déclarés
TYPES_ACHETEES = [   # (mots du nom, type, jeu min effectif après rétrécissement des trous, jeu max dessiné par côté)
    (("roulement", "bearing", "608", "625", "623", "6000", "6001", "6200", "6800"), "roulement", -0.10, 0.20),
    (("ecrou", "écrou", "nut"), "écrou", 0.0, 0.50),
    (("aimant", "magnet"), "aimant", 0.0, 0.30),
    (("vis", "screw", "boulon", "bolt"), "vis", 0.0, 0.50),
]


def _type_achetee(nom):
    n = nom.lower()
    for mots, t, mini, maxi in TYPES_ACHETEES:
        if any(m in n for m in mots): return t, mini, maxi
    return None, 0.0, None


def _jeu_lateral(x, y, axe, n=4000):
    """Jeu RADIAL entre la pièce achetée x et la pièce imprimée y (en place) : distance entre les faces de x parallèles à l'axe
    d'insertion et les murs de y parallèles à cet axe (les appuis — tête de vis, fond du logement — ne comptent pas)."""
    axe = np.asarray(axe, float); axe /= np.linalg.norm(axe)
    pts, fi = trimesh.sample.sample_surface(x, n, seed=3)
    lat = np.abs(x.face_normals[fi] @ axe) < 0.3
    pts = pts[lat]
    if not len(pts): return None
    cp, d, tri = trimesh.proximity.closest_point(y, pts)
    murs = (np.abs(y.face_normals[tri] @ axe) < 0.5) & (d < 2.0)
    return float(d[murs].min()) if murs.any() else None


def verif_complements(meshes, pieces, A, en_place):
    out = []
    tb = VARIATION_P2S["trou_biais"]
    achetees = [n for n, pc in pieces.items() if pc.role == "achetee" and n in en_place]
    imprimees = [n for n, pc in pieces.items() if pc.role != "achetee" and n in en_place]
    seq = {s_["piece"]: s_ for s_ in A.sequence if s_["type"] == "translation"}
    # 1-2) jeu de chaque pièce achetée dans la pièce imprimée qui la reçoit (trous imprimés ~trou_biais plus petits au rayon)
    for x in achetees:
        t, mini, maxi = _type_achetee(x)
        axe = seq[x]["depuis"] if x in seq and np.linalg.norm(seq[x]["depuis"]) > 0 else (0, 0, 1)
        for y in imprimees:
            X, Y = en_place[x], en_place[y]
            if not ((X.bounds[0] <= Y.bounds[1] + 1).all() and (Y.bounds[0] <= X.bounds[1] + 1).all()): continue
            if _vol_inter(X, Y)[0] > 0.01: continue          # collision : déjà ❌ « Position finale »
            d = _jeu_lateral(X, Y, axe)
            if d is None: continue
            eff = d - tb; quoi = t or "pièce achetée"
            if eff < mini - 1e-9:
                r_ = res(f"Jeu achetée {x} ↔ {y}", ECHEC, f"{quoi} : jeu dessiné {d:.2f} mm par côté, mais les trous imprimés sortent ~{tb:.2f} mm plus petits au rayon "
                         f"→ ≈ {eff:+.2f} mm : ne passera pas" + (" (serrage trop fort)" if t == "roulement" else ""), valeur=round(d, 3),
                         conseil="Agrandir le trou (lc3d.TROUS_FDM / calc ajustement / logement_roulement donnent la cote à dessiner).")
            elif maxi is not None and d > maxi + 0.02:
                r_ = res(f"Jeu achetée {x} ↔ {y}", ECHEC, f"{quoi} : jeu {d:.2f} mm par côté > {maxi:.2f} mm : trop lâche (ça ballotte" +
                         (", le roulement tourne dans son logement)" if t == "roulement" else ")"), valeur=round(d, 3),
                         conseil="Réduire le Ø du logement (cotes conseillées : lc3d.TROUS_FDM, logement_roulement).")
            else:
                r_ = res(f"Jeu achetée {x} ↔ {y}", OK, f"{quoi} : jeu {d:.2f} mm par côté (≈ {eff:+.2f} mm imprimé)", valeur=round(d, 3))
            r_["mini_sim"] = mini
            out.append(r_)
    # 3) engrenages : la VRAIE roue (rayon de tête, nombre de dents) doit correspondre au module/dents déclarés; elles doivent se toucher
    for g in getattr(A, "engrenages", []):
        if g["interne"]: continue
        for nom, c, z in ((g["a"], g["ca"], g["za"]), (g["b"], g["cb"], g["zb"])):
            if nom not in en_place: continue
            M_ = en_place[nom]; zm = float(M_.bounds[:, 2].mean())
            S = _polys_section(M_, zm)
            if S is None or S.is_empty: continue
            P = max(getattr(S, "geoms", [S]), key=lambda q: q.area)
            ext = np.asarray(P.exterior.segmentize(0.1).coords)[:, :2] - np.asarray(c)[:2]
            r = np.hypot(ext[:, 0], ext[:, 1]); th = np.arctan2(ext[:, 1], ext[:, 0])
            r_tete = float(r.max()); attendu = g["m"] * (z + 2) / 2
            bins = np.full(720, np.nan); k_ = ((th + np.pi) / (2 * np.pi) * 720).astype(int) % 720
            np.fmax.at(bins, k_, r) if hasattr(np.fmax, "at") else None
            b_ = bins[~np.isnan(bins)]
            dents = None
            if len(b_) > 100:
                seuil = (float(b_.max()) + float(np.percentile(b_, 5))) / 2      # mi-chemin entre le pied et la tête MESURÉS
                h_ = b_ > seuil; dents = int(np.sum(h_ & ~np.roll(h_, 1)))
            ok_r = abs(r_tete - attendu) <= max(0.3, 0.08 * g["m"])
            ok_z = dents is None or dents == z
            if not (ok_r and ok_z):
                m_mes = 2 * r_tete / (z + 2)
                out.append(res(f"Engrenage {nom} : roue mesurée", ECHEC,
                               f"rayon de tête mesuré {r_tete:.2f} mm (attendu {attendu:.2f} pour module {g['m']}, {z} dents)" + (f", {dents} dents comptées" if dents is not None else "") +
                               f" → module réel ≈ {m_mes:.2f}", conseil="Le module ou le nombre de dents déclaré à A.engrenage() ne correspond pas à la roue dessinée."))
        if g["a"] in en_place and g["b"] in en_place and _vol_inter(en_place[g["a"]], en_place[g["b"]])[0] <= 0.01:
            d, _ = _distance_min(en_place[g["a"]], en_place[g["b"]])
            if d > 1.0:
                out.append(res(f"Engrenage {g['a']} ↔ {g['b']} : contact", ECHEC, f"les dents ne se touchent jamais : {d:.2f} mm entre les deux roues",
                               conseil="Rapprocher les axes (entraxe = m·(za+zb)/2 + jeu) ou corriger le module."))
    # 4) becs déclarés : épaisseur ≥ 2 mm
    for b in getattr(A, "becs", []):
        if b["piece"] not in meshes: continue
        m = affiner(meshes[b["piece"]]); ep, _, pe, _ = epaisseurs_par_face(m)
        (x0, y0, z0), (x1, y1, z1) = b["zone"]; c_ = m.triangles_center
        dans = (c_[:, 0] >= x0) & (c_[:, 0] <= x1) & (c_[:, 1] >= y0) & (c_[:, 1] <= y1) & (c_[:, 2] >= z0) & (c_[:, 2] <= z1) & ~np.isnan(ep)
        if not dans.any():
            out.append(res(f"Bec {b['piece']}", AVERT, "aucune face du bec dans la zone donnée", conseil="Vérifier la zone de A.bec().")); continue
        e = float(np.nanpercentile(ep[dans], 3))
        out.append(res(f"Bec {b['piece']}", OK if e >= b["minimum"] - 0.02 else ECHEC, f"épaisseur du bec {e:.2f} mm (règle ≥ {b['minimum']} mm)",
                       valeur=round(e, 2), conseil=None if e >= b["minimum"] - 0.02 else "Épaissir le bec à ≥ 2 mm : sinon il plie ou casse à la première ouverture."))
    # 5) clips démontables / couvercle qui ne pourra plus s'ouvrir
    retenus = {r["piece"] for r in getattr(A, "retenues", [])}
    assis = {frozenset((x["a"], x["b"])) for x in getattr(A, "assises", [])}
    for k_, ci in getattr(A, "clips_info", {}).items():
        perm = ci["alpha_out"] >= 89.9
        cc = getattr(A, "clips_calc", {}).get(k_)
        F_ret = None
        if cc:
            try:
                r_ = calc_snap(cc["L"], cc["h"], cc["w"], cc["accroche"], cc["mat"], cc["alpha_in"], cc["alpha_out"], usage=cc["usage"], conique=cc["conique"])
                F_ret = r_["force_retrait_N"] if not isinstance(r_["force_retrait_N"], str) else None
            except Exception:
                pass
        if ci["demontable"]:
            if perm or (F_ret is not None and F_ret > 30):
                out.append(res(f"Démontage : {ci['a']} / {ci['b']}", ECHEC, ("retenue à 90° : le clip ne se déclipse pas sans casser" if perm else f"retrait {F_ret:.0f} N > 30 N : trop dur à déclipser à la main"),
                               conseil="Face de retenue à 45-60° (alpha_out) et accroche ≥ 1 mm : se déclipse en tirant, tient quand même."))
            else:
                out.append(res(f"Démontage : {ci['a']} / {ci['b']}", OK, "se déclipse à la main" + (f" (≈ {F_ret:.0f} N)" if F_ret else "")))
        elif ci["demontable"] is None and perm:
            couv = any(m_ in ci["a"].lower() + ci["b"].lower() for m_ in ("couvercle", "lid", "capot", "trappe", "porte", "cover")) or k_ in assis
            if couv and ci["a"] not in retenus and ci["b"] not in retenus:
                out.append(res(f"Démontage : {ci['a']} / {ci['b']}", AVERT, "clip à retenue 90° (permanent) sur un couvercle : une fois clipsé, il ne pourra plus s'ouvrir sans outil",
                               conseil="S'il doit s'ouvrir : A.clip(..., demontable=True) avec alpha_out 45-60°. Si c'est voulu : demontable=False."))
    # 6) contact à 0 mm entre deux pièces imprimées, sans rien de déclaré (soudure ou frottement non voulu)
    declares = {frozenset((a, b)) for a, b, _ in A.jeux} | {frozenset((a, b)) for a, b, _ in A.clips} | assis | \
               {frozenset((x["a"], x["b"])) for x in getattr(A, "alignements", []) + getattr(A, "serrages", []) + getattr(A, "ajustements", [])} | \
               {frozenset((g["a"], g["b"])) for g in getattr(A, "engrenages", [])}
    mobiles = {mv["piece"] for mv in getattr(A, "mouvements", [])} | {e["piece"] for mv in getattr(A, "mouvements", []) for e in mv["entraine"]} | \
              {r["nom"] for r in getattr(A, "ressorts", [])} | {n for _, dep in A.etats for n in dep}      # ressorts / états : contacts vérifiés ailleurs
    jeux_decl = {frozenset((a, b)) for a, b, _ in A.jeux}
    for x in getattr(A, "assises", []):     # posée sur l'autre : l'appui touche exprès, mais les CÔTÉS ? (pièce soulevée de 0,2 mm)
        a, b = x["a"], x["b"]
        if b == "sol" or a not in en_place or b not in en_place or frozenset((a, b)) in jeux_decl or a in mobiles: continue
        ma = en_place[a].copy(); ma.apply_translation((0, 0, 0.2))
        if _vol_inter(ma, en_place[b])[0] > 0.01: continue
        d, ou = _distance_min(ma, en_place[b])
        if d < 0.1:
            out.append(res(f"Contact {a} / {b} (côtés)", AVERT, f"{a} est posée sur {b} (assise), mais ses CÔTÉS touchent aussi ({d:.2f} mm) : ça frotte ou ça se soude, sans jeu déclaré",
                           lieux=[ou], conseil="Donner un jeu latéral (≥ 0,2-0,5 mm) et le déclarer : A.jeu(a, b, minimum=...)."))
    for i, a in enumerate(imprimees):
        for b in imprimees[i + 1:]:
            if frozenset((a, b)) in declares or a in mobiles or b in mobiles: continue
            X, Y = en_place[a], en_place[b]
            if not ((X.bounds[0] <= Y.bounds[1] + 0.2).all() and (Y.bounds[0] <= X.bounds[1] + 0.2).all()): continue
            if _vol_inter(X, Y)[0] > 0.01: continue
            d, ou = _distance_min(X, Y)
            if d < 0.1:
                out.append(res(f"Contact {a} / {b}", AVERT, f"les deux pièces se touchent ({d:.2f} mm) sans jeu, assise ni clip déclaré : soudure ou frottement non voulu ?",
                               lieux=[ou], conseil="Si elles doivent bouger : A.jeu(a, b) (≥ 0,5 mm). Si l'une est posée sur l'autre : A.assise(a, b)."))
    return out


def verif_mecanique(meshes, pieces, A, en_place, infos=None):
    clips = {frozenset((a, b)) for a, b, _ in A.clips} | {frozenset((d["a"], d["b"])) for d in getattr(A, "serrages", [])}
    out = []
    out += garde_res("Retenues (tient en place)", verif_retenues, meshes, A, en_place, etat=A)
    out += garde_res("Jeu des pièces clipsées, fermées", verif_jeu_ferme, meshes, A, en_place, etat=A)
    out += verif_engrenages(A, en_place)
    out += garde_res("Mouvements", verif_mouvements, meshes, A, en_place, clips, etat=A)
    out += garde_res("Assises", verif_assises, en_place, A, etat=A)
    out += garde_res("Alignements", verif_alignements, pieces, A, etat=A)
    out += garde_res("Stabilité", verif_stabilite, en_place, pieces, A, infos, meshes, etat=A)
    out += verif_ressorts(A, pieces)
    out += garde_res("Exigences mesurées", verif_exigences, A, en_place, etat=A)
    try:
        out += garde_res("Connecteurs (fiches de câble)", verif_connecteurs, meshes, pieces, A, en_place, etat=A)
    except Exception as e:
        out.append(res("Connecteurs (fiches de câble)", AVERT, f"calcul impossible : {type(e).__name__}: {e}"))
    try:
        out += garde_res("Vérifications complémentaires", verif_complements, meshes, pieces, A, en_place, etat=A)
    except Exception as e:
        out.append(res("Vérifications complémentaires", AVERT, f"calcul impossible : {type(e).__name__}: {e}"))
    return out


def verif_ressorts(A, pieces=None):
    """Ressorts déclarés : force minimale (au repos) ≥ 3× frottements + contrainte à pleine course.
    Pièce flexible sans ressort ni clip déclaré : avertissement (sa force n'est pas vérifiée)."""
    out = []
    for r in getattr(A, "ressorts", []):
        f_min_req = 3 * r["frottement_N"]
        if r["type"] == "helice":
            if not (r["d_fil"] and r["D_moyen"] and r["spires"]):
                out.append(res(f"Ressort {r['nom']}", ECHEC, "ressort hélicoïdal sans d_fil / D_moyen / spires : force impossible à vérifier")); continue
            c = calc_ressort(r["d_fil"], r["D_moyen"], r["spires"], r["precharge"] + r["course"])
            k = c["raideur_N_mm"]; contrainte_ok = c["verdict"] == OK; lim_txt = f"{c['contrainte_MPa']} MPa (limite {c['limite_MPa']})"
        else:
            if not (r["L"] and r["h"] and r["w"]):
                out.append(res(f"Ressort {r['nom']}", ECHEC, "lame sans L / h / w : force impossible à vérifier")); continue
            c = calc_lame(r["L"], r["h"], r["w"], r["precharge"] + r["course"], r["mat"], usage=r["usage"])
            k = c["raideur_N_mm"]; contrainte_ok = c["contrainte_MPa"] <= c["limite_MPa"]; lim_txt = f"{c['contrainte_MPa']} MPa (limite {c['limite_MPa']})"
        f_min = k * r["precharge"]; f_max = k * (r["precharge"] + r["course"])
        notes = []
        if f_min < f_min_req - 1e-9:
            notes.append(f"au repos (fin du retour) la force n'est que {f_min:.2f} N < 3 × {r['frottement_N']} N = {f_min_req:.2f} N"
                         + (" : sans précharge elle tombe à 0, la pièce ne revient pas jusqu'au bout" if r["precharge"] <= 0 else ""))
        if not contrainte_ok: notes.append(f"contrainte à pleine course {lim_txt} : trop sollicité")
        out.append(res(f"Ressort {r['nom']}", ECHEC if notes else OK,
                       f"force {f_min:.2f} N au repos → {f_max:.2f} N enfoncé (exigé ≥ {f_min_req:.2f} N partout) · contrainte {lim_txt}",
                       conseil="; ".join(notes) + ("; ajouter une précharge, une lame plus épaisse/large, ou un ressort de métal (ressort de stylo)" if notes else "") or None))
    declares = {r["nom"] for r in getattr(A, "ressorts", [])} | {a for a, b, _ in A.clips} | {b for a, b, _ in A.clips}
    for n, p in (pieces or {}).items():
        if getattr(p, "role", "") == "flexible" and n not in declares:
            out.append(res(f"Ressort {n}", AVERT, "pièce flexible sans A.ressort(...) ni A.clip(...) : sa force de retour n'est pas vérifiée",
                           conseil="Déclarer A.ressort(nom, frottement_N, L=, h=, w=, precharge=, course=) si elle doit revenir toute seule."))
    return out


def _vue_mvt(mv):
    """Rotation : on regarde le long de l'axe (on voit tourner). Translation : vue iso."""
    if mv["type"] in ("translation", "vissage"): return "Iso avant"     # vissage : on voit le bouchon monter / descendre
    d = -np.asarray(mv["axe"], float); d /= np.linalg.norm(d)
    up = (0, 1, 0) if abs(d[2]) > 0.9 else (0, 0, 1)
    return (tuple(d), up)


def planche_mouvements(meshes, A, chemin):
    """Pour chaque mouvement : 5 positions sur la course (0, 25, 50, 75, 100 %) + 1 vue iso,
    et, s'il y a un blocage, un ZOOM sur l'endroit qui touche (rouge, cercle)."""
    from PIL import Image, ImageDraw
    mvs = getattr(A, "mouvements", [])
    if not mvs: return None
    noms = list(meshes); cols = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(noms)}
    places = {}
    for n, m in meshes.items():
        mm = m.copy(); mm.apply_transform(A.poses.get(n, np.eye(4))); places[n] = mm
    T = 380; C = 3; bloc = getattr(A, "_mvt_blocages", {})
    hauteurs = [(2 + (1 if mv["titre"] in bloc else 0)) for mv in mvs]
    H = sum(h * (T + 30) + 40 for h in hauteurs)
    fond = Image.new("RGB", (T * C, H), "white"); dr = ImageDraw.Draw(fond)
    y0 = 0
    for i, mv in enumerate(mvs):
        dr.text((10, y0 + 10), f"Mouvement : {mv['titre']}", fill=(20, 20, 30), font=_fnt(19)); y0 += 40
        bougent = [mv["piece"]] + [e["piece"] for e in mv["entraine"]]
        etendue = mv["a"] - mv["de"]; unite = " mm" if mv["type"] == "translation" else "°"
        vue = _vue_mvt(mv)
        cases = [(f"{int(f * 100)} % ({mv['de'] + etendue * f:.0f}{unite})", mv["de"] + etendue * f, vue, None) for f in (0, 0.25, 0.5, 0.75, 1.0)]
        cases.append(("vue iso (début)", mv["de"], "Iso avant", None))
        if mv["titre"] in bloc:
            v, Im = bloc[mv["titre"]]
            cases += [(f"PROBLÈME à {v:.1f}{unite}", v, vue, Im), (f"ZOOM sur l'endroit", v, vue, ("zoom", Im)), (f"ZOOM iso", v, "Iso avant", ("zoom", Im))]
        cadres = {}
        for k, (lab, v, vu, Im) in enumerate(cases):
            rel = poses_mouvement(mv, v)
            mc = []
            for n in noms:
                if n in bougent:
                    mk = meshes[n].copy(); mk.apply_transform(rel[n] @ A.poses.get(n, np.eye(4))); mc.append((mk, cols[n]))
                else:
                    mc.append((places[n], tuple(0.6 + 0.4 * c for c in cols[n])))
            zoom = isinstance(Im, tuple)
            Ir = Im[1] if zoom else Im
            r, u, d = _camera(*VUES[vu]) if isinstance(vu, str) else _camera(*vu)
            if Ir is not None and len(Ir.faces):
                rouge = Ir.copy(); rouge.apply_translation(-d * 0.08)   # posé devant pour être visible
                mc.append((rouge, (0.95, 0.08, 0.08)))
            if zoom and Ir is not None and len(Ir.faces):
                c0 = Ir.centroid; P = np.array([c0 @ r, c0 @ u]); demi = max(6.0, float(Ir.extents.max()) * 2.5)
                cadre = (P - demi, P + demi)
            else:
                cle = str(vu)
                if cle not in cadres:
                    Vall = np.vstack([m.vertices for m, _ in mc]); P = np.c_[Vall @ r, Vall @ u]
                    pad = (P.max(0) - P.min(0)) * 0.06; cadres[cle] = (P.min(0) - pad, P.max(0) + pad)
                cadre = cadres[cle]
            im, (lo2, hi2), ech = rendre_vue(mc, vu, T, cadre=cadre)
            if Ir is not None and len(Ir.faces):
                cxy = (lo2 + hi2) / 2; p = Ir.centroid
                px = (p @ r - cxy[0]) * ech + T / 2; py = T / 2 - (p @ u - cxy[1]) * ech
                d2 = ImageDraw.Draw(im)
                rr0 = 26 if zoom else 16
                for rr in (rr0, rr0 + 1, rr0 + 2): d2.ellipse([px - rr, py - rr, px + rr, py + rr], outline=(230, 20, 20))
            x = (k % C) * T; y = y0 + (k // C) * (T + 30)
            fond.paste(im, (x, y + 26))
            dr.text((x + 8, y + 4), lab, fill=(200, 20, 20) if Ir is not None else (40, 40, 50), font=_fnt(16))
            dr.rectangle([x, y + 26, x + T - 1, y + 26 + T - 1], outline=(225, 225, 230))
        y0 += hauteurs[i] * (T + 30)
    fond.save(chemin); return chemin


# ----------------------------------------------------------------------------
# BLOC 2 — Vraies pièces standard : vis, écrous, rondelles, roulements, filets,
# trous compensés FDM, catalogue des pièces achetées, ajustements
# ----------------------------------------------------------------------------
# Cotes ISO (source : normes citées) + compensation FDM buse 0,4 (trous imprimés ~0,1-0,2 mm trop petits).
VIS_ISO = {   # pas, Ø tête CHC ISO 4762, haut. tête, Ø tête fraisée ISO 10642, entre-plats écrou ISO 4032, haut. écrou, Ø rondelle ISO 7089
    "M2":   dict(pas=0.4,  tete_chc=3.8,  h_chc=2.0, tete_fr=4.4,   ecrou=4.0,  h_ecrou=1.6, rondelle=5.0, e_rondelle=0.3),
    "M2.5": dict(pas=0.45, tete_chc=4.5,  h_chc=2.5, tete_fr=5.5,   ecrou=5.0,  h_ecrou=2.0, rondelle=6.0, e_rondelle=0.5),
    "M3":   dict(pas=0.5,  tete_chc=5.5,  h_chc=3.0, tete_fr=6.72,  ecrou=5.5,  h_ecrou=2.4, rondelle=7.0, e_rondelle=0.5),
    "M4":   dict(pas=0.7,  tete_chc=7.0,  h_chc=4.0, tete_fr=8.96,  ecrou=7.0,  h_ecrou=3.2, rondelle=9.0, e_rondelle=0.8),
    "M5":   dict(pas=0.8,  tete_chc=8.5,  h_chc=5.0, tete_fr=11.2,  ecrou=8.0,  h_ecrou=4.7, rondelle=10.0, e_rondelle=1.0),
    "M6":   dict(pas=1.0,  tete_chc=10.0, h_chc=6.0, tete_fr=13.44, ecrou=10.0, h_ecrou=5.2, rondelle=12.0, e_rondelle=1.6),
    "M8":   dict(pas=1.25, tete_chc=13.0, h_chc=8.0, tete_fr=17.92, ecrou=13.0, h_ecrou=6.8, rondelle=16.0, e_rondelle=1.6),
}
# Trous FDM conseillés (Ø imprimé, P2S buse 0,4, PETG/PLA). Inserts : valeurs type CNC Kitchen / Ruthex -> confirmer sur la fiche.
TROUS_FDM = {
    "passage":        {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 9.0},   # ISO 273 moyen (+0,1 à 0,2 pour FDM vertical)
    "auto_taraudage": {"M2": 1.7, "M2.5": 2.1, "M3": 2.6, "M4": 3.5, "M5": 4.4, "M6": 5.3},
    "insert":         {"M2": 3.2, "M2.5": 3.6, "M3": 4.0, "M4": 5.6, "M5": 6.4, "M6": 8.0},
    "insert_prof":    {"M2": 4.0, "M2.5": 5.0, "M3": 5.7, "M4": 8.1, "M5": 9.5, "M6": 12.7},
}
JEU_TETE = 0.6     # Ø de lamage = Ø tête + 0,6
JEU_ECROU = 0.3    # entre-plats du logement = écrou + 0,3


def trou_vis(taille="M3", type="passage", profondeur=None, tete="chc", prof_tete=None, insert_prof=None, x=0, y=0, z=0, vers="-Z"):
    """Solide à SOUSTRAIRE (CadQuery) pour un trou de vis compensé FDM, ouverture en z, qui descend (vers="-Z").
    type : "passage" | "auto_taraudage" | "insert" | "ecrou_captif" | "fraise" | "lamage".
    tete : "chc" (lamage pour tête cylindrique) | "fraisee" | None. Le trou part de z et va vers le bas."""
    import cadquery as cq
    V = VIS_ISO[taille]
    if profondeur is None:   # insert : longueur de l'insert + 1 mm (plastique repoussé au fond)
        profondeur = TROUS_FDM["insert_prof"][taille] + 1.0 if type == "insert" else 10.0
    d = TROUS_FDM["insert" if type == "insert" else ("auto_taraudage" if type == "auto_taraudage" else "passage")][taille]
    s = cq.Workplane("XY").circle(d / 2).extrude(profondeur).translate((0, 0, -profondeur))
    if type == "insert":   # chanfrein d'entrée 0,5 mm pour centrer l'insert
        s = s.union(cq.Workplane("XY").circle(d / 2 + 0.5).workplane(offset=-0.5).circle(d / 2).loft().translate((0, 0, 0)))
    if type == "lamage" or (tete == "chc" and type in ("passage", "lamage")):
        hp = prof_tete if prof_tete is not None else V["h_chc"] + 0.4
        s = s.union(cq.Workplane("XY").circle((V["tete_chc"] + JEU_TETE) / 2).extrude(hp).translate((0, 0, -hp)))
    if type == "fraise" or tete == "fraisee":
        dt = V["tete_fr"] + 0.4; h = (dt - d) / 2   # 90°
        s = s.union(cq.Workplane("XY").circle(dt / 2).workplane(offset=-h).circle(d / 2).loft())
    if type == "ecrou_captif":
        e = V["ecrou"] + JEU_ECROU; hn = V["h_ecrou"] + 0.4
        s = s.union(cq.Workplane("XY").polygon(6, e / math.cos(math.radians(30))).extrude(hn).translate((0, 0, -profondeur)))
    if vers == "+Z":
        s = s.mirror("XY")
    return s.translate((x, y, z))


def _depuis_b123(obj):
    import cadquery as cq
    return cq.Workplane("XY").add(cq.Shape.cast(obj.wrapped))


def vis(taille="M3", longueur=12, type="chc"):
    """Vraie vis ISO (bd_warehouse), tête en haut à z = 0, tige vers -Z. Pour l'assemblage (pièce achetée)."""
    from bd_warehouse import fastener as F
    pas = VIS_ISO[taille]["pas"]; nom = f"{taille}-{pas:g}"
    cls = {"chc": (F.SocketHeadCapScrew, "iso4762"), "fraisee": (F.CounterSunkScrew, "iso10642"),
           "bombee": (F.ButtonHeadScrew, "iso7380_1"), "hex": (F.HexHeadScrew, "iso4014")}[type]
    v = _depuis_b123(cls[0](nom, longueur, cls[1], simple=True))
    # bd_warehouse « simple » dessine la tige au Ø du fond de filet : on la remet au Ø nominal (le filet prend toute cette place)
    import cadquery as cq
    D = float(taille[1:])
    return v.union(cq.Workplane("XY").circle(D / 2).extrude(longueur).translate((0, 0, -longueur)))


def ecrou(taille="M3"):
    from bd_warehouse import fastener as F
    return _depuis_b123(F.HexNut(f"{taille}-{VIS_ISO[taille]['pas']:g}", "iso4032", simple=True))


def rondelle(taille="M3"):
    from bd_warehouse import fastener as F
    return _depuis_b123(F.PlainWasher(taille, "iso7089"))


ROULEMENTS = {"608": "M8-22-7", "625": "M5-16-5", "623": "M3-10-4", "6000": "M10-26-8", "6001": "M12-28-8", "6200": "M10-30-9", "6800": "M10-19-5"}


def roulement(ref="608"):
    """Vrai roulement à billes (bd_warehouse) : 608 = 8×22×7 (planches à roulettes, spinners)."""
    from bd_warehouse.bearing import SingleRowDeepGrooveBallBearing as B
    ref = str(ref); code = ROULEMENTS.get(ref, ref)
    try:
        return _depuis_b123(B(code))
    except ValueError:
        # taille absente de bd_warehouse (ex. 6001 = 12 × 28 × 8) : dessinée à la main (bagues + cage simplifiée, cotes ISO 15 exactes)
        import cadquery as cq
        d, D, Bw = (float(x) for x in code.lstrip("M").split("-"))
        e = (D - d) / 4
        ext = cq.Workplane("XY").circle(D / 2).circle(D / 2 - e).extrude(Bw)
        intr = cq.Workplane("XY").circle(d / 2 + e).circle(d / 2).extrude(Bw)
        cage = cq.Workplane("XY").circle(D / 2 - e).circle(d / 2 + e).extrude(Bw - 1.0).translate((0, 0, 0.5))
        return ext.union(intr).union(cage)


def logement_roulement(ref="608", serrage="leger"):
    """Ø à imprimer pour loger un roulement. serrage (Ø obtenu − Ø du roulement) : 'presse' (−0,15 au Ø, soit ≈ −0,08 par côté, comme
    « presse » de calc ajustement → tient seul), 'leger' (+0,05), 'libre' (+0,20)."""
    ref = str(ref); dims = ROULEMENTS.get(ref, ref).split("-"); D = float(dims[1]); B = float(dims[2])
    s_ = normaliser_cible(serrage); s_ = {"leger": "leger", "presse": "presse", "serre": "presse", "glissant_dur": "presse", "libre": "libre", "glissant": "leger"}.get(s_, s_)
    if s_ not in ("presse", "leger", "libre"): raise ValueError(f"serrage « {serrage} » inconnu : presse, leger ou libre")
    imprime = {"presse": -0.15, "leger": 0.05, "libre": 0.20}[s_]     # Ø réellement obtenu − Ø du roulement
    return dict(diametre=round(D + imprime + 0.15, 2), profondeur=B + 0.2, diametre_imprime_attendu=round(D + imprime, 2),
                note="dessiné = obtenu + 0,15 (trous verticaux imprimés ~0,15 mm plus petits). Presse = 0,15 mm de serrage au Ø. "
                     "Trou HORIZONTAL : utiliser goutte() (il s'affaisse). Tenue critique : anneau d'essai de 2 mm de haut.")


def filet(taille="M8", longueur=10.0, externe=True, compensation=None):
    """Filet ISO imprimable (≥ M5 conseillé). Externe : tige filetée pleine. Interne : volume à SOUSTRAIRE (taraudage).
    compensation FDM par défaut : 0,15 mm (externe aminci, interne élargi)."""
    import cadquery as cq
    from bd_warehouse.thread import IsoThread
    D = float(taille[1:]); P = VIS_ISO.get(taille, dict(pas=None))["pas"] or {10: 1.5, 12: 1.75}.get(int(D), 1.5)
    c = 0.15 if compensation is None else compensation
    if D < 5: raise ValueError("Filets imprimés < M5 : trop fins pour une buse 0,4 — utiliser un insert ou une vis auto-taraudeuse.")
    if not externe and D > 12:
        raise ValueError(f"Taraudage ISO {taille} refusé : au-delà de M12, un filet ISO fin est fragile à l'impression et lourd à calculer. "
                         "Bouchon / couvercle vissé → recette etui_visse / pot_visse (lc3d_recettes) ou composant n° 5 (filet 45°, pas 4). "
                         "Vrai standard imposé → Atelier.tarauder(...).")
    th = IsoThread(major_diameter=D, pitch=P, length=longueur, external=externe, end_finishes=("chamfer", "chamfer") if externe else ("square", "square"),
                   manufacturing_compensation=c)
    fil = cq.Shape.cast(th.wrapped)
    h = 0.6134 * P if externe else 0.5413 * P
    if externe:
        coeur = cq.Workplane("XY").circle(D / 2 - h - c + 0.05).extrude(longueur)
        return coeur.union(cq.Workplane("XY").add(fil))
    coeur = cq.Workplane("XY").circle((D - 1.0825 * P) / 2 + 0.15).extrude(longueur)   # crête du taraudage tronquée de 0,15 (vérifié : vissage sans contact M5-M8)
    return coeur.union(cq.Workplane("XY").add(fil))


LONGUEURS_VIS = [3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80]


PLAGE_LONGUEURS = {"M2": (3, 20), "M2.5": (4, 25), "M3": (4, 40), "M4": (5, 50), "M5": (6, 60), "M6": (8, 80), "M8": (10, 80)}


def calc_vis(taille="M3", traversee=6.0, prof_trou=7.0, prise="insert", lamage=0.0, tete="chc", rondelle=False):
    """Quelle longueur de vis acheter. traversee : épaisseur de la pièce traversée (mm, du dessus jusqu'au joint);
    prof_trou : profondeur du trou fileté / insert sous le joint; lamage : profondeur où la tête cylindrique est enfoncée.
    tete 'fraisee' : la longueur d'une vis fraisée INCLUT la tête (affleurante). prise : 'insert' | 'auto_taraudage' | 'ecrou'."""
    D = float(taille[1:]); V = VIS_ISO[taille]
    t = traversee if tete == "fraisee" else max(0.0, traversee - lamage)
    if rondelle: t += V["e_rondelle"]
    mini = {"insert": 0.8 * TROUS_FDM["insert_prof"].get(taille, 2 * D), "auto_taraudage": 2.5 * D, "ecrou": V["h_ecrou"] + 2 * V["pas"]}[prise]
    maxi = prof_trou - 0.5 if prise != "ecrou" else V["h_ecrou"] + 6 * V["pas"]
    lo, hi = PLAGE_LONGUEURS.get(taille, (3, 80))
    ok = [L for L in LONGUEURS_VIS if lo <= L <= hi and t + mini <= L <= t + maxi]
    if not ok:
        return dict(verdict=ECHEC, detail=f"aucune longueur {taille} standard entre {t + mini:.1f} et {t + maxi:.1f} mm", conseil="Approfondir le trou ou changer l'épaisseur serrée.")
    return dict(verdict=OK, longueur=ok[0], autres=ok[1:], detail=f"vis {taille} × {ok[0]} mm ({'tête fraisée incluse' if tete == 'fraisee' else 'sous tête'}) : prise {ok[0] - t:.1f} mm (min {mini:.1f}), max {t + maxi:.1f}")


def calc_bossage(taille="M3", type="insert"):
    """Ø extérieur minimal d'un bossage (tube) autour d'un trou de vis/insert : mur ≥ 2 mm et ≥ 0,5 × Ø du trou."""
    d = TROUS_FDM["insert" if type == "insert" else ("auto_taraudage" if type == "auto_taraudage" else "passage")][taille]
    mur = max(2.0, 0.5 * d) + (0.4 if type == "insert" else 0.0)   # l'insert chauffé pousse le plastique : un peu plus de mur
    return dict(trou=d, diametre_bossage_min=round(d + 2 * mur, 1), distance_bord_min=round(mur + d / 2, 1),
                profondeur_trou=round(TROUS_FDM["insert_prof"].get(taille, 2 * d) + 1.0, 1) if type == "insert" else None)


def goutte(d, longueur, axe="X"):
    """Trou HORIZONTAL imprimable sans support : forme en goutte (pointe à 45° vers le haut) + 0,1 mm (affaissement)."""
    import cadquery as cq
    r = d / 2 + 0.1
    prof = cq.Workplane("YZ").circle(r).extrude(longueur / 2, both=True)
    pointe = (cq.Workplane("YZ").polyline([(-r * math.cos(math.radians(45)), r * math.sin(math.radians(45))), (0, r * math.sqrt(2)),
                                           (r * math.cos(math.radians(45)), r * math.sin(math.radians(45)))]).close().extrude(longueur / 2, both=True))
    g = prof.union(pointe)
    return g if axe == "X" else g.rotate((0, 0, 0), (0, 0, 1), 90)


# Pièces achetées : cotes SOURCÉES + confiance + quoi vérifier (une enveloppe simple pour les collisions/passages)
CATALOGUE = {
    "pile_AA":     dict(forme=("cyl", 14.5, 50.5), source="IEC 60086 LR6 (max Ø14,5 × 50,5)", confiance="norme", verifier=["borne + dépasse ~1 mm"]),
    "pile_AAA":    dict(forme=("cyl", 10.5, 44.5), source="IEC 60086 LR03 (max Ø10,5 × 44,5)", confiance="norme", verifier=[]),
    "pile_CR2032": dict(forme=("cyl", 20.0, 3.2), source="IEC 60086 CR2032", confiance="norme", verifier=[]),
    "pile_18650":  dict(forme=("cyl", 18.6, 65.2), source="format 18650 (protégées jusqu'à ~69 mm)", confiance="type", verifier=["longueur réelle si protection"]),
    "roulement_608": dict(forme=("anneau", 22.0, 7.0, 8.0), source="ISO 15 (608 : 8×22×7)", confiance="norme", verifier=[]),
    "aimant_6x2":  dict(forme=("cyl", 6.0, 2.0), source="néodyme type, tolérance ±0,05-0,1", confiance="type", verifier=["Ø et épaisseur au pied à coulisse"]),
    "aimant_6x3":  dict(forme=("cyl", 6.0, 3.0), source="néodyme type", confiance="type", verifier=["Ø et épaisseur"]),
    "aimant_8x3":  dict(forme=("cyl", 8.0, 3.0), source="néodyme type", confiance="type", verifier=["Ø et épaisseur"]),
    "aimant_10x2": dict(forme=("cyl", 10.0, 2.0), source="néodyme type", confiance="type", verifier=["Ø et épaisseur"]),
    "aimant_10x3": dict(forme=("cyl", 10.0, 3.0), source="néodyme type", confiance="type", verifier=["Ø et épaisseur"]),
    "ressort_stylo": dict(forme=("cyl", 4.5, 22.0), source="typique (très variable)", confiance="à mesurer", verifier=["Ø extérieur", "longueur libre", "Ø du fil (k ≈ G·d⁴/(8·D³·n))"]),
    "douille_E26": dict(forme=("cyl", 40.0, 60.0), source="filet E26 = 26 mm (ANSI C81.61); corps de douille variable", confiance="à mesurer", verifier=["Ø du corps", "bague de fixation", "longueur"]),
    "douille_E27": dict(forme=("cyl", 40.0, 60.0), source="filet E27 = 27 mm (IEC 60061); corps variable", confiance="à mesurer", verifier=["Ø du corps", "bague", "longueur"]),
    "prise_NEMA_1_15": dict(forme=("boite", 20.0, 32.0, 28.0), source="fiche moulée typique 2 broches", confiance="à mesurer", verifier=["largeur × épaisseur × longueur de la fiche moulée"]),
    "ESP32_devkit": dict(forme=("boite", 28.0, 55.0, 13.0), source="DevKitC 38 broches typique (varie selon le clone)", confiance="à mesurer", verifier=["largeur", "longueur", "hauteur avec broches", "position de la prise USB"],
                         alias=("esp32",), connecteurs=[dict(type="micro_usb", pos=(0.0, -27.5, 11.4), dir=(0, -1, 0), haut=(0, 0, 1), nom="micro-USB")]),
    "ESP32_devkit_usbc": dict(forme=("boite", 28.0, 55.0, 13.0), source="DevKitC 38 broches, version USB-C (varie selon le clone)", confiance="à mesurer", verifier=["largeur", "longueur", "hauteur avec broches", "position de la prise USB-C"],
                              alias=("esp32_c", "esp32c", "esp32_usbc"), connecteurs=[dict(type="usb_c", pos=(0.0, -27.5, 11.7), dir=(0, -1, 0), haut=(0, 0, 1), nom="USB-C")]),
    # Arduino Uno R3 : 68,6 × 53,3 × 1,6 (docs.arduino.cc, fiche UNO R3). Repère du plan officiel : origine au coin bas-gauche du circuit,
    # X le long des 68,6 mm, prises sur le bord x = 0, dessous du circuit à z = 0. Prise USB-B 12 × 16 × 11 qui DÉPASSE de 6,5 mm du bord
    # (y 32,0-44,0), jack barillet 9 × 13,2 × 10,9 qui dépasse de 1,8 mm (y 2,2-11,2) : composants ngComponents/unoHoles de la
    # bibliothèque OpenSCAD « Arduino mounting library » (kellyegan, recoupée avec les trous officiels 14,0/2,5 · 15,3/50,7 · 66,1/7,6 · 66,1/35,5);
    # hauteur USB + pattes ≈ 15,4 mm mesurée (forum.arduino.cc/t/how-tall-is-the-arduino-uno/660699) → USB ≈ 11 mm au-dessus du circuit.
    "arduino_uno": dict(forme=("composite", [(0.0, 0.0, 0.0, 68.6, 53.3, 1.6), (-6.5, 32.0, 1.6, 9.5, 44.0, 12.6), (-1.8, 2.2, 1.6, 11.4, 11.2, 12.5)]),
                        source="Arduino UNO R3 (docs.arduino.cc) + bibliothèque OpenSCAD Arduino (prises)", confiance="fabricant", alias=("arduino", "uno"),
                        verifier=["clone : position de l'USB (certains clones ont un USB-B décalé ou un micro-USB/USB-C)"],
                        connecteurs=[dict(type="usb_b", pos=(-6.5, 38.0, 7.1), dir=(-1, 0, 0), haut=(0, 0, 1), nom="USB-B"),
                                     dict(type="barillet_5.5", pos=(-1.8, 6.7, 7.9), dir=(-1, 0, 0), haut=(0, 0, 1), nom="jack 5,5 mm")]),
    # Fiches de câble seules (pour passage_cable(gabarit="fiche_USB_B") : surmoulage + longueur rigide, voir FICHES_CABLE)
    "fiche_USB_A": dict(forme=("boite", 16.0, 8.5, 42.0), source="USB 2.0 §6 (surmoulage A ≤ 16,0 × 8,0) + câbles réels", confiance="type", verifier=[]),
    "fiche_USB_B": dict(forme=("boite", 16.0, 15.5, 44.0), source="USB 2.0 §6 + pire câble réel mesuré 16 × 15,5", confiance="type", verifier=[]),
    "fiche_USB_C": dict(forme=("boite", 12.35, 6.5, 31.0), source="USB Type-C (surmoulage de référence 12,35 × 6,5)", confiance="norme", verifier=[]),
    "fiche_micro_USB": dict(forme=("boite", 10.5, 7.5, 25.5), source="micro-USB : surmoulage courant ≈ 10,5 × 7,5", confiance="type", verifier=["surmoulage du câble réel"]),
    "fiche_barillet_5.5": dict(forme=("cyl", 11.0, 35.0), source="fiche CC 5,5 × 2,1 : surmoulage Ø 9-11 (pire 11)", confiance="type", verifier=["Ø du surmoulage"]),
    "iPhone_13":   dict(forme=("boite", 71.5, 146.7, 7.65), source="Apple (fiche technique)", confiance="fabricant", verifier=["étui en plus ?"]),
    "carte_credit": dict(forme=("boite", 85.6, 53.98, 0.76), source="ISO/IEC 7810 ID-1", confiance="norme", verifier=[]),
    "canette_355": dict(forme=("cyl", 66.0, 122.0), source="canette 355 ml standard nord-américaine", confiance="type", verifier=[]),
}


def piece_achetee(nom, **surcharge):
    """Enveloppe CadQuery d'une pièce achetée du catalogue (pour vérifier que ça rentre / ça passe), + sa fiche.
    surcharge : remplacer une cote mesurée, ex. piece_achetee('ressort_stylo', d=4.2, L=19.5)."""
    import cadquery as cq
    f = dict(CATALOGUE[nom]); t = f["forme"]
    if t[0] == "cyl":
        d = surcharge.get("d", t[1]); L = surcharge.get("L", t[2])
        s = cq.Workplane("XY").circle(d / 2).extrude(L)
    elif t[0] == "anneau":
        D = surcharge.get("D", t[1]); B = surcharge.get("B", t[2]); d = surcharge.get("d", t[3])
        s = cq.Workplane("XY").circle(D / 2).circle(d / 2).extrude(B)
    elif t[0] == "composite":                 # plusieurs boîtes (x0, y0, z0, x1, y1, z1) : circuit + prises qui dépassent
        s = None
        for x0, y0, z0, x1, y1, z1 in t[1]:
            b_ = cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0).translate(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
            s = b_ if s is None else s.union(b_)
    else:
        lx = surcharge.get("x", t[1]); ly = surcharge.get("y", t[2]); lz = surcharge.get("z", t[3])
        s = cq.Workplane("XY").box(lx, ly, lz).translate((0, 0, lz / 2))
    f["mesure"] = bool(surcharge)
    f["nom"] = nom
    if f.get("connecteurs"):                  # la forme PORTE ses prises : Piece(nom, s, role="achetee") → vérifiées toutes seules
        f["connecteurs"] = [dict(c) for c in f["connecteurs"]]
        try: s._lc3d_connecteurs = f["connecteurs"]; s._lc3d_catalogue = nom
        except Exception: pass
    return s, f


# --- Fiches de câble RÉELLES (essai réel : trou de 13,2 mm, la fiche USB-B surmoulée ne pouvait pas atteindre la prise).
# profil : [(distance depuis la face de la prise où ce tronçon commence, largeur, hauteur)] — le surmoulage grossit vers le câble;
# rigide : longueur de fiche rigide (au-delà, le câble plie : obstacle = ⚠️); insertion : (largeur, hauteur, profondeur) de la partie qui entre.
# Sources : USB 2.0 spec ch. 6 (fig. 6-8 à 6-10 : surmoulage A ≤ 16,0 × 8,0; B ≤ 11,5 / 10,5 selon la spec — les câbles réels
#   dépassent : B mesuré jusqu'à 16 × 15,5 avec le serre-câble, d'où le pire cas retenu) — https://studfile.net/preview/3568652/page:13/ ;
# USB Type-C Cable & Connector spec (IEC 62680-1-3) : surmoulage de référence 12,35 × 6,5 — contour 12,35 repris dans
#   https://git.cuvoodoo.info/kingkevin/qeda_library (connector_usb-c_plug.yaml), largeur de prise 8,34 / profondeur d'accouplement
#   4,7-6,6 (Molex, https://mouser.com/pdfdocs/MolexUSBType-C.pdf) ;
# micro-USB 1.01 §4.5.2 (fig. 4-5, surmoulage « rectangulaire chanfreiné ») : ≈ 10,5 × 7,5 sur les câbles courants (à mesurer si gros câble) ;
# fiche CC 5,5 × 2,1 × 9,5 : surmoulage Ø 9 à 11 (pire 11). Valeurs « pire câble réel » : prudent, pas la cote mini de la norme.
FICHES_CABLE = {
    "usb_a":        dict(nom="fiche USB-A", rond=False, profil=[(0.0, 16.0, 8.5)], rigide=30.0, insertion=(12.0, 4.5, 12.0)),
    "usb_b":        dict(nom="fiche USB-B", rond=False, profil=[(0.0, 16.0, 11.0), (10.0, 16.0, 15.5)], rigide=35.0, insertion=(8.5, 7.8, 9.0)),
    "usb_c":        dict(nom="fiche USB-C", rond=False, profil=[(0.0, 12.35, 6.5)], rigide=25.0, insertion=(8.34, 2.56, 6.6)),
    "micro_usb":    dict(nom="fiche micro-USB", rond=False, profil=[(0.0, 10.5, 7.5)], rigide=20.0, insertion=(6.85, 1.8, 5.5)),
    "barillet_5.5": dict(nom="fiche barillet 5,5 mm", rond=True, profil=[(0.0, 11.0, 11.0)], rigide=25.0, insertion=(5.5, 5.5, 9.5)),
}
_ALIAS_FICHES = {"usba": "usb_a", "usb_a": "usb_a", "usbb": "usb_b", "usb_b": "usb_b", "usbc": "usb_c", "usb_c": "usb_c", "typec": "usb_c",
                 "microusb": "micro_usb", "micro_usb": "micro_usb", "microb": "micro_usb", "barillet": "barillet_5.5", "barillet_5.5": "barillet_5.5",
                 "barillet55": "barillet_5.5", "jack": "barillet_5.5", "jack_5.5": "barillet_5.5", "dc": "barillet_5.5", "barrel": "barillet_5.5"}


def _type_fiche(t):
    k = str(t).lower().replace("-", "_").replace(" ", "_").replace(",", ".")
    return k if k in FICHES_CABLE else _ALIAS_FICHES.get(k) or _ALIAS_FICHES.get(k.replace("_", "").replace(".", ""))


_MOTS_ELECTRONIQUE = ("arduino", "esp32", "esp8266", "raspberry", "pico", "pcb", "carte", "uno", "nano", "usb", "jack", "chargeur", "module")


def _connecteurs_piece(nom, pc, mesh_brut):
    """Prises d'une pièce achetée, dans son repère : portées par la forme (piece_achetee), par Piece.connecteurs, ou retrouvées
    par le NOM (« arduino », « esp32 »…) si l'enveloppe correspond au catalogue (même taille → décalage appliqué). (liste, note)"""
    conns = list(getattr(pc, "connecteurs", None) or getattr(pc.forme, "_lc3d_connecteurs", None) or [])
    if conns: return conns, None
    n = nom.lower()
    cand = [k for k, f in CATALOGUE.items() if f.get("connecteurs") and (k.lower() in n or any(a in n for a in f.get("alias", ())))]
    cand.sort(key=lambda k: -max([len(k)] + [len(a) for a in CATALOGUE[k].get("alias", ()) if a in n]))
    for k in cand:
        try:
            s_, f_ = piece_achetee(k); env = vers_mesh(s_)
        except Exception:
            continue
        if mesh_brut is not None and np.allclose(env.extents, mesh_brut.extents, atol=0.6):
            dec = mesh_brut.bounds[0] - env.bounds[0]
            return [dict(c, pos=tuple(np.asarray(c["pos"], float) + dec)) for c in f_["connecteurs"]], f"prises du catalogue « {k} » (reconnue par le nom et la taille)"
    if cand or any(m in n for m in _MOTS_ELECTRONIQUE):
        return [], (f"« {nom} » ressemble à {cand[0]} mais sa taille ne correspond pas au catalogue" if cand else f"« {nom} » ressemble à une carte/pièce électronique")
    return [], None


def _test_fiche(conn, M, places, jeu=0.5, pas=0.25):
    """Une VRAIE fiche (surmoulage) arrive dans l'axe de la prise jusqu'à l'insertion complète : rayons parallèles à l'axe sur toute
    la section de la fiche (+ jeu), tirés depuis la face de la prise vers l'extérieur. Retourne (statut, détail, conseil, lieux)."""
    F = FICHES_CABLE[conn["type"]]
    R3 = np.asarray(M, float)[:3, :3]; T = np.asarray(M, float)[:3, 3]
    p0 = R3 @ np.asarray(conn["pos"], float) + T
    d = R3 @ np.asarray(conn["dir"], float); d /= np.linalg.norm(d)
    h0 = np.asarray(conn.get("haut") or ((0, 0, 1) if abs(conn["dir"][2]) < 0.9 else (0, 1, 0)), float)
    h = R3 @ h0; h = h - d * (h @ d); h /= np.linalg.norm(h)
    u = np.cross(h, d); u /= np.linalg.norm(u)
    Wm = max(w for _, w, _ in F["profil"]) + 2 * jeu; Hm = max(z for _, _, z in F["profil"]) + 2 * jeu
    gu = np.arange(-Wm / 2 + pas / 2, Wm / 2, pas); gv = np.arange(-Hm / 2 + pas / 2, Hm / 2, pas)     # centres de cellules : un trou « juste » n'est pas touché par un rayon rasant
    U, V = [a.ravel() for a in np.meshgrid(gu, gv)]
    def dans(w, z, uu, vv):
        return ((uu / (w / 2 + jeu)) ** 2 + (vv / (z / 2 + jeu)) ** 2 <= 1.0) if F["rond"] else ((np.abs(uu) <= w / 2 + jeu) & (np.abs(vv) <= z / 2 + jeu))
    tmin = np.full(len(U), np.inf)                      # distance depuis la face où ce point de la section devient occupé par la fiche
    for t0, w, z in F["profil"]:
        tmin = np.where(dans(w, z, U, V) & (t0 < tmin), t0, tmin)
    wi, zi, di = F["insertion"]; ins = dans(wi, zi, U, V) if not F["rond"] else ((U ** 2 + V ** 2) <= (wi / 2 + jeu) ** 2)
    tmin = np.where(ins, -di, tmin)                     # la partie qui entre dans la prise part de -profondeur
    ok_ = np.isfinite(tmin); U, V, tmin = U[ok_], V[ok_], tmin[ok_]
    orig = p0 + np.outer(U, u) + np.outer(V, h) + np.outer(tmin, d)
    dirs = np.tile(d, (len(U), 1))
    thit = np.full(len(U), np.inf); qui = np.full(len(U), "", dtype=object)
    for nom, m in places.items():
        try:
            loc, ir, _ = m.ray.intersects_location(orig, dirs, multiple_hits=False)
        except Exception:
            continue
        if not len(ir): continue
        t_ = tmin[ir] + np.einsum("ij,j->i", loc - orig[ir], d)
        mieux = t_ < thit[ir]
        thit[ir[mieux]] = t_[mieux]; qui[ir[mieux]] = nom
    bloque = thit <= F["rigide"]; loin = np.isfinite(thit) & ~bloque
    W1, H1 = F["profil"][0][1], F["profil"][0][2]
    taille = " → ".join(f"{w:g} × {z:g}" if not F["rond"] else f"Ø {w:g}" for _, w, z in F["profil"])
    if bloque.any():
        Ub, Vb, tb = U[bloque], V[bloque], thit[bloque]
        tsec = float(np.median(tb)); W_, H_ = next(((w, z) for t0, w, z in reversed(F["profil"]) if t0 <= max(tsec, 0)), (W1, H1))
        band = 1.0
        def libre(a, b_, demi):
            sel = np.abs(b_) <= band
            hp = a[sel & (a > 0)]; hn = a[sel & (a < 0)]
            return (min(hp.min() if len(hp) else demi, demi) - max(hn.max() if len(hn) else -demi, -demi))
        fw = libre(Ub, Vb, Wm / 2); fh = libre(Vb, Ub, Hm / 2)
        mw = max(0.0, W_ - fw); mh = max(0.0, H_ - fh)
        noms_ = sorted(set(qui[bloque]))
        lieu = _pt(p0 + d * float(tb.min()))
        if F["rond"]:
            manque = f"ouverture libre ≈ Ø {min(fw, fh):.1f} mm, la fiche fait Ø {W_:g} → il manque {max(mw, mh):.1f} mm ({max(mw, mh) + 2 * jeu:.1f} avec le jeu de {jeu} mm par côté)"
        elif mw > 0.05 or mh > 0.05:
            fwt = f"{fw:.1f}" if fw < Wm - 0.3 else f"≥ {fw:.1f}"; fht = f"{fh:.1f}" if fh < Hm - 0.3 else f"≥ {fh:.1f}"
            manque = (f"ouverture libre dans l'axe ≈ {fwt} × {fht} mm, la fiche fait {W_:g} × {H_:g} → il manque " +
                      " et ".join(x for x in ((f"{mw:.1f} mm en largeur" if mw > 0.05 else ""), (f"{mh:.1f} mm en hauteur" if mh > 0.05 else "")) if x) +
                      f" (+{2 * jeu:g} mm de jeu)")
        else:
            manque = f"la fiche ({W_:g} × {H_:g}) touche le bord avec le jeu de {jeu} mm par côté : trou décentré ou trop juste (ouverture ≈ {fw:.1f} × {fh:.1f})"
        return (ECHEC, f"une vraie {F['nom']} (surmoulage {taille} mm) ne peut pas atteindre la prise : elle bute dans « {', '.join(noms_)} » à {float(tb.min()):.1f} mm de la prise; {manque}",
                f"Agrandir l'ouverture à au moins {W_ + 2 * jeu:.1f} × {H_ + 2 * jeu:.1f} mm, centrée sur l'axe de la prise (ou approcher la prise du mur)" if not F["rond"] else
                f"Ouverture Ø ≥ {W_ + 2 * jeu:.1f} mm centrée sur la prise", [lieu])
    if loin.any():
        return (AVERT, f"la {F['nom']} entre sur sa longueur rigide ({F['rigide']:g} mm), mais un obstacle (« {', '.join(sorted(set(qui[loin])))} ») est dans l'axe à {float(thit[loin].min()):.0f} mm : le câble doit arriver en biais",
                "Vérifier qu'on peut passer la fiche en biais jusqu'à l'axe, sinon ouvrir dans l'axe.", None)
    return (OK, f"une vraie {F['nom']} (surmoulage {taille} mm, +{jeu} mm de jeu) atteint la prise dans l'axe jusqu'à l'insertion complète ({F['insertion'][2]:g} mm) sans rien toucher", None, None)


def verif_connecteurs(meshes, pieces, A, en_place, jeu=0.5):
    """AUTOMATIQUE : chaque prise (USB, jack…) d'une pièce achetée doit être atteignable par une vraie fiche de câble depuis l'extérieur."""
    out = []
    imprimees = {n: en_place[n] for n, pc in pieces.items() if pc.role != "achetee" and n in en_place}
    decl = {}
    for c in getattr(A, "connecteurs", []): decl.setdefault(c["piece"], []).append(c)
    noms = [n for n, pc in pieces.items() if pc.role == "achetee"] + [n for n in decl if n in pieces and pieces[n].role != "achetee"]
    for nom in noms:
        if nom not in en_place: continue
        pc = pieces[nom]
        conns, note = ([], None)
        if pc.role == "achetee": conns, note = _connecteurs_piece(nom, pc, meshes.get(nom))
        conns = [dict(c, type=_type_fiche(c["type"]) or c["type"]) for c in conns] + decl.get(nom, [])
        if not conns:
            if note:
                out.append(res(f"Connecteur {nom}", AVERT, f"{note} : ses prises (USB, jack…) ne sont pas connues, l'accès des fiches n'est PAS vérifié",
                               conseil="Utiliser piece_achetee('arduino_uno') / piece_achetee('ESP32_devkit'), ou déclarer A.connecteur(piece, 'usb_c', position, direction)."))
            continue
        M = A.poses.get(nom, np.eye(4))
        for c in conns:
            if c["type"] not in FICHES_CABLE:
                out.append(res(f"Connecteur {nom}", AVERT, f"type de prise « {c['type']} » inconnu")); continue
            try:
                st, det, cons, lieux = _test_fiche(c, M, imprimees, jeu=jeu)
            except Exception as e:
                st, det, cons, lieux = AVERT, f"calcul impossible : {type(e).__name__}: {e}", None, None
            out.append(res(f"Connecteur {nom} : {c.get('nom') or FICHES_CABLE[c['type']]['nom']}", st, det + (f" ({note})" if note and note.startswith("prises du catalogue") else ""), conseil=cons, lieux=lieux))
    return out


AJUSTEMENTS_FDM = [   # jeu radial (par côté) mesuré sur pièce imprimée P2S, PETG -> nom de l'ajustement
    (-0.10, "presse forte (marteau, ne se démonte pas)"),
    (0.00, "presse (à la main avec force, tient tout seul)"),
    (0.10, "glissant dur (glisse en forçant un peu, ne tombe pas) — en génie « serré » = interférence : voir presse"),
    (0.20, "glissant (rentre à la main, se tient)"),
    (0.35, "libre (tourne/coulisse facilement)"),
    (0.50, "mobile (pièce qui bouge, règle LC3D)"),
    (1.00, "lâche (ballant)"),
]


def _note_tol(tol):
    if tol is None: return None
    tol = abs(float(tol))
    if tol < 0.1:
        return (f"±{tol:.2f} mm n'est PAS tenable en FDM (une imprimante bien calibrée tient ±0,1 à ±0,2 mm). Solutions : arbre/bague en acier "
                f"acheté, alésoir après impression, ou calibration (lc3d.py calibration) puis anneau d'essai de 2 mm.")
    return f"±{tol:.2f} mm : tenable en FDM avec une machine calibrée (vérifier avec un anneau d'essai de 2 mm)."


def calc_ajustement(trou=None, arbre=None, jeu=None, cible=None, alesage=None, sens=None, tol=None):
    """Sens 1 : trou et arbre (Ø dessinés) -> nom de l'ajustement obtenu.
    Sens 2 : cible='glissant' + arbre (acheté) -> Ø de TROU à dessiner.
    Sens 3 : cible='presse' + alesage (Ø du trou ACHETÉ, ex. 8 pour un 608), ou sens='arbre_imprime' -> Ø d'ARBRE imprimé à dessiner.
    cible : presse_forte, presse, glissant_dur, glissant, libre, mobile, lache (accents et « serré » acceptés). tol : tolérance voulue."""
    if cible:
        c = normaliser_cible(cible)
        for j, nom in AJUSTEMENTS_FDM:
            if normaliser_cible(nom.split(" (")[0]) == c:
                out = dict(ajustement=nom, jeu_par_cote=j)
                if alesage is not None or sens == "arbre_imprime":
                    a_ = float(alesage if alesage is not None else arbre)
                    # arbre IMPRIMÉ : sa surface sort ~xy_biais plus grosse par côté; le tableau compte déjà le trou imprimé ~trou_biais plus petit
                    d_ = a_ - 2 * (j - VARIATION_P2S["trou_biais"]) - 2 * VARIATION_P2S["xy_biais"]
                    out.update(arbre_a_dessiner=round(d_, 2), alesage_achete=a_, note="arbre imprimé dans un alésage acheté (roulement, bague)")
                else:
                    out.update(trou_a_dessiner=round((arbre or 0) + 2 * j, 2) if arbre else None)
                if tol is not None: out["tolerance"] = _note_tol(tol)
                return out
        raise ValueError(f"cible « {cible} » inconnue; choix : presse_forte, presse, glissant_dur (ancien « serré »), glissant, libre, mobile, lache")
    if jeu is None and (trou is None or arbre is None):
        raise ValueError("donner trou=… et arbre=… (Ø dessinés), ou jeu=…, ou cible=… avec arbre=… (acheté) / alesage=… (trou acheté)")
    j = jeu if jeu is not None else (trou - arbre) / 2
    nom = AJUSTEMENTS_FDM[0][1]
    for seuil, n in AJUSTEMENTS_FDM:
        if j >= seuil - 1e-9: nom = n
    out = dict(jeu_par_cote=round(j, 3), ajustement=nom, note="jeu dessiné; les trous imprimés sortent ~0,1-0,15 mm plus petits — compté dans les seuils")
    if tol is not None: out["tolerance"] = _note_tol(tol)
    return out


def normaliser_cible(c):
    import unicodedata
    c = unicodedata.normalize("NFKD", str(c).lower()).encode("ascii", "ignore").decode().strip().replace(" ", "_").replace("-", "_")
    return {"serre": "glissant_dur", "serr": "glissant_dur", "glissant_force": "glissant_dur", "presse_forte": "presse_forte", "force": "presse_forte",
            "lache": "lache", "ballant": "lache", "glisse": "glissant"}.get(c, c)


# ----------------------------------------------------------------------------
# BLOC 3 — Validation dure : corps soudés sur une ligne, règles du projet avec leur « pourquoi »,
# mémoire des erreurs, balayage de paramètres, 1 000 impressions simulées, ordre de montage
# automatique, liste de ce qui n'est PAS prouvé
# ----------------------------------------------------------------------------
def verif_corps(m, piece):
    """Une pièce = un seul solide (sauf si déclaré), et pas deux morceaux qui se touchent seulement sur une ligne ou un point
    (l'impression les sépare : ça casse au premier effort)."""
    out = []
    attendu = getattr(piece, "corps", 1)
    _, cnt = np.unique(m.edges_sorted, axis=0, return_counts=True)
    imp = bool(getattr(piece, "importee", False))
    if (cnt > 2).any():
        return [res("Morceaux soudés sur une ligne", AVERT if imp else ECHEC,
                    f"{int((cnt > 2).sum())} arête(s) partagée(s) par plus de 2 faces : des morceaux ne se touchent que par une arête ou un point (ils semblent attachés mais ne le sont pas)",
                    conseil="Faire chevaucher les morceaux d'au moins 0,3 mm (union avec recouvrement) au lieu de les mettre coin à coin.")]
    try:
        parts = _manifold(m).decompose()
        n_mf = len(parts)
    except Exception:
        return out
    n_tri = len(m.split(only_watertight=False))
    if n_mf > n_tri:
        out.append(res("Morceaux soudés sur une ligne", AVERT if imp else ECHEC,
                       f"{n_mf} solides qui ne se touchent que par une arête ou un point (ils semblent attachés mais ne le sont pas)",
                       conseil="Faire chevaucher les morceaux d'au moins 0,3 mm (union avec recouvrement) au lieu de les mettre bout à bout."))
    elif n_mf != attendu:
        out.append(res("Nombre de solides", ECHEC if (n_mf > attendu and not imp) else AVERT, f"{n_mf} solide(s) au lieu de {attendu}",
                       conseil="Un morceau ne touche pas le reste (coupé en deux par une opération?). Si c'est voulu : Piece(..., corps=N)."))
    return out


Piece.corps = 1


# --- Règles du projet (avec leur pourquoi) et mémoire des erreurs (toutes les règles apprises, pour tous les projets)
def _regle(self, nom, condition, pourquoi=""):
    """Règle du projet évaluée sur les PARAMS, ex. A.regle("jeu pivot", "trou_pivot - goupille >= 1.0", "leçon sifflet").
    condition : texte Python ou fonction p -> bool."""
    self.__dict__.setdefault("regles", []).append(dict(nom=nom, condition=condition, pourquoi=pourquoi)); return self


Assemblage.regle = _regle
FICHIER_LECONS = os.environ.get("LC3D_LECONS", os.path.join(os.path.expanduser("~"), ".lc3d", "lecons.json"))

LECONS_DE_BASE = [   # leçons vécues sur de vrais projets : s'appliquent dès que les paramètres nommés existent
    # jeu : seulement les jeux MOBILES déclarés (jeu_mobile…, ou « jeu » dans un projet qui a des mouvements/états) — un « jeu » d'emmanchement
    # voulu (bouton serré sur son axe, 0,15 mm) n'est pas un jeu mobile
    dict(nom="Jeu des pièces mobiles ≥ 0,5 mm", besoin=["jeu"], motif=r"^jeu(_mobile\w*)?$", mobile_seulement=True, condition="jeu >= 0.5", pourquoi="sous 0,5 mm, une pièce mobile imprimée frotte et reste coincée", origine="projet réel (bouton coulissant), oct. 2026"),
    dict(nom="Fentes ≥ 1,2 mm", besoin=["fente"], condition="fente >= 1.2", pourquoi="sous 1,2 mm les fentes se soudent à l'impression", origine="projet réel (poignée)"),
    dict(nom="Accroche de clip ≥ 1 mm", besoin=["accroche"], condition="accroche >= 1.0", pourquoi="clips en billes de 0,55 mm qui ne tiennent pas", origine="projet réel (crochet, manivelle)"),
    dict(nom="Bec pour l'ongle ≥ 2 mm", besoin=["bec"], condition="bec >= 2.0", pourquoi="bec trop petit : couvercle impossible à ouvrir", origine="projet réel (sifflet)"),
    dict(nom="Trou de pivot = goupille + 1,0 mm", besoin=["trou_pivot", "goupille"], condition="trou_pivot - goupille >= 1.0", pourquoi="pivot qui grippe une fois imprimé", origine="règle de montage"),
    dict(nom="Chevauchement des faces visibles ≥ 1 mm", besoin=["chevauchement"], condition="chevauchement >= 1.0", pourquoi="lumière qui passe entre deux faces bout à bout", origine="projet réel (lampe), oct. 2026"),
]


def charger_lecons():
    L = list(LECONS_DE_BASE)
    try:
        L += json.load(open(FICHIER_LECONS))
    except Exception:
        pass
    return L


def ajouter_lecon(nom, condition, pourquoi, besoin, origine=""):
    os.makedirs(os.path.dirname(FICHIER_LECONS), exist_ok=True)
    try: L = json.load(open(FICHIER_LECONS))
    except Exception: L = []
    L.append(dict(nom=nom, condition=condition, pourquoi=pourquoi, besoin=list(besoin), origine=origine, date=time.strftime("%Y-%m-%d")))
    json.dump(L, open(FICHIER_LECONS, "w"), ensure_ascii=False, indent=1)
    return len(L)


def _eval_regle(cond, p):
    if callable(cond): return bool(cond(p))
    env = {k: v for k, v in p.items() if isinstance(k, str)}
    env.update(math=math, min=min, max=max, abs=abs)
    return bool(eval(cond, {"__builtins__": {}}, env))


# ----------------------------------------------------------------------------
# EXIGENCES de l'utilisateur (consigne) > règles par défaut de LC3D
#   EXIGENCES = {"accroche": (0.4, 1.0), "jeu_axial": (0.3, 0.6), "mur_min": 1.6, "surplomb_max": 50, ...} dans le modèle,
#   ou A.exigence(nom, mini, maxi, mesure=...) dans assembly(). La plage REMPLACE la règle par défaut, LC3D vise le MILIEU
#   (milieu("accroche") dans le modèle), ❌ si la valeur MESURÉE sort de la plage, ⚠️ si elle est collée à un bord.
#   « jeu_axial » = jeu TOTAL de l'empilement (somme des deux côtés), sauf mention contraire.
# ----------------------------------------------------------------------------
EXIGENCES_CONNUES = {   # nom (et synonymes) -> (clé REGLES remplacée, sens, texte de la règle par défaut)
    "accroche": ("accroche_min", "plage", "accroche de clip ≥ 1,0 mm"),
    "jeu": ("jeu_mobile", "plage", "jeu des pièces mobiles ≥ 0,5 mm par côté"),
    "jeu_axial": (None, "plage", "jeu axial total ≥ 2 × 0,5 mm (0,5 par côté)"),
    "mur_min": ("mur_min", "mini", "mur ≥ 1,5 mm (⚠️ seulement en dessous)"),
    "fente_min": ("fente_min", "mini", "fente ≥ 1,2 mm"),
    "surplomb_max": ("surplomb_max", "maxi", "surplomb ≤ 45° (⚠️ jusqu'à 75°)"),
    "pont_max": ("pont_max", "maxi", "pont ≤ 12 mm"),
    "bec_min": ("bec_min", "mini", "bec ≥ 2 mm"),
    "angle_retenue": (None, "plage", "face de retenue : 90° si permanent, < 90° si démontable"),
    "detail_min": (None, "mini", "crêtes/sommets/nervures ≥ 2 lignes de buse (0,84 mm en 0,4), mesuré en 3D"),
    "tours_vissage": (None, "plage", "prise réelle d'un vissage ≥ 1 tour"),
    "jeu_ferme": (None, "maxi", "pièce clipsée fermée : jeu ≤ 0,5 mm"),
    "degagement": (None, "mini", "dégagement mesuré autour d'une pièce achetée"),
}
SYNONYMES_EXIGENCES = {"clip_retenue": "accroche", "retenue": "accroche", "accroche_clip": "accroche", "jeu_mobile": "jeu", "jeu_lateral": "jeu",
                       "jeu_axial_total": "jeu_axial", "mur": "mur_min", "paroi_min": "mur_min", "epaisseur_min": "mur_min", "fente": "fente_min",
                       "surplomb": "surplomb_max", "pont": "pont_max", "bec": "bec_min", "face_retenue": "angle_retenue", "alpha_retenue": "angle_retenue",
                       "crete_min": "detail_min", "sommet_min": "detail_min", "filet_min": "detail_min", "details_min": "detail_min",
                       "tours": "tours_vissage", "tours_prise": "tours_vissage", "jeu_tenue": "jeu_ferme", "hauteur_libre": "degagement", "degagement_min": "degagement"}
EXIGENCES_ACTIVES = {}     # nom canonique -> dict(mini, maxi, cible, source)


def _norm_exigence(nom, v):
    nom = SYNONYMES_EXIGENCES.get(nom, nom)
    sens = EXIGENCES_CONNUES.get(nom, (None, "plage", ""))[1]
    if isinstance(v, dict): mini, maxi = v.get("mini"), v.get("maxi")
    elif isinstance(v, (tuple, list)): mini, maxi = (list(v) + [None, None])[:2]
    elif sens == "maxi": mini, maxi = None, v
    else: mini, maxi = v, None
    mini = None if mini is None else float(mini); maxi = None if maxi is None else float(maxi)
    cible = (mini + maxi) / 2 if mini is not None and maxi is not None else (mini if maxi is None else maxi)
    return nom, dict(mini=mini, maxi=maxi, cible=cible)


def milieu(nom, defaut=None):
    """Valeur à VISER pour une exigence active (milieu de la plage). Ex. dans build() : accroche = milieu("accroche", 1.0)."""
    e = EXIGENCES_ACTIVES.get(SYNONYMES_EXIGENCES.get(nom, nom))
    return defaut if e is None or e["cible"] is None else e["cible"]


def appliquer_exigences(ex, source="EXIGENCES du modèle"):
    """Remplace les règles par défaut (REGLES) par les plages de l'utilisateur. Retourne les lignes ℹ️ du rapport. À annuler avec annuler_exigences()."""
    out = []
    for nom_, v in (ex or {}).items():
        nom, e = _norm_exigence(nom_, v); e["source"] = source
        EXIGENCES_ACTIVES[nom] = e
        cle, sens, txt = EXIGENCES_CONNUES.get(nom, (None, "plage", None))
        if cle:
            _REGLES_AVANT.setdefault(cle, REGLES[cle])
            if e["mini"] is not None and sens in ("plage", "mini"): REGLES[cle] = e["mini"]
            if e["maxi"] is not None and sens == "maxi": REGLES[cle] = e["maxi"]
        plage = _txt_plage(e)
        out.append(res(f"Consigne : {nom}", INFO, f"plage imposée {plage} (cible = milieu {e['cible']:g})" if e["cible"] is not None else f"plage imposée {plage}",
                       conseil=(f"remplace la règle par défaut LC3D : {txt}" if txt else "exigence propre au modèle (mesurée si mesure= est donnée)")))
    return out


_REGLES_AVANT = {}


def annuler_exigences():
    """Remet les règles remplacées par une consigne (seulement celles-là : la buse choisie a pu changer mur_absolu, etc.)."""
    EXIGENCES_ACTIVES.clear(); REGLES.update(_REGLES_AVANT); _REGLES_AVANT.clear()


def _txt_plage(e):
    if e["mini"] is not None and e["maxi"] is not None: return f"{e['mini']:g} à {e['maxi']:g}"
    return f"≥ {e['mini']:g}" if e["mini"] is not None else f"≤ {e['maxi']:g}"


def juger_exigence(nom, valeur, unite="mm"):
    """(statut, texte) d'une valeur MESURÉE contre l'exigence active `nom`; None si aucune exigence."""
    e = EXIGENCES_ACTIVES.get(SYNONYMES_EXIGENCES.get(nom, nom))
    if e is None or valeur is None: return None
    v = float(valeur)
    if (e["mini"] is not None and v < e["mini"] - 0.01) or (e["maxi"] is not None and v > e["maxi"] + 0.01):
        return ECHEC, f"{v:.2f} {unite} HORS de la plage imposée {_txt_plage(e)} (viser {e['cible']:g})"
    if e["mini"] is not None and e["maxi"] is not None:
        marge = 0.1 * (e["maxi"] - e["mini"])
        if v < e["mini"] + marge - 1e-9 or v > e["maxi"] - marge + 1e-9:
            return AVERT, f"{v:.2f} {unite} dans la plage {_txt_plage(e)} mais collé au bord : viser le milieu {e['cible']:g} (les variations d'impression la feront sortir)"
    return OK, f"{v:.2f} {unite} dans la plage imposée {_txt_plage(e)}"


def _exigence(self, nom, mini=None, maxi=None, mesure=None, unite="mm"):
    """Exigence de l'utilisateur (consigne). mesure : None (exigence connue : accroche, jeu, jeu_axial…), une fonction
    f(en_place) -> valeur, ou un tuple : ("jeu", a, b) distance mini · ("jeu_axial", piece, axe) course libre totale ·
    ("dimension", piece, axe) longueur de la pièce selon l'axe. La valeur MESURÉE est comparée à la plage."""
    nom_c, e = _norm_exigence(nom, (mini, maxi))
    self.__dict__.setdefault("exigences", []).append(dict(nom=nom_c, mini=e["mini"], maxi=e["maxi"], mesure=mesure, unite=unite))
    if nom_c not in EXIGENCES_ACTIVES:      # (les règles de PIÈCE — mur_min, surplomb… — se donnent dans EXIGENCES : elles servent avant assembly())
        self.__dict__.setdefault("_consigne", []).extend(appliquer_exigences({nom_c: (e["mini"], e["maxi"])}, "A.exigence"))
    return self


def _jeu_axial(self, piece, axe=(0, 0, 1), entre=None, nom=None):
    """Jeu AXIAL d'une pièce entre deux butées : LC3D la pousse le long de l'axe dans les deux sens jusqu'au contact et mesure
    la course libre TOTALE (somme des deux côtés). Comparé à l'exigence « jeu_axial » (sinon règle par défaut : ≥ 2 × jeu mobile)."""
    self.__dict__.setdefault("jeux_axiaux", []).append(dict(piece=piece, axe=tuple(map(float, axe)), entre=list(entre) if entre else None, nom=nom))
    return self


Assemblage.exigence = _exigence
Assemblage.jeu_axial = _jeu_axial


def course_libre(m, autres, d, max_mm=5.0, tol=0.01, vol_min=0.005):
    """Distance (mm) que la pièce m peut parcourir le long du vecteur unitaire d avant de toucher une des pièces `autres`."""
    d = np.asarray(d, float); d /= np.linalg.norm(d)
    autres = [o for o in autres if _paires_proches(m, o, max_mm + 0.5)]
    if not autres: return max_mm
    Mm = _manifold(m); Mo = [_manifold(o) for o in autres]
    def touche(t):
        T = Mm.translate(tuple(float(x) for x in d * t))
        return any((T ^ o).volume() > vol_min for o in Mo)
    if touche(0.0): return 0.0
    a, t = 0.0, 0.1
    while t <= max_mm and not touche(t): a = t; t = round(t + 0.1, 6)
    if t > max_mm: return max_mm
    b = t
    while b - a > tol:
        c = (a + b) / 2
        if touche(c): b = c
        else: a = c
    return round(a, 3)


def verif_exigences(A, en_place):
    """Jeux axiaux déclarés + exigences avec mesure= : mesurés sur l'assemblage livré, jugés contre la plage (consigne ou règle)."""
    out = []
    for j in getattr(A, "jeux_axiaux", []):
        p = j["piece"]
        if p not in en_place: out.append(res(f"Jeu axial {p}", ECHEC, "pièce introuvable")); continue
        autres = [en_place[n] for n in (j["entre"] or en_place) if n != p and n in en_place]
        def _mes(p=p, autres=autres, ax=j["axe"]):
            return course_libre(en_place[p], autres, ax), course_libre(en_place[p], autres, -np.asarray(ax))
        try: haut, bas = garde(f"Jeu axial {p}", _mes)
        except NonVerifie as e: out.append(res_non_verifie(f"Jeu axial {p}", str(e))); continue
        tot = haut + bas; titre = j["nom"] or f"Jeu axial {p}"
        jug = juger_exigence("jeu_axial", tot)
        if jug is None:
            mini = 2 * REGLES["jeu_mobile"]
            jug = (OK, f"{tot:.2f} mm ≥ {mini:g} (règle par défaut : {REGLES['jeu_mobile']:g} par côté)") if tot >= mini - 0.02 else \
                  (ECHEC, f"{tot:.2f} mm < {mini:g} (règle par défaut : {REGLES['jeu_mobile']:g} par côté)")
        out.append(res(titre, jug[0], f"course libre mesurée {haut:.2f} mm d'un côté + {bas:.2f} mm de l'autre = {tot:.2f} mm au TOTAL → {jug[1]}",
                       valeur=round(tot, 3), exigence="jeu_axial", mesure="forme", unite="mm", conseil=None if jug[0] == OK else "Ajuster les cotes des butées pour viser le milieu de la plage (jeu total, réparti des deux côtés)."))
    for e in getattr(A, "exigences", []):
        if e["mesure"] is None: continue
        try:
            m_ = e["mesure"]
            if callable(m_): v = m_(en_place)
            elif m_[0] == "jeu": v = _distance_min(en_place[m_[1]], en_place[m_[2]])[0]
            elif m_[0] == "jeu_axial":
                ax = m_[2] if len(m_) > 2 else (0, 0, 1); pc = en_place[m_[1]]; au = [x for n, x in en_place.items() if n != m_[1]]
                v = course_libre(pc, au, ax) + course_libre(pc, au, -np.asarray(ax, float))
            elif m_[0] == "dimension":
                ax = np.asarray(m_[2], float); ax /= np.linalg.norm(ax); pr = en_place[m_[1]].vertices @ ax; v = float(pr.max() - pr.min())
            else: raise ValueError(f"mesure inconnue {m_[0]}")
        except Exception as ex_:
            out.append(res(f"Exigence {e['nom']}", ECHEC, f"mesure impossible : {type(ex_).__name__}: {ex_}")); continue
        st, txt = juger_exigence(e["nom"], v, e["unite"]) or (OK, f"{v:.2f}")
        out.append(res(f"Exigence {e['nom']} (mesurée)", st, txt, valeur=round(float(v), 3), exigence=e["nom"], mesure="forme", unite=e["unite"]))
    ar = EXIGENCES_ACTIVES.get("angle_retenue")
    if ar:
        for (a, b), ci in ((tuple(sorted(k)), v) for k, v in getattr(A, "clips_info", {}).items()):
            st, txt = juger_exigence("angle_retenue", ci["alpha_out"], "°")
            out.append(res(f"Face de retenue {ci['a']} → {ci['b']}", st, txt + " (angle DÉCLARÉ dans A.clip, pas mesuré sur la forme)", valeur=ci["alpha_out"],
                           exigence="angle_retenue", mesure="parametres", unite="°"))
    return out


def verif_regles(p, A=None):
    out = []
    for r in (getattr(A, "regles", []) if A is not None else []):
        try:
            ok = _eval_regle(r["condition"], p)
            out.append(res(f"Règle : {r['nom']}", OK if ok else ECHEC, f"{r['condition'] if isinstance(r['condition'], str) else 'condition'} → {'respectée' if ok else 'NON respectée'}" + (f" — pourquoi : {r['pourquoi']}" if r['pourquoi'] else "")))
        except Exception as e:
            out.append(res(f"Règle : {r['nom']}", ECHEC, f"impossible d'évaluer : {e}"))
    import re
    for l in charger_lecons():
        noms = [n for n in p if isinstance(n, str)]
        b0 = l["besoin"][0]
        motif = re.compile(l.get("motif") or (r"^" + re.escape(b0) + r"(_\w+)?$"))
        if not all(any(n == b for n in noms) for b in l["besoin"][1:]): continue
        # la leçon s'applique à chaque paramètre dont le nom correspond (ex. jeu, jeu_mobile_bouton) — pas jeu_entraxe
        mobile = A is not None and bool(getattr(A, "mouvements", None) or getattr(A, "etats", None) or getattr(A, "jeux", None))
        for n in [n for n in noms if motif.match(n)]:
            if l.get("mobile_seulement") and n == b0 and not mobile: continue      # « jeu » sans aucune pièce mobile déclarée
            cle_ex = SYNONYMES_EXIGENCES.get(b0, b0)
            cle_n = SYNONYMES_EXIGENCES.get(n, n)
            if cle_n != cle_ex and cle_n in EXIGENCES_ACTIVES: continue     # ex. paramètre « jeu_axial » : jugé par sa mesure, pas par la leçon « jeu »
            if cle_ex in EXIGENCES_ACTIVES and isinstance(p[n], (int, float)):   # la CONSIGNE remplace la leçon (règle par défaut)
                st_, txt_ = juger_exigence(cle_ex, p[n])
                if st_ != OK:
                    out.append(res(f"Consigne {cle_ex} ({n} = {p[n]})", st_, txt_ + f" — remplace la leçon « {l['nom']} »"))
                continue
            q = dict(p); q[b0] = p[n]
            try: ok = _eval_regle(l["condition"], q)
            except Exception: continue
            if not ok:
                out.append(res(f"Leçon apprise : {l['nom']} ({n} = {p[n]})", ECHEC, f"pourquoi : {l['pourquoi']} — origine : {l.get('origine', '')}",
                               conseil="Corriger ce paramètre. Si c'est voulu (ajustement serré, pas une pièce mobile) : le déclarer avec A.serrage(a, b, interférence) "
                                       "et renommer le paramètre (ex. jeu_emmanchement)."))
    return out


# --- 1 000 impressions simulées (tolérances P2S) sur les jeux mesurés
VARIATION_P2S = dict(xy_sigma=0.03, machine_sigma=0.03, xy_biais=0.05, trou_biais=0.08, z_couche=0.2)
# Chaque impression : un décalage COMMUN à toute la machine ce jour-là (machine_sigma, filament, calibration) + un bruit propre à chaque surface (xy_sigma).
# xy_biais : chaque surface extérieure sort ~0,05 mm « plus grosse » (largeur d'extrusion); trou_biais : trous ~0,08 mm plus petits au rayon


def simulation_impressions(mesures, n=1000, var=None, graine=7):
    """mesures : liste de dict(nom, type='jeu'|'clip'|'entraxe', valeur, mini) — jeu nominal par côté (mm).
    Chaque impression : chaque côté du jeu se décale (biais + bruit). Retourne le % d'impressions où TOUT marche."""
    cal = {k: v for k, v in calibration_machine().items() if k in VARIATION_P2S}
    var = dict(VARIATION_P2S, **cal, **(var or {}))
    rng = np.random.default_rng(graine)
    if not mesures: return None
    ok_tout = np.ones(n, bool); detail = []
    commun = rng.normal(0.0, var["machine_sigma"], n)          # même machine, même jour : toutes les surfaces bougent ensemble
    for m in mesures:
        e1 = var["xy_biais"] + commun + rng.normal(0, var["xy_sigma"], n)           # surface extérieure de la pièce intérieure
        e2 = var["trou_biais"] + commun + rng.normal(0, var["xy_sigma"], n)         # surface intérieure du logement (trou)
        if m["type"] == "jeu":
            reel = m["valeur"] - e1 - e2              # les deux surfaces grossissent vers le jeu
            ok = reel >= m.get("mini", 0.05)
        elif m["type"] == "jeu_achete":               # pièce achetée (métal, cote exacte) dans un trou imprimé : seul le trou rétrécit
            reel = m["valeur"] - e2
            ok = reel >= m.get("mini", 0.0)
        elif m["type"] == "clip":
            reel = m["valeur"] + e1 + e2              # l'interférence d'un clip augmente quand ça grossit
            ok = (reel >= m.get("mini", 0.6)) & (reel <= m.get("maxi", m["valeur"] * 1.8 + 0.3))
        elif m["type"] == "entraxe":
            # jeu normal entre flancs créé par l'entraxe : 2·Δa·sin(20°); les DEUX flancs sont des surfaces extérieures
            e2x = var["xy_biais"] + commun + rng.normal(0, var["xy_sigma"], n)
            reel = 2 * m["valeur"] * math.sin(math.radians(20)) - e1 - e2x
            ok = reel >= m.get("mini", 0.0)
        else:
            continue
        ok_tout &= ok
        detail.append(dict(nom=m["nom"], nominal=round(m["valeur"], 3), pire_1pct=round(float(np.percentile(reel, 1)), 3), reussite_pct=round(100 * ok.mean(), 1)))
    detail.sort(key=lambda d: d["reussite_pct"])
    return dict(n=n, reussite_pct=round(100 * ok_tout.mean(), 1), detail=detail, hypotheses=var)


def mesures_depuis_resultats(res_a):
    """Récupère les jeux mesurés dans le rapport d'assemblage (jeux, mouvements, engrenages, clips)."""
    out = []
    for r in res_a:
        v = r.get("valeur")
        d = r.get("detail", "")
        if r["verif"].startswith("Jeu achetée") and v is not None:
            out.append(dict(nom=r["verif"], type="jeu_achete", valeur=float(v), mini=r.get("mini_sim", 0.0)))
        elif r["verif"].startswith("Jeu ") and v is not None:
            out.append(dict(nom=r["verif"], type="jeu", valeur=float(v), mini=0.05))
        elif r["verif"].startswith("Mouvement") and "jeu le plus serré" in d:
            try: out.append(dict(nom=r["verif"], type="jeu", valeur=float(d.split("jeu le plus serré ")[1].split(" mm")[0]), mini=0.05))
            except Exception: pass
        elif r["verif"].startswith("Engrenage") and "jeu FDM" in d:
            try: out.append(dict(nom=r["verif"], type="entraxe", valeur=float(d.split("jeu FDM ")[1].split(" mm")[0]), mini=0.0))
            except Exception: pass
        elif r["verif"].startswith("Clip") and "flexion mesurée" in d:
            try: out.append(dict(nom=r["verif"], type="clip", valeur=float(d.split("flexion mesurée ")[1].split(" mm")[0]), mini=0.6))
            except Exception: pass
    return out


# --- Ordre de montage automatique
DIRECTIONS = {"par le haut": (0, 0, 1), "par le bas": (0, 0, -1), "par l'avant": (0, -1, 0), "par l'arrière": (0, 1, 0), "par la gauche": (-1, 0, 0), "par la droite": (1, 0, 0)}


def _entre_libre(meshes, A, nom, presentes, direction, dist, clips, pas=30):
    base = meshes[nom]; Mf = A.poses.get(nom, np.eye(4))
    for k in range(pas + 1):
        t = 1 - k / pas
        mk = base.copy(); mk.apply_transform(trimesh.transformations.translation_matrix(np.asarray(direction) * dist * t) @ Mf)
        for autre, mo in presentes.items():
            if frozenset((nom, autre)) in clips: continue
            if not _paires_proches(mk, mo): continue
            if _vol_inter(mk, mo)[0] > 0.01: return False
    return True


def chercher_ordre(meshes, A, en_place, max_essais=400):
    """Cherche un ordre + une direction d'entrée (ligne droite) qui marche pour TOUTES les pièces de la séquence.
    Recherche avec retour en arrière (pas juste la première pièce qui passe). Retourne dict(ordre, bloque)."""
    clips = {frozenset((a, b)) for a, b, _ in A.clips} | {frozenset((d["a"], d["b"])) for d in getattr(A, "serrages", [])}
    a_monter = [s["piece"] for s in A.sequence if s["type"] == "translation"]
    if not a_monter: return None
    fixes = {n: en_place[n] for n in en_place if n not in a_monter}
    dist = float(trimesh.util.concatenate(list(en_place.values())).extents.max()) + 10
    memo = {}; essais = [0]; meilleur = [[]]

    def entre(n, d, deja):
        cle = (n, d, frozenset(deja))
        if cle not in memo:
            essais[0] += 1
            pres = dict(fixes); pres.update({x: en_place[x] for x in deja})
            memo[cle] = _entre_libre(meshes, A, n, pres, DIRECTIONS[d], dist, clips)
        return memo[cle]

    def cherche(ordre, restant):
        if not restant: return ordre
        if essais[0] > max_essais: return None
        deja = [n for n, _ in ordre]
        for n in restant:
            for d in DIRECTIONS:
                if entre(n, d, deja):
                    o = ordre + [(n, d)]
                    if len(o) > len(meilleur[0]): meilleur[0] = o
                    r = cherche(o, [x for x in restant if x != n])
                    if r is not None: return r
                    break   # cette pièce entre (par la 1re direction libre); essayer une autre pièce en tête si la suite bloque
        return None

    r = cherche([], list(a_monter))
    if r is not None: return dict(ordre=r, bloque=[])
    return dict(ordre=meilleur[0], bloque=[n for n in a_monter if n not in {x for x, _ in meilleur[0]}])


# --- Balayage de paramètres : où ça arrête de marcher
def balayage(chemin_modele, param, valeurs, sets=None, sortie=None):
    """Relance toutes les vérifs pour chaque valeur d'un paramètre. Dit entre quelles valeurs le modèle passe."""
    lignes = []
    for v in valeurs:
        out = (sortie or tempfile.mkdtemp()) + f"/b_{param}_{v}"
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = executer(chemin_modele, list(sets or []) + [f"{param}={v}"], out, None, rendus=False)
        R = json.load(open(os.path.join(out, "rapport.json")))
        echecs = [r["verif"] for P in R["pieces"].values() for r in P["resultats"] if r["statut"] == ECHEC] + [r["verif"] for r in R.get("assemblage", []) if r["statut"] == ECHEC]
        lignes.append(dict(valeur=v, code=code, echecs=echecs[:4], reussite_1000=(R.get("simulation") or {}).get("reussite_pct")))
    passent = [l["valeur"] for l in lignes if l["code"] < 2]
    zone = f"passe de {min(passent)} à {max(passent)}" if passent else "ne passe pour aucune valeur"
    return dict(parametre=param, zone=zone, essais=lignes)



def variantes(chemin_modele, grille, sets=None, sortie=None, max_n=10):
    """Jusqu'à 10 variantes (ex. {"ep": [4, 6, 8], "mur": [2, 3]}) toutes vérifiées, tranchées par Orca et classées :
    d'abord celles sans ❌, puis la plus solide (facteur de sécurité), puis la moins chère, puis la plus rapide."""
    import itertools, io, contextlib
    cles = list(grille); combos = list(itertools.product(*[grille[k] for k in cles]))[:max_n]
    base = sortie or tempfile.mkdtemp(); lignes = []
    for i, c in enumerate(combos, 1):
        s_ = list(sets or []) + [f"{k}={v}" for k, v in zip(cles, c)]
        out = os.path.join(base, f"v{i:02d}")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = executer(chemin_modele, s_, out, f"variante_{i:02d}", rendus=False)
        R = json.load(open(os.path.join(out, "rapport.json")))
        fs = [r.get("valeur") for r in R.get("assemblage", []) if r["verif"].lower().startswith(("résistance", "crochet")) or "facteur de sécurité" in str(r.get("detail"))]
        fs = [x for x in fs if isinstance(x, (int, float))]
        orca = R.get("tranchage_orca") or {}
        lignes.append(dict(variante=i, reglages=dict(zip(cles, c)), verdict=R["verdict"], echecs=R["compte"].get(ECHEC, 0),
                           securite=min(fs) if fs else None, cout=(R.get("cout_total") or {}).get("total"),
                           grammes=round(sum(o.get("grammes") or 0 for o in orca.values()), 1) or None,
                           heures=round(sum(_heures(o.get("temps")) or 0 for o in orca.values()), 2) or None,
                           reussite_1000=(R.get("simulation") or {}).get("reussite_pct"), dossier=out))
    # d'abord celles qui passent (0 ❌ et sécurité ≥ 2 quand elle est calculée), puis la moins chère, puis la plus rapide, puis la plus solide
    lignes.sort(key=lambda l: (l["echecs"] > 0, l["securite"] is not None and l["securite"] < 2, l["cout"] or 1e9, l["heures"] or 1e9, -(l["securite"] or 0)))
    for r, l in enumerate(lignes, 1): l["rang"] = r
    return dict(classement=lignes, meilleure=lignes[0] if lignes else None)

# --- Ce que les vérifs NE prouvent PAS (toujours dit à l'utilisateur)
NON_PROUVE = [
    "La résistance sous charge : calculée par éléments finis SEULEMENT pour les charges déclarées avec A.resistance(...) (matériau plein, élastique); les autres pièces : clips, lames, ressorts et engrenages par formules. Chocs, fatigue et fluage non calculés.",
    "Les vraies cotes de TA P2S : les jeux supposent une machine bien calibrée et un filament sec (peigne de calibration pour le confirmer).",
    "Le frottement réel, l'usure et le fluage du plastique dans le temps (clips tenus fermés des mois).",
    "Les pièces achetées : leurs cotes viennent du catalogue/fiche; celles marquées « à mesurer » doivent être mesurées.",
    "Le temps et le filament : donnés par OrcaSlicer sur le fichier livré (si installé), sinon estimation ±30 %. La vraie machine peut varier de ±10 %.",
    "L'esthétique (lignes de couches, coutures, couleur) : à juger sur les images.",
]


# ----------------------------------------------------------------------------
# BLOC 4 — Impression réelle : profils officiels Bambu Lab P2S, 3MF « projet Bambu Studio »
# avec les réglages dedans (par pièce), tranchage réel (temps, filament, ponts, alertes), peigne de calibration
# ----------------------------------------------------------------------------
FICHIER_PROFILS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profils_p2s.json")
FICHIER_MACHINE = os.path.join(os.path.expanduser("~"), ".lc3d", "machine.json")
PROFIL_MACHINE = "Bambu Lab P2S 0.4 nozzle"
PROFIL_PROCESS = {0.2: "0.20mm Standard @BBL P2S", 0.16: "0.16mm Standard @BBL P2S", 0.24: "0.24mm Standard @BBL P2S", 0.12: "0.12mm High Quality @BBL P2S"}
PROFIL_FILAMENT = {"PETG": "Bambu PETG HF @BBL P2S 0.4 nozzle", "PETG Basic": "Bambu PETG Basic @BBL P2S 0.4 nozzle", "PLA": "Bambu PLA Basic @BBL P2S",
                   "PLA Matte": "Bambu PLA Matte @BBL P2S", "TPU": "Bambu TPU 95A @BBL P2S", "PETG générique": "Generic PETG @BBL P2S", "PLA générique": "Generic PLA @BBL P2S",
                   "PCTG": "Generic PCTG @BBL P2S", "PA": "Generic PA @BBL P2S", "PC": "Generic PC @BBL P2S"}
# Réglages LC3D par rôle de pièce (écrits DANS le 3MF, par objet)
REGLAGES_ROLE = {
    "rigide":   {"wall_loops": "3", "sparse_infill_density": "20%", "top_shell_layers": "5", "bottom_shell_layers": "4"},
    # 100 % : motif « zig-zag » (rectiligne) — Bambu Studio refuse « grid » à 100 % (« grid doesn't work at 100% density »)
    "flexible": {"wall_loops": "6", "sparse_infill_density": "100%", "sparse_infill_pattern": "zig-zag"},          # clips / lames : plein, pas de remplissage creux
    "structure": {"wall_loops": "6", "sparse_infill_density": "100%", "sparse_infill_pattern": "zig-zag", "top_shell_layers": "6", "bottom_shell_layers": "6"},   # pièces qui portent l'effort (plaques d'embrayage, leviers, pivots)
    "esthetique": {"wall_loops": "2", "sparse_infill_density": "15%"},
}


def profils():
    try: return json.load(open(FICHIER_PROFILS))
    except Exception: return {}


def calibration_machine():
    """Jeux mesurés sur TA P2S (peigne de calibration). Sinon les valeurs par défaut."""
    try: return json.load(open(FICHIER_MACHINE))
    except Exception: return {}


def _est_bambu():
    return "bambu" in (MACHINE.get("profil", PROFIL_MACHINE) + MACHINE.get("nom", "")).lower()


def _machine_bambu():
    import lc3d_bambu as LB
    if not LB.disponible(): return None
    return LB.trouver_machine(MACHINE.get("nom") or PROFIL_MACHINE, MACHINE.get("buse", 0.4)) or (PROFIL_MACHINE if PROFIL_MACHINE in LB.index() else None)


def filament_pour_machine(materiau):
    """Le VRAI profil de filament que le 3MF aura sur la machine choisie. dict(nom, type, famille, abrasif, note, profil, buse_type).
    profil = None : aucun profil pour cette machine (le 3MF doit être refusé, jamais remplacé par un autre matériau)."""
    info = normaliser_materiau(materiau)
    profil = None; buse_type = None
    try:
        import lc3d_bambu as LB
        mb = _machine_bambu() if _est_bambu() else None
        if mb:
            pref = {"PLA Matte": "Bambu PLA Matte", "PLA Silk": "Bambu PLA Silk", "PETG Basic": "Bambu PETG Basic",
                    "PLA générique": "Generic PLA", "PETG générique": "Generic PETG", "PA-CF": "Bambu PA-CF"}.get(info["nom"])
            if pref:
                c = sorted((n for n, j in LB.index().items() if j.get("type") == "filament" and str(j.get("instantiation")) == "true"
                            and LB._compatible(j, mb) and n.startswith(pref + " @")), key=len)
                profil = c[0] if c else None
            profil = profil or LB.choisir_filament(mb, info["type"])
            nt = LB.resoudre(mb).get("nozzle_type"); buse_type = nt[0] if isinstance(nt, list) and nt else nt
            return dict(info, profil=profil, buse_type=buse_type, source="Bambu Studio")
    except Exception:
        pass
    if PROFIL_MACHINE == "Bambu Lab P2S 0.4 nozzle":
        cle = info["nom"] if info["nom"] in PROFIL_FILAMENT else info["type"]
        return dict(info, profil=PROFIL_FILAMENT.get(cle), buse_type="hardened_steel", source="profils P2S de LC3D")
    try:
        import lc3d_profils as LP
        profil, d = LP.filament_resolu(PROFIL_MACHINE, info["type"])
        cat = LP.catalogue(); fab = cat[PROFIL_MACHINE]["fabricant"]
        nt = LP._resoudre(LP._index(fab, PROFIL_MACHINE), PROFIL_MACHINE).get("nozzle_type")
        buse_type = nt[0] if isinstance(nt, list) and nt else nt
    except Exception as e:
        return dict(info, profil=None, buse_type=None, source=f"profils OrcaSlicer indisponibles ({e})")
    return dict(info, profil=profil, buse_type=buse_type, source="profils OrcaSlicer")


def verif_materiau(piece):
    """Le matériau demandé existe-t-il, et la machine choisie a-t-elle un VRAI profil pour lui ?"""
    try:
        f = filament_pour_machine(piece.materiau)
    except ValueError as e:
        return [res("Matériau", ECHEC, str(e), conseil="Écrire un matériau courant (ex. PLA, PETG, ABS, ASA, PA-CF, TPU 95A).")]
    machine = MACHINE.get("nom", PROFIL_MACHINE)
    if not f.get("profil"):
        return [res("Matériau : profil de la machine", ECHEC, f"{f['nom']} : aucun profil de filament {f['type']} pour la {machine} ({f.get('source')}). "
                    "LC3D ne le remplace PAS par un autre matériau.",
                    conseil="Choisir un matériau que cette machine imprime (PLA, PETG, TPU…), ou une machine qui a ce profil (ex. ABS/ASA : machine fermée).")]
    out = [res("Matériau : profil de la machine", INFO, f"{f['ecrit']} → {f['nom']} · profil « {f['profil']} » ({f.get('source')})")]
    if f.get("note"):
        out.append(res("Matériau : profil de la famille", AVERT if f["type"] == "TPU" else INFO, f["note"]))
    if f.get("abrasif") and f.get("buse_type") and "brass" in str(f["buse_type"]).lower():
        out.append(res("Matériau abrasif sur buse laiton", AVERT, f"{f['nom']} (fibres) use une buse en laiton en quelques centaines de grammes (buse de la {machine} : laiton).",
                       conseil="Installer une buse en acier trempé (et choisir le profil de cette buse) avant d'imprimer."))
    if f["type"] == "TPU" and _est_bambu():
        out.append(res("TPU sur une Bambu", INFO, "Le TPU s'imprime depuis la bobine externe (pas par l'AMS, sauf « TPU for AMS »)."))
    return out


def utiliser_imprimante(texte, buse=None):
    """Choisit l'imprimante (n'importe laquelle du catalogue Orca, ~1 150 machines) : plateau, buse, profils du 3MF."""
    global PROFIL_MACHINE
    import lc3d_profils as LP
    m = LP.trouver_machine_stricte(texte, buse or 0.4, buse_imposee=buse is not None)     # absente / mal écrite / résine : ValueError expliquée, jamais une autre machine
    PROFIL_MACHINE = m["nom"]
    MACHINE.update(nom=m.get("modele") or m["nom"], lit=(float(m["x"]), float(m["y"]), float(m["z"] or 250)), buse=m["buse"],
                   largeur_ligne=round(m["buse"] * 1.05, 2), profil=m["nom"], firmware=m.get("firmware", ""))
    REGLES["mur_absolu"] = round(2 * MACHINE["largeur_ligne"], 2)
    REGLES["mur_physique"] = round(2 * MACHINE["buse"] - 0.02, 2)     # 2 lignes = 2 × buse (Arachne remplit 0,80 mm avec une buse 0,4), − tolérance de maillage
    return m


_PLATEAUX = [("Textured PEI Plate", "textured_plate_temp"), ("High Temp Plate", "hot_plate_temp"), ("Engineering Plate", "eng_plate_temp"),
             ("Supertack Plate", "supertack_plate_temp"), ("Textured Cool Plate", "textured_cool_plate_temp"), ("Cool Plate", "cool_plate_temp")]
# certains profils écrivent le plateau par son numéro (enum BedType d'OrcaSlicer, PrintConfig.hpp)
_PLATEAU_NUM = {"1": "Cool Plate", "2": "Engineering Plate", "3": "High Temp Plate", "4": "Textured PEI Plate",
                "5": "Textured Cool Plate", "6": "Supertack Plate"}


def _completer_cfg(cfg):
    """Plateau compatible avec le filament (sinon Bambu Studio / Orca refusent : « Cool Plate does not support filament »)
    + valeurs hors plage que les logiciels refusent."""
    def temp(k):        # plus basse température de plateau parmi TOUS les filaments du projet (0 = plateau refusé)
        v = cfg.get(k); vs = v if isinstance(v, list) else [v]
        try: return min(float(x) for x in vs)
        except Exception: return 0.0
    defaut = cfg.get("default_bed_type")
    defaut = _PLATEAU_NUM.get(str(defaut), defaut) if defaut not in (None, "", "0") else None
    choix = None
    multi = isinstance(cfg.get("filament_settings_id"), list) and len(cfg["filament_settings_id"]) > 1
    if defaut:   # le plateau d'origine de la machine d'abord
        k = dict(_PLATEAUX).get(defaut)
        if k and temp(k) > 0: choix = defaut
    if choix is None and not multi:
        for nom, k in _PLATEAUX:
            if temp(k) > 0: choix = nom; break
    if choix is None and defaut:
        # multi-filaments : un filament n'a pas de température pour ce plateau → on prend sa température d'un autre plateau
        choix = defaut; k = dict(_PLATEAUX).get(defaut) or "textured_plate_temp"
        for kk in (k, k + "_initial_layer"):
            v = cfg.get(kk)
            if isinstance(v, list):
                for i, x in enumerate(v):
                    if float(x or 0) == 0:
                        autres = [float(cfg[o][i]) for _, o in _PLATEAUX if isinstance(cfg.get(o), list) and len(cfg[o]) > i and float(cfg[o][i] or 0) > 0]
                        v[i] = str(int(max(autres))) if autres else "50"
    if choix: cfg["curr_bed_type"] = choix
    cal = calibration_machine()
    if cal and cal.get("machine", PROFIL_MACHINE) == PROFIL_MACHINE:
        # jumeau de TA machine : le slicer corrige les contours et les trous selon ta calibration réelle
        cfg["xy_contour_compensation"] = str(round(-cal.get("xy_biais", 0.0), 3))
        cfg["xy_hole_compensation"] = str(round(cal.get("trou_biais", 0.0), 3))
    if str(cfg.get("tree_support_wall_count", "0")).strip("[]'\" ") in ("-1",):
        cfg["tree_support_wall_count"] = "0"
    return cfg


def reglages_projet(materiau="PETG", couche=0.2):
    cfg, noms = _reglages_projet(materiau, couche)
    return (_completer_cfg(cfg) if cfg else cfg), noms


def _reglages_projet(materiau="PETG", couche=0.2):
    info = normaliser_materiau(materiau)
    if PROFIL_MACHINE != "Bambu Lab P2S 0.4 nozzle":
        try:
            import lc3d_profils as LP
            return LP.reglages_projet_orca(PROFIL_MACHINE, info["type"], couche)
        except Exception as e:
            print(f"(profils Orca indisponibles : {e}; 3MF sans réglages de machine)", file=sys.stderr)
            return {}, dict(machine=PROFIL_MACHINE, process=None, filament=None)
    P = profils()
    nm, npr = PROFIL_MACHINE, PROFIL_PROCESS.get(couche, PROFIL_PROCESS[0.2])
    nf = PROFIL_FILAMENT.get(info["nom"]) or PROFIL_FILAMENT.get(info["type"])
    if not nf:
        raise ValueError(f"matériau {info['nom']} : pas de profil P2S connu sans Bambu Studio (lc3d.py bambu-installer) — pas de remplacement par un autre matériau")
    cfg = {}
    for n in (nm, npr, nf):
        d = dict(P.get(n, {})); d.pop("_categorie", None)
        for k in ("name", "from", "instantiation", "setting_id", "type", "description", "compatible_printers", "compatible_printers_condition", "filament_id", "base_id"):
            d.pop(k, None)
        cfg.update(d)
    cfg.update({"printer_settings_id": nm, "print_settings_id": npr, "filament_settings_id": [nf], "printer_model": "Bambu Lab P2S",
                "from": "project", "name": "project_settings", "version": "02.04.00.70", "inherits_group": [npr, nf, nm] if False else None})
    cfg.pop("inherits_group")
    # Bambu Studio écrit chaque valeur en texte, et les listes en listes de textes
    cfg = {k: ([str(x) for x in v] if isinstance(v, list) else str(v)) for k, v in cfg.items() if v is not None}
    return cfg, dict(machine=nm, process=npr, filament=nf)


def _xml_mesh(m):
    v = "\n".join(f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in m.vertices)
    t = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
    return f"    <mesh>\n     <vertices>\n{v}\n     </vertices>\n     <triangles>\n{t}\n     </triangles>\n    </mesh>"


def _verifier_nb_filaments(mats):
    """Nombre de filaments ≤ ce que la machine peut tenir (têtes, ou fentes de son changeur). Sinon : refus clair AVANT le fichier
    (OrcaSlicer plantait en std::bad_alloc avec 5 filaments sur les 4 têtes de la U1)."""
    n = len(mats)
    if n < 2: return
    nom = (MACHINE.get("nom", "") + " " + MACHINE.get("profil", PROFIL_MACHINE)).lower()
    maxi, quoi = None, ""
    if "snapmaker u1" in nom: maxi, quoi = 4, "4 têtes"
    elif re.search(r"\ba1\b|a1 mini", nom): maxi, quoi = 4, "4 fentes de l'AMS lite"
    elif "bambu" in nom and re.search(r"\bh2", nom): maxi, quoi = 24, "AMS (jusqu'à 24 fentes)"
    elif "bambu" in nom: maxi, quoi = 16, "AMS (4 unités × 4 fentes)"
    elif re.search(r"xl", nom) and "prusa" in nom: m_ = re.search(r"(\d)t", nom); maxi, quoi = (int(m_.group(1)) if m_ else 5), "têtes de la Prusa XL"
    elif "mmu" in nom: maxi, quoi = 5, "5 fentes du MMU3"
    if maxi and n > maxi:
        raise ValueError(f"{n} filaments (couleurs/matériaux) > {maxi} ({quoi} de la {MACHINE.get('nom', PROFIL_MACHINE)}) : impossible d'imprimer en une fois. "
                         f"Regrouper {n - maxi + 1} couleurs en une seule, ou imprimer une partie des pièces à part.")


def _verifier_changeur(cfg, mats):
    """Plusieurs filaments : la machine (son profil) doit avoir un changeur (AMS, CFS, Canvas, MMU, Box, ERCF…) ou plusieurs têtes."""
    buses = cfg.get("nozzle_diameter"); nb = len(buses) if isinstance(buses, list) else 1
    if nb > 1: return
    machine = MACHINE.get("nom", PROFIL_MACHINE)
    if str(cfg.get("manual_filament_change", "0")) == "1":
        raise ValueError(f"La {machine} n'a pas de changeur de filament : son profil fait les changements À LA MAIN (pause). Avec des pièces "
                         f"de couleurs différentes côte à côte, il faudrait changer le filament à chaque couche. Solutions : imprimer chaque "
                         f"couleur séparément, ou ajouter un changeur (ex. Creality CFS, Elegoo Canvas) et choisir le profil qui va avec.")
    if str(cfg.get("single_extruder_multi_material", "0")) != "1":
        raise ValueError(f"Le profil de la {machine} n'a pas de changeur de filament (ex. MMU3 pour Prusa). Solutions : imprimer chaque couleur "
                         f"séparément, ou choisir le profil de la version multi-filaments si elle existe (ex. « Prusa XL 5T », « Core One MMU3 »).")


def _verifier_multi_une_buse(cfg, mats):
    """Une seule buse pour plusieurs filaments : MÊME RÈGLE QU'ORCASLICER (Print::check_multi_filaments_compatibility) :
    la température d'impression de chaque filament doit être dans la plage recommandée de chacun des autres.
    Sinon OrcaSlicer refuse (risque de bouchon). On refuse AVANT de faire le fichier, avec la raison et les solutions."""
    buses = cfg.get("nozzle_diameter"); nb = len(buses) if isinstance(buses, list) else 1
    if nb > 1 or len(mats) < 2: return
    def liste(k):
        v = cfg.get(k); v = v if isinstance(v, list) else [v]
        try: return [float(x) for x in v]
        except Exception: return []
    T, bas, haut = liste("nozzle_temperature"), liste("nozzle_temperature_range_low"), liste("nozzle_temperature_range_high")
    n = len(mats)
    if min(len(T), len(bas), len(haut)) < n: return
    for i in range(n):
        for j in range(i + 1, n):
            if not (bas[j] <= T[i] <= haut[j] and bas[i] <= T[j] <= haut[i]):
                a_, b_ = mats[i], mats[j]
                raise ValueError(f"{a_[0]} ({T[i]:.0f} °C) + {b_[0]} ({T[j]:.0f} °C) sur une seule buse : chacun sort de la plage de l'autre "
                                 f"({bas[i]:.0f}-{haut[i]:.0f} °C / {bas[j]:.0f}-{haut[j]:.0f} °C) — OrcaSlicer le refuse (risque de bouchon). "
                                 f"Solutions : le même matériau en plusieurs couleurs (ex. PLA + PLA), une machine à plusieurs têtes "
                                 f"(Snapmaker U1, Prusa XL multi-outils), ou imprimer les pièces séparément.")


def exporter_3mf_bambu(objets, chemin, materiau="PETG", couche=0.2, vignette=True):
    """objets : liste de dict(nom, mesh (orienté pour l'impression), copies=1, role='rigide', reglages={...}).
    Écrit un 3MF « projet Bambu Studio » : géométrie + imprimante P2S + profil d'impression + filament + réglages par pièce.
    Bambu Studio l'ouvre avec tout déjà réglé (il peut demander « charger les réglages du projet ? » : répondre Oui)."""
    import uuid
    # matériaux : noms canoniques (« pla » = PLA, « Nylon » = PA). Inconnu ou sans profil pour la machine : REFUS, jamais un autre matériau
    materiau = normaliser_materiau(materiau)["nom"]
    objets = [dict(o, materiau=normaliser_materiau(o.get("materiau") or materiau)["nom"]) for o in objets]
    _typ = lambda m_: normaliser_materiau(m_)["type"]
    # un filament = (matériau, couleur) : deux couleurs du même PLA = deux filaments (AMS / têtes multiples)
    cle = lambda o: ((o.get("materiau") or materiau), (o.get("couleur") or None))
    mats = []
    for o in objets:
        if cle(o) not in mats: mats.append(cle(o))
    est_bambu = _est_bambu()
    cfg = None
    _verifier_nb_filaments(mats)
    try:
        import lc3d_bambu as LB
        if est_bambu and LB.disponible():
            mb = _machine_bambu()
            if mb:
                fils = []
                for m_, c_ in mats:
                    f_ = filament_pour_machine(m_).get("profil")
                    if not f_: raise ValueError(f"Bambu Lab ne fournit aucun profil {m_} pour la {mb.replace(' 0.4 nozzle', '')} : ce matériau n'y est pas "
                                                f"recommandé (ex. ABS/ASA sur une imprimante ouverte : déformation et fumées). Choisir PLA, PETG ou TPU, "
                                                f"ou une imprimante fermée (P1S, P2S, X1C, H2D).")
                    fils.append(f_)
                pr = LB.choisir_process(mb, couche)
                cfg = _completer_cfg(LB.cfg_projet(mb, pr, fils, [c_ for _, c_ in mats]))
                noms = dict(machine=mb, process=pr, filament=fils, source="profils Bambu Studio")
    except ValueError:
        raise
    except Exception as e:
        print(f"(profils Bambu Studio indisponibles : {e})", file=sys.stderr); cfg = None
    if cfg is None:
        cfg, noms = reglages_projet(mats[0][0], couche)
        if cfg and not noms.get("filament"):
            raise ValueError(f"aucun profil de filament {mats[0][0]} pour la {MACHINE.get('nom', PROFIL_MACHINE)} : le 3MF n'est pas fait "
                             f"(LC3D ne remplace jamais un matériau par un autre). Choisir un matériau que cette machine imprime.")
        if len(mats) > 1 and cfg:
            if PROFIL_MACHINE == "Bambu Lab P2S 0.4 nozzle" and os.path.exists(FICHIER_MODELE_MULTI):
                cfg = cfg_multi_bambu([m_ for m_, _ in mats])
            else:
                import lc3d_profils as LP
                _verifier_changeur(cfg, mats)
                cfg = LP.multi_filaments(cfg, MACHINE.get("profil", PROFIL_MACHINE), [_typ(m_) for m_, _ in mats])
                manquants = [m_ for (m_, _), n_ in zip(mats, cfg.get("filament_settings_id", [])) if not n_]
                if manquants: raise ValueError(f"aucun profil de filament {', '.join(manquants)} pour la {MACHINE.get('nom', PROFIL_MACHINE)} : 3MF refusé.")
                cfg = _completer_cfg(cfg)
                _verifier_multi_une_buse(cfg, mats)
        if cfg and (any(c_ for _, c_ in mats) or len(mats) > 1):      # une couleur par filament, TOUJOURS (sinon OrcaSlicer plante)
            defaut = cfg.get("filament_colour") if isinstance(cfg.get("filament_colour"), list) else []
            cfg["filament_colour"] = [c_ or (defaut[i] if i < len(defaut) else _COULEURS_FIL[i % len(_COULEURS_FIL)]) for i, (_, c_) in enumerate(mats)]
    roles = {o.get("role", "rigide") for o in objets}
    if cfg and len(roles) == 1:      # une pièce par fichier : ses réglages deviennent aussi ceux du projet (tous les logiciels les lisent)
        cfg.update({k: v for k, v in REGLAGES_ROLE.get(roles.pop(), {}).items()})
        if len(objets) == 1 and objets[0].get("reglages"): cfg.update(objets[0]["reglages"])     # ex. bordure d'office
    W, D = MACHINE["lit"][0], MACHINE["lit"][1]
    # placement : rangées sur le plateau, 6 mm entre les pièces
    places = []; x = y = 8.0; rang_h = 0.0
    for o in objets:
        m = poser_sur_plateau(o["mesh"].copy())
        for k in range(o.get("copies", 1)):
            e = m.extents
            if x + e[0] > W - 8: x = 8.0; y += rang_h + 6; rang_h = 0.0
            places.append((o, m, x - m.bounds[0, 0], y - m.bounds[0, 1])); x += e[0] + 6; rang_h = max(rang_h, e[1])
    # centrer l'ensemble sur le plateau (comme les logiciels) puis éviter les zones interdites de la machine
    # (ex. coin de purge des X1 / P1 : bed_exclude_area)
    if places:
        lo = np.min([[tx + m.bounds[0, 0], ty + m.bounds[0, 1]] for o, m, tx, ty in places], axis=0)
        hi = np.max([[tx + m.bounds[1, 0], ty + m.bounds[1, 1]] for o, m, tx, ty in places], axis=0)
        # vraie zone imprimable de la machine (certaines ont l'origine au CENTRE du plateau : Flashforge AD5M, etc.)
        bx0, by0, bx1, by1 = 0.0, 0.0, W, D
        try:
            pa = (cfg or {}).get("printable_area")
            P = [tuple(float(a) for a in str(p).lower().split("x")) for p in (pa if isinstance(pa, list) else str(pa).split(","))]
            if len(P) >= 3:
                bx0, by0, bx1, by1 = min(p[0] for p in P), min(p[1] for p in P), max(p[0] for p in P), max(p[1] for p in P)
                W, D = bx1 - bx0, by1 - by0
        except Exception:
            pass
        dx, dy = (bx0 + bx1) / 2 - (lo[0] + hi[0]) / 2, (by0 + by1) / 2 - (lo[1] + hi[1]) / 2
        zones = []
        for z in (cfg or {}).get("bed_exclude_area", []) if isinstance((cfg or {}).get("bed_exclude_area"), list) else []:
            try:
                P = [tuple(float(a) for a in p.lower().split("x")) for p in str(z).split(",") if "x" in p.lower()]
                if len(P) >= 3: zones.append((min(p[0] for p in P), min(p[1] for p in P), max(p[0] for p in P), max(p[1] for p in P)))
            except Exception:
                pass
        if not zones and isinstance((cfg or {}).get("bed_exclude_area"), list):
            P = []
            for p in cfg["bed_exclude_area"]:
                try: P.append(tuple(float(a) for a in str(p).lower().split("x")))
                except Exception: pass
            if len(P) >= 3: zones.append((min(p[0] for p in P), min(p[1] for p in P), max(p[0] for p in P), max(p[1] for p in P)))
        def touche(dx_, dy_):
            for o, m, tx, ty in places:
                a0, a1 = tx + dx_ + m.bounds[0, 0] - 2, tx + dx_ + m.bounds[1, 0] + 2
                b0, b1 = ty + dy_ + m.bounds[0, 1] - 2, ty + dy_ + m.bounds[1, 1] + 2
                for (x0, y0, x1, y1) in zones:
                    if a0 < x1 and a1 > x0 and b0 < y1 and b1 > y0: return True
            return False
        if zones and touche(dx, dy):           # pousser vers le côté opposé aux zones interdites
            for pas in range(1, 60):
                essai = [(dx + 2 * pas, dy), (dx, dy + 2 * pas), (dx + 2 * pas, dy + 2 * pas)]
                ok = [e for e in essai if not touche(*e) and lo[0] + e[0] >= bx0 + 2 and hi[0] + e[0] <= bx1 - 2 and lo[1] + e[1] >= by0 + 2 and hi[1] + e[1] <= by1 - 2]
                if ok: dx, dy = ok[0]; break
        places = [(o, m, tx + dx, ty + dy) for o, m, tx, ty in places]
        deborde = (hi[0] - lo[0]) > W - 4 or (hi[1] - lo[1]) > D - 4
        # multi-filaments : tour de purge À CÔTÉ des pièces (sinon le logiciel la met à sa place fixe, parfois sur la pièce)
        if cfg and len(mats) > 1:
            larg = float((cfg.get("prime_tower_width") if not isinstance(cfg.get("prime_tower_width"), list) else cfg["prime_tower_width"][0]) or 35)
            prof = 60.0
            gx0, gx1 = lo[0] + dx, hi[0] + dx; gy0 = lo[1] + dy
            x = gx1 + 15 if gx1 + 15 + larg <= bx1 - 5 else gx0 - 15 - larg
            y = min(max(gy0, by0 + 5), by1 - 5 - prof)
            if x >= bx0 + 5:
                cfg["wipe_tower_x"] = [f"{x:.1f}"]; cfg["wipe_tower_y"] = [f"{y:.1f}"]     # même repère que le plateau (Print.cpp : + origine du plateau 1 = 0)
    else:
        deborde = False
    res_xml, build_xml, cfg_obj, inst = [], [], [], []
    for i, (o, m, tx, ty) in enumerate(places, start=1):
        res_xml.append(f'  <object id="{i}" type="model">\n{_xml_mesh(m)}\n  </object>')
        build_xml.append(f'  <item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} 0" printable="1"/>')
        reg = dict(REGLAGES_ROLE.get(o.get("role", "rigide"), {})); reg.update(o.get("reglages", {}))
        meta = "".join(f'\n    <metadata key="{k}" value="{v}"/>' for k, v in reg.items())
        nom = o["nom"] + (f"_{i}" if o.get("copies", 1) > 1 else "")
        ext = mats.index(cle(o)) + 1
        cfg_obj.append(f'  <object id="{i}">\n    <metadata key="name" value="{nom}"/>\n    <metadata key="extruder" value="{ext}"/>{meta}\n'
                       f'    <part id="1" subtype="normal_part">\n      <metadata key="name" value="{nom}"/>\n'
                       f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                       f'      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n    </part>\n  </object>')
        inst.append(f'    <model_instance>\n      <metadata key="object_id" value="{i}"/>\n      <metadata key="instance_id" value="0"/>\n      <metadata key="identify_id" value="{100 + i}"/>\n    </model_instance>')
    modele = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
              'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">\n <metadata name="Application">BambuStudio-02.04.00.70</metadata>\n'
              ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <metadata name="Title">' + os.path.splitext(os.path.basename(chemin))[0] + '</metadata>\n'
              ' <metadata name="Designer">LC3D</metadata>\n <resources>\n' + "\n".join(res_xml) + '\n </resources>\n <build>\n' + "\n".join(build_xml) + '\n </build>\n</model>\n')
    model_cfg = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg_obj) +
                 '\n  <plate>\n    <metadata key="plater_id" value="1"/>\n    <metadata key="plater_name" value=""/>\n    <metadata key="locked" value="false"/>\n'
                 + ('    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>\n' if vignette else '') + "\n".join(inst) + '\n  </plate>\n</config>\n')
    types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
             ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
             ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
             ' <Default Extension="png" ContentType="image/png"/>\n <Default Extension="config" ContentType="text/plain"/>\n</Types>\n')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n' +
            (' <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>\n' if vignette else '') +
            '</Relationships>\n')
    with zipfile.ZipFile(chemin, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types); z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", modele)
        if cfg: z.writestr("Metadata/project_settings.config", json.dumps(cfg, ensure_ascii=False, indent=1))
        z.writestr("Metadata/model_settings.config", model_cfg)
        if vignette:
            try:
                import io
                mc = []
                for i, (o, m, tx, ty) in enumerate(places):
                    mm = m.copy(); mm.apply_translation([tx, ty, 0]); mc.append((mm, PALETTE[i % len(PALETTE)]))
                im, _, _ = rendre_vue(mc, "Iso avant", 256)
                b = io.BytesIO(); im.save(b, "PNG"); z.writestr("Metadata/plate_1.png", b.getvalue())
            except Exception:
                pass
    note = None
    if len(mats) > 1:
        buses = (cfg or {}).get("nozzle_diameter"); nb = len(buses) if isinstance(buses, list) else 1
        note = (f"{len(mats)} filaments sur {nb} têtes : chaque filament dans sa tête." if nb > 1 else
                "Il faut l'AMS lite (vendu à part) branché sur l'A1 / A1 mini, chargé dans cet ordre : " + ", ".join(f"{i + 1} = {m_}{' ' + c_ if c_ else ''}" for i, (m_, c_) in enumerate(mats)) if re.search(r"\ba1\b|a1 mini", (MACHINE.get("nom", "") + " " + MACHINE.get("profil", PROFIL_MACHINE)).lower()) else
                f"{len(mats)} filaments : il faut le changeur de la machine branché et chargé dans cet ordre "
                f"({', '.join(f'{i + 1} = {m_}{' ' + c_ if c_ else ''}' for i, (m_, c_) in enumerate(mats))}) — AMS / AMS lite (Bambu), CFS, Canvas, MMU, Box…")
    return dict(chemin=chemin, objets=len(places), deborde_plateau=deborde, profils=noms, note_multi=note)


def verifier_3mf(chemin):
    """Relit le 3MF : géométrie étanche, objets sur le plateau, réglages présents."""
    out = []
    with zipfile.ZipFile(chemin) as z:
        noms = z.namelist()
        cfg = json.loads(z.read("Metadata/project_settings.config")) if "Metadata/project_settings.config" in noms else {}
    sc = trimesh.load(chemin, force="scene")
    geoms = list(sc.dump()) if hasattr(sc, "dump") else [sc]
    etanches = sum(g.is_watertight for g in geoms)
    lo = np.min([g.bounds[0] for g in geoms], axis=0); hi = np.max([g.bounds[1] for g in geoms], axis=0)
    # zone imprimable de LA machine du fichier (certaines ont l'origine au centre du plateau)
    x0, y0, x1, y1 = 0.0, 0.0, MACHINE["lit"][0], MACHINE["lit"][1]
    try:
        P = [tuple(float(a) for a in str(p).lower().split("x")) for p in cfg.get("printable_area", [])]
        if len(P) >= 3: x0, y0, x1, y1 = min(p[0] for p in P), min(p[1] for p in P), max(p[0] for p in P), max(p[1] for p in P)
    except Exception:
        pass
    zmax = float(cfg.get("printable_height") or MACHINE["lit"][2])
    dans = lo[0] >= x0 - 0.01 and lo[1] >= y0 - 0.01 and hi[0] <= x1 + 0.01 and hi[1] <= y1 + 0.01 and hi[2] <= zmax + 0.01 and abs(lo[2]) < 0.05
    out.append(res("3MF : géométrie", OK if etanches == len(geoms) else ECHEC, f"{len(geoms)} objet(s), {etanches} étanche(s)"))
    out.append(res(f"3MF : sur le plateau ({cfg.get('printer_model') or MACHINE['nom']})", OK if dans else ECHEC,
                   f"de {_pt(lo)} à {_pt(hi)} (zone {x0:.0f}..{x1:.0f} × {y0:.0f}..{y1:.0f} × {zmax:.0f})"))
    ok_cfg = bool(cfg.get("printer_settings_id") and cfg.get("print_settings_id") and cfg.get("filament_settings_id"))
    out.append(res("3MF : réglages dedans", OK if ok_cfg else ECHEC, f"imprimante {cfg.get('printer_settings_id')} · {cfg.get('print_settings_id')} · {cfg.get('filament_settings_id')}"))
    return out


def _slicer():
    import shutil
    for n in ("bambu-studio", "orca-slicer", "prusa-slicer", "PrusaSlicer"):
        p = shutil.which(n)
        if p: return n, p
    return None, None


def trancher(mesh, materiau="PETG", couche=0.2, role="rigide", nom="piece"):
    """Tranche pour de vrai (PrusaSlicer en ligne de commande, réglé comme la P2S : mêmes vitesses, accélérations, murs).
    Donne le temps, les grammes, les ponts les plus longs mesurés dans le G-code et les alertes du slicer.
    Le temps Bambu Studio peut différer de ±15 % (moteur de calcul différent)."""
    nom_s, exe = _slicer()
    if not exe: return dict(disponible=False, note="aucun slicer installé ici")
    try:
        cfg, _ = reglages_projet(materiau, couche)
    except ValueError:      # estimation seulement (le fichier livré, lui, a le vrai profil) : températures/densité de la famille
        i_ = normaliser_materiau(materiau)
        cfg, _ = reglages_projet(i_["type"] if i_["type"] in PROFIL_FILAMENT else (i_["famille"] or "PETG"), couche)
    reg = dict(REGLAGES_ROLE.get(role, {}))
    v = lambda k, i=0, d=None: (cfg.get(k)[i] if isinstance(cfg.get(k), list) else cfg.get(k, d)) if cfg.get(k) is not None else d
    tmp = tempfile.mkdtemp(); stl = os.path.join(tmp, nom + ".stl"); gc = os.path.join(tmp, nom + ".gcode")
    m = poser_sur_plateau(mesh.copy())
    c0 = m.bounds.mean(0); m.apply_translation([128 - c0[0], 128 - c0[1], 0]); m.export(stl)   # --center du slicer = centre de la boîte englobante
    murs = int(reg.get("wall_loops", v("wall_loops", d="2"))); dens = reg.get("sparse_infill_density", v("sparse_infill_density", d="15%"))
    args = [exe, "--export-gcode", "--output", gc, "--nozzle-diameter", "0.4", "--layer-height", str(couche), "--first-layer-height", "0.2",
            "--bed-shape", "0x0,256x0,256x256,0x256", "--max-print-height", "256", "--filament-diameter", "1.75",
            "--temperature", str(v("nozzle_temperature", d="250")), "--bed-temperature", str(v("hot_plate_temp", d="70")),
            "--filament-density", str(v("filament_density", d="1.27")),
            "--perimeters", str(murs), "--fill-density", str(dens), "--top-solid-layers", str(reg.get("top_shell_layers", 5)), "--bottom-solid-layers", str(reg.get("bottom_shell_layers", 3)),
            "--external-perimeter-speed", str(v("outer_wall_speed", d="200")), "--perimeter-speed", str(v("inner_wall_speed", d="300")),
            "--infill-speed", str(v("sparse_infill_speed", d="270")), "--solid-infill-speed", str(v("internal_solid_infill_speed", d="250")),
            "--top-solid-infill-speed", str(v("top_surface_speed", d="200")), "--travel-speed", "500", "--first-layer-speed", str(v("initial_layer_speed", d="50")),
            "--bridge-speed", str(v("bridge_speed", d="50")), "--default-acceleration", str(v("default_acceleration", d="10000")),
            "--machine-max-acceleration-extruding", "20000", "--machine-max-acceleration-x", "20000", "--machine-max-acceleration-y", "20000",
            "--machine-max-feedrate-x", "1000", "--machine-max-feedrate-y", "1000", "--max-volumetric-speed", str(v("filament_max_volumetric_speed", d="20")),
            "--gcode-flavor", "marlin2", "--center", "128,128"] + (["--fill-pattern", "rectilinear"] if str(dens).startswith("100") else []) + [stl]
    import subprocess
    p = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if p.returncode != 0 or not os.path.exists(gc):
        return dict(disponible=True, ok=False, erreur=(p.stderr or p.stdout)[-800:])
    txt = open(gc).read()
    temps = None
    import re
    mt = re.search(r"estimated printing time \(normal mode\) = (.+)", txt)
    if mt:
        s = mt.group(1); temps = sum(int(n) * f for n, f in zip(re.findall(r"(\d+)\s*[dhms]", s)[::-1], [1 / 60, 1, 60, 1440]))
    mm = re.search(r"filament used \[mm\] = ([\d.]+)", txt)
    grammes = float(mm.group(1)) * math.pi * (1.75 / 2) ** 2 / 1000 * float(v("filament_density", d="1.27")) if mm else None
    # ponts : longueur de chaque extrusion de type pont
    type_cour = None; x = y = 0.0; z = 0.0; ponts = []
    for ligne in txt.splitlines():
        if ligne.startswith(";TYPE:"): type_cour = ligne[6:].strip(); continue
        if ligne.startswith(";Z:"):
            try: z = float(ligne[3:])
            except ValueError: pass
            continue
        if ligne.startswith("G1") or ligne.startswith("G0"):
            gx = re.search(r"X([-\d.]+)", ligne); gy = re.search(r"Y([-\d.]+)", ligne); ge = re.search(r"E([-\d.]+)", ligne)
            nx = float(gx.group(1)) if gx else x; ny = float(gy.group(1)) if gy else y
            if type_cour and "ridge" in type_cour and ge and float(ge.group(1)) > 0:
                ponts.append((math.hypot(nx - x, ny - y), z, ((nx + x) / 2, (ny + y) / 2)))
            x, y = nx, ny
    alertes = [l.strip() for l in (p.stdout + p.stderr).splitlines() if any(k in l.lower() for k in ("warning", "detected", "floating", "loose", "collapsing", "bridging", "adhesion", "thin"))]
    # pont « dans le vide » seulement : sous le milieu du segment, la pièce est vide (sinon c'est un pont interne sur le remplissage, normal)
    from shapely.geometry import Point
    sections = {}
    vrais = []
    for L, zz, (cx, cy) in ponts:
        k = round(zz - couche, 2)
        if k not in sections: sections[k] = _polys_section(m, k - couche / 2) if k > 0 else None
        S = sections[k]
        if S is None or not S.buffer(0.3).contains(Point(cx, cy)):
            vrais.append((L, zz))
    ponts = vrais
    pmax = max(ponts) if ponts else (0.0, 0.0)
    return dict(disponible=True, ok=True, slicer=nom_s, temps_min=round(temps) if temps else None, filament_g=round(grammes, 1) if grammes else None,
                pont_max_mm=round(pmax[0], 1), pont_max_z=pmax[1], nb_ponts=len(ponts), alertes=alertes[:8], murs=murs, remplissage=dens)


def verif_tranchage(m, piece):
    try: mat_t = normaliser_materiau(piece.materiau)["nom"]
    except ValueError: return [], dict(disponible=False)
    t = trancher(m, mat_t, MACHINE["couche"], piece.role, piece.nom)
    if not t.get("disponible"): return [], t
    if not t.get("ok"): return [res("Tranchage réel", AVERT, f"le slicer a refusé la pièce : {t.get('erreur', '')[:200]}")], t
    logi = "Bambu Studio" if _est_bambu() else "OrcaSlicer"
    out = [res(f"Tranchage d'estimation ({t.get('slicer', 'slicer')}, vitesses du profil {MACHINE.get('nom', 'P2S')})", INFO,
               f"~{t['temps_min']} min · ~{t['filament_g']} g · {t['murs']} murs, remplissage {t['remplissage']} ({logi}, sur le fichier livré, peut différer de ±15 %)")]
    if t["pont_max_mm"] > REGLES["pont_max"]:
        out.append(res("Ponts mesurés dans le G-code", AVERT, f"pont le plus long {t['pont_max_mm']} mm à z = {t['pont_max_z']} (règle ≤ {REGLES['pont_max']} mm)",
                       conseil="Raccourcir la portée, ajouter un appui, ou orienter autrement."))
    for a in t["alertes"]:
        out.append(res("Alerte du slicer", AVERT, a[:200]))
    return out, t


# --- Peigne de calibration : mesure les VRAIS jeux de SA machine
def peigne_calibration(d_tige=6.0, jeux=(0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)):
    """Une plaque avec 7 trous numérotés (Ø tige + 2×jeu) + une tige de Ø 6,00 + un cube 20 mm.
    On essaie la tige dans chaque trou : le 1er trou où elle GLISSE donne le vrai jeu de la machine."""
    import cadquery as cq
    n = len(jeux); pas = 12.0
    plaque = cq.Workplane("XY").box(pas * n + 6, 20, 5).translate((pas * (n - 1) / 2, 0, 2.5))
    for i, j in enumerate(jeux):
        plaque = plaque.cut(cq.Workplane("XY").circle((d_tige + 2 * j) / 2).extrude(20).translate((i * pas, 2, -5)))
        for k in range(i + 1):   # numéro du trou = nombre de petits points creux (lisibles, et pas de lettres trop fines)
            plaque = plaque.cut(cq.Workplane("XY").circle(0.8).extrude(1).translate((i * pas + ((k % 4) - min(i, 3) / 2) * 2.2, -6.0 - (k // 4) * 2.2, 4.4)))
    tige = cq.Workplane("XY").circle(d_tige / 2).extrude(15).faces(">Z").chamfer(0.4)
    cube = cq.Workplane("XY").box(20, 20, 20).translate((0, 0, 10))
    return {"peigne": Piece("peigne", plaque, orientation="telle"), "tige": Piece("tige", tige, orientation="telle"), "cube_20": Piece("cube_20", cube, orientation="telle")}, list(jeux)


def enregistrer_calibration(trou_qui_glisse, jeux=(0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40), cube_x=20.0, cube_y=20.0, jeu_glissement=0.05):
    """L'utilisateur dit le PREMIER trou où la tige GLISSE (n° 1 à 7) et la taille mesurée du cube.
    Cube : chaque surface extérieure sort de b_ext = (X − 20)/2. Tige dans le trou : ça glisse quand
    jeu dessiné − b_ext − b_trou ≥ ~0,05 mm  →  b_trou = jeu* − 0,05 − b_ext (peut être négatif : trous plus grands que dessinés).
    Résolution : le pas du peigne (0,05 mm)."""
    j = jeux[trou_qui_glisse - 1]
    b_ext = ((cube_x + cube_y) / 2 - 20.0) / 2
    b_trou = j - jeu_glissement - b_ext
    d = dict(machine=MACHINE.get("profil", PROFIL_MACHINE), jeu_glissant_mesure=j, xy_biais=round(b_ext, 3), trou_biais=round(b_trou, 3), resolution_mm=0.05, date=time.strftime("%Y-%m-%d"),
             note="xy_biais : surfaces extérieures (par côté); trou_biais : rétrécissement des trous (par côté). Utilisés par la simulation des 1 000 impressions.")
    os.makedirs(os.path.dirname(FICHIER_MACHINE), exist_ok=True)
    json.dump(d, open(FICHIER_MACHINE, "w"), ensure_ascii=False, indent=1)
    return d


# ----------------------------------------------------------------------------
# BLOC 5 — Visuel : visionneuse 3D (cell : tourne, éclaté, mouvement, coupe), comparaison de versions,
# grandeur réelle, plans cotés, notice de montage PDF
# ----------------------------------------------------------------------------
import base64 as _b64

_GABARIT_VISIONNEUSE = r"""<title>__TITRE__</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Atelier : établi graphite, plastique PETG orange comme seul accent. Visionneuse en haut, commandes au pouce en bas. */
:root{--fond:#eef0f2;--surface:#ffffff;--trait:#d5d9de;--texte:#1d2329;--doux:#5d6771;--accent:#e2702a;--ok:#2f8a4e;--avert:#b7791f;--echec:#c0392b;--scene:#e6e9ec;
--f-titre:"Archivo","Helvetica Neue",Arial,sans-serif;--f-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fond:#15191d;--surface:#1d2227;--trait:#2e353c;--texte:#e7ebee;--doux:#9aa4ad;--accent:#f08a45;--ok:#5fbf7f;--avert:#e0a948;--echec:#e86b5c;--scene:#1a1f24;color-scheme:dark}}
:root[data-theme="dark"]{--fond:#15191d;--surface:#1d2227;--trait:#2e353c;--texte:#e7ebee;--doux:#9aa4ad;--accent:#f08a45;--ok:#5fbf7f;--avert:#e0a948;--echec:#e86b5c;--scene:#1a1f24;color-scheme:dark}
body{background:var(--fond);color:var(--texte);font-family:var(--f-titre);padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:12px 24px}
.tete{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 16px;margin-bottom:10px}
h1{font-size:1.35rem;font-weight:800;letter-spacing:-.01em;margin:0;text-wrap:balance}
.cotes{font-family:var(--f-mono);font-size:.82rem;color:var(--doux);font-variant-numeric:tabular-nums}
.verdict{display:inline-flex;gap:8px;align-items:center;font-family:var(--f-mono);font-size:.8rem;padding:4px 10px;border-radius:999px;border:1px solid var(--trait);background:var(--surface)}
.verdict b{font-weight:500}
#scene{position:relative;width:100%;height:min(58vh,620px);min-height:300px;border-radius:14px;overflow:hidden;background:var(--scene);border:1px solid var(--trait);touch-action:none}
#scene canvas{display:block;width:100%;height:100%}
.astuce{position:absolute;left:12px;bottom:10px;font-family:var(--f-mono);font-size:.72rem;color:var(--doux);pointer-events:none}
.commandes{display:grid;gap:14px;margin-top:14px}
.ligne{display:grid;grid-template-columns:7.5rem 1fr auto;align-items:center;gap:10px}
.ligne label{font-size:.82rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--doux)}
.ligne output{font-family:var(--f-mono);font-size:.82rem;min-width:4.5rem;text-align:right;font-variant-numeric:tabular-nums}
input[type=range]{width:100%;accent-color:var(--accent);min-width:0}
select{font:inherit;font-size:.85rem;padding:6px 8px;border-radius:8px;border:1px solid var(--trait);background:var(--surface);color:var(--texte);max-width:100%}
.boutons{display:flex;flex-wrap:wrap;gap:8px}
button{font:inherit;font-size:.85rem;font-weight:700;padding:8px 14px;border-radius:999px;border:1px solid var(--trait);background:var(--surface);color:var(--texte);cursor:pointer}
button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.pieces{display:flex;flex-wrap:wrap;gap:8px}
.puce{display:inline-flex;align-items:center;gap:6px;font-size:.82rem;padding:5px 10px;border-radius:999px;border:1px solid var(--trait);background:var(--surface);cursor:pointer;user-select:none}
.puce i{width:12px;height:12px;border-radius:3px;display:inline-block}
.puce[aria-pressed="false"]{opacity:.45}
.verifs{margin-top:18px;border-top:1px solid var(--trait);padding-top:12px;font-size:.88rem;line-height:1.45}
.verifs h2{font-size:.82rem;text-transform:uppercase;letter-spacing:.08em;color:var(--doux);margin:0 0 8px}
.verifs ul{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.verifs li{display:grid;grid-template-columns:1.4rem 1fr;gap:6px;min-width:0}
.verifs li span{min-width:0;overflow-wrap:anywhere}
@media (max-width:480px){.ligne{grid-template-columns:5.6rem 1fr auto}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style>
<div class="tete"><h1>__TITRE__</h1><span class="cotes" id="cotes"></span></div>
<div class="verdict" id="verdict" hidden></div>
<div id="scene" style="margin-top:10px"><span class="astuce">1 doigt : tourner · 2 doigts : zoomer / déplacer</span></div>
<div class="commandes">
  <div class="boutons" role="group" aria-label="Affichage">
    <button id="b-tourne" aria-pressed="true">Tourne tout seul</button>
    <button id="b-vue" aria-pressed="false">Recentrer</button>
    <button id="b-fil" aria-pressed="false">Arêtes</button>
  </div>
  <div class="ligne"><label for="r-eclate">Éclaté</label><input id="r-eclate" type="range" min="0" max="100" value="0"><output id="o-eclate">0 %</output></div>
  <div class="ligne" id="l-mvt" hidden><label for="r-mvt">Mouvement</label><input id="r-mvt" type="range" min="0" max="1000" value="0"><output id="o-mvt"></output></div>
  <div class="ligne" id="l-mvt-choix" hidden><label for="s-mvt">Lequel</label><select id="s-mvt"></select><span></span></div>
  <div class="ligne"><label for="r-coupe">Coupe</label><input id="r-coupe" type="range" min="0" max="1000" value="1000"><output id="o-coupe">aucune</output></div>
  <div class="pieces" id="pieces" role="group" aria-label="Pièces visibles"></div>
</div>
<section class="verifs" id="verifs" hidden><h2>Vérifications LC3D</h2><ul id="liste"></ul></section>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const DONNEES = __DONNEES__;
(function(){
  const el = document.getElementById("scene");
  const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const renderer = new THREE.WebGLRenderer({antialias:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1, 2));
  renderer.localClippingEnabled = true;
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 0.85));
  const sol = new THREE.DirectionalLight(0xffffff, 0.75); sol.position.set(1, -1.4, 2.2); scene.add(sol);
  const contre = new THREE.DirectionalLight(0xffffff, 0.35); contre.position.set(-1.5, 1, 0.6); scene.add(contre);
  const racine = new THREE.Group(); racine.rotation.x = -Math.PI/2; scene.add(racine);   // Z de la CAO vers le haut
  const b64 = (s, T) => { const bin = atob(s); const u = new Uint8Array(bin.length); for (let i=0;i<bin.length;i++) u[i]=bin.charCodeAt(i); return new T(u.buffer); };
  const plan = new THREE.Plane(new THREE.Vector3(-1,0,0), 1e6);
  const objets = {};
  let rayon = 50; const centre = new THREE.Vector3(...DONNEES.centre);
  DONNEES.pieces.forEach(p => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(b64(p.v, Float32Array), 3));
    g.setIndex(new THREE.BufferAttribute(b64(p.f, Uint32Array), 1));
    g.computeVertexNormals();
    const coul = new THREE.Color(...p.c);
    const mat = new THREE.MeshStandardMaterial({color:coul, roughness:p.achetee?0.35:0.62, metalness:p.achetee?0.55:0.0, clippingPlanes:[plan], side:THREE.FrontSide, flatShading:false});
    const dos = new THREE.MeshBasicMaterial({color:new THREE.Color(css("--echec")||"#c0392b"), clippingPlanes:[plan], side:THREE.BackSide});
    const grp = new THREE.Group();
    const m1 = new THREE.Mesh(g, mat), m2 = new THREE.Mesh(g, dos);
    const aretes = new THREE.LineSegments(new THREE.EdgesGeometry(g, 28), new THREE.LineBasicMaterial({color:0x222222, transparent:true, opacity:.45, clippingPlanes:[plan]}));
    aretes.visible = false;
    grp.add(m1); grp.add(m2); grp.add(aretes);
    grp.matrixAutoUpdate = false;
    racine.add(grp);
    objets[p.nom] = {grp, pose:new THREE.Matrix4().fromArray(p.pose).transpose(), eclate:new THREE.Vector3(...p.eclate), aretes};
  });
  rayon = DONNEES.rayon;
  const controles = new THREE.OrbitControls(camera, renderer.domElement);
  controles.enableDamping = true; controles.autoRotate = true; controles.autoRotateSpeed = 1.6;
  const cible = new THREE.Vector3(centre.x, centre.z, -centre.y);
  function recentrer(){ controles.target.copy(cible); camera.position.set(cible.x + rayon*1.9, cible.y + rayon*1.25, cible.z + rayon*2.2); camera.near = rayon/100; camera.far = rayon*60; camera.updateProjectionMatrix(); controles.update(); }
  recentrer();
  function fond(){ renderer.setClearColor(new THREE.Color(css("--scene")||"#e6e9ec")); }
  fond(); try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", fond); new MutationObserver(fond).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]}); } catch(e){}
  // --- mouvements
  const mvts = DONNEES.mouvements; let iMvt = 0, tMvt = 0;
  const sel = document.getElementById("s-mvt");
  if (mvts.length){ document.getElementById("l-mvt").hidden = false; if (mvts.length>1){ document.getElementById("l-mvt-choix").hidden=false; mvts.forEach((m,i)=>{const o=document.createElement("option"); o.value=i; o.textContent=m.titre; sel.appendChild(o);}); } }
  function matMvt(type, pivot, axe, v){
    const M = new THREE.Matrix4();
    if (type === "rotation"){ const a = new THREE.Vector3(...axe).normalize(); const P = new THREE.Vector3(...pivot);
      M.makeTranslation(P.x,P.y,P.z).multiply(new THREE.Matrix4().makeRotationAxis(a, v*Math.PI/180)).multiply(new THREE.Matrix4().makeTranslation(-P.x,-P.y,-P.z)); }
    else { const a = new THREE.Vector3(...axe).normalize().multiplyScalar(v); M.makeTranslation(a.x,a.y,a.z); }
    return M;
  }
  let eclate = 0;
  function poser(){
    const rel = {};
    if (mvts.length){ const m = mvts[iMvt]; const v = m.de + (m.a - m.de)*tMvt;
      rel[m.piece] = matMvt(m.type, m.pivot, m.axe, v);
      m.entraine.forEach(e => { rel[e.piece] = matMvt(e.type||"rotation", e.pivot||[0,0,0], e.axe||[0,0,1], v*(e.ratio==null?1:e.ratio)); });
      document.getElementById("o-mvt").textContent = (m.type==="rotation" ? v.toFixed(0)+"°" : v.toFixed(1)+" mm"); }
    for (const [nom,o] of Object.entries(objets)){
      const M = new THREE.Matrix4().makeTranslation(o.eclate.x*eclate, o.eclate.y*eclate, o.eclate.z*eclate);
      if (rel[nom]) M.multiply(rel[nom]);
      M.multiply(o.pose); o.grp.matrix.copy(M); o.grp.matrixWorldNeedsUpdate = true;
    }
  }
  poser();
  document.getElementById("r-eclate").addEventListener("input", e => { eclate = e.target.value/100; document.getElementById("o-eclate").textContent = e.target.value+" %"; poser(); });
  document.getElementById("r-mvt").addEventListener("input", e => { tMvt = e.target.value/1000; poser(); });
  sel.addEventListener("change", e => { iMvt = +e.target.value; tMvt = 0; document.getElementById("r-mvt").value = 0; poser(); });
  const [xmin, xmax] = DONNEES.etendue_x;
  document.getElementById("r-coupe").addEventListener("input", e => { const t = e.target.value/1000;
    if (t >= 0.999){ plan.constant = 1e6; document.getElementById("o-coupe").textContent = "aucune"; }
    else { const x = xmin + (xmax - xmin)*t; plan.constant = x; document.getElementById("o-coupe").textContent = "X " + x.toFixed(1); } });
  const bT = document.getElementById("b-tourne"); bT.addEventListener("click", () => { controles.autoRotate = !controles.autoRotate; bT.setAttribute("aria-pressed", controles.autoRotate); });
  document.getElementById("b-vue").addEventListener("click", recentrer);
  const bF = document.getElementById("b-fil"); bF.addEventListener("click", () => { const on = bF.getAttribute("aria-pressed")!=="true"; bF.setAttribute("aria-pressed", on); Object.values(objets).forEach(o=>o.aretes.visible=on); });
  const zp = document.getElementById("pieces");
  DONNEES.pieces.forEach(p => { const b = document.createElement("button"); b.className="puce"; b.setAttribute("aria-pressed","true");
    b.innerHTML = `<i style="background:rgb(${p.c.map(x=>Math.round(x*255)).join(",")})"></i>`; b.append(p.nom + (p.achetee ? " (achetée)" : ""));
    b.addEventListener("click", () => { const on = b.getAttribute("aria-pressed")!=="true"; b.setAttribute("aria-pressed", on); objets[p.nom].grp.visible = on; }); zp.appendChild(b); });
  document.getElementById("cotes").textContent = DONNEES.cotes;
  if (DONNEES.verdict){ const v = document.getElementById("verdict"); v.hidden=false; v.innerHTML = `<b>${DONNEES.verdict}</b>` + (DONNEES.score!=null ? ` · 1re impression ${DONNEES.score} %` : ""); }
  if (DONNEES.verifs && DONNEES.verifs.length){ document.getElementById("verifs").hidden=false; const ul=document.getElementById("liste");
    DONNEES.verifs.forEach(r => { const li=document.createElement("li"); const a=document.createElement("b"); a.textContent=r[0]; const s=document.createElement("span"); s.textContent=r[1]; li.append(a,s); ul.appendChild(li); }); }
  function taille(){ const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h, false); camera.aspect = w/h; camera.updateProjectionMatrix(); }
  new ResizeObserver(taille).observe(el); taille();
  const reduit = matchMedia("(prefers-reduced-motion: reduce)").matches; if (reduit){ controles.autoRotate=false; bT.setAttribute("aria-pressed","false"); }
  (function boucle(){ requestAnimationFrame(boucle); controles.update(); renderer.render(scene, camera); })();
})();
</script>
"""


def visionneuse(chemin, meshes, poses=None, mouvements=None, titre="Pièce LC3D", R=None, achetees=(), max_faces=250000, sequence=None):
    """Page 3D autonome pour le cell (Three.js) : la pièce tourne, éclaté, mouvements de l'assemblage, coupe glissante.
    meshes : {nom: maillage NON placé}; poses : {nom: 4×4}. À publier comme artifact (un seul fichier)."""
    poses = poses or {}
    noms = list(meshes)
    total = sum(len(m.faces) for m in meshes.values())
    places = {}
    for n, m in meshes.items():
        mm = m.copy(); mm.apply_transform(poses.get(n, np.eye(4))); places[n] = mm
    ens = trimesh.util.concatenate(list(places.values()))
    c = ens.bounds.mean(0); rayon = float(np.linalg.norm(ens.extents)) / 2
    pieces = []
    for i, n in enumerate(noms):
        m = meshes[n]
        if total > max_faces and len(m.faces) > 2000:
            try:
                m = m.simplify_quadric_decimation(face_count=max(2000, int(len(m.faces) * max_faces / total)))
            except Exception:
                pass
        dir_ = places[n].centroid - c
        if np.linalg.norm(dir_) < 1e-6: dir_ = np.array([0, 0, 1.0])
        ecl = dir_ / np.linalg.norm(dir_) * rayon * 0.9
        pieces.append(dict(nom=n, v=_b64.b64encode(np.asarray(m.vertices, np.float32).tobytes()).decode(),
                           f=_b64.b64encode(np.asarray(m.faces, np.uint32).tobytes()).decode(),
                           c=list((0.62, 0.64, 0.68) if n in achetees else PALETTE_STUDIO[i % len(PALETTE_STUDIO)]), achetee=n in achetees,
                           pose=np.asarray(poses.get(n, np.eye(4)), float).flatten().tolist(), eclate=ecl.tolist(),
                           mesures=mesures_piece(meshes[n])))
    # la scène tourne de -90° autour de X (Z CAO vers le haut) : la coupe se fait sur X, qui ne change pas
    e = ens.extents
    verifs = []
    if R:
        for nom_p, P in R.get("pieces", {}).items():
            for r in P["resultats"]:
                if r["statut"] in (ECHEC, AVERT): verifs.append((r["statut"], f"{nom_p} — {r['verif']} : {r['detail']}"[:240]))
        for r in R.get("assemblage", []):
            if r["statut"] in (ECHEC, AVERT, OK) and not r["verif"].startswith("Taille totale"):
                verifs.append((r["statut"], f"{r['verif']} : {r['detail']}"[:240]))
    donnees = dict(pieces=pieces, centre=c.tolist(), rayon=rayon, etendue_x=[float(ens.bounds[0, 0]) - 1, float(ens.bounds[1, 0]) + 1],
                   mouvements=[dict(titre=mv["titre"], piece=mv["piece"], type=mv["type"], pivot=list(mv["pivot"]), axe=list(mv["axe"]), de=mv["de"], a=mv["a"], pas_filet=mv.get("pas_filet"),
                                    entraine=[dict(piece=x["piece"], type=x.get("type", "rotation"), pivot=list(x.get("pivot", (0, 0, 0))), axe=list(x.get("axe", (0, 0, 1))), ratio=x.get("ratio", 1.0)) for x in mv["entraine"]])
                               for mv in (mouvements or [])],
                   cotes=f"{e[0]:.1f} × {e[1]:.1f} × {e[2]:.1f} mm", verdict=(R or {}).get("verdict"), score=(R or {}).get("score_premiere_impression"),
                   verifs=verifs[:40])
    donnees["zmin"] = float(ens.bounds[0, 2])
    donnees["sequence"] = [{k: (list(v) if isinstance(v, tuple) else v) for k, v in s_.items()} for s_ in (sequence or [])]
    donnees["titre"] = titre
    if chemin is None:
        return donnees
    html = _GABARIT_VISIONNEUSE.replace("__TITRE__", titre.replace("<", "")).replace("__DONNEES__", json.dumps(donnees, ensure_ascii=False))
    open(chemin, "w").write(html)
    return dict(chemin=chemin, taille_ko=round(os.path.getsize(chemin) / 1024), faces=sum(len(_b64.b64decode(p["f"])) // 12 for p in pieces))



# --- LC3D Studio : paquet à pousser vers l'écran en direct (scene.json + livraison.json + photo)
def exporter_studio(sortie, brut_meshes, A, R, titre, achetees=()):
    """Écrit sortie/studio/scene.json (maillages, poses, éclaté, mouvements, chemin de montage, professeurs)
    et, si le zip existe, sortie/studio/livraison.json (zip en base64). Claude les téléverse puis met à jour la db."""
    d = os.path.join(sortie, "studio"); os.makedirs(d, exist_ok=True)
    poses = A.poses if A is not None else {}
    sc = visionneuse(None, brut_meshes, poses, getattr(A, "mouvements", []) if A is not None else [], titre, R,
                     achetees=achetees, max_faces=300000, sequence=getattr(A, "sequence", []) if A is not None else [])
    profs = []
    for nom_p, P in R.get("pieces", {}).items():
        profs.append(dict(qui=f"Impression — {nom_p}", resultats=[dict(s=r["statut"], v=r["verif"], d=str(r["detail"])[:300], c=r.get("conseil")) for r in P["resultats"]]))
    if R.get("assemblage"):
        profs.append(dict(qui="Montage et mécanique", resultats=[dict(s=r["statut"], v=r["verif"], d=str(r["detail"])[:300], c=r.get("conseil")) for r in R["assemblage"]]))
    sc.pop("verifs", None)
    sc["params"] = dict(PARAMS_STUDIO)
    sc.update(professeurs=profs, compte=R.get("compte"), non_prouve=R.get("non_prouve"), erreurs=R.get("erreurs", []),
              pieces_info={n: dict(temps=(P.get("tranchage") or {}).get("temps"), grammes=(P.get("tranchage") or {}).get("grammes")) for n, P in R.get("pieces", {}).items()})
    json.dump(sc, open(os.path.join(d, "scene.json"), "w"), ensure_ascii=False, separators=(",", ":"), default=str)
    out = dict(scene=os.path.join(d, "scene.json"))
    if R.get("zip") and os.path.exists(str(R["zip"])):
        json.dump(dict(nom=os.path.basename(R["zip"]), b64=_b64.b64encode(open(R["zip"], "rb").read()).decode()),
                  open(os.path.join(d, "livraison.json"), "w"))
        out["livraison"] = os.path.join(d, "livraison.json")
    if R.get("photo"):
        out["photo"] = R["photo"]
        try:
            from PIL import Image
            Image.open(R["photo"]).convert("RGB").save(os.path.join(sortie, "photo.jpg"), quality=86)
        except Exception:
            pass
    feu = "rouge" if R["compte"][ECHEC] else ("jaune" if R["compte"][AVERT] else "vert")
    out["etat"] = dict(feu=feu, verdict=R["verdict"], score=R.get("score_premiere_impression"), compte={"ok": R["compte"][OK], "avert": R["compte"][AVERT], "echec": R["compte"][ECHEC]})
    json.dump(out, open(os.path.join(d, "a_pousser.json"), "w"), ensure_ascii=False, indent=1, default=str)
    return out


def apercu_studio(chemin_modele, sets=None, sortie=None):
    """Aperçu RAPIDE pour le Studio pendant la construction : maillages + positions, aucune vérif (quelques secondes)."""
    sortie = sortie or os.path.join(os.path.dirname(os.path.abspath(chemin_modele)), "apercu")
    JOURNAL.clear()
    mod = _charger_modele(chemin_modele); p = _parse_set(sets, getattr(mod, "PARAMS", {})); _noter_params(mod, p)
    brut = mod.build(p); pieces = {}
    for nom, v in (brut.items() if isinstance(brut, dict) else [(x.nom, x) for x in brut]):
        pieces[nom] = v if isinstance(v, Piece) else Piece(nom, v); pieces[nom].nom = nom
    meshes = {n: vers_mesh(pc.forme, tol=0.05, ang=0.2) for n, pc in pieces.items()}
    A = None
    if hasattr(mod, "assembly"):
        try: A = mod.assembly(p, pieces)
        except Exception: A = None
    achetees = [n for n, pc in pieces.items() if pc.role == "achetee"]
    garde = garde_express(pieces, meshes)
    R = dict(projet=os.path.splitext(os.path.basename(chemin_modele))[0], pieces={}, compte={OK: 0, AVERT: 0, ECHEC: 0}, verdict="en construction")
    out = exporter_studio(sortie, meshes, A, R, R["projet"].replace("_", " "), achetees=achetees)
    if JOURNAL:
        sc = json.load(open(out["scene"])); sc["gestes"], sc["nb_gestes"] = gestes_pour_studio()
        try: sc["live"] = live_studio(mod, p)
        except Exception as e: sc["live"] = dict(ok=False, raison=str(e)[:160])
        sc["gestes"], sc["nb_gestes"] = gestes_pour_studio()
        json.dump(sc, open(out["scene"], "w"), ensure_ascii=False, separators=(",", ":"))
    out["etat"] = dict(feu="travail")
    out["garde_fous"] = garde
    json.dump(out, open(os.path.join(sortie, "studio", "a_pousser.json"), "w"), ensure_ascii=False, indent=1, default=str)
    return out


def _matrice_orientation(piece, m):
    al = {"retourner": ((1, 0, 0), 180), "retournee": ((1, 0, 0), 180), "retournée": ((1, 0, 0), 180), "couche": ((1, 0, 0), 90), "couchée": ((1, 0, 0), 90)}
    o = piece.orientation
    if isinstance(o, str): o = al.get(o.strip().lower(), o)
    if isinstance(o, tuple): return trimesh.transformations.rotation_matrix(math.radians(o[1]), o[0])
    if isinstance(o, str) and o.strip().lower() == "auto": return choisir_orientation(m, axe_flexion=piece.axe_flexion)[0]["M"]
    if o is not None and not isinstance(o, str): return np.array(o)
    return np.eye(4)


def garde_express(pieces, meshes):
    """GARDE-FOUS pendant la construction (quelques secondes) : îlots dans le vide, détails plus fins que la buse,
    murs sous 2 lignes, couche par couche dans l'orientation d'impression. Le défaut est vu au geste près, avant le run."""
    out = {}
    for n, pc in pieces.items():
        if pc.role == "achetee" or n not in meshes: continue
        try:
            m = meshes[n].copy(); m.apply_transform(_matrice_orientation(pc, m)); m.apply_translation((0, 0, -m.bounds[0][2]))
            A = analyse_couches(m)
            res_ = [r for r in verif_couches(m, pc, A) if r["statut"] == ECHEC]
            try:     # murs et fentes, réglages rapides (le run complet refait la mesure fine)
                ma = affiner(m, RAPIDE["affiner_faces"]); ep, fe, pe, pf = epaisseurs_par_face(ma, RAPIDE["rayons_faces"])
                res_ += [r for r in verif_epaisseurs(ma, pc, ep, fe, pe, pf) if r["statut"] == ECHEC]
            except Exception:
                pass
            out[n] = [dict(titre=r["verif"], detail=r["detail"], conseil=r.get("conseil", "")) for r in res_]
        except Exception as e:
            out[n] = [dict(titre="garde-fou non calculé", detail=str(e)[:200], conseil="le run complet tranchera")]
    return out


def morceaux_studio(chemin, fichier_id, dossier, taille=180000):
    """Découpe un fichier (gzip + base64) en documents de base de données pour le Studio.
    Retourne la liste des écritures pour ArtifactData batch (collection fichiers/<id>/morceaux)."""
    import gzip
    brut = open(chemin, "rb").read()
    z = _b64.b64encode(gzip.compress(brut, 6)).decode()
    parts = [z[i:i + taille] for i in range(0, len(z), taille)] or [""]
    os.makedirs(dossier, exist_ok=True)
    ecr = []
    for k, p in enumerate(parts):
        f = os.path.join(dossier, f"{fichier_id}_{k:03d}.json")
        json.dump(dict(k=k, n=len(parts), data=p), open(f, "w"))
        ecr.append(dict(op="set", collection=f"fichiers/{fichier_id}/morceaux", doc_id=f"m{k:03d}", file_path=os.path.abspath(f)))
    return ecr


def paquet_studio(sortie, projet, version, etat=None, message="", imprimante=None, etape=None):
    """Prépare UNE écriture groupée (ArtifactData batch) : morceaux de la scène, de la photo, du zip + studio/courant.
    Écrit sortie/studio/batch.json : la liste `writes` à passer telle quelle (si > 1 Mo : plusieurs lots batch_N.json)."""
    import hashlib, re as _re
    d = os.path.join(sortie, "studio"); db = os.path.join(d, "db"); os.makedirs(db, exist_ok=True)
    for f in glob.glob(os.path.join(db, "*.json")): os.unlink(f)
    import unicodedata
    slug = _re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", projet.lower()).encode("ascii", "ignore").decode()).strip("-")[:40] or "projet"
    ecr, champs = [], {}
    for cle, chemin in (("scene", os.path.join(d, "scene.json")), ("livraison", os.path.join(d, "livraison.json")), ("photo", os.path.join(sortie, "photo.jpg"))):
        if os.path.exists(chemin):
            fid = f"{slug}-{version}-{cle}-" + hashlib.sha1(open(chemin, "rb").read()).hexdigest()[:8]
            ecr += morceaux_studio(chemin, fid, db); champs[cle] = fid
    courant = dict(projet=projet, version=version, message=message, maj=time.strftime("%Y-%m-%dT%H:%M:%S"), **champs)
    for cle in ("scene", "livraison", "photo"):
        courant.setdefault(cle, {"__delete__": True})        # pas d'ancienne photo / ancien zip d'une autre version
    if etape != "pret": courant["independant"] = {"__delete__": True}
    courant["questions"] = {"__delete__": True}
    if imprimante: courant["imprimante"] = imprimante
    if etape: courant["etape"] = etape
    if etat: courant.update({k: v for k, v in etat.items() if k in ("feu", "verdict", "score", "compte", "garde")})
    courant.setdefault("garde", {"__delete__": True})
    f = os.path.join(db, "courant.json"); json.dump(courant, open(f, "w"), ensure_ascii=False)
    lots, lot, poids = [], [], 0
    for e in ecr:
        p = os.path.getsize(e["file_path"])
        if lot and (poids + p > 900000 or len(lot) >= 45): lots.append(lot); lot, poids = [], 0
        lot.append(e); poids += p
    lot.append(dict(op="update", collection="studio", doc_id="courant", file_path=os.path.abspath(f))); lots.append(lot)
    noms = []
    for i, l in enumerate(lots):
        n = os.path.join(d, f"batch_{i}.json"); json.dump(l, open(n, "w"), ensure_ascii=False, indent=0); noms.append(n)
    return dict(lots=noms, courant=courant, note="Le dernier lot met à jour studio/courant : il faut son if_version (lire studio/courant d'abord).")


# ---------- Studio hébergé (n'importe quelle IA : Claude, Kimi, Codex…) ----------
STUDIO_EN_LIGNE = "https://lc3d-studio.lc3d.workers.dev"


def studio_conf(creer=True):
    """Le Studio de cette personne → (base, clé).
    Ordre : LC3D_STUDIO (lien avec #cle=…) ; sinon ~/.lc3d/studio.json ; sinon un Studio est créé tout seul et gardé là."""
    from urllib.parse import urlsplit, parse_qs
    lien = os.environ.get("LC3D_STUDIO", "").strip()
    fich = os.path.join(os.path.expanduser("~"), ".lc3d", "studio.json")
    if not lien and os.path.exists(fich):
        try: lien = json.load(open(fich)).get("lien", "")
        except Exception: lien = ""
    if not lien:
        if not creer: return None, None
        base = os.environ.get("LC3D_STUDIO_URL", STUDIO_EN_LIGNE).rstrip("/")
        cle = _studio_api("espace", {}, base, "")["cle"]
        lien = f"{base}/#cle={cle}"
        os.makedirs(os.path.dirname(fich), exist_ok=True)
        json.dump(dict(lien=lien, cree=time.strftime("%Y-%m-%d %H:%M")), open(fich, "w"))
    u = urlsplit(lien)
    cle = (parse_qs(u.fragment).get("cle") or parse_qs(u.query).get("cle") or [""])[0]
    if not cle: raise RuntimeError("le lien du Studio doit contenir #cle=…")
    return f"{u.scheme}://{u.netloc}", cle


def studio_ouvrir(navigateur=True):
    """Donne le lien du Studio de cette personne (le crée la première fois) et l'ouvre dans le navigateur si possible."""
    base, cle = studio_conf()
    lien = f"{base}/#cle={cle}"
    ouvert = False
    if navigateur:
        try:
            import webbrowser; ouvert = webbrowser.open(lien)
        except Exception: ouvert = False
    return dict(studio=lien, ouvert=ouvert, note="Donne ce lien à la personne : c'est SON Studio (garde-le privé). La pièce y apparaît à chaque studio-pousser.")


def _studio_api(chemin, corps=None, base=None, cle=None):
    import urllib.request, urllib.error
    if base is None: base, cle = studio_conf()
    req = urllib.request.Request(base + "/api/" + chemin, method="POST" if corps is not None else "GET",
                                 data=None if corps is None else json.dumps(corps, ensure_ascii=False).encode(),
                                 headers={"content-type": "application/json", "x-lc3d-cle": cle, "user-agent": "lc3d"})
    for essai in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if (e.code < 500 and e.code != 429) or essai == 2: raise RuntimeError(f"Studio : HTTP {e.code} {msg[:300]}")
        except urllib.error.URLError as e:
            if essai == 2: raise RuntimeError(f"Studio injoignable : {e.reason}")
        time.sleep(1.5 * (essai + 1))


def studio_pousser(sortie, projet, version, etat=None, message="", imprimante=None, etape=None):
    """Prépare le paquet (comme studio-paquet) puis l'envoie au Studio hébergé par petits lots (le dernier met studio/courant à jour).
    Étape « pret » : copie aussi la version dans versions/<projet>-<version> (historique de la page)."""
    base, cle = studio_conf()
    pq = paquet_studio(sortie, projet, version, etat, message, imprimante, etape)
    ecr = []
    for n in pq["lots"]:
        for e in json.load(open(n)):
            ecr.append(dict(op=e["op"], collection=e["collection"], doc_id=e["doc_id"], data=json.load(open(e["file_path"]))))
    fin = ecr.pop()                                   # studio/courant : en dernier, une fois les fichiers arrivés
    lots, lot, poids = [], [], 0
    for e in ecr:
        p = len(json.dumps(e["data"]))
        if lot and (poids + p > 250000 or len(lot) >= 20): lots.append(lot); lot, poids = [], 0
        lot.append(e); poids += p
    if lot: lots.append(lot)
    for l in lots: _studio_api("batch", dict(writes=l), base, cle)
    _studio_api("batch", dict(writes=[fin]), base, cle)
    if etape == "pret":
        import unicodedata
        slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", projet.lower()).encode("ascii", "ignore").decode()).strip("-")[:40] or "projet"
        cour = _studio_api("doc?col=studio&id=courant", None, base, cle).get("data") or {}
        _studio_api("batch", dict(writes=[dict(op="set", collection="versions", doc_id=f"{slug}-{version}", data=cour)]), base, cle)
    return dict(envoye=True, lots=len(lots) + 1, studio=f"{base}/#cle={cle}", courant=pq["courant"])


def studio_lire(chemin):
    """chemin = « studio/ici », « studio/demande »… (un document) ou une collection (« bibliotheque »)."""
    from urllib.parse import quote
    parts = chemin.strip("/").split("/")
    if len(parts) % 2 == 0:
        return _studio_api(f"doc?col={quote('/'.join(parts[:-1]), safe='')}&id={quote(parts[-1], safe='')}")
    docs, apres = [], ""
    while True:
        r = _studio_api(f"col?col={quote(chemin.strip('/'), safe='')}&apres={quote(apres, safe='')}")
        docs += r["docs"]
        if not (r.get("plus") and r["docs"]): return dict(docs=docs)
        apres = r["docs"][-1]["id"]


def studio_ecrire(chemin, donnees, fusionner=False):
    """Écrit un document (set, ou update avec fusionner=True ; {"__delete__": true} enlève un champ)."""
    parts = chemin.strip("/").split("/")
    if len(parts) % 2: raise RuntimeError("chemin de document attendu : collection/id (ex. studio/courant)")
    return _studio_api("batch", dict(writes=[dict(op="update" if fusionner else "set", collection="/".join(parts[:-1]), doc_id=parts[-1], data=donnees)]))


def _shape_cq(f):
    import cadquery as cq
    if isinstance(f, cq.Workplane):
        return f.val() if len(f.vals()) == 1 else cq.Compound.makeCompound(f.vals())
    if isinstance(f, cq.Shape): return f
    if hasattr(f, "wrapped"): return cq.Shape.cast(f.wrapped)
    return None


def verif_validite(nom, forme, journal=()):
    """Solide CadQuery invalide (isValid() faux, ex. chanfrein tangent à un trou) : ❌ « géométrie invalide après le geste X »,
    sauf si shape.fix() le répare (⚠️ et on continue avec la forme réparée). Retourne (résultats, forme à utiliser)."""
    if isinstance(forme, (trimesh.Trimesh, trimesh.Scene)): return [], forme
    try:
        sh = _shape_cq(forme)
        if sh is None or sh.isValid(): return [], forme
    except Exception:
        return [], forme
    geste = None
    for g in journal:
        if g.get("piece") != nom: continue
        try:
            a_ = _shape_cq(g["apres"])
            if a_ is not None and not a_.isValid(): geste = g.get("titre"); break
        except Exception:
            pass
    ou = f" après le geste « {geste} »" if geste else ""
    try:
        import cadquery as cq
        rep = sh.fix()
        if rep.isValid():
            return [res("Géométrie CAO valide", AVERT, f"{nom} : solide invalide{ou}, réparé automatiquement (shape.fix()) — vérifier la forme sur les images.",
                        conseil="Le geste en cause touche souvent une surface tangente (chanfrein/arrondi qui rejoint un trou) : réduire la cote.")], cq.Workplane("XY").add(rep)
    except Exception:
        pass
    return [res("Géométrie CAO valide", ECHEC, f"{nom} : géométrie invalide{ou} (OpenCascade isValid() = faux, non réparable) — le maillage, les mesures et l'export ne sont pas fiables.",
                conseil="Changer ce geste (arrondi/chanfrein plus petit, ou fait avant le perçage); éviter les surfaces tangentes.")], forme


def _mesures_cao(f):
    """Volume, centre de masse et boîte OPTIMALE d'une forme CadQuery/build123d, calculés sur le B-rep (pas de maillage)."""
    import cadquery as cq
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    if isinstance(f, cq.Workplane):
        sh = f.val() if len(f.vals()) == 1 else cq.Compound.makeCompound(f.vals())
    elif isinstance(f, cq.Shape):
        sh = f
    else:
        sh = cq.Shape.cast(f.wrapped)
    if not sh.isValid():
        raise ValueError("géométrie CAO invalide (isValid() = faux) : référence impossible — voir le rapport de run (« Géométrie CAO valide »)")
    c = sh.Center(); b = Bnd_Box(); BRepBndLib.AddOptimal_s(sh.wrapped, b, False, False)
    x0, y0, z0, x1, y1, z1 = b.Get()
    return dict(volume=round(float(sh.Volume()), 3), centre=[round(float(x), 4) for x in (c.x, c.y, c.z)],
                boite=[round(float(x), 4) for x in (x0, y0, z0, x1, y1, z1)],
                faces=len(sh.Faces()))     # nombre de faces B-rep : un arrondi sur 2 arêtes de trop change à peine le volume, mais pas ce nombre


def _attendus_cao(mod, p, facteur=1.1):
    """Volumes que DOIT donner chaque logiciel CAO : pièce de base + chaque cote ×1,1 (calculés par LC3D lui-même).
    touche_fixe = la cote change une forme « fixe » (non paramétrique) → elle ne peut pas suivre dans le logiciel."""
    def construire(pp):
        JOURNAL.clear(); pcs = mod.build(pp)
        vols = {}
        for n, pc in (pcs.items() if isinstance(pcs, dict) else []):
            f = pc.forme if isinstance(pc, Piece) else pc
            if isinstance(f, trimesh.Trimesh): continue
            # mesures EXACTES sur la forme CAO (OpenCascade : propriétés de masse + boîte optimale) — aucun maillage
            # (avant : maillage à 0,005 mm sans limite, un STEP de moteur NEMA 17 de 8 Mo épuisait la mémoire)
            vols[n] = _mesures_cao(f)
        sig = []
        for g in JOURNAL:
            if not g.get("recette") or g["recette"].get("type") == "remplace":
                f = g["outil"] if g.get("recette") is None else g["apres"]
                try:
                    # volume + centre de masse EXACTS (la boîte englobante d'OpenCascade dépend du maillage déjà fait :
                    # ±0,001 mm d'un essai à l'autre → fausse « forme fixe touchée » et la cote n'était plus vérifiée)
                    import cadquery as _cq
                    sh = _cq.Compound.makeCompound(f.vals()) if hasattr(f, "vals") else f
                    c_ = sh.Center()
                    sig.append((round(sh.Volume(), 2),) + tuple(round(x, 3) for x in (c_.x, c_.y, c_.z)))
                except Exception:
                    sig.append(None)
        return vols, sig
    base, sig0 = construire(dict(p))
    essais = {}
    for k, v in p.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v == 0: continue
        pp = dict(p); pp[k] = v * facteur
        try:
            vols, sig = construire(pp)
            essais[k] = dict(valeur=round(v * facteur, 6), mesures=vols, touche_fixe=sig != sig0)
        except Exception as e:
            essais[k] = dict(valeur=round(v * facteur, 6), mesures={}, touche_fixe=False, erreur_lc3d=f"{type(e).__name__}: {e}")
    JOURNAL.clear()
    return dict(base=base, essais=essais)


def _comparer_mesures(m, attendus, faces=None):
    """Maillage OpenSCAD (toutes pièces ensemble) vs mesures LC3D : volume < 0,5 %, centre < 0,1 mm, boîte < 0,1 mm.
    (OpenSCAD facette les cercles à $fn=96 : ≈ 0,07 % de volume en moins, sous le seuil.)"""
    V = sum(a["volume"] for a in attendus.values())
    C = [sum(a["volume"] * a["centre"][i] for a in attendus.values()) / V for i in range(3)]
    B = [min(a["boite"][i] for a in attendus.values()) for i in range(3)] + [max(a["boite"][i] for a in attendus.values()) for i in range(3, 6)]
    ev = 100 * abs(m.volume - V) / V; ec = max(abs(x - y) for x, y in zip(m.center_mass, C))
    eb = max(abs(x - y) for x, y in zip(list(m.bounds[0]) + list(m.bounds[1]), B))
    out = dict(ok=bool(ev < 0.5 and ec < 0.1 and eb < 0.1), ecart_volume_pct=round(ev, 3), ecart_centre_mm=round(ec, 3), ecart_boite_mm=round(eb, 3))
    # nombre de faces B-rep (clé « faces », facultative : absente d'un côté = pas comparée). Un maillage (OpenSCAD) n'en a pas.
    fa = [a.get("faces") for a in attendus.values()]
    if faces is not None and all(x is not None for x in fa):
        out["faces"], out["faces_attendues"] = int(faces), int(sum(fa))
        if int(faces) != int(sum(fa)):
            out["ok"] = False; out["note_faces"] = "❌ arêtes traitées différentes (nombre de faces ≠ LC3D)"
    return out


def lot_fusion(chemin_modele):
    """Juste ce qu'il faut pour le script Fusion d'un modèle (recettes + mesures attendues), sans FreeCAD ni OpenSCAD."""
    import lc3d_freecad as LF, cadquery as cq
    mod = _charger_modele(chemin_modele); p = _parse_set(None, getattr(mod, "PARAMS", {}))
    attendus = _attendus_cao(mod, p); JOURNAL.clear()
    mod.build(LF.params_parametriques(p))
    recettes, d = {}, tempfile.mkdtemp()
    for i, g in enumerate(JOURNAL):
        r = dict(g.get("recette") or dict(type="fixe"), titre=g["titre"], op=g["op"] if g["op"] != "modif" else "ajout")
        if r["type"] in ("fixe", "remplace"):
            forme = g["outil"] if r["type"] == "fixe" else g["apres"]
            sh = forme.val() if isinstance(forme, cq.Workplane) and len(forme.vals()) == 1 else cq.Compound.makeCompound(forme.vals())
            f = os.path.join(d, f"g{i}.brep"); sh.exportBrep(f); r["brep"] = f
        recettes.setdefault(g["piece"], []).append(r)
    return (recettes, p, os.path.splitext(os.path.basename(chemin_modele))[0], attendus)


def exporter_freecad(chemin_modele, sortie=None, sets=None):
    """Fichier FreeCAD .FCStd avec l'histoire : feuille Paramètres + arbre des gestes de l'Atelier."""
    import lc3d_freecad as LF, cadquery as cq
    sortie = sortie or os.path.join(os.path.dirname(os.path.abspath(chemin_modele)), "sortie")
    os.makedirs(sortie, exist_ok=True)
    JOURNAL.clear()
    mod = _charger_modele(chemin_modele); p = _parse_set(sets, getattr(mod, "PARAMS", {}))
    attendus = _attendus_cao(mod, p)
    JOURNAL.clear()
    pieces = mod.build(LF.params_parametriques(p))
    recettes, d, etats = {}, tempfile.mkdtemp(), {}
    for i, g in enumerate(JOURNAL):
        r = dict(g.get("recette") or dict(type="fixe"), titre=g["titre"], op=g["op"] if g["op"] != "modif" else "ajout")
        if r["type"] in ("fixe", "remplace"):
            forme = g["outil"] if r["type"] == "fixe" else g["apres"]
            sh = forme.val() if isinstance(forme, cq.Workplane) and len(forme.vals()) == 1 else cq.Compound.makeCompound(forme.vals())
            f = os.path.join(d, f"g{i}.brep"); sh.exportBrep(f); r["brep"] = f
        recettes.setdefault(g["piece"], []).append(r)
        etats[(g["piece"], len(recettes[g["piece"]]) - 1)] = g["apres"]
        try:      # état exact après le geste : FreeCAD le reprend si son moteur rate une opération (forme figée, signalée)
            fa = g["apres"]; sh = fa.val() if isinstance(fa, cq.Workplane) and len(fa.vals()) == 1 else cq.Compound.makeCompound(fa.vals())
            fb = os.path.join(d, f"etat{i}.brep"); sh.exportBrep(fb); r["brep_apres"] = fb
        except Exception:
            pass
    nom = os.path.splitext(os.path.basename(chemin_modele))[0]
    chemin = os.path.join(sortie, f"{nom}.FCStd")
    rep = LF.exporter(recettes, p, nom, chemin, attendus)
    rep["attendus"] = attendus
    rep["_lot_fusion"] = (recettes, p, nom, attendus)
    # Fusion (historique) + STEP par pièce (SolidWorks, Onshape, Inventor, Creo… ; SolidWorks : FeatureWorks le rend modifiable)
    try:
        import lc3d_fusion as LFu
        rep["fusion"] = LFu.exporter(recettes, p, nom, sortie, attendus)
    except Exception as e:
        rep["fusion"] = dict(ok=False, erreur=f"{type(e).__name__}: {e}")
    rep["step"] = []; rep["formats"] = {}
    stl_fixes = {}
    for pn, gl in recettes.items():
        for i, g in enumerate(gl):
            if g["type"] in ("fixe", "remplace"):
                sh = cq.Shape.importBrep(g["brep"]); f = os.path.join(sortie, f"{nom}_{pn}_{i:02d}.stl"); cq.exporters.export(sh, f); stl_fixes[(pn, i)] = f
    try:
        import lc3d_openscad as LO
        def figer(pn, i):
            f = os.path.join(sortie, f"{nom}_{pn}_{i:02d}_fige.stl"); cq.exporters.export(etats[(pn, i)], f, tolerance=0.005, angularTolerance=0.05); return f
        boites = {n: a["boite"] for n, a in attendus["base"].items()}
        fs, info_scad = LO.exporter(recettes, p, nom, sortie, stl_fixes, figer, boites); rep["formats"]["OpenSCAD (variables)"] = fs
        import shutil, subprocess as _sp
        if shutil.which("openscad"):      # vérification : OpenSCAD doit redonner la même pièce, et suivre chaque cote
            plusieurs = len(attendus["base"]) > 1
            def rendre(defs, attendu):
                """Une pièce à la fois (-D piece=...) : chaque pièce comparée à SES mesures. Retourne le pire écart."""
                pire = None
                for pn, a in attendu.items():
                    tk = os.path.join(tempfile.mkdtemp(), "v.stl")
                    extra = ["-D", f'piece="{re.sub(r"[^A-Za-z0-9_]", "_", pn)}"'] if plusieurs else []
                    _sp.run(["openscad", "-o", tk, *extra, *defs, fs], capture_output=True, timeout=900)
                    if not os.path.exists(tk): return dict(ok=False, note=f"OpenSCAD n'a rien produit pour {pn}")
                    r_ = _comparer_mesures(trimesh.load(tk), {pn: a})
                    if pire is None or not r_["ok"] or r_["ecart_volume_pct"] > pire["ecart_volume_pct"]: pire = dict(r_, piece=pn)
                    if not r_["ok"]: break
                return pire
            if True:
                rep["openscad_verif"] = rendre([], attendus["base"])
                rep["openscad_verif"]["figes"] = info_scad["figes"]
                txt = open(fs).read(); corps_txt = txt[txt.index("// ---- pièce"):txt.index("// profil a × b")]
                corps_txt = re.sub(r"//[^\n]*", "", corps_txt)      # sans commentaires (« l'intérieur » n'est pas la cote l)
                essais = {}
                for k, e in attendus["essais"].items():     # chaque cote ×1,1 : OpenSCAD doit suivre
                    if e.get("touche_fixe") or not e["mesures"]: essais[k] = dict(ok=None, note="touche une forme fixe"); continue
                    if not re.search(rf"\b{re.escape(k)}\b", corps_txt):
                        essais[k] = dict(ok=None, note="pièce figée dans OpenSCAD avant cette cote"); continue
                    # une pièce figée (STL exact) après un geste qui utilise k ne peut pas suivre k, même si k réapparaît plus loin
                    touchees = {pn for pn, i_ in info_scad.get("figes_idx", []) if pn in e["mesures"]
                                and re.search(rf"Parametres\.p_{re.escape(k)}\b", json.dumps(recettes[pn][:i_ + 1], default=str))}
                    mes = {pn: a for pn, a in e["mesures"].items() if pn not in touchees}
                    if not mes:
                        essais[k] = dict(ok=None, note="pièce figée dans OpenSCAD avant cette cote"); continue
                    essais[k] = rendre(["-D", f"{k}={e['valeur']}"], mes)
                    if touchees: essais[k]["note_figees"] = f"non comparé (figé dans OpenSCAD avant cette cote) : {sorted(touchees)}"
                rep["openscad_verif"]["essais_cotes"] = essais
    except Exception as e:
        rep["formats"]["OpenSCAD"] = f"échec : {e}"
    for n, pc in (pieces.items() if isinstance(pieces, dict) else []):
        forme = pc.forme if isinstance(pc, Piece) else pc
        if isinstance(forme, trimesh.Trimesh): continue
        f = os.path.join(sortie, f"{nom}_{n}.step"); cq.exporters.export(forme, f); rep["step"].append(f)
        sh = forme.val() if isinstance(forme, cq.Workplane) and len(forme.vals()) == 1 else (cq.Compound.makeCompound(forme.vals()) if isinstance(forme, cq.Workplane) else forme)
        try:
            from OCP.IGESControl import IGESControl_Writer
            w = IGESControl_Writer("MM", 1); w.AddShape(sh.wrapped); w.ComputeModel()
            fi = os.path.join(sortie, f"{nom}_{n}.igs"); w.Write(fi); rep["formats"].setdefault("IGES", []).append(fi)
        except Exception as e:
            rep["formats"]["IGES"] = f"échec : {e}"
        m = vers_mesh(forme)
        for ext in ("stl", "obj", "glb"):
            fo = os.path.join(sortie, f"{nom}_{n}.{ext}"); m.export(fo); rep["formats"].setdefault(ext.upper(), []).append(fo)
    rep["formats"]["STEP (SolidWorks, Onshape, Inventor, Creo…)"] = rep["step"]
    rep["formats"]["FreeCAD (historique)"] = chemin if rep.get("ok") else rep.get("erreur")
    rep["formats"]["Fusion (historique, script)"] = (rep.get("fusion") or {}).get("dossier")
    if rep.get("ok"):
        # le volume FreeCAD doit égaler le volume LC3D (même pièce)
        for n, pc in (pieces.items() if isinstance(pieces, dict) else []):
            if n in rep["pieces"]:
                v = vers_mesh(pc.forme if isinstance(pc, Piece) else pc).volume
                rep["pieces"][n]["volume_lc3d"] = round(v, 1); rep["pieces"][n]["ecart_pct"] = round(100 * abs(rep["pieces"][n]["volume"] - v) / max(v, 1e-9), 2)
        rep["fichier"] = chemin
    return rep


ECHELLE_MIN_MM, ECHELLE_MAX_MM = 1.0, 2000.0


def controle_echelle(boite_mm, nom="pièce", source=""):
    """Boîte (dx, dy, dz) en mm. Plus grande cote < 1 mm ou > 2 000 mm : unités fausses -> ValueError AVANT de mailler
    (un STEP en mètres maillé à 0,01 mm faisait exploser la mémoire)."""
    g = max(float(x) for x in boite_mm)
    if g < ECHELLE_MIN_MM:
        raise ValueError(f"{nom}{' (' + source + ')' if source else ''} : {g:.4g} mm au plus grand — taille aberrante (< 1 mm). Le fichier est "
                         f"sans doute en MÈTRES (×1000) ou en pouces (×25,4) : le réexporter en millimètres (SolidWorks/Fusion : Options d'export > "
                         f"Unités = mm), ou mettre l'échelle dans le modèle (forme.scale(1000)).")
    if g > ECHELLE_MAX_MM:
        raise ValueError(f"{nom}{' (' + source + ')' if source else ''} : {g:.4g} mm au plus grand — taille aberrante (> 2 000 mm). Le fichier "
                         f"est sans doute en MICROMÈTRES ou mal mis à l'échelle (÷1000) : le réexporter en millimètres.")
    return g


def boite_forme(forme):
    """(dx, dy, dz) en mm SANS mailler (boîte CAO d'OpenCascade, ou boîte du maillage)."""
    if isinstance(forme, trimesh.Trimesh): return tuple(float(x) for x in forme.extents)
    if isinstance(forme, trimesh.Scene): return tuple(float(x) for x in forme.extents)
    import cadquery as cq
    if isinstance(forme, cq.Workplane):
        forme = forme.val() if len(forme.vals()) == 1 else cq.Compound.makeCompound(forme.vals())
    if hasattr(forme, "BoundingBox"):
        bb = forme.BoundingBox(); return (bb.xlen, bb.ylen, bb.zlen)
    if hasattr(forme, "bounding_box"):      # build123d
        bb = forme.bounding_box(); return (bb.size.X, bb.size.Y, bb.size.Z)
    return None


def _comparer_echelle(ancienne, nouvelle, nom):
    """Retour CAO : la nouvelle pièce a-t-elle à peu près la taille de l'ancienne ? (×1000, ×25,4 = unités)"""
    try:
        a, b = max(boite_forme(ancienne)), max(boite_forme(nouvelle))
    except Exception:
        return
    r = b / a if a else 1.0
    if r < 0.1 or r > 10:
        f = "1000× plus petite (mètres ?)" if 0.0005 < r < 0.002 else ("25,4× plus petite (pouces ?)" if 0.03 < r < 0.05 else
             ("1000× plus grande (micromètres ?)" if 500 < r < 2000 else ("25,4× plus grande" if 20 < r < 30 else f"{r:.3g}× la taille d'avant")))
        raise ValueError(f"{nom} : la version reçue fait {b:.4g} mm au plus grand contre {a:.4g} mm avant — {f}. Vérifier les unités de l'export "
                         f"(millimètres) avant de revérifier.")


def _lire_step_controle(chemin, nom="pièce"):
    """Lit un STEP et contrôle son échelle sur la boîte EXACTE de la CAO (aucun maillage)."""
    import cadquery as cq
    f = cq.importers.importStep(chemin)
    bb = (cq.Compound.makeCompound(f.vals()) if hasattr(f, "vals") else f).BoundingBox()
    controle_echelle((bb.xlen, bb.ylen, bb.zlen), nom, os.path.basename(chemin))
    return f


def retour_cao(chemin_modele, remplacements, sortie=None, livrer_zip=None, extras=()):
    """La pièce revient de SolidWorks / Fusion / FreeCAD / Onshape (STEP) : on remplace la pièce dans le projet
    et on relance TOUTES les vérifs (montage, clips, mouvements, résistance, tranchage) + le zip 3MF.
    remplacements : {nom_piece: "chemin.step"}. Les positions d'assemblage du projet sont gardées : exporter la pièce
    dans le même repère que le STEP reçu de LC3D (ne pas la déplacer dans l'autre logiciel)."""
    import cadquery as cq
    base = _charger_modele(chemin_modele)
    tmp = tempfile.mkdtemp(); f = os.path.join(tmp, "retour_" + os.path.basename(chemin_modele))
    code = (f"import importlib.util, sys, cadquery as cq\nfrom lc3d import Piece\n"
            f"spec = importlib.util.spec_from_file_location('origine', {chemin_modele!r}); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)\n"
            f"PARAMS = M.PARAMS\nR = {json.dumps({k: os.path.abspath(v) for k, v in remplacements.items()})}\n"
            "def build(p):\n    pieces = M.build(p)\n    for n, f in R.items():\n"
            "        anc = pieces[n]; nouv = _lire_step_controle(f, n)\n"
            "        _comparer_echelle(anc.forme if isinstance(anc, Piece) else anc, nouv, n)\n"
            "        # TOUT ce que la pièce d'origine déclarait est gardé (orientation, axe_flexion, mur_min, couleur, usage…), seule la forme change\n"
            "        pieces[n] = dataclasses.replace(anc, forme=nouv, mesh=None, importee=True) if isinstance(anc, Piece) else Piece(n, nouv, importee=True)\n"
            "    return pieces\n")
    code = code.replace("import importlib.util, sys, cadquery as cq\nfrom lc3d import Piece\n",
                        "import importlib.util, sys, dataclasses, cadquery as cq\nfrom lc3d import Piece, _lire_step_controle, _comparer_echelle\n")
    if hasattr(base, "assembly"):      # pièce seule (sans assembly) : ne PAS définir assembly (sinon « 'NoneType' has no attribute 'poses' »)
        code += "def assembly(p, pieces):\n    return M.assembly(p, pieces)\n"
    for k in ("COULEURS", "ENVIRONNEMENT", "USAGE"):
        if hasattr(base, k): code += f"{k} = M.{k}\n"
    open(f, "w").write(code)
    _pl = os.path.join(os.path.dirname(os.path.abspath(chemin_modele)), "plan.json")      # le plan suit la pièce
    if os.path.exists(_pl): import shutil; shutil.copy(_pl, os.path.join(tmp, "plan.json"))
    PLAN_EXEMPTE["actif"] = os.path.basename(os.path.dirname(os.path.abspath(chemin_modele))) == "exemples"
    try: return executer(f, None, sortie or os.path.join(os.path.dirname(os.path.abspath(chemin_modele)), "sortie_retour"), livrer_zip, True, "3mf", extras)
    finally: PLAN_EXEMPTE["actif"] = False

# --- Comparaison de deux versions : ce qui a été ajouté (vert) / enlevé (rouge)
def comparer_versions(avant, apres, chemin_png=None):
    A_ = avant if isinstance(avant, trimesh.Trimesh) else trimesh.load(avant, force="mesh")
    B_ = apres if isinstance(apres, trimesh.Trimesh) else trimesh.load(apres, force="mesh")
    ajoute = _de_manifold(_manifold(B_) - _manifold(A_)); enleve = _de_manifold(_manifold(A_) - _manifold(B_))
    d = dict(volume_avant=round(float(A_.volume), 1), volume_apres=round(float(B_.volume), 1), ajoute_mm3=round(float(ajoute.volume), 1) if len(ajoute.faces) else 0.0,
             enleve_mm3=round(float(enleve.volume), 1) if len(enleve.faces) else 0.0, dims_avant=_pt(A_.extents), dims_apres=_pt(B_.extents))
    if chemin_png:
        from PIL import Image, ImageDraw
        T = 520; fond = Image.new("RGB", (T * 2, T + 40), "white"); dr = ImageDraw.Draw(fond)
        for k, vue in enumerate(("Iso avant", "Iso arrière")):
            mc = [(B_, (0.82, 0.84, 0.87))]
            if len(ajoute.faces): a2 = ajoute.copy(); mc.append((a2, (0.2, 0.72, 0.35)))
            if len(enleve.faces): mc.append((enleve, (0.9, 0.2, 0.2)))
            im, _, _ = rendre_vue(mc, vue, T); fond.paste(im, (k * T, 40))
        dr.text((10, 10), f"Vert : ajouté {d['ajoute_mm3']} mm³ · Rouge : enlevé {d['enleve_mm3']} mm³", fill=(20, 20, 30), font=_fnt(18))
        fond.save(chemin_png); d["image"] = chemin_png
    return d


# --- Grandeur réelle : la pièce à côté d'objets connus
def grandeur_reelle(mesh, chemin_png, references=("canette_355", "iPhone_13", "carte_credit")):
    from PIL import Image, ImageDraw
    m = poser_sur_plateau(mesh.copy()); m.apply_translation([-m.bounds[0, 0], -m.bounds[0, 1], 0])
    mc = [(m, PALETTE[0])]; x = m.extents[0] + 15
    lab = []
    for r in references:
        s, f = piece_achetee(r); mr = vers_mesh(s); mr = poser_sur_plateau(mr)
        if r in ("iPhone_13", "carte_credit"):   # debout, comme on les voit
            mr.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (1, 0, 0))); mr = poser_sur_plateau(mr)
        mr.apply_translation([x - mr.bounds[0, 0], -mr.bounds[0, 1], 0]); mc.append((mr, (0.78, 0.8, 0.83))); lab.append((r, x + mr.extents[0] / 2)); x += mr.extents[0] + 15
    im, (lo, hi), ech = rendre_vue(mc, "Avant", 900)
    fond = Image.new("RGB", (900, 960), "white"); fond.paste(im, (0, 0)); dr = ImageDraw.Draw(fond)
    e = m.extents
    r_, u_, d_ = _camera(*VUES["Avant"]); cx = (lo[0] + hi[0]) / 2
    noms_lisibles = {"canette_355": "canette 355 ml", "iPhone_13": "iPhone 13", "carte_credit": "carte de crédit"}
    zbas = 450 + (0 - (lo[1] + hi[1]) / 2) * ech * -1
    for (r, xc), (mm, _) in zip([("piece", m.extents[0] / 2)] + lab, mc):
        px = (np.array([xc, 0, 0]) @ r_ - cx) * ech + 450
        txt = "ta pièce" if r == "piece" else noms_lisibles.get(r, r)
        dr.text((px, min(890, zbas + 12)), txt, fill=(30, 30, 40), font=_fnt(17), anchor="ma")
    dr.text((14, 910), f"Ta pièce : {e[0]:.0f} × {e[1]:.0f} × {e[2]:.0f} mm · à côté : canette 355 ml, iPhone 13, carte de crédit (même échelle)", fill=(20, 20, 30), font=_fnt(18))
    fond.save(chemin_png); return chemin_png


# --- Plan coté (PDF) : 3 vues + iso, cotes hors-tout, Ø des trous, cartouche
def plan_cote(forme, chemin_pdf, titre="Pièce", auteur="LevixiaSaaS", materiau="PETG"):
    import cadquery as cq
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    m = vers_mesh(forme); m = poser_sur_plateau(m)
    lo, hi = m.bounds; e = hi - lo
    cyl = [c for c in _cylindres(forme, np.eye(4)) if c["r"] < max(e) / 3] if not isinstance(forme, trimesh.Trimesh) else []
    trous = sorted({round(2 * c["r"], 2) for c in cyl})
    dz = -(vers_mesh(forme).bounds[0, 2]) if not isinstance(forme, trimesh.Trimesh) else 0.0
    fig = plt.figure(figsize=(11.69, 8.27))   # A4 paysage
    vues = [("Dessus", (0, 1), (0, 0.5, 0.45, 0.45)), ("Avant", (0, 2), (0, 0.04, 0.45, 0.42)), ("Droite", (1, 2), (0.47, 0.04, 0.3, 0.42))]
    for nom, (i, j), pos in vues:
        ax = fig.add_axes(pos); ax.set_aspect("equal"); ax.axis("off"); ax.set_title(nom, fontsize=9, loc="left")
        k = 3 - i - j
        # contour de la silhouette : arêtes vives projetées
        aretes = m.face_adjacency_edges[m.face_adjacency_angles > math.radians(25)]
        V = m.vertices
        for a, b in aretes:
            ax.plot([V[a, i], V[b, i]], [V[a, j], V[b, j]], color="#1d2329", lw=0.5)
        bord = m.outline() if False else None
        # cotes hors-tout
        ax.annotate("", xy=(lo[i], lo[j] - e[j] * 0.08), xytext=(hi[i], lo[j] - e[j] * 0.08), arrowprops=dict(arrowstyle="<->", lw=0.7))
        ax.text((lo[i] + hi[i]) / 2, lo[j] - e[j] * 0.14, f"{e[i]:.1f}", ha="center", va="top", fontsize=8)
        ax.annotate("", xy=(hi[i] + e[i] * 0.06, lo[j]), xytext=(hi[i] + e[i] * 0.06, hi[j]), arrowprops=dict(arrowstyle="<->", lw=0.7))
        ax.text(hi[i] + e[i] * 0.09, (lo[j] + hi[j]) / 2, f"{e[j]:.1f}", ha="left", va="center", fontsize=8, rotation=90)
        if nom == "Dessus":   # Ø de chaque trou vertical, écrit à côté du trou
            vus = set()
            for c in cyl:
                if abs(abs(c["d"][2]) - 1) > 1e-3: continue
                k2 = (round(c["p"][0], 1), round(c["p"][1], 1), round(2 * c["r"], 2))
                if k2 in vus: continue
                vus.add(k2); ax.text(c["p"][0] + c["r"] * 0.75, c["p"][1] + c["r"] * 0.75, f"Ø{2 * c['r']:g}", fontsize=7, color="#c0392b")
        ax.set_xlim(lo[i] - e[i] * 0.1, hi[i] + e[i] * 0.2); ax.set_ylim(lo[j] - e[j] * 0.25, hi[j] + e[j] * 0.05)
    axi = fig.add_axes((0.62, 0.5, 0.36, 0.45)); axi.axis("off")
    im, _, _ = rendre_vue([(m, PALETTE[0])], "Iso avant", 500); axi.imshow(np.asarray(im)); axi.set_title("Iso", fontsize=9, loc="left")
    axc = fig.add_axes((0.79, 0.04, 0.2, 0.42)); axc.axis("off")
    lignes = [titre, f"Matière : {materiau}", f"Hors-tout : {e[0]:.1f} × {e[1]:.1f} × {e[2]:.1f} mm", "Unités : mm", "Trous Ø : " + (", ".join(f"{t:g}" for t in trous[:8]) or "—"),
              f"Auteur : {auteur}", f"Date : {time.strftime('%Y-%m-%d')}", "Généré par LC3D"]
    for k, l in enumerate(lignes): axc.text(0.02, 0.95 - k * 0.11, l, fontsize=9 if k else 11, weight="bold" if k == 0 else "normal", transform=axc.transAxes)
    axc.add_patch(plt.Rectangle((0, 0), 1, 1, fill=False, lw=0.8, transform=axc.transAxes))
    with PdfPages(chemin_pdf) as pdf: pdf.savefig(fig)
    plt.close(fig); return chemin_pdf


# --- Notice de montage (PDF) : une page par étape, à partir de la planche de montage
def notice_montage(meshes, A, chemin_pdf, titre="Notice de montage"):
    from PIL import Image, ImageDraw
    if not A.sequence: return None
    noms = list(meshes); cols = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(noms)}
    places = {}
    for n, m in meshes.items():
        mm = m.copy(); mm.apply_transform(A.poses.get(n, np.eye(4))); places[n] = mm
    seq = [s["piece"] for s in A.sequence]; presentes = [n for n in noms if n not in seq]
    pages = []
    W, H = 1240, 1754   # A4 à 150 ppp
    couverture = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(couverture)
    d.text((80, 90), titre, fill=(20, 20, 30), font=_fnt(56)); d.text((80, 170), f"{len(A.sequence)} étapes · pièces : {', '.join(noms)}", fill=(80, 80, 90), font=_fnt(26))
    im, _, _ = rendre_vue([(m, cols[n]) for n, m in places.items()], "Iso avant", 1000); couverture.paste(im, (120, 300)); pages.append(couverture)
    for i, s in enumerate(A.sequence):
        n = s["piece"]; Mf = A.poses.get(n, np.eye(4))
        page = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(page)
        quoi = "arrive en ligne droite" if s["type"] == "translation" else f"arrive en pivotant de {s['angle']}°"
        d.text((80, 80), f"Étape {i + 1} sur {len(A.sequence)}", fill=(226, 112, 42), font=_fnt(34)); d.text((80, 135), f"{n} — {quoi}", fill=(20, 20, 30), font=_fnt(40))
        for k, t in enumerate((1.0, 0.0)):
            if s["type"] == "translation": Mk = trimesh.transformations.translation_matrix(np.asarray(s["depuis"]) * t) @ Mf
            else: Mk = trimesh.transformations.rotation_matrix(math.radians(s["angle"] * t), s["axe"], s["pivot"]) @ Mf
            mk = meshes[n].copy(); mk.apply_transform(Mk)
            mc = [(places[p], tuple(0.55 + 0.45 * c for c in cols[p])) for p in presentes] + [(mk, cols[n])]
            im, _, _ = rendre_vue(mc, "Iso avant", 760); page.paste(im, (240, 230 + k * 760))
            d.text((90, 250 + k * 760), "Avant" if k == 0 else "En place", fill=(80, 80, 90), font=_fnt(28))
        pages.append(page); presentes.append(n)
    pages[0].save(chemin_pdf, save_all=True, append_images=pages[1:], resolution=150)
    return chemin_pdf


# --- Rendu photo-réaliste (Blender / Cycles) : la pièce comme une photo de produit
def _python_blender():
    import shutil, subprocess
    cands = [os.environ.get("LC3D_BLENDER_PY"), os.path.expanduser("~/bpyenv/bin/python")]
    for c in cands:
        if c and os.path.exists(c):
            r = subprocess.run([c, "-c", "import bpy"], capture_output=True)
            if r.returncode == 0: return [c]
    b = shutil.which("blender")
    return [b, "-b", "--python-exit-code", "1", "-P"] if b else None


COULEURS_FILAMENT = {"orange": (0.92, 0.42, 0.10), "noir": (0.05, 0.05, 0.055), "blanc": (0.9, 0.9, 0.88), "gris": (0.45, 0.47, 0.5),
                     "rouge": (0.75, 0.06, 0.05), "bleu": (0.06, 0.22, 0.65), "vert": (0.1, 0.5, 0.2), "or": (0.83, 0.62, 0.2), "transparent": (0.85, 0.88, 0.9)}


def rendu_photo(places, chemin_png, couleurs=None, vue="iso", taille=(1600, 1200), echantillons=96, achetees=()):
    """places : {nom: maillage EN POSITION (assemblé)}. couleurs : {nom: (r,g,b) ou nom de filament}. ~1-3 min sur 2 cœurs."""
    import subprocess
    py = _python_blender()
    if not py: return dict(ok=False, note="Blender (bpy) non installé ici")
    tmp = tempfile.mkdtemp(); pieces = []
    for i, (n, m) in enumerate(places.items()):
        f = os.path.join(tmp, f"{i}.stl"); m.export(f)
        c = (couleurs or {}).get(n, PALETTE[i % len(PALETTE)] if n not in achetees else (0.7, 0.72, 0.75))
        if isinstance(c, str): c = COULEURS_FILAMENT.get(c, (0.8, 0.8, 0.8))
        pieces.append(dict(stl=f, couleur=list(c), matiere="metal" if n in achetees else "plastique"))
    sj = os.path.join(tmp, "scene.json"); json.dump(dict(pieces=pieces, vue=vue, taille=list(taille), echantillons=echantillons), open(sj, "w"))
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lc3d_blender.py")
    r = subprocess.run(py + [script, "rendu", sj, chemin_png] if py[0].endswith("python") or "python" in os.path.basename(py[0]) else py + [script, "--", "rendu", sj, chemin_png],
                       capture_output=True, text=True, timeout=1800)
    return dict(ok=os.path.exists(chemin_png), image=chemin_png, erreur=None if os.path.exists(chemin_png) else (r.stderr or r.stdout)[-600:])


def nettoyer_organique(stl_entree, stl_sortie, lisser=1, faces=200000):
    """Figurine (ex. sortie de Hunyuan3D/Meshy) : étanche, lissée, allégée, prête à imprimer."""
    import subprocess
    py = _python_blender()
    if not py: return dict(ok=False, note="Blender (bpy) non installé ici")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lc3d_blender.py")
    r = subprocess.run(py + [script, "nettoyer", stl_entree, stl_sortie, "--lisser", str(lisser), "--faces", str(faces)], capture_output=True, text=True, timeout=1800)
    return dict(ok=os.path.exists(stl_sortie), stl=stl_sortie, journal=r.stdout[-300:])


# ----------------------------------------------------------------------------
# BLOC 6 — Entrées et outils de forme : modifier un STL téléchargé, couper une grosse pièce avec connecteurs,
# texte / logo / QR en relief, fuites de lumière, passage d'un fil avec sa prise, figurine (photo → 3D → socle)
# ----------------------------------------------------------------------------
def _en_mesh(x):
    if isinstance(x, trimesh.Trimesh): return x
    if isinstance(x, str): return trimesh.load(x, force="mesh")
    return vers_mesh(x)


def modifier_stl(base, ajouter=(), enlever=()):
    """Modifier un modèle téléchargé (MakerWorld, Printables) SANS le refaire : union de formes à ajouter, soustraction de formes à enlever.
    base : chemin .stl/.3mf ou maillage; ajouter / enlever : formes CadQuery ou maillages, déjà positionnées dans le repère du modèle."""
    M = _manifold(_en_mesh(base))
    for a in ajouter: M = M + _manifold(_en_mesh(a))
    for e in enlever: M = M - _manifold(_en_mesh(e))
    return _de_manifold(M)


def couper(mesh, axe="Z", position=None, connecteur="goupilles", jeu=0.15, d_goupille=4.0, prof=6.0, nb=2):
    """Coupe une pièce en deux (trop grande pour le plateau, ou pour imprimer sans support) avec des connecteurs qui alignent et tiennent.
    connecteur : 'goupilles' (trous dans les 2 moitiés + goupilles imprimées à part, Ø d+2·jeu dans les trous) | 'queue_aronde' (mâle/femelle)
    Retourne {nom: maillage} : moitie_1, moitie_2 (+ goupille si goupilles)."""
    import cadquery as cq
    m = _en_mesh(mesh); k = "XYZ".index(axe.upper())
    lo, hi = m.bounds; pos = (lo[k] + hi[k]) / 2 if position is None else position
    taille = float(np.max(hi - lo)) * 3
    boite = trimesh.creation.box(extents=[taille] * 3); dec = np.zeros(3); dec[k] = -taille / 2 + pos
    boite.apply_translation(m.bounds.mean(0) * (np.arange(3) != k) + dec)
    M = _manifold(m); B = _manifold(boite)
    a = _de_manifold(M ^ B); b = _de_manifold(M - B)
    out = {}
    section = _polys_section(m if k == 2 else m.copy(), pos) if k == 2 else None
    if k != 2:   # section dans un autre axe : on tourne pour réutiliser la tranche en Z
        R = trimesh.geometry.align_vectors(np.eye(3)[k], [0, 0, 1]); mr = m.copy(); mr.apply_transform(R)
        z = (mr.bounds[0, 2] + mr.bounds[1, 2]) / 2 if position is None else (R[:3, :3] @ (np.eye(3)[k] * pos))[2]
        section = _polys_section(mr, z); Rinv = np.linalg.inv(R)
    if section is None or section.is_empty:
        return dict(moitie_1=a, moitie_2=b, note="coupe hors de la pièce")
    gros = max(getattr(section, "geoms", [section]), key=lambda g: g.area)
    if connecteur == "goupilles":
        # points d'ancrage : loin des bords (≥ d/2 + 2 mm), répartis sur le grand axe de la section.
        # Section mince : goupilles plus fines (Ø3, 1,5 mm de paroi autour) avant d'abandonner — et alors on le DIT (avertissement)
        interieur = None
        for d_, marge in ((d_goupille, 2.0), (3.0, 1.5)):
            if d_ > d_goupille: continue
            interieur = gros.buffer(-(d_ / 2 + marge))
            if not interieur.is_empty: d_goupille = d_; break
        if interieur is None or interieur.is_empty:
            ep = 2 * max(0.0, min(gros.bounds[2] - gros.bounds[0], gros.bounds[3] - gros.bounds[1]) / 2)
            return dict(moitie_1=a, moitie_2=b, copies_goupille=0, avertissement=f"section trop mince ({ep:.1f} mm) : AUCUNE goupille possible — "
                        f"les morceaux ne sont ni alignés ni tenus. Coller (cyanoacrylate, ou soudure au stylo 3D) avec une éclisse "
                        f"collée par-dessus le joint, ou épaissir la pièce à cet endroit (≥ 8 mm pour des goupilles Ø3).",
                        note="aucune goupille (section trop mince)")
        rr = interieur.minimum_rotated_rectangle; xs, ys = rr.exterior.coords.xy
        p0 = np.array([xs[0], ys[0]]); p1 = np.array([xs[1], ys[1]]); p2 = np.array([xs[2], ys[2]])
        longue = (p1 - p0) if np.linalg.norm(p1 - p0) > np.linalg.norm(p2 - p1) else (p2 - p1)
        c = np.array(interieur.centroid.coords[0])
        pts = [c + longue * t for t in (np.linspace(-0.35, 0.35, nb) if nb > 1 else [0])]
        from shapely.geometry import Point
        pts = [p if interieur.contains(Point(*p)) else np.array(interieur.representative_point().coords[0]) for p in pts]
        uniques = []
        for p in pts:      # deux goupilles au même endroit (section étroite) : une seule
            if all(np.linalg.norm(p - q) > d_goupille + 2 for q in uniques): uniques.append(p)
        pts = uniques
        trous = []
        for p in pts:
            cyl = trimesh.creation.cylinder(radius=d_goupille / 2 + jeu, height=2 * prof + 0.4, sections=48)
            pz = pos if k == 2 else z
            cyl.apply_translation([p[0], p[1], pz])
            if k != 2: cyl.apply_transform(Rinv)
            trous.append(_manifold(cyl))
        for T in trous:
            a = _de_manifold(_manifold(a) - T); b = _de_manifold(_manifold(b) - T)
        g = trimesh.creation.cylinder(radius=d_goupille / 2, height=2 * prof - 0.5, sections=48)
        out = dict(moitie_1=a, moitie_2=b, goupille=g, copies_goupille=len(pts),
                   note=f"{len(pts)} goupille(s) Ø{d_goupille} × {2 * prof - 0.5:.1f} mm, trous Ø{d_goupille + 2 * jeu:.2f} × {prof:.1f} mm de chaque côté")
    elif connecteur == "queue_aronde":
        w = min(12.0, max(6.0, np.sqrt(gros.area) / 3)); h = min(8.0, w * 0.7)
        c = np.array(gros.centroid.coords[0])
        prof2d = cq.Workplane("XY").polyline([(-w / 2, 0), (w / 2, 0), (w / 2 + h * 0.35, h), (-w / 2 - h * 0.35, h)]).close()
        male = vers_mesh(prof2d.extrude(prof).translate((c[0], c[1] - h / 2, (pos if k == 2 else z))))
        femelle = vers_mesh(cq.Workplane("XY").polyline([(-w / 2 - jeu, -jeu), (w / 2 + jeu, -jeu), (w / 2 + h * 0.35 + jeu, h + jeu), (-w / 2 - h * 0.35 - jeu, h + jeu)])
                            .close().extrude(prof + 0.3).translate((c[0], c[1] - h / 2, (pos if k == 2 else z))))
        if k != 2: male.apply_transform(Rinv); femelle.apply_transform(Rinv)
        b = _de_manifold(_manifold(b) + _manifold(male)); a = _de_manifold(_manifold(a) - _manifold(femelle))
        out = dict(moitie_1=a, moitie_2=b, note=f"queue d'aronde {w:.1f} × {h:.1f} × {prof} mm, jeu {jeu} mm (se glisse de côté)")
    return out


def _aire_section(m, k, pos):
    """Aire de la section pleine de m au plan axe k = pos (0 si la coupe tombe hors de la pièce)."""
    try:
        if k == 2: S = _polys_section(m, pos)
        else:
            R = trimesh.geometry.align_vectors(np.eye(3)[k], [0, 0, 1]); mr = m.copy(); mr.apply_transform(R)
            S = _polys_section(mr, (R[:3, :3] @ (np.eye(3)[k] * pos))[2])
        return 0.0 if S is None or S.is_empty else float(S.area)
    except Exception:
        return 0.0


def decouper_pour_plateau(mesh, plateau=None, connecteur="goupilles", marge=3.0):
    """Coupe automatiquement tout ce qui dépasse le plateau de LA machine choisie (MACHINE["lit"], marge 3 mm par côté) en morceaux
    qui rentrent. La coupe est placée là où la section est la plus PLEINE (jamais en plein dans un trou) parmi les positions permises.
    Retourne la liste des morceaux (+ goupilles). decouper_pour_plateau.notes = avertissements (goupilles impossibles…)."""
    if plateau is None:
        L_ = MACHINE["lit"]; plateau = (L_[0] - 2 * marge, L_[1] - 2 * marge, L_[2])
    morceaux = [_en_mesh(mesh)]; finis = []; notes = []
    while morceaux:
        m = morceaux.pop()
        e = m.extents; lo, hi = m.bounds
        trop = [i for i in range(3) if e[i] > plateau[i]]
        if not trop: finis.append(m); continue
        k = max(trop, key=lambda i: e[i] / plateau[i])
        P = plateau[k]
        # positions où les deux morceaux rentrent (si > 2 longueurs de plateau : un morceau plein + le reste, recoupé ensuite)
        n = int(math.ceil(e[k] / (P - 2.0)))       # nombre de morceaux sur cet axe : premier morceau ≈ e/n, le reste recoupé pareil
        a0, a1 = hi[k] - (n - 1) * (P - 2.0), lo[k] + P - 1.0
        cands = np.linspace(a0, a1, 15) if a1 > a0 else np.array([lo[k] + e[k] / n])
        milieu = lo[k] + e[k] / n
        aires = [_aire_section(m, k, float(c)) for c in cands]
        amax = max(aires) if aires else 0.0
        bons = [c for c, a in zip(cands, aires) if a >= 0.98 * amax] or list(cands)
        pos = float(min(bons, key=lambda c: abs(c - milieu)))
        r = couper(m, "XYZ"[k], pos, connecteur)
        morceaux += [r["moitie_1"], r["moitie_2"]]
        if r.get("avertissement"): notes.append(f"coupe {'XYZ'[k]} = {pos:.1f} mm : {r['avertissement']}")
        if "goupille" in r: finis += [r["goupille"]] * r["copies_goupille"]
    decouper_pour_plateau.notes = notes
    return finis


# --- Relief : texte, logo (image), code QR — à unir (relief) ou soustraire (gravure) sur une face
def relief_texte(texte, taille=8.0, hauteur=0.8, police="Arial", gras=True):
    """Texte en relief (CadQuery), base à z = 0, centré. Lettres ≥ 0,84 mm de trait : viser taille ≥ 6 mm en gras."""
    import cadquery as cq
    return cq.Workplane("XY").text(texte, taille, hauteur, font=police, kind="bold" if gras else "regular", halign="center", valign="center").translate((0, 0, hauteur / 2))


def relief_qr(contenu, cote=30.0, hauteur=0.8, marge_modules=1):
    """Code QR en relief (modules carrés), base à z = 0, centré. Module ≥ 1,2 mm pour une buse 0,4 (sinon illisible)."""
    import segno
    qr = segno.make(contenu, error="m"); mat = np.array(list(qr.matrix), dtype=bool)
    n = mat.shape[0]; mod = cote / (n + 2 * marge_modules)
    boites = []
    for i in range(n):
        for j in range(n):
            if mat[i, j]:
                b = trimesh.creation.box(extents=[mod + 0.02, mod + 0.02, hauteur])
                b.apply_translation([(j + marge_modules + 0.5) * mod - cote / 2, cote / 2 - (i + marge_modules + 0.5) * mod, hauteur / 2]); boites.append(_manifold(b))
    M = boites[0]
    for b in boites[1:]: M = M + b
    q = _de_manifold(M)
    return q, dict(modules=n, module_mm=round(mod, 2), lisible=mod >= 1.2, conseil=None if mod >= 1.2 else f"Agrandir à {1.2 * (n + 2 * marge_modules):.0f} mm de côté")


def relief_image(chemin_png, largeur=40.0, hauteur=0.8, seuil=None, inverser=False, lissage=0.15):
    """Logo / dessin (ex. monogramme LC) → relief vectorisé : seuil, contours avec trous, lissage, mis à l'échelle.
    Marche même avec une image basse résolution (les contours sont lissés)."""
    import cv2
    img = cv2.imread(chemin_png, cv2.IMREAD_UNCHANGED)
    if img is None: raise FileNotFoundError(chemin_png)
    if img.ndim == 3 and img.shape[2] == 4:   # transparence = fond
        g = np.where(img[:, :, 3] > 127, 255 - cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY), 0).astype(np.uint8); g = 255 - g
    else:
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC); g = cv2.GaussianBlur(g, (5, 5), 0)
    _, b = cv2.threshold(g, seuil if seuil is not None else 0, 255, cv2.THRESH_BINARY_INV + (0 if seuil is not None else cv2.THRESH_OTSU))
    if inverser: b = 255 - b
    cont, hier = cv2.findContours(b, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    polys = []
    if hier is not None:
        for i, c in enumerate(cont):
            if hier[0][i][3] != -1 or len(c) < 3: continue
            ext = c[:, 0, :].astype(float)
            trous = [cont[j][:, 0, :].astype(float) for j in range(len(cont)) if hier[0][j][3] == i and len(cont[j]) >= 3]
            P = Polygon(ext, trous).buffer(0)
            if P.area > 20: polys.append(P)
    forme = unary_union(polys)
    x0, y0, x1, y1 = forme.bounds; ech = largeur / (x1 - x0)
    from shapely import affinity
    forme = affinity.scale(affinity.translate(forme, -(x0 + x1) / 2, -(y0 + y1) / 2), ech, -ech, origin=(0, 0)).simplify(lissage * 0.5).buffer(lissage).buffer(-lissage)
    maill = []
    for p in getattr(forme, "geoms", [forme]):
        if p.area < 0.3: continue
        maill.append(trimesh.creation.extrude_polygon(p, hauteur))
    m = trimesh.util.concatenate(maill)
    fin = forme.difference(forme.buffer(-0.42).buffer(0.42)).area
    return m, dict(largeur=largeur, hauteur_mm=round(m.extents[1], 1), traits_fins_mm2=round(fin, 1),
                   conseil=None if fin < 1 else "Des traits font moins de 0,84 mm : agrandir le logo ou épaissir (lissage plus grand)")


# --- Fuites de lumière (lampes) : des rayons partent de l'ampoule; ceux qui sortent sans traverser une pièce = fente visible
def fuites_lumiere(places, source, diffuseurs=(), n=40000, graine=3):
    """places : {nom: maillage en position}. source : (x,y,z) de l'ampoule/LED. diffuseurs : pièces translucides (la lumière doit passer PAR elles).
    Tout rayon qui sort sans toucher aucune pièce = fuite. Rayon qui touche d'abord une pièce opaque puis rien : OK."""
    rng = np.random.default_rng(graine)
    d = rng.normal(size=(n, 3)); d /= np.linalg.norm(d, axis=1)[:, None]
    o = np.tile(np.asarray(source, float), (n, 1))
    touche = np.zeros(n, bool); par_diffuseur = np.zeros(n, bool)
    for nom, m in places.items():
        try:
            idx = m.ray.intersects_any(o, d)
        except Exception:
            idx = trimesh.ray.ray_triangle.RayMeshIntersector(m).intersects_any(o, d)
        touche |= idx
        if nom in diffuseurs: par_diffuseur |= idx
    fuite = ~touche
    ens = trimesh.util.concatenate(list(places.values())); R = float(np.linalg.norm(ens.extents))
    sorties = (o + d * R)[fuite]
    groupes = []
    if fuite.any():
        # regrouper les directions de fuite (fentes) : grille sur la sphère
        cle = np.round(d[fuite] * 6).astype(int)
        uniq, cnt = np.unique(cle, axis=0, return_counts=True)
        for u, c_ in sorted(zip(uniq, cnt), key=lambda x: -x[1])[:6]:
            sel = (cle == u).all(1); dirm = d[fuite][sel].mean(0); dirm /= np.linalg.norm(dirm)
            # point où le rayon passe au ras de la pièce la plus proche
            p = np.asarray(source) + dirm * (np.linalg.norm(ens.extents) * 0.3)
            groupes.append(dict(direction=_pt(dirm), part_pct=round(100 * c_ / n, 3)))
    pct = 100 * fuite.mean()
    st = OK if pct < 0.01 else (AVERT if pct < 0.2 else ECHEC)
    return res("Fuites de lumière", st, f"{pct:.3f} % des rayons de l'ampoule sortent par une fente ({fuite.sum()} sur {n})" +
               (f"; principales directions : {[g['direction'] for g in groupes[:3]]}" if groupes else ""),
               conseil=None if st == OK else "Faire chevaucher les pièces au joint (languette ou mur intérieur ≥ 1 mm), jamais bout à bout.",
               valeur=round(pct, 4)), dict(fuites=groupes)


# --- Passage d'un fil AVEC sa prise / douille à travers toutes les pièces (essai réel)
def passage_cable(places, chemin, gabarit="prise_NEMA_1_15", pas=1.0, jeu=0.5, **mesures):
    """chemin : liste de points (x,y,z) que la prise suit, dans l'ordre où on la passe (du bout du fil vers l'intérieur).
    gabarit : pièce du catalogue (prise_NEMA_1_15, douille_E26, ...) ou (largeur, épaisseur, longueur). La prise avance
    alignée sur le chemin; à chaque pas on vérifie qu'elle ne touche aucune pièce (avec 'jeu' mm de marge)."""
    import cadquery as cq
    if isinstance(gabarit, str):
        s, f = piece_achetee(gabarit, **mesures); g = vers_mesh(s)
    else:
        lx, ly, lz = gabarit; g = trimesh.creation.box(extents=[lx, ly, lz]); g.apply_translation([0, 0, lz / 2])
    # gonfler du jeu : boîte englobante agrandie (simple et prudent)
    e = g.extents + 2 * jeu; c = g.bounds.mean(0)
    env = trimesh.creation.box(extents=e); env.apply_translation(c)
    env.apply_translation([-c[0], -c[1], -g.bounds[0, 2]])   # le bout de la prise à z = 0, elle pointe vers +Z
    P = [np.asarray(p, float) for p in chemin]
    premier = None; n_tests = 0
    for i in range(len(P) - 1):
        a, b = P[i], P[i + 1]; L = np.linalg.norm(b - a)
        if L < 1e-9: continue
        dvec = (b - a) / L
        Rm = trimesh.geometry.align_vectors([0, 0, 1], dvec)
        for t in np.arange(0, L + 1e-9, pas):
            M = Rm.copy(); M[:3, 3] = a + dvec * t
            ek = env.copy(); ek.apply_transform(M); n_tests += 1
            for nom, m in places.items():
                if not _paires_proches(ek, m): continue
                v = _vol_inter(ek, m)[0]
                if v > 0.02:
                    premier = (nom, _pt(a + dvec * t), round(v, 1)); break
            if premier: break
        if premier: break
    nomg = gabarit if isinstance(gabarit, str) else f"{gabarit}"
    if premier:
        return res(f"Passage de la {nomg}", ECHEC, f"bloque dans « {premier[0]} » au point {premier[1]} ({premier[2]} mm³ avec {jeu} mm de marge)",
                   conseil="Agrandir ce trou pour la PRISE moulée (pas juste le fil), ou ajouter une fente de passage; puis revérifier toute la chaîne.", lieux=[premier[1]])
    return res(f"Passage de la {nomg}", OK, f"passe partout sur {sum(np.linalg.norm(P[i + 1] - P[i]) for i in range(len(P) - 1)):.0f} mm ({n_tests} positions, marge {jeu} mm)")


# --- Figurine (photo → 3D) : nettoyer le maillage IA, le mettre à l'échelle et lui ajouter un socle avec un nom
def socle_figurine(maillage, hauteur_figurine=80.0, nom=None, d_socle=None, h_socle=5.0, police="Arial"):
    """Maillage IA (Hunyuan3D, Meshy, Tripo) → figurine imprimable : échelle, posée sur un socle rond (nom gravé sur le côté avant en relief)."""
    import cadquery as cq
    m = _en_mesh(maillage)
    m.apply_scale(hauteur_figurine / m.extents[2]); m = poser_sur_plateau(m)
    m.apply_translation([-m.bounds.mean(0)[0], -m.bounds.mean(0)[1], h_socle - 0.6])   # s'enfonce 0,6 mm dans le socle (soudé)
    d = d_socle or max(m.extents[0], m.extents[1]) * 1.15 + 6
    socle = cq.Workplane("XY").circle(d / 2).extrude(h_socle).edges(">Z").fillet(min(1.2, h_socle / 3))
    if nom:
        txt = cq.Workplane("XZ").text(nom, min(h_socle * 0.62, 5.0), 0.7, font=police, kind="bold", halign="center", valign="center").translate((0, -d / 2 + 0.3, h_socle / 2))
        socle = socle.union(txt)
    s = vers_mesh(socle)
    try:
        f = _de_manifold(_manifold(s) + _manifold(m))
    except Exception:
        f = trimesh.util.concatenate([s, m])
    return f


# ----------------------------------------------------------------------------
# Ligne de commande
# ----------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="lc3d")
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("run"); a.add_argument("modele"); a.add_argument("--set", nargs="*"); a.add_argument("--out"); a.add_argument("--zip"); a.add_argument("--format", default="3mf", choices=["3mf", "stl", "step"]); a.add_argument("--sans-rendu", action="store_true")
    a.add_argument("--photo", action="store_true", help="rendu photo-réaliste Blender (1-3 min)"); a.add_argument("--plans", action="store_true"); a.add_argument("--notice", action="store_true")
    a.add_argument("--imprimante", help="ex. « p2s », « u1 », « prusa core one », « ender 3 v3 se » (défaut : P2S)")
    a.add_argument("--buse", type=float, help="diamètre de buse en mm : 0.2 (détails fins), 0.4 (défaut), 0.6, 0.8 (solide, rapide)")
    a.add_argument("--studio", action="store_true", help="prépare le paquet pour l'écran LC3D Studio (scene.json, livraison.json)")
    a.add_argument("--sans-tranchage", action="store_true")
    a.add_argument("--plateau-unique", action="store_true", help="UN 3MF avec toutes les pièces, chacune avec son matériau et sa couleur (AMS, têtes multiples)")
    a.add_argument("--rapide", action="store_true", help="vérifs essentielles en 1-2 min (pas grossier, sans rendus/FEM/simulations/tranchage) pour itérer")
    a.add_argument("--livrer-quand-meme", action="store_true", help="livre le zip même avec des ❌ (chacun écrit en tête du rapport)")
    a.add_argument("--mem-max", type=int, help="plafond mémoire par vérification lourde, en Mo (défaut 2048)"); a.add_argument("--delai-max", type=float, help="durée max par vérification lourde, en s (défaut 150)")
    a = sp.add_parser("apercu", help="aperçu rapide pour le Studio (sans vérifs; --verif = run --rapide)"); a.add_argument("modele"); a.add_argument("--set", nargs="*"); a.add_argument("--out"); a.add_argument("--imprimante"); a.add_argument("--buse", type=float)
    a.add_argument("--verif", action="store_true", help="avec les vérifs essentielles (= run --rapide)")
    a = sp.add_parser("studio-paquet", help="prépare l'envoi vers le Studio (lots pour ArtifactData batch)"); a.add_argument("sortie"); a.add_argument("--projet", required=True); a.add_argument("--version", default="v1"); a.add_argument("--message", default=""); a.add_argument("--imprimante"); a.add_argument("--etape")
    a = sp.add_parser("studio-pousser", help="envoie la pièce au Studio hébergé (LC3D_STUDIO) — marche avec n'importe quelle IA"); a.add_argument("sortie"); a.add_argument("--projet", required=True); a.add_argument("--version", default="v1"); a.add_argument("--message", default=""); a.add_argument("--imprimante"); a.add_argument("--etape")
    a = sp.add_parser("studio-ouvrir", help="donne (et ouvre) le lien du Studio en ligne de cette personne — le crée la première fois"); a.add_argument("--sans-navigateur", action="store_true")
    a = sp.add_parser("studio-lire", help="lit un document du Studio hébergé (ex. studio/ici, studio/demande) ou une collection"); a.add_argument("chemin")
    a = sp.add_parser("studio-ecrire", help="écrit un document du Studio hébergé (ex. studio/courant avec les questions)"); a.add_argument("chemin"); a.add_argument("json", help="objet JSON, ou @fichier.json"); a.add_argument("--fusion", action="store_true", help="fusionne avec le document existant (update)")
    a = sp.add_parser("variantes", help="jusqu'à 10 variantes vérifiées et classées"); a.add_argument("modele"); a.add_argument("grille", nargs="+", help="ep=4,6,8 mur=2,3"); a.add_argument("--out"); a.add_argument("--set", nargs="*")
    a = sp.add_parser("gravure", help="SVG à l'échelle pour le laser (xTool) : texte ou STL/STEP"); a.add_argument("source", help="texte entre guillemets, ou fichier .stl/.step"); a.add_argument("--taille", type=float, default=10); a.add_argument("--decoupe", action="store_true"); a.add_argument("--out", default="gravure.svg")
    a = sp.add_parser("miroir", help="compare la pièce à la photo de l'objet (carte de crédit pour l'échelle)"); a.add_argument("modele"); a.add_argument("photo"); a.add_argument("--vue", default="face", choices=["face", "cote", "dessus"]); a.add_argument("--set", nargs="*"); a.add_argument("--out", default="miroir.png")
    a = sp.add_parser("retour", help="la pièce revient de SolidWorks/Fusion (STEP) : tout revérifier"); a.add_argument("modele"); a.add_argument("remplacements", nargs="+", help="piece=fichier.step"); a.add_argument("--out"); a.add_argument("--zip")
    a = sp.add_parser("cao", help="export CAO avec l'histoire : FreeCAD (.FCStd), Fusion (script), STEP (SolidWorks…)"); a.add_argument("modele"); a.add_argument("--out"); a.add_argument("--set", nargs="*")
    a = sp.add_parser("freecad", help="export FreeCAD avec l'histoire modifiable"); a.add_argument("modele"); a.add_argument("--out"); a.add_argument("--set", nargs="*")
    a = sp.add_parser("freecad-installer")
    a = sp.add_parser("orca-installer", help="installe OrcaSlicer (tranchage exact des 3MF livrés)")
    a = sp.add_parser("bambu-installer", help="installe Bambu Studio (profils Bambu + tranchage des 3MF Bambu, gratuit)")
    a = sp.add_parser("imprimante", help="trouver une imprimante dans le catalogue (~1 150 machines)"); a.add_argument("texte", nargs="+")
    a = sp.add_parser("check"); a.add_argument("stl"); a.add_argument("--mur-min", type=float); a.add_argument("--role", default="rigide"); a.add_argument("--orientation", default="telle"); a.add_argument("--out")
    a = sp.add_parser("calc"); a.add_argument("type", choices=["snap", "lame", "ressort", "rampe", "trous", "engrenage", "ajustement", "roulement", "vis", "bossage"]); a.add_argument("kv", nargs="*")
    a = sp.add_parser("outline-scan"); a.add_argument("scan"); a.add_argument("--jeu", type=float, default=0.5); a.add_argument("--out", default="contour.svg")
    a = sp.add_parser("outline-photo"); a.add_argument("photo"); a.add_argument("--ref", default="a4"); a.add_argument("--jeu", type=float, default=0.5); a.add_argument("--out", default="contour.svg")
    a = sp.add_parser("gridfinity"); a.add_argument("type", choices=["bac", "plaque"]); a.add_argument("dims", nargs="+", type=int)
    a.add_argument("--aimants", action="store_true"); a.add_argument("--sans-levre", action="store_true"); a.add_argument("--etiquette", action="store_true")
    a.add_argument("--cases", nargs=2, type=int, default=[1, 1]); a.add_argument("--out", default="gridfinity.stl")
    a = sp.add_parser("balayage"); a.add_argument("modele"); a.add_argument("param"); a.add_argument("--valeurs", required=True, help="debut:fin:pas ou v1,v2,v3 (écrire --valeurs=-0.3,0,0.2)"); a.add_argument("--set", nargs="*")
    a = sp.add_parser("lecon"); a.add_argument("nom"); a.add_argument("--condition", required=True); a.add_argument("--pourquoi", required=True); a.add_argument("--besoin", nargs="+", required=True); a.add_argument("--origine", default="")
    a = sp.add_parser("lecons")
    a = sp.add_parser("composants")
    a = sp.add_parser("composant"); a.add_argument("action", choices=["valider", "fiche", "preuve", "chercher"]); a.add_argument("numero", nargs="?"); a.add_argument("--projet", default=""); a.add_argument("--note", default="")
    a.add_argument("--reussi", choices=["oui", "non"], default="oui"); a.add_argument("--imprimante", default="Bambu Lab P2S"); a.add_argument("--filament", default="PETG"); a.add_argument("--photo"); a.add_argument("--qui", default="l'utilisateur"); a.add_argument("--version", type=int, default=1)
    a = sp.add_parser("figurine"); a.add_argument("stl"); a.add_argument("--hauteur", type=float, default=80); a.add_argument("--nom"); a.add_argument("--nettoyer", action="store_true"); a.add_argument("--out", default="figurine")
    a = sp.add_parser("couper"); a.add_argument("stl"); a.add_argument("--axe", default="auto"); a.add_argument("--position", type=float); a.add_argument("--connecteur", default="goupilles"); a.add_argument("--out", default="morceaux")
    a.add_argument("--imprimante", help="machine dont le plateau limite les morceaux (défaut : P2S)"); a.add_argument("--materiau", default="PETG"); a.add_argument("--buse", type=float)
    a = sp.add_parser("logo"); a.add_argument("image"); a.add_argument("--largeur", type=float, default=40); a.add_argument("--hauteur", type=float, default=0.8); a.add_argument("--out", default="logo.stl")
    a = sp.add_parser("qr"); a.add_argument("contenu"); a.add_argument("--cote", type=float, default=35); a.add_argument("--hauteur", type=float, default=0.8); a.add_argument("--out", default="qr.stl")
    a = sp.add_parser("comparer"); a.add_argument("avant"); a.add_argument("apres"); a.add_argument("--out", default="comparaison.png")
    a = sp.add_parser("nettoyer"); a.add_argument("stl"); a.add_argument("--out"); a.add_argument("--lisser", type=int, default=1); a.add_argument("--faces", type=int, default=200000)
    a = sp.add_parser("visionneuse"); a.add_argument("stl", nargs="+"); a.add_argument("--out", default="visionneuse.html"); a.add_argument("--titre", default="Pièce LC3D")
    a = sp.add_parser("calibration"); a.add_argument("--out", default="calibration")
    a = sp.add_parser("calibration-mesure"); a.add_argument("trou", type=int); a.add_argument("--cube", nargs=2, type=float, default=[20.0, 20.0])
    a = sp.add_parser("3mf"); a.add_argument("stl"); a.add_argument("--materiau", default="PETG"); a.add_argument("--role", default="rigide"); a.add_argument("--copies", type=int, default=1); a.add_argument("--out")
    ar = ap.parse_args(argv)
    if ar.cmd == "balayage":
        if ":" in ar.valeurs:
            d, f_, st = (float(x) for x in ar.valeurs.split(":")); vals = [round(d + k * st, 6) for k in range(int(round((f_ - d) / st)) + 1)]
        else:
            vals = [json.loads(x) for x in ar.valeurs.split(",")]
        print(json.dumps(balayage(ar.modele, ar.param, vals, ar.set), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "lecon":
        print(f"leçon ajoutée ({ajouter_lecon(ar.nom, ar.condition, ar.pourquoi, ar.besoin, ar.origine)} au total) : {FICHIER_LECONS}"); return 0
    if ar.cmd == "calibration":
        P, jeux = peigne_calibration(); os.makedirs(ar.out, exist_ok=True)
        meshes = {n: vers_mesh(p.forme) for n, p in P.items()}
        zp = livrer(meshes, P, ar.out, "LC3D_calibration_P2S")
        print(json.dumps(dict(zip=zp, jeux_des_trous_1_a_7=jeux, quoi_faire="Imprimer, essayer la tige dans chaque trou, mesurer le cube, puis : lc3d.py calibration-mesure N --cube X Y"), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "calibration-mesure":
        print(json.dumps(enregistrer_calibration(ar.trou, cube_x=ar.cube[0], cube_y=ar.cube[1]), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "3mf":
        m = trimesh.load(ar.stl, force="mesh"); out = ar.out or os.path.splitext(ar.stl)[0] + ".3mf"
        r = exporter_3mf_bambu([dict(nom=os.path.splitext(os.path.basename(ar.stl))[0], mesh=m, copies=ar.copies, role=ar.role)], out, ar.materiau)
        print(json.dumps(dict(r, verifs=verifier_3mf(out)), ensure_ascii=False, indent=1, default=str)); return 0
    if ar.cmd == "comparer":
        print(json.dumps(comparer_versions(ar.avant, ar.apres, ar.out), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "nettoyer":
        print(json.dumps(nettoyer_organique(ar.stl, ar.out or ar.stl.replace(".stl", "_propre.stl"), ar.lisser, ar.faces), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "visionneuse":
        M = {os.path.splitext(os.path.basename(f))[0]: trimesh.load(f, force="mesh") for f in ar.stl}
        print(json.dumps(visionneuse(ar.out, M, titre=ar.titre), ensure_ascii=False)); return 0
    if ar.cmd == "figurine":
        src = ar.stl
        if ar.nettoyer:
            n = nettoyer_organique(ar.stl, os.path.splitext(ar.stl)[0] + "_propre.stl"); src = n["stl"] if n.get("ok") else ar.stl
        f = socle_figurine(src, ar.hauteur, ar.nom); os.makedirs(ar.out, exist_ok=True)
        P = {"figurine": Piece("figurine", f, orientation="telle", role="esthetique")}
        _, info = verifier_piece(P["figurine"], ar.out, True)
        zp = livrer({"figurine": poser_sur_plateau(f)}, P, ar.out, "Figurine" + ("_" + ar.nom if ar.nom else ""))
        print(json.dumps(dict(zip=zp, dims=_pt(f.extents), verifs=[(r["statut"], r["verif"], r["detail"]) for r in info["resultats"] if r["statut"] != OK]), ensure_ascii=False, indent=1, default=str)); return 0
    if ar.cmd == "couper":
        m = trimesh.load(ar.stl, force="mesh"); os.makedirs(ar.out, exist_ok=True)
        try:
            if ar.imprimante or getattr(ar, "buse", None): utiliser_imprimante(ar.imprimante or "p2s", ar.buse)
            controle_echelle(m.extents, os.path.basename(ar.stl)); normaliser_materiau(ar.materiau)
        except ValueError as e: print(json.dumps(dict(verdict=ECHEC, erreur=str(e)), ensure_ascii=False, indent=1)); return 2
        alertes = []
        if ar.axe == "auto":
            mor = decouper_pour_plateau(m, connecteur=ar.connecteur); alertes += getattr(decouper_pour_plateau, "notes", [])
        else:
            r = couper(m, ar.axe, ar.position, ar.connecteur); mor = [r[k] for k in ("moitie_1", "moitie_2")] + [r["goupille"]] * r.get("copies_goupille", 0)
            if r.get("avertissement"): alertes.append(r["avertissement"])
        P = {}; M = {}; gou = [x for x in mor if x.volume <= 500]; i_ = 0
        for x in mor:
            if x.volume <= 500: continue
            i_ += 1; nom = f"morceau_{i_}"; P[nom] = Piece(nom, x, materiau=ar.materiau); M[nom] = poser_sur_plateau(x)
        if gou:      # toutes les goupilles dans UN fichier (copies)
            P["goupilles"] = Piece("goupilles", gou[0], materiau=ar.materiau, copies=len(gou)); M["goupilles"] = poser_sur_plateau(gou[0])
        lit = MACHINE["lit"]; trop = []
        for k, v in M.items():      # chaque morceau revérifié sur LE plateau choisi
            if any(x > l + 1e-6 for x, l in zip(sorted(v.extents[:2]) + [v.extents[2]], sorted(lit[:2]) + [lit[2]])): trop.append(f"{k} {_pt(v.extents)}")
        if trop:
            print(json.dumps(dict(verdict=ECHEC, erreur=f"morceau(x) plus grand(s) que le plateau {_pt(lit)} de la {MACHINE['nom']} : {trop}"), ensure_ascii=False, indent=1)); return 2
        try:
            zp = livrer(M, P, ar.out, os.path.splitext(os.path.basename(ar.stl))[0] + "_coupe")
        except ValueError as e:
            print(json.dumps(dict(verdict=ECHEC, erreur=str(e)), ensure_ascii=False, indent=1)); return 2
        tr = {n: {k: o.get(k) for k in ("ok", "logiciel", "temps", "grammes", "erreur")} for n, o in getattr(livrer, "orca", {}).items()}
        print(json.dumps(dict(verdict=(AVERT + " à revoir") if alertes else OK, machine=MACHINE["nom"], plateau=_pt(lit), materiau=normaliser_materiau(ar.materiau)["nom"],
                              zip=zp, morceaux={k: " × ".join(f"{x:.1f}" for x in v.extents) + (f" mm, ×{P[k].copies}" if P[k].copies > 1 else " mm") for k, v in M.items()},
                              avertissements=[AVERT + " " + a for a in alertes], tranchage=tr), ensure_ascii=False, indent=1)); return 1 if alertes else 0
    if ar.cmd == "logo":
        m, i = relief_image(ar.image, ar.largeur, ar.hauteur); m.export(ar.out); print(json.dumps(dict(stl=ar.out, **i), ensure_ascii=False, default=str)); return 0
    if ar.cmd == "qr":
        m, i = relief_qr(ar.contenu, ar.cote, ar.hauteur); m.export(ar.out); print(json.dumps(dict(stl=ar.out, **i), ensure_ascii=False, default=str)); return 0
    if ar.cmd in ("composants", "composant"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import composants_lc3d as C
        import catalogue_lc3d as K
        if ar.cmd == "composants": print(json.dumps([{k: f[k] for k in ("num", "nom_complet", "statut", "reussites", "taux")} for f in K.tout()], ensure_ascii=False, indent=1)); return 0
        if ar.action == "chercher": print(json.dumps(K.chercher(ar.numero or ar.note), ensure_ascii=False, indent=1)); return 0
        if ar.action == "fiche": print(json.dumps(K.fiche(int(ar.numero)), ensure_ascii=False, indent=1, default=str)); return 0
        if ar.action == "preuve":
            print(json.dumps(K.ajouter_preuve(int(ar.numero), ar.reussi == "oui", ar.imprimante, ar.filament, ar.photo, ar.qui, ar.note, ar.version), ensure_ascii=False, indent=1)); return 0
        print(json.dumps(C.valider(int(ar.numero), ar.projet, ar.note), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "lecons":
        print(json.dumps(charger_lecons(), ensure_ascii=False, indent=1)); return 0
    if (getattr(ar, "imprimante", None) or getattr(ar, "buse", None)) and ar.cmd in ("run", "apercu", "couper"):
        try:
            utiliser_imprimante(ar.imprimante or "p2s", getattr(ar, "buse", None))
        except ValueError as e:
            print(json.dumps(dict(verdict=ECHEC + " imprimante refusée", erreur=str(e)), ensure_ascii=False, indent=1)); return 2
    if ar.cmd in ("studio-pousser", "studio-lire", "studio-ecrire", "studio-ouvrir"):
        try:
            if ar.cmd == "studio-ouvrir": out = studio_ouvrir(not ar.sans_navigateur)
            elif ar.cmd == "studio-lire": out = studio_lire(ar.chemin)
            elif ar.cmd == "studio-ecrire":
                brut = open(ar.json[1:], encoding="utf-8").read() if ar.json.startswith("@") else ar.json
                out = studio_ecrire(ar.chemin, json.loads(brut), ar.fusion)
            else:
                if ar.etape == "pret":           # « Prêt » = plan complet + coup d'œil final sur les rendus
                    _d = os.path.abspath(ar.sortie)
                    for _ in range(3):              # plan.json : dans le dossier du projet, au-dessus de la sortie
                        _d = os.path.dirname(_d)
                        if os.path.exists(os.path.join(_d, "plan.json")) or os.path.basename(_d) == "exemples": break
                    _mod = os.path.join(_d, "modele.py")
                    if os.path.basename(_d) != "exemples":
                        _manque = plan_manquant(_plan_projet(_mod)[0], final=True)
                        if _manque:
                            print(json.dumps(dict(verdict=ECHEC + " pas encore prêt", manque=_manque,
                                                  conseil="Regarde les images du rapport : est-ce que ça ressemble au vrai objet, est-ce beau et logique ? "
                                                          "Corrige si non, puis écris ta réponse dans plan.json (coup_oeil)."), ensure_ascii=False, indent=1)); return 2
                etat = None
                try:
                    _ap = json.load(open(os.path.join(ar.sortie, "studio", "a_pousser.json"))); etat = _ap.get("etat")
                    if _ap.get("garde_fous") is not None:
                        etat = dict(etat or {}); etat["garde"] = [f"{n} : {g['titre']} — {g['detail']}" for n, L in _ap["garde_fous"].items() for g in L][:8]
                except Exception: pass
                out = studio_pousser(ar.sortie, ar.projet, ar.version, etat, ar.message, ar.imprimante, ar.etape)
        except (RuntimeError, ValueError) as e:
            print(json.dumps(dict(verdict=ECHEC + " Studio", erreur=str(e)), ensure_ascii=False, indent=1)); return 2
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "studio-paquet":
        etat = None
        try:
            _ap = json.load(open(os.path.join(ar.sortie, "studio", "a_pousser.json"))); etat = _ap.get("etat")
            if _ap.get("garde_fous") is not None:
                etat = dict(etat or {}); etat["garde"] = [f"{n} : {g['titre']} — {g['detail']}" for n, L in _ap["garde_fous"].items() for g in L][:8]
        except Exception: pass
        print(json.dumps(paquet_studio(ar.sortie, ar.projet, ar.version, etat, ar.message, ar.imprimante, ar.etape), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "gravure":
        if os.path.exists(ar.source):
            src = trimesh.load(ar.source, force="mesh") if ar.source.lower().endswith((".stl", ".obj", ".3mf")) else __import__("cadquery").importers.importStep(ar.source)
        else:
            src = relief_texte(ar.source, ar.taille, 1.0)
        print(json.dumps(gravure_svg(src, ar.out, remplir=not ar.decoupe), ensure_ascii=False, indent=1)); return 0
    if ar.cmd == "miroir":
        import lc3d_miroir as LM
        mod = _charger_modele(ar.modele); p = _parse_set(ar.set, getattr(mod, "PARAMS", {})); pcs = mod.build(p)
        A = mod.assembly(p, pcs) if hasattr(mod, "assembly") else None; ms = []
        for n, pc in pcs.items():
            if getattr(pc, "role", "") == "achetee": continue
            m = vers_mesh(pc.forme if isinstance(pc, Piece) else pc)
            if A is not None and n in A.poses: m.apply_transform(A.poses[n])
            ms.append(m)
        print(json.dumps(LM.comparer(ms, ar.photo, ar.vue, sortie_png=ar.out), ensure_ascii=False, indent=1, default=float)); return 0
    if ar.cmd == "retour":
        return retour_cao(ar.modele, dict(x.split("=", 1) for x in ar.remplacements), ar.out, ar.zip)
    if ar.cmd == "variantes":
        g = {}
        for t in ar.grille:
            k, v = t.split("="); g[k] = [float(x) if re.match(r"^-?[\d.]+$", x) else x for x in v.split(",")]
        print(json.dumps(variantes(ar.modele, g, ar.set, ar.out), ensure_ascii=False, indent=1, default=str)); return 0
    if ar.cmd in ("freecad", "cao"):
        print(json.dumps(exporter_freecad(ar.modele, ar.out, ar.set), ensure_ascii=False, indent=1, default=str)); return 0
    if ar.cmd == "freecad-installer":
        import lc3d_freecad as LF; print(json.dumps(dict(ok=LF.installer()), ensure_ascii=False)); return 0
    if ar.cmd == "bambu-installer":
        import lc3d_bambu as LB
        print("Bambu Studio installé" if (LB.disponible() or LB.installer()) else "échec de l'installation"); return 0
    if ar.cmd == "orca-installer":
        print(json.dumps(dict(ok=installer_orca(), chemin=ORCA_APP), ensure_ascii=False)); return 0
    if ar.cmd == "imprimante":
        import lc3d_profils as LP
        try:
            print(json.dumps(LP.trouver_machine_stricte(" ".join(ar.texte), buse_imposee=False), ensure_ascii=False, indent=1)); return 0
        except ValueError as e:
            print(json.dumps(dict(trouve=False, erreur=str(e)), ensure_ascii=False, indent=1)); return 2
    if ar.cmd == "apercu" and ar.verif:
        return executer(ar.modele, ar.set, ar.out, None, False, "3mf", (), rapide=True)
    if ar.cmd == "apercu":
        print(json.dumps(apercu_studio(ar.modele, ar.set, ar.out), ensure_ascii=False, indent=1, default=str)); return 0
    if ar.cmd == "run":
        global TRANCHER
        if ar.sans_tranchage: TRANCHER = False
        ex = tuple(k for k in ("photo", "plans", "notice", "studio", "plateau_unique") if getattr(ar, k))
        if ar.zip and "studio" not in ex: ex += ("studio",)          # livrer = toujours montrer la pièce dans le Studio
        if ar.mem_max: GARDE["mem_mo"] = ar.mem_max
        if ar.delai_max: GARDE["delai_s"] = ar.delai_max
        return executer(ar.modele, ar.set, ar.out, ar.zip, not ar.sans_rendu, ar.format, ex, rapide=ar.rapide, livrer_quand_meme=ar.livrer_quand_meme)
    if ar.cmd == "check":
        mm_ = trimesh.load(ar.stl, force="mesh")
        try: controle_echelle(mm_.extents, os.path.basename(ar.stl))
        except ValueError as e: print(json.dumps(dict(verdict=ECHEC, erreur=str(e)), ensure_ascii=False, indent=1)); return 2
        pc = Piece(os.path.splitext(os.path.basename(ar.stl))[0], mm_, role=ar.role, mur_min=ar.mur_min, orientation=ar.orientation)
        _, info = verifier_piece(pc, ar.out or "sortie_check")
        print(json.dumps(info, ensure_ascii=False, indent=1, default=str)); return 0
    if ar.cmd == "calc":
        f = dict(snap=calc_snap, lame=calc_lame, ressort=calc_ressort, rampe=calc_rampe, engrenage=calc_engrenage, ajustement=calc_ajustement, roulement=logement_roulement, vis=calc_vis, bossage=calc_bossage)
        try:
            mal = [x for x in ar.kv if "=" not in x]
            if mal: raise ValueError(f"écrire nom=valeur (ex. arbre=8), pas « {mal[0]} »")
            kv = {}
            for k, v in (x.split("=", 1) for x in ar.kv):
                v = v.replace(",", ".") if re.match(r"^-?\d+,\d+$", v) else v
                kv[k] = json.loads(v) if re.match(r"^-?\d+(\.\d+)?$", v) or v in ("true", "false") else v
            print(json.dumps(dict(trous_fdm=TROUS_FDM, vis_iso=VIS_ISO, divers=TROUS) if ar.type == "trous" else f[ar.type](**kv), ensure_ascii=False, indent=1)); return 0
        except TypeError as e:
            import inspect
            perm = ", ".join(inspect.signature(f[ar.type]).parameters) if ar.type in f else ""
            manq = re.findall(r"'(\w+)'", str(e))
            quoi = (f"il manque : {', '.join(manq)}" if "missing" in str(e) else f"paramètre inconnu : {', '.join(manq)}") if manq else "paramètre inconnu ou manquant"
            print(json.dumps(dict(erreur=f"calc {ar.type} : {quoi}. Paramètres permis : {perm}"), ensure_ascii=False)); return 2
        except (ValueError, KeyError, ZeroDivisionError) as e:
            print(json.dumps(dict(erreur=f"calc {ar.type} : {e if not isinstance(e, KeyError) else 'valeur inconnue ' + str(e)}"), ensure_ascii=False)); return 2
    if ar.cmd == "outline-scan":
        P, i = contour_depuis_scan(ar.scan, ar.jeu); contour_svg(P, ar.out); print(json.dumps(i, ensure_ascii=False)); return 0
    if ar.cmd == "outline-photo":
        P, i = contour_depuis_photo(ar.photo, ar.ref, jeu=ar.jeu); contour_svg(P, ar.out); print(json.dumps(i, ensure_ascii=False)); return 0
    if ar.cmd == "gridfinity":
        import cadquery as cq
        if ar.type == "bac":
            nx, ny, nz = (ar.dims + [1, 1, 3])[:3]
            s = gridfinity_bac(nx, ny, nz, ar.cases[0], ar.cases[1], ar.aimants, not ar.sans_levre, ar.etiquette)
        else:
            nx, ny = (ar.dims + [1, 1])[:2]; s = gridfinity_plaque(nx, ny)
        cq.exporters.export(s, ar.out); print(ar.out); return 0


if __name__ == "__main__":
    sys.exit(main())
