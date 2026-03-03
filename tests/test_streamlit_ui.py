import streamlit_app


def test_no_obj_download_text_in_source():
    # ensure the Streamlit frontend no longer offers an OBJ download button
    src = open(streamlit_app.__file__).read()
    # the string we really care about is the call to st.download_button;
    # everything else (like URLs containing "download") is harmless.
    assert "st.download_button" not in src
