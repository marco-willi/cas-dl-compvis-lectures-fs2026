"""Download a configurable subset of Snapshot Serengeti (SER) camera-trap images.

First run (~1 min):
  - Downloads the Snapshot Safari 2024 metadata ZIP from LILA (~60 MB)
  - Downloads the MegaDetector results ZIP (~42 MB)
  - Builds a deduplicated, MD-filtered catalogue and caches it as a CSV
  - Downloads your selected images from Azure blob storage

Subsequent runs:
  - Loads the cached catalogue CSV (< 1 s) and jumps straight to downloading.
  - Image downloads are resumable — already-present files are skipped.

Requirements: pip install pandas requests Pillow

Available classes
-----------------
Run once and read the catalogue printed at startup.
Typical: buffalo, elephant, gazellegrants, gazellethomsons, hartebeest,
         impala, warthog, wildebeestblue, zebraplains, empty

Note on the 'empty' class
--------------------------
The catalogue contains ~644k empty frames vs. ~153k animal frames.
If you include 'empty', always set CLASS_COUNTS explicitly — proportional
sampling will otherwise produce a dataset that is ~80% empty.

Helper functions (call after the script runs, or import individually)
----------------------------------------------------------------------
  make_splits(df)           → (train_df, val_df, test_df)
                              Sequence-safe stratified split; no sequence
                              leaks across splits.
  compute_class_weights(df) → dict[label, weight]
                              Inverse-frequency weights; pass to
                              nn.CrossEntropyLoss(weight=...).
"""

from __future__ import annotations

import ast
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
from PIL import Image

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("data/serengeti")  # images saved as  <label>/<filename>.jpg
CACHE_DIR  = Path(".cache/ser")      # ZIPs + catalogue cached here — keep between runs

# Which classes to include.  None → all classes in the catalogue.
CLASSES: list[str] | None = None
# e.g. CLASSES = ["zebraplains", "elephant", "wildebeestblue"]

# Total image cap, distributed proportionally across selected classes.
# None → no limit (download everything available for selected classes).
MAX_IMAGES: int | None = 3_000

# Per-class exact counts — overrides MAX_IMAGES when set.
# Classes absent from the catalogue are silently ignored.
CLASS_COUNTS: dict[str, int] | None = None
# e.g. CLASS_COUNTS = {"zebraplains": 1000, "elephant": 800, "wildebeestblue": 600}

# Minimum MegaDetector animal confidence to include an image.
# 0.8 = strict (default)    0.5 = looser (more images, noisier labels)
MD_CONF_THRESHOLD: float = 0.8

# Crop each image to the MegaDetector bounding box before saving (10 % padding).
# False = full camera-trap frame    True = tight animal crop
CROP: bool = False

WORKERS: int = 8   # parallel download threads
SEED:    int = 123  # reproducible sampling

# ── CONSTANTS ─────────────────────────────────────────────────────────────────

_METADATA_URL = (
    "https://storage.googleapis.com/public-datasets-lila/"
    "snapshot-safari-2024-expansion/snapshot_safari_2024_metadata.zip"
)
_MD_URL = (
    "https://lila.science/public/lila-md-results/"
    "snapshot-safari-2024-expansion-SER-subset-v1000.0.0-redwood_detections"
    ".threshold.filtered.json.zip"
)
_IMAGE_BASE = (
    "https://lilawildlife.blob.core.windows.net"
    "/lila-wildlife/snapshot-safari-2024-expansion"
)
_SER_PREFIX    = "SER/"
_CATALOGUE_CSV = CACHE_DIR / "ser_catalogue.csv"

# ── HELPERS ───────────────────────────────────────────────────────────────────


def _download_zip(url: str, dest: Path, label: str) -> None:
    if dest.exists():
        print(f"  [cached] {label} ({dest.stat().st_size >> 20} MB)")
        return
    print(f"  Downloading {label} …")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done  = 0
        with dest.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"    {done >> 20}/{total >> 20} MB ({100*done/total:.0f}%)", end="\r")
    print(f"    Saved → {dest} ({dest.stat().st_size >> 20} MB)           ")


def _best_animal_det(md_entry: dict | None) -> tuple[float, list | None]:
    if md_entry is None:
        return 0.0, None
    best_conf, best_bbox = 0.0, None
    for det in md_entry.get("detections", []):
        if str(det.get("category", "")) == "1":
            conf = float(det.get("conf", 0))
            if conf > best_conf:
                best_conf, best_bbox = conf, det.get("bbox")
    return best_conf, best_bbox


def _build_catalogue() -> pd.DataFrame:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. Metadata ZIP
    print("=" * 60)
    print("Step 1/3 — Snapshot Safari 2024 metadata")
    print("=" * 60)
    meta_zip = CACHE_DIR / "snapshot_safari_2024_metadata.zip"
    _download_zip(_METADATA_URL, meta_zip, "metadata ZIP")

    print("  Parsing JSON …")
    with zipfile.ZipFile(meta_zip) as zf:
        json_name = next(n for n in zf.namelist() if n.endswith(".json"))
        raw = json.loads(zf.read(json_name))

    categories  = {c["id"]: c["name"] for c in raw["categories"]}
    ser_images  = [img for img in raw["images"]
                   if img.get("file_name", "").startswith(_SER_PREFIX)]
    annotations = raw["annotations"]
    print(f"  SER images: {len(ser_images):,}  (of {len(raw['images']):,} total)")
    del raw  # free ~600 MB

    # Detect annotation structure (image-level vs. sequence-level)
    sample_ann  = annotations[0] if annotations else {}
    has_img_id  = "image_id" in sample_ann
    seq_key_ann = next((k for k in ("seq_id", "sequence_id") if k in sample_ann), None)
    sample_img  = ser_images[0] if ser_images else {}
    img_seq_key = next((k for k in ("seq_id", "sequence_id") if k in sample_img), None)

    # Build image_id → category name
    print("  Building label map …")
    img_to_cat: dict[str, str] = {}
    if has_img_id:
        ser_ids = {img["id"] for img in ser_images}
        for ann in annotations:
            if ann["image_id"] in ser_ids:
                img_to_cat[ann["image_id"]] = categories.get(ann["category_id"], "unknown")
    elif seq_key_ann and img_seq_key:
        seq_to_cat: dict[str, str] = {}
        for ann in annotations:
            sid = ann.get(seq_key_ann)
            if sid is not None and sid not in seq_to_cat:
                seq_to_cat[sid] = categories.get(ann["category_id"], "unknown")
        for img in ser_images:
            sid = img.get(img_seq_key)
            if sid in seq_to_cat:
                img_to_cat[img["id"]] = seq_to_cat[sid]
    del annotations  # free memory

    # ── 2. MegaDetector results
    print("\n" + "=" * 60)
    print("Step 2/3 — MegaDetector results")
    print("=" * 60)
    md_zip = CACHE_DIR / "ser_md_results.zip"
    _download_zip(_MD_URL, md_zip, "MegaDetector results ZIP")

    print("  Parsing JSON …")
    with zipfile.ZipFile(md_zip) as zf:
        json_name = next(n for n in zf.namelist() if n.endswith(".json"))
        md_data = json.loads(zf.read(json_name))

    print("  Building MD lookup …")
    md_lookup: dict[str, dict] = {}
    for md_img in md_data.get("images", []):
        fname = md_img.get("file", md_img.get("file_name", "")).lstrip("./")
        md_lookup[fname] = md_img
        md_lookup[Path(fname).name] = md_img  # basename fallback
    del md_data  # free ~400 MB

    # ── 3. Build catalogue: one image per (sequence, label), MD-filtered
    print("\n" + "=" * 60)
    print("Step 3/3 — Building catalogue")
    print("=" * 60)
    seq_best: dict[tuple, dict] = {}

    for img in ser_images:
        img_id = img["id"]
        label  = img_to_cat.get(img_id)
        if label is None:
            continue

        fname    = img.get("file_name", "").lstrip("./")
        md_entry = md_lookup.get(fname) or md_lookup.get(Path(fname).name)
        conf, bbox = _best_animal_det(md_entry)

        if label == "empty":
            if conf >= 0.2:   # skip if MD sees an animal
                continue
            conf, bbox = 0.0, None
        else:
            if conf < MD_CONF_THRESHOLD:
                continue

        seq_id = img.get(img_seq_key, img_id) if img_seq_key else img_id
        key    = (seq_id, label)
        # Keep the frame with the highest MD confidence per sequence
        if key not in seq_best or conf > seq_best[key]["md_conf"]:
            seq_best[key] = {
                "image_id":   img_id,
                "file_name":  img.get("file_name", ""),
                "label":      label,
                "sequence_id": str(seq_id),
                "md_conf":    round(conf, 4),
                "md_bbox":    json.dumps(bbox) if bbox else "",
            }

    df = pd.DataFrame(list(seq_best.values()))
    df.to_csv(_CATALOGUE_CSV, index=False)
    print(f"  Catalogue: {len(df):,} images → {_CATALOGUE_CSV}")
    return df


# ── STEP 1: LOAD (OR BUILD) CATALOGUE ────────────────────────────────────────

if _CATALOGUE_CSV.exists():
    print(f"Loading cached catalogue from {_CATALOGUE_CSV} …")
    catalogue = pd.read_csv(_CATALOGUE_CSV)
else:
    catalogue = _build_catalogue()

# Re-apply threshold so students can tighten/loosen it without rebuilding
catalogue = catalogue[
    (catalogue["label"] == "empty") | (catalogue["md_conf"] >= MD_CONF_THRESHOLD)
]

print(f"\nCatalogue ({len(catalogue):,} images, {catalogue['label'].nunique()} classes):")
print(catalogue["label"].value_counts().to_string())

# ── STEP 2: SELECT SUBSET ─────────────────────────────────────────────────────

df = catalogue.copy()

if CLASSES:
    df = df[df["label"].isin(CLASSES)]

if CLASS_COUNTS:
    parts = [
        df[df["label"] == lbl].sample(
            n=min(n, int((df["label"] == lbl).sum())),
            random_state=SEED,
        )
        for lbl, n in CLASS_COUNTS.items()
        if lbl in df["label"].values
    ]
    df = pd.concat(parts, ignore_index=True)
elif MAX_IMAGES and len(df) > MAX_IMAGES:
    # Guard: 'empty' has ~644k images and will dominate proportional sampling.
    # Cap it at the size of the largest animal class before distributing.
    if "empty" in df["label"].values:
        animal_df    = df[df["label"] != "empty"]
        largest_n    = animal_df["label"].value_counts().iloc[0] if len(animal_df) else 0
        empty_n      = int((df["label"] == "empty").sum())
        if largest_n > 0 and empty_n > largest_n:
            print(
                f"\n  NOTE: 'empty' has {empty_n:,} images — capping at {largest_n:,} "
                f"(size of largest animal class) before proportional sampling.\n"
                f"  To set a different count, use CLASS_COUNTS = {{\"empty\": N, ...}}."
            )
            empty_sample = df[df["label"] == "empty"].sample(n=largest_n, random_state=SEED)
            df = pd.concat([animal_df, empty_sample], ignore_index=True)

    n_total = len(df)
    parts   = []
    for lbl in df["label"].unique():
        grp = df[df["label"] == lbl]
        n   = max(1, round(MAX_IMAGES * len(grp) / n_total))
        parts.append(grp.sample(n=min(n, len(grp)), random_state=SEED))
    df = pd.concat(parts, ignore_index=True)
    if len(df) > MAX_IMAGES:
        df = df.sample(n=MAX_IMAGES, random_state=SEED)

print(f"\nSelected {len(df):,} images:")
print(df["label"].value_counts().to_string())

# ── STEP 3: DOWNLOAD (+ OPTIONAL CROP) ───────────────────────────────────────


def _crop_bbox(img: Image.Image, bbox_raw, pad: float = 0.10) -> Image.Image:
    bbox = ast.literal_eval(bbox_raw) if isinstance(bbox_raw, str) else list(bbox_raw)
    W, H = img.size
    x, y, bw, bh = bbox
    x1, y1 = x * W, y * H
    x2, y2 = (x + bw) * W, (y + bh) * H
    px, py  = pad * (x2 - x1), pad * (y2 - y1)
    box = (max(0.0, x1 - px), max(0.0, y1 - py), min(float(W), x2 + px), min(float(H), y2 + py))
    if box[2] <= box[0] or box[3] <= box[1]:
        return img
    return img.crop(tuple(int(v) for v in box))


def _download_one(row) -> str:
    dest = OUTPUT_DIR / row.label / Path(row.file_name).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return "skip"
    url = f"{_IMAGE_BASE}/{row.file_name}"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
            if CROP and row.md_bbox and str(row.md_bbox) not in ("", "nan"):
                img = _crop_bbox(img, row.md_bbox)
            img.save(dest, "JPEG", quality=92)
            return "ok"
        except Exception as exc:
            if attempt == 2:
                return f"fail:{exc}"
            time.sleep(2 ** attempt)
    return "fail"


print()
rows   = list(df.itertuples(index=False))
counts = {"ok": 0, "skip": 0, "fail": 0}
t0     = time.time()

with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    futures = {pool.submit(_download_one, row): row for row in rows}
    for i, fut in enumerate(as_completed(futures), 1):
        status = fut.result()
        key = "fail" if status.startswith("fail") else status
        counts[key] += 1
        if i % 20 == 0 or i == len(rows):
            elapsed = time.time() - t0
            rate    = i / elapsed if elapsed else 0
            print(
                f"\r[{i:>5}/{len(rows)}]  {elapsed:.0f}s  {rate:.1f} img/s  "
                f"ok={counts['ok']}  skip={counts['skip']}  fail={counts['fail']}",
                end="",
            )

print(f"\n\nImages saved to: {OUTPUT_DIR.resolve()}")
for d in sorted(OUTPUT_DIR.iterdir()):
    if d.is_dir():
        n = len(list(d.glob("*.jpg"))) + len(list(d.glob("*.JPG")))
        print(f"  {d.name:25s}: {n:>5} images")

# ── HELPER FUNCTIONS ──────────────────────────────────────────────────────────
# These operate on any DataFrame with columns [file_name, label, sequence_id].
# Call them after running the script, or import them into your own notebook.


def make_splits(
    df: pd.DataFrame,
    train: float = 0.70,
    val:   float = 0.15,
    test:  float = 0.15,
    seed:  int   = SEED,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return stratified (train_df, val_df, test_df) with no sequence leakage.

    Splits are performed at sequence level so that frames from the same
    camera-trap burst never appear in more than one split.  Each returned
    DataFrame has columns: file_path, label, sequence_id, md_conf, md_bbox.
    """
    assert abs(train + val + test - 1.0) < 1e-6, "train + val + test must equal 1.0"

    df = df.copy()
    df["file_path"] = df["file_name"].apply(
        lambda fn: str(OUTPUT_DIR / Path(fn).parent.name / Path(fn).name)
        if "/" in fn
        else str(OUTPUT_DIR / df.loc[df["file_name"] == fn, "label"].iloc[0] / Path(fn).name)
    )

    # Collapse to one row per sequence so we split sequences, not frames.
    seq_df = (
        df.groupby("sequence_id", sort=False)
        .agg(label=("label", "first"))
        .reset_index()
    )

    rng        = pd.Series(seq_df["sequence_id"].unique())
    train_seqs: set[str] = set()
    val_seqs:   set[str] = set()
    test_seqs:  set[str] = set()

    for lbl, grp in seq_df.groupby("label"):
        ids     = grp["sequence_id"].sample(frac=1, random_state=seed).tolist()
        n_train = round(len(ids) * train)
        n_val   = round(len(ids) * val)
        train_seqs.update(ids[:n_train])
        val_seqs.update(ids[n_train : n_train + n_val])
        test_seqs.update(ids[n_train + n_val :])

    train_df = df[df["sequence_id"].isin(train_seqs)].reset_index(drop=True)
    val_df   = df[df["sequence_id"].isin(val_seqs)].reset_index(drop=True)
    test_df  = df[df["sequence_id"].isin(test_seqs)].reset_index(drop=True)

    print(
        f"Split sizes — train: {len(train_df):,}  val: {len(val_df):,}  test: {len(test_df):,}"
    )
    return train_df, val_df, test_df


def compute_class_weights(df: pd.DataFrame) -> dict[str, float]:
    """Return inverse-frequency class weights as a dict {label: weight}.

    Weights are normalised so they average to 1.0.  Pass them to
    nn.CrossEntropyLoss via a tensor ordered by sorted(weights.keys()):

        classes = sorted(weights)
        w = torch.tensor([weights[c] for c in classes], dtype=torch.float32)
        criterion = nn.CrossEntropyLoss(weight=w)

    The label-to-index mapping must match your Dataset's class_to_idx, which
    should also use sorted(classes) as its ordering.
    """
    counts  = df["label"].value_counts()
    n_total = len(df)
    n_cls   = len(counts)
    weights = {lbl: n_total / (n_cls * cnt) for lbl, cnt in counts.items()}

    print("Class weights (higher = rarer class):")
    for lbl in sorted(weights, key=lambda l: weights[l], reverse=True):
        print(f"  {lbl:30s}: {weights[lbl]:.4f}  ({counts[lbl]:>6,} images)")

    return weights
