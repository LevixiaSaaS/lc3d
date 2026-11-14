"""LC3D — catalogue de composants numérotés, versionnés et prouvés.

Fiche d'un composant : numéro, nom simple (« Clip n° 1 — clip carré 1 mm »), version, besoins (pour la recherche
« je veux un couvercle qui s'ouvre sans outil »), cotes fixes / ajustables, calcul, statut, preuves, licence, ligne d'usage.

Statuts (jamais donnés à la main) :
- « calculé »             : passe les vérifications LC3D, aucune impression déclarée;
- « imprimé 1 fois »      : au moins 1 impression réussie AVEC photo;
- « prouvé (communauté) » : ≥ 5 impressions réussies avec photo, par ≥ 3 personnes différentes, et ≥ 90 % de réussite.
Une preuve sans photo est gardée mais ne compte pas. Un échec compte toujours (taux de réussite honnête).

Versions : une amélioration crée la v2 (nouvelle fonction ou nouveaux défauts); un projet garde la version qu'il a
utilisée (`utiliser(1, version=1)`), donc une amélioration ne brise jamais un ancien projet.

Licence des composants : MIT — réutilisables par tous, même pour vendre des produits, en gardant l'avis d'auteur.
"""
import json, os, re, time, unicodedata, importlib

LICENCE = "MIT — © LevixiaSaaS (LC3D). Réutilisation libre, même commerciale, en gardant cet avis."
FICHIER_PREUVES = os.path.join(os.path.expanduser("~"), ".lc3d", "preuves.json")

# Fiches des 7 premiers composants (les lots 8-30 apportent leurs propres FICHES_*)
FICHES_BASE = [
    dict(num=1, nom="Clip carré 1 mm", type="clip", fonction="clip_1", besoins="clipser fermer couvercle sans outil attache encliqueter tenir boite ouvrable",
         description="Bras flexible avec crochet : rampe d'entrée 30°, face de retenue 90° (permanent), 45° (s'enlève en tirant) ou 30° (à la main). Accroche 1 mm.",
         cotes_fixes=dict(rampe="30°", accroche_min="1,0 mm", jeu_fenetre="0,3 mm"), cotes_ajustables=dict(L="12 mm", h="1,6 mm", w="6 mm", retenue="90/45/30°")),
    dict(num=2, nom="Bossage pour insert chaud", type="vis", fonction="bossage_insert_2", besoins="visser vis insert laiton filet solide démonter souvent",
         description="Trou et paroi calculés pour inserts laiton M2 à M5.", cotes_fixes=dict(), cotes_ajustables=dict(taille="M3", hauteur="8 mm")),
    dict(num=3, nom="Écrou captif", type="vis", fonction="ecrou_captif_3", besoins="écrou visser boulon serrer bloquer ne tourne pas",
         description="Logement hexagonal avec fente latérale : l'écrou glisse et ne tourne pas.", cotes_fixes=dict(), cotes_ajustables=dict(taille="M3", longueur_fente="10 mm")),
    dict(num=4, nom="Logement de roulement", type="roulement", fonction="logement_roulement_4", besoins="tourner axe roulement 608 rotation fluide roue",
         description="Roulement 608 et autres : serrage pressé, léger ou libre.", cotes_fixes=dict(), cotes_ajustables=dict(ref="608", serrage="leger")),
    dict(num=5, nom="Pot + couvercle vissé", type="filet", fonction="couvercle_filete_5", besoins="visser dévisser couvercle pot bocal fermer étanche sans outil rond",
         description="Filet trapézoïdal à 45°, sans support, 0,2 mm de jeu axial. Vérifié : se visse sans toucher et tient.",
         cotes_fixes=dict(angle_filet="45°", jeu="0,3 mm"), cotes_ajustables=dict(diametre="40 mm", pas="4 mm", hauteur_filet="14 mm")),
    dict(num=6, nom="Poche d'aimant", type="aimant", fonction="poche_aimant_6", besoins="aimant magnétique fermer couvercle sans outil coller fixer métal",
         description="Aimants néodyme à presser ou à coller, jeu selon le diamètre.", cotes_fixes=dict(), cotes_ajustables=dict(d="6 mm", e="2 mm", serrage="serre")),
    dict(num=7, nom="Goupille d'alignement", type="assemblage", fonction="goupille_alignement_7", besoins="aligner deux pièces coller assembler grande pièce coupée",
         description="Goupille + trous pour aligner deux pièces collées ou coupées.", cotes_fixes=dict(jeu="0,15 mm"), cotes_ajustables=dict(d="4 mm", longueur="10 mm")),
]

# Synonymes pour la recherche par besoin (français parlé)
SYNONYMES = {
    "ouvrir": "ouvrable ouvre ouverture enlever démonter", "fermer": "fermeture refermer clipser verrou",
    "sans outil": "main doigt pouce clip clipser aimant baionnette", "couvercle": "couvert dessus bouchon",
    "tourner": "rotation pivot charniere axe roulement", "glisser": "coulisser glissiere tiroir",
    "accrocher": "crochet mur suspendre trou serrure", "ressort": "revient retour pousser bouton",
    "visser": "vis filet ecrou insert boulon", "solide": "resistant robuste structure",
    "assembler": "joindre coller aronde goupille", "cable": "fil cordon passe-cable",
    "sangle": "courroie laisse passant boucle", "engrenage": "dent reducteur roue", "pied": "antiderapant caoutchouc",
}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s).lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def _lots():
    """Toutes les fiches : base + lots (composants_lot_a/b/c) s'ils existent."""
    fiches = [dict(f, module="composants_lc3d") for f in FICHES_BASE]
    for mod, var, lot in (("composants_lot_a", "FICHES_A", "LOT_A"), ("composants_lot_b", "FICHES_B", "LOT_B"), ("composants_lot_c", "FICHES_C", "LOT_C")):
        try:
            m = importlib.import_module(mod)
            fonctions = getattr(m, lot, {})
            for f in getattr(m, var, []):
                g = dict(f, module=mod)
                if "fonction" not in g and f["num"] in fonctions: g["fonction"] = fonctions[f["num"]].__name__
                g.setdefault("besoins", "")
                if f.get("statut") == "a_revoir": g["a_revoir"] = True
                fiches.append(g)
        except Exception:
            pass
    return fiches


def preuves():
    try: return json.load(open(FICHIER_PREUVES))
    except Exception: return {}


def statut(num):
    P = [p for p in preuves().get(str(num), [])]
    avec_photo = [p for p in P if p.get("photo")]
    ok = [p for p in avec_photo if p.get("reussi")]
    taux = (len(ok) / len(avec_photo)) if avec_photo else None
    gens = {p.get("qui", "?") for p in ok}
    if len(ok) >= 5 and len(gens) >= 3 and taux >= 0.9:
        s = "prouvé (communauté)"
    elif ok:
        s = "imprimé 1 fois" if len(ok) == 1 else f"imprimé {len(ok)} fois"
    else:
        s = "calculé"
    machines = sorted({f"{p.get('imprimante')}, {p.get('filament')}" for p in ok})
    return dict(statut=s, reussites=len(ok), essais=len(avec_photo), taux=None if taux is None else round(100 * taux),
                personnes=len(gens), machines=machines, sans_photo_ignorees=len(P) - len(avec_photo))


def ajouter_preuve(num, reussi, imprimante, filament, photo=None, qui="anonyme", note="", version=1):
    """Déclare une vraie impression. Sans photo : gardée mais ne compte pas pour le statut."""
    d = preuves()
    d.setdefault(str(num), []).append(dict(reussi=bool(reussi), imprimante=imprimante, filament=filament, photo=photo, qui=qui,
                                           note=note, version=version, date=time.strftime("%Y-%m-%d")))
    os.makedirs(os.path.dirname(FICHIER_PREUVES), exist_ok=True)
    json.dump(d, open(FICHIER_PREUVES, "w"), ensure_ascii=False, indent=1)
    return statut(num)


def fiche(num):
    for f in _lots():
        if f["num"] == num:
            st = statut(num)
            nom_complet = f"{_type_nom(f.get('type'))} n° {num} — {f['nom']}"
            f = {k: v for k, v in f.items() if k != "statut"}
            if f.get("a_revoir"): st["statut"] = "à revoir (ne passe pas encore toutes les vérifs)"
            return dict(f, nom_complet=nom_complet, version=f.get("version", 1), licence=LICENCE, **st,
                        usage=f"from {f['module']} import {f.get('fonction', '?')}   # ou à la voix : « mets le {_type_nom(f.get('type')).lower()} n° {num} »")
    raise KeyError(f"composant n° {num} inconnu")


def _type_nom(t):
    return {"clip": "Clip", "vis": "Fixation", "filet": "Filet", "roulement": "Roulement", "aimant": "Aimant", "assemblage": "Jonction",
            "charniere": "Charnière", "ressort": "Ressort", "engrenage": "Engrenage", "fermeture": "Fermeture"}.get(t or "", "Composant")


def chercher(besoin, n=5):
    """Recherche par besoin : « je veux un couvercle qui s'ouvre sans outil »."""
    q = _norm(besoin)
    for k, v in SYNONYMES.items():
        if _norm(k) in q: q += " " + _norm(v)
    mots = {w for w in q.split() if len(w) > 2 and w not in {"veux", "une", "des", "les", "qui", "pour", "avec", "sans", "dans", "faire", "mettre"}}
    res = []
    for f in _lots():
        texte = _norm(" ".join([f.get("nom", ""), f.get("type", ""), f.get("besoins", ""), f.get("description", "")]))
        tm = set(texte.split())
        score = sum(2 if w in tm else (1 if any(t.startswith(w[:5]) for t in tm) else 0) for w in mots)
        if score: res.append((score, f["num"], f["nom"]))
    return [dict(num=x[1], nom=x[2], pertinence=x[0]) for x in sorted(res, key=lambda t: (-t[0], t[1]))[:n]]


def utiliser(num, version=None, **params):
    """Appelle le composant n° num (version donnée ou la plus récente)."""
    f = next(f for f in _lots() if f["num"] == num)
    m = importlib.import_module(f["module"])
    nom = f["fonction"] if version in (None, 1) else f"{f['fonction']}_v{version}"
    return getattr(m, nom)(**params)


def tout():
    return [fiche(f["num"]) for f in sorted(_lots(), key=lambda f: f["num"])]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "chercher":
        print(json.dumps(chercher(" ".join(sys.argv[2:])), ensure_ascii=False, indent=1))
    else:
        for f in tout():
            print(f["nom_complet"], "·", f["statut"])
