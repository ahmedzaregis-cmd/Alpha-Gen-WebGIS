# -*- coding: utf-8 -*-
"""Numeric kernels behind the analyses.

Everything here depends on numpy only (no shapely / geopandas / rasterio), so each
function can be unit-tested in isolation and compared against the original loop-based
implementation (see tests/test_kernels.py). The results are the same as before; the
cost is not: the per-building and per-cell Python loops became array operations.
"""
import heapq
import math

import numpy as np


# ------------------------------------------------------------------ Gi* hot spots
def grid_cells(bx, by, bdist, cell, threshold, min_bldg):
    """Bucket building centroids into square cells.

    Returns (ix, iy, total, covered): integer cell indices plus, per cell, the number of
    buildings and the number within `threshold` of a school. Only cells holding at least
    `min_bldg` buildings are returned, sorted by (ix, iy).
    """
    ix = np.floor(bx / cell).astype(np.int64)
    iy = np.floor(by / cell).astype(np.int64)
    ix0, iy0 = ix.min(), iy.min()
    width = int(iy.max() - iy0) + 1
    key = (ix - ix0) * width + (iy - iy0)
    uniq, inv, total = np.unique(key, return_inverse=True, return_counts=True)
    covered = np.bincount(inv, weights=(bdist <= threshold).astype(np.float64),
                          minlength=len(uniq))
    keep = total >= min_bldg
    uniq, total, covered = uniq[keep], total[keep], covered[keep]
    return (uniq // width + ix0, uniq % width + iy0, total, covered.astype(np.int64))


def getis_ord_gi_star(ix, iy, x, cell, band):
    """Getis-Ord Gi* z-scores with binary distance-band weights on a regular grid.

    Cell centres sit on a lattice, so every neighbour within `band` is found by testing a
    small set of integer lattice offsets (about 49 for a 250 m cell and a 1000 m band)
    instead of comparing every cell with every other cell. Weights include the cell
    itself, exactly like the original implementation.
    """
    n = len(x)
    xbar = x.mean()
    s = math.sqrt((x ** 2).sum() / n - xbar ** 2)

    reach = int(math.floor(band / cell)) + 1
    width = int(iy.max() - iy.min()) + 1 + 2 * reach
    iy_base = iy.min() - reach
    ky = iy - iy_base
    key = ix * width + ky                      # unique per cell, sortable
    order = np.argsort(key)
    skey, sx = key[order], x[order]

    wsum = np.zeros(n)
    g = np.zeros(n)
    band2 = band ** 2
    for a in range(-reach, reach + 1):
        for b in range(-reach, reach + 1):
            if (a * cell) ** 2 + (b * cell) ** 2 > band2:
                continue
            ny = ky + b
            ok = (ny >= 0) & (ny < width)
            nkey = (ix + a) * width + ny
            pos = np.searchsorted(skey, nkey)
            pos[pos >= n] = n - 1
            hit = ok & (skey[pos] == nkey)
            wsum += hit
            g += np.where(hit, sx[pos], 0.0)

    with np.errstate(divide="ignore", invalid="ignore"):
        denom = s * np.sqrt((n * wsum - wsum ** 2) / (n - 1))
        z = np.where(denom > 0, (g - xbar * wsum) / denom, 0.0)
    return z


def classify_gi(z):
    """z-scores -> Gi* class labels (same break points as the QGIS workflow)."""
    return np.select(
        [z >= 2.576, z >= 1.96, z <= -2.576, z <= -1.96],
        ["Hot 99%", "Hot 95%", "Cold 99%", "Cold 95%"], default="Not significant")


def cells_to_fc(ix, iy, cell, to_lnglat, props, ndigits=6):
    """Square grid cells -> WGS84 GeoJSON FeatureCollection, with one batched transform.

    `to_lnglat(xs, ys)` is a vectorised projection (pyproj Transformer.transform).
    `props` is a list of per-cell property dicts. The ring order matches shapely.box.
    """
    x0 = ix * float(cell)
    y0 = iy * float(cell)
    x1 = x0 + cell
    y1 = y0 + cell
    xs = np.stack([x1, x1, x0, x0, x1], axis=1)
    ys = np.stack([y0, y1, y1, y0, y0], axis=1)
    lng, lat = to_lnglat(xs.ravel(), ys.ravel())
    lng = np.round(np.asarray(lng).reshape(xs.shape), ndigits)
    lat = np.round(np.asarray(lat).reshape(ys.shape), ndigits)
    rings = np.stack([lng, lat], axis=2).tolist()
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": props[i],
                          "geometry": {"type": "Polygon", "coordinates": [rings[i]]}}
                         for i in range(len(props))]}


# ------------------------------------------------------------------ zone statistics
def zone_stats(b2z, bdist, threshold, n_zones):
    """Per-zone building counts, buildings within `threshold`, and mean distance.

    `b2z` maps each building to a zone index (-1 = outside every zone). One pass with
    bincount replaces a boolean mask per zone (zones x buildings comparisons).
    """
    ok = b2z >= 0
    z = b2z[ok]
    d = bdist[ok]
    n = np.bincount(z, minlength=n_zones)
    w = np.bincount(z[d <= threshold], minlength=n_zones)
    dsum = np.bincount(z, weights=d, minlength=n_zones)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.where(n > 0, dsum / n, np.nan)
    return n, w, mean


# ------------------------------------------------------------------ KDE
def quartic_kde(xs, ys, minx, maxy, pixel, w, h, bandwidth):
    """Quartic-kernel density on a w x h grid (row 0 = north).

    Each point only touches the pixels inside its bandwidth window rather than the whole
    raster, which is what made the original slow on large cities and wide bandwidths.
    """
    gx = minx + (np.arange(w) + 0.5) * pixel
    gy = maxy - (np.arange(h) + 0.5) * pixel
    r2 = bandwidth ** 2
    acc = np.zeros((h, w), dtype=np.float64)
    ngy = -gy                                  # ascending, for searchsorted
    for px, py in zip(xs, ys):
        j0 = int(np.searchsorted(gx, px - bandwidth, "left"))
        j1 = int(np.searchsorted(gx, px + bandwidth, "right"))
        i0 = int(np.searchsorted(ngy, -(py + bandwidth), "left"))
        i1 = int(np.searchsorted(ngy, -(py - bandwidth), "right"))
        if j0 >= j1 or i0 >= i1:
            continue
        d2 = ((gx[j0:j1] - px) ** 2)[None, :] + ((gy[i0:i1] - py) ** 2)[:, None]
        k = np.where(d2 <= r2, (1.0 - d2 / r2) ** 2, 0.0)
        acc[i0:i1, j0:j1] += k
    return acc


# ------------------------------------------------------------------ network search
def dijkstra_to_targets(adj, src, targets):
    """Shortest distances from `src`, stopping once every node in `targets` is settled.

    Searching the whole network for ten schools was wasteful: the loop now ends as soon
    as the farthest school has been reached.
    """
    remaining = set(t for t in targets if t is not None)
    dist = {src: 0.0}
    done = set()
    pq = [(0.0, src)]
    while pq and remaining:
        d, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        remaining.discard(u)
        for v, length in adj.get(u, ()):
            nd = d + length
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return {t: dist[t] for t in targets if t in dist and t in done}
