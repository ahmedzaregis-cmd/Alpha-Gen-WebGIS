# -*- coding: utf-8 -*-
"""Layer catalog — single source of truth for titles (EN/AR), colours and map presets.

Colours/labels are transcribed exactly from:
  - maps.py  (DIST_CLASSES/DIST_COLORS, service areas, overlap palette, coverage ramp, hotspot classes)
  - mapkit.py (raster ramp, school/boundary/road styles)
  - map1 PNG legend (mean center / std distance / ellipse)
  - atlas_kit.py (Education City / priority-site palette)
"""
import os

PROC = r"D:/EDF-GIS/مشروع روضات جيل ألفا/Processed"
GPKG = os.path.join(PROC, "alpha_accessibility.gpkg")
GPKG_EDU = os.path.join(PROC, "edu_city_proximity.gpkg")
GPKG_EDIT = os.path.join(PROC, "alpha_accessibility_edited.gpkg")

# ---------------------------------------------------------------- colours (maps.py)
DIST_CLASSES = [  # map3 graduated
    [0, 400, "0 - 400 m", "0 - 400 م", "#0d5c3f"],
    [400, 800, "400 - 800 m", "400 - 800 م", "#4a9a5c"],
    [800, 1200, "800 - 1200 m", "800 - 1200 م", "#f0c808"],
    [1200, 2000, "1200 - 2000 m", "1200 - 2000 م", "#e07b39"],
    [2000, 10 ** 9, "> 2000 m", "> 2000 م", "#a31d1d"],
]
COV_CLASSES = [  # map5 choropleth
    [0, 5, "0 - 5 %", "0 - 5 %", "#f7fcf0"],
    [5, 15, "5 - 15 %", "5 - 15 %", "#ccebc5"],
    [15, 30, "15 - 30 %", "15 - 30 %", "#7bccc4"],
    [30, 60, "30 - 60 %", "30 - 60 %", "#2b8cbe"],
    [60, 100.1, "60 - 100 %", "60 - 100 %", "#084081"],
]
OVERLAP_PAL = {  # map4 categorized (n_schools -> colour)
    2: "#1f78b4", 3: "#33a02c", 4: "#ff7f00", 5: "#e31a1c", 6: "#6a3d9a",
    7: "#b15928", 8: "#fb9a99", 9: "#a6cee3", 10: "#b2df8a",
}
OVERLAP_DEF = "#999999"
HOTSPOT_CLASSES = {  # map6
    "Hot 99%": ("#b30000", "Hot spot 99% (high coverage)", "نقاط ساخنة 99% (تغطية عالية)"),
    "Hot 95%": ("#fc8d59", "Hot spot 95%", "نقاط ساخنة 95%"),
    "Not significant": ("#e8e8e8", "Not significant", "غير دال"),
    "Cold 95%": ("#91bfdb", "Cold spot 95%", "نقاط باردة 95%"),
    "Cold 99%": ("#045a8d", "Cold spot 99% (low coverage)", "نقاط باردة 99% (تغطية منخفضة)"),
}
KDE_RAMP = ["#ffffff", "#fee8c8", "#fdbb84", "#e34a33", "#b30000"]  # mapkit.style_raster default
SUIT_RAMP = ["#a31d1d", "#e07b39", "#f0c808", "#4a9a5c", "#0d5c3f"]  # low -> high (project palette)
SCHOOL_COLOR = "#b3121b"
SCHOOL_LABEL = "#7b1a12"
ROAD_COLOR = "#b0b0b0"
BOUND_STROKE = "#3d3d3d"
MEAN_CENTER = "#1b3a5c"
STD_DIST = "#1b4e7a"
STD_ELLIPSE = "#7b5ea7"
ATLAS_NAVY = "#12355B"
ATLAS_AMBER = "#C8811A"

CITY = {
    "nasr": {"en": "Nasr City", "ar": "مدينة نصر", "key": "nasr"},
    "ps": {"en": "Port Said", "ar": "بورسعيد", "key": "ps"},
}

# ---------------------------------------------------------------- groups
GROUPS = [
    {"id": "ref", "en": "Reference layers", "ar": "المدخلات المرجعية"},
    {"id": "network", "en": "Network & buildings", "ar": "الشبكة والمباني"},
    {"id": "service", "en": "Service areas", "ar": "نطاقات الخدمة"},
    {"id": "stats", "en": "Statistics & analysis", "ar": "الإحصاء والتوزيع"},
    {"id": "raster", "en": "Raster layers", "ar": "الطبقات الشعاعية"},
    {"id": "edu", "en": "Education City proximity", "ar": "المسافة إلى المدينة التعليمية"},
]

# ---------------------------------------------------------------- helpers
def _schools(city):
    return {
        "id": "schools_32636", "group": "ref", "city": city, "geom": "point",
        "title_en": "Schools (KG proxy)", "title_ar": "المدارس (وكيل رياض الأطفال)",
        "opacity": 1.0, "editable": True, "default_on": True, "z": 60,
        "style": {"type": "point", "color": SCHOOL_COLOR, "radius": 6,
                  "stroke": "#ffffff", "weight": 1,
                  "label": {"field": "name_ar", "color": SCHOOL_LABEL, "size": 11, "bold": True}},
        "fields": ["school_id", "name_ar", "city", "admin_unit", "neighborhood",
                   "recommendation", "gov_proxy", "kg_proxy", "kg_status", "language_type", "source"],
        "popup_fields": ["school_id", "name_ar", "neighborhood", "gov_proxy", "kg_status"],
        "pad": 2500,
    }


def _boundary(city):
    return {
        "id": "%s_boundary_32636" % city, "group": "ref", "city": city, "geom": "poly",
        "title_en": "City / district boundary", "title_ar": "حدود المدينة / المنطقة",
        "opacity": 1.0, "editable": True, "default_on": True, "z": 10,
        "style": {"type": "fill", "fill": "#ffffff", "fillOpacity": 0.0,
                  "stroke": BOUND_STROKE, "weight": 2},
        "fields": ["NAME_2", "NAME_1", "GOV_AR", "POP_EST", "Gov_A_Name", "GOV_CODE"],
        "popup_fields": ["NAME_2", "GOV_AR", "Gov_A_Name"],
        "pad": 2500,
    }


def _roads(city, layer_id=None, en="Walkable network", ar="شبكة الطرق قابلة للمشي",
           color=ROAD_COLOR, weight=1, default_on=True, group="network", z=20, fields=None,
           popup_fields=None):
    return {
        "id": layer_id or ("roads_walk_" + city), "group": group, "city": city, "geom": "line",
        "title_en": en, "title_ar": ar,
        "opacity": 1.0, "editable": True, "default_on": default_on, "z": z,
        "style": {"type": "line", "color": color, "weight": weight, "opacity": 0.9},
        "fields": fields or ["osm_id", "highway", "name", "surface", "lit"],
        "popup_fields": popup_fields or ["name", "highway"],
        "pad": 2500,
    }


def _service(city, t):
    fills = {400: ("#2e7d4f", "#14532d", 190), 800: ("#8fd3a0", "#2e7d4f", 160),
             1200: ("#ffe08a", "#c9a227", 150)}
    fill, stroke, alpha = fills[t]
    return {
        "id": "service_area_%d_%s" % (t, city), "group": "service", "city": city, "geom": "poly",
        "title_en": "Service area %d m" % t, "title_ar": "نطاق الخدمة %d م" % t,
        "opacity": round(alpha / 255.0, 3), "editable": True, "default_on": False, "z": 30 + t // 100,
        "style": {"type": "fill", "fill": fill, "fillOpacity": round(alpha / 255.0, 3),
                  "stroke": stroke, "weight": 1},
        "fields": ["threshold"],
        "popup_fields": ["threshold"],
        "pad": 2500,
    }


def _per_school_service(city, t):
    return {
        "id": "school_service_%d_%s" % (t, city), "group": "service", "city": city, "geom": "poly",
        "title_en": "Per-school service %d m" % t, "title_ar": "نطاق كل مدرسة %d م" % t,
        "opacity": 0.35, "editable": False, "default_on": False, "z": 29 + t // 100,
        "style": {"type": "fill", "fill": "#8fd3a0", "fillOpacity": 0.30,
                  "stroke": "#2e7d4f", "weight": 0.6},
        "fields": ["school_id", "threshold"],
        "popup_fields": ["school_id", "threshold"],
        "pad": 2500,
    }


def _buildings_net(city):
    return {
        "id": "buildings_net_" + city, "group": "network", "city": city, "geom": "poly",
        "title_en": "Buildings by network distance", "title_ar": "المباني حسب المسافة الشبكية",
        "opacity": 1.0, "editable": True, "default_on": False, "z": 40,
        "style": {"type": "graduated", "field": "dist_min", "classes": DIST_CLASSES,
                  "stroke": "#ffffff", "weight": 0.4},
        "fields": ["osm_id", "name", "nearest_id", "nearest_name", "dist_min",
                   "n400", "n800", "n1200", "n5m", "n10m", "n15m", "b_snap_m"],
        "popup_fields": ["nearest_name", "dist_min", "n800"],
        "pad": 2500,
    }


def _buildings_demand(city):
    return {
        "id": "buildings_demand_" + city, "group": "network", "city": city, "geom": "poly",
        "title_en": "Buildings + population proxy", "title_ar": "المباني + وكيل السكان",
        "opacity": 1.0, "editable": True, "default_on": False, "z": 39,
        "style": {"type": "graduated", "field": "dist_min", "classes": DIST_CLASSES,
                  "stroke": "#ffffff", "weight": 0.4},
        "fields": ["osm_id", "name", "nearest_name", "dist_min", "uns_pop", "n400", "n800", "n1200"],
        "popup_fields": ["nearest_name", "dist_min", "uns_pop"],
        "pad": 2500,
    }


def _buildings_res(city):
    return {
        "id": "buildings_res_" + city, "group": "network", "city": city, "geom": "poly",
        "title_en": "Residential buildings (OSM)", "title_ar": "المباني السكنية (OSM)",
        "opacity": 1.0, "editable": True, "default_on": False, "z": 38,
        "style": {"type": "fill", "fill": "#d9d9d9", "fillOpacity": 0.7,
                  "stroke": "#9e9e9e", "weight": 0.4},
        "fields": ["osm_id", "building", "name", "building:levels"],
        "popup_fields": ["building", "name"],
        "pad": 2500,
    }


def _overlap(city, t=800):
    return {
        "id": "overlap_class_%d_%s" % (t, city), "group": "stats", "city": city, "geom": "poly",
        "title_en": "Overlap (%d m)" % t, "title_ar": "التداخل (%d م)" % t,
        "opacity": 1.0, "editable": True, "default_on": False, "z": 50,
        "style": {"type": "categorized", "field": "n_schools",
                  "palette": {str(k): v for k, v in OVERLAP_PAL.items()},
                  "default": OVERLAP_DEF, "stroke": "#ffffff", "weight": 0.6,
                  "label_tpl_en": "%d schools", "label_tpl_ar": "%d مدارس"},
        "fields": ["n_schools", "area_km2"],
        "popup_fields": ["n_schools", "area_km2"],
        "pad": 2500,
    }


def _coverage_zone(city):
    return {
        "id": "coverage_zone_map_" + city, "group": "stats", "city": city, "geom": "poly",
        "title_en": "Shiakha coverage (% area, 800 m)", "title_ar": "تغطية الشياخة (% من المساحة، 800 م)",
        "opacity": 1.0, "editable": True, "default_on": False, "z": 48,
        "style": {"type": "graduated", "field": "pct_area_800", "classes": COV_CLASSES,
                  "stroke": "#ffffff", "weight": 0.6},
        "label": {"field": "shiakha", "color": "#222222", "size": 10},
        "fields": ["zone_id", "qism", "shiakha", "pop2017", "area_km2", "n_bldg", "n_schools",
                   "pct_area_400", "pct_area_800", "pct_area_1200",
                   "pct_bldg_400", "pct_bldg_800", "pct_bldg_1200",
                   "pct_pop_400", "pct_pop_800", "pct_pop_1200",
                   "avg_dist_m", "med_dist_m", "nsvc_400", "nsvc_800", "nsvc_1200"],
        "popup_fields": ["shiakha", "pop2017", "n_bldg", "pct_area_800", "pct_bldg_800"],
        "subset": "n_bldg > 0",
        "pad": 2500,
    }


def _hotspot(city):
    return {
        "id": "hotspot_cov800_" + city, "group": "stats", "city": city, "geom": "poly",
        "title_en": "Hot spot (Gi*) of 800 m coverage", "title_ar": "النقاط الساخنة/الباردة (Gi*) لتغطية 800 م",
        "opacity": 1.0, "editable": True, "default_on": False, "z": 52,
        "style": {"type": "categorized", "field": "class",
                  "palette": {k: v[0] for k, v in HOTSPOT_CLASSES.items()},
                  "labels_en": {k: v[1] for k, v in HOTSPOT_CLASSES.items()},
                  "labels_ar": {k: v[2] for k, v in HOTSPOT_CLASSES.items()},
                  "stroke": "#ffffff", "weight": 0.4},
        "fields": ["city", "cell", "n_bldg", "pct_cov800", "gi_z", "class"],
        "popup_fields": ["class", "gi_z", "pct_cov800", "n_bldg"],
        "pad": 2500,
    }


def _zones(city, layer_id=None, en="Shiakha units (2017)", ar="وحدات الشياخات (2017)",
           group="ref", default_on=False, z=15, extra_fields=None):
    fields = ["OBJECTID", "Gov_A_Name", "Section_A_Nam", "SubSection_A",
              "جمله_سكان_تقديرى2017", "ذكور_تقديرى2017", "اناث_تقديرى2017", "اسر_تقديرى2017"]
    fields += (extra_fields or [])
    return {
        "id": layer_id or ("zones_shiakha_" + city), "group": group, "city": city, "geom": "poly",
        "title_en": en, "title_ar": ar,
        "opacity": 1.0, "editable": True, "default_on": default_on, "z": z,
        "style": {"type": "fill", "fill": "#ffffff", "fillOpacity": 0.06,
                  "stroke": "#5b87b0", "weight": 0.8, "dash": "4 4"},
        "fields": fields,
        "popup_fields": ["Section_A_Nam", "جمله_سكان_تقديرى2017"],
        "pad": 2500,
    }


def _stats_point(city, kind):
    meta = {
        "mean_center": ("Mean center", "مركز المتوسط", MEAN_CENTER, 8),
        "std_distance": ("Standard distance", "المسافة المعيارية", STD_DIST, 7),
    }
    en, ar, color, radius = meta[kind]
    return {
        "id": "%s_%s" % (kind, city), "group": "stats", "city": city,
        "geom": "point" if kind == "mean_center" else "poly",
        "title_en": en, "title_ar": ar,
        "opacity": 1.0, "editable": False, "default_on": False, "z": 55,
        "style": ({"type": "point", "color": color, "radius": radius, "stroke": "#ffffff", "weight": 1.5}
                  if kind == "mean_center" else
                  {"type": "line", "color": STD_DIST, "weight": 2.5, "fill": "transparent", "dash": None}),
        "fields": ["city", "n", "radius_m"],
        "popup_fields": ["city", "n", "radius_m"],
        "pad": 2500,
    }


def _std_ellipse(city):
    return {
        "id": "std_ellipse_" + city, "group": "stats", "city": city, "geom": "poly",
        "title_en": "Standard deviation ellipse", "title_ar": "إهليلج الانحراف المعياري",
        "opacity": 1.0, "editable": False, "default_on": False, "z": 54,
        "style": {"type": "fill", "fill": STD_ELLIPSE, "fillOpacity": 0.10,
                  "stroke": STD_ELLIPSE, "weight": 2.5},
        "fields": ["city"],
        "popup_fields": ["city"],
        "pad": 2500,
    }


def _uncovered(city, t):
    return {
        "id": "uncovered_%d_%s" % (t, city), "group": "service", "city": city, "geom": "poly",
        "title_en": "Uncovered area (%d m)" % t, "title_ar": "المساحة غير المخدومة (%d م)" % t,
        "opacity": 0.5, "editable": False, "default_on": False, "z": 25,
        "style": {"type": "fill", "fill": "#f2f2f2", "fillOpacity": 0.5,
                  "stroke": "#bdbdbd", "weight": 0.6, "dash": "3 3"},
        "fields": ["threshold"],
        "popup_fields": ["threshold"],
        "pad": 2500,
    }


def _priority(city):
    return {
        "id": "priority_sites_" + city, "group": "stats", "city": city, "geom": "point",
        "title_en": "Priority sites (suitability)", "title_ar": "المواقع ذات الأولوية (الملاءمة)",
        "opacity": 1.0, "editable": True, "default_on": False, "z": 62,
        "style": {"type": "graduated_point", "field": "score",
                  "classes": [[85, 101, "Score ≥ 85", "نقاط ≥ 85", "#a31d1d"],
                              [70, 85, "70 - 85", "70 - 85", "#e07b39"],
                              [0, 70, "< 70", "< 70", "#f0c808"]],
                  "radius": 8, "stroke": "#ffffff", "weight": 1.2},
        "fields": ["site_id", "rank", "score", "zone", "uns_pop_1200", "bldg_1200",
                   "road_m", "nn_school_m", "x", "y"],
        "popup_fields": ["rank", "score", "zone"],
        "pad": 2500,
    }


def _edu_layer(lid, en, ar, geom, style, fields, popup, z=70, editable=True, default_on=True):
    return {
        "id": lid, "group": "edu", "city": None, "source": "edu", "geom": geom,
        "title_en": en, "title_ar": ar,
        "opacity": 1.0, "editable": editable, "default_on": default_on, "z": z,
        "style": style, "fields": fields, "popup_fields": popup, "pad": 0,
    }


def build_catalog():
    layers = []
    for city in ("nasr", "ps"):
        layers += [
            _schools(city), _boundary(city),
            _zones(city), _roads(city),
            _roads(city, "roads_main_" + city, "Main roads", "الطرق الرئيسية",
                   color="#8c8c8c", weight=1.6, default_on=False, z=19,
                   fields=["highway", "name"], popup_fields=["name", "highway"]),
            _buildings_res(city), _buildings_demand(city), _buildings_net(city),
            _service(city, 400), _service(city, 800), _service(city, 1200),
            _uncovered(city, 400), _uncovered(city, 800), _uncovered(city, 1200),
            _per_school_service(city, 400), _per_school_service(city, 800), _per_school_service(city, 1200),
            _overlap(city, 400), _overlap(city, 800), _overlap(city, 1200),
            _coverage_zone(city),
            _zones(city, "coverage_by_shiakha_" + city, "Coverage by shiakha (all fields)",
                   "التغطية حسب الشياخة (كل الحقول)", group="stats", default_on=False, z=47,
                   extra_fields=["zone_id", "n_bldg", "n_schools", "pct_area_800", "pct_bldg_800",
                                 "pct_pop_800", "avg_dist_m", "nsvc_800"]),
            _zones(city, "zones_analysis_" + city, "Zones analysis", "تحليل الوحدات",
                   group="stats", default_on=False, z=46,
                   extra_fields=["pop_dens", "pop_dens_built", "pct_bldg_800", "pct_pop_800",
                                 "unserved_800", "unserved_dens", "avg_dist_m"]),
            _hotspot(city), _stats_point(city, "mean_center"), _stats_point(city, "std_distance"),
            _std_ellipse(city), _priority(city),
        ]

    # ------------------------------------------------ rasters (server-rendered PNG overlays)
    rasters = [
        {"id": "kde_schools_nasr", "file": "kde_schools_nasr.tif", "group": "raster", "city": "nasr",
         "title_en": "KDE of schools (bandwidth 800 m)", "title_ar": "كثافة المدارس KDE (نطاق 800 م)",
         "ramp": KDE_RAMP, "opacity": 0.75, "default_on": False, "z": 44,
         "legend_en": "Kernel density (quartic, 800 m / 50 m px)",
         "legend_ar": "كثافة النواة (رباعية، 800 م / بكسل 50 م)"},
        {"id": "kde_schools_ps", "file": "kde_schools_ps.tif", "group": "raster", "city": "ps",
         "title_en": "KDE of schools (bandwidth 800 m)", "title_ar": "كثافة المدارس KDE (نطاق 800 م)",
         "ramp": KDE_RAMP, "opacity": 0.75, "default_on": False, "z": 44,
         "legend_en": "Kernel density (quartic, 800 m / 50 m px)",
         "legend_ar": "كثافة النواة (رباعية، 800 م / بكسل 50 م)"},
        {"id": "suitscore_nasr", "file": "suitscore_nasr.tif", "group": "raster", "city": "nasr",
         "title_en": "Suitability score", "title_ar": "درجة الملاءمة",
         "ramp": SUIT_RAMP, "opacity": 0.7, "default_on": False, "z": 43,
         "legend_en": "Composite suitability (12 – 92)", "legend_ar": "الملاءمة المركبة (12 – 92)"},
        {"id": "suitscore_ps", "file": "suitscore_ps.tif", "group": "raster", "city": "ps",
         "title_en": "Suitability score", "title_ar": "درجة الملاءمة",
         "ramp": SUIT_RAMP, "opacity": 0.7, "default_on": False, "z": 43,
         "legend_en": "Composite suitability (10 – 93)", "legend_ar": "الملاءمة المركبة (10 – 93)"},
        {"id": "hillshade_nasr", "file": "QGIS File/hillshade_nasr.tif", "group": "raster", "city": "nasr",
         "title_en": "Hillshade", "title_ar": "التظليل التضاريسي",
         "ramp": None, "opacity": 0.6, "default_on": False, "z": 12,
         "legend_en": "Hillshade (1 m vertical exaggeration)", "legend_ar": "تظليل تضاريسي"},
        {"id": "dem_colored_nasr", "file": "QGIS File/dem_colored.tif", "group": "raster", "city": "nasr",
         "title_en": "DEM (color relief)", "title_ar": "الارتفاع (ملون)",
         "ramp": None, "opacity": 0.8, "default_on": False, "z": 11,
         "legend_en": "Elevation 20 – 230 m (color relief)", "legend_ar": "الارتفاع 20 – 230 م"},
    ]

    # ------------------------------------------------ Education City (extra analysis)
    edu = [
        _edu_layer("edu_city_pt", "Education City", "المدينة التعليمية", "point",
                   {"type": "star", "color": ATLAS_NAVY, "radius": 12},
                   ["name", "kind"], ["name"], z=72, editable=False),
        _edu_layer("edu_rings", "Distance rings (2 / 4 / 6 km)", "حلقات المسافة (2 / 4 / 6 كم)", "line",
                   {"type": "line", "color": "#5B87B0", "weight": 1.6, "dash": "8 6", "fill": "transparent"},
                   ["dist_km"], ["dist_km"], z=66, editable=False, default_on=True),
        _edu_layer("edu_links", "Nearest-school links", "خطوط أقرب المدارس", "line",
                   {"type": "graduated_line", "field": "dist_km",
                    "classes": [[0, 3, "0 – 3 km", "0 – 3 كم", "#1E7B4F"],
                                [3, 6, "3 – 6 km", "3 – 6 كم", "#C8811A"],
                                [6, 99, "> 6 km", "> 6 كم", "#B3202B"]],
                    "weight": 2},
                   ["rank", "dist_km", "school_id", "name_ar"], ["rank", "name_ar", "dist_km"], z=68),
        _edu_layer("schools_ranked", "Schools (ranked by distance)", "المدارس (مرتبة حسب المسافة)", "point",
                   {"type": "point", "color": "#B3202B", "radius": 6, "stroke": "#ffffff", "weight": 1,
                    "label": {"field": "rank", "color": "#22303C", "size": 10, "bold": True}},
                   ["rank", "school_id", "name_ar", "dist_km", "city"], ["rank", "name_ar", "dist_km"], z=71),
    ]

    return {
        "groups": GROUPS,
        "layers": layers,
        "rasters": rasters,
        "edu_layers": edu,
        "cities": CITY,
        "colors": {
            "school": SCHOOL_COLOR, "road": ROAD_COLOR, "bound": BOUND_STROKE,
            "meanCenter": MEAN_CENTER, "stdDist": STD_DIST, "ellipse": STD_ELLIPSE,
            "navy": ATLAS_NAVY, "amber": ATLAS_AMBER,
            "kdeRamp": KDE_RAMP, "suitRamp": SUIT_RAMP,
        },
        "maps": build_maps(),
        "limitations": build_limitations(),
    }


def build_maps():
    """The six original QGIS maps + the Education City map — exact titles/subtitles."""
    m = []
    m.append({
        "id": 1, "city": True, "pad": 2500,
        "title_en": "Spatial distribution of schools - {city}",
        "title_ar": "التوزيع المكاني للمدارس - {city}",
        "sub_en": "KDE bandwidth 800 m / 50 m pixel | mean center, standard distance and 1-sd ellipse (EPSG:32636)",
        "sub_ar": "كثافة KDE بنطاق 800 م / بكسل 50 م | مركز المتوسط والمسافة المعيارية وإهليلج الانحراف (EPSG:32636)",
        "layers": ["roads_walk_{c}", "{c}_boundary_32636", "kde_schools_{c}",
                   "std_ellipse_{c}", "std_distance_{c}", "mean_center_{c}", "schools_32636"],
        "on": ["roads_walk_{c}", "{c}_boundary_32636", "kde_schools_{c}",
               "std_ellipse_{c}", "std_distance_{c}", "mean_center_{c}", "schools_32636"],
        "legend": [
            {"en": "Mean center", "ar": "مركز المتوسط", "sym": "point", "color": MEAN_CENTER},
            {"en": "Schools (KG proxy)", "ar": "المدارس (وكيل KG)", "sym": "point", "color": SCHOOL_COLOR},
            {"en": "Standard distance", "ar": "المسافة المعيارية", "sym": "line", "color": STD_DIST},
            {"en": "Standard deviation ellipse", "ar": "إهليلج الانحراف المعياري", "sym": "poly", "color": STD_ELLIPSE},
            {"en": "City / district boundary", "ar": "حدود المدينة", "sym": "poly", "color": BOUND_STROKE},
            {"en": "Walkable network", "ar": "شبكة الطرق", "sym": "line", "color": ROAD_COLOR},
            {"en": "KDE of schools", "ar": "كثافة المدارس KDE", "sym": "ramp", "color": KDE_RAMP},
        ],
    })
    m.append({
        "id": 2, "city": True, "pad": 1500,
        "title_en": "Network service areas (400 / 800 / 1200 m) - {city}",
        "title_ar": "نطاقات الخدمة الشبكية (400 / 800 / 1200 م) - {city}",
        "sub_en": "Walking network from OSM | service areas built on the road graph and buffered by 25 m",
        "sub_ar": "شبكة مشي من OSM | نطاقات الخدمة مبنية على رسم الطرق وبمنطقة تأثير 25 م",
        "layers": ["roads_walk_{c}", "{c}_boundary_32636", "service_area_1200_{c}",
                   "service_area_800_{c}", "service_area_400_{c}", "schools_32636"],
        "on": ["roads_walk_{c}", "{c}_boundary_32636", "service_area_1200_{c}",
               "service_area_800_{c}", "service_area_400_{c}", "schools_32636"],
        "legend": [
            {"en": "Schools (KG proxy)", "ar": "المدارس (وكيل KG)", "sym": "point", "color": SCHOOL_COLOR},
            {"en": "Service area 400 m", "ar": "نطاق الخدمة 400 م", "sym": "poly", "color": "#2e7d4f"},
            {"en": "Service area 800 m", "ar": "نطاق الخدمة 800 م", "sym": "poly", "color": "#8fd3a0"},
            {"en": "Service area 1200 m", "ar": "نطاق الخدمة 1200 م", "sym": "poly", "color": "#ffe08a"},
            {"en": "City / district boundary", "ar": "حدود المدينة", "sym": "poly", "color": BOUND_STROKE},
            {"en": "Walkable network", "ar": "شبكة الطرق", "sym": "line", "color": ROAD_COLOR},
        ],
    })
    m.append({
        "id": 3, "city": True, "pad": 2500,
        "title_en": "Nearest school by network distance - {city}",
        "title_ar": "أقرب مدرسة بالمسافة الشبكية - {city}",
        "sub_en": "Buildings classified by shortest walking-network distance to the nearest school",
        "sub_ar": "المباني مصنفة حسب أقصر مسافة مشي شبكية إلى أقرب مدرسة",
        "layers": ["roads_walk_{c}", "{c}_boundary_32636", "buildings_net_{c}", "schools_32636"],
        "on": ["roads_walk_{c}", "{c}_boundary_32636", "buildings_net_{c}", "schools_32636"],
        "legend": [
            {"en": "Schools (KG proxy)", "ar": "المدارس (وكيل KG)", "sym": "point", "color": SCHOOL_COLOR},
            {"en": "Buildings by network distance", "ar": "المباني حسب المسافة الشبكية", "sym": "classes",
             "classes": [[c[2], c[3], c[4]] for c in DIST_CLASSES]},
            {"en": "City / district boundary", "ar": "حدود المدينة", "sym": "poly", "color": BOUND_STROKE},
            {"en": "Walkable network", "ar": "شبكة الطرق", "sym": "line", "color": ROAD_COLOR},
        ],
    })
    m.append({
        "id": 4, "city": True, "pad": 2000,
        "title_en": "Overlapping service areas (800 m) - {city}",
        "title_ar": "تداخل نطاقات الخدمة (800 م) - {city}",
        "sub_en": "Number of schools whose 800 m network service area covers each polygon",
        "sub_ar": "عدد المدارس التي تغطي نطاق خدمتها الشبكي 800 م كل مضلع",
        "layers": ["roads_walk_{c}", "{c}_boundary_32636", "overlap_class_800_{c}", "schools_32636"],
        "on": ["roads_walk_{c}", "{c}_boundary_32636", "overlap_class_800_{c}", "schools_32636"],
        "legend": [
            {"en": "Schools (KG proxy)", "ar": "المدارس (وكيل KG)", "sym": "point", "color": SCHOOL_COLOR},
            {"en": "Overlap (800 m)", "ar": "التداخل (800 م)", "sym": "cats",
             "cats": [[str(k), "%d schools" % k, "%d مدارس" % k, v] for k, v in OVERLAP_PAL.items()]},
            {"en": "City / district boundary", "ar": "حدود المدينة", "sym": "poly", "color": BOUND_STROKE},
            {"en": "Walkable network", "ar": "شبكة الطرق", "sym": "line", "color": ROAD_COLOR},
        ],
    })
    m.append({
        "id": 5, "city": True, "pad": 2500,
        "title_en": "Share of shiakha area within 800 m of a school - {city}",
        "title_ar": "نسبة مساحة الشياخة داخل 800 م من مدرسة - {city}",
        "sub_en": "Choropleth: % of shiakha (2017 CAPMAS unit) area inside the 800 m network service area",
        "sub_ar": "خرائط كمية: % من مساحة الشياخة (وحدة 2017) داخل نطاق الخدمة الشبكي 800 م",
        "layers": ["roads_walk_{c}", "{c}_boundary_32636", "coverage_zone_map_{c}", "schools_32636"],
        "on": ["roads_walk_{c}", "{c}_boundary_32636", "coverage_zone_map_{c}", "schools_32636"],
        "legend": [
            {"en": "Schools (KG proxy)", "ar": "المدارس (وكيل KG)", "sym": "point", "color": SCHOOL_COLOR},
            {"en": "Shiakha coverage (% area, 800 m)", "ar": "تغطية الشياخة (% مساحة، 800 م)", "sym": "classes",
             "classes": [[c[2], c[3], c[4]] for c in COV_CLASSES]},
            {"en": "City / district boundary", "ar": "حدود المدينة", "sym": "poly", "color": BOUND_STROKE},
            {"en": "Walkable network", "ar": "شبكة الطرق", "sym": "line", "color": ROAD_COLOR},
        ],
    })
    m.append({
        "id": 6, "city": True, "pad": 2500,
        "title_en": "Hot / cold spots of 800 m school coverage - {city}",
        "title_ar": "النقاط الساخنة/الباردة لتغطية المدارس 800 م - {city}",
        "sub_en": "Getis-Ord Gi* on 250 m cells (bandwidth 1000 m), value = share of residential buildings within 800 m",
        "sub_ar": "Getis-Ord Gi* على خلايا 250 م (نطاق 1000 م)، القيمة = نسبة المباني السكنية داخل 800 م",
        "layers": ["roads_walk_{c}", "{c}_boundary_32636", "hotspot_cov800_{c}", "schools_32636"],
        "on": ["roads_walk_{c}", "{c}_boundary_32636", "hotspot_cov800_{c}", "schools_32636"],
        "legend": [
            {"en": "Schools (KG proxy)", "ar": "المدارس (وكيل KG)", "sym": "point", "color": SCHOOL_COLOR},
            {"en": "Hot spot (Gi*) of 800 m coverage", "ar": "النقاط الساخنة/الباردة (Gi*)", "sym": "cats",
             "cats": [[k, v[1], v[2], v[0]] for k, v in HOTSPOT_CLASSES.items()]},
            {"en": "City / district boundary", "ar": "حدود المدينة", "sym": "poly", "color": BOUND_STROKE},
            {"en": "Walkable network", "ar": "شبكة الطرق", "sym": "line", "color": ROAD_COLOR},
        ],
    })
    m.append({
        "id": 7, "city": False, "pad": 0,
        "title_en": "Nearest Schools to Education City",
        "title_ar": "المدارس الأقرب إلى المدينة التعليمية",
        "sub_en": "Straight-line (geodesic) distance ranking · 11 schools",
        "sub_ar": "ترتيب بالمسافة المستقيمة (جيوديسيك) · 11 مدرسة",
        "layers": ["edu_rings", "edu_links", "schools_ranked", "edu_city_pt"],
        "on": ["edu_rings", "edu_links", "schools_ranked", "edu_city_pt"],
        "legend": [
            {"en": "Education City", "ar": "المدينة التعليمية", "sym": "star", "color": ATLAS_NAVY},
            {"en": "Distance rings (2 / 4 / 6 km)", "ar": "حلقات المسافة", "sym": "line", "color": "#5B87B0"},
            {"en": "Nearest-school links", "ar": "خطوط أقرب المدارس", "sym": "classes",
             "classes": [["0 – 3 km", "0 – 3 كم", "#1E7B4F"], ["3 – 6 km", "3 – 6 كم", "#C8811A"],
                         ["> 6 km", "> 6 كم", "#B3202B"]]},
            {"en": "Schools (ranked)", "ar": "المدارس (مرتبة)", "sym": "point", "color": "#B3202B"},
        ],
    })
    return m


def build_limitations():
    """Report §7 — shown verbatim in the platform (bilingual)."""
    return [
        {"en": '1. "Government" and "KG" classification is unofficial — inferred from school names. Not an official register of government KG schools.',
         "ar": "1. تصنيف «حكومي» و«رياض أطفال» غير رسمي — مستنتج من أسماء المدارس. ليس سجلاً رسمياً."},
        {"en": "2. Small sample (10 schools/city) — any clustering or Gi* test on these points is indicative only.",
         "ar": "2. عينة صغيرة (10 مدارس/مدينة) — أي تحليل تجمّع أو Gi* على هذه النقاط استرشادي."},
        {"en": "3. Port Said is not representative: all 10 schools are in north Port Said only.",
         "ar": "3. بورسعيد غير ممثلة: المدارس العشر كلها في شمال بورسعيد فقط."},
        {"en": "4. Buildings come from OSM and are not exhaustive; served-building ratios are ratios of mapped buildings.",
         "ar": "4. المباني من OSM وليست حصراً؛ نسب المباني المخدومة هي نسب من المباني المرسومة."},
        {"en": "5. Population is a dasymetric proxy: 2017 shiakha population spread evenly over residential buildings.",
         "ar": "5. السكان وكيل (dasymetric): توزيع سكان الشياخة 2017 بالتساوي على المباني السكنية."},
        {"en": "6. Walking speed 5 km/h is assumed, not field-measured; no terrain/heat/crossing calibration.",
         "ar": "6. سرعة المشي 5 كم/س مفترضة وغير مقيسة ميدانياً؛ لا معايرة للتضاريس أو الحرارة أو التقاطعات."},
        {"en": "7. Service areas are 25 m buffers around network segments — an approximation of real access.",
         "ar": "7. نطاقات الخدمة بمنطقة تأثير 25 م حول مقاطع الشبكة — تمثيل تقريبي للوصول الفعلي."},
        {"en": "8. Nasr City boundary from GADM (Nasr City 1+2) is larger than the customary boundary.",
         "ar": "8. حدود مدينة نصر من GADM أكبر من الحدود المتعارف عليها."},
        {"en": "9. The network is undirected, with no turn penalties and no separate pedestrian corridors.",
         "ar": "9. الشبكة غير موجّهة، بلا منع انعطاف ولا محاور مشاة منفصلة."},
        {"en": "10. Walls and gates inside schools/compounds were not modelled.",
         "ar": "10. لم يتم نمذجة الأسوار والبوابات داخل المدارس والتجمعات."},
    ]
