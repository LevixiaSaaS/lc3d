"""LC3D — toutes les imprimantes : profils officiels d'OrcaSlicer (gratuit, libre, ~1 150 machines).

- trouver_machine("p1s") / ("ender 3 v3") / ("u1")  -> nom exact du profil + plateau + buse
- reglages_projet_orca(machine, "PETG", 0.2)        -> réglages aplatis (machine + impression + filament)
  pour le fichier Metadata/project_settings.config d'un 3MF (OrcaSlicer et Bambu Studio les lisent).
Les profils sont téléchargés une fois (git, seulement le dossier du fabricant) dans ~/.lc3d/orca.
"""
import json, os, re, subprocess, glob, unicodedata

ICI = os.path.dirname(os.path.abspath(__file__))
CATALOGUE = os.path.join(ICI, "imprimantes_catalogue.json")
ORCA = os.path.join(os.path.expanduser("~"), ".lc3d", "orca")
# Profils du logiciel INSTALLÉ (OrcaSlicer ~/.lc3d/orcaslicer) en priorité : mêmes noms et mêmes modèles de G-code que le
# logiciel qui vérifie le fichier. Sinon : copie git des profils d'OrcaSlicer.
_APP = os.path.join(os.path.expanduser("~"), ".lc3d", "orcaslicer", "squashfs-root", "resources", "profiles")
_GIT = os.path.join(ORCA, "resources", "profiles")
PROFILS = _APP if os.path.isdir(_APP) else _GIT
DEPOT = "https://github.com/SoftFever/OrcaSlicer.git"

ALIAS = {"bambu": "bambu lab", "bbl": "bambu lab", "x1c": "x1 carbon", "x1-c": "x1 carbon", "core one": "core one", "mk4": "mk4",
         "ender3": "ender-3", "ender 3": "ender-3", "k1max": "k1 max", "u1": "snapmaker u1"}


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    for a, b in ALIAS.items():
        s = re.sub(rf"\b{re.escape(a)}\b", b, s)
    return re.sub(r"[^a-z0-9.]+", " ", s).strip()


def catalogue():
    return json.load(open(CATALOGUE))


def trouver_machine(texte, buse=0.4):
    """Meilleure correspondance dans le catalogue. Retourne dict(nom, fabricant, x, y, z, buse, modele, firmware, autres=[...])."""
    cat = catalogue(); q = _norm(texte).split()
    def score(nom, d):
        n = _norm(nom + " " + d.get("modele", ""))
        mots = n.split()
        s = sum(3 if w in mots else (1 if w in n else -2) for w in q)
        if abs(d.get("buse", 0.4) - buse) < 1e-6: s += 2
        if d.get("fabricant") in ("OrcaArena", "Custom") and "arena" not in q and "custom" not in q: s -= 4
        return s - len(mots) * 0.05
    rang = sorted(cat.items(), key=lambda kv: -score(*kv))
    # correspondance STRICTE : chaque mot écrit doit être dans le nom de la machine (ou son modèle / fabricant)
    def mots(nom, d): return set(_norm(nom + " " + d.get("modele", "") + " " + d.get("fabricant", "")).split())
    stricts = [(n, d) for n, d in rang if all(w in mots(n, d) for w in q)]
    ambigus = []
    if stricts:
        nom, d = stricts[0]; certain = True
        # même nombre de mots en trop, même buse, mais plateau différent (ex. Voron 2.4 250 / 300 / 350) : il faut préciser
        ext = lambda n, d_: len(mots(n, d_)) - len(set(q))
        m0 = min(ext(n, d_) for n, d_ in stricts if abs(d_.get("buse", 0.4) - buse) < 1e-6) if any(abs(d_.get("buse", 0.4) - buse) < 1e-6 for _, d_ in stricts) else None
        if m0 is not None:
            memes = [(n, d_) for n, d_ in stricts if abs(d_.get("buse", 0.4) - buse) < 1e-6 and ext(n, d_) == m0]
            if len({(d_.get("x"), d_.get("y"), d_.get("z")) for _, d_ in memes}) > 1: ambigus = [n for n, _ in memes][:6]
        # même nom chez deux fabricants (ex. « x1 » : Bambu Lab X1 et Chuanying X1) : il faut nommer le fabricant
        fabs = {}
        for n, d_ in stricts:
            if abs(d_.get("buse", 0.4) - buse) < 1e-6 and d_.get("fabricant") not in ("OrcaArena", "Custom"): fabs.setdefault(d_.get("fabricant"), n)
        if len(fabs) > 1: ambigus = list(fabs.values())[:6]
    else:
        nom, d = rang[0]; certain = False
    r = dict(nom=nom, **d, autres=[n for n, _ in rang[1:6] if n != nom], certain=certain, ambigus=ambigus)
    if not certain:
        # faute de frappe ? (difflib sur les mots du catalogue) -> proposition, jamais un choix en silence
        import difflib
        vocab = sorted({w for n, d_ in cat.items() for w in mots(n, d_)})
        corr = [w if any(w in mots(n, d_) for n, d_ in rang[:50]) or w in vocab else (difflib.get_close_matches(w, vocab, 1, 0.75) or [w])[0] for w in q]
        prop = None
        if corr != q:
            for n, d_ in sorted(cat.items(), key=lambda kv: -score(*kv)):
                if all(w in mots(n, d_) for w in corr): prop = n; break
        r["proposition"] = prop
    return r


MOTS_RESINE = ("photon", "mars", "saturn", "jupiter", "halot", "formlabs", "form 2", "form 3", "form 4", "sonic mini", "sonic mighty",
               "resine", "resin", "sla", "msla", "dlp", "lcd", "uniformation", "phrozen", "peopoly")


def trouver_machine_stricte(texte, buse=0.4, buse_imposee=True):
    """Comme trouver_machine, mais REFUSE (ValueError) une machine absente du catalogue, mal écrite (« vouliez-vous dire … ? »)
    ou à résine. Jamais de substitution silencieuse par une autre imprimante."""
    t = _norm(texte)
    if any(re.search(rf"\b{re.escape(m)}\b", t) for m in MOTS_RESINE):
        raise ValueError(f"« {texte} » est une imprimante à RÉSINE (SLA/MSLA). LC3D fait du FDM (filament) seulement : ses 3MF, profils et "
                         f"vérifications (murs, ponts, couches) ne s'appliquent pas. Exporter la pièce en STL (run … --format stl) et la préparer "
                         f"dans le logiciel de la résine (Chitubox, Lychee, PreForm pour Formlabs) : supports, évents, drainage des creux.")
    m = trouver_machine(texte, buse)
    if not m["certain"]:
        if m.get("proposition"):
            raise ValueError(f"Imprimante « {texte} » introuvable telle qu'écrite dans le catalogue (~1 150 profils OrcaSlicer/Bambu). "
                             f"Vouliez-vous dire « {m['proposition']} » ? Rien n'est fait tant que ce n'est pas confirmé : relancer avec "
                             f"--imprimante \"{m['proposition']}\".")
        raise ValueError(f"Imprimante « {texte} » absente du catalogue (~1 150 profils OrcaSlicer/Bambu) : LC3D ne la remplace pas par une autre. "
                         f"Les plus ressemblantes par le nom (pas forcément la même machine) : {', '.join([m['nom']] + m['autres'][:3])}. "
                         f"Solutions : donner le nom exact d'un profil équivalent (même plateau, même buse), ou exporter en STL (--format stl) "
                         f"et trancher dans le logiciel de la machine.")
    if m.get("ambigus"):
        raise ValueError(f"« {texte} » désigne plusieurs machines : {', '.join(m['ambigus'])}. Préciser laquelle (ex. --imprimante \"{m['ambigus'][0]}\").")
    if buse_imposee and buse and abs(float(m["buse"]) - float(buse)) > 1e-6:     # jamais une autre buse en silence
        dispo = sorted({float(d.get("buse", 0.4)) for n, d in catalogue().items() if _base_machine(n) == _base_machine(m["nom"])})
        raise ValueError(f"Aucun profil buse {buse:g} mm pour la {_base_machine(m['nom'])} (le fabricant fournit : "
                         f"{', '.join(f'{b:g}' for b in dispo) or '?'} mm). LC3D ne change PAS de buse en silence : relancer avec --buse "
                         f"{min(dispo, key=lambda b: abs(b - float(buse))):g} si c'est la bonne, ou exporter en STL et trancher dans le logiciel de la machine.")
    return m


def _base_machine(nom):
    return re.sub(r"\s*\(?\d+(\.\d+)?\s*nozzle\)?\s*$", "", nom, flags=re.I).strip()


def _telecharger(fabricant):
    dossier = os.path.join(_GIT, fabricant)
    if os.path.isdir(dossier):
        return dossier
    os.makedirs(os.path.dirname(ORCA), exist_ok=True)
    if not os.path.isdir(os.path.join(ORCA, ".git")):
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse", DEPOT, ORCA], check=True)
        subprocess.run(["git", "-C", ORCA, "sparse-checkout", "set", "--no-cone", "/resources/profiles/*.json"], check=True)
    voulus = set(subprocess.run(["git", "-C", ORCA, "sparse-checkout", "list"], capture_output=True, text=True).stdout.split())
    voulus |= {f"/resources/profiles/{fabricant}/", "/resources/profiles/OrcaFilamentLibrary/", "/resources/profiles/*.json"}
    subprocess.run(["git", "-C", ORCA, "sparse-checkout", "set", "--no-cone", *sorted(voulus)], check=True)
    return dossier


_CACHE_IDX = {}


def _index(fabricant, machine=None):
    """Profils du fabricant. Si la machine est connue du logiciel installé : SES profils (mêmes noms, mêmes G-code que le
    logiciel qui vérifie). Sinon (machine plus récente que le logiciel) : profils à jour d'OrcaSlicer (git)."""
    racines = [_APP] if os.path.isdir(_APP) else []
    if machine is not None:
        app = _charger_idx(_APP, fabricant) if racines else {}
        if machine in app: return app
        _telecharger(fabricant); return _charger_idx(_GIT, fabricant)
    if racines: return _charger_idx(_APP, fabricant)
    _telecharger(fabricant); return _charger_idx(_GIT, fabricant)


def _charger_idx(racine, fabricant):
    cle = (racine, fabricant)
    if cle in _CACHE_IDX: return _CACHE_IDX[cle]
    idx = {}
    for dos in (fabricant, "OrcaFilamentLibrary"):
        for f in glob.glob(os.path.join(racine, dos, "**", "*.json"), recursive=True):
            try:
                j = json.load(open(f))
            except Exception:
                continue
            if isinstance(j, dict) and "name" in j and "type" in j:
                idx.setdefault(j["name"], j)     # le fabricant passe avant la bibliothèque commune
    _CACHE_IDX[cle] = idx
    return idx


def _resoudre(idx, nom, vus=()):
    j = idx.get(nom)
    if j is None:
        return {}
    base = _resoudre(idx, j["inherits"], vus + (nom,)) if j.get("inherits") and j["inherits"] not in vus else {}
    r = dict(base); r.update(j); return r


def _cond_vraie(cond, M):
    """Évalue (à peu près) compatible_printers_condition d'Orca : =~ /re/, !~ /re/, ==, !=, and, or."""
    def val(k):
        m = re.match(r"(\w+)(?:\[(\d+)\])?", k.strip()); v = M.get(m.group(1), "")
        if isinstance(v, list): v = v[int(m.group(2) or 0)] if v else ""
        return str(v)
    def atome(a):
        a = a.strip().strip("()").strip()
        if not a: return True
        m = re.match(r"(.+?)\s*(=~|!~)\s*/(.*)/$", a)
        if m:
            ok = re.search(m.group(3), val(m.group(1))) is not None
            return ok if m.group(2) == "=~" else not ok
        m = re.match(r"(.+?)\s*(==|!=)\s*\"?([^\"]*)\"?$", a)
        if m:
            g, d = val(m.group(1)), m.group(3)
            try: eg = abs(float(g) - float(d)) < 1e-6
            except Exception: eg = g == d
            return eg if m.group(2) == "==" else not eg
        return True
    try:
        return any(all(atome(a) for a in re.split(r"\band\b", o)) for o in re.split(r"\bor\b", cond))
    except Exception:
        return False


def _compatible(j, machine, M=None, buse=0.4):
    cp = j.get("compatible_printers")
    if cp:
        return 2 if machine in cp else 0
    cond = j.get("compatible_printers_condition")
    if cond and M is not None:
        return 1 if _cond_vraie(cond, M) else 0
    # ni liste ni condition : profil générique du fabricant, accepté si la buse correspond
    tailles = re.findall(r"(\d\.\d+)\s*(?:mm\s*)?nozzle|nozzle\s*(\d\.\d+)", j.get("name", ""))
    tailles = [float(a or b) for a, b in tailles]
    return 0.5 if (not tailles or abs(tailles[0] - buse) < 1e-6) else 0


def choisir_process(idx, machine, couche=0.2, M=None, buse=0.4):
    cands = []
    for n, j in idx.items():
        if j.get("type") != "process" or str(j.get("instantiation", "")).lower() != "true":
            continue
        c = _compatible(j, machine, M, buse)
        if not c:
            continue
        r = _resoudre(idx, n)
        try:
            lh = float(r.get("layer_height", 0))
        except Exception:
            continue
        pref = (0 if re.search(r"standard|optimal|normal|quality|structural", n, re.I) else 1) + (2 - c) * 2
        cands.append((abs(lh - couche), pref, len(n), n))
    return sorted(cands)[0][3] if cands else None


def choisir_filament(idx, machine, materiau="PETG", M=None, buse=0.4):
    mat = materiau.upper().replace("É", "E").split()[0]
    cands = []
    for n, j in idx.items():
        if j.get("type") != "filament" or str(j.get("instantiation", "")).lower() != "true":
            continue
        c = _compatible(j, machine, M, buse)
        if not c:
            continue
        r = _resoudre(idx, n)
        ft = r.get("filament_type", [""]); ft = (ft[0] if isinstance(ft, list) else ft).upper()
        if ft != mat:
            continue
        pref = 0 if n.lower().startswith("generic") else 1
        if "HF" in n and mat == "PETG": pref -= 0.5          # PETG HF : coule mieux sur les machines rapides
        if re.search(r"support|cf|gf|silk|matte|translucent", n, re.I): pref += 2
        pref += (2 - c) * 2
        cands.append((pref, len(n), n))
    return sorted(cands)[0][2] if cands else None


_JETER = ("name", "from", "instantiation", "setting_id", "type", "description", "compatible_printers", "compatible_printers_condition",
          "filament_id", "base_id", "inherits", "renamed_from")


def reglages_projet_orca(machine, materiau="PETG", couche=0.2):
    """Retourne (cfg, noms) comme reglages_projet() de lc3d, pour n'importe quelle machine du catalogue."""
    cat = catalogue()
    if machine not in cat:
        machine = trouver_machine(machine)["nom"]
    fab = cat[machine]["fabricant"]
    idx = _index(fab, machine)
    M = _resoudre(idx, machine); buse = cat[machine].get("buse", 0.4)
    npr = choisir_process(idx, machine, couche, M, buse)
    nf = choisir_filament(idx, machine, materiau, M, buse)
    cfg = {}
    for n in (machine, npr, nf):
        if not n:
            continue
        d = _resoudre(idx, n)
        for k in _JETER:
            d.pop(k, None)
        cfg.update(d)
    cfg.update({"printer_settings_id": machine, "print_settings_id": npr or "", "filament_settings_id": [nf or ""],
                "printer_model": cat[machine].get("modele", ""), "from": "project", "name": "project_settings"})
    cfg = {k: ([str(x) for x in v] if isinstance(v, list) else str(v)) for k, v in cfg.items() if v is not None}
    return cfg, dict(machine=machine, process=npr, filament=nf)


if __name__ == "__main__":
    import sys
    t = " ".join(sys.argv[1:]) or "p2s"
    m = trouver_machine(t)
    print(json.dumps(m, ensure_ascii=False, indent=1))
    cfg, noms = reglages_projet_orca(m["nom"], "PETG", 0.2)
    print(json.dumps(noms, ensure_ascii=False), len(cfg), "réglages")


def filament_resolu(machine, materiau="PETG"):
    cat = catalogue(); fab = cat[machine]["fabricant"]; idx = _index(fab, machine)
    M = _resoudre(idx, machine); n = choisir_filament(idx, machine, materiau, M, cat[machine].get("buse", 0.4))
    d = _resoudre(idx, n) if n else {}
    for k in _JETER: d.pop(k, None)
    return n, d


VARIANTE_FILAMENT = {
    "filament_flow_ratio", "filament_max_volumetric_speed", "filament_extruder_id", "filament_extruder_variant", "filament_retraction_length",
    "filament_z_hop", "filament_z_hop_types", "filament_retract_lift_above", "filament_retract_lift_below", "filament_retract_lift_enforce",
    "filament_retract_restart_extra", "filament_retraction_speed", "filament_deretraction_speed", "filament_retraction_minimum_travel",
    "filament_retract_when_changing_layer", "filament_wipe", "filament_wipe_distance", "filament_retract_before_wipe",
    "filament_long_retractions_when_cut", "filament_retraction_distances_when_cut", "long_retractions_when_ec", "retraction_distances_when_ec",
    "nozzle_temperature_initial_layer", "nozzle_temperature", "filament_flush_volumetric_speed", "filament_flush_temp",
    "filament_cooling_before_tower", "volumetric_speed_coefficients", "filament_adaptive_volumetric_speed", "filament_ironing_flow",
    "filament_ironing_spacing", "filament_ironing_inset", "filament_ironing_speed", "activate_air_filtration",
    "activate_air_filtration_during_print", "activate_air_filtration_on_completion", "during_print_exhaust_fan_speed",
    "complete_print_exhaust_fan_speed"}


def multi_filaments(cfg, machine, materiaux):
    """Plusieurs filaments dans le même projet (AMS de Bambu, 4 têtes de la Snapmaker U1, MMU Prusa…) :
    chaque réglage de filament devient une liste, un élément par filament, dans l'ordre de `materiaux`."""
    profs = [filament_resolu(machine, m) for m in materiaux]
    cles = set().union(*[set(d) for _, d in profs])
    for k in cles:
        vals = []
        for _, d in profs:
            v = d.get(k, cfg.get(k))
            v = v[0] if isinstance(v, list) and v else v
            vals.append(None if v is None else str(v))
        if all(v is not None for v in vals):       # dans OrcaSlicer, TOUT réglage de filament est une liste (une valeur par filament)
            cfg[k] = vals
    cfg["filament_settings_id"] = [n or "" for n, _ in profs]
    # Réglages « par variante de buse » (liste exacte : OrcaSlicer PrintConfig.cpp, filament_options_with_variant) : une valeur par
    # (filament × variante), et filament_self_index dit à quel filament appartient chaque valeur. Sans lui, OrcaSlicer donne à TOUS
    # les filaments les valeurs du premier (ex. PLA chauffé à la température du PETG sur une machine à plusieurs têtes).
    variantes = [(d.get("filament_extruder_variant") or ["Direct Drive Standard"]) for _, d in profs]
    variantes = [v if isinstance(v, list) else [v] for v in variantes]
    for k in VARIANTE_FILAMENT:
        if k in ("filament_extruder_variant",): continue
        vals = []
        for (_, d), var in zip(profs, variantes):
            v = d.get(k, cfg.get(k))
            if v is None: vals = None; break
            v = v if isinstance(v, list) else [v]
            vals += [str(x) for x in ((v + [v[-1]] * len(var))[:len(var)] if len(v) >= 1 else [""] * len(var))]
        if vals is not None: cfg[k] = vals
    cfg["filament_extruder_variant"] = [x for var in variantes for x in var]
    cfg["filament_self_index"] = [str(i + 1) for i, var in enumerate(variantes) for _ in var]
    # TOUTE option de filament doit avoir une valeur par filament (sinon Orca : « preset invalide »)
    fab = catalogue()[machine]["fabricant"] if machine in catalogue() else None
    univers = set()
    if fab:
        for j in _index(fab, machine).values():
            if j.get("type") == "filament": univers |= set(j)
    univers |= {"filament_is_support", "filament_colour", "filament_type", "filament_soluble", "filament_diameter", "filament_density",
                "filament_cost", "nozzle_temperature", "nozzle_temperature_initial_layer", "filament_max_volumetric_speed"}
    n = len(materiaux)
    for k in list(cfg):
        v = cfg[k]
        if k in univers and k not in _JETER and k not in ("filament_settings_id",) and k not in VARIANTE_FILAMENT and k != "filament_self_index":
            if isinstance(v, list) and len(v) == 1: cfg[k] = v * n
            elif not isinstance(v, list) and k.startswith("filament_"): cfg[k] = [str(v)] * n
    for k in ("filament_is_support", "filament_soluble"):
        if k not in cfg: cfg[k] = ["0"] * n
    nb_ext = len(cfg.get("nozzle_diameter", ["0.4"])) if isinstance(cfg.get("nozzle_diameter"), list) else 1
    # quelle tête/buse imprime quel filament : une tête par filament si la machine en a assez (U1 : 4), sinon tout sur la buse 1 (AMS)
    cfg["filament_map"] = [str(min(i + 1, nb_ext)) for i in range(len(materiaux))]
    cfg["filament_map_mode"] = "Manual"
    return cfg
