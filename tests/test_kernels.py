# -*- coding: utf-8 -*-
"""Parity tests: every kernel must reproduce the original loop-based implementation.

Run from platform/:   python -m unittest discover -s tests -v
(numpy only; the Dijkstra test also uses networkx when it is installed)
"""
import heapq
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import kernels as K  # noqa: E402


# ---------------------------------------------------------------- original implementations
def old_hotspot(bx, by, bdist, threshold, cell, band, min_bldg):
    cells = {}
    for i in range(len(bx)):
        k = (int(bx[i] // cell), int(by[i] // cell))
        c = cells.setdefault(k, [0, 0])
        c[0] += 1
        if bdist[i] <= threshold:
            c[1] += 1
    keys = [k for k, v in cells.items() if v[0] >= min_bldg]
    cx = np.array([(k[0] + 0.5) * cell for k in keys])
    cy = np.array([(k[1] + 0.5) * cell for k in keys])
    x = np.array([cells[k][1] / cells[k][0] for k in keys])
    n = len(x)
    xbar = x.mean()
    S = math.sqrt((x ** 2).sum() / n - xbar ** 2)
    z = np.zeros(n)
    for i in range(n):
        d2 = (cx - cx[i]) ** 2 + (cy - cy[i]) ** 2
        wij = (d2 <= band ** 2).astype(float)
        wsum = wij.sum()
        g = (wij * x).sum()
        denom = S * math.sqrt((n * (wij ** 2).sum() - wsum ** 2) / (n - 1))
        z[i] = (g - xbar * wsum) / denom if denom > 0 else 0.0
    return {k: (cells[k][0], cells[k][1], z[i]) for i, k in enumerate(keys)}


def old_kde(xs, ys, minx, maxy, pixel, w, h, bandwidth):
    gx = minx + (np.arange(w) + 0.5) * pixel
    gy = maxy - (np.arange(h) + 0.5) * pixel
    GX, GY = np.meshgrid(gx, gy)
    R2 = bandwidth ** 2
    acc = np.zeros((h, w), dtype=np.float64)
    for px, py in zip(xs, ys):
        d2 = (GX - px) ** 2 + (GY - py) ** 2
        m = d2 <= R2
        acc[m] += (1.0 - d2[m] / R2) ** 2
    return acc


def old_dijkstra(adj, src):
    dist = {src: 0.0}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        for v, l in adj.get(u, ()):
            nd = d + l
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


def make_buildings(n=40000, seed=7):
    rng = np.random.default_rng(seed)
    cx = rng.choice([310000, 313500, 316000], n) + rng.normal(0, 1800, n)
    cy = rng.choice([3326000, 3328500], n) + rng.normal(0, 1500, n)
    d = np.abs(rng.normal(900, 700, n))
    d[rng.random(n) < 0.01] = np.nan                 # a few buildings with no distance
    return cx, cy, d


class HotspotParity(unittest.TestCase):
    def run_case(self, threshold, cell, band, min_bldg):
        bx, by, bd = make_buildings()
        old = old_hotspot(bx, by, bd, threshold, cell, band, min_bldg)
        ix, iy, tot, cov = K.grid_cells(bx, by, bd, cell, threshold, min_bldg)
        z = K.getis_ord_gi_star(ix, iy, cov / tot, cell, band)
        self.assertEqual(len(old), len(ix))
        for i in range(len(ix)):
            n_old, c_old, z_old = old[(int(ix[i]), int(iy[i]))]
            self.assertEqual(n_old, tot[i])
            self.assertEqual(c_old, cov[i])
            self.assertAlmostEqual(z_old, z[i], places=9)

    def test_default_parameters(self):
        self.run_case(800.0, 250.0, 1000.0, 5)

    def test_other_threshold_and_band(self):
        self.run_case(400.0, 250.0, 750.0, 5)

    def test_small_cells(self):
        self.run_case(1200.0, 100.0, 500.0, 3)

    def test_classes(self):
        z = np.array([3, 2.0, 0, -2.0, -3, 1.96, -1.96, 2.576])
        self.assertEqual(list(K.classify_gi(z)),
                         ["Hot 99%", "Hot 95%", "Not significant", "Cold 95%", "Cold 99%",
                          "Hot 95%", "Cold 95%", "Hot 99%"])


class KdeParity(unittest.TestCase):
    def test_matches_full_grid(self):
        rng = np.random.default_rng(3)
        xs = 310000 + rng.random(10) * 9000
        ys = 3326000 + rng.random(10) * 7000
        bw, px = 800.0, 50.0
        minx, miny, maxx, maxy = 310000 - bw, 3326000 - bw, 319000 + bw, 3333000 + bw
        w = int(math.ceil((maxx - minx) / px))
        h = int(math.ceil((maxy - miny) / px))
        a = old_kde(xs, ys, minx, maxy, px, w, h, bw)
        b = K.quartic_kde(xs, ys, minx, maxy, px, w, h, bw)
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-12)

    def test_point_outside_grid_is_ignored(self):
        acc = K.quartic_kde([0.0], [0.0], 1000.0, 2000.0, 50.0, 20, 20, 100.0)
        self.assertEqual(acc.sum(), 0.0)


class ZoneStatsParity(unittest.TestCase):
    def test_matches_per_zone_masks(self):
        rng = np.random.default_rng(5)
        n, zc = 5000, 12
        b2z = rng.integers(-1, zc, n)
        bd = np.abs(rng.normal(900, 500, n))
        thr = 800.0
        cnt, within, mean = K.zone_stats(b2z, bd, thr, zc)
        for zi in range(zc):
            m = b2z == zi
            self.assertEqual(int(cnt[zi]), int(m.sum()))
            if m.sum():
                self.assertEqual(int(within[zi]), int(np.sum(bd[m] <= thr)))
                self.assertAlmostEqual(float(mean[zi]), float(np.mean(bd[m])), places=9)


class CellsToFc(unittest.TestCase):
    def test_ring_matches_box_orientation_and_count(self):
        ix = np.array([1, 2]); iy = np.array([3, 3])
        fc = K.cells_to_fc(ix, iy, 250.0, lambda x, y: (x / 1e5, y / 1e5),
                           [{"a": 1}, {"a": 2}], ndigits=6)
        ring = fc["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(len(ring), 5)
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(ring[0], [round(500 / 1e5, 6), round(750 / 1e5, 6)])   # (maxx, miny)
        self.assertEqual(ring[1], [round(500 / 1e5, 6), round(1000 / 1e5, 6)])  # (maxx, maxy)
        self.assertEqual(fc["features"][1]["properties"], {"a": 2})


class DijkstraEarlyExit(unittest.TestCase):
    def test_matches_full_search(self):
        rng = np.random.default_rng(11)
        n, m = 3000, 9000
        adj = {}
        for _ in range(m):
            a, b = int(rng.integers(0, n)), int(rng.integers(0, n))
            l = float(rng.random() * 200 + 5)
            adj.setdefault(a, []).append((b, l))
            adj.setdefault(b, []).append((a, l))
        full = old_dijkstra(adj, 0)
        targets = [int(t) for t in rng.integers(0, n, 10)] + [None]
        got = K.dijkstra_to_targets(adj, 0, targets)
        for t in targets:
            if t is None:
                continue
            if t in full:
                self.assertAlmostEqual(got[t], full[t], places=9)
            else:
                self.assertNotIn(t, got)


if __name__ == "__main__":
    unittest.main()
