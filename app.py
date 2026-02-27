from flask import Flask, request, jsonify, render_template
from droneflight.kmz import parse_kmz

app = Flask(__name__)

@app.route('/')
def index():
    """Serve the main HTML interface."""
    return render_template('index.html')


@app.route('/upload-kmz', methods=['POST'])
def upload_kmz():
    """Handle a KMZ upload and return geojson (plus generated OBJ).

    The OBJ is built on the server using the same helper that drives the
    path editor and is returned as a plain-text string.  The client may
    choose to display or download it automatically; we used to offer a
    download button but requirements changed.
    """
    uploaded = request.files.get('file')
    if uploaded is None:
        return jsonify({'error': 'no file provided'}), 400
    try:
        content = uploaded.read()
        geo = parse_kmz(content)
        from droneflight.kmz import kmz_to_obj
        obj = kmz_to_obj(content, thickness=0.5)
        return jsonify({'geojson': geo, 'obj': obj})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/weather')
def weather():
    """Return weather page content, falling back if the remote site is
    unreachable.  This lets the iframe always show something even when
    external DNS/network access is blocked (as it is in some environments)."""
    try:
        import requests
        resp = requests.get('https://mscweather.com/weekly', timeout=3)
        content = resp.text
        ctype = resp.headers.get('Content-Type', 'text/html')
        # if upstream returned an error status, fall through to local rendering
        if resp.status_code >= 400:
            raise Exception(f"upstream error {resp.status_code}")
        return content, resp.status_code, {'Content-Type': ctype}
    except Exception:
        # network failure or upstream error: attempt to render a simple forecast
        try:
            from droneflight.weather import WeatherProvider
            lat = request.args.get('lat', type=float) or 37.77
            lon = request.args.get('lon', type=float) or -122.42
            wp = WeatherProvider()
            # try hourly forecast first
            data = wp.get_forecast(lat, lon, hours=6)
            if isinstance(data, dict) and 'error' not in data and 'list' in data:
                # build a tiny HTML representation
                parts = ['<h3>Forecast (next hours)</h3>', '<ul>']
                for item in data.get('list', [])[:6]:
                    dt = item.get('dt_txt', '') if 'dt_txt' in item else item.get('dt', '')
                    temp = item.get('main', {}).get('temp')
                    desc = item.get('weather', [{}])[0].get('description', '')
                    parts.append(f'<li>{dt}: {temp}°C — {desc}</li>')
                parts.append('</ul>')
                return '\n'.join(parts), 200, {'Content-Type': 'text/html'}
        except Exception:
            pass
        # final fallback
        return '<p>Weather data unavailable</p>', 200, {'Content-Type': 'text/html'}

if __name__ == '__main__':
    app.run(debug=True)
