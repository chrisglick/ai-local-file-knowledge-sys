"""Vendored OKF visualizer — render an OKF bundle to a self-contained HTML graph.
Usage: python render.py <bundle_dir> <out.html> [bundle_name]
Deps: pyyaml only. Viewer code vendored from GoogleCloudPlatform/knowledge-catalog okf.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from enrichment_agent.viewer.generator import generate_visualization

if __name__ == "__main__":
    bundle = Path(sys.argv[1])
    out = Path(sys.argv[2])
    name = sys.argv[3] if len(sys.argv) > 3 else None
    stats = generate_visualization(bundle, out, bundle_name=name)
    print(f"concepts={stats['concepts']} edges={stats['edges']} bytes={stats['bytes']} -> {out}")
