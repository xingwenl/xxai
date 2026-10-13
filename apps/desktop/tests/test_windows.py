"""子应用窗口管理测试：去重聚焦、清理与子窗口判定（全部用替身，不真开窗口）。"""

from __future__ import annotations

from desktop_app.windows import CHILD_HEIGHT, CHILD_MIN_SIZE, CHILD_WIDTH, AppWindowManager, child_url


class FakeEvent:
    """pywebview Event 的最小替身：支持 `+=` 注册回调。"""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def emit(self) -> None:
        for handler in list(self.handlers):
            handler()


class FakeWindow:
    """pywebview Window 的最小替身：记录调用，并可模拟「已被用户关闭」。"""

    def __init__(self, title: str, **options) -> None:
        self.title = title
        self.options = options
        self.calls: list[str] = []
        self.closed_by_user = False

        class _Events:
            def __init__(self) -> None:
                self.closed = FakeEvent()

        self.events = _Events()

    def show(self) -> None:
        self.calls.append("show")

    def restore(self) -> None:
        if self.closed_by_user:
            # pywebview 里操作已销毁的窗口会抛错，这里如实模拟
            raise RuntimeError("window already closed")
        self.calls.append("restore")

    def destroy(self) -> None:
        if self.closed_by_user:
            raise RuntimeError("window already closed")
        self.calls.append("destroy")


def _manager() -> tuple[AppWindowManager, list[FakeWindow]]:
    created: list[FakeWindow] = []

    def create_window(title: str, **options) -> FakeWindow:
        window = FakeWindow(title, **options)
        created.append(window)
        return window

    return AppWindowManager(create_window=create_window), created


def test_child_url_puts_marker_before_hash() -> None:
    # child=1 必须在 hash 之前：hash 里的深链才是插件路由，标记不能混进去
    assert child_url("http://127.0.0.1:8765/", "hello-world") == "http://127.0.0.1:8765/?child=1#/app/hello-world"
    # 尾斜杠与需要转义的 id 都要处理
    assert child_url("http://127.0.0.1:8765", "a/b") == "http://127.0.0.1:8765/?child=1#/app/a%2Fb"


def test_open_creates_window_with_expected_options() -> None:
    manager, created = _manager()
    bridge = object()

    result = manager.open("hello-world", "http://127.0.0.1:8765/?child=1#/app/hello-world", "你好世界", js_api=bridge)

    assert result == {"opened": True, "reused": False}
    assert len(created) == 1
    window = created[0]
    assert window.title == "你好世界"
    assert window.options["js_api"] is bridge
    assert (window.options["width"], window.options["height"]) == (CHILD_WIDTH, CHILD_HEIGHT)
    assert window.options["min_size"] == CHILD_MIN_SIZE
    assert manager.app_ids == ["hello-world"]


def test_open_same_app_focuses_existing_window() -> None:
    manager, created = _manager()
    manager.open("hello-world", "u1", "你好世界")
    result = manager.open("hello-world", "u2", "你好世界")

    assert result == {"opened": True, "reused": True}
    assert len(created) == 1
    assert created[0].calls == ["restore", "show"]


def test_open_different_apps_get_separate_windows() -> None:
    manager, created = _manager()
    manager.open("a", "u-a", "A")
    manager.open("b", "u-b", "B")

    assert len(created) == 2
    assert manager.app_ids == ["a", "b"]


def test_open_recreates_when_previous_window_was_closed() -> None:
    manager, created = _manager()
    manager.open("hello-world", "u1", "你好世界")
    # 用户手动关掉了窗口，但 closed 回调还没跑到：复用时抛错，应重建而不是静默失败
    created[0].closed_by_user = True

    result = manager.open("hello-world", "u2", "你好世界")

    assert result == {"opened": True, "reused": False}
    assert len(created) == 2


def test_closed_event_drops_registry_entry() -> None:
    manager, created = _manager()
    manager.open("hello-world", "u", "你好世界")

    created[0].events.closed.emit()

    assert manager.app_ids == []
    # 摘除后再次打开会新建，而不是复用死引用
    manager.open("hello-world", "u", "你好世界")
    assert len(created) == 2


def test_is_child_distinguishes_master_window() -> None:
    manager, created = _manager()
    manager.open("hello-world", "u", "你好世界")
    master = FakeWindow("WW 桌面应用")

    assert manager.is_child(created[0]) is True
    assert manager.is_child(master) is False
    # 主窗口传进来必须原样拒绝，否则前端在主窗口按 Esc 会把主窗口关掉
    assert manager.close(master) is False
    assert manager.app_ids == ["hello-world"]


def test_close_child_removes_and_destroys() -> None:
    manager, created = _manager()
    manager.open("hello-world", "u", "你好世界")

    assert manager.close(created[0]) is True
    assert manager.app_ids == []
    assert created[0].calls == ["destroy"]


def test_close_all_survives_already_closed_window() -> None:
    manager, created = _manager()
    manager.open("a", "u-a", "A")
    manager.open("b", "u-b", "B")
    created[0].closed_by_user = True

    assert manager.close_all() == 1
    assert manager.app_ids == []


def test_close_all_on_empty_registry_is_noop() -> None:
    manager, _ = _manager()
    assert manager.close_all() == 0
