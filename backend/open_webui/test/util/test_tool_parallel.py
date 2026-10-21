from open_webui.utils.tool_parallel import (
    ACTIVITY_PARAM,
    DEPENDS_ON_PARAM,
    DISPLAY_PARAM,
    execution_waves,
    inject_depends_on_spec,
    parse_depends_on,
    strip_depends_on,
    strip_display,
    with_implicit_depends_on,
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
    assert DISPLAY_PARAM in spec["parameters"]["properties"]
    assert ACTIVITY_PARAM in spec["parameters"]["properties"]


def test_strip_display_removes_phrase_and_keeps_args():
    params = strip_display(
        {
            "argv": ["--out", "a.zarr"],
            "display": "Grouping the data into weekly bins",
            "activity": "Fetching IMERG and clipping to Kenya",
        }
    )
    assert params == {"argv": ["--out", "a.zarr"]}


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


def test_cycle_falls_back_to_serial_waves():
    waves = execution_waves(
        ["a", "b"],
        ["one", "two"],
        [["two"], ["one"]],
    )
    assert waves == [[0], [1]]


def test_repeated_tool_name_resolves_to_earlier_call():
    # The chain from a real chat: two selects, each later step depending on the
    # previous step by name. Matching every select made a false cycle, and the
    # cycle fallback ran the last five steps at once.
    names = [
        "convert_to_totals",
        "select",
        "label_group",
        "summarize_dim",
        "edit_coords",
        "select",
        "inspect_zarr",
    ]
    deps = [
        [],
        ["convert_to_totals"],
        ["select"],
        ["label_group"],
        ["summarize_dim"],
        ["edit_coords"],
        ["select"],
    ]
    waves = execution_waves([""] * len(names), names, deps)
    assert waves == [[0], [1], [2], [3], [4], [5], [6]]


def test_display_image_waits_for_every_earlier_plot():
    names = ["plot", "plot", "display_image"]
    deps = with_implicit_depends_on(names, [[], [], []])
    waves = execution_waves(["a", "b", "c"], names, deps)
    assert waves == [[0, 1], [2]]


def test_display_image_waits_for_sibling_skills():
    names = ["plot", "display_image", "clip"]
    deps = with_implicit_depends_on(names, [[], [], []])
    assert deps[1] == ["plot", "clip"]
    assert deps[0] == []
    assert deps[2] == []
    waves = execution_waves(["a", "b", "c"], names, deps)
    assert waves == [[0, 2], [1]]


def test_read_artifact_waits_for_sibling_skills():
    names = ["plot", "read_artifact"]
    deps = with_implicit_depends_on(names, [[], []])
    assert deps[1] == ["plot"]
    waves = execution_waves(["a", "b"], names, deps)
    assert waves == [[0], [1]]


def test_display_image_alone_stays_one_wave():
    names = ["display_image"]
    deps = with_implicit_depends_on(names, [[]])
    assert deps == [[]]
    assert execution_waves(["a"], names, deps) == [[0]]
