from __future__ import annotations


def chain_activity_pathways_refresh(
    app_cls,
    extension,
    *,
    pass_force: bool = True,
) -> None:
    """Append one projection refresh after the composed Activity Pathways refresh.

    The previously installed refresh always runs first. Install order therefore remains
    the execution order. ``pass_force=False`` supports projections whose refresh method
    intentionally has no force parameter.
    """
    previous = app_cls._refresh_activity_pathways

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        previous(self, force=force)
        if pass_force:
            extension(self, force=force)
        else:
            extension(self)

    app_cls._refresh_activity_pathways = _refresh_activity_pathways
