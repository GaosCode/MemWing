from pathlib import Path


def test_add_memory_button_opens_local_dialog_from_click() -> None:
    source = Path("frontend/src/features/library/LibraryPage.tsx").read_text()
    button_start = source.index('className="button button--primary"')
    button_end = source.index("新增记忆", button_start)
    button_source = source[button_start:button_end]

    assert "const [memoryComposerOpen, setMemoryComposerOpen] = useState(false)" in source
    assert "onClick={() => setMemoryComposerOpen(true)}" in button_source
    assert "onPointerUp" not in button_source
    assert "onPointerDown" not in button_source
    assert "<AddMemoryDialog" in source
    assert "open={memoryComposerOpen}" in source


def test_manual_memory_client_uses_control_plane_create_route() -> None:
    source = Path("frontend/src/shared/api/controlPlaneClient.ts").read_text()

    assert "/v1/control/memories/manual" in source
    assert "/v1/openclaw/events/ingest" not in source
