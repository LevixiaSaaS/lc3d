#!/usr/bin/env bash
# LC3D — installation (Linux / macOS / WSL). Tout est gratuit.
set -e
PY=${PY:-python3.12}
$PY -m venv ~/cadenv
. ~/cadenv/bin/activate
pip install -q -r "$(dirname "$0")/requirements.txt"
python -c "import cadquery, build123d, bd_warehouse, trimesh, manifold3d, skfem, gmsh; print('LC3D : bibliothèques OK')"
if [ "$(uname)" = "Linux" ]; then
  (command -v apt-get >/dev/null && sudo apt-get install -y --no-install-recommends libwebkit2gtk-4.1-0) || true
  (command -v apt-get >/dev/null && sudo apt-get install -y --no-install-recommends openscad xvfb) || true
  python "$(dirname "$0")/lc3d/lc3d.py" orca-installer || echo "OrcaSlicer non installé : le tranchage de contrôle sera estimé."
  python "$(dirname "$0")/lc3d/lc3d.py" bambu-installer || echo "Bambu Studio non installé : les 3MF Bambu seront tranchés par OrcaSlicer."
  python "$(dirname "$0")/lc3d/lc3d.py" freecad-installer || echo "FreeCAD non installé : l'export FreeCAD ne sera pas vérifié."
fi
echo "Prêt. Lance : python lc3d/lc3d.py run exemples/Boite_couvercle.py"
