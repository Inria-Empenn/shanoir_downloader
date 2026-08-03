# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Shanoir Downloader'
author = 'Shanoir developer team'
release = '0.0.0' # TODO: parse github tag

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration
# root_doc='contents/README'
extensions = ['myst_parser', "sphinx_design"]
myst_enable_extensions = [
    "colon_fence",  # Enables ::: block syntax
    "tasklist" # Enables task list - []
]
# sphinxemoji_style = 'twemoji'
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_book_theme'
html_static_path = ['_static']
# html_css_files = ["theme.css"]
html_sourcelink_suffix = ".md" # our sources are in markdown; but this only has an effect if "use_download_button": True
# html_favicon = "_static/favicon_dark.png"
html_theme_options = {
    "toc_title": "Page Contents",
    "search_bar_text": "Search...",
    "repository_branch": "main",
    "use_fullscreen_button": True,
    "use_source_button": True,
    "use_edit_page_button": True,
    "use_download_button": False,
    "use_issues_button": True,
    "use_repository_button": True,
    "default_mode": "light",
    "repository_provider": "github",
    "repository_url": "https://github.com/empenn/username.github.io"
}
