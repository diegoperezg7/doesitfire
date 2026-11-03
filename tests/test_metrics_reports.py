import json
import xml.etree.ElementTree as ET

from conftest import make_results, trial

from doesitfire.html import render_html
from doesitfire.metrics import check_thresholds, overall, summarize
from doesitfire.report import badge_endpoint, badge_svg, print_matrix, write_junit


def test_summary_math(sample_results):
    s = summarize(sample_results)
    c = s["cells"]["claude-code|commit-message"]
    assert (c["true_fires"], c["fire_runs"], c["false_fires"], c["nofire_runs"]) == (1, 2, 1, 2)
    assert c["recall"] == 0.5 and c["false_fire_rate"] == 0.5 and c["precision"] == 0.5
    r = s["cells"]["claude-code|regex-explainer"]
    assert r["errors"] == 1 and r["nofire_runs"] == 0 and r["false_fire_rate"] is None
    codex = s["cells"]["codex|commit-message"]
    assert codex["prompts"][1]["other"] == ["regex-explainer"]
    assert s["totals"]["codex"]["recall"] == 0.5


def test_overall_and_thresholds(sample_results):
    s = summarize(sample_results)
    o = overall(s)
    assert round(o["recall"], 3) == 0.6  # 3 of 5 should-fire runs
    fails = check_thresholds(s, min_recall=0.8, max_false_fire=0.2)
    assert any("recall 50% < 80%" in f for f in fails)
    assert any("false-fire rate 50% > 20%" in f for f in fails)
    assert check_thresholds(s, None, None) == []


def test_junit_is_valid(sample_results, tmp_path):
    p = tmp_path / "junit.xml"
    write_junit(sample_results, p)
    root = ET.parse(p).getroot()
    assert root.tag == "testsuites"
    assert int(root.get("tests")) == 10  # unique agent x skill x prompt rows
    assert int(root.get("errors")) == 1
    assert int(root.get("failures")) >= 1


def test_badges(sample_results):
    svg = badge_svg(sample_results)
    ET.fromstring(svg)
    assert "fires 60%" in svg
    ep = badge_endpoint(sample_results)
    assert ep["schemaVersion"] == 1 and ep["color"] == "a45e00"


def test_html_embeds_data_safely(tmp_path):
    results = make_results([trial("claude-code", "commit-message", "fire", True, prompt="</script><b>x</b>")])
    html = render_html(results)
    assert "__DOESITFIRE_DATA__" not in html
    assert "</script><b>" not in html
    payload = html.split('id="data">', 1)[1].split("</script>", 1)[0]
    data = json.loads(payload)
    assert data["summary"]["cells"]["claude-code|commit-message"]["true_fires"] == 1


def test_terminal_matrix(sample_results, capsys):
    from rich.console import Console

    console = Console(width=160, force_terminal=False)
    sample_results["recorded"] = True
    print_matrix(sample_results, console)
    out = capsys.readouterr().out
    assert "RECORDED" in out and "fires 1/2" in out and "experimental" in out
