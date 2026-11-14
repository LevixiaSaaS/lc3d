"""Robot du catalogue LC3D (GitHub Actions).

- `traiter <event.json>` : lit une issue (preuve / signalement), vérifie la photo, l'ajoute aux registres,
  répond dans l'issue (texte écrit dans reponse.md) et recalcule le catalogue.
- `recalculer` : refait catalogue/catalogue.json à partir des fiches, preuves et signalements.

Règles de statut (identiques à catalogue_lc3d.py) :
  calculé → imprimé N fois (photo obligatoire) → prouvé (communauté) : ≥ 5 réussites avec photo, ≥ 3 personnes,
  ≥ 90 % de réussite.  Un signalement ouvert avec photo marque la fiche « signalé ».  Taux < 70 % sur ≥ 3 essais :
  « à revoir ».  Une personne = un compte GitHub; seules ses 3 dernières preuves par composant comptent.
"""
import json, os, re, sys, time

ICI = os.path.dirname(os.path.abspath(__file__))
CAT = os.path.join(ICI, "..", "catalogue")
F_FICHES, F_PREUVES, F_SIGN, F_SORTIE = (os.path.join(CAT, f) for f in ("fiches.json", "preuves.json", "signalements.json", "catalogue.json"))


def lire(f, defaut):
    try: return json.load(open(f))
    except Exception: return defaut


def ecrire(f, d):
    json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)


def champs_formulaire(corps):
    """Les formulaires GitHub donnent « ### Libellé\n\nvaleur ». """
    out = {}
    for bloc in re.split(r"^### ", corps or "", flags=re.M)[1:]:
        titre, _, val = bloc.partition("\n")
        out[titre.strip()] = val.strip()
    return out


def photos(texte):
    return re.findall(r"(https://(?:github\.com/user-attachments/assets|user-images\.githubusercontent\.com|private-user-images\.githubusercontent\.com)/[^\s)\"']+)", texte or "")


def numero(txt):
    m = re.search(r"\d+", txt or ""); return int(m.group()) if m else None


def traiter(evenement):
    ev = json.load(open(evenement)); iss = ev["issue"]; labels = {l["name"] for l in iss.get("labels", [])}
    f = champs_formulaire(iss.get("body")); qui = iss["user"]["login"]; num = numero(f.get("Numéro du composant"))
    fiches = {x["num"]: x for x in lire(F_FICHES, [])}
    rep = []
    if num not in fiches:
        rep.append(f"Le composant n° {num} n'existe pas dans le catalogue. Vérifie le numéro (ex. 1 pour « Clip n° 1 »).")
        return fin(rep, ok=False)
    ph = photos(f.get("Photo de la pièce imprimée") or f.get("Photo du problème") or iss.get("body"))
    if "preuve" in labels:
        res = f.get("Résultat", "")
        P = lire(F_PREUVES, [])
        P = [p for p in P if p.get("issue") != iss["number"]]          # une issue modifiée remplace sa preuve
        P.append(dict(num=num, version=numero(f.get("Version")) or 1, qui=qui, date=iss["created_at"][:10], issue=iss["number"],
                      reussi=not res.startswith("Raté"), ajuste=res.startswith("Réussi après"), imprimante=f.get("Imprimante", "").strip(),
                      filament=f.get("Filament (matière et marque)", "").strip(), note=numero(f.get("Ta note")), photo=ph[0] if ph else None,
                      commentaire=(f.get("Commentaire (facultatif)") or "")[:500]))
        ecrire(F_PREUVES, P)
        if not ph:
            rep.append("⚠️ **Photo manquante** : ta preuve est enregistrée mais ne compte pas tant qu'il n'y a pas de photo. Modifie l'issue pour l'ajouter.")
        else:
            rep.append(f"✅ Merci @{qui} ! Ta preuve pour le n° {num} est comptée.")
    elif "signalement" in labels:
        S = lire(F_SIGN, [])
        S = [s for s in S if s.get("issue") != iss["number"]]
        S.append(dict(num=num, version=numero(f.get("Version")) or 1, qui=qui, date=iss["created_at"][:10], issue=iss["number"],
                      probleme=f.get("Le problème"), imprimante=f.get("Imprimante et filament"), photo=ph[0] if ph else None,
                      details=(f.get("Ce qui s'est passé") or "")[:800], ouvert=iss.get("state") == "open"))
        ecrire(F_SIGN, S)
        rep.append("Signalement reçu : le composant est marqué « signalé » dans le catalogue jusqu'à ce qu'il soit corrigé." if ph
                   else "⚠️ **Photo manquante** : ajoute une photo du problème pour que le signalement compte.")
    recalculer()
    st = next(c for c in lire(F_SORTIE, {"composants": []})["composants"] if c["num"] == num)
    rep.append(f"\nStatut actuel du n° {num} : **{st['statut']}** — {st['reussites']} réussite(s) sur {st['essais']} essai(s), {st['personnes']} personne(s).")
    return fin(rep, ok=True)


def fin(rep, ok):
    open("reponse.md", "w").write("\n".join(rep)); print("\n".join(rep)); return 0 if ok else 1


def recalculer():
    fiches = lire(F_FICHES, []); P = lire(F_PREUVES, []); S = lire(F_SIGN, [])
    out = []
    for fc in fiches:
        n = fc["num"]
        mes = [p for p in P if p["num"] == n and p.get("photo")]
        # une personne : ses 3 dernières preuves seulement
        par_qui = {}
        for p in sorted(mes, key=lambda p: p["date"]): par_qui.setdefault(p["qui"], []).append(p)
        comptees = [p for L in par_qui.values() for p in L[-3:]]
        ok = [p for p in comptees if p["reussi"]]
        taux = len(ok) / len(comptees) if comptees else None
        personnes = len({p["qui"] for p in ok})
        notes = [p["note"] for p in comptees if p.get("note")]
        machines = {}
        for p in comptees:
            m = machines.setdefault(p["imprimante"] or "?", dict(reussites=0, essais=0)); m["essais"] += 1; m["reussites"] += p["reussi"]
        sig = [s for s in S if s["num"] == n and s.get("ouvert") and s.get("photo")]
        if len(ok) >= 5 and personnes >= 3 and taux >= 0.9: statut = "prouvé"
        elif comptees and len(comptees) >= 3 and taux < 0.7: statut = "à revoir"
        elif ok: statut = "imprimé"
        else: statut = "calculé"
        out.append(dict(fc, statut=statut, signale=bool(sig), signalements=[{k: s[k] for k in ("probleme", "imprimante", "photo", "issue", "date")} for s in sig],
                        reussites=len(ok), essais=len(comptees), taux=None if taux is None else round(100 * taux), personnes=personnes,
                        note=None if not notes else round(sum(notes) / len(notes), 1), nb_notes=len(notes), par_imprimante=machines,
                        photos=[dict(url=p["photo"], qui=p["qui"], imprimante=p["imprimante"], reussi=p["reussi"]) for p in sorted(comptees, key=lambda p: p["date"], reverse=True)[:8]]))
    ecrire(F_SORTIE, dict(maj=time.strftime("%Y-%m-%d %H:%M"), composants=out,
                          totaux=dict(composants=len(out), preuves=sum(c["essais"] for c in out), prouves=sum(c["statut"] == "prouvé" for c in out),
                                      signales=sum(c["signale"] for c in out))))


if __name__ == "__main__":
    if sys.argv[1] == "traiter": sys.exit(traiter(sys.argv[2]))
    recalculer()
