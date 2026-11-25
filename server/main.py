# -*- coding: utf-8 -*-
"""Alpha GIS Platform — FastAPI backend.

Run:  python -m uvicorn server.main:app --port 8765   (from platform/)
  or:  python server/main.py

Speed model (v1.3)
  * every response body is built once, as bytes, and kept (layers, catalog, stats, analyses);
  * bodies over 1 KB are gzip-compressed once, not once per request;
  * ETags are stable across restarts, so the browser revalidates with a tiny 304;
  * two requests for the same analysis share one computation instead of running it twice;
  * at start-up a background thread loads the data and runs the default analyses, so the
    first dashboard visit and the first click are served from memory.
"""
import gzip
import hashlib
import inspect
import json
import os
import sys
import threading
import time
import traceback
from collections import OrderedDict
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Optional

import catalog
import store
import analysis
import raster as raster_svc

try:                                    # much faster than json for large GeoJSON: pip install orjson
    import orjson as _orjson

    def _dumps(obj):
        return _orjson.dumps(obj, option=_orjson.OPT_SERIALIZE_NUMPY)
    JSON_ENGINE = "orjson"
except Exception:                       # pragma: no cover - optional
    def _np_default(o):
        if hasattr(o, "tolist"):
            return o.tolist()
        if hasattr(o, "item"):
            return o.item()
        raise TypeError(type(o))

    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                          default=_np_default).encode("utf-8")
    JSON_ENGINE = "json"

try:                                    # does this Starlette leave pre-encoded bodies alone?
    import starlette.middleware.gzip as _starlette_gzip
    _PRECOMPRESS = "content_encoding_set" in inspect.getsource(_starlette_gzip)
except Exception:                       # pragma: no cover
    _PRECOMPRESS = False


@asynccontextmanager
async def _lifespan(_app):
    if os.environ.get("ALPHA_NO_WARM") != "1":
        threading.Thread(target=_warm, name="alpha-warm", daemon=True).start()
    yield


app = FastAPI(title="Alpha GIS Platform — روضات جيل ألفا", version="1.3.0", lifespan=_lifespan)
# fallback for anything not pre-compressed below (static files, rasters)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

STATIC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static"))


# ------------------------------------------------------------------ response payloads
class _Payload:
    """An immutable response body: raw bytes, the same bytes gzipped once, and an ETag."""
    __slots__ = ("raw", "gz", "etag", "size")

    def __init__(self, raw, etag=None):
        self.raw = raw
        self.gz = (gzip.compress(raw, compresslevel=6, mtime=0)
                   if _PRECOMPRESS and len(raw) > 1024 else None)
        self.etag = etag or '"%s"' % hashlib.md5(raw).hexdigest()[:20]
        self.size = len(raw) + (len(self.gz) if self.gz else 0)


def _not_modified(request, etag):
    inm = request.headers.get("if-none-match")
    return inm is not None and etag in [x.strip() for x in inm.split(",")]


def _send(request, payload, use_etag=True, media="application/json"):
    headers = {"Vary": "Accept-Encoding", "Cache-Control": "no-cache"}
    if use_etag:
        headers["ETag"] = payload.etag
        if _not_modified(request, payload.etag):
            return Response(status_code=304, headers=headers)
    if payload.gz and "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
        return Response(payload.gz, media_type=media, headers=headers)
    return Response(payload.raw, media_type=media, headers=headers)


# ------------------------------------------------------------------ caches
_VERSION = 0                         # bumped by every edit
_LOCK = threading.Lock()
_META = {}                           # layer id -> catalog entry

_AN = OrderedDict()                  # analysis key -> _Payload
_AN_MAX = 64
_AN_KEYLOCKS = {}

_LAYERS = OrderedDict()              # layer key -> _Payload
_LAYER_BUDGET = 600 * 1024 * 1024    # bytes (raw + gzip) kept in memory
_layer_bytes = 0
_LAYER_KEYLOCKS = {}

_CATALOG = {"payload": None, "obj": None}
_WARM = {"state": "idle", "seconds": None, "error": None}


def get_catalog():
    if _CATALOG["obj"] is None:
        with _LOCK:
            if _CATALOG["obj"] is None:
                obj = catalog.build_catalog()
                _CATALOG["payload"] = _Payload(_dumps(obj))
                for m in obj["layers"] + obj["edu_layers"]:
                    _META[m["id"]] = m
                _CATALOG["obj"] = obj
    return _CATALOG["obj"]


def _data_stamp():
    out = []
    for p in (catalog.GPKG, catalog.GPKG_EDIT, catalog.GPKG_EDU):
        try:
            out.append(int(os.stat(p).st_mtime))
        except OSError:
            out.append(0)
    return tuple(out)


def _bump_version():
    global _VERSION, _layer_bytes
    with _LOCK:
        _VERSION += 1
        _LAYERS.clear()
        _layer_bytes = 0
        _AN.clear()
    analysis.invalidate()


def _keyed(store_dict, locks, key, build, budget=None):
    """Return the cached _Payload for `key`, building it once even if requests arrive together."""
    global _layer_bytes
    with _LOCK:
        hit = store_dict.get(key)
        if hit is not None:
            store_dict.move_to_end(key)
            return hit
        lk = locks.setdefault(key, threading.Lock())
    with lk:
        with _LOCK:
            hit = store_dict.get(key)
            if hit is not None:
                return hit
            gen = _VERSION
        payload = build()
        with _LOCK:
            if gen == _VERSION:                       # an edit during the build makes it stale
                store_dict[key] = payload
                if budget is not None:
                    _layer_bytes += payload.size
                    while _layer_bytes > budget and len(store_dict) > 1:
                        _k, old = store_dict.popitem(last=False)
                        _layer_bytes -= old.size
                else:
                    while len(store_dict) > _AN_MAX:
                        store_dict.popitem(last=False)
            locks.pop(key, None)
        return payload


def _memo(key, fn):
    """Analysis results, as ready-to-send bytes."""
    return _keyed(_AN, _AN_KEYLOCKS, key, lambda: _Payload(_dumps(fn())))


class _Static(StaticFiles):
    """Vendor libraries are cached for a week; app files are revalidated every time (ETag)."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code in (200, 304):
            resp.headers["Cache-Control"] = (
                "public, max-age=604800, immutable" if path.startswith("vendor/") else "no-cache")
        return resp


# ------------------------------------------------------------------ models
class EditBody(BaseModel):
    layer: str
    action: str                       # create | update | delete
    feature: Optional[Any] = None
    fid: Optional[int] = None
    source: Optional[str] = None


class AnalysisBody(BaseModel):
    city: str
    threshold: Optional[float] = 800
    per_school: Optional[bool] = False
    cell: Optional[float] = 250
    band: Optional[float] = 1000
    min_bldg: Optional[int] = 5
    bandwidth: Optional[float] = 800
    pixel: Optional[float] = 50
    lng: Optional[float] = None
    lat: Optional[float] = None


# ------------------------------------------------------------------ routes
@app.get("/api/catalog")
def api_catalog(request: Request):
    get_catalog()
    return _send(request, _CATALOG["payload"])


@app.get("/api/health")
def api_health():
    return {"ok": True, "version": app.version, "json": JSON_ENGINE,
            "precompressed": _PRECOMPRESS, "warm": dict(_WARM)}


def _layer_payload(layer_id, source=None, subset=None, full=False):
    get_catalog()
    meta = _META.get(layer_id)
    sub = subset or (meta.get("subset") if meta else None)
    key = (layer_id, source, sub, bool(full))
    etag = '"%s"' % hashlib.md5(repr((key, _VERSION, _data_stamp())).encode()).hexdigest()[:20]

    def build():
        # full=true: every field and no simplification (for export)
        fc, _m = store.layer_geojson(layer_id, source=source, simplify=0 if full else None,
                                     thin=not full, subset=sub, cache=False)
        return _Payload(_dumps(fc), etag)

    if full:                                          # exports are big and rare: don't keep them
        return build()
    return _keyed(_LAYERS, _LAYER_KEYLOCKS, key + (_VERSION,), build, budget=_LAYER_BUDGET)


@app.get("/api/layers/{layer_id}")
def api_layer(layer_id: str, request: Request, source: Optional[str] = None,
              subset: Optional[str] = None, full: bool = False):
    try:
        get_catalog()
        meta = _META.get(layer_id)
        sub = subset or (meta.get("subset") if meta else None)
        etag = '"%s"' % hashlib.md5(
            repr(((layer_id, source, sub, bool(full)), _VERSION, _data_stamp())).encode()
        ).hexdigest()[:20]
        if _not_modified(request, etag):              # answer 304 without touching the data
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
        return _send(request, _layer_payload(layer_id, source, subset, full))
    except KeyError:
        raise HTTPException(404, "layer not found: %s" % layer_id)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/api/layermeta/{layer_id}")
def api_layermeta(layer_id: str, source: Optional[str] = None):
    _, m = store.layer_geojson(layer_id, source=source)
    return m


@app.post("/api/edit")
def api_edit(body: EditBody):
    if body.action not in ("create", "update", "delete"):
        raise HTTPException(400, "bad action")
    if body.action != "delete" and not body.feature:
        raise HTTPException(400, "feature required")
    try:
        res = store.edit_feature(body.layer, body.action, body.feature,
                                 body.fid, body.source)
        _bump_version()
        return {"ok": True, "result": res,
                "edited_gpkg": os.path.exists(catalog.GPKG_EDIT)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/api/export/{layer_id}.geojson")
def api_export(layer_id: str, source: Optional[str] = None):
    fc, _ = store.layer_geojson(layer_id, source=source, simplify=0, thin=False, cache=False)
    return Response(_dumps(fc), media_type="application/geo+json",
                    headers={"Content-Disposition": 'attachment; filename="%s.geojson"' % layer_id})


# ------------------------------------------------------------------ analyses
def _city(body_city):
    if body_city not in ("nasr", "ps"):
        raise HTTPException(400, "city must be nasr|ps")
    return body_city


def _service_key(city, threshold, per_school=False):
    return ("svc", city, threshold, bool(per_school))


def _run(request, key, fn):
    try:
        return _send(request, _memo(key, fn), use_etag=False)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.post("/api/analysis/service-area")
def an_service_area(body: AnalysisBody, request: Request):
    city = _city(body.city)
    return _run(request, _service_key(city, body.threshold, body.per_school),
                lambda: analysis.analysis_service_area(city, body.threshold, bool(body.per_school)))


@app.post("/api/analysis/overlap")
def an_overlap(body: AnalysisBody, request: Request):
    city = _city(body.city)
    return _run(request, ("ovl", city, body.threshold),
                lambda: analysis.analysis_overlap(city, body.threshold))


@app.post("/api/analysis/coverage")
def an_coverage(body: AnalysisBody, request: Request):
    city = _city(body.city)
    return _run(request, ("cov", city, body.threshold),
                lambda: analysis.analysis_coverage(city, body.threshold))


@app.post("/api/analysis/hotspot")
def an_hotspot(body: AnalysisBody, request: Request):
    city = _city(body.city)
    return _run(request, ("hot", city, body.threshold, body.cell, body.band, body.min_bldg),
                lambda: analysis.analysis_hotspot(city, body.threshold, body.cell,
                                                  body.band, body.min_bldg))


@app.post("/api/analysis/distribution")
def an_distribution(body: AnalysisBody, request: Request):
    city = _city(body.city)
    return _run(request, ("dist", city), lambda: analysis.analysis_distribution(city))


@app.post("/api/analysis/kde")
def an_kde(body: AnalysisBody, request: Request):
    city = _city(body.city)
    return _run(request, ("kde", city, body.bandwidth, body.pixel),
                lambda: analysis.analysis_kde(city, body.bandwidth, body.pixel))


@app.post("/api/analysis/nearest-from-point")
def an_nearest(body: AnalysisBody, request: Request):
    city = _city(body.city)
    if body.lng is None or body.lat is None:
        raise HTTPException(400, "lng & lat required")
    try:                                                # every point is different: nothing to cache
        res = analysis.analysis_nearest_from_point(city, body.lng, body.lat)
        return _send(request, _Payload(_dumps(res)), use_etag=False)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/api/stats")
def api_stats(request: Request):
    return _run(request, ("stats",), analysis.ready_stats)


# ------------------------------------------------------------------ rasters
def _raster_meta(rid):
    cat = get_catalog()
    meta = next((r for r in cat["rasters"] if r["id"] == rid), None)
    if not meta:
        raise HTTPException(404, "raster not found")
    try:
        return raster_svc.render(meta)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


@app.get("/api/raster/{rid}.png")
def api_raster_png(rid: str):
    """The image itself as a binary PNG (a third lighter than base64, and the browser caches it)."""
    _raster_meta(rid)
    path = os.path.join(raster_svc.CACHE, rid + ".png")
    if not os.path.exists(path):
        raise HTTPException(404, "raster image missing")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/raster/{rid}")
def api_raster(rid: str):
    m = _raster_meta(rid)
    return {"png": "/api/raster/%s.png" % rid, "bounds": m["bounds"]}


# ------------------------------------------------------------------ warm-up
def _warm():
    """Runs once in the background after start-up. Every step is optional: a failure is
    logged and the platform keeps working, it simply computes that item on first use."""
    t0 = time.time()
    _WARM["state"] = "running"

    def step(label, fn):
        try:
            fn()
        except Exception as e:                        # pragma: no cover - depends on local data
            print("[warm] %s skipped: %s" % (label, e))
            _WARM["error"] = "%s: %s" % (label, e)

    cat = None
    try:
        cat = get_catalog()
    except Exception as e:                            # pragma: no cover
        print("[warm] catalog failed: %s" % e)
    if cat:
        # default layers first: they are what the first screen asks for
        for m in cat["layers"] + cat["edu_layers"]:
            if m.get("default_on"):
                step("layer " + m["id"],
                     lambda m=m: _layer_payload(m["id"], m.get("source")))
    for city in ("nasr", "ps"):
        step("data " + city, lambda c=city: analysis.warm(c))
        # exactly what the dashboard and the analysis panel request first
        step("hotspot " + city, lambda c=city: _memo(
            ("hot", c, 800.0, 250.0, 1000.0, 5),
            lambda: analysis.analysis_hotspot(c, 800.0, 250.0, 1000.0, 5)))
        for th in (800.0, 400.0, 1200.0):
            step("coverage %s %d" % (city, th), lambda c=city, t=th: _memo(
                ("cov", c, t), lambda: analysis.analysis_coverage(c, t)))
            step("service-area %s %d" % (city, th), lambda c=city, t=th: _memo(
                _service_key(c, t), lambda: analysis.analysis_service_area(c, t, False)))
    step("stats", lambda: _memo(("stats",), analysis.ready_stats))
    _WARM["state"] = "done"
    _WARM["seconds"] = round(time.time() - t0, 1)
    print("[warm] finished in %.1f s" % _WARM["seconds"])


# ------------------------------------------------------------------ static
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"),
                        headers={"Cache-Control": "no-cache"})


app.mount("/static", _Static(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
