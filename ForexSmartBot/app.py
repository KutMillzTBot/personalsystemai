import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("forexsmartbot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def _find_dashboard_dir(explicit_dir: str | None = None) -> Path:
    """
    Resolve where command_center.html lives.
    Search priority:
      1) --dashboard-dir
      2) current working directory
      3) repo root (this app.py directory)
      4) parent directory of repo root
    """
    candidates: list[Path] = []
    repo_root = Path(__file__).resolve().parent

    if explicit_dir:
        candidates.append(Path(explicit_dir).expanduser().resolve())
    candidates.append(Path.cwd().resolve())
    candidates.append(repo_root)
    candidates.append(repo_root.parent)

    for c in candidates:
        if (c / "command_center.html").exists():
            return c
    return Path.cwd().resolve()


def run_web(host: str, port: int, bridge_url: str, dashboard_dir: str | None = None) -> None:
    """Serve command_center.html + static assets so dashboard and backend are wired."""
    from flask import Flask, jsonify, redirect, request, send_from_directory

    base_dir = _find_dashboard_dir(dashboard_dir)
    html_file = base_dir / "command_center.html"
    local_dashboard = Path(__file__).resolve().parent / "forexsmartbot_dashboard.html"
    if not html_file.exists():
        raise FileNotFoundError(
            f"command_center.html not found in {base_dir}. "
            "Pass --dashboard-dir to point to the correct folder."
        )

    app = Flask(__name__, static_folder=None)
    bridge_url = bridge_url.rstrip("/")

    @app.get("/")
    def root():
        q_bridge = request.args.get("bridge", "").strip()
        target = q_bridge or bridge_url
        if local_dashboard.exists():
            return redirect(f"/forexsmartbot_dashboard.html?bridge={target}", code=302)
        return redirect(f"/command_center.html?bridge={target}", code=302)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "dashboard_dir": str(base_dir), "bridge": bridge_url})

    @app.get("/command_center.html")
    def index():
        return send_from_directory(base_dir, "command_center.html")

    @app.get("/app.js")
    def command_js():
        return send_from_directory(base_dir, "app.js")

    @app.get("/style.css")
    def command_css():
        return send_from_directory(base_dir, "style.css")

    @app.get("/forexsmartbot_dashboard.html")
    def local_index():
        if local_dashboard.exists():
            return send_from_directory(Path(__file__).resolve().parent, "forexsmartbot_dashboard.html")
        return redirect("/command_center.html", code=302)

    @app.get("/forexsmartbot_dashboard.css")
    def local_css():
        css_file = Path(__file__).resolve().parent / "forexsmartbot_dashboard.css"
        if css_file.exists():
            return send_from_directory(Path(__file__).resolve().parent, "forexsmartbot_dashboard.css")
        return ("Not Found", 404)

    @app.get("/forexsmartbot_dashboard.js")
    def local_js():
        js_file = Path(__file__).resolve().parent / "forexsmartbot_dashboard.js"
        if js_file.exists():
            return send_from_directory(Path(__file__).resolve().parent, "forexsmartbot_dashboard.js")
        return ("Not Found", 404)

    @app.get("/<path:asset>")
    def static_assets(asset: str):
        asset_path = base_dir / asset
        if asset_path.exists() and asset_path.is_file():
            return send_from_directory(base_dir, asset)
        local_asset_path = Path(__file__).resolve().parent / asset
        if local_asset_path.exists() and local_asset_path.is_file():
            return send_from_directory(Path(__file__).resolve().parent, asset)
        return ("Not Found", 404)

    logger.info("Web mode: serving dashboard from %s", base_dir)
    logger.info("Web mode: bridge URL = %s", bridge_url)
    logger.info("Web mode: http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)


def run_desktop() -> None:
    """Run the original PyQt desktop app."""
    # Lazy imports so web mode works even if PyQt isn't installed.
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from forexsmartbot.ui.enhanced_main_window import EnhancedMainWindow

    app = None
    try:
        load_dotenv()
        logger.info("Starting ForexSmartBot desktop application...")

        app = QApplication(sys.argv)
        app.setApplicationName("ForexSmartBot")
        app.setApplicationVersion("3.1.0")
        app.setOrganizationName("VoxHash")

        try:
            app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        except AttributeError:
            pass
        try:
            app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        except AttributeError:
            pass

        icon_path = os.path.join(os.path.dirname(__file__), "assets", "icons", "forexsmartbot_256.png")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))

        window = EnhancedMainWindow()
        window.show()
        logger.info("Desktop application started successfully")
        sys.exit(app.exec())
    except Exception as exc:
        logger.error("Failed to start desktop application: %s", exc)
        try:
            if app is not None:
                QMessageBox.critical(None, "Application Error", f"Failed to start ForexSmartBot:\n\n{exc}")
        except Exception:
            pass
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ForexSmartBot launcher")
    parser.add_argument("--web", action="store_true", help="Run web dashboard server mode")
    parser.add_argument("--host", default="127.0.0.1", help="Host for web mode")
    parser.add_argument("--port", type=int, default=8080, help="Port for web mode")
    parser.add_argument("--bridge", default="http://127.0.0.1:5050", help="Backend bridge URL for dashboard")
    parser.add_argument(
        "--dashboard-dir",
        default=None,
        help="Folder containing command_center.html, app.js, and style.css",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    if args.web:
        run_web(args.host, args.port, args.bridge, args.dashboard_dir)
    else:
        run_desktop()


if __name__ == "__main__":
    main()
