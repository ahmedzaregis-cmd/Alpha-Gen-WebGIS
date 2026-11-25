# -*- coding: utf-8 -*-
"""Raster server — render GeoTIFFs (KDE, suitability, hillshade, DEM) to PNG
overlays with WGS84 bounds, cached on disk under platform/cache/rasters/."""
import base64
import hashlib
import io
import json
import os
import threading

import numpy as np
import rasterio
from PIL import Image

import catalog

CACHE = os.path.join(catalog.PROC, "platform", "cache", "rasters")
os.makedirs(CACHE, exist_ok=True)
_LOCK = threading.Lock()


def _hex_ramp(stops, n):
    cols = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in stops], float)
    x = np.linspace(0, len(cols) - 1, n)
    out = np.empty((n, 3))
    for ch in range(3):
        out[:, ch] = np.interp(x, np.arange(len(cols)), cols[:, ch])
    return out


def render(layer_meta, max_px=1400):
    """layer_meta from catalog.build_catalog()['rasters'] -> {png_b64, bounds}."""
    lid = layer_meta["id"]
    out_png = os.path.join(CACHE, lid + ".png")
    out_meta = os.path.join(CACHE, lid + ".json")
    with _LOCK:
        if os.path.exists(out_png) and os.path.exists(out_meta):
            with open(out_meta, encoding="utf-8") as f:
                m = json.load(f)
            return {"bounds": m["bounds"]}      # الصورة تُخدَّم كملف PNG منفصل

    path = os.path.join(catalog.PROC, layer_meta["file"])
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)
        bounds = src.bounds
        crs = src.crs
        if src.count >= 3 and layer_meta.get("rgb"):
            rgb = src.read()[:3]
            has_rgb = True
        else:
            has_rgb = False

    if has_rgb:
        img = np.dstack([rgb[i] for i in range(3)] + [np.full(rgb[0].shape, 255, np.uint8)])
        img = Image.fromarray(img, "RGBA")
    else:
        arr = data.filled(np.nan).astype(float)
        valid = ~np.isnan(arr)
        if layer_meta.get("ramp"):                       # classified / pseudo-colour
            vmin = float(np.nanmin(arr)) if valid.any() else 0.0
            vmax = float(np.nanmax(arr)) if valid.any() else 1.0
            if vmax <= vmin:
                vmax = vmin + 1
            t = np.clip((arr - vmin) / (vmax - vmin), 0, 1)
            ramp = _hex_ramp(layer_meta["ramp"], 256)
            idx = (t * 255).astype(np.uint8)
            rgb = ramp[idx].astype(np.uint8)
            alpha = np.where(valid, 255, 0).astype(np.uint8)
            # make the lowest value transparent-ish for KDE (0 = no density)
            if lid.startswith("kde"):
                alpha = np.where(valid & (arr > 0), 255, 0).astype(np.uint8)
            img = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
        else:                                             # grayscale (hillshade)
            vmin = float(np.nanmin(arr)) if valid.any() else 0
            vmax = float(np.nanmax(arr)) if valid.any() else 255
            t = np.clip((arr - vmin) / ((vmax - vmin) or 1), 0, 1)
            g = (t * 255).astype(np.uint8)
            alpha = np.where(valid, 255, 0).astype(np.uint8)
            img = Image.fromarray(np.dstack([g, g, g, alpha]), "RGBA")

    # downscale if huge
    if max(img.size) > max_px:
        s = max_px / max(img.size)
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))),
                         Image.BILINEAR)

    img.save(out_png, format="PNG", optimize=True)

    # bounds -> WGS84 (transform all 4 corners, take bbox)
    from pyproj import Transformer
    epsg = crs.to_epsg() if crs else None
    if epsg == 4326:
        lngs = [bounds.left, bounds.right]; lats = [bounds.bottom, bounds.top]
    else:
        tf = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        pts = [tf.transform(bounds.left, bounds.bottom), tf.transform(bounds.left, bounds.top),
               tf.transform(bounds.right, bounds.bottom), tf.transform(bounds.right, bounds.top)]
        lngs = [p[0] for p in pts]; lats = [p[1] for p in pts]
    meta = {"bounds": [[min(lats), min(lngs)], [max(lats), max(lngs)]]}
    with open(out_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return meta
