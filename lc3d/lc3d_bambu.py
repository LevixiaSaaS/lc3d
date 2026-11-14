"""LC3D — projets 3MF Bambu Lab construits avec les PROFILS DE BAMBU STUDIO LUI-MÊME (dossier resources/profiles/BBL
de l'AppImage officielle, gratuite). Toutes les machines Bambu (P2S, X1C, P1S, P1P, A1, A1 mini, H2D, H2S…),
tous les filaments Bambu, en 1 couleur ou multi-couleurs (AMS) — et vérifiés en les tranchant avec Bambu Studio en
ligne de commande (s'il refuse un réglage, on le sait avant l'utilisateur)."""
import json, os, glob, re, subprocess, tempfile, shutil

RACINE = os.environ.get("LC3D_BAMBU", os.path.expanduser("~/.lc3d/bambu/squashfs-root"))
PROFILS = os.path.join(RACINE, "resources", "profiles", "BBL")
APP = os.path.join(RACINE, "AppRun")
_META = {"name", "inherits", "from", "setting_id", "instantiation", "type", "description", "compatible_printers",
         "compatible_printers_condition", "base_id", "renamed_from", "version", "filament_id", "is_custom_defined"}
_IDX = None


def disponible():
    return os.path.isdir(PROFILS) and os.path.exists(APP)


def installer(version="v02.08.02.61", build="20260820225108"):
    """AppImage officielle Bambu Studio (GitHub, gratuite) → ~/.lc3d/bambu. ~550 Mo une fois extraite."""
    d = os.path.dirname(RACINE); os.makedirs(d, exist_ok=True); ai = os.path.join(d, "bs.AppImage")
    url = f"https://github.com/bambulab/BambuStudio/releases/download/{version}/BambuStudio_ubuntu24.04-{version}-{build}.AppImage"
    subprocess.run(["curl", "-sL", "-o", ai, url], check=True); os.chmod(ai, 0o755)
    subprocess.run([ai, "--appimage-extract"], cwd=d, check=True, capture_output=True); os.unlink(ai)
    return disponible()


def index():
    global _IDX
    if _IDX is None:
        _IDX = {}
        for f in glob.glob(os.path.join(PROFILS, "*", "*.json")):
            try:
                j = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if isinstance(j, dict) and j.get("name"):
                _IDX[j["name"]] = j
    return _IDX


def resoudre(nom):
    I = index(); j = I[nom]; base = resoudre(j["inherits"]) if j.get("inherits") in I else {}
    out = dict(base); out.update(j); return out


def machines():
    return sorted(n for n, j in index().items() if j.get("type") == "machine" and str(j.get("instantiation")) == "true")


def trouver_machine(texte, buse=0.4):
    t = texte.lower().replace("bambu lab", "").replace("bambu", "").strip()
    alias = {"x1c": "x1 carbon", "x1-carbon": "x1 carbon", "a1m": "a1 mini", "a1-mini": "a1 mini"}
    t = alias.get(t, t)
    cands = [n for n in machines() if f"{buse} nozzle" in n]
    exact = [n for n in cands if n.lower().replace("bambu lab ", "").replace(f" {buse} nozzle", "") == t]
    if exact: return exact[0]
    part = sorted((n for n in cands if t and t in n.lower()), key=len)
    return part[0] if part else None


def _compatible(j, machine):
    return machine in (j.get("compatible_printers") or [])


def choisir_process(machine, couche=0.2):
    I = index(); cible = f"{couche:.2f}mm Standard"
    c = [n for n, j in I.items() if j.get("type") == "process" and str(j.get("instantiation")) == "true" and _compatible(j, machine)]
    std = [n for n in c if n.startswith(cible)]
    if std: return sorted(std, key=len)[0]
    proches = sorted(c, key=lambda n: abs(float(re.match(r"([\d.]+)mm", n).group(1)) - couche) if re.match(r"([\d.]+)mm", n) else 9)
    return proches[0] if proches else None


PREFERES = {"PLA": ["Bambu PLA Basic", "Bambu PLA Matte", "Generic PLA"], "PETG": ["Bambu PETG HF", "Bambu PETG Basic", "Generic PETG"],
            "TPU": ["Bambu TPU 95A", "Bambu TPU for AMS", "Generic TPU"], "ABS": ["Bambu ABS", "Generic ABS"], "ASA": ["Bambu ASA", "Generic ASA"],
            "PCTG": ["Generic PCTG"], "PA": ["Generic PA"], "PC": ["Bambu PC", "Generic PC"], "PVA": ["Bambu PVA", "Generic PVA"]}


def choisir_filament(machine, materiau="PLA"):
    I = index(); mat = materiau.upper().split()[0].replace("É", "E")
    c = [n for n, j in I.items() if j.get("type") == "filament" and str(j.get("instantiation")) == "true" and _compatible(j, machine)]
    for pref in PREFERES.get(mat, [f"Generic {mat}"]):
        ok = sorted((n for n in c if n.startswith(pref + " @") or n.startswith(pref + " @BBL")), key=len)
        if ok: return ok[0]
    autres = []
    for n in c:
        ft = resoudre(n).get("filament_type", [""]); ft = (ft[0] if isinstance(ft, list) else ft).upper()
        if ft == mat and not re.search(r"support|cf|gf|silk|translucent|glow|marble|sparkle|wood|galaxy|metal", n, re.I):
            autres.append(n)
    return sorted(autres, key=len)[0] if autres else None


def _txt(v):
    return [str(x) for x in v] if isinstance(v, list) else str(v)


REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modele_multi_p2s.json")   # projet enregistré PAR Bambu Studio (P2S, 2 filaments)


def _classes_reference():
    """Apprend du projet de référence (écrit par Bambu Studio) quelles clés sont : par variante de buse × filament,
    par filament, ou globales. Cette liste vient du code de Bambu Studio : elle est la même pour toutes ses machines."""
    ref = json.load(open(REFERENCE)); n = len(ref["filament_settings_id"]); nv = len(ref["printer_extruder_variant"])
    var, fil = set(), set()
    cles_filament = set().union(*[set(j) for j in index().values() if j.get("type") == "filament"]) | {
        "filament_settings_id", "filament_ids", "filament_colour", "filament_multi_colour", "filament_colour_type", "default_filament_colour",
        "filament_self_index", "filament_nozzle_map", "filament_volume_map", "extruder_ams_count", "filament_is_mixed"}
    for k, v in ref.items():
        if k not in cles_filament: continue
        if not isinstance(v, list): continue
        if len(v) == n * nv: var.add(k)
        elif len(v) == n and k not in ("filament_map",): fil.add(k)
    return ref, n, var, fil


def cfg_projet(machine, process, filaments, couleurs=None, reglages=None):
    """Réglages de projet comme Bambu Studio les écrit. filaments : noms de profils Bambu, dans l'ordre des extrudeurs du 3MF."""
    ref, n_ref, VAR, FIL = _classes_reference()
    M = resoudre(machine); P = resoudre(process); F = [resoudre(f) for f in filaments]; n = len(F)
    variantes_machine = M.get("printer_extruder_variant") or ["Direct Drive Standard"]
    cfg = {}
    # 1) global : référence, puis machine et process de Bambu (ils gagnent)
    for k, v in ref.items():
        if k not in VAR and k not in FIL: cfg[k] = v
    for d in (M, P):
        cfg.update({k: v for k, v in d.items() if k not in _META})
    # 2) par filament (et par variante de buse : les listes des profils filament ont une valeur par variante de la machine)
    nv = len(variantes_machine)
    cles_f = (set().union(*[set(f) for f in F]) - _META) | VAR | FIL
    for k in cles_f:
        if k in (M.keys() | P.keys()) and k not in VAR and k not in FIL and not k.startswith("filament_"): continue
        vals = []
        for f in F:
            v = f.get(k)
            if v is None: v = ref.get(k)
            v = list(v) if isinstance(v, list) else [v]
            if k in VAR:
                bloc = (v + [v[-1]] * nv)[:nv] if len(v) != 1 else v * nv
            elif k in FIL:
                bloc = v[:1] if v else [""]
            else:
                bloc = v
            vals += bloc
        cfg[k] = vals
    if "filament_extruder_variant" in cfg:
        cfg["filament_extruder_variant"] = [mv for _ in F for mv in variantes_machine]
    cfg["filament_self_index"] = [str(i + 1) for i in range(n) for _ in variantes_machine]
    cfg["filament_settings_id"] = list(filaments)
    cfg["filament_ids"] = [str(f.get("filament_id", "")) for f in F]
    cols = list(couleurs or [])
    defaut = ["#E2702A", "#2B2F33", "#F2F0EA", "#2C6CB0", "#5A8A3A", "#C0392B", "#8E44AD", "#F1C40F"]
    cfg["filament_colour"] = [(cols[i] if i < len(cols) and cols[i] else defaut[i % len(defaut)]) for i in range(n)]
    cfg["filament_multi_colour"] = list(cfg["filament_colour"])
    cfg["filament_colour_type"] = ["0"] * n
    cfg["default_filament_colour"] = [""] * n
    nb_ext = len(M.get("nozzle_diameter", ["0.4"]))
    cfg["filament_map"] = ["1"] * n if nb_ext == 1 else [str(1 + (i % nb_ext)) for i in range(n)]
    cfg["filament_map_mode"] = ref.get("filament_map_mode", "Auto For Flush")
    rn = ref.get("filament_nozzle_map", ["1", "0"])
    cfg["filament_nozzle_map"] = [rn[0] if i == 0 else rn[-1] for i in range(n)]
    cfg["filament_volume_map"] = ["0"] * n
    cfg["flush_volumes_matrix"] = [("0" if i == j else "280") for _ in range(nb_ext) for i in range(n) for j in range(n)]
    cfg["flush_volumes_vector"] = ["140"] * (2 * n)
    # identité de la machine : jamais celle de la référence (P2S)
    cfg["print_compatible_printers"] = list(P.get("compatible_printers") or [machine])
    cfg["default_print_profile"] = M.get("default_print_profile", process)
    cfg["default_filament_profile"] = M.get("default_filament_profile", [filaments[0]])
    if "upward_compatible_machine" in M: cfg["upward_compatible_machine"] = M["upward_compatible_machine"]
    else: cfg.pop("upward_compatible_machine", None)
    cfg.update({"printer_settings_id": machine, "print_settings_id": process, "from": "project", "name": "project_settings",
                "printer_model": M.get("printer_model", ""), "printer_variant": M.get("printer_variant", cfg.get("printer_variant", "0.4"))})
    if reglages: cfg.update(reglages)
    return compatible_orca({k: _txt(v) for k, v in cfg.items() if v is not None})


# --- UN SEUL 3MF lisible par Bambu Studio ET OrcaSlicer -----------------------------------------------------------------
# OrcaSlicer (CLI et appli) refuse un projet dont une valeur numérique sort de SA plage (PrintConfig.cpp, validate() :
# « Param values in 3mf/config error : raft_first_layer_expansion: -1 not in range [0, …] », code -18). Bambu Studio, lui,
# écrit -1 (= « auto ») dans plusieurs clés. orca_plages.json = min/max de chaque option, extraits du code source
# d'OrcaSlicer v2.4.2 (src/libslic3r/PrintConfig.cpp, 397 options). On ramène chaque valeur hors plage à la borne la
# plus proche : Bambu Studio accepte ces valeurs aussi (vérifié en tranchant avec les deux CLI, tests/t_orca_bambu.py).
# Autre refus d'Orca : « Unsupported 3MF version » (code -24) quand l'en-tête Application du 3MF est BambuStudio-02.08+ et
# Orca 2.4 (OrcaSlicer.cpp : majeur.mineur du fichier > celui d'Orca). L'en-tête écrit par LC3D (BambuStudio-02.04.00.70,
# lc3d.py exporter_3mf_bambu) passe : ne JAMAIS le monter au-dessus de 02.04 (ENTETE_MAX_ORCA).
ENTETE_MAX_ORCA = "02.04.00.70"
_PLAGES_ORCA = None


def plages_orca():
    global _PLAGES_ORCA
    if _PLAGES_ORCA is None:
        try:
            _PLAGES_ORCA = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "orca_plages.json")))
        except Exception:
            _PLAGES_ORCA = {}
    return _PLAGES_ORCA


def _hors_plage(x, pl):
    try:
        f = float(str(x).strip().rstrip("%"))
    except ValueError:
        return None
    lo, hi = pl.get("min"), pl.get("max")
    if lo is not None and ((lo == 0 and f < 0) or f < lo - 1e-4): return lo
    if hi is not None and f > hi + 1e-4: return hi
    return None


def _fmt(b):
    return str(int(b)) if float(b).is_integer() else str(b)


def compatible_orca(cfg, journal=None):
    """Ramène dans la plage d'OrcaSlicer toute valeur numérique qu'il refuserait (ex. -1 « auto » de Bambu Studio).
    journal : liste où noter (clé, avant, après). Retourne cfg (modifié en place)."""
    P = plages_orca()
    for k, v in list(cfg.items()):
        pl = P.get(k)
        if not pl: continue
        if isinstance(v, list):
            nv = []
            for x in v:
                b = _hors_plage(x, pl); nv.append(_fmt(b) if b is not None else x)
            if nv != v:
                if journal is not None: journal.append((k, v, nv))
                cfg[k] = nv
        else:
            b = _hors_plage(v, pl)
            if b is not None:
                if journal is not None: journal.append((k, v, _fmt(b)))
                cfg[k] = _fmt(b)
    return cfg


def valeurs_refusees_orca(cfg):
    """Liste des (clé, valeur) qu'OrcaSlicer refuserait. Vide = OK."""
    P = plages_orca(); out = []
    for k, v in cfg.items():
        if k in P:
            for x in (v if isinstance(v, list) else [v]):
                if _hors_plage(x, P[k]) is not None: out.append((k, x)); break
    return out


def rendre_compatible_orca(chemin_3mf, sortie=None):
    """Corrige un 3MF déjà écrit (même par Bambu Studio) pour qu'Orca l'ouvre : valeurs hors plage ramenées dans la plage
    et en-tête Application ≤ 02.04 (sinon « Unsupported 3MF version »). Retourne la liste des corrections."""
    import zipfile
    sortie = sortie or chemin_3mf; journal = []
    with zipfile.ZipFile(chemin_3mf) as zi:
        items = [(i, zi.read(i.filename)) for i in zi.infolist()]
    out = []
    for i, d in items:
        if i.filename == "Metadata/project_settings.config":
            c = json.loads(d); compatible_orca(c, journal); d = json.dumps(c, ensure_ascii=False, indent=1).encode()
        elif i.filename == "3D/3dmodel.model":
            t = d.decode("utf-8", "ignore")
            m = re.search(r'<metadata name="Application">BambuStudio-(\d+)\.(\d+)[^<]*</metadata>', t)
            if m and (int(m.group(1)), int(m.group(2))) > (2, 4):
                t = t.replace(m.group(0), f'<metadata name="Application">BambuStudio-{ENTETE_MAX_ORCA}</metadata>')
                journal.append(("Application", m.group(0), ENTETE_MAX_ORCA)); d = t.encode()
        out.append((i.filename, d))
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as zo:
        for n, d in out: zo.writestr(n, d)
    return journal


def trancher_orca_cli(chemin_3mf, delai=600, app=None):
    """Tranche avec OrcaSlicer en ligne de commande (sans --allow-newer-file : comme un utilisateur qui ouvre le fichier)."""
    app = app or os.environ.get("LC3D_ORCA", os.path.expanduser("~/.lc3d/orcaslicer/squashfs-root/AppRun"))
    if not os.path.exists(app): return dict(ok=None, erreur="OrcaSlicer non installé")
    out = tempfile.mkdtemp()
    try:
        p = subprocess.run([app, "--slice", "0", "--outputdir", out, chemin_3mf], capture_output=True, text=True, timeout=delai,
                           env=dict(os.environ, XDG_RUNTIME_DIR=tempfile.gettempdir()))
        g = glob.glob(os.path.join(out, "*.gcode"))
        if p.returncode != 0 or not g:
            txt = (p.stdout or "") + (p.stderr or ""); res = {}
            try: res = json.load(open(os.path.join(out, "result.json")))
            except Exception: pass
            lignes = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("[")]
            return dict(ok=False, code=p.returncode, erreur=(res.get("error_string") or " / ".join(lignes[-3:]))[:400])
        t = open(g[0], errors="ignore").read()
        gr = re.search(r"filament used \[g\] = ([\d.]+)", t) or re.search(r"total filament weight \[g\] : ([\d.]+)", t)
        tm = re.search(r"total estimated time: ([^;\n]+)", t) or re.search(r"estimated printing time \(normal mode\) = ([^\n]+)", t)
        return dict(ok=True, grammes=float(gr.group(1)) if gr else None, temps=tm.group(1).strip() if tm else None)
    except subprocess.TimeoutExpired:
        return dict(ok=False, erreur="OrcaSlicer : délai dépassé")
    finally:
        shutil.rmtree(out, ignore_errors=True)


def trancher_les_deux(chemin_3mf):
    """Le même fichier tranché par Bambu Studio ET OrcaSlicer : dict(bambu=..., orca=..., ok=bool)."""
    b = trancher(chemin_3mf) if disponible() else dict(ok=None, erreur="Bambu Studio non installé")
    b.pop("gcode_cfg", None); o = trancher_orca_cli(chemin_3mf)
    return dict(bambu=b, orca=o, ok=bool(b.get("ok")) and bool(o.get("ok")))


def trancher(chemin_3mf, delai=900):
    """Tranche avec Bambu Studio (ligne de commande). dict(ok, erreur, grammes, temps, outils, gcode_cfg)."""
    out = tempfile.mkdtemp()
    try:
        p = subprocess.run([APP, "--slice", "0", "--outputdir", out, chemin_3mf], capture_output=True, text=True, timeout=delai,
                           env=dict(os.environ, XDG_RUNTIME_DIR=tempfile.gettempdir()))
        res = {}
        try: res = json.load(open(os.path.join(out, "result.json")))
        except Exception: pass
        g = glob.glob(os.path.join(out, "*.gcode"))
        if p.returncode != 0 or not g:
            return dict(ok=False, erreur=res.get("error_string") or f"Bambu Studio s'est arrêté (code {p.returncode})")
        t = open(g[0], errors="ignore").read()
        w = re.findall(r"total filament weight \[g\] : ([\d.]+)", t)
        tm = re.findall(r"total estimated time: ([^;\n]+)", t)
        outils = sorted(set(re.findall(r"^M620 S(\d+)A", t, re.M)) - {"255"})
        cfg = dict(re.findall(r"^; (\w+) = (.*)$", t, re.M))
        av = "; ".join(x.get("warning_message", "") for x in res.get("sliced_plates", []) if x.get("warning_message"))
        return dict(ok=True, grammes=float(w[0]) if w else None, temps=tm[0].strip() if tm else None, outils=outils, gcode_cfg=cfg, avertissement=av or None)
    except subprocess.TimeoutExpired:
        return dict(ok=False, erreur="Bambu Studio : délai dépassé")
    finally:
        shutil.rmtree(out, ignore_errors=True)
