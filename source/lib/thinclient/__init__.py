"""Thin-client search stack (no JVM): the serving engines behind ``SFU_SEARCH_BACKEND=thinclient``.

The package root re-exports nothing; import the submodule you need, e.g.
``from lib.thinclient.retriever import ThinClientRetriever``. The engines,
index layout, env gates and the serving path are documented in
docs/THIN_CLIENT_SWAP.md (canonical current-architecture doc).
"""
