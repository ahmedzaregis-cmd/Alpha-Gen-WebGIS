# -*- coding: utf-8 -*-
"""Data store — read layers from the GeoPackages as WGS84 GeoJSON, with caching,
and persist user edits into alpha_accessibility_edited.gpkg (original untouched)."""
import os
import threading
import json
import sqlite3
import shutil

import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform as shp_transform

import catalog

_cache = {}
_cache_lock = threading.RLock()
_EDIT_LOCK = threading.Lock()
_EDIT_READY = False

# transformer 32636 -> 4326 (and reverse)
_FWD = Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True)
_INV = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)

# layers too heavy to ship whole to the browser -> simplified + attribute-thin
HEAVY = {
    "roads_all_nasr": 6.0, "roads_all_ps": 6.0,
    "roads_walk_nasr": 2.0, "roads_walk_ps": 2.0,
    "buildings_res_nasr": 1.5, "buildings_res_ps": 1.5,
    "buildings_net_nasr": 1.5, "buildings_net_ps": 1.5,
    "buildings_demand_nasr": 1.5, "buildings_demand_ps": 1.5,
}
HEAVY_FIELDS = {
    "roads_all_nasr": ["osm_id", "highway", "name"],
    "roads_all_ps": ["osm_id", "highway", "name"],
    "roads_walk_nasr": ["osm_id", "highway", "name", "surface", "lit"],
    "roads_walk_ps": ["osm_id", "highway", "name", "surface", "lit"],
    "buildings_res_nasr": ["osm_id", "building", "name"],
    "buildings_res_ps": ["osm_id", "building", "name"],
    "buildings_net_nasr": ["osm_id", "name", "nearest_id", "nearest_name", "dist_min",
                           "n400", "n800", "n1200", "b_snap_m"],
    "buildings_net_ps": ["osm_id", "name", "nearest_id", "nearest_name", "dist_min",
                         "n400", "n800", "n1200", "b_snap_m"],
    "buildings_demand_nasr": ["osm_id", "name", "nearest_name", "dist_min", "uns_pop", "n800"],
    "buildings_demand_ps": ["osm_id", "name", "nearest_name", "dist_min", "uns_pop", "n800"],
}


def _has_layer(path, layer_id):
    if not os.path.exists(path):
        return False
    try:
        con = sqlite3.connect(path)
        row = con.execute(
            "select 1 from gpkg_contents where table_name=?", (layer_id,)).fetchone()
        con.close()
        return row is not None
    except sqlite3.Error:
        return False


def _src_path(layer_id, source=None):
    if source == "edu":
        return catalog.GPKG_EDU
    if os.path.exists(catalog.GPKG_EDIT):
        # edited copy holds everything (created lazily as a full copy)
        try:
            with _EDIT_LOCK:
                con = sqlite3.connect(catalog.GPKG_EDIT)
                row = con.execute(
                    "select 1 from gpkg_contents where table_name=?", (layer_id,)).fetchone()
                con.close()
            if row:
                return catalog.GPKG_EDIT
        except sqlite3.Error:
            pass
    if _has_layer(catalog.GPKG, layer_id):
        return catalog.GPKG
    # not in the main data — maybe an Education City layer
    if _has_layer(catalog.GPKG_EDU, layer_id):
        return catalog.GPKG_EDU
    return catalog.GPKG


def list_layers():
    out = set()
    for p in (catalog.GPKG, catalog.GPKG_EDU):
        if os.path.exists(p):
            con = sqlite3.connect(p)
            out |= {r[0] for r in con.execute("select table_name from gpkg_contents")}
            con.close()
    return sorted(out)


def _read(layer_id, source=None, columns=None):
    """Read a layer. With `columns`, only those attributes are decoded (column push-down:
    the heavy building layers carry dozens of OSM fields the map never shows)."""
    path = _src_path(layer_id, source)
    if columns:
        try:
            return gpd.read_file(path, layer=layer_id, engine="pyogrio", fid_as_index=True,
                                 columns=list(columns))
        except Exception:                      # a listed column is missing: read everything
            pass
    return gpd.read_file(path, layer=layer_id, engine="pyogrio", fid_as_index=True)


def _to_wgs84(gdf):
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:32636")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def layer_geojson(layer_id, source=None, simplify=None, fields=None, subset=None, thin=True, cache=True):
    """Return (geojson_dict, meta). Cached in memory.

    thin=True  : الطبقات الثقيلة تُقلَّص حقولها وتُبسَّط هندستها (للعرض على الخريطة).
    thin=False : كل الحقول (للتصدير). simplify=0 يلغي التبسيط.
    cache=False: لا تحتفظ بقاموس Python الضخم (الخادم يحتفظ بالبايتات الجاهزة بدلًا منه).
    """
    key = (layer_id, source, simplify, tuple(fields or ()), subset, bool(thin))
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    # attribute thinning for heavy layers (pushed down to the reader unless a subset query needs other columns)
    keep = list(fields) if fields else (HEAVY_FIELDS.get(layer_id) if thin else None)
    gdf = _read(layer_id, source, columns=keep if (keep and not subset) else None)
    if keep:
        keep = [c for c in keep if c in gdf.columns]
        gdf = gdf[keep + ["geometry"]]

    if subset:
        gdf = gdf.query(subset).copy()

    # geometry simplification (metres, in native projected CRS) for heavy layers
    tol = simplify if simplify is not None else HEAVY.get(layer_id)
    if tol and len(gdf) > 300:
        gdf["geometry"] = gdf.geometry.simplify(tol, preserve_topology=True)

    gdf = _to_wgs84(gdf)

    # الطبقات الكبيرة: إحداثيات بدقة ~1 م (5 خانات عشرية) — تقلّل حجم الملف بنحو الثلث
    if thin and len(gdf) > 300:
        try:
            import shapely
            gdf["geometry"] = shapely.set_precision(gdf.geometry.values, 1e-5)
        except Exception:
            pass

    n = len(gdf)
    geom_types = sorted({gt for gt in gdf.geom_type.unique()}) if n else []
    fields_meta = []
    for c in gdf.columns:
        if c == "geometry":
            continue
        s = gdf[c]
        dtype = "number" if pd.api.types.is_numeric_dtype(s) else "string"
        fields_meta.append({"name": c, "type": dtype})

    # fid preservation: index is the gpkg fid (fid_as_index=True)
    from shapely.geometry import mapping as shp_mapping
    feats = []
    props_cols = [c for c in gdf.columns if c != "geometry"]
    records = gdf[props_cols].to_dict("records")
    geoms = list(gdf.geometry)
    fids = list(gdf.index)
    # NaN -> None
    for i, rec in enumerate(records):
        props = {}
        for k, v in rec.items():
            if v is None or (isinstance(v, float) and v != v):
                props[k] = None
            elif hasattr(v, "item"):
                props[k] = v.item()
            else:
                props[k] = v
        g = geoms[i]
        feats.append({"type": "Feature", "id": int(fids[i]), "properties": props,
                      "geometry": (shp_mapping(g) if g is not None and not g.is_empty else None)})

    fc = {"type": "FeatureCollection", "features": feats}
    meta = {"layer": layer_id, "count": n, "fields": fields_meta,
            "geom_types": geom_types, "crs": "EPSG:4326"}
    if cache:
        with _cache_lock:
            _cache[key] = (fc, meta)
    return fc, meta


def invalidate(layer_id=None):
    with _cache_lock:
        if layer_id is None:
            _cache.clear()
        else:
            for k in [k for k in _cache if k[0] == layer_id]:
                del _cache[k]


# ------------------------------------------------------------------ editing
def ensure_edit_copy():
    """Create alpha_accessibility_edited.gpkg as a full copy of the original (once)."""
    global _EDIT_READY
    if _EDIT_READY and os.path.exists(catalog.GPKG_EDIT):
        return
    with _EDIT_LOCK:
        if not os.path.exists(catalog.GPKG_EDIT):
            shutil.copy2(catalog.GPKG, catalog.GPKG_EDIT)
        _EDIT_READY = True


def _transform_geom(geom, inverse=True):
    fn = _INV.transform if inverse else _FWD.transform
    return shp_transform(fn, geom)


def edit_feature(layer_id, action, feature=None, fid=None, source=None):
    """action: create | update | delete. feature: GeoJSON feature (WGS84)."""
    ensure_edit_copy()
    path = catalog.GPKG_EDIT if source != "edu" else catalog.GPKG_EDU
    if source == "edu":
        raise ValueError("Education City layers are read-only.")

    with _EDIT_LOCK:
        con = sqlite3.connect(path)
        con.execute("PRAGMA foreign_keys=ON")
        cur = con.cursor()
        cols = [r[1] for r in cur.execute('PRAGMA table_info("%s")' % layer_id)]
        if not cols:
            con.close()
            raise KeyError("unknown layer %s" % layer_id)
        geom_col = "geometry" if "geometry" in cols else ("geom" if "geom" in cols else None)
        attr_cols = [c for c in cols if c not in (geom_col, "fid")]

        try:
            if action == "delete":
                cur.execute('DELETE FROM "%s" WHERE fid=?' % layer_id, (fid,))
                ok = cur.rowcount
            else:
                props = (feature or {}).get("properties") or {}
                geo = (feature or {}).get("geometry")
                set_cols, vals = [], []
                for c in attr_cols:
                    if c in props:
                        v = props[c]
                        if isinstance(v, (list, dict)):
                            v = json.dumps(v, ensure_ascii=False)
                        set_cols.append('"%s"' % c)
                        vals.append(v)
                if action == "create":
                    sql = 'INSERT INTO "%s" (%s) VALUES (%s)' % (
                        layer_id, ", ".join(set_cols + ([geom_col] if geom_col and geo else [])),
                        ", ".join(["?"] * len(set_cols) + (["?"] if geom_col and geo else [])))
                    params = vals[:]
                    if geom_col and geo:
                        params.append(_gpkg_blob(geo))
                    cur.execute(sql, params)
                    ok = cur.lastrowid
                elif action == "update":
                    if not set_cols and not (geom_col and geo):
                        raise ValueError("nothing to update")
                    parts = [", ".join(set_cols)] if set_cols else []
                    params = list(vals)
                    if geom_col and geo:
                        parts.append('"%s"=?' % geom_col)
                        params.append(_gpkg_blob(geo))
                    params.append(fid)
                    cur.execute('UPDATE "%s" SET %s WHERE fid=?' % (layer_id, ", ".join(parts)), params)
                    ok = cur.rowcount
                else:
                    raise ValueError("unknown action " + action)
            con.commit()
        finally:
            con.close()

    invalidate(layer_id)
    return ok


def _gpkg_blob(geojson_geom):
    """Encode a GeoJSON geometry (WGS84) as a GPKG geometry blob in EPSG:32636."""
    from shapely.geometry import shape
    geom = shape(geojson_geom)
    if not geom.is_valid:
        geom = geom.buffer(0)
    geom = _transform_geom(geom, inverse=True)  # 4326 -> 32636
    wkb = geom.wkb
    # GPKG binary header: 'GP', version 0, flags (envelope=0, little endian), srs_id
    header = b"GP" + bytes([0x00, 0x01]) + (32636).to_bytes(4, "little", signed=True)
    return header + wkb


def export_layer_geojson(layer_id, source=None):
    fc, _ = layer_geojson(layer_id, source=source, simplify=0, thin=False)
    return fc
