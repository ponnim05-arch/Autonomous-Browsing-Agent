import sys
from pathlib import Path

# Ensure 'src' is in sys.path for all pytest test collection and execution
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Starlette compatibility shim for FastAPI when Starlette >= 1.0 or newer
try:
    import starlette.routing
    _orig_router_init = starlette.routing.Router.__init__
    def _patched_router_init(self, *args, **kwargs):
        kwargs.pop("on_startup", None)
        kwargs.pop("on_shutdown", None)
        return _orig_router_init(self, *args, **kwargs)
    starlette.routing.Router.__init__ = _patched_router_init
    if not hasattr(starlette.routing.Router, "add_event_handler"):
        starlette.routing.Router.add_event_handler = lambda self, event_type, func: None
except Exception:
    pass
