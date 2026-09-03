from open_webui.utils.tool_parallel import (
    DEPENDS_ON_PARAM,
    execution_waves,
    inject_depends_on_spec,
    parse_depends_on,
    strip_depends_on,
)


def test_strip_depends_on_pulls_reserved_param():
    params, deps = strip_depends_on(
        {"argv": ["--out", "a.zarr"], "depends_on": ["fetch_chirps", "fetch_chirps"]}
    )
    assert params == {"argv": ["--out", "a.zarr"]}
    assert deps == ["fetch_chirps"]


def test_parse_depends_on_accepts_string():
    assert parse_depends_on("call_1") == ["call_1"]


def test_inject_depends_on_spec_is_idempotent():
    spec = {"name": "plot", "parameters": {"type": "object", "properties": {}}}
    inject_depends_on_spec(spec)
    inject_depends_on_spec(spec)
    assert DEPENDS_ON_PARAM in spec["parameters"]["properties"]


def test_all_independent_calls_are_one_wave():
    waves = execution_waves(
        ["a", "b", "c"],
        ["fetch_a", "fetch_b", "fetch_c"],
        [[], [], []],
    )
    assert waves == [[0, 1, 2]]


def test_name_dependency_splits_waves():
    waves = execution_waves(
        ["c1", "c2"],
        ["fetch", "plot"],
        [[], ["fetch"]],
    )
    assert waves == [[0], [1]]


def test_id_dependency_splits_waves():
    waves = execution_waves(
        ["call_a", "call_b"],
        ["fetch", "plot"],
        [[], ["call_a"]],
    )
    assert waves == [[0], [1]]


def test_unknown_dependency_is_ignored():
    waves = execution_waves(
        ["a", "b"],
        ["fetch", "plot"],
        [["prior_turn_tool"], []],
    )
    assert waves == [[0, 1]]


def test_cycle_falls_back_to_one_wave():
    waves = execution_waves(
        ["a", "b"],
        ["one", "two"],
        [["two"], ["one"]],
    )
    assert waves == [[0, 1]]
