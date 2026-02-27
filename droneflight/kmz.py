<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KMZ Viewer</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
    <style>
        #map {
            width: 100%;
            height: 500px;
        }
    </style>
</head>
<body>
    <h1>Upload KMZ File</h1>
    <input type="file" id="fileInput" accept=".kmz" />
    <button id="uploadButton">Upload</button>
    <div id="map"></div>

    <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
    <script src="https://unpkg.com/kml-parser"></script>
    <script>
        let map;

        // Initialize the map
        function initMap() {
            map = L.map('map').setView([0, 0], 2); // Center map at coordinates 0,0
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
            }).addTo(map);
        }

        document.getElementById('uploadButton').addEventListener('click', function() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];

            if (!file) {
                alert('Please select a KMZ file.');
                return;
            }

            const reader = new FileReader();
            reader.onload = function(event) {
                const kmzData = event.target.result;
                parseKMZ(kmzData);
            };
            reader.readAsArrayBuffer(file);
        });

        function parseKMZ(kmzData) {
            const blob = new Blob([kmzData], { type: 'application/vnd.google-earth.kmz' });
            const url = URL.createObjectURL(blob);

            // Use the 'kml-parser' library to parse the KMZ file
            fetch(url)
                .then(response => response.blob())
                .then(blob => {
                    const kmlUrl = URL.createObjectURL(blob);
                    fetch(kmlUrl)
                        .then(response => response.text())
                        .then(kmlText => {
                            const kml = new KmlParser();
                            const geoJson = kml.parse(kmlText);
                            L.geoJSON(geoJson).addTo(map);
                            map.fitBounds(L.geoJSON(geoJson).getBounds());
                        });
                });
        }

        // Initialize the map on page load
        window.onload = initMap;
    </script>
</body>
</html>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KMZ Viewer</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
    <style>
        #map {
            width: 100%;
            height: 500px;
        }
    </style>
</head>
<body>
    <h1>Upload KMZ File</h1>
    <input type="file" id="fileInput" accept=".kmz" />
    <button id="uploadButton">Upload</button>
    <div id="map"></div>

    <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
    <script>
        let map;

        // Initialize the map
        function initMap() {
            map = L.map('map').setView([0, 0], 2);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
            }).addTo(map);
        }

        document.getElementById('uploadButton').addEventListener('click', function() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];

            if (!file) {
                alert('Please select a KMZ file.');
                return;
            }

            const reader = new FileReader();
            reader.onload = function(event) {
                const kmzData = event.target.result;
                parseKMZ(kmzData);
            };
            reader.readAsArrayBuffer(file);
        });

        function parseKMZ(kmzData) {
            const blob = new Blob([kmzData], { type: 'application/vnd.google-earth.kmz' });
            const url = URL.createObjectURL(blob);

            // Use JSZip to read the KMZ contents
            JSZip.loadAsync(kmzData).then(zip => {
                // Look for the KML file inside the KMZ
                const kmlFileName = Object.keys(zip.files).find(name => name.endsWith('.kml'));

                if (!kmlFileName) {
                    alert('No KML file found in the KMZ.');
                    return;
                }

                zip.file(kmlFileName).async('text').then(kmlText => {
                    // Parse the KML using the KML parser
                    const parser = new DOMParser();
                    const kmlDoc = parser.parseFromString(kmlText, 'text/xml');
                    const geoJson = toGeoJSON.kml(kmlDoc);
                    
                    L.geoJSON(geoJson).addTo(map);
                    map.fitBounds(L.geoJSON(geoJson).getBounds());
                }).catch(err => {
                    console.error('Error reading KML file:', err);
                    alert('Error reading KML file.');
                });
            }).catch(err => {
                console.error('Error loading KMZ file:', err);
                alert('Error loading KMZ file.');
            });
        }

        // Initialize the map on page load
        window.onload = initMap;
    </script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
    <script src="https://unpkg.com/@tmcw/togeojson@2.0.1/togeojson.js"></script>
</body>
</html>