from pathlib import Path
from adrgraph.extractors import EXTRACTORS
from adrgraph.extractors.terraform import extract


def test_symbols_and_refs():
    e = extract("main.tf", Path("tests/fixtures/tf/main.tf").read_bytes(), "main.tf")
    assert EXTRACTORS[".tf"] is extract
    assert e.units[0].lang == "terraform"
    assert {(s.name, s.kind) for s in e.symbols} == {
        ("var.name", "variable"), ("local.suffix", "variable"), ("aws_s3_bucket.logs", "resource"),
        ("aws_s3_bucket.orphan", "resource"), ("aws_s3_bucket_policy.p", "resource"),
        ("data.aws_iam_policy_document.doc", "resource"), ("module.net", "module_call"), ("output.vpc", "variable")}
    refs = {(r.src_id.split("::")[1], r.name) for r in e.refs}
    assert refs == {("aws_s3_bucket.logs", "var.name"), ("aws_s3_bucket.logs", "local.suffix"),
                    ("aws_s3_bucket_policy.p", "aws_s3_bucket.logs"),
                    ("aws_s3_bucket_policy.p", "data.aws_iam_policy_document.doc"), ("output.vpc", "module.net")}
    assert all(not r.call for r in e.refs)
    logs = next(s for s in e.symbols if s.name == "aws_s3_bucket.logs")
    assert logs.line == 5 and logs.id == "main.tf::aws_s3_bucket.logs"


def test_scan_resolves_terraform_refs(monkeypatch):
    from adrgraph.scan import scan
    monkeypatch.chdir("tests/fixtures/tf")
    e = {(d.label, d.src, d.dst) for d in scan(["."]).edges}
    assert ("REFERENCES", "main.tf::aws_s3_bucket_policy.p", "main.tf::aws_s3_bucket.logs") in e
    assert ("REFERENCES", "main.tf::output.vpc", "main.tf::module.net") in e
