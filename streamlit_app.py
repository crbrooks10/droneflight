<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>DroneFlight Planner</title>
  <script src="https://cesium.com/downloads/cesiumjs/releases/1.114/Build/Cesium/Cesium.js"></script>
  <link  href="https://cesium.com/downloads/cesiumjs/releases/1.114/Build/Cesium/Widgets/widgets.css" rel="stylesheet"/>
  <!-- JSZip: reads KMZ (ZIP) bytes directly in JS — no fetch, no CORS, guaranteed to work -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; padding: 0; font-family: Arial, sans-serif; background: #1a1a2e; color: #e0e0e0; }

    #mainContainer { display: flex; height: 100vh; }

    /* ── Left KML Panel ── */
    #kmlPanel {
      flex: 0 0 320px;
      display: flex;
      flex-direction: column;
      background: #16213e;
      border-right: 2px solid #0f3460;
      overflow: hidden;
    }
    #kmlHeader {
      padding: 14px 16px;
      background: #0f3460;
      color: #e94560;
      font-weight: bold;
      font-size: 15px;
      letter-spacing: 1px;
      border-bottom: 2px solid #e94560;
      flex-shrink: 0;
    }
    #kmlUploadBar {
      padding: 10px;
      background: #1a1a2e;
      border-bottom: 1px solid #333;
      display: flex;
      flex-direction: column;
      gap: 6px;
      flex-shrink: 0;
    }
    #kmlUploadBar label { font-size: 12px; color: #aaa; }
    #kmlUploadBar input[type=file] {
      font-size: 12px;
      color: #ccc;
      background: #0f3460;
      border: 1px solid #e94560;
      border-radius: 4px;
      padding: 4px 6px;
      cursor: pointer;
      width: 100%;
    }
    #kmlUploadBar input[type=file]::-webkit-file-upload-button {
      background: #e94560; color: white; border: none;
      padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 12px;
    }
    #kmlCoordArea {
      font-size: 11px;
      resize: vertical;
      background: #0f3460;
      color: #ccc;
      border: 1px solid #333;
      border-radius: 4px;
      padding: 6px;
      font-family: monospace;
      width: 100%;
    }
    .kml-btn {
      padding: 7px 10px; font-size: 12px; cursor: pointer;
      background: #0f3460; color: #e0e0e0;
      border: 1px solid #e94560; border-radius: 4px;
      transition: background 0.2s; width: 100%;
    }
    .kml-btn:hover { background: #e94560; color: white; }

    #kmlRoutesList {
      flex: 1;
      overflow-y: auto;
      padding: 10px;
    }
    #kmlRoutesList:empty::before {
      content: 'Upload a KMZ file or paste coordinates to see routes here.';
      display: block;
      color: #666;
      font-size: 12px;
      margin-top: 8px;
    }
    .route-card {
      background: #0f3460;
      border: 1px solid #333;
      border-radius: 5px;
      margin-bottom: 10px;
      overflow: hidden;
    }
    .route-card-header {
      padding: 8px 10px;
      background: #1a3a6e;
      font-weight: bold;
      font-size: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
    }
    .route-card-header:hover { background: #1f4a8a; }
    .route-badge {
      background: #e94560; color: white;
      border-radius: 10px; padding: 2px 8px; font-size: 10px;
    }
    .route-coords {
      font-family: monospace;
      font-size: 10px;
      color: #aaa;
      padding: 8px;
      max-height: 140px;
      overflow-y: auto;
      white-space: pre;
      line-height: 1.5;
      display: none;
    }
    .route-card.open .route-coords { display: block; }
    .route-fly-btn {
      margin: 6px 8px 8px;
      padding: 5px 10px;
      font-size: 11px;
      cursor: pointer;
      background: #27ae60;
      color: white;
      border: none;
      border-radius: 3px;
      display: none;
    }
    .route-card.open .route-fly-btn { display: inline-block; }
    .route-fly-btn:hover { background: #2ecc71; }

    #statusBar {
      padding: 6px 10px;
      font-size: 11px;
      color: #888;
      background: #111;
      border-top: 1px solid #333;
      flex-shrink: 0;
    }

    /* ── Right Map Area ── */
    #mapArea { flex: 1; display: flex; flex-direction: column; min-width: 0; }

    #topToolbar {
      padding: 8px 10px;
      background: #16213e;
      border-bottom: 1px solid #333;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
      flex-shrink: 0;
    }
    .tb-btn {
      padding: 6px 13px; font-size: 12px; cursor: pointer;
      background: #0f3460; color: #e0e0e0;
      border: 1px solid #555; border-radius: 4px;
      transition: background 0.2s;
    }
    .tb-btn:hover { background: #1a4a8a; }
    .tb-btn.active { background: #27ae60; border-color: #2ecc71; color: white; }
    .tb-btn.danger { background: #c0392b; border-color: #e74c3c; color: white; }
    .tb-sep { width: 1px; background: #444; height: 24px; margin: 0 2px; }
    #widthLabel { font-size: 12px; color: #aaa; }
    #widthInput {
      width: 60px; padding: 5px; font-size: 12px;
      background: #0f3460; color: #e0e0e0;
      border: 1px solid #555; border-radius: 4px;
    }

    #cesiumContainer { flex: 1; position: relative; }
    #mainContainer.fullscreen {
      position: fixed; top: 0; left: 0;
      width: 100vw; height: 100vh; z-index: 10000;
    }

    /* ── OBJ preview (collapsible) ── */
    #objSection {
      padding: 8px 10px;
      background: #111;
      border-top: 1px solid #333;
      flex-shrink: 0;
    }
    #objToggle {
      font-size: 11px; color: #888; cursor: pointer; user-select: none;
    }
    #objToggle:hover { color: #ccc; }
    #objOutput {
      display: none;
      height: 100px;
      overflow: auto;
      background: #0d1117;
      color: #7ec8e3;
      font-size: 10px;
      font-family: monospace;
      padding: 6px;
      border: 1px solid #333;
      border-radius: 4px;
      margin-top: 4px;
      white-space: pre;
    }
  </style>
</head>
<body>
<div id="mainContainer">

  <!-- ── Left KML Panel ── -->
  <div id="kmlPanel">
    <div id="kmlHeader">📋 KML ROUTES</div>

    <div id="kmlUploadBar">
      <label>Upload KMZ / KML file:</label>
      <input type="file" id="kmzInput" accept=".kmz,.kml"/>

      <label style="margin-top:4px;">Or paste lon,lat pairs (space/newline separated):</label>
      <textarea id="kmlCoordArea" rows="3" placeholder="-122.42,37.77 -122.41,37.78"></textarea>
      <button class="kml-btn" id="loadCoordsBtn">Load Coordinates</button>
    </div>

    <div id="kmlRoutesList"></div>
    <div id="statusBar">Ready — upload a KMZ or paste coordinates.</div>
  </div>

  <!-- ── Right Map Area ── -->
  <div id="mapArea">
    <div id="topToolbar">
      <button class="tb-btn" id="startDrawBtn">✏ Draw Line</button>
      <button class="tb-btn" id="finishDrawBtn">✓ Finish</button>
      <button class="tb-btn" id="clearBtn">✕ Clear</button>
      <div class="tb-sep"></div>
      <button class="tb-btn" id="fitBtn">⊡ Fit View</button>
      <button class="tb-btn" id="fullscreenBtn">⛶ Fullscreen</button>
      <div class="tb-sep"></div>
      <button class="tb-btn" id="droneBtn">▶ Trace Drone</button>
      <button class="tb-btn danger" id="stopDroneBtn" style="display:none;">⊠ Stop</button>
      <div class="tb-sep"></div>
      <label id="widthLabel">Corridor (m):</label>
      <input type="number" id="widthInput" value="10" min="0" step="1"/>
      <button class="tb-btn" id="applyWidthBtn">Apply</button>
    </div>

    <div id="cesiumContainer"></div>

    <div id="objSection">
      <span id="objToggle">▶ Generated OBJ (click to expand)</span>
      <pre id="objOutput"></pre>
    </div>
  </div>
</div>

<script>
// FIX 1: Suppress "no Ion token" console warning
Cesium.Ion.defaultAccessToken = '';

// ── Cesium init ──────────────────────────────────────────────────────────────
const _creditSink = document.createElement('div');
let viewer;
try {
  viewer = new Cesium.Viewer('cesiumContainer', {
    terrainProvider: Cesium.EllipsoidTerrainProvider.INSTANCE,
    animation: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: true,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton:     false,
    timeline:             false,
    creditContainer:      _creditSink,
  });
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#0d1117');
} catch (e) {
  console.error('Cesium init failed', e);
  document.getElementById('cesiumContainer').textContent = '3D view failed to load — see console.';
  viewer = null;
}

// ── State ────────────────────────────────────────────────────────────────────
let currentGroups   = [];   // array of [[lon,lat,alt?], ...] per line
let corridorEntities= [];
let polylineEntities= [];
let pointEntities   = [];
let drawPolyEnt     = null;
let drawing         = false;
let drawPositions   = [];
let dragIndex       = null;
let droneEntity     = null;
let allRouteCoords  = [];   // flat merged coords for drone/fit

// ── Helpers ──────────────────────────────────────────────────────────────────
function setStatus(msg) {
  document.getElementById('statusBar').textContent = msg;
}

// ── KMZ/KML Parsing: JSZip + DOMParser ───────────────────────────────────────
// Cesium.KmlDataSource.load() calls fetch() on the blob: URL we give it.
// Browsers block blob: fetches in most contexts (CORS / security policy) so
// zero entities are created and the globe stays blank.
// JSZip reads the ZIP bytes directly in JS — no network call, always works.

function extractCoordsFromKMLDoc(doc) {
  var groups = [], ptCoords = [];
  // getElementsByTagNameNS('*', ...) matches any KML namespace prefix
  var coordEls = doc.getElementsByTagNameNS('*', 'coordinates');
  for (var i = 0; i < coordEls.length; i++) {
    var group = [];
    var tokens = coordEls[i].textContent.trim().split(/\s+/);
    for (var j = 0; j < tokens.length; j++) {
      var tk = tokens[j].trim();
      if (!tk) continue;
      var parts = tk.split(',');
      if (parts.length < 2) continue;
      var lon = parseFloat(parts[0]);
      var lat = parseFloat(parts[1]);
      var alt = parts.length > 2 ? parseFloat(parts[2]) : 0;
      if (isFinite(lon) && isFinite(lat)) group.push([lon, lat, isFinite(alt) ? alt : 0]);
    }
    if (group.length >= 2) groups.push(group);
  }
  var ptEls = doc.getElementsByTagNameNS('*', 'Point');
  for (var k = 0; k < ptEls.length; k++) {
    var cEl = ptEls[k].getElementsByTagNameNS('*', 'coordinates')[0];
    if (!cEl) continue;
    var pp = cEl.textContent.trim().split(',');
    if (pp.length < 2) continue;
    var plon = parseFloat(pp[0]), plat = parseFloat(pp[1]);
    var palt = pp.length > 2 ? parseFloat(pp[2]) : 0;
    if (isFinite(plon) && isFinite(plat)) ptCoords.push([plon, plat, isFinite(palt) ? palt : 0]);
  }
  if (ptCoords.length >= 2) groups.push(ptCoords);
  return groups;
}

function parseKMLText(kmlText) {
  var parser = new DOMParser();
  var doc = parser.parseFromString(kmlText, 'application/xml');
  if (doc.querySelector('parsererror')) doc = parser.parseFromString(kmlText, 'text/html');
  return extractCoordsFromKMLDoc(doc);
}

async function loadKMZOrKML(file) {
  if (file.name.toLowerCase().endsWith('.kml')) {
    var groups = parseKMLText(await file.text());
    if (!groups.length) throw new Error('KML has no LineString, Polygon or Point geometry.');
    return groups;
  }
  if (typeof JSZip === 'undefined') throw new Error('JSZip not loaded — check network.');
  var zip;
  try { zip = await JSZip.loadAsync(await file.arrayBuffer()); }
  catch (e) { throw new Error('Cannot unzip KMZ: ' + e.message); }
  var entries = Object.values(zip.files).filter(function(f) {
    return !f.dir && f.name.toLowerCase().endsWith('.kml');
  });
  if (!entries.length) throw new Error('No .kml in KMZ. Has: ' + Object.keys(zip.files).join(', '));
  var allGroups = [];
  for (var i = 0; i < entries.length; i++) {
    var text = await entries[i].async('string');
    var g = parseKMLText(text);
    console.log('[KMZ] ' + entries[i].name + ' -> ' + g.length + ' route(s)');
    allGroups = allGroups.concat(g);
  }
  if (!allGroups.length) throw new Error('KML inside KMZ has no usable coordinate data.');
  return allGroups;
}

// ── Rendering ─────────────────────────────────────────────────────────────────
function clearMap() {
  if (!viewer) return;
  corridorEntities.forEach(e => viewer.entities.remove(e));
  polylineEntities.forEach(e => viewer.entities.remove(e));
  pointEntities.forEach(e => viewer.entities.remove(e));
  if (drawPolyEnt) { viewer.entities.remove(drawPolyEnt); drawPolyEnt = null; }
  corridorEntities = []; polylineEntities = []; pointEntities = [];
}

function renderGroups(groups) {
  if (!viewer) return;
  clearMap();
  currentGroups = groups;
  allRouteCoords = [];

  const width = parseFloat(document.getElementById('widthInput').value) || 10;

  groups.forEach((group, gi) => {
    allRouteCoords.push(...group);

    const flat = [];
    group.forEach(c => { flat.push(c[0]); flat.push(c[1]); });

    // Corridor (ground footprint)
    const corrEnt = viewer.entities.add({
      corridor: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: width,
        material: Cesium.Color.RED.withAlpha(0.5),
        height: 0,
        extrudedHeight: 5.0,
        // outline not supported on extruded corridors (removed to prevent DeveloperError)
      }
    });
    corridorEntities.push(corrEnt);

    // 3-D polyline (with altitude if present)
    const positions3d = group.map(c => Cesium.Cartesian3.fromDegrees(c[0], c[1], c[2] || 0));
    const polyEnt = viewer.entities.add({
      polyline: {
        positions: positions3d,
        width: 3,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower:  0.25,
          taperPower: 1.0,
          color:      Cesium.Color.CYAN,
        }),
        clampToGround: false,
      }
    });
    polylineEntities.push(polyEnt);

    // Waypoint dots
    group.forEach((c, idx) => {
      const pt = viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(c[0], c[1], (c[2] || 0) + 10),
        point: {
          pixelSize: 8,
          color: Cesium.Color.YELLOW,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 1,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: String(gi * 1000 + idx + 1),
          font: '10px sans-serif',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -4),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          show: group.length <= 50,  // hide labels if too many points
        }
      });
      pointEntities.push(pt);
    });
  });

  fitView();
}

function fitView() {
  if (!viewer || !allRouteCoords.length) return;
  if (allRouteCoords.length === 1) {
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(allRouteCoords[0][0], allRouteCoords[0][1], 2000)
    });
    return;
  }
  const positions = allRouteCoords.map(c => Cesium.Cartesian3.fromDegrees(c[0], c[1], c[2] || 0));
  viewer.camera.flyToBoundingSphere(
    Cesium.BoundingSphere.fromPoints(positions),
{ duration: 1.5, offset: (() => {
      const r = Math.max(Cesium.BoundingSphere.fromPoints(positions).radius * 3, 500);
      return new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-40), r);
    })() }
  );
}

// ── KML side panel ────────────────────────────────────────────────────────────
function buildKMLPanel(groups) {
  const list = document.getElementById('kmlRoutesList');
  list.innerHTML = '';

  groups.forEach((group, gi) => {
    const card = document.createElement('div');
    card.className = 'route-card';

    const header = document.createElement('div');
    header.className = 'route-card-header';
    header.innerHTML =
      `<span>Route ${gi + 1}</span>` +
      `<span class="route-badge">${group.length} pts</span>`;
    card.appendChild(header);

    const coordsDiv = document.createElement('div');
    coordsDiv.className = 'route-coords';
    coordsDiv.textContent = group.map((c, i) =>
      `${(i+1).toString().padStart(3)}. ${c[0].toFixed(6)}, ${c[1].toFixed(6)}` +
      (c[2] ? `, ${c[2].toFixed(1)}m` : '')
    ).join('\n');
    card.appendChild(coordsDiv);

    const flyBtn = document.createElement('button');
    flyBtn.className = 'route-fly-btn';
    flyBtn.textContent = '📍 Fly to Route';
    flyBtn.addEventListener('click', () => {
      const positions = group.map(c => Cesium.Cartesian3.fromDegrees(c[0], c[1], c[2] || 0));
      viewer.camera.flyToBoundingSphere(
        Cesium.BoundingSphere.fromPoints(positions),
        { duration: 1.2 }
      );
    });
    card.appendChild(flyBtn);

    header.addEventListener('click', () => card.classList.toggle('open'));

    list.appendChild(card);
  });

  // Auto-open first card
  if (list.firstChild) list.firstChild.classList.add('open');
}

// ── File input handler ────────────────────────────────────────────────────────
document.getElementById('kmzInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  setStatus(`Loading ${file.name}…`);
  try {
    const groups = await loadKMZOrKML(file);
    buildKMLPanel(groups);
    renderGroups(groups);
    setStatus(`✅ ${file.name} — ${groups.length} route(s), ${allRouteCoords.length} waypoints.`);
  } catch (err) {
    setStatus(`❌ ${err.message}`);
    console.error('KMZ/KML error:', err);
  }
});

// ── Manual coordinate input ───────────────────────────────────────────────────
document.getElementById('loadCoordsBtn').addEventListener('click', () => {
  const text = document.getElementById('kmlCoordArea').value.trim();
  if (!text) return;
  const group = [];
  text.replace(/\n/g, ' ').split(/\s+/).forEach(p => {
    const parts = p.split(',');
    if (parts.length >= 2) {
      const lon = parseFloat(parts[0]), lat = parseFloat(parts[1]);
      const alt = parts[2] !== undefined ? parseFloat(parts[2]) : 0;
      if (!isNaN(lon) && !isNaN(lat)) group.push([lon, lat, alt]);
    }
  });
  if (group.length < 2) { setStatus('❌ Need at least 2 valid lon,lat pairs.'); return; }
  buildKMLPanel([group]);
  renderGroups([group]);
  setStatus(`✅ Loaded ${group.length} manual waypoints.`);
});

// ── Draw mode ─────────────────────────────────────────────────────────────────
const drawHandler = new Cesium.ScreenSpaceEventHandler(viewer ? viewer.canvas : document.createElement('canvas'));

drawHandler.setInputAction(click => {
  if (!drawing || !viewer) return;
  const ellipsoid = viewer.scene.globe.ellipsoid;
  const cart = viewer.camera.pickEllipsoid(click.position, ellipsoid);
  if (!Cesium.defined(cart)) return;
  // lon/lat not needed here — cart is stored directly
  drawPositions.push(cart);
  setStatus(`Draw: ${drawPositions.length} point(s) placed — click Finish when done.`);

  const pt = viewer.entities.add({
    position: cart,
    point: { pixelSize: 10, color: Cesium.Color.ORANGE, outlineColor: Cesium.Color.WHITE, outlineWidth: 2,
             disableDepthTestDistance: Number.POSITIVE_INFINITY }
  });
  pointEntities.push(pt);

  if (!drawPolyEnt) {
    drawPolyEnt = viewer.entities.add({
      polyline: {
        positions: new Cesium.CallbackProperty(() => drawPositions, false),
        width: 4,
        material: Cesium.Color.BLUE.withAlpha(0.8),
      }
    });
  }
}, Cesium.ScreenSpaceEventType.LEFT_CLICK);

// Drag support
drawHandler.setInputAction(movement => {
  if (dragIndex === null || !viewer) return;
  const cart = viewer.camera.pickEllipsoid(movement.endPosition, viewer.scene.globe.ellipsoid);
  if (cart) {
    drawPositions[dragIndex] = cart;
    pointEntities[dragIndex].position = cart;
  }
}, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

drawHandler.setInputAction(() => { dragIndex = null; }, Cesium.ScreenSpaceEventType.LEFT_UP);

drawHandler.setInputAction(movement => {
  if (!viewer) return;
  const picked = viewer.scene.pick(movement.position);
  if (Cesium.defined(picked) && pointEntities.includes(picked.id)) {
    dragIndex = pointEntities.indexOf(picked.id);
  }
}, Cesium.ScreenSpaceEventType.LEFT_DOWN);

function setDrawing(on) {
  drawing = on;
  document.getElementById('startDrawBtn').classList.toggle('active', on);
  if (viewer) viewer.canvas.style.cursor = on ? 'crosshair' : 'default';
  setStatus(on ? 'Draw mode ON — click the globe to place points.' : 'Draw mode OFF.');
}

document.getElementById('startDrawBtn').addEventListener('click', () => {
  drawPositions = [];
  if (drawPolyEnt) { viewer.entities.remove(drawPolyEnt); drawPolyEnt = null; }
  pointEntities.forEach(p => viewer.entities.remove(p));
  pointEntities = [];
  setDrawing(true);
});

document.getElementById('finishDrawBtn').addEventListener('click', () => {
  setDrawing(false);
  if (drawPositions.length < 2) { setStatus('Need at least 2 points to finish a line.'); return; }
  // Convert to lon/lat groups and render
  const group = drawPositions.map(cart => {
    const carto = viewer.scene.globe.ellipsoid.cartesianToCartographic(cart);
    return [Cesium.Math.toDegrees(carto.longitude), Cesium.Math.toDegrees(carto.latitude), 0];
  });
  buildKMLPanel([...currentGroups.length ? currentGroups : [], group]);
  renderGroups([...currentGroups.length ? currentGroups : [], group]);
  setStatus(`✅ Line finished with ${group.length} points.`);
});

document.getElementById('clearBtn').addEventListener('click', () => {
  drawing = false;
  drawPositions = [];
  currentGroups = [];
  allRouteCoords = [];
  // Remove Cesium KmlDataSource layer if present
  if (kmlDataSource) {
    viewer.dataSources.remove(kmlDataSource, true);
    kmlDataSource = null;
  }
  clearMap();
  document.getElementById('kmlRoutesList').innerHTML = '';
  document.getElementById('objOutput').textContent = '';
  document.getElementById('kmzInput').value = '';
  setDrawing(false);
  setStatus('Cleared all routes and drawings.');
});

// ── Toolbar buttons ───────────────────────────────────────────────────────────
document.getElementById('fitBtn').addEventListener('click', fitView);

document.getElementById('applyWidthBtn').addEventListener('click', () => {
  if (currentGroups.length) renderGroups(currentGroups);
});

document.getElementById('fullscreenBtn').addEventListener('click', () => {
  document.getElementById('mainContainer').classList.toggle('fullscreen');
  if (viewer) viewer.forceResize();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('mainContainer').classList.remove('fullscreen');
    setDrawing(false);
    if (viewer) viewer.forceResize();
  }
});

// ── Drone trace ───────────────────────────────────────────────────────────────
document.getElementById('droneBtn').addEventListener('click', () => {
  if (!viewer) return;
  if (allRouteCoords.length < 2) { setStatus('❌ Load a route first.'); return; }
  if (droneEntity) stopDrone();

  const start = Cesium.JulianDate.now();
  const secsEach = 3;
  const stop = Cesium.JulianDate.addSeconds(start, allRouteCoords.length * secsEach, new Cesium.JulianDate());
  const prop = new Cesium.SampledPositionProperty();

  allRouteCoords.forEach((c, i) => {
    const t = Cesium.JulianDate.addSeconds(start, i * secsEach, new Cesium.JulianDate());
    prop.addSample(t, Cesium.Cartesian3.fromDegrees(c[0], c[1], (c[2] || 0) + 80));
  });

  droneEntity = viewer.entities.add({
    availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({ start, stop })]),
    position: prop,
    point: {
      pixelSize: 14,
      color: Cesium.Color.YELLOW,
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 2,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
    label: {
      text: '✈',
      font: '22px sans-serif',
      fillColor: Cesium.Color.YELLOW,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
    path: {
      show: true, leadTime: 0, trailTime: 30, width: 2,
      material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.3, taperPower: 1.0, color: Cesium.Color.YELLOW })
    }
  });

  viewer.clock.startTime     = start;
  viewer.clock.stopTime      = stop;
  viewer.clock.currentTime   = start;
  viewer.clock.multiplier    = 1;
  viewer.clock.shouldAnimate = true;
  viewer.clock.clockRange    = Cesium.ClockRange.LOOP_STOP;
  viewer.trackedEntity       = droneEntity;

  document.getElementById('droneBtn').style.display    = 'none';
  document.getElementById('stopDroneBtn').style.display = 'inline-block';
  setStatus('Drone trace running…');
});

document.getElementById('stopDroneBtn').addEventListener('click', stopDrone);

function stopDrone() {
  if (droneEntity) { viewer.entities.remove(droneEntity); droneEntity = null; }
  viewer.trackedEntity = undefined;
  viewer.clock.shouldAnimate = false;
  document.getElementById('droneBtn').style.display    = 'inline-block';
  document.getElementById('stopDroneBtn').style.display = 'none';
  setStatus('Drone trace stopped.');
}

// ── OBJ panel toggle ──────────────────────────────────────────────────────────
document.getElementById('objToggle').addEventListener('click', () => {
  const pre = document.getElementById('objOutput');
  const arrow = document.getElementById('objToggle');
  const open = pre.style.display === 'block';
  pre.style.display = open ? 'none' : 'block';
  arrow.textContent = (open ? '▶' : '▼') + ' Generated OBJ (click to ' + (open ? 'expand' : 'collapse') + ')';
});
</script>
</body>
</html> 