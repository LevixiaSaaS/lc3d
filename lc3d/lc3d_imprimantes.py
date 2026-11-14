"""LC3D — contrôle de SES imprimantes, sur son réseau local (à lancer sur SON ordi, pas dans le nuage).

  python lc3d_imprimantes.py etat                    # les deux imprimantes : état, températures, progression
  python lc3d_imprimantes.py u1 etat|pause|reprendre|annuler
  python lc3d_imprimantes.py u1 envoyer piece.gcode [--imprimer --oui]
  python lc3d_imprimantes.py p2s etat|pause|reprendre|annuler|lumiere on|off
  python lc3d_imprimantes.py p2s trancher piece.3mf          # Bambu Studio en ligne de commande -> 3MF tranché
  python lc3d_imprimantes.py p2s envoyer piece_tranchee.3mf [--imprimer --oui]

Configuration : ~/.lc3d/imprimantes.json, que l'utilisateur remplit LUI-MÊME (le code d'accès ne passe jamais par Claude) :
  {"u1":  {"ip": "192.168.x.x", "port": 80},
   "p2s": {"ip": "192.168.x.x", "serie": "N° de série (écran > Réglages > Appareil)", "code_acces": "code LAN (écran > Réglages > Réseau)"},
   "bambu_studio": "C:/Program Files/Bambu Studio/bambu-studio.exe"}
P2S : activer « LAN only » + « Mode développeur » sur l'écran de l'imprimante (sinon Bambu bloque les logiciels tiers).

SÉCURITÉ : démarrer une impression ou chauffer exige --oui (Claude demande toujours l'accord de l'utilisateur dans le chat avant).
Rien ici n'a pu être testé sur les vraies machines depuis le nuage : premier essai = « etat » seulement.
"""
import json, os, ssl, sys, time, socket, ftplib, subprocess, urllib.request, urllib.parse

CONFIG = os.path.join(os.path.expanduser("~"), ".lc3d", "imprimantes.json")


def conf():
    try:
        return json.load(open(CONFIG))
    except Exception:
        sys.exit(f"Créer d'abord {CONFIG} (voir l'aide en haut du fichier).")


# ---------------------------------------------------------------- Snapmaker U1 (Klipper / Moonraker, API REST)
def _u1_url(c, chemin):
    return f"http://{c['ip']}:{c.get('port', 80)}{chemin}"


def _u1_get(c, chemin):
    with urllib.request.urlopen(_u1_url(c, chemin), timeout=8) as r:
        return json.load(r)


def _u1_post(c, chemin, data=b"", entetes=None):
    req = urllib.request.Request(_u1_url(c, chemin), data=data, method="POST", headers=entetes or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def u1_etat(c):
    q = "/printer/objects/query?print_stats&extruder&heater_bed&display_status&virtual_sdcard"
    s = _u1_get(c, q)["result"]["status"]
    ps = s.get("print_stats", {})
    return dict(machine="Snapmaker U1", etat=ps.get("state"), fichier=ps.get("filename"),
                progression_pct=round(100 * (s.get("virtual_sdcard", {}).get("progress") or 0), 1),
                buse=f"{s.get('extruder', {}).get('temperature', 0):.0f}/{s.get('extruder', {}).get('target', 0):.0f} °C",
                plateau=f"{s.get('heater_bed', {}).get('temperature', 0):.0f}/{s.get('heater_bed', {}).get('target', 0):.0f} °C",
                duree_min=round((ps.get("print_duration") or 0) / 60, 1))


def u1_commande(c, quoi):
    chemins = {"pause": "/printer/print/pause", "reprendre": "/printer/print/resume", "annuler": "/printer/print/cancel"}
    return _u1_post(c, chemins[quoi])


def u1_envoyer(c, fichier, imprimer=False):
    limite = "----lc3d" + str(int(time.time()))
    nom = os.path.basename(fichier)
    corps = (f"--{limite}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{nom}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + open(fichier, "rb").read() + f"\r\n--{limite}--\r\n".encode()
    r = _u1_post(c, "/server/files/upload", corps, {"Content-Type": f"multipart/form-data; boundary={limite}"})
    if imprimer:
        _u1_post(c, "/printer/print/start?filename=" + urllib.parse.quote(nom))
    return r


# ---------------------------------------------------------------- Bambu Lab P2S (LAN : MQTT TLS 8883 + FTPS 990)
def _p2s_mqtt(c, message=None, attendre_rapport=True, delai=8):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("Installer paho-mqtt : pip install paho-mqtt")
    rapport = {}
    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client()
    cl.username_pw_set("bblp", c["code_acces"])
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE   # certificat auto-signé de l'imprimante (réseau local)
    cl.tls_set_context(ctx)
    sujet_r, sujet_q = f"device/{c['serie']}/report", f"device/{c['serie']}/request"

    def sur_connexion(client, *a):
        client.subscribe(sujet_r)
        client.publish(sujet_q, json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))
        if message: client.publish(sujet_q, json.dumps(message))

    def sur_message(client, userdata, msg):
        try:
            d = json.loads(msg.payload)
            if "print" in d: rapport.update(d["print"])
        except Exception:
            pass
    cl.on_connect = sur_connexion; cl.on_message = sur_message
    cl.connect(c["ip"], 8883, 30); cl.loop_start()
    fin = time.time() + delai
    while time.time() < fin and (attendre_rapport and "gcode_state" not in rapport):
        time.sleep(0.2)
    time.sleep(0.5); cl.loop_stop(); cl.disconnect()
    return rapport


def p2s_etat(c):
    r = _p2s_mqtt(c)
    return dict(machine="Bambu Lab P2S", etat=r.get("gcode_state"), fichier=r.get("subtask_name"), progression_pct=r.get("mc_percent"),
                buse=f"{r.get('nozzle_temper', 0):.0f}/{r.get('nozzle_target_temper', 0):.0f} °C", plateau=f"{r.get('bed_temper', 0):.0f}/{r.get('bed_target_temper', 0):.0f} °C",
                reste_min=r.get("mc_remaining_time"), couche=f"{r.get('layer_num')}/{r.get('total_layer_num')}", erreur=r.get("print_error") or None)


def p2s_commande(c, quoi, valeur=None):
    if quoi in ("pause", "reprendre", "annuler"):
        cmd = {"pause": "pause", "reprendre": "resume", "annuler": "stop"}[quoi]
        return _p2s_mqtt(c, {"print": {"sequence_id": "1", "command": cmd}}, attendre_rapport=False, delai=3)
    if quoi == "lumiere":
        return _p2s_mqtt(c, {"system": {"sequence_id": "1", "command": "ledctrl", "led_node": "chamber_light", "led_mode": "on" if valeur == "on" else "off",
                                        "led_on_time": 500, "led_off_time": 500, "loop_times": 0, "interval_time": 0}}, attendre_rapport=False, delai=3)


class _FTPS_implicite(ftplib.FTP_TLS):
    """FTPS implicite (port 990) utilisé par les imprimantes Bambu."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, valeur):
        if valeur is not None and not isinstance(valeur, ssl.SSLSocket):
            valeur = self.context.wrap_socket(valeur)
        self._sock = valeur

    def ntransfercmd(self, cmd, rest=None):   # réutiliser la session TLS pour le canal de données
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def p2s_envoyer(c, fichier_3mf_tranche, imprimer=False, plaque=1, ams=True):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    f = _FTPS_implicite(context=ctx); f.connect(c["ip"], 990, timeout=30); f.login("bblp", c["code_acces"]); f.prot_p()
    nom = os.path.basename(fichier_3mf_tranche)
    with open(fichier_3mf_tranche, "rb") as fh: f.storbinary(f"STOR {nom}", fh)
    f.quit()
    if not imprimer: return dict(envoye=nom)
    msg = {"print": {"sequence_id": "2", "command": "project_file", "param": f"Metadata/plate_{plaque}.gcode", "subtask_name": nom,
                     "url": f"ftp:///{nom}", "bed_type": "auto", "timelapse": False, "bed_leveling": True, "flow_cali": True,
                     "vibration_cali": True, "layer_inspect": True, "use_ams": bool(ams), "ams_mapping": [0]}}
    _p2s_mqtt(c, msg, attendre_rapport=False, delai=4)
    return dict(envoye=nom, impression="demandée", plaque=plaque)


def p2s_trancher(c, entree_3mf, sortie=None):
    """Tranche le 3MF LC3D avec Bambu Studio (réglages du projet) -> 3MF prêt à imprimer (avec le G-code dedans). Vérifie aussi que
    Bambu Studio ouvre bien le fichier LC3D (preuve que les réglages embarqués sont acceptés)."""
    exe = c.get("bambu_studio") or "bambu-studio"
    sortie = sortie or os.path.splitext(entree_3mf)[0] + "_tranche.3mf"
    r = subprocess.run([exe, "--slice", "0", "--export-3mf", sortie, entree_3mf], capture_output=True, text=True, timeout=1800)
    return dict(ok=os.path.exists(sortie), sortie=sortie, journal=(r.stdout + r.stderr)[-1500:])


def main(a):
    if not a: print(__doc__); return
    c = conf()
    oui = "--oui" in a; imprimer = "--imprimer" in a
    a = [x for x in a if not x.startswith("--")]
    if a[0] == "etat":
        out = {}
        if "u1" in c:
            try: out["u1"] = u1_etat(c["u1"])
            except Exception as e: out["u1"] = f"injoignable : {e}"
        if "p2s" in c:
            try: out["p2s"] = p2s_etat(c["p2s"])
            except Exception as e: out["p2s"] = f"injoignable : {e}"
        print(json.dumps(out, ensure_ascii=False, indent=1)); return
    machine, quoi = a[0], a[1]
    if (imprimer or quoi in ("chauffer",)) and not oui:
        sys.exit("Refusé : démarrer une impression demande --oui (accord de l'utilisateur dans le chat).")
    if machine == "u1":
        cu = c["u1"]
        r = u1_etat(cu) if quoi == "etat" else (u1_envoyer(cu, a[2], imprimer) if quoi == "envoyer" else u1_commande(cu, quoi))
    elif machine == "p2s":
        cp = c["p2s"]
        if quoi == "etat": r = p2s_etat(cp)
        elif quoi == "trancher": r = p2s_trancher(c, a[2])
        elif quoi == "envoyer": r = p2s_envoyer(cp, a[2], imprimer)
        else: r = p2s_commande(cp, quoi, a[2] if len(a) > 2 else None)
    else:
        sys.exit("machine : u1 ou p2s")
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
