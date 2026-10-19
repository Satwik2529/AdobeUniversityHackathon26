"""Imported first by every test module to put nlp-query-intelligence/ (the
package root for `lib`) on sys.path, without relying on the package being
installed."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
