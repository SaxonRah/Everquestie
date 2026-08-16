from __future__ import annotations


_TRAVEL_OUTPUT_UI_MARKER = "_everquestie_travel_output_ui"


def _children(widget) -> list:
    try:
        return list(widget.winfo_children())
    except Exception:
        return []


def _walk(widget):
    stack = [widget]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(_children(current)))


def _configure_text(root, old: str, new: str) -> int:
    changed = 0
    for widget in _walk(root):
        try:
            if str(widget.cget("text")) != old:
                continue
            widget.configure(text=new)
            changed += 1
        except Exception:
            continue
    return changed


def _bind_from_enter(frame) -> None:
    """Make Enter in From route when a destination is already present."""
    wanted = str(frame.from_var)
    for widget in _walk(frame):
        try:
            if str(widget.cget("textvariable")) != wanted:
                continue
        except Exception:
            continue

        def _enter(_event=None, owner=frame):
            if owner.to_var.get().strip():
                owner.find_route()
            else:
                owner.show_zone_context()
            return "break"

        try:
            widget.bind("<Return>", _enter)
        except Exception:
            pass
        return


def _result_prefix(frame) -> str:
    mode = getattr(frame, "_everquestie_result_mode", "")
    source = frame.from_var.get().strip()
    target = frame.to_var.get().strip()
    if mode == "route":
        return f"ROUTE RESULT | {source or '?'} → {target or '?'}"
    if mode == "zone":
        return f"SOURCE ZONE CONTEXT | {source or '?'}"
    if mode == "nearby":
        return f"NEARBY CONFIRMED POINTS | {source or '?'}"
    if mode == "dashboard":
        return f"CURRENT ZONE DASHBOARD | {source or '?'}"
    if mode == "pending_route":
        return f"ROUTE REQUEST PENDING | {source or '?'} → {target or '?'}"
    return ""


def install_travel_output_ui() -> None:
    """Keep route requests visually distinct from source-zone information."""
    from .route_guidance_ui import RouteGuidanceFrame

    current_build = RouteGuidanceFrame._build
    if getattr(current_build, _TRAVEL_OUTPUT_UI_MARKER, False):
        return

    current_set_result = RouteGuidanceFrame._set_result
    current_show_zone = RouteGuidanceFrame.show_zone_context
    current_find_route = RouteGuidanceFrame.find_route
    current_show_nearby = RouteGuidanceFrame.show_nearby
    current_dashboard = RouteGuidanceFrame.show_current_zone_dashboard

    def _set_result(self, text: str) -> None:
        prefix = _result_prefix(self)
        payload = f"{prefix}\n\n{text}" if prefix else text
        current_set_result(self, payload)

    def _route_endpoint_changed(self, *_args) -> None:
        if not hasattr(self, "result_text"):
            return
        target = self.to_var.get().strip()
        if not target:
            return
        mode = getattr(self, "_everquestie_result_mode", "")
        if mode not in {"route", "zone", "pending_route"}:
            return
        self._everquestie_result_mode = "pending_route"
        source = self.from_var.get().strip() or "?"
        current_set_result(
            self,
            f"ROUTE REQUEST PENDING | {source} → {target}\n\n"
            "Press Find route, or press Enter while either route field is focused.",
        )
        try:
            self.status_var.set(
                "Route request changed; the previous route/zone output was cleared. Press Find route."
            )
        except Exception:
            pass

    def _build(self) -> None:
        self._everquestie_result_mode = ""
        current_build(self)
        _configure_text(self, "Show zone", "Show From zone")
        _configure_text(self, "Canonical navigation knowledge", "Travel result / zone context")
        _bind_from_enter(self)
        try:
            self.to_var.trace_add("write", self._everquestie_route_endpoint_trace)
            self.from_var.trace_add("write", self._everquestie_route_endpoint_trace)
        except Exception:
            pass

    def _show_zone_context(self) -> None:
        self._everquestie_result_mode = "zone"
        current_show_zone(self)
        target = self.to_var.get().strip()
        if target:
            try:
                self.status_var.set(
                    f"Source-zone context shown for {self.from_var.get().strip()}; "
                    f"destination {target} has not been routed. Press Find route."
                )
            except Exception:
                pass

    def _find_route(self) -> None:
        self._everquestie_result_mode = "route"
        current_find_route(self)

    def _show_nearby(self) -> None:
        self._everquestie_result_mode = "nearby"
        current_show_nearby(self)

    def _show_current_zone_dashboard(self) -> bool:
        self._everquestie_result_mode = "dashboard"
        return bool(current_dashboard(self))

    setattr(_build, _TRAVEL_OUTPUT_UI_MARKER, True)
    RouteGuidanceFrame._everquestie_route_endpoint_trace = _route_endpoint_changed
    RouteGuidanceFrame._set_result = _set_result
    RouteGuidanceFrame._build = _build
    RouteGuidanceFrame.show_zone_context = _show_zone_context
    RouteGuidanceFrame.find_route = _find_route
    RouteGuidanceFrame.show_nearby = _show_nearby
    RouteGuidanceFrame.show_current_zone_dashboard = _show_current_zone_dashboard
