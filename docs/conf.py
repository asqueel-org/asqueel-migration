"""Sphinx configuration for asqueel-migration documentation."""

import sys
from importlib import import_module
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Project information
project = "Asqueel Migration"
copyright = "2025-2026, Softwell S.r.l."
author = "Softwell S.r.l."
# Document the checked-out source even when an older wheel is installed.
release = import_module("asqueel_migration").__version__

# Extensions
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "myst_parser",
    "sphinxcontrib.mermaid",
]

# Templates
exclude_patterns = [
    "_build", "Thumbs.db", ".DS_Store",
    "legacy_test_alignment.md", "decisioni-e-ripartenza.md",
]

# HTML output
html_theme = "sphinx_rtd_theme"
html_title = "Asqueel Migration — Developer documentation"
html_logo = "../assets/branding/asqueel-migration-inverse.svg"
html_favicon = "../assets/branding/asqueel-monogram.svg"
html_static_path = ["_static"]
html_css_files = ["brand.css"]
html_theme_options = {
    "logo_only": True,
    "collapse_navigation": False,  # keep section tree visible on every page
    "navigation_depth": 3,
}

# Intersphinx
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
