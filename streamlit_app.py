# Streamlit Cloud のデフォルトファイル名 (streamlit_app.py) に対応
import runpy

if __name__ == "__main__":
    runpy.run_path("app.py", run_name="__main__")
