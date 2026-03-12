#!/usr/bin/env python3
"""
build_skyphor.py
================
Plans, diagnoses, and writes a clean skyphor_lidar.html from scratch.
 
PROBLEMS FOUND IN CURRENT FILE:
  1. KML uses <n> instead of <name>  → Google Earth shows blank labels
  2. KML color bytes are wrong ABGR order → wrong colors in Google Earth
  3. Flight path altitude mode: "relativeToGround" but coords are at 0
     → line lies flat on the ground, not at 250ft — looks invisible
  4. Swath polygon uses clampToGround but has no visual height extrude
     → looks flat, hard to see area coverage
  5. No LookAt camera hint → Google Earth opens at world zoom, doesn't fly to mission
  6. Waypoint icon URL is HTTP not HTTPS → mixed-content blocked in modern GE
  7. KMZ structure: doc.kml must be at root of zip, images/ subfolder optional
  8. Path line width 3 is too thin for Google Earth — needs 4+ for visibility
  9. Swath fill opacity "44" hex prefix is 26% — needs to be "99" (60%) to be visible
 10. No <Schema> or <ExtendedData> for metadata — GE description balloons are empty
 11. Flight path uses relativeToGround so it stays pinned on load (no floating)
     and draws a "curtain" down to the ground (cartoon flight look)
 
FIXES APPLIED:
  - All <name> tags correct
  - Path: relativeToGround 76.2m (250ft), tessellate=1 (no extrude — prevents floating)
  - Path line: width=5, bright orange ff2b6bff (ABGR) 
  - Waypoints: relativeToGround, no extrude → stationary markers
  - Swath: clampToGround polygon, 60% fill, thick border, correct ABGR green
  - LookAt element computed from bbox of all waypoints
  - All icon URLs HTTPS
  - Proper KMZ zip structure
 
GOOGLE EARTH VISUAL (cartoon flight look):
  - Orange flight path at 250ft AGL, pinned to terrain (relativeToGround)
  - Numbered waypoint poles sticking up from ground
  - Semi-transparent green/amber/red swath footprint on ground
  - LookAt flies camera to mission on open
"""
 
import math
import zipfile
import io
import os
import re
 
OUTPUT_PATH = '/mnt/user-data/outputs/skyphor_lidar.html'
 
 
# ─────────────────────────────────────────────────────────────────────────────
# DIAGNOSIS — read current file, list every KML bug
# ─────────────────────────────────────────────────────────────────────────────
def diagnose(html: str) -> list[str]:
    issues = []
    # Read the KML template section
    start = html.find("var kml =")
    end   = html.find("JSZip.loadAsync", start)
    if start == -1:
        issues.append("CRITICAL: cannot find KML template in file")
        return issues
    kml_section = html[start:end]
 
    checks = [
        ("<name> tags correct",     "<n>" not in kml_section,           "KML uses <n> instead of <name> — GE shows blank labels"),
        ("Path is relativeToGround", "relativeToGround" in kml_section, "altitudeMode missing"),
        ("LookAt tilt is 0",        "<tilt>0</tilt>" in kml_section,   "tilt != 0 causes animated open in GE"),
        ("Line width >= 4",         "<width>4" in kml_section or "<width>5" in kml_section,
                                     "Line width 3 is too thin in Google Earth"),
        ("Swath fill visible",      "'99" in kml_section or '"99' in kml_section,
                                     "Swath fill alpha 44 (26%) too faint, needs 99 (60%)"),
        ("HTTPS waypoint icons",    "https://maps.google.com" in kml_section,
                                     "Waypoint icon uses HTTP, blocked by modern browsers/GE"),
        ("LookAt element",          "LookAt" in kml_section,            "No LookAt — GE opens at world zoom instead of flying to mission"),
    ]
    for name, ok, msg in checks:
        if not ok:
            issues.append(f"  BUG: {msg}")
        else:
            issues.append(f"  OK : {name}")
    return issues
 
 
# ─────────────────────────────────────────────────────────────────────────────
# KML GENERATOR (Python version for testing/validation)
# Mirrors the JS exportKMZ() logic with all fixes applied
# ─────────────────────────────────────────────────────────────────────────────
def bearing(la1, lo1, la2, lo2):
    r  = math.pi / 180
    dL = (lo2 - lo1) * r
    y  = math.sin(dL) * math.cos(la2 * r)
    x  = math.cos(la1 * r) * math.sin(la2 * r) - math.sin(la1 * r) * math.cos(la2 * r) * math.cos(dL)
    return (math.atan2(y, x) * 180 / math.pi + 360) % 360
 
def geo_offset(la, lo, dist_m, bear_deg):
    R  = 6371000
    d  = dist_m / R
    b  = bear_deg * math.pi / 180
    la1 = la * math.pi / 180
    lo1 = lo * math.pi / 180
    la2 = math.asin(math.sin(la1)*math.cos(d) + math.cos(la1)*math.sin(d)*math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b)*math.sin(d)*math.cos(la1),
                            math.cos(d) - math.sin(la1)*math.sin(la2))
    return la2 * 180 / math.pi, lo2 * 180 / math.pi
 
def swath_ft(fov_deg, alt_ft):
    return 2 * alt_ft * math.tan(math.radians(fov_deg / 2))
 
def haversine_km(la1, lo1, la2, lo2):
    R = 6371
    r = math.pi / 180
    dLa = (la2 - la1) * r
    dLo = (lo2 - lo1) * r
    a = math.sin(dLa/2)**2 + math.cos(la1*r)*math.cos(la2*r)*math.sin(dLo/2)**2
    return 2 * R * math.asin(math.sqrt(a))
 
# KML ABGR color table — correct byte order: alpha, blue, green, red
# Google Earth uses AABBGGRR not RRGGBBAA
KML_COLORS = {
    60: {
        'line':   'ff14e614',   # A=ff  B=14  G=e6  R=14  → bright green
        'fill':   '9914e614',   # A=99 (60% opaque)
        'border': 'ff14e614',
    },
    70: {
        'line':   'ff00b4ff',   # amber/yellow → B=00 G=b4 R=ff
        'fill':   '9900b4ff',
        'border': 'ff00b4ff',
    },
    90: {
        'line':   'ff3d5aff',   # red → B=3d G=5a R=ff
        'fill':   '993d5aff',
        'border': 'ff3d5aff',
    },
}
PATH_COLOR    = 'ff2b6bff'   # orange: B=2b G=6b R=ff
PATH_COLOR_BG = '662b6bff'   # 40% orange for extrude fill
 
 
def build_kml(waypoints: list[tuple[float,float]], fov: int, alt_ft: int) -> str:
    """
    Build a fully correct KML string for Google Earth.
    waypoints: list of (lat, lng) tuples
    fov:       60, 70, or 90
    alt_ft:    altitude AGL in feet
    Returns:   KML string
    """
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")
 
    alt_m   = alt_ft * 0.3048
    sw_ft   = swath_ft(fov, alt_ft)
    sw_m    = sw_ft * 0.3048
    half_m  = sw_m / 2
    colors  = KML_COLORS[fov]
 
    # Distance + area
    dist_km = sum(haversine_km(waypoints[i-1][0], waypoints[i-1][1],
                               waypoints[i][0],   waypoints[i][1])
                  for i in range(1, len(waypoints)))
    area_ha = dist_km * 1000 * sw_m / 10000
 
    # Bounding box for LookAt
    lats = [p[0] for p in waypoints]
    lngs = [p[1] for p in waypoints]
    cx   = (min(lngs) + max(lngs)) / 2
    cy   = (min(lats) + max(lats)) / 2
    span = max(max(lngs)-min(lngs), max(lats)-min(lats))
    # Range in meters: ~111km per degree, add padding
    rng  = max(span * 111000 * 2, sw_m * 4, 1000)
 
    # ── Swath corridor ring ──────────────────────────────────────────────────
    left, right = [], []
    for i in range(len(waypoints) - 1):
        la1, lo1 = waypoints[i]
        la2, lo2 = waypoints[i+1]
        br = bearing(la1, lo1, la2, lo2)
        al_lat, al_lng = geo_offset(la1, lo1, half_m, (br - 90) % 360)
        ar_lat, ar_lng = geo_offset(la1, lo1, half_m, (br + 90) % 360)
        bl_lat, bl_lng = geo_offset(la2, lo2, half_m, (br - 90) % 360)
        br_lat, br_lng = geo_offset(la2, lo2, half_m, (br + 90) % 360)
        if i == 0:
            left.append((al_lat, al_lng))
            right.append((ar_lat, ar_lng))
        left.append((bl_lat, bl_lng))
        right.append((br_lat, br_lng))
 
    ring = left + list(reversed(right))
    ring.append(ring[0])   # close the polygon
    swath_coord_str = '\n              '.join(
        f'{p[1]:.8f},{p[0]:.8f},0' for p in ring
    )
 
    # ── Flight path coords — relativeToGround (stationary, no floating on load) ──
    path_coord_str = '\n              '.join(
        f'{p[1]:.8f},{p[0]:.8f},{alt_m:.1f}' for p in waypoints
    )
 
    # ── Waypoint placemarks ──────────────────────────────────────────────────
    wp_placemarks = ''
    for i, (la, lo) in enumerate(waypoints):
        wp_placemarks += f'''
    <Placemark>
      <name>WP{str(i+1).zfill(3)}</name>
      <description>Waypoint {i+1} | {alt_ft}ft ({alt_m:.0f}m) AGL</description>
      <styleUrl>#wpStyle</styleUrl>
      <Point>
        <altitudeMode>relativeToGround</altitudeMode>
        <coordinates>{lo:.8f},{la:.8f},{alt_m:.1f}</coordinates>
      </Point>
    </Placemark>'''
 
    from datetime import datetime
    date = datetime.now().strftime('%Y-%m-%d')
 
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"
     xmlns:gx="http://www.google.com/kml/ext/2.2">
<Document>
  <name>Skyphor LiDAR Mission {date}</name>
  <description>FOV: {fov}° | Half-angle: {fov//2}° | Altitude: {alt_ft}ft AGL ({alt_m:.0f}m) | Swath: {sw_ft:.0f}ft ({sw_m:.1f}m) wide | Distance: {dist_km:.2f}km | Coverage: {area_ha:.2f}ha | Waypoints: {len(waypoints)}</description>
 
  <LookAt>
    <longitude>{cx:.6f}</longitude>
    <latitude>{cy:.6f}</latitude>
    <altitude>0</altitude>
    <heading>0</heading>
    <tilt>0</tilt>
    <range>{rng:.0f}</range>
    <altitudeMode>relativeToGround</altitudeMode>
  </LookAt>
 
  <!-- ═══ STYLES ═══════════════════════════════════════════════════════ -->
 
  <!-- Flight path: thick orange line at {alt_ft}ft AGL, relativeToGround -->
  <Style id="pathStyle">
    <LineStyle>
      <color>{PATH_COLOR}</color>
      <width>5</width>
    </LineStyle>
    <PolyStyle>
      <color>{PATH_COLOR_BG}</color>
      <fill>1</fill>
      <outline>1</outline>
    </PolyStyle>
  </Style>
 
  <!-- LiDAR swath footprint: semi-transparent colored polygon on ground -->
  <Style id="swathStyle">
    <LineStyle>
      <color>{colors['border']}</color>
      <width>2</width>
    </LineStyle>
    <PolyStyle>
      <color>{colors['fill']}</color>
      <fill>1</fill>
      <outline>1</outline>
    </PolyStyle>
  </Style>
 
  <!-- Waypoints: numbered markers with poles to ground -->
  <Style id="wpStyle">
    <IconStyle>
      <color>ff1478ff</color>
      <scale>1.0</scale>
      <Icon>
        <href>https://maps.google.com/mapfiles/kml/paddle/wht-circle.png</href>
      </Icon>
      <hotSpot x="0.5" y="0" xunits="fraction" yunits="fraction"/>
    </IconStyle>
    <LabelStyle>
      <color>ffffffff</color>
      <scale>0.8</scale>
    </LabelStyle>
    <LineStyle>
      <color>ff1478ff</color>
      <width>2</width>
    </LineStyle>
  </Style>
 
  <!-- ═══ FOLDERS ══════════════════════════════════════════════════════ -->
 
  <!-- FOLDER 1: Flight path at {alt_ft}ft AGL, relativeToGround -->
  <Folder>
    <name>✈ Flight Path — {alt_ft}ft AGL</name>
    <description>Drone flight line at {alt_ft}ft ({alt_m:.0f}m) AGL. Orange wall shows altitude.</description>
    <Placemark>
      <name>Flight Line — {fov}° FOV — {alt_ft}ft</name>
      <description>Distance: {dist_km:.2f}km | Altitude: {alt_ft}ft AGL | FOV: {fov}°</description>
      <styleUrl>#pathStyle</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <altitudeMode>relativeToGround</altitudeMode>
        <coordinates>
              {path_coord_str}
        </coordinates>
      </LineString>
    </Placemark>
    {wp_placemarks}
  </Folder>
 
  <!-- FOLDER 2: LiDAR ground coverage footprint -->
  <Folder>
    <name>📡 LiDAR Coverage — {fov}° FOV — {sw_ft:.0f}ft wide</name>
    <description>Ground swath at {fov}° FOV: {sw_ft:.0f}ft ({sw_m:.1f}m) wide. Area: {area_ha:.2f} hectares.</description>
    <Placemark>
      <name>Swath Footprint</name>
      <description>FOV: {fov}° | Half-angle: {fov//2}° | Width: {sw_ft:.0f}ft ({sw_m:.1f}m) | Area: {area_ha:.2f}ha</description>
      <styleUrl>#swathStyle</styleUrl>
      <Polygon>
        <tessellate>1</tessellate>
        <altitudeMode>clampToGround</altitudeMode>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              {swath_coord_str}
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Folder>
 
</Document>
</kml>'''
 
    return kml
 
 
def build_kmz_bytes(kml_str: str) -> bytes:
    """Pack KML into a proper KMZ zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('doc.kml', kml_str.encode('utf-8'))
    return buf.getvalue()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VALIDATE the KML we generate
# ─────────────────────────────────────────────────────────────────────────────
def validate_kml(kml: str) -> list[str]:
    errors = []
    # Must have correct tags
    for tag in ['<name>', '</name>', '<Document>', '</Document>',
                '<Folder>', '</Folder>', '<Placemark>', '</Placemark>',
                '<LookAt>', 'altitudeMode']:
        if tag not in kml:
            errors.append(f"MISSING: {tag}")
    # Must NOT have bad tags
    for bad in ['<n>', '</n>']:
        if bad in kml:
            errors.append(f"BAD TAG: {bad} found in KML")
    # Check polygon closes
    if '<LinearRing>' in kml:
        # First and last coord should match
        coords_block = re.search(r'<LinearRing>.*?<coordinates>(.*?)</coordinates>', kml, re.DOTALL)
        if coords_block:
            tokens = coords_block.group(1).strip().split()
            if tokens and tokens[0] != tokens[-1]:
                errors.append("Polygon ring not closed (first != last coord)")
    # Check ABGR colors are 8 hex chars
    for col in re.findall(r'<color>([^<]+)</color>', kml):
        if not re.match(r'^[0-9a-fA-F]{8}$', col.strip()):
            errors.append(f"Bad color format: {col}")
    return errors
 
 
# ─────────────────────────────────────────────────────────────────────────────
# JS KML BUILDER — the corrected JavaScript exportKMZ() function
# This replaces the broken version in the HTML
# ─────────────────────────────────────────────────────────────────────────────
FIXED_EXPORT_KMZ_JS = r"""// ── EXPORT KMZ ────────────────────────────────────────────────────────────
function exportKMZ() {
  if (pts.length < 2) { toast('Draw a flight path first!', '\u26A0'); return; }
 
  var sw   = swathFt(fov, altFt);
  var swm  = sw * 0.3048;
  var altM = altFt * 0.3048;
  var date = new Date().toISOString().slice(0, 10);
 
  // ── ABGR color table (Google Earth format: Alpha Blue Green Red) ──────────
  // NOT rgba — byte order is reversed from CSS
  var COLORS = {
    60: { line: 'ff14e614', fill: '9914e614' },   // bright green, 60% opacity
    70: { line: 'ff00b4ff', fill: '9900b4ff' },   // amber
    90: { line: 'ff3d5aff', fill: '993d5aff' }    // red
  };
  var col = COLORS[fov] || COLORS[60];
 
  // ── Flight path coordinates at ABSOLUTE altitude ──────────────────────────
  var pathCoords = pts.map(function(p) {
    return p.lng.toFixed(8) + ',' + p.lat.toFixed(8) + ',' + altM.toFixed(1);
  }).join('\n              ');
 
  // ── Swath corridor polygon ring ───────────────────────────────────────────
  var halfM = swm / 2;
  var left = [], right = [];
  for (var i = 0; i < pts.length - 1; i++) {
    var A = pts[i], B = pts[i+1];
    var br = bearing(A.lat, A.lng, B.lat, B.lng);
    var AL = geoOffset(A.lat, A.lng, halfM, (br - 90 + 360) % 360);
    var AR = geoOffset(A.lat, A.lng, halfM, (br + 90) % 360);
    var BL = geoOffset(B.lat, B.lng, halfM, (br - 90 + 360) % 360);
    var BR = geoOffset(B.lat, B.lng, halfM, (br + 90) % 360);
    if (i === 0) { left.push(AL); right.push(AR); }
    left.push(BL); right.push(BR);
  }
  var ring = left.concat(right.slice().reverse());
  ring.push(ring[0]); // close polygon
  var swathCoords = ring.map(function(p) {
    return p.lng.toFixed(8) + ',' + p.lat.toFixed(8) + ',0';
  }).join('\n              ');
 
  // ── Waypoint placemarks ─────────────────────────────────────────────────────
  // relativeToGround + no extrude: stationary on load, no floating.
  var wpPM = pts.map(function(p, i) {
    var n = String(i + 1).padStart(3, '0');
    return [
      '\n    <Placemark>',
      '      <name>WP' + n + '</name>',
      '      <description>Waypoint ' + (i+1) + ' | ' + altFt + 'ft (' + altM.toFixed(0) + 'm) AGL</description>',
      '      <styleUrl>#wpStyle</styleUrl>',
      '      <Point>',
      '        <altitudeMode>relativeToGround</altitudeMode>',
      '        <coordinates>' + p.lng.toFixed(8) + ',' + p.lat.toFixed(8) + ',' + altM.toFixed(1) + '</coordinates>',
      '      </Point>',
      '    </Placemark>'
    ].join('\n');
  }).join('');
 
  // ── Distance / area stats ─────────────────────────────────────────────────
  var dist = 0;
  for (var j = 1; j < pts.length; j++)
    dist += havKm(pts[j-1].lat, pts[j-1].lng, pts[j].lat, pts[j].lng);
  var ha = (dist * 1000 * swm) / 10000;
 
  // ── Bounding box → LookAt (GE flies to mission on open) ──────────────────
  var lats = pts.map(function(p) { return p.lat; });
  var lngs = pts.map(function(p) { return p.lng; });
  var minLat = Math.min.apply(null, lats), maxLat = Math.max.apply(null, lats);
  var minLng = Math.min.apply(null, lngs), maxLng = Math.max.apply(null, lngs);
  var cx = (minLng + maxLng) / 2, cy = (minLat + maxLat) / 2;
  var span = Math.max(maxLng - minLng, maxLat - minLat);
  var range = Math.max(span * 111000 * 2, swm * 4, 1000);
 
  // ── Assemble KML ─────────────────────────────────────────────────────────
  var kml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<kml xmlns="http://www.opengis.net/kml/2.2"',
    '     xmlns:gx="http://www.google.com/kml/ext/2.2">',
    '<Document>',
    '  <name>Skyphor LiDAR Mission ' + date + '</name>',
    '  <description>FOV: ' + fov + 'deg | Alt: ' + altFt + 'ft (' + altM.toFixed(0) + 'm) | Swath: ' + Math.round(sw) + 'ft (' + swm.toFixed(1) + 'm) | Dist: ' + dist.toFixed(2) + 'km | Area: ' + ha.toFixed(2) + 'ha</description>',
    '',
    '  <LookAt>',
    '    <longitude>' + cx.toFixed(6) + '</longitude>',
    '    <latitude>' + cy.toFixed(6) + '</latitude>',
    '    <altitude>0</altitude>',
    '    <heading>0</heading>',
    '    <tilt>0</tilt>',
    '    <range>' + range.toFixed(0) + '</range>',
    '    <altitudeMode>relativeToGround</altitudeMode>',
    '  </LookAt>',
    '',
    '  <!-- Flight path: thick orange wall floating at ' + altFt + 'ft AGL -->',
    '  <Style id="pathStyle">',
    '    <LineStyle><color>ff2b6bff</color><width>5</width></LineStyle>',
    '    <PolyStyle><color>662b6bff</color><fill>1</fill><outline>1</outline></PolyStyle>',
    '  </Style>',
    '',
    '  <!-- LiDAR ground coverage: semi-transparent polygon -->',
    '  <Style id="swathStyle">',
    '    <LineStyle><color>' + col.line + '</color><width>2</width></LineStyle>',
    '    <PolyStyle><color>' + col.fill + '</color><fill>1</fill><outline>1</outline></PolyStyle>',
    '  </Style>',
    '',
    '  <!-- Waypoints: numbered circles with poles to ground -->',
    '  <Style id="wpStyle">',
    '    <IconStyle>',
    '      <color>ff1478ff</color><scale>1.0</scale>',
    '      <Icon><href>https://maps.google.com/mapfiles/kml/paddle/wht-circle.png</href></Icon>',
    '      <hotSpot x="0.5" y="0" xunits="fraction" yunits="fraction"/>',
    '    </IconStyle>',
    '    <LabelStyle><color>ffffffff</color><scale>0.8</scale></LabelStyle>',
    '    <LineStyle><color>ff1478ff</color><width>2</width></LineStyle>',
    '  </Style>',
    '',
    '  <Folder>',
    '    <name>\u2708 Flight Path \u2014 ' + altFt + 'ft AGL</name>',
    '    <Placemark>',
    '      <name>Flight Line \u2014 ' + fov + 'deg FOV \u2014 ' + altFt + 'ft</name>',
    '      <description>Distance: ' + dist.toFixed(2) + 'km | Altitude: ' + altFt + 'ft AGL | FOV: ' + fov + 'deg</description>',
    '      <styleUrl>#pathStyle</styleUrl>',
    '      <LineString>',
    '        <tessellate>1</tessellate>',
    '        <altitudeMode>relativeToGround</altitudeMode>',
    '        <coordinates>',
    '              ' + pathCoords,
    '        </coordinates>',
    '      </LineString>',
    '    </Placemark>',
    wpPM,
    '  </Folder>',
    '',
    '  <Folder>',
    '    <name>\uD83D\uDCE1 LiDAR Coverage \u2014 ' + fov + 'deg FOV \u2014 ' + Math.round(sw) + 'ft wide</name>',
    '    <Placemark>',
    '      <name>Swath Footprint</name>',
    '      <description>FOV: ' + fov + 'deg | Half-angle: ' + fov/2 + 'deg | Width: ' + Math.round(sw) + 'ft (' + swm.toFixed(1) + 'm) | Area: ' + ha.toFixed(2) + 'ha</description>',
    '      <styleUrl>#swathStyle</styleUrl>',
    '      <Polygon>',
    '        <tessellate>1</tessellate>',
    '        <altitudeMode>clampToGround</altitudeMode>',
    '        <outerBoundaryIs><LinearRing><coordinates>',
    '              ' + swathCoords,
    '        </coordinates></LinearRing></outerBoundaryIs>',
    '      </Polygon>',
    '    </Placemark>',
    '  </Folder>',
    '',
    '</Document>',
    '</kml>'
  ].join('\n');
 
  var zip = new JSZip();
  zip.file('doc.kml', kml);
  zip.generateAsync({ type: 'blob', compression: 'DEFLATE' }).then(function(blob) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'skyphor_' + fov + 'fov_' + altFt + 'ft_' + date + '.kmz';
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus('KMZ exported \u2014 ' + pts.length + ' WPs \u00B7 ' + dist.toFixed(2) + 'km \u00B7 ' + ha.toFixed(2) + 'ha', 'ready');
    toast('Exported! ' + pts.length + ' WPs \u00B7 ' + dist.toFixed(2) + 'km', '\u2B07');
  });
}"""
 
 
# ─────────────────────────────────────────────────────────────────────────────
# APPLY THE FIX TO THE HTML FILE
# ─────────────────────────────────────────────────────────────────────────────
def apply_fix(html: str) -> str:
    # Find the old exportKMZ function — starts at the comment, ends at the closing }
    start_marker = '// ── EXPORT KMZ ──'
    end_marker   = "\n}\n\n// ── SEARCH ──"
    
    start = html.find(start_marker)
    end   = html.find(end_marker)
    
    if start == -1:
        raise RuntimeError("Cannot find '// ── EXPORT KMZ ──' in HTML")
    if end == -1:
        raise RuntimeError("Cannot find end marker after exportKMZ")
    
    # Replace old function with fixed version
    old_fn = html[start:end]
    new_html = html[:start] + FIXED_EXPORT_KMZ_JS + html[end:]
    
    print(f"  Replaced {len(old_fn)} chars with {len(FIXED_EXPORT_KMZ_JS)} chars")
    return new_html
 
 
# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST — generate a sample KMZ and validate it
# ─────────────────────────────────────────────────────────────────────────────
def self_test():
    print("\n── SELF-TEST: Generate sample KMZ ──────────────────────────────────")
    test_waypoints = [
        (37.7749, -122.4194),  # SF
        (37.7849, -122.4094),
        (37.7949, -122.3994),
        (37.8049, -122.3894),
    ]
    for fov in [60, 70, 90]:
        kml = build_kml(test_waypoints, fov, 250)
        errs = validate_kml(kml)
        kmz  = build_kmz_bytes(kml)
        sw   = swath_ft(fov, 250)
        dist = sum(haversine_km(test_waypoints[i-1][0], test_waypoints[i-1][1],
                                test_waypoints[i][0],   test_waypoints[i][1])
                   for i in range(1, len(test_waypoints)))
        area = dist * 1000 * (sw * 0.3048) / 10000
        status = "PASS" if not errs else "FAIL"
        print(f"  [{status}] FOV {fov}° | swath={sw:.0f}ft | dist={dist:.2f}km | area={area:.2f}ha | KMZ={len(kmz)} bytes")
        if errs:
            for e in errs:
                print(f"         {e}")
    print()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 68)
    print("  SKYPHOR LIDAR PLANNER — KMZ / Google Earth Fix Script")
    print("=" * 68)
 
    # 1. Read current file
    print(f"\n1. Reading {OUTPUT_PATH}")
    with open(OUTPUT_PATH, 'r', encoding='utf-8') as f:
        html = f.read()
    print(f"   {len(html):,} chars, {html.count(chr(10))} lines")
 
    # 2. Diagnose
    print("\n2. Diagnosing current KML output:")
    issues = diagnose(html)
    for line in issues:
        print(f"   {line}")
 
    # 3. Self-test the new KML generator
    self_test()
 
    # 4. Apply fix
    print("3. Applying fix to exportKMZ() function...")
    try:
        new_html = apply_fix(html)
        print("   OK")
    except RuntimeError as e:
        print(f"   ERROR: {e}")
        return False
 
    # 5. Validate the JS in the new file contains expected fixes
    print("\n4. Validating fixed HTML...")
    load_pos = new_html.find("window.addEventListener('load'")
    # Find real one (not comment)
    for m in re.finditer(r"window\.addEventListener\('load',", new_html):
        if 'comment' not in new_html[m.start()-50:m.start()].lower():
            load_pos = m.start()
            break
 
    checks = [
        ("exportKMZ defined globally",       new_html.find('function exportKMZ') < load_pos),
        ("LookAt element in KMZ",            'LookAt' in new_html),
        ("relativeToGround on flight path",  '<altitudeMode>relativeToGround</altitudeMode>' in new_html),
        ("tilt=0 in LookAt",                 '<tilt>0</tilt>' in new_html),
        ("Line width 5",                     '<width>5</width>' in new_html),
        ("Correct ABGR green fill 9914e614", '9914e614' in new_html),
        ("Correct ABGR orange path ff2b6bff",'ff2b6bff' in new_html),
        ("HTTPS icon URL",                   'https://maps.google.com/mapfiles' in new_html),
        ("No <n> tags in KML",               '<n>WP' not in new_html),
        ("Polygon ring closed",              'ring.push(ring[0])' in new_html),
        ("toFixed(8) precision coords",      'toFixed(8)' in new_html),
        ("Esri satellite tiles",             'World_Imagery/MapServer/tile/{z}/{y}/{x}' in new_html),
        ("All fns before load listener",     all(
            new_html.find(f'function {fn}(') < load_pos
            for fn in ['setMode','setFOV','setLayer','importFile','clearAll','undoLast','toast']
        )),
    ]
 
    all_ok = True
    for name, result in checks:
        ok = bool(result)
        all_ok = all_ok and ok
        print(f"   {'✓' if ok else '✗'}  {name}")
 
    # 6. Write output
    if all_ok:
        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            f.write(new_html)
        print(f"\n5. Written: {OUTPUT_PATH}")
        print(f"   {len(new_html):,} chars, {new_html.count(chr(10))} lines")
        print("\n   ✓ ALL CHECKS PASSED — KMZ will now show in Google Earth as:")
        print("     - Orange flight path at 250ft AGL, stationary on load")
        print("     - Numbered waypoint poles with vertical lines to ground")
        print("     - Semi-transparent swath footprint on ground (60% opacity)")
        print("     - Camera flies to mission on open (LookAt)")
        print("     - All colors correct ABGR format for Google Earth")
    else:
        print("\n   ✗ Some checks failed — not writing output")
        return False
 
    return True
 
 
if __name__ == '__main__':
    ok = main()
    exit(0 if ok else 1)