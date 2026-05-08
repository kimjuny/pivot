"""Channel provider registry seed.

Built-in channel providers have been retired in favour of extension-backed
providers.  This module retains the ``BUILTIN_PROVIDERS`` export (empty) so
that ``provider_registry_service.py`` and ``registry.py`` can continue to
import it without ``ImportError`` during the migration window.
"""

BUILTIN_PROVIDERS: dict = {}
