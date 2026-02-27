from flask import Flask, request, jsonify, render_template
from droneflight.kmz import parse_kmz

app = Flask(__name__)

@app.route('/')
def index():
    """Serve the main HTML interface."""
    return render_template('index.html')


@app.route('/upload-kmz', methods=['POST'])
def upload_kmz():
    """Handle a KMZ upload and return geojson (plus optional glTF later)."""
    uploaded = request.files.get('file')
    if uploaded is None:
        return jsonify({'error': 'no file provided'}), 400
    try:
        content = uploaded.read()
        geo = parse_kmz(content)
        return jsonify({'geojson': geo})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)
