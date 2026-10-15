"""Local CLI and compatibility import for the canonical API application."""
if __name__ == '__main__':
    import runpy
    runpy.run_module('api.index', run_name='__main__')
else:
    import sys
    from api import index
    sys.modules[__name__] = index
