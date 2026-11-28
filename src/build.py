"""Assemble vault-planner.html from template.html + rules.js + the STL measurement table.

usage: python3 -I build.py [--public] <foot.tsv> <out.html> [previews/index.tsv]
--public: the version for sharing. Leaves out the Mac-only VaultPrint helper and Terminal script, and this Mac's paths.
Leave out previews/index.tsv to build without part pictures.
foot.tsv columns: path, bbox dx, dy, dz, volume mm3, footprint a, footprint b, angle (the Oct 2026 download;
src/stl-measurements-2611.tsv has the Nov 2026 files that are new or changed shape)
index.tsv columns: path, sprite sheet number, cell in sheet (from the thumbnail packer)
"""
import json
import pathlib
import re
import sys

here = pathlib.Path(__file__).resolve().parent
public = "--public" in sys.argv
if public:
    sys.argv.remove("--public")
foot, out = sys.argv[1], sys.argv[2]
thumbs, thumbs2611 = {}, {}
if len(sys.argv) > 3:
    for line in pathlib.Path(sys.argv[3]).read_text().strip().split("\n"):
        path, sheet, cell = line.split("\t")
        thumbs[path] = [int(sheet), int(cell)]
    # Pictures of the Nov 2026 files that are new or changed shape (previews/index-2611.tsv, from src/render-sheet.js)
    i2611 = pathlib.Path(sys.argv[3]).with_name("index-2611.tsv")
    if i2611.exists():
        for line in i2611.read_text().strip().split("\n"):
            path, sheet, cell = line.split("\t")
            thumbs2611[path] = [int(sheet), int(cell)]

# Parts Bambu Studio warns about when sliced as exported without supports ("floating cantilever" and so on),
# from slicing every STL on its own: path, Bambu's warning (empty when it's happy)
needs = set()
audit = here / "bambu-support-audit.tsv"
if audit.exists():
    for line in audit.read_text().strip().split("\n"):
        path, _, msg = line.partition("\t")
        if "enable support" in msg:
            needs.add(path)

# How far Bambu's supports reach past each part at any layer, from slicing it alone with the planner's settings
# (src/bambu-reach.tsv: path, printer, support reach, auto brim reach, skirt reach, warning). The packer keeps
# neighbours that far away, since supports, unlike brims, aren't trimmed around other parts.
reach = {}
rf = here / "bambu-reach.tsv"
if rf.exists():
    for line in rf.read_text().strip().split("\n"):
        c = line.split("\t")
        if len(c) > 2 and c[2]:
            reach[c[0]] = round(float(c[2]), 1)

# USSA releases: every STL each download has, with its size in bytes (src/ussa-<release>-paths.tsv, from src/ussa-paths.py)
sizes = {r: dict((l.split("\t")[0], int(l.split("\t")[1])) for l in (here / f"ussa-{r}-paths.tsv").read_text().strip().split("\n")) for r in ("2610", "2611")}

# Parts laid on another face than exported, because they hang out over air as exported (src/lay-flat.tsv): path ->
# (turn, the part measured that way, the file size it was measured on). The picture still shows the file as exported.
lay = {}
for line in (here / "lay-flat.tsv").read_text().splitlines():
    if line and not line.startswith("#"):
        c = line.split("\t")
        lay[c[0]] = (c[1], "\t".join([c[0]] + c[2:9]), int(c[9]))

def row(line, pics=True, pictures=None, size=None):
    turn = None
    if line.split("\t")[0] in lay and lay[line.split("\t")[0]][2] == size:
        turn, line = lay[line.split("\t")[0]][0], lay[line.split("\t")[0]][1]
    p, bx, by, bz, vol, fa, fb, ang = line.split("\t")
    a, b = sorted((float(fa), float(fb)), reverse=True)
    # Round parts (keys, knobs, disks): turning them doesn't shrink their footprint, so keep them as exported
    if float(bx) * float(by) <= float(fa) * float(fb) * 1.03:
        a, b, ang = *sorted((float(bx), float(by)), reverse=True), "0"
    r = [p, a, b, float(bz), int(float(vol)), float(ang)] + ((pictures or thumbs).get(p, [0, 0]) if pics else [0, 0]) + [1 if p in needs else 0, reach.get(p, -1), float(bx), float(by)]
    # laid flat: Bambu's warning and support reach were measured as exported, so they don't apply
    return r if not turn else r[:8] + [0, -1] + r[10:] + [size, turn]

rows = [(lambda r, z: r if len(r) > 12 else r + [z])(row(line, size=sizes["2610"][line.split("\t")[0]]), sizes["2610"][line.split("\t")[0]]) for line in pathlib.Path(foot).read_text().strip().split("\n")]
catalog = "window.VAULT_FILES=" + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + ";"
# The Nov 2026 download (Vault Archive_18.11.2026): files measured again where they are new or changed shape
# (src/stl-measurements-2611.tsv), every file's size, and the Oct 2026 files it no longer has. A changed part keeps its old
# picture only if it's still exported at the same angle (pictures show the part as exported); its support reach is reused,
# since the support rules didn't change.
old = {r[0]: r for r in rows}
r2611 = []
for line in (here / "stl-measurements-2611.tsv").read_text().strip().split("\n"):
    p = line.split("\t")[0]
    z = sizes["2611"][p]
    r = row(line, pictures=thumbs2611, size=z) if p in thumbs2611 else row(line, pics=p in old and abs(old[p][5] - float(line.split("\t")[7])) < 1, size=z)
    r2611.append(r if len(r) > 12 else r + [z])
rel = {"rows": r2611, "size": {p: s for p, s in sizes["2611"].items() if sizes["2610"].get(p) != s},
       "drop": sorted(p for p in sizes["2610"] if p not in sizes["2611"])}
catalog += "window.VAULT_2611=" + json.dumps(rel, ensure_ascii=False, separators=(",", ":")) + ";"
# Bambu Studio's own project settings per printer (src/bambu-settings/<printer id>.json, each saved by Bambu Studio itself).
# Keys every printer shares are stored once.
sets = {f.stem: json.loads(f.read_text()) for f in sorted((here / "bambu-settings").glob("*.json"))}
base = {k: v for k, v in next(iter(sets.values()), {}).items() if all(k in d and d[k] == v for d in sets.values())}
bambu = {"base": base, "per": {i: {k: v for k, v in d.items() if k not in base} for i, d in sets.items()}}
# Settings with one entry per filament (src/bambu-filament-keys.json, from src/bambu-filament-keys.py), so the page can
# give each plate colour its own filament
bambu["perFilament"] = json.loads((here / "bambu-filament-keys.json").read_text())
catalog += "window.BAMBU_SETTINGS=" + json.dumps(bambu, ensure_ascii=False, separators=(",", ":")) + ";"
# Bed sizes for the "My printer isn't listed" lookup (src/printer-beds.tsv, from OrcaSlicer's profiles by src/orca-beds.py)
beds = [l.split("\t") for l in (here / "printer-beds.tsv").read_text().splitlines() if l and not l.startswith("#")]
catalog += "window.PRINTER_BEDS=" + json.dumps([[b, m, int(w), int(d), int(h)] for b, m, w, d, h in beds], ensure_ascii=False, separators=(",", ":")) + ";"
html = (here / "template.html").read_text()
if public:
    catalog += "window.VAULT_PUBLIC=true;"
    html = re.sub(r'<script type="text/plain" id="py3mf">.*?</script>\n', "", html, flags=re.S)
    html = re.sub(r"const SRC_DEFAULT = '[^']*/", "const SRC_DEFAULT = '", html)
    # The VaultPrint helper and Terminal script only work on the author's Mac (the public template has them removed already)
    html = re.sub(r"  /\*MAC\*/.*?/\*END MAC\*/", "  const macPanel = () => '', bindMac = () => {};", html, flags=re.S)
# What's new (header button opens it): src/public/CHANGELOG.md, every date
def changelog_html():
    import html as h
    days, cur = [], None
    for line in (here / "public" / "CHANGELOG.md").read_text().splitlines():
        if line.startswith("## "):
            cur = [line[3:].strip(), []]; days.append(cur)
        elif line.startswith("- ") and cur:
            t = h.escape(line[2:].strip(), quote=False)
            t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
            t = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
            cur[1].append(f"<li>{t}</li>")
    day = lambda d: f'<h3>{d[0]}</h3><ul>{"".join(d[1])}</ul>'
    return "".join(day(d) for d in days)
html = html.replace("<!--CHANGELOG-->", changelog_html())
html = html.replace("/*CATALOG*/", catalog).replace("/*RULES*/", (here / "rules.js").read_text())
pathlib.Path(out).write_text(html)
print(f"{len(rows)} files -> {out} ({len(html) // 1024} KB)")
