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

if __name__ == '__main__':
    app.run(debug=True)
