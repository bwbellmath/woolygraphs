#!/usr/bin/env python3
"""
Local development server for the Knit Geometry Editor.

Serves the HTML editor and provides endpoints for:
  POST /save-tikz   — save generated TikZ code to disk
  POST /render-tikz  — compile TikZ to SVG via pdflatex + pdf2svg (if available)

Usage:
    python knit_server.py [--port 8080]

Then open http://localhost:8080/knit_editor.html
"""

import argparse
import http.server
import json
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent
SAVE_DIR = PROJECT_DIR / "tikz_saves"


class KnitHandler(http.server.SimpleHTTPRequestHandler):
    """Extends SimpleHTTPRequestHandler with API endpoints."""

    def do_POST(self):
        if self.path == '/save-tikz':
            self._handle_save_tikz()
        elif self.path == '/render-tikz':
            self._handle_render_tikz()
        else:
            self.send_error(404)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        return json.loads(body)

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _handle_save_tikz(self):
        try:
            data = self._read_json()
            content = data.get('content', '')
            filename = data.get('filename', None)

            SAVE_DIR.mkdir(exist_ok=True)

            if not filename:
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"knit_editor_{ts}.tex"

            path = SAVE_DIR / filename
            path.write_text(content)

            result = {'ok': True, 'path': str(path)}

            # Also save as "latest" for .tex files
            if filename.endswith('.tex'):
                latest = SAVE_DIR / "knit_editor_latest.tex"
                latest.write_text(content)
                result['latest'] = str(latest)

            self._json_response(result)
        except Exception as e:
            self._json_response({'ok': False, 'error': str(e)}, 500)

    def _handle_render_tikz(self):
        try:
            data = self._read_json()
            tikz_code = data.get('tikz', '')

            # Check for pdflatex
            if not shutil.which('pdflatex'):
                self._json_response(
                    {'ok': False, 'error': 'pdflatex not found'},
                    500
                )
                return

            # Build full document
            doc = (
                "\\documentclass[border=2pt]{standalone}\n"
                "\\usepackage{tikz}\n"
                "\\usetikzlibrary{calc, decorations.markings, arrows.meta}\n"
                "\\begin{document}\n"
                f"{tikz_code}\n"
                "\\end{document}\n"
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                tex_path = os.path.join(tmpdir, 'input.tex')
                with open(tex_path, 'w') as f:
                    f.write(doc)

                # Compile to PDF
                result = subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', 'input.tex'],
                    cwd=tmpdir, capture_output=True, text=True, timeout=30
                )

                pdf_path = os.path.join(tmpdir, 'input.pdf')
                if not os.path.exists(pdf_path):
                    self._json_response({
                        'ok': False,
                        'error': f'Compilation failed:\n{result.stdout[-500:]}',
                    }, 500)
                    return

                # Try pdf2svg
                svg_path = os.path.join(tmpdir, 'output.svg')
                if shutil.which('pdf2svg'):
                    subprocess.run(
                        ['pdf2svg', pdf_path, svg_path],
                        cwd=tmpdir, capture_output=True, timeout=10
                    )
                    if os.path.exists(svg_path):
                        svg_content = open(svg_path).read()
                        self._json_response({'ok': True, 'svg': svg_content})
                        return

                # Try dvisvgm
                if shutil.which('dvisvgm'):
                    subprocess.run(
                        ['dvisvgm', '--pdf', pdf_path, '-o', svg_path],
                        cwd=tmpdir, capture_output=True, timeout=10
                    )
                    if os.path.exists(svg_path):
                        svg_content = open(svg_path).read()
                        self._json_response({'ok': True, 'svg': svg_content})
                        return

                # Fallback: return PNG via pdftoppm or convert
                import base64
                png_path = os.path.join(tmpdir, 'output.png')
                if shutil.which('pdftoppm'):
                    subprocess.run(
                        ['pdftoppm', '-png', '-r', '200', '-singlefile',
                         pdf_path, os.path.join(tmpdir, 'output')],
                        cwd=tmpdir, capture_output=True, timeout=10
                    )
                    if os.path.exists(png_path):
                        with open(png_path, 'rb') as pf:
                            png_b64 = base64.b64encode(pf.read()).decode()
                        self._json_response({'ok': True, 'png_base64': png_b64})
                        return

                # Last resort: return PDF path
                self._json_response({
                    'ok': False,
                    'error': 'PDF compiled but no SVG/PNG converter found. Install pdf2svg or poppler-utils.'
                }, 500)

        except subprocess.TimeoutExpired:
            self._json_response({'ok': False, 'error': 'Compilation timed out'}, 500)
        except Exception as e:
            self._json_response({'ok': False, 'error': str(e)}, 500)


def main():
    parser = argparse.ArgumentParser(description='Knit Editor development server')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()

    os.chdir(PROJECT_DIR)

    server = http.server.HTTPServer(('', args.port), KnitHandler)
    print(f"Knit Editor server running at http://localhost:{args.port}/knit_editor.html")
    print(f"TikZ saves go to {SAVE_DIR}/")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()


if __name__ == '__main__':
    main()
