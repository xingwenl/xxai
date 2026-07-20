from app.shared.pagination import PageResponse, PaginationParams, build_page_data, build_pagination_meta


def test_pagination_params_calculate_offset_and_limit() -> None:
    params = PaginationParams(page=3, page_size=10)

    assert params.offset == 20
    assert params.limit == 10


def test_build_pagination_meta() -> None:
    params = PaginationParams(page=2, page_size=20)
    meta = build_pagination_meta(params, total=95)

    assert meta.page == 2
    assert meta.page_size == 20
    assert meta.total == 95
    assert meta.total_pages == 5


def test_build_page_data() -> None:
    params = PaginationParams(page=2, page_size=20)
    page_data = build_page_data(items=[{"id": 1}], params=params, total=95)

    assert page_data.page_no == 2
    assert page_data.page_size == 20
    assert page_data.items == [{"id": 1}]
    assert page_data.total == 95
    assert page_data.pages == 5


def test_page_response_uses_expected_envelope() -> None:
    params = PaginationParams(page=1, page_size=10)
    payload = build_page_data(items=[], params=params, total=0)
    response = PageResponse(data=payload)

    assert response.code == 200
    assert response.message == "操作成功"
    assert response.data.page_no == 1
