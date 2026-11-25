# -*- coding: utf-8 -*-
"""Analysis engine — re-implements the QGIS/PyQGIS analyses of REPORT_accessibility.md
server-side so the platform can re-run them at any threshold, live.

Parity sources:
  - service areas / overlap  : net_{city}.pkl  (pre-computed Dijkstra costs per school)
  - nearest facility         : buildings_net_{city}.dist_min
  - coverage by shiakha      : pre-computed fields + live intersection for any T
  - Gi* hotspot              : distribution.py::hotspot() algorithm (identical)
  - distribution stats       : distribution.py::stats_city() (identical formulas)
  - KDE                      : QGIS quartic kernel, bandwidth R, 50 m pixel
"""
import math
import os
import pickle
import threading
from collections import OrderedDict

import numpy as np
import shapely
from shapely.geometry import shape, mapping, box, Point, MultiLineString
from shapely.ops import unary_union

import catalog
import kernels as K
import store

_LOCK = threading.RLock()
_NET = {}          # city -> dict(segs(arr), costs(arr), snap, verts)  (static network: never invalidated)
_GRAPH = {}        # city -> adjacency list for arbitrary-point Dijkstra

# ---- data caches. Everything read from the GeoPackages, or derived from it, is computed once
# and shared by every analysis. The whole group is dropped by invalidate() after an edit.
_DATA = {}
_DATA_LOCK = threading.Lock()
_KEY_LOCKS = {}
_GROUPS = {}       # group name -> OrderedDict of keys, used to cap memory of big derived geometries


def _cached(key, fn, group=None, cap=0):
    """Compute fn() once per key; concurrent callers of the same key wait instead of repeating it."""
    with _DATA_LOCK:
        if key in _DATA:
            return _DATA[key]
        lock = _KEY_LOCKS.setdefault(key, threading.Lock())
    with lock:
        with _DATA_LOCK:
            if key in _DATA:
                return _DATA[key]
        val = fn()
        with _DATA_LOCK:
            _DATA[key] = val
            if group:
                order = _GROUPS.setdefault(group, OrderedDict())
                order[key] = True
                while cap and len(order) > cap:
                    old, _ = order.popitem(last=False)
                    _DATA.pop(old, None)
        return val


def invalidate():
    """Called after an edit: forget everything that was read from or derived from the data."""
    with _DATA_LOCK:
        _DATA.clear()
        _KEY_LOCKS.clear()
        _GROUPS.clear()


# ------------------------------------------------------------------ network
def _load_net(city):
    with _LOCK:
        if city in _NET:
            return _NET[city]
    with open(os.path.join(catalog.PROC, "net_%s.pkl" % city), "rb") as f:
        raw = pickle.load(f)
    segs = np.asarray(raw["segs"], dtype=np.float64)          # (N,7): u,v,x1,y1,x2,y2,len
    school_ids = list(raw["costs"].keys())
    costs = np.asarray([raw["costs"][s] for s in school_ids], dtype=np.float64)  # (S,V)
    net = {"segs": segs, "costs": costs, "schools": school_ids,
           "snap": raw["snap"], "verts": np.asarray(raw["verts"], dtype=np.float64),
           "u": segs[:, 0].astype(np.int64), "v": segs[:, 1].astype(np.int64)}
    with _LOCK:
        _NET[city] = net
    return net


def _school_gap(net, sid):
    s = net["snap"].get(sid)
    if isinstance(s, (tuple, list)):
        return float(s[0])
    return 0.0


def _build_graph(net):
    """Undirected adjacency from segs: node -> [(neighbor, length)]."""
    segs = net["segs"]
    u = segs[:, 0].astype(np.int64)
    v = segs[:, 1].astype(np.int64)
    L = segs[:, 6]
    adj = {}
    for i in range(len(u)):
        a, b, l = int(u[i]), int(v[i]), float(L[i])
        adj.setdefault(a, []).append((b, l))
        adj.setdefault(b, []).append((a, l))
    return adj


def _graph(city):
    with _LOCK:
        if city in _GRAPH:
            return _GRAPH[city]
    adj = _build_graph(_load_net(city))
    with _LOCK:
        _GRAPH[city] = adj
    return adj


# ------------------------------------------------------------------ geometries
def _seg_lines(masked_segs):
    """(N,7) selected segs -> one MultiLineString, built with array calls (no Python loop)."""
    if len(masked_segs) == 0:
        return MultiLineString([])
    coords = masked_segs[:, 2:6].reshape(-1, 2, 2)
    return shapely.multilinestrings(shapely.linestrings(coords))


def _mincost(city):
    """Cost to the nearest school at every network node (independent of the threshold)."""
    def build():
        net = _load_net(city)
        gaps = np.array([_school_gap(net, s) for s in net["schools"]])
        return (net["costs"] + gaps[:, None]).min(axis=0)
    return _cached(("mincost", city), build)


def _buffered(net, cost, threshold):
    sel = (cost[net["u"]] <= threshold) | (cost[net["v"]] <= threshold)
    lines = _seg_lines(net["segs"][sel])
    if lines.is_empty:
        return lines
    return lines.buffer(25.0, quad_segs=5)     # QGIS buffer default = 5 segments


def service_area_geom(city, threshold, school_idx=None):
    """Network service area polygon (EPSG:32636) at `threshold` metres.
    Parity with QGIS: segments whose Dijkstra cost (+ snap gap) <= T, buffer 25 m, dissolve.
    The result is cached, so service area, coverage and the dashboard share one computation."""
    net = _load_net(city)
    if school_idx is None:
        return _cached(("svc", city, int(threshold)),
                       lambda: _buffered(net, _mincost(city), threshold),
                       group="svc", cap=12)
    cost = net["costs"][school_idx] + _school_gap(net, net["schools"][school_idx])
    return _buffered(net, cost, threshold)


def per_school_service_geoms(city, threshold):
    def build():
        net = _load_net(city)
        return [(sid, _buffered(net, net["costs"][i] + _school_gap(net, sid), threshold))
                for i, sid in enumerate(net["schools"])]
    return _cached(("svc_each", city, int(threshold)), build, group="svc_each", cap=6)


# ------------------------------------------------------------------ cached feature collections
def _to_wgs84_geoms(geoms):
    """EPSG:32636 shapely geometries -> WGS84, one batched projection call for all of them
    (the old code projected each geometry separately). Coordinates keep 6 decimals (~0.1 m)."""
    arr = np.empty(len(geoms), dtype=object)
    for i, g in enumerate(geoms):
        arr[i] = g

    def fwd(c):
        lng, lat = store._FWD.transform(c[:, 0], c[:, 1])
        return np.round(np.column_stack([lng, lat]), 6)
    return shapely.transform(arr, fwd)


def geoms_to_fc(geoms, props_list):
    if not len(geoms):
        return {"type": "FeatureCollection", "features": []}
    out = _to_wgs84_geoms(geoms)
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": p, "geometry": mapping(g)}
                         for g, p in zip(out, props_list)]}


def geom_to_fc(geom, props=None):
    """EPSG:32636 shapely geom -> WGS84 GeoJSON FeatureCollection."""
    return geoms_to_fc([geom], [props or {}])


# ------------------------------------------------------------------ data readers (each layer is read once)
def _layer_path(layer):
    return store._src_path(layer)


def _read_attrs(layer, columns):
    """Attribute columns only, no geometry decoding (pyogrio). Far cheaper than read_file."""
    import pyogrio
    return pyogrio.read_dataframe(_layer_path(layer), layer=layer, columns=columns,
                                  read_geometry=False)


def _bld(city):
    """Building centroids (EPSG:32636) and distance to the nearest school, read once per city."""
    def build():
        import geopandas as gpd
        layer = "buildings_net_" + city
        try:
            gdf = gpd.read_file(_layer_path(layer), layer=layer, engine="pyogrio", columns=["dist_min"])
        except Exception:                     # layer without dist_min
            gdf = gpd.read_file(_layer_path(layer), layer=layer, engine="pyogrio")
        cent = gdf.geometry.centroid
        dist = gdf["dist_min"].to_numpy(dtype=float) if "dist_min" in gdf.columns else None
        return {"bx": cent.x.to_numpy(), "by": cent.y.to_numpy(), "bdist": dist, "crs": gdf.crs}
    return _cached(("bld", city), build)


def _demand(city):
    """Population proxy per building: (uns_pop, dist_min) arrays."""
    def build():
        layer = "buildings_demand_" + city
        df = _read_attrs(layer, ["uns_pop", "dist_min"])
        return df["uns_pop"].to_numpy(dtype=float), df["dist_min"].to_numpy(dtype=float)
    return _cached(("demand", city), build)


def _boundary(city):
    """City boundary: (dissolved geometry, area in m2, total bounds)."""
    def build():
        import geopandas as gpd
        layer = "%s_boundary_32636" % city
        bnd = gpd.read_file(_layer_path(layer), layer=layer, engine="pyogrio")
        geom = unary_union(bnd.geometry.values)
        return geom, float(geom.area), tuple(bnd.total_bounds), float(bnd.geometry.area.sum())
    return _cached(("boundary", city), build)


def _schools_gdf():
    def build():
        import geopandas as gpd
        return gpd.read_file(_layer_path("schools_32636"), layer="schools_32636", engine="pyogrio")
    return _cached(("schools",), build)


def _city_schools(city):
    sc = _schools_gdf()
    return sc[sc["city"] == catalog.CITY[city]["en"]]


def _zones_gdf(city):
    def build():
        import geopandas as gpd
        layer = "zones_shiakha_" + city
        zg = gpd.read_file(_layer_path(layer), layer=layer, engine="pyogrio")
        # normalise raw CEDA field names
        if "zone_id" not in zg.columns:
            if "Final_code_6dig" in zg.columns:
                zg["zone_id"] = zg["Final_code_6dig"].astype(str)
            else:
                zg["zone_id"] = zg.index.astype(str)
        if "shiakha" not in zg.columns and "SubSection_A" in zg.columns:
            zg["shiakha"] = zg["SubSection_A"]
        if "qism" not in zg.columns and "Section_A_Nam" in zg.columns:
            zg["qism"] = zg["Section_A_Nam"]
        if "pop2017" not in zg.columns:
            pop_col = next((c for c in zg.columns if "سكان" in str(c)), None)
            if pop_col:
                zg["pop2017"] = zg[pop_col]
        return zg
    return _cached(("zones", city), build)


def _building_zone_map(city):
    """Zone index for every building (-1 = outside). Reuses the centroids already in memory
    instead of reading the buildings layer a second time."""
    def build():
        import geopandas as gpd
        b = _bld(city)
        zg = _zones_gdf(city)
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(b["bx"], b["by"]), crs=b["crs"])
        joined = gpd.sjoin(pts, zg[["geometry"]], how="left", predicate="within")
        joined = joined[~joined.index.duplicated(keep="first")]      # a point on a border matches twice
        arr = np.full(len(pts), -1, dtype=np.int64)
        ir = joined["index_right"].to_numpy(dtype=float)
        ok = ~np.isnan(ir)
        arr[joined.index.to_numpy()[ok]] = ir[ok].astype(np.int64)
        return arr
    return _cached(("b2z", city), build)


def _num(v, nd=None):
    """float or None (NaN never reaches the JSON, which would be invalid)."""
    v = float(v)
    if v != v:
        return None
    return round(v, nd) if nd is not None else v


# ------------------------------------------------------------------ analyses
def analysis_service_area(city, threshold, per_school=False, simplify=1.0):
    threshold = int(round(threshold))
    if per_school:
        geoms, props = [], []
        for sid, g in per_school_service_geoms(city, threshold):
            if g.is_empty:
                continue
            geoms.append(g.simplify(simplify, preserve_topology=True) if simplify else g)
            props.append({"school_id": sid, "threshold": threshold})
        return geoms_to_fc(geoms, props)
    g = service_area_geom(city, threshold)
    if g.is_empty:
        return {"type": "FeatureCollection", "features": []}
    if simplify:
        g = g.simplify(simplify, preserve_topology=True)
    return geom_to_fc(g, {"threshold": threshold})


def analysis_overlap(city, threshold, grid=10.0):
    """k-fold overlap of per-school service areas — rasterise at `grid` metres,
    then polygonise (parity with QGIS raster-based overlap at 10 m)."""
    from rasterio.features import rasterize, shapes
    from rasterio.transform import from_origin

    geoms = [g for _, g in per_school_service_geoms(city, threshold) if not g.is_empty]
    if not geoms:
        return {"type": "FeatureCollection", "features": []}
    union = unary_union(geoms)
    minx, miny, maxx, maxy = union.bounds
    minx -= 50; miny -= 50; maxx += 50; maxy += 50
    w = int(math.ceil((maxx - minx) / grid))
    h = int(math.ceil((maxy - miny) / grid))
    if w * h > 60_000_000:
        grid = math.sqrt((maxx - minx) * (maxy - miny) / 60_000_000)
        w = int(math.ceil((maxx - minx) / grid))
        h = int(math.ceil((maxy - miny) / grid))
    transform = from_origin(minx, maxy, grid, grid)
    acc = np.zeros((h, w), dtype=np.uint8)
    for g in geoms:
        # rasterise only inside the school's own bounding window, aligned to the same pixel
        # grid, instead of allocating and filling a full-city raster for every school
        gx0, gy0, gx1, gy1 = g.bounds
        c0 = max(0, int(math.floor((gx0 - minx) / grid)))
        c1 = min(w, int(math.ceil((gx1 - minx) / grid)) + 1)
        r0 = max(0, int(math.floor((maxy - gy1) / grid)))
        r1 = min(h, int(math.ceil((maxy - gy0) / grid)) + 1)
        if c0 >= c1 or r0 >= r1:
            continue
        win = from_origin(minx + c0 * grid, maxy - r0 * grid, grid, grid)
        acc[r0:r1, c0:c1] += rasterize([(g, 1)], out_shape=(r1 - r0, c1 - c0), transform=win,
                                       dtype=np.uint8, all_touched=False)
    polys, props = [], []
    for geom_json, val in shapes(acc, mask=acc >= 2, transform=transform):
        if val < 2:
            continue
        g = shape(geom_json).buffer(0)
        if g.is_empty:
            continue
        polys.append(g)
        props.append({"n_schools": int(val), "area_km2": round(g.area / 1e6, 3),
                      "threshold": threshold})
    return geoms_to_fc(polys, props)


def analysis_coverage(city, threshold, per_zone=True):
    """Coverage at ANY threshold — buildings, population proxy, area, per-shiakha."""
    threshold = float(threshold)
    b = _bld(city)
    bdist = b["bdist"]

    n_bldg = int(len(bdist))
    within = int(np.sum(bdist <= threshold)) if bdist is not None else 0
    bldg_pct = round(100.0 * within / n_bldg, 2) if n_bldg else 0.0

    # population proxy from the demand layer (read once)
    pop, dem_d = _demand(city)
    pop_total = float(np.nansum(pop))
    pop_within = float(np.nansum(pop[dem_d <= threshold]))
    pop_pct = round(100.0 * pop_within / pop_total, 2) if pop_total else 0.0

    # service area (shared cache) ∩ boundary (read once)
    svc = service_area_geom(city, int(threshold))
    bnd_geom, area_m2, _bounds, _ = _boundary(city)
    area_total = area_m2 / 1e6
    area_cov = (svc.intersection(bnd_geom).area / 1e6) if not svc.is_empty else 0.0
    area_pct = round(100.0 * area_cov / area_total, 2) if area_total else 0.0

    out = {
        "threshold": int(threshold),
        "buildings": {"total": n_bldg, "within": within, "pct": bldg_pct},
        "population": {"total": round(pop_total), "within": round(pop_within), "pct": pop_pct},
        "area_km2": {"total": round(area_total, 2), "within": round(area_cov, 3), "pct": area_pct},
        "avg_dist_m": _num(np.mean(bdist), 1) if bdist is not None else None,
        "median_dist_m": _num(np.median(bdist), 1) if bdist is not None else None,
    }

    if per_zone:
        zg = _zones_gdf(city)
        b2z = _building_zone_map(city)
        n_z = len(zg)
        counts, wins, means = K.zone_stats(b2z, bdist, threshold, n_z)
        zone_ids = zg["zone_id"].to_numpy()
        shi = zg["shiakha"].to_numpy()
        pops = zg["pop2017"].to_numpy()
        rows = []
        for zi in np.nonzero(counts)[0]:
            n = int(counts[zi])
            rows.append({
                "zone_id": str(zone_ids[zi]), "shiakha": str(shi[zi]),
                "pop2017": int(pops[zi]) if pops[zi] == pops[zi] else None,
                "n_bldg": n, "within": int(wins[zi]),
                "pct_bldg": round(100.0 * int(wins[zi]) / n, 2),
                "avg_dist": _num(means[zi], 0),
            })
        rows.sort(key=lambda r: -r["n_bldg"])
        out["zones"] = rows
    return out


def analysis_hotspot(city, threshold=800.0, cell=250.0, band=1000.0, min_bldg=5):
    """Getis-Ord Gi* — identical algorithm to distribution.py::hotspot(), vectorised."""
    b = _bld(city)
    if b["bdist"] is None:
        raise ValueError("buildings lack dist_min")
    empty = {"type": "FeatureCollection", "features": [], "counts": {}}
    if len(b["bx"]) == 0:
        return empty
    ix, iy, tot, cov = K.grid_cells(b["bx"], b["by"], b["bdist"], cell, threshold, min_bldg)
    if len(ix) < 10:
        return empty
    x = cov / tot
    z = K.getis_ord_gi_star(ix, iy, x, cell, band)
    cls = K.classify_gi(z)
    props = [{"city": city, "cell": "%d_%d" % (a, c), "n_bldg": int(t),
              "pct_cov800": round(100 * float(xv), 2), "gi_z": round(float(zv), 3), "class": str(k)}
             for a, c, t, xv, zv, k in zip(ix.tolist(), iy.tolist(), tot.tolist(), x.tolist(),
                                           z.tolist(), cls.tolist())]
    fc = K.cells_to_fc(ix, iy, cell, store._FWD.transform, props)
    order = ["Hot 99%", "Hot 95%", "Not significant", "Cold 95%", "Cold 99%"]
    fc["counts"] = {k: int(np.sum(cls == k)) for k in order}
    return fc


def analysis_distribution(city):
    """Mean center, standard distance, 1-sd ellipse, NN ratio — distribution.py parity."""
    cityname = catalog.CITY[city]["en"]
    pts = _city_schools(city)
    xs = pts.geometry.x.to_numpy()
    ys = pts.geometry.y.to_numpy()
    n = len(xs)
    if n < 2:
        raise ValueError("at least two schools are needed for the distribution statistics")
    mx, my = xs.mean(), ys.mean()
    dx, dy = xs - mx, ys - my
    sd = math.sqrt((dx ** 2 + dy ** 2).sum() / n)
    sx = math.sqrt((dx ** 2).sum() / n)
    sy = math.sqrt((dy ** 2).sum() / n)
    cov = (dx * dy).sum() / n
    theta = 0.5 * math.atan2(2 * cov, sx ** 2 - sy ** 2)
    dmat = np.hypot(xs[:, None] - xs[None, :], ys[:, None] - ys[None, :])
    np.fill_diagonal(dmat, np.inf)
    nn_mean = float(dmat.min(axis=1).mean())
    area = _boundary(city)[3]
    expected = 0.5 / math.sqrt(n / area)
    R = nn_mean / expected
    se = math.sqrt((4 - math.pi) / (4 * math.pi) / n)
    z = (nn_mean - expected) / (expected * se) if se else None

    # geometries
    from shapely.geometry import Polygon
    mean_pt = Point(mx, my)
    std_circle = mean_pt.buffer(sd, 64)
    ct, st = math.cos(theta), math.sin(theta)
    ring = []
    for k in range(73):
        a = 2 * math.pi * k / 72
        px, py = 2.4477 * sx * math.cos(a), 2.4477 * sy * math.sin(a)
        ring.append((mx + px * ct - py * st, my + px * st + py * ct))
    ellipse = Polygon(ring)

    lng0, lat0 = store._FWD.transform(mx, my)
    stats = {"city": cityname, "n": n, "mean_x": round(mx, 1), "mean_y": round(my, 1),
             "std_dist_m": round(sd, 1), "sx": round(sx, 1), "sy": round(sy, 1),
             "theta_deg": round(math.degrees(theta), 1),
             "nn_mean_m": round(nn_mean, 1), "nn_expected_m": round(expected, 1),
             "nn_ratio": round(R, 3), "nn_z": round(z, 2) if z else None,
             "mean_center": [round(lng0, 6), round(lat0, 6)]}
    return {
        "stats": stats,
        "mean_center": geom_to_fc(mean_pt, {"city": cityname, "n": n}),
        "std_distance": geom_to_fc(std_circle, {"radius_m": round(sd, 1)}),
        "std_ellipse": geom_to_fc(ellipse, {"city": cityname}),
    }


def analysis_kde(city, bandwidth=800.0, pixel=50.0):
    """Quartic KDE (QGIS parity) rendered to a PNG overlay + WGS84 bounds."""
    from PIL import Image
    import io, base64

    pts = _city_schools(city)
    minx, miny, maxx, maxy = _boundary(city)[2]
    minx -= bandwidth; miny -= bandwidth; maxx += bandwidth; maxy += bandwidth
    w = int(math.ceil((maxx - minx) / pixel))
    h = int(math.ceil((maxy - miny) / pixel))
    acc = K.quartic_kde(pts.geometry.x.to_numpy(), pts.geometry.y.to_numpy(),
                        minx, maxy, pixel, w, h, bandwidth)
    vmax = float(acc.max()) or 1.0

    ramp = np.array([list(int(c[i:i + 2], 16) for i in (1, 3, 5))
                     for c in catalog.KDE_RAMP], dtype=float)
    t = acc / vmax * (len(ramp) - 1)
    i0 = np.clip(np.floor(t).astype(int), 0, len(ramp) - 2)
    frac = (t - i0)[..., None]
    rgb = ramp[i0] * (1 - frac) + ramp[i0 + 1] * frac
    alpha = np.where(acc > 0, np.clip(acc / vmax * 255 * 1.6, 0, 255), 0).astype(np.uint8)
    im = Image.fromarray(np.dstack([rgb.astype(np.uint8), alpha]), "RGBA")

    buf = io.BytesIO()
    im.save(buf, format="PNG", compress_level=3)
    b64 = base64.b64encode(buf.getvalue()).decode()

    # bounds -> wgs84 (transform the 4 corners)
    lls = [store._FWD.transform(x, y) for x, y in
           [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]]
    lngs = [p[0] for p in lls]; lats = [p[1] for p in lls]
    return {"png": "data:image/png;base64," + b64,
            "bounds": [[min(lats), min(lngs)], [max(lats), max(lngs)]],
            "bandwidth": bandwidth, "pixel": pixel, "vmax": round(vmax, 4)}


def analysis_nearest_from_point(city, lng, lat):
    """Network distance from an arbitrary map point to every school (Dijkstra, stops at the last school)."""
    net = _load_net(city)
    adj = _graph(city)
    X, Y = store._INV.transform(lng, lat)
    d2 = (net["verts"][:, 0] - X) ** 2 + (net["verts"][:, 1] - Y) ** 2
    src = int(np.argmin(d2))
    src_gap = float(math.sqrt(d2[src]))

    nodes = []
    for sid in net["schools"]:
        snap = net["snap"].get(sid)
        nodes.append(int(snap[1]) if isinstance(snap, (tuple, list)) else None)
    dist = K.dijkstra_to_targets(adj, src, nodes)

    results = []
    for sid, snode in zip(net["schools"], nodes):
        d = dist.get(snode)
        if d is None:
            continue
        results.append({"school_id": sid, "dist_m": round(d + src_gap + _school_gap(net, sid), 1)})
    results.sort(key=lambda r: r["dist_m"])

    sc = _city_schools(city)
    names = dict(zip(sc["school_id"], sc["name_ar"]))
    for r in results:
        r["name_ar"] = names.get(r["school_id"])
    return {"point": [lng, lat], "snap_gap_m": round(src_gap, 1), "schools": results}


def warm(city):
    """Load and index everything the analyses share for one city (run once in the background
    at start-up, so the first click is as fast as the hundredth)."""
    _load_net(city)
    _graph(city)
    _mincost(city)
    _bld(city)
    _demand(city)
    _boundary(city)
    _schools_gdf()
    try:
        _zones_gdf(city)
        _building_zone_map(city)
    except Exception:
        pass


# ------------------------------------------------------------------ ready-made stats
def ready_stats():
    import json
    out = {}
    for f in ("summary_stats.json", "distribution_stats.json"):
        p = os.path.join(catalog.PROC, f)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                out[f.replace(".json", "")] = json.load(fh)
    import csv
    p = os.path.join(catalog.PROC, "coverage_by_shiakha.csv")
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig") as fh:
            out["coverage_csv"] = list(csv.DictReader(fh))
    return out
